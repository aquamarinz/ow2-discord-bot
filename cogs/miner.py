"""Twitch Drops Miner status query cog — /miner slash command + notifier_loop.

Reads HTTP API of rangermix miner (no socket.io). The /miner command does a
one-shot fetch and replies ephemerally. The notifier_loop runs every 60s in
the background, polling /api/campaigns per twitch_links row, and pushes a
channel message + @user mention only for newly claimed drops and newly
started campaigns (no per-drop switch spam).
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


NOTIFY_CONTENT_BUDGET = 1800
DROPS_STATE_CAP = 2000
MINING_STATE_CAP = 500


def diff_tick(
    state: dict | None,
    payload: object,
) -> tuple[dict, list[dict], list[dict]] | None:
    """One notifier tick as a pure state transition.

    state:   {"drops": dict[str, bool], "mining": set[str]} or None (first tick).
    payload: raw /api/campaigns JSON (untrusted shape).

    Returns None when payload is invalid (caller must skip the tick and keep
    old state), else (new_state, claim_groups, campaign_events):
      claim_groups:    [{"campaign": str, "drops": [str], "done": bool,
                         "image_url": str | None}]
      campaign_events: [{"id": str, "campaign": str, "game": str,
                         "drop_count": int, "box_art_url": object,
                         "drops": [{"name", "required_minutes", "image_url"}]}]
    Both event lists are always [] when state is None (silent baseline).

    Semantics (spec §3.1/3.2): claim = seen-unclaimed→claimed transition,
    detected across ALL campaigns (no linked/active filter, so end-of-campaign
    claims still fire). "mining" is append-only: a campaign is announced at
    most once. Drop memory merges (absent entries retained) so partial or
    transiently-empty payloads never cause false or lost events.
    """
    if not isinstance(payload, dict) or not isinstance(payload.get("campaigns"), list):
        return None
    baseline = state is None
    prev_drops: dict[str, bool] = {} if baseline else state["drops"]
    prev_mining: set[str] = set() if baseline else state["mining"]

    cur_drops: dict[str, bool] = {}
    present_campaigns: set[str] = set()
    mining_candidates: set[str] = set()
    claim_groups: list[dict] = []
    campaign_events: list[dict] = []

    for c in payload["campaigns"]:
        if not isinstance(c, dict):
            continue
        cid = c.get("id")
        if not isinstance(cid, str) or not cid:
            continue
        present_campaigns.add(cid)
        drops = c.get("drops")
        if not isinstance(drops, list):
            drops = []
        newly_claimed: list[str] = []
        image_url: str | None = None
        n_valid = n_claimed = 0
        has_progress = False
        for d in drops:
            if not isinstance(d, dict):
                continue
            did = d.get("id")
            if not isinstance(did, str) or not did:
                continue
            n_valid += 1
            claimed = bool(d.get("is_claimed"))
            if claimed:
                n_claimed += 1
            minutes = d.get("current_minutes")
            if claimed or (isinstance(minutes, (int, float)) and minutes > 0):
                has_progress = True
            cur_drops[did] = claimed
            if claimed and prev_drops.get(did) is False:
                newly_claimed.append(d.get("name") or "?")
                if image_url is None:
                    image_url = _benefit_image_url(d)
        if newly_claimed:
            claim_groups.append({
                "campaign": c.get("name") or "?",
                "drops": newly_claimed,
                "done": n_valid > 0 and n_claimed == n_valid,
                "image_url": image_url,
            })
        if c.get("active") and has_progress:
            mining_candidates.add(cid)
            if cid not in prev_mining:
                event_drops: list[dict] = []
                for d in drops:
                    if not isinstance(d, dict):
                        continue
                    did = d.get("id")
                    if not isinstance(did, str) or not did:
                        continue
                    rm = d.get("required_minutes")
                    if isinstance(rm, bool) or not isinstance(rm, (int, float)) or rm < 0:
                        rm = None
                    event_drops.append({
                        "name": d.get("name") or "?",
                        "required_minutes": rm,
                        "image_url": _benefit_image_url(d),
                    })
                campaign_events.append({
                    "id": cid,
                    "campaign": c.get("name") or "?",
                    "game": c.get("game_name") or "?",
                    "drop_count": n_valid,
                    "box_art_url": c.get("game_box_art_url"),
                    "drops": event_drops,
                })

    merged_drops = {**prev_drops, **cur_drops}
    merged_mining = prev_mining | mining_candidates
    # Hygiene caps: unbounded growth is impossible in practice; sweep to
    # payload-present entries only when a cap is exceeded (spec §3.1).
    if len(merged_drops) > DROPS_STATE_CAP:
        merged_drops = dict(cur_drops)
    if len(merged_mining) > MINING_STATE_CAP:
        merged_mining = merged_mining & present_campaigns
    new_state = {"drops": merged_drops, "mining": merged_mining}
    if baseline:
        return new_state, [], []
    return new_state, claim_groups, campaign_events


def _fit_budget(content: str, total: int) -> str:
    """Clamp content to NOTIFY_CONTENT_BUDGET with a '…等 N 个' tail (§3.3)."""
    if len(content) <= NOTIFY_CONTENT_BUDGET:
        return content
    tail = f"…等 {total} 个"
    return content[:NOTIFY_CONTENT_BUDGET - len(tail)] + tail


def build_claim_message(discord_id: str, claim_groups: list[dict]) -> tuple[str, str | None]:
    """(content, image_url) for a 🎉 claim message.

    First campaign group sits inline after the colon (spec §3.5 template);
    additional campaigns get one line each.
    """
    total = 0
    group_lines = []
    for g in claim_groups:
        total += len(g["drops"])
        names = "、".join(f"**{n}**" for n in g["drops"])
        done = " ✅ 全部领完" if g["done"] else ""
        group_lines.append(f"{names} _({g['campaign']})_{done}")
    content = f"<@{discord_id}> 🎉 已领取掉宝:" + "\n".join(group_lines)
    image_url = next((g["image_url"] for g in claim_groups if g["image_url"]), None)
    return _fit_budget(content, total), image_url


def build_campaign_message(discord_id: str, campaign_events: list[dict]) -> str:
    """Content for a ⛏️ new-campaign message. All events joined on one line."""
    parts = "、".join(
        f"**{e['campaign']}** _({e['game']} · {e['drop_count']} 个掉宝)_"
        for e in campaign_events
    )
    return _fit_budget(
        f"<@{discord_id}> ⛏️ 开始挖新活动:{parts}", len(campaign_events)
    )


class MinerCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._session: aiohttp.ClientSession | None = None
        # (discord_id, guild_id, twitch_user) -> {"drops": dict, "mining": set}
        # In-memory only: restart re-baselines silently (spec §3.1).
        self._notify_state: dict[tuple[str, str, str], dict] = {}

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
        # Collect in-progress drops with can_claim and the ordered list
        # (for the "Also in progress" section).
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
                        "image_url": _benefit_image_url(d),
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
            if top.get("image_url"):
                embed.set_image(url=top["image_url"])
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
    # Background notifier loop (claim / new-campaign push notifications)
    # ─────────────────────────────────────────────────────────────────

    @tasks.loop(seconds=NOTIFIER_LOOP_SECONDS)
    async def notifier_loop(self) -> None:
        links = await self.bot.db.iter_links_with_state()
        live_keys = {
            (l.discord_id, l.guild_id, l.twitch_user) for l in links
        }
        for stale in set(self._notify_state) - live_keys:
            del self._notify_state[stale]
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
        # Guard against the session being closed mid-tick by cog_unload.
        if self._session is None or self._session.closed:
            return

        miner = TWITCH_MINERS.get(link.twitch_user)
        if miner is None:
            return  # operator hasn't started a miner for this twitch user

        container, port = miner
        base_url = f"http://{container}:{port}"

        try:
            data = await self._fetch_json(self._session, f"{base_url}/api/campaigns")
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as e:
            logger.info("notifier: miner %s unreachable/invalid: %s", link.twitch_user, e)
            return

        key = (link.discord_id, link.guild_id, link.twitch_user)
        result = diff_tick(self._notify_state.get(key), data)
        if result is None:
            # Malformed payload — treat like unreachable: keep old state.
            logger.info("notifier: miner %s returned malformed payload", link.twitch_user)
            return
        new_state, claim_groups, campaign_events = result
        self._notify_state[key] = new_state

        if not link.last_interaction_channel_id:
            return  # dormant row: keep the baseline fresh, never send
        if claim_groups:
            content, image_url = build_claim_message(link.discord_id, claim_groups)
            await self._push_notification(link, content, image_url)
        if campaign_events:
            await self._push_notification(
                link, build_campaign_message(link.discord_id, campaign_events), None
            )

    async def _push_notification(
        self, link: LinkState, content: str, image_url: str | None
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
        embed = None
        if image_url:
            embed = discord.Embed(color=0x9146FF)
            embed.set_image(url=image_url)
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
