from __future__ import annotations
from typing import Optional
import logging

import discord
from discord import app_commands
from discord.ext import commands

from utils.embeds import build_rank_embed, build_stats_embed

logger = logging.getLogger(__name__)


class StatsCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ------------------------------------------------------------------ /stats
    @app_commands.command(name="stats", description="查看玩家的 Overwatch 2 战绩数据")
    @app_commands.describe(member="要查询的服务器成员（留空则查询自己）")
    async def stats(
        self,
        interaction: discord.Interaction,
        member: Optional[discord.Member] = None,
    ) -> None:
        await interaction.response.defer()
        target = member or interaction.user

        player = await self.bot.db.get_player(str(target.id), str(interaction.guild_id))
        if not player:
            await interaction.followup.send(embed=_not_registered(target, member is None))
            return

        summary = await self.bot.api.get_player_summary(player["battletag"])
        if summary is None:
            await interaction.followup.send(embed=_api_error())
            return
        if summary.get("_private"):
            await interaction.followup.send(embed=_private(player["battletag"]))
            return

        stats = await self.bot.api.get_player_stats(player["battletag"])
        await interaction.followup.send(embed=build_stats_embed(target, summary, stats))

    # ------------------------------------------------------------------ /rank
    @app_commands.command(name="rank", description="快速查看玩家当前竞技段位")
    @app_commands.describe(member="要查询的服务器成员（留空则查询自己）")
    async def rank(
        self,
        interaction: discord.Interaction,
        member: Optional[discord.Member] = None,
    ) -> None:
        await interaction.response.defer()
        target = member or interaction.user

        player = await self.bot.db.get_player(str(target.id), str(interaction.guild_id))
        if not player:
            await interaction.followup.send(embed=_not_registered(target, member is None))
            return

        summary = await self.bot.api.get_player_summary(player["battletag"])
        if summary is None:
            await interaction.followup.send(embed=_api_error())
            return
        if summary.get("_private"):
            await interaction.followup.send(embed=_private(player["battletag"]))
            return

        await interaction.followup.send(embed=build_rank_embed(target, summary))


# ------------------------------------------------------------------ shared embeds
def _not_registered(target: discord.Member, is_self: bool) -> discord.Embed:
    who = "你" if is_self else target.mention
    return discord.Embed(
        title="❌ 未注册",
        description=f"{who} 还没有绑定 Overwatch 账号。\n使用 `/register <BattleTag>` 完成注册。",
        color=0xFF4444,
    )


def _api_error() -> discord.Embed:
    return discord.Embed(
        title="⚠️ 数据获取失败",
        description="当前无法连接到 Overwatch API，请稍后重试。",
        color=0xFFAA00,
    )


def _private(battletag: str) -> discord.Embed:
    return discord.Embed(
        title="🔒 主页设为私密",
        description=(
            f"`{battletag}` 的 Overwatch 主页设为私密，无法读取数据。\n"
            "请将主页改为公开后重试。"
        ),
        color=0xFFAA00,
    )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(StatsCog(bot))
