"""Twitch Drops Miner status query cog — /miner slash command + notifier_loop.

Reads HTTP API of rangermix miner (no socket.io). The /miner command does a
one-shot fetch and replies ephemerally. The notifier_loop runs every 60s in
the background, polling /api/campaigns per twitch_links row, and pushes a
channel message + @user mention when the top in-progress drop_id changes.
"""
from __future__ import annotations
import asyncio
import logging
from datetime import datetime, timezone
from urllib.parse import urlsplit

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands, tasks

from config import TWITCH_MINERS
from database import LinkState

logger = logging.getLogger(__name__)

HTTP_TIMEOUT_SECONDS = 5
NOTIFIER_LOOP_SECONDS = 60


def compute_top_drop(campaigns_data: dict) -> dict | None:
    """Return top in-progress drop (highest progress) or None.

    Returned dict contains: id, drop_name, game, campaign,
    current_min, required_min, progress (float 0.0-1.0).

    Caller semantics (spec §9, D12):
    - None means no in-progress drop; caller MUST keep db's last_top_drop_id
      unchanged. idle-pause-resume becomes "switch" via the next non-None tick.
    - Non-None with id != db last_top_drop_id is a switch. Covers both
      old-completed→new-started and old-campaign-expired→new-started.

    Drops with falsy id are skipped to avoid set_last_top_drop(None) wiping
    the row back to bootstrap state.
    """
    campaigns = campaigns_data.get("campaigns", []) or []
    in_progress: list[dict] = []
    for c in campaigns:
        if not (c.get("linked") and c.get("active")):
            continue
        for d in c.get("drops", []) or []:
            drop_id = d.get("id")
            if not drop_id:
                continue
            if (d.get("current_minutes") or 0) > 0 and not d.get("is_claimed"):
                in_progress.append({
                    "id": drop_id,
                    "drop_name": d.get("name") or "?",
                    "game": c.get("game_name") or "?",
                    "campaign": c.get("name") or "?",
                    "current_min": d.get("current_minutes") or 0,
                    "required_min": d.get("required_minutes") or 0,
                    "progress": float(d.get("progress") or 0.0),
                })
    if not in_progress:
        return None
    in_progress.sort(key=lambda x: x["progress"], reverse=True)
    return in_progress[0]


def _usable_image_url(value: object) -> str | None:
    """Return value as a clean http(s) URL Discord can render, else None.

    Discord rejects an embed whose image url is not a well-formed http(s) URL
    with 50035 (Invalid Form Body), which fails the WHOLE message. We validate
    scheme + host and reject embedded whitespace so a garbage/drifted url
    degrades to "no thumbnail" instead of a dropped notification. Twitch CDN
    always returns clean https; this guards against miner payload drift, not
    adversarial input. (Discord also accepts attachment:// — out of scope, our
    only source is the CDN.)
    """
    if not isinstance(value, str):
        return None
    url = value.strip()
    if not url or any(ch.isspace() for ch in url):
        return None
    try:
        parts = urlsplit(url)
    except ValueError:  # e.g. "https://[bad" (unterminated IPv6) raises
        return None
    if parts.scheme in ("http", "https") and parts.netloc:
        return url
    return None


def _benefit_image_url(drop: dict) -> str | None:
    """First usable benefit image URL of a drop, else None.

    Defensive against miner payload shape drift (benefits not a list, an item
    not a dict) so a cosmetic thumbnail can never crash the embed build.
    """
    benefits = drop.get("benefits")
    if not isinstance(benefits, list):
        return None
    for b in benefits:
        if isinstance(b, dict):
            url = _usable_image_url(b.get("image_url"))
            if url:
                return url
    return None


class MinerCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._session: aiohttp.ClientSession | None = None

    async def cog_load(self) -> None:
        self._session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=HTTP_TIMEOUT_SECONDS)
        )
        self.notifier_loop.start()

    async def cog_unload(self) -> None:
        # Shutdown order (codex round-2 note 3):
        # 1. cancel the loop so no new iteration starts
        # 2. close the session AFTER any running tick has bailed out
        #    (running tick checks self._session.closed at the top of _process_link)
        # 3. null out _session so a leftover reference cannot accidentally be used
        self.notifier_loop.cancel()
        if self._session is not None:
            await self._session.close()
            self._session = None

    @app_commands.command(
        name="miner",
        description="查看你绑定的 Twitch 账号对应 miner 的实时状态",
    )
    @app_commands.guild_only()
    async def miner(self, interaction: discord.Interaction) -> None:
        # Defer FIRST (always within 3s window). Then do I/O. Use followup to reply.
        # Prevents discord.errors.HTTPException 40060 "Interaction has already been
        # acknowledged" from any race / latency between cmd dispatch and our response.
        await interaction.response.defer(ephemeral=True, thinking=True)

        # 1. Resolve bound twitch user from DB
        link = await self.bot.db.get_twitch_link(
            str(interaction.user.id),
            str(interaction.guild_id),
        )
        if link is None:
            await interaction.followup.send(
                "你还没绑定 Twitch 账号。先跑 `/twitch link <username>`。",
                ephemeral=True,
            )
            return

        canonical = link["twitch_user"]
        # Refresh last_interaction_channel_id every /miner call so notifications
        # follow the user to whichever channel they last interacted in.
        await self.bot.db.set_last_interaction_channel(
            str(interaction.user.id),
            str(interaction.guild_id),
            str(interaction.channel_id),
        )
        miner_info = TWITCH_MINERS.get(canonical)
        if miner_info is None:
            await interaction.followup.send(
                f"Twitch 账号 `{canonical}` 当前没有 miner 在跑。"
                " 需要 operator 先在 Pi 上起一个并加进 `TWITCH_MINERS`。",
                ephemeral=True,
            )
            return

        container, port = miner_info
        base_url = f"http://{container}:{port}"

        # 2. Concurrent fetch /api/status + /api/campaigns using the shared session.
        if self._session is None or self._session.closed:
            # cog is being unloaded — bail
            await interaction.followup.send(
                "bot 正在重启，30 秒后再试。",
                ephemeral=True,
            )
            return
        try:
            status_data, campaigns_data = await asyncio.gather(
                self._fetch_json(self._session, f"{base_url}/api/status"),
                self._fetch_json(self._session, f"{base_url}/api/campaigns"),
            )
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
            logger.info("miner %s unreachable/invalid: %s", canonical, e)
            await interaction.followup.send(
                f"miner `{canonical}` 暂时联系不上（容器可能在重启 / 网络问题）。"
                "30 秒后再试。",
                ephemeral=True,
            )
            return

        # 3. Build embed
        embed = self._build_embed(canonical, status_data, campaigns_data)
        await interaction.followup.send(embed=embed, ephemeral=True)

    async def _fetch_json(self, session: aiohttp.ClientSession, url: str) -> dict:
        async with session.get(url) as r:
            r.raise_for_status()
            return await r.json()

    def _build_embed(
        self,
        canonical: str,
        status_data: dict | None,
        campaigns_data: dict,
    ) -> discord.Embed:
        # status_data is None when called by notifier_loop._push_notification —
        # in that case we skip the status string entirely and show a fixed label.
        if status_data is None:
            status_text = ""
            is_logged_in = True   # in notifier path, miner is alive enough to return campaigns
        else:
            status_text = status_data.get("status", "(unknown)")
            login = status_data.get("login", {}) or {}
            login_status = (login.get("status") or "")
            is_logged_in = "已登录" in login_status or "logged" in login_status.lower()

        campaigns = campaigns_data.get("campaigns", []) or []
        linked_active = [
            c for c in campaigns
            if c.get("linked") and c.get("active")
        ]

        # Find drops with progress > 0 and not yet claimed.
        # Inline rather than reuse compute_top_drop because we need can_claim
        # field and the ordered list (for "Also in progress" section).
        in_progress = []
        for c in linked_active:
            for d in c.get("drops", []) or []:
                drop_id = d.get("id")
                if not drop_id:
                    continue
                if (d.get("current_minutes") or 0) > 0 and not d.get("is_claimed"):
                    in_progress.append({
                        "id": drop_id,
                        "game": c.get("game_name") or "?",
                        "campaign": c.get("name") or "?",
                        "drop_name": d.get("name") or "?",
                        "current_min": d.get("current_minutes") or 0,
                        "required_min": d.get("required_minutes") or 0,
                        "progress": float(d.get("progress") or 0.0),
                        "can_claim": bool(d.get("can_claim")),
                    })
        in_progress.sort(key=lambda x: x["progress"], reverse=True)

        # Decide status presentation
        if status_data is None:
            # notifier path: we know there's a top drop and miner is responsive
            emoji, status_label, color = "🟢", "正在挂宝", 0x9146FF
        else:
            is_watching = "正在观看" in status_text or "watching" in status_text.lower()
            if is_watching and in_progress:
                emoji, status_label, color = "🟢", "正在挂宝", 0x9146FF
            elif is_logged_in:
                emoji, status_label, color = "🟡", "空闲", 0xFFC107
            else:
                emoji, status_label, color = "🔴", "离线", 0xFF4444

        embed = discord.Embed(
            title=f"🎮 Twitch Drops Miner — {canonical}",
            color=color,
        )
        status_value = f"{emoji} {status_label}" + (f"\n{status_text}" if status_text else "")
        embed.add_field(
            name="状态",
            value=status_value,
            inline=False,
        )

        if in_progress:
            top = in_progress[0]
            bar_filled = max(0, min(12, int(top["progress"] * 12)))
            bar = "█" * bar_filled + "░" * (12 - bar_filled)
            embed.add_field(
                name="当前 Drop",
                value=f"**{top['drop_name']}** _(in {top['game']} — {top['campaign']})_",
                inline=False,
            )
            embed.add_field(
                name="进度",
                value=f"`{bar}` {top['current_min']}/{top['required_min']} min ({top['progress']*100:.0f}%)",
                inline=False,
            )
            if len(in_progress) > 1:
                others = "\n".join(
                    f"• **{d['drop_name']}** — {d['progress']*100:.0f}%"
                    for d in in_progress[1:4]
                )
                embed.add_field(name="同时在挂", value=others, inline=False)
        else:
            embed.add_field(
                name="当前 Drop",
                value="当前没有 drop 在挂",
                inline=False,
            )

        embed.add_field(
            name="可挂活动",
            value=f"{len(linked_active)}",
            inline=True,
        )
        embed.set_footer(
            text=f"来源:miner /api/* @ {datetime.now(timezone.utc).strftime('%H:%M:%S UTC')}"
        )
        return embed

    # ─────────────────────────────────────────────────────────────────
    # Background notifier loop (drop-switch push notifications)
    # ─────────────────────────────────────────────────────────────────

    @tasks.loop(seconds=NOTIFIER_LOOP_SECONDS)
    async def notifier_loop(self) -> None:
        links = await self.bot.db.iter_links_with_state()
        for link in links:
            try:
                await self._process_link(link)
            except asyncio.CancelledError:
                # cog_unload cancellation — let it propagate so the loop stops cleanly
                raise
            except Exception:
                # broad catch: per-link failures must NOT kill notifier_loop
                # (codex round-2 note 1: don't catch BaseException;
                # CancelledError above is the escape)
                logger.exception(
                    "notifier: unexpected failure for user=%s guild=%s twitch=%s",
                    link.discord_id, link.guild_id, link.twitch_user,
                )
                continue

    @notifier_loop.before_loop
    async def _notifier_wait_ready(self) -> None:
        await self.bot.wait_until_ready()

    @notifier_loop.error
    async def _on_error(self, exc: BaseException) -> None:
        # discord.py 2.x: this fires only when an exception escapes the loop body.
        # It is NOT auto-continue — the loop is now stopped until restart.
        # Per-link failures should be caught inside notifier_loop's for-loop;
        # this hook is a diagnostic of last resort.
        logger.exception(
            "notifier_loop FAILED (will stop until docker compose restart): %s", exc
        )

    async def _process_link(self, link: LinkState) -> None:
        # Codex round-2 note 2: guard against the session being closed mid-tick
        # by cog_unload.
        if self._session is None or self._session.closed:
            return

        miner = TWITCH_MINERS.get(link.twitch_user)
        if miner is None:
            return  # operator hasn't started a miner for this twitch user

        container, port = miner
        base_url = f"http://{container}:{port}"

        # — network layer —
        try:
            data = await self._fetch_json(self._session, f"{base_url}/api/campaigns")
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
            # ValueError covers json.JSONDecodeError when body is invalid JSON;
            # aiohttp.ContentTypeError is a ClientError subclass (already covered).
            logger.info("notifier: miner %s unreachable/invalid: %s", link.twitch_user, e)
            return

        # — data layer —
        try:
            top = compute_top_drop(data)
        except Exception as e:
            logger.error(
                "notifier: compute_top_drop failed for twitch=%s: %s",
                link.twitch_user, e,
            )
            return

        if top is None:
            # No in-progress drop. Per D12: preserve db's last_top_drop_id.
            # The next non-None top different from db will be a switch.
            return

        if top["id"] == link.last_top_drop_id:
            return  # no change

        # — notification decision —
        should_notify = (
            link.last_top_drop_id is not None  # silent bootstrap on NULL
            and link.last_interaction_channel_id  # dormant rows have no channel yet
        )
        if should_notify:
            await self._push_notification(link, top, data)

        # — db update —
        try:
            await self.bot.db.set_last_top_drop(
                link.discord_id, link.guild_id, top["id"]
            )
        except Exception as e:
            logger.error(
                "notifier: db.set_last_top_drop failed for user=%s guild=%s: %s",
                link.discord_id, link.guild_id, e,
            )

    async def _push_notification(
        self, link: LinkState, top: dict, data: dict
    ) -> None:
        try:
            channel_id_int = int(link.last_interaction_channel_id)
        except (TypeError, ValueError):
            logger.warning(
                "notifier: invalid channel_id=%r for user=%s; skip",
                link.last_interaction_channel_id, link.discord_id,
            )
            return
        channel = self.bot.get_channel(channel_id_int)
        if channel is None:
            logger.warning(
                "notifier: channel %s not found (deleted/bot kicked/thread archived) for user=%s guild=%s",
                link.last_interaction_channel_id, link.discord_id, link.guild_id,
            )
            return
        content = (
            f"<@{link.discord_id}> 切到新挂宝目标:**{top['drop_name']}** "
            f"_({top['game']} — {top['campaign']})_"
        )
        embed = self._build_embed(link.twitch_user, status_data=None, campaigns_data=data)
        try:
            await channel.send(content=content, embed=embed)
        except discord.Forbidden:
            logger.warning(
                "notifier: forbidden in channel=%s; skipping",
                link.last_interaction_channel_id,
            )
        except discord.NotFound:
            logger.warning(
                "notifier: channel/thread %s no longer exists; skipping",
                link.last_interaction_channel_id,
            )
        except discord.HTTPException as e:
            logger.warning(
                "notifier: discord HTTP error in channel=%s: %s",
                link.last_interaction_channel_id, e,
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MinerCog(bot))
