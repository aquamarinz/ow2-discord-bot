from __future__ import annotations
from typing import Optional
import logging

import discord
from discord import app_commands
from discord.ext import commands

from utils.embeds import build_trends_embed

logger = logging.getLogger(__name__)


class TrendsCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ----------------------------------------------------------------- /trends
    @app_commands.command(name="trends", description="查看玩家最近的竞技段位与战绩走势")
    @app_commands.describe(member="要查询的成员（留空则查询自己）")
    async def trends(
        self,
        interaction: discord.Interaction,
        member: Optional[discord.Member] = None,
    ) -> None:
        await interaction.response.defer()

        target     = member or interaction.user
        guild_id   = str(interaction.guild_id)
        discord_id = str(target.id)

        player = await self.bot.db.get_player(discord_id, guild_id)
        if not player:
            await interaction.followup.send(
                embed=discord.Embed(
                    title="❌ 未注册",
                    description=(
                        f"{'你' if member is None else target.mention} 还没有绑定 Overwatch 账号。\n"
                        "使用 `/register <BattleTag>` 完成注册。"
                    ),
                    color=0xFF4444,
                )
            )
            return

        snapshots = await self.bot.db.get_trend_snapshots(discord_id, guild_id, limit=50)

        if len(snapshots) < 2:
            await interaction.followup.send(
                embed=discord.Embed(
                    title="📈 数据收集中",
                    description=(
                        "还没有足够的历史数据来显示趋势。\n"
                        "Bot 每 30 分钟自动记录一次快照，积累后即可查看走势。\n\n"
                        f"当前已收集 **{len(snapshots)}** 条，至少需要 **2** 条。"
                    ),
                    color=0x4488FF,
                )
            )
            return

        summary = await self.bot.api.get_player_summary(player["battletag"])
        await interaction.followup.send(
            embed=build_trends_embed(target, player["battletag"], snapshots, summary)
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TrendsCog(bot))
