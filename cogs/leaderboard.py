from __future__ import annotations
import asyncio
import logging
import time
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from config import LEADERBOARD_CACHE_TTL, RANK_ORDER
from utils.embeds import build_leaderboard_embed

logger = logging.getLogger(__name__)


class LeaderboardCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._cache: dict[str, tuple[float, list]] = {}
        self._api_sem = asyncio.Semaphore(3)

    @app_commands.command(name="leaderboard", description="查看服务器 Overwatch 2 竞技排行榜")
    @app_commands.guild_only()
    async def leaderboard(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()

        guild_id = str(interaction.guild_id)
        players  = await self.bot.db.get_all_players(guild_id)

        if not players:
            await interaction.followup.send(
                embed=discord.Embed(
                    title="📊 排行榜",
                    description="服务器暂无成员注册 Overwatch 账号。\n使用 `/register` 成为第一个！",
                    color=0x4488FF,
                )
            )
            return

        cached = self._cache.get(guild_id)
        if cached and time.monotonic() - cached[0] < LEADERBOARD_CACHE_TTL:
            ranked = cached[1]
        else:
            ranked = await self._build_rankings(players)
            self._cache[guild_id] = (time.monotonic(), ranked)

        requester_id  = str(interaction.user.id)
        requester_pos: Optional[int] = next(
            (i + 1 for i, p in enumerate(ranked) if p["discord_id"] == requester_id),
            None,
        )
        await interaction.followup.send(
            embed=build_leaderboard_embed(ranked, interaction.guild, requester_pos)
        )

    def invalidate(self, guild_id: str) -> None:
        self._cache.pop(str(guild_id), None)

    async def _build_rankings(self, players: list[dict]) -> list[dict]:
        tasks   = [self._fetch_one(p) for p in players]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        valid   = [r for r in results if isinstance(r, dict)]
        valid.sort(key=_rank_sort_key, reverse=True)
        return valid

    async def _fetch_one(self, player: dict) -> dict:
        try:
            async with self._api_sem:
                await asyncio.sleep(0.3)
                summary = await self.bot.api.get_player_summary(player["battletag"])
            if summary and not summary.get("_private"):
                return {
                    "discord_id":  player["discord_id"],
                    "battletag":   player["battletag"],
                    "username":    summary.get("username") or player["battletag"].split("#")[0],
                    "competitive": summary.get("competitive", {}),
                }
        except Exception as exc:
            logger.error("Leaderboard fetch failed for %s: %s", player["battletag"], exc)
        return {
            "discord_id":  player["discord_id"],
            "battletag":   player["battletag"],
            "username":    player["battletag"].split("#")[0],
            "competitive": {},
        }


def _rank_sort_key(p: dict) -> int:
    best = 0
    for rd in (p.get("competitive") or {}).values():
        if not isinstance(rd, dict):
            continue
        score = RANK_ORDER.get(rd.get("division", "Unranked"), 0) * 10 + (6 - rd.get("tier", 5))
        if score > best:
            best = score
    return best


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(LeaderboardCog(bot))
