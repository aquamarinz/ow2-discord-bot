from __future__ import annotations
"""
/server-stats — aggregate Overwatch stats for all registered players in this guild.
Uses local snapshot data only (no API calls) to keep it fast.
"""
import discord
from discord import app_commands
from discord.ext import commands

from config import RANK_ORDER
from utils.embeds import build_server_stats_embed


class ServerStatsCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="server-stats", description="查看本服务器所有玩家的整体战绩统计")
    async def server_stats(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()

        guild_id = str(interaction.guild_id)
        players  = await self.bot.db.get_all_players(guild_id)

        if not players:
            await interaction.followup.send(
                embed=discord.Embed(
                    title="📊 服务器战况",
                    description=(
                        "本服务器暂无注册成员。\n"
                        "使用 `/register` 绑定 BattleTag 加入榜单。"
                    ),
                    color=0x888888,
                )
            )
            return

        # Collect snapshot data without making API calls
        player_data: list[dict] = []
        for p in players:
            latest = await self.bot.db.get_latest_snapshot(p["discord_id"], guild_id, "periodic")
            recent = await self.bot.db.get_trend_snapshots(p["discord_id"], guild_id, limit=20)
            player_data.append({
                "discord_id": p["discord_id"],
                "battletag":  p["battletag"],
                "latest":     latest,
                "recent":     recent,
            })

        aggregated = _aggregate(player_data)
        await interaction.followup.send(
            embed=build_server_stats_embed(interaction.guild, len(players), aggregated)
        )


def _best_div(comp: dict) -> str:
    best_div, best_score = "Unranked", 0
    for rd in (comp or {}).values():
        if not isinstance(rd, dict):
            continue
        div   = rd.get("division", "Unranked")
        tier  = rd.get("tier", 5)
        score = RANK_ORDER.get(div, 0) * 10 + (6 - tier)
        if score > best_score:
            best_div, best_score = div, score
    return best_div


def _aggregate(player_data: list[dict]) -> dict:
    rank_dist:      dict[str, int] = {}
    most_active:    dict | None = None
    most_active_g:  int = -1
    best_wr_player: dict | None = None
    best_wr_val:    float = -1.0

    for pd in player_data:
        latest = pd["latest"]
        recent = pd["recent"]

        if latest:
            div = _best_div(latest.get("competitive_data") or {})
            if div and div != "Unranked":
                rank_dist[div] = rank_dist.get(div, 0) + 1

        if len(recent) >= 2:
            newest, oldest = recent[0], recent[-1]
            d_g = max(0, (newest.get("games_played") or 0) - (oldest.get("games_played") or 0))
            d_w = max(0, (newest.get("games_won")    or 0) - (oldest.get("games_won")    or 0))

            if d_g > most_active_g:
                most_active_g = d_g
                most_active   = {**pd, "recent_games": d_g}

            if d_g >= 5:
                wr = d_w / d_g * 100
                if wr > best_wr_val:
                    best_wr_val    = wr
                    best_wr_player = {**pd, "recent_wr": wr, "recent_games": d_g}

    return {
        "rank_dist":     rank_dist,
        "most_active":   most_active,
        "best_wr_player": best_wr_player,
        "best_wr_val":   best_wr_val,
    }


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ServerStatsCog(bot))
