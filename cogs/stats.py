from __future__ import annotations
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from utils.embeds import build_stats_embed


class StatsCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="stats", description="查看玩家的 Overwatch 2 战绩数据")
    @app_commands.describe(member="要查询的服务器成员（留空则查询自己）")
    @app_commands.guild_only()
    async def stats(
        self,
        interaction: discord.Interaction,
        member: Optional[discord.Member] = None,
    ) -> None:
        await interaction.response.defer()
        target = member or interaction.user

        player = await self.bot.db.get_player(str(target.id), str(interaction.guild_id))
        if not player:
            who = "你" if target == interaction.user else target.mention
            await interaction.followup.send(
                embed=discord.Embed(
                    title="❌ 未注册",
                    description=f"{who} 还没有绑定主账号。\n使用 `/register <BattleTag>` 完成注册。",
                    color=0xFF4444,
                )
            )
            return

        summary = await self.bot.api.get_player_summary(player["battletag"])
        if summary is None:
            await interaction.followup.send(
                embed=discord.Embed(
                    title="⚠️ 数据获取失败",
                    description="当前无法连接到 Overwatch API，请稍后重试。",
                    color=0xFFAA00,
                )
            )
            return
        if summary.get("_private"):
            await interaction.followup.send(
                embed=discord.Embed(
                    title="🔒 主页设为私密",
                    description=f"`{player['battletag']}` 的主页设为私密，无法读取数据。",
                    color=0xFFAA00,
                )
            )
            return

        stats = await self.bot.api.get_player_stats(player["battletag"])
        await interaction.followup.send(embed=build_stats_embed(target, summary, stats))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(StatsCog(bot))
