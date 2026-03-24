from __future__ import annotations
from typing import Optional
"""
/goal set/show/clear  — personal rank goals with progress tracking
/weekly setchannel/disable — configure weekly server war report
"""
import asyncio
import logging
from datetime import datetime, timedelta

import discord
from discord import app_commands
from discord.ext import commands, tasks

from config import RANK_ORDER, RANK_EMOJIS, ROLE_EMOJIS, ROLE_LABELS
from utils.embeds import build_goals_embed, build_weekly_report_embed

logger = logging.getLogger(__name__)

_DIVISIONS = [
    "Bronze", "Silver", "Gold", "Platinum",
    "Diamond", "Master", "Grandmaster", "Champion",
]


def _fmt_rank_str(division: str, tier: int) -> str:
    if not division or division == "Unranked":
        return "未定级"
    emoji = RANK_EMOJIS.get(division, "")
    if division in ("Grandmaster", "Champion"):
        return f"{emoji} {division}"
    return f"{emoji} {division} {tier}"


# ─────────────────────────────────────────────── /goal command group
class GoalGroup(app_commands.Group):
    def __init__(self, bot: commands.Bot) -> None:
        super().__init__(name="goal", description="设置和查看个人竞技段位目标")
        self.bot = bot

    @app_commands.command(name="set", description="设置某个角色的段位目标")
    @app_commands.describe(
        role="角色类型",
        division="目标段位",
        tier="目标级别 1（最高）~5（最低）；Grandmaster/Champion 忽略此项",
    )
    @app_commands.choices(
        role=[
            app_commands.Choice(name="🛡️ 坦克",  value="tank"),
            app_commands.Choice(name="⚔️ 输出",  value="damage"),
            app_commands.Choice(name="💚 辅助",  value="support"),
        ],
        division=[app_commands.Choice(name=d, value=d) for d in _DIVISIONS],
        tier=[
            app_commands.Choice(name="Tier 1（最高）", value=1),
            app_commands.Choice(name="Tier 2",         value=2),
            app_commands.Choice(name="Tier 3",         value=3),
            app_commands.Choice(name="Tier 4",         value=4),
            app_commands.Choice(name="Tier 5（最低）", value=5),
        ],
    )
    async def goal_set(
        self,
        interaction: discord.Interaction,
        role: str,
        division: str,
        tier: int = 5,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        guild_id   = str(interaction.guild_id)
        discord_id = str(interaction.user.id)

        rec = await self.bot.db.get_player(discord_id, guild_id)
        if not rec:
            await interaction.followup.send(
                embed=discord.Embed(
                    title="❌ 未注册",
                    description="请先使用 `/register` 绑定 Overwatch 账号。",
                    color=0xFF4444,
                ),
                ephemeral=True,
            )
            return

        # GM and Champion don't use tiers
        if division in ("Grandmaster", "Champion"):
            tier = 1

        await self.bot.db.set_goal(discord_id, guild_id, role, division, tier)

        role_label = ROLE_LABELS.get(role, role)
        rank_txt   = _fmt_rank_str(division, tier)
        await interaction.followup.send(
            embed=discord.Embed(
                title="🎯 目标已设置",
                description=f"{ROLE_EMOJIS.get(role, '')} **{role_label}** 目标: {rank_txt}",
                color=0x44FF88,
            ),
            ephemeral=True,
        )

    @app_commands.command(name="show", description="查看玩家的段位目标与当前进度")
    @app_commands.describe(member="要查看的成员（留空则查询自己）")
    async def goal_show(
        self,
        interaction: discord.Interaction,
        member: Optional[discord.Member] = None,
    ) -> None:
        await interaction.response.defer()

        target   = member or interaction.user
        guild_id = str(interaction.guild_id)

        rec = await self.bot.db.get_player(str(target.id), guild_id)
        if not rec:
            who = "你" if target == interaction.user else target.mention
            await interaction.followup.send(
                embed=discord.Embed(
                    title="❌ 未注册",
                    description=f"{who}尚未注册 Overwatch 账号。",
                    color=0xFF4444,
                ),
                ephemeral=True,
            )
            return

        goals   = await self.bot.db.get_goals(str(target.id), guild_id)
        summary = await self.bot.api.get_player_summary(rec["battletag"])

        current_comp: dict = {}
        if summary and not summary.get("_private"):
            current_comp = summary.get("competitive") or {}

        await interaction.followup.send(
            embed=build_goals_embed(target, rec["battletag"], goals, current_comp)
        )

    @app_commands.command(name="clear", description="清除某个角色的段位目标")
    @app_commands.describe(role="要清除目标的角色")
    @app_commands.choices(
        role=[
            app_commands.Choice(name="🛡️ 坦克",  value="tank"),
            app_commands.Choice(name="⚔️ 输出",  value="damage"),
            app_commands.Choice(name="💚 辅助",  value="support"),
        ],
    )
    async def goal_clear(
        self,
        interaction: discord.Interaction,
        role: str,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        guild_id   = str(interaction.guild_id)
        discord_id = str(interaction.user.id)
        removed    = await self.bot.db.delete_goal(discord_id, guild_id, role)
        role_label = ROLE_LABELS.get(role, role)

        if removed:
            await interaction.followup.send(
                embed=discord.Embed(
                    title="✅ 目标已清除",
                    description=f"**{role_label}** 的段位目标已删除。",
                    color=0x44FF88,
                ),
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                embed=discord.Embed(
                    title="ℹ️ 无目标",
                    description=f"**{role_label}** 没有设置过目标。",
                    color=0x4488FF,
                ),
                ephemeral=True,
            )


# ─────────────────────────────────────────────── /weekly command group
class WeeklyGroup(app_commands.Group):
    def __init__(self, bot: commands.Bot) -> None:
        super().__init__(name="weekly", description="配置服务器周报推送频道")
        self.bot = bot

    @app_commands.command(name="setchannel", description="设置周报推送频道（需要管理服务器权限）")
    @app_commands.describe(channel="用于接收每周战况汇报的文字频道")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def weekly_setchannel(
        self,
        interaction: discord.Interaction,
        channel: discord.TextChannel,
    ) -> None:
        await interaction.response.defer(ephemeral=True)
        await self.bot.db.set_weekly_channel(
            str(interaction.guild_id), str(channel.id), str(interaction.user.id)
        )
        await interaction.followup.send(
            embed=discord.Embed(
                title="✅ 周报频道已设置",
                description=(
                    f"每周一 UTC 00:00 将向 {channel.mention} 发送本周战况汇报。\n"
                    "使用 `/weekly disable` 可随时停用。"
                ),
                color=0x44FF88,
            ),
            ephemeral=True,
        )

    @app_commands.command(name="disable", description="停止向本服务器发送周报（需要管理服务器权限）")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def weekly_disable(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)
        await self.bot.db.disable_weekly_channel(str(interaction.guild_id))
        await interaction.followup.send(
            embed=discord.Embed(
                title="✅ 周报已停用",
                description="本服务器的周报推送已关闭。",
                color=0x44FF88,
            ),
            ephemeral=True,
        )


# ─────────────────────────────────────────────── Cog + weekly task
class GoalsCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot       = bot
        self._goal_grp   = GoalGroup(bot)
        self._weekly_grp = WeeklyGroup(bot)
        bot.tree.add_command(self._goal_grp)
        bot.tree.add_command(self._weekly_grp)
        self._weekly_task.start()

    async def cog_unload(self) -> None:
        self._weekly_task.cancel()
        self.bot.tree.remove_command("goal")
        self.bot.tree.remove_command("weekly")

    @tasks.loop(hours=24)
    async def _weekly_task(self) -> None:
        if datetime.utcnow().weekday() != 0:  # 0 = Monday
            return

        logger.info("Sending weekly reports…")
        channels = await self.bot.db.get_all_weekly_channels()
        for entry in channels:
            try:
                await self._send_weekly_report(
                    entry["guild_id"], int(entry["channel_id"])
                )
            except Exception as exc:
                logger.warning(
                    "Weekly report failed for guild %s: %s", entry["guild_id"], exc
                )
            await asyncio.sleep(1.0)

    @_weekly_task.before_loop
    async def _before_weekly(self) -> None:
        await self.bot.wait_until_ready()

    async def _send_weekly_report(self, guild_id: str, channel_id: int) -> None:
        guild = self.bot.get_guild(int(guild_id))
        if not guild:
            return
        channel = guild.get_channel(channel_id)
        if not channel:
            return

        players = await self.bot.db.get_all_players(guild_id)
        if not players:
            return

        since = (datetime.utcnow() - timedelta(days=7)).isoformat()
        player_data: list[dict] = []
        for p in players:
            snaps = await self.bot.db.get_snapshots_since(p["discord_id"], guild_id, since)
            player_data.append({
                "discord_id": p["discord_id"],
                "battletag":  p["battletag"],
                "snapshots":  snaps,
            })
            await asyncio.sleep(0.05)

        report = _build_weekly_data(player_data)
        embed  = build_weekly_report_embed(guild, report)
        await channel.send(embed=embed)
        logger.info("Weekly report sent to guild %s", guild_id)


# ─────────────────────────────────────────────── helpers
def _build_weekly_data(player_data: list[dict]) -> dict:
    total_games     = 0
    total_wins      = 0
    most_active:    dict | None = None
    most_active_g   = -1
    best_wr_player: dict | None = None
    best_wr_val     = -1.0
    worst_wr_player: dict | None = None
    worst_wr_val    = 101.0
    rank_changes:   list[dict] = []

    for pd in player_data:
        snaps = pd["snapshots"]  # newest-first
        if len(snaps) < 2:
            continue

        newest, oldest = snaps[0], snaps[-1]
        d_g = max(0, (newest.get("games_played") or 0) - (oldest.get("games_played") or 0))
        d_w = max(0, (newest.get("games_won")    or 0) - (oldest.get("games_won")    or 0))
        total_games += d_g
        total_wins  += d_w

        if d_g > most_active_g:
            most_active_g = d_g
            most_active   = {**pd, "games": d_g}

        if d_g >= 5:
            wr = d_w / d_g * 100
            if wr > best_wr_val:
                best_wr_val    = wr
                best_wr_player = {**pd, "wr": wr, "games": d_g}
            if wr < worst_wr_val:
                worst_wr_val    = wr
                worst_wr_player = {**pd, "wr": wr, "games": d_g}

        old_comp = oldest.get("competitive_data") or {}
        new_comp = newest.get("competitive_data") or {}
        changes  = _detect_rank_changes(old_comp, new_comp)
        if changes:
            rank_changes.append({**pd, "changes": changes})

    avg_wr = total_wins / total_games * 100 if total_games > 0 else 0.0
    return {
        "total_games":     total_games,
        "avg_wr":          avg_wr,
        "most_active":     most_active,
        "best_wr_player":  best_wr_player,
        "best_wr_val":     best_wr_val,
        "worst_wr_player": worst_wr_player,
        "worst_wr_val":    worst_wr_val,
        "rank_changes":    rank_changes,
    }


def _detect_rank_changes(old_comp: dict, new_comp: dict) -> list[str]:
    changes = []
    for role in ("tank", "damage", "support"):
        old_rd = old_comp.get(role)
        new_rd = new_comp.get(role)
        if not old_rd or not new_rd:
            continue
        old_div = old_rd.get("division", "Unranked")
        new_div = new_rd.get("division", "Unranked")
        old_t   = old_rd.get("tier", 5)
        new_t   = new_rd.get("tier", 5)
        old_score = RANK_ORDER.get(old_div, 0) * 10 + (6 - old_t)
        new_score = RANK_ORDER.get(new_div, 0) * 10 + (6 - new_t)
        if new_score > old_score:
            arrow = "⬆️"
        elif new_score < old_score:
            arrow = "⬇️"
        else:
            continue
        changes.append(
            f"{ROLE_EMOJIS.get(role, '')} "
            f"{_fmt_rank_str(old_div, old_t)} → {_fmt_rank_str(new_div, new_t)} {arrow}"
        )
    return changes


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(GoalsCog(bot))
