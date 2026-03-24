from __future__ import annotations
from typing import Optional
"""
/streak [member] — current win/loss streak inferred from snapshot history
"""
import discord
from discord import app_commands
from discord.ext import commands

from utils.embeds import build_streak_embed


class StreakCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="streak", description="查看玩家近期连胜/连败情况")
    @app_commands.describe(member="要查看的成员（留空则查询自己）")
    async def streak(
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
                    description=f"{who}尚未绑定 Overwatch 账号。请先使用 `/register`。",
                    color=0xFF4444,
                ),
                ephemeral=True,
            )
            return

        snapshots = await self.bot.db.get_trend_snapshots(str(target.id), guild_id, limit=50)
        if len(snapshots) < 2:
            await interaction.followup.send(
                embed=discord.Embed(
                    title="📊 数据不足",
                    description=(
                        "快照数量不足，暂时无法统计连胜/连败。\n"
                        "Bot 每 30 分钟自动记录，积累后即可查看。"
                    ),
                    color=0xFFAA00,
                )
            )
            return

        game_results = _extract_game_results(snapshots)
        await interaction.followup.send(
            embed=build_streak_embed(target, rec["battletag"], game_results)
        )


def _extract_game_results(snapshots: list[dict]) -> list[str]:
    """
    Given periodic snapshots newest-first, derive an approximate W/L sequence.
    Within each snapshot interval the order is unknown; wins are listed before
    losses as a best-guess approximation.
    Returns a list of 'W'/'L' entries, newest-first, capped at 30.
    """
    results: list[str] = []
    for i in range(len(snapshots) - 1):
        newer    = snapshots[i]
        older    = snapshots[i + 1]
        d_played = max(0, (newer.get("games_played") or 0) - (older.get("games_played") or 0))
        d_won    = max(0, (newer.get("games_won")    or 0) - (older.get("games_won")    or 0))
        d_lost   = max(0, d_played - d_won)
        results.extend(["W"] * d_won + ["L"] * d_lost)
        if len(results) >= 30:
            break
    return results[:30]


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(StreakCog(bot))
