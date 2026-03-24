from __future__ import annotations
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from utils.embeds import build_hero_embed, _HERO_CN

# Reverse lookup: Chinese name → hero key, plus key → key for English input
_HERO_SEARCH: dict[str, str] = {}
for _k, _cn in _HERO_CN.items():
    _HERO_SEARCH[_cn.lower()] = _k
    _HERO_SEARCH[_k.lower()] = _k
    # Also add without hyphens: "soldier 76" → "soldier-76"
    _HERO_SEARCH[_k.replace("-", " ").lower()] = _k


class HeroCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        # Cache: discord_id → [(hero_key, games_played, time_played)]
        self._hero_cache: dict[str, list[dict]] = {}

    @app_commands.command(name="hero", description="查看某个英雄的详细数据（含专属技能数据）")
    @app_commands.describe(
        hero="英雄名称（中文或英文，如 源氏 / genji）",
        member="要查询的成员（留空则查询自己）",
    )
    @app_commands.guild_only()
    async def hero(
        self,
        interaction: discord.Interaction,
        hero: str,
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

        # Resolve hero key
        hero_key = _HERO_SEARCH.get(hero.lower().strip())
        if not hero_key:
            await interaction.followup.send(
                embed=discord.Embed(
                    title="❌ 未找到英雄",
                    description=f"找不到英雄「{hero}」。\n请输入英雄的中文名或英文名，如「源氏」或「genji」。",
                    color=0xFF4444,
                )
            )
            return

        data = await self.bot.api.get_hero_stats(player["battletag"], hero_key)
        if data is None:
            await interaction.followup.send(
                embed=discord.Embed(
                    title="⚠️ 数据获取失败",
                    description="当前无法连接到 Overwatch API，请稍后重试。",
                    color=0xFFAA00,
                )
            )
            return
        if data.get("_private"):
            await interaction.followup.send(
                embed=discord.Embed(
                    title="🔒 主页设为私密",
                    description=f"`{player['battletag']}` 的主页设为私密，无法读取数据。",
                    color=0xFFAA00,
                )
            )
            return

        await interaction.followup.send(embed=build_hero_embed(target, data))

    @hero.autocomplete("hero")
    async def _hero_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        """Autocomplete hero names from the player's played heroes."""
        uid = str(interaction.user.id)

        # Try to get player's played heroes for personalized suggestions
        if uid not in self._hero_cache:
            player = await self.bot.db.get_player(uid, str(interaction.guild_id))
            if player:
                heroes = await self.bot.api.get_played_heroes(player["battletag"])
                self._hero_cache[uid] = heroes

        played = self._hero_cache.get(uid, [])
        query = current.lower().strip()

        choices = []
        if played:
            # Show player's most-played heroes, filtered by input
            for h in played:
                key = h["key"]
                cn = _HERO_CN.get(key, key.replace("-", " ").title())
                label = f"{cn} ({key})"
                if not query or query in cn.lower() or query in key.lower():
                    choices.append(app_commands.Choice(name=label, value=key))
                if len(choices) >= 25:
                    break
        else:
            # Fallback: show all heroes filtered by input
            for key, cn in sorted(_HERO_CN.items(), key=lambda x: x[1]):
                label = f"{cn} ({key})"
                if not query or query in cn.lower() or query in key.lower():
                    choices.append(app_commands.Choice(name=label, value=key))
                if len(choices) >= 25:
                    break

        return choices


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(HeroCog(bot))
