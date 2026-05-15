"""Twitch Drops Miner status query cog — /miner slash command.

Reads HTTP API of rangermix miner (no socket.io). Each /miner invocation
hits /api/status and /api/campaigns on the configured miner, builds an
ephemeral Discord Embed with current status + progress.
"""
from __future__ import annotations
import asyncio
import logging
from datetime import datetime, timezone

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from config import TWITCH_MINERS

logger = logging.getLogger(__name__)

HTTP_TIMEOUT_SECONDS = 5


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


class MinerCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

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

        # 2. Concurrent fetch /api/status + /api/campaigns
        try:
            timeout = aiohttp.ClientTimeout(total=HTTP_TIMEOUT_SECONDS)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                status_data, campaigns_data = await asyncio.gather(
                    self._fetch_json(session, f"{base_url}/api/status"),
                    self._fetch_json(session, f"{base_url}/api/campaigns"),
                )
        except (aiohttp.ClientError, asyncio.TimeoutError) as e:
            logger.info("miner %s unreachable: %s", canonical, e)
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


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(MinerCog(bot))
