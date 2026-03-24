from __future__ import annotations
"""
/history — list recent completed match sessions for this server
"""
import discord
from discord import app_commands
from discord.ext import commands

from utils.embeds import build_history_embed


class HistoryCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="history", description="查看本服务器最近的对局记录列表")
    async def history(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()

        guild_id = str(interaction.guild_id)
        sessions = await self.bot.db.get_match_history(guild_id, limit=10)

        if not sessions:
            await interaction.followup.send(
                embed=discord.Embed(
                    title="📜 对局历史",
                    description=(
                        "本服务器暂无已完成的对局记录。\n"
                        "使用 `/match start` 开始第一场记录。"
                    ),
                    color=0x888888,
                )
            )
            return

        await interaction.followup.send(
            embed=build_history_embed(sessions, interaction.guild)
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(HistoryCog(bot))
