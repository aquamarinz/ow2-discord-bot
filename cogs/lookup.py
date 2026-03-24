from __future__ import annotations
"""
/lookup <battletag> — query any player's public stats without registration
"""
import discord
from discord import app_commands
from discord.ext import commands

from utils.embeds import build_lookup_embed


class LookupCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="lookup", description="直接查询任意玩家的公开战绩（无需注册）")
    @app_commands.describe(battletag="玩家的 BattleTag，格式：名字#数字  例如 Player#1234")
    async def lookup(
        self,
        interaction: discord.Interaction,
        battletag: str,
    ) -> None:
        await interaction.response.defer()

        # Normalize: accept Chinese full-width ＃
        battletag = battletag.replace("＃", "#").strip()

        if "#" not in battletag:
            await interaction.followup.send(
                embed=discord.Embed(
                    title="❌ 格式错误",
                    description="BattleTag 格式应为 `名字#数字`，例如 `Player#1234`。",
                    color=0xFF4444,
                ),
                ephemeral=True,
            )
            return

        summary = await self.bot.api.get_player_summary(battletag)
        if summary is None:
            await interaction.followup.send(
                embed=discord.Embed(
                    title="❌ 玩家不存在",
                    description=f"找不到 `{battletag}`，请检查 BattleTag 是否正确。",
                    color=0xFF4444,
                )
            )
            return

        if summary.get("_private"):
            await interaction.followup.send(
                embed=discord.Embed(
                    title="🔒 主页设为私密",
                    description=f"`{battletag}` 的 Overwatch 主页为私密，无法读取数据。",
                    color=0xFFAA00,
                )
            )
            return

        stats = await self.bot.api.get_player_stats(battletag)
        await interaction.followup.send(
            embed=build_lookup_embed(battletag, summary, stats)
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(LookupCog(bot))
