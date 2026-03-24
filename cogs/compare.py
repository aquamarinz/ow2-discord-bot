from __future__ import annotations
"""
/compare @playerA @playerB — side-by-side stats comparison
"""
import discord
from discord import app_commands
from discord.ext import commands

from utils.embeds import build_compare_embed


class CompareCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="compare", description="并排对比两名服务器成员的 Overwatch 战绩")
    @app_commands.describe(player_a="第一名玩家", player_b="第二名玩家")
    async def compare(
        self,
        interaction: discord.Interaction,
        player_a: discord.Member,
        player_b: discord.Member,
    ) -> None:
        await interaction.response.defer()

        if player_a.id == player_b.id:
            await interaction.followup.send(
                embed=discord.Embed(
                    title="❌ 无法比较",
                    description="请选择两名不同的玩家进行对比。",
                    color=0xFF4444,
                ),
                ephemeral=True,
            )
            return

        guild_id = str(interaction.guild_id)
        rec_a = await self.bot.db.get_player(str(player_a.id), guild_id)
        rec_b = await self.bot.db.get_player(str(player_b.id), guild_id)

        missing = []
        if not rec_a:
            missing.append(player_a.display_name)
        if not rec_b:
            missing.append(player_b.display_name)

        if missing:
            await interaction.followup.send(
                embed=discord.Embed(
                    title="❌ 玩家未注册",
                    description=(
                        f"**{'、'.join(missing)}** 尚未注册 Overwatch 账号。\n"
                        "请先使用 `/register` 绑定 BattleTag。"
                    ),
                    color=0xFF4444,
                ),
                ephemeral=True,
            )
            return

        sum_a = stats_a = sum_b = stats_b = None
        try:
            sum_a   = await self.bot.api.get_player_summary(rec_a["battletag"])
            stats_a = await self.bot.api.get_player_stats(rec_a["battletag"])
        except Exception:
            pass
        try:
            sum_b   = await self.bot.api.get_player_summary(rec_b["battletag"])
            stats_b = await self.bot.api.get_player_stats(rec_b["battletag"])
        except Exception:
            pass

        await interaction.followup.send(
            embed=build_compare_embed(
                player_a, rec_a["battletag"], sum_a, stats_a,
                player_b, rec_b["battletag"], sum_b, stats_b,
            )
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CompareCog(bot))
