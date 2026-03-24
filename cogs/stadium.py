"""
/stadium <hero> — top 5 Stadium build codes from stadiumbuilds.io
Supports Chinese / English hero names with autocomplete.
"""
from __future__ import annotations

import logging

import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

from config import SUPABASE_STADIUM_URL, SUPABASE_STADIUM_KEY
from utils.embeds import _HERO_CN

logger = logging.getLogger(__name__)

_SUPABASE_URL = SUPABASE_STADIUM_URL
_SUPABASE_KEY = SUPABASE_STADIUM_KEY
_BASE_URL = "https://stadiumbuilds.io"
_HEADERS = {
    "apikey": _SUPABASE_KEY,
    "authorization": f"Bearer {_SUPABASE_KEY}",
    "content-type": "application/json",
    "content-profile": "public",
}
_ROLE_EMOJI = {"Tank": "🛡️", "Damage": "⚔️", "Support": "💚"}

# ── Hero lookup tables ────────────────────────────────────────────────────────
# cn → english key, english key → english key, display name for the API
_HERO_SEARCH: dict[str, str] = {}
for _k, _cn in _HERO_CN.items():
    _HERO_SEARCH[_cn.lower()] = _k
    _HERO_SEARCH[_k.lower()] = _k
    _HERO_SEARCH[_k.replace("-", " ").lower()] = _k

# Stadium API uses different name formats — map our keys to stadium display names
_STADIUM_NAME: dict[str, str] = {k: k.replace("-", " ").title() for k in _HERO_CN}
_STADIUM_NAME.update({
    "dva": "D.Va",
    "soldier-76": "Soldier: 76",
    "wrecking-ball": "Wrecking Ball",
    "junker-queen": "Junker Queen",
    "torbjorn": "Torbjörn",
    "lucio": "Lúcio",
})


class StadiumCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(
        name="stadium",
        description="查询 Stadium 模式英雄的 Top 5 Build Codes（数据来自 stadiumbuilds.io）",
    )
    @app_commands.describe(hero="英雄名称（中文或英文，如 源氏 / genji / Kiriko）")
    @app_commands.guild_only()
    async def stadium(self, interaction: discord.Interaction, hero: str) -> None:
        await interaction.response.defer()

        # Resolve input to English key
        hero_key = _HERO_SEARCH.get(hero.lower().strip())
        search_name = _STADIUM_NAME.get(hero_key, hero) if hero_key else hero
        display_cn = _HERO_CN.get(hero_key, search_name) if hero_key else hero

        payload = {
            "p_search_text": search_name,
            "p_sort_by": "hotness",
            "p_sort_direction": "desc",
            "p_offset": 0,
            "p_limit": 5,
            "p_filter_type": "all",
            "p_hero_ids": None,
            "p_stat_names": None,
            "p_updated_after": None,
            "p_item_ids": None,
            "p_item_filter_mode": "all",
            "p_average_cost": None,
            "p_matchup_hero_ids": None,
            "p_mode": None,
            "p_build_code": None,
            "p_show_only_with_notes": False,
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    _SUPABASE_URL, headers=_HEADERS, json=payload,
                    timeout=aiohttp.ClientTimeout(total=10),
                ) as resp:
                    if resp.status != 200:
                        raise RuntimeError(f"HTTP {resp.status}")
                    builds = await resp.json()
        except Exception as exc:
            logger.warning("Stadium API error: %s", exc)
            await interaction.followup.send(
                embed=discord.Embed(
                    title="❌ 查询失败",
                    description="无法连接到 stadiumbuilds.io，请稍后重试。",
                    color=0xFF4444,
                )
            )
            return

        if not builds:
            await interaction.followup.send(
                embed=discord.Embed(
                    title="🔍 未找到结果",
                    description=(
                        f"没有找到关于 **{display_cn}** ({search_name}) 的 Stadium Build。\n"
                        "请检查英雄名称是否正确。"
                    ),
                    color=0xFFAA00,
                )
            )
            return

        embed = discord.Embed(
            title=f"🏟️ {display_cn} ({search_name}) — Top Stadium Builds",
            url=f"{_BASE_URL}/browse?search={search_name.replace(' ', '+')}",
            color=0xFF6B2B,
        )
        embed.set_footer(text="数据来源：stadiumbuilds.io • 按热度排序")

        for i, b in enumerate(builds[:5], 1):
            title      = b.get("title") or "未命名"
            build_code = b.get("build_code") or "—"
            role       = b.get("hero_role") or ""
            role_emoji = _ROLE_EMOJI.get(role, "")
            creator    = b.get("user_username") or "未知"
            likes      = b.get("like_count", 0)
            views      = b.get("view_count", 0)
            build_id   = b.get("id", "")
            season     = b.get("season_number")

            code_txt   = f"`{build_code}`" if build_code != "—" else "—"
            season_txt = f" · S{season}" if season else ""
            build_url  = f"{_BASE_URL}/build/{build_id}"

            embed.add_field(
                name=f"{i}. {title}",
                value=(
                    f"**Code:** {code_txt}{season_txt}  {role_emoji}\n"
                    f"👤 {creator}  ❤️ {likes}  👁 {views}\n"
                    f"[🔗 查看 Build]({build_url})"
                ),
                inline=False,
            )

        await interaction.followup.send(embed=embed)

    @stadium.autocomplete("hero")
    async def _hero_autocomplete(
        self, interaction: discord.Interaction, current: str
    ) -> list[app_commands.Choice[str]]:
        query = current.lower().strip()
        choices = []
        for key, cn in sorted(_HERO_CN.items(), key=lambda x: x[1]):
            label = f"{cn} ({key})"
            if not query or query in cn.lower() or query in key.lower():
                choices.append(app_commands.Choice(name=label, value=key))
            if len(choices) >= 25:
                break
        return choices


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(StadiumCog(bot))
