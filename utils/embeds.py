from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Optional

import discord

from config import RANK_COLORS, RANK_EMOJIS, RANK_ORDER, ROLE_EMOJIS, ROLE_LABELS


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _best_rank(competitive: dict) -> tuple[str, int]:
    best_div, best_tier, best_score = "Unranked", 5, 0
    for rd in competitive.values():
        if not isinstance(rd, dict):
            continue
        div   = rd.get("division", "Unranked")
        tier  = rd.get("tier", 5)
        score = RANK_ORDER.get(div, 0) * 10 + (6 - tier)
        if score > best_score:
            best_div, best_tier, best_score = div, tier, score
    return best_div, best_tier


def _fmt_rank(division: str, tier: int) -> str:
    if not division or division == "Unranked":
        return "未定级"
    emoji = RANK_EMOJIS.get(division, "")
    if division in ("Grandmaster", "Champion"):
        return f"{emoji} {division}"
    return f"{emoji} {division} {tier}"


def _fmt_time(seconds: int) -> str:
    if not seconds:
        return "—"
    h, m = divmod(seconds, 3600)
    m //= 60
    return f"{h}h {m}m" if h else f"{m}m"


def _embed_color(competitive: dict) -> int:
    div, _ = _best_rank(competitive)
    return RANK_COLORS.get(div, 0x4488FF)


# ── /stats ────────────────────────────────────────────────────────────────────
def build_stats_embed(
    member: discord.Member,
    summary: dict[str, Any],
    stats: Optional[dict[str, Any]],
) -> discord.Embed:
    comp  = summary.get("competitive") or {}
    color = _embed_color(comp)

    embed = discord.Embed(
        title=f"📊  {summary.get('username', member.display_name)} 的战绩",
        color=color,
        timestamp=_now(),
    )
    embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)
    avatar = summary.get("avatar", "")
    embed.set_thumbnail(url=avatar or member.display_avatar.url)

    embed.add_field(name="🎮 BattleTag", value=f"`{summary.get('battletag', '—')}`", inline=True)
    endorse = summary.get("endorsement")
    embed.add_field(name="⭐ 信誉等级", value=f"Lv.{endorse}" if endorse else "—", inline=True)
    embed.add_field(name="\u200b", value="\u200b", inline=True)

    if comp:
        lines = []
        for role in ("tank", "damage", "support"):
            rd = comp.get(role)
            if rd:
                lines.append(
                    f"{ROLE_EMOJIS[role]} **{ROLE_LABELS[role]}**: "
                    f"{_fmt_rank(rd.get('division', 'Unranked'), rd.get('tier', 0))}"
                )
        embed.add_field(
            name="🏅 竞技段位",
            value="\n".join(lines) if lines else "本赛季暂未参与竞技",
            inline=False,
        )
    else:
        embed.add_field(name="🏅 竞技段位", value="本赛季暂未参与竞技", inline=False)

    if stats and not stats.get("_private"):
        played = stats.get("games_played") or 0
        won    = stats.get("games_won") or 0
        wr     = won / played * 100 if played else 0
        embed.add_field(
            name="🎯 总览",
            value=(
                f"胜场: **{won}** / 场次: **{played}**\n"
                f"胜率: **{wr:.1f}%**\n"
                f"游戏时间: **{_fmt_time(stats.get('time_played_seconds', 0))}**"
            ),
            inline=True,
        )
        embed.add_field(
            name="📈 每10分钟均值",
            value=(
                f"⚔️ 击杀: **{stats.get('eliminations_per_10', 0):.1f}**\n"
                f"💀 阵亡: **{stats.get('deaths_per_10', 0):.1f}**\n"
                f"💥 伤害: **{stats.get('damage_per_10', 0):,.0f}**\n"
                f"💚 治疗: **{stats.get('healing_per_10', 0):,.0f}**"
            ),
            inline=True,
        )

    embed.set_footer(text="数据来自 OverFast API · 仅供参考")
    return embed


# ── /leaderboard ──────────────────────────────────────────────────────────────
def build_leaderboard_embed(
    ranked: list[dict[str, Any]],
    guild: discord.Guild,
    requester_pos: Optional[int],
) -> discord.Embed:
    embed = discord.Embed(
        title=f"🏆  {guild.name} · Overwatch 2 排行榜",
        color=0xFFD700,
        timestamp=_now(),
    )
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)

    MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}
    lines  = []
    for i, p in enumerate(ranked[:15], 1):
        medal    = MEDALS.get(i, f"`#{i:2d}`")
        comp     = p.get("competitive") or {}
        best_txt, best_score = "未定级", 0
        for role in ("damage", "tank", "support"):
            rd = comp.get(role)
            if rd:
                div   = rd.get("division", "Unranked")
                tier  = rd.get("tier", 5)
                score = RANK_ORDER.get(div, 0) * 10 + (6 - tier)
                if score > best_score:
                    best_score = score
                    best_txt   = _fmt_rank(div, tier)
        member = guild.get_member(int(p["discord_id"]))
        name   = member.mention if member else f"**{p.get('username', p['battletag'].split('#')[0])}**"
        lines.append(f"{medal} {name} — {best_txt}")

    embed.description = "\n".join(lines) or "暂无数据"
    if len(ranked) > 15:
        embed.add_field(name="", value=f"*还有 {len(ranked) - 15} 名成员未显示*", inline=False)
    if requester_pos:
        embed.add_field(
            name="📍 你的位置",
            value=f"第 **{requester_pos}** 名 / 共 {len(ranked)} 名",
            inline=False,
        )
    embed.set_footer(text="数据每5分钟缓存刷新 · 仅供参考")
    return embed


# ── /id list & share ──────────────────────────────────────────────────────────
def build_id_list_embed(
    member: discord.Member,
    accounts: list[dict],
    primary_tag: Optional[str],
) -> discord.Embed:
    embed = discord.Embed(
        title=f"🎮  {member.display_name} 的已保存账号",
        color=0x4488FF,
        timestamp=_now(),
    )
    embed.set_thumbnail(url=member.display_avatar.url)

    if not accounts:
        embed.description = "你还没有保存任何账号。\n使用 `/id add <BattleTag>` 添加。"
    else:
        lines = []
        for acc in accounts:
            tag   = acc["battletag"]
            label = acc.get("label") or ""
            is_primary = tag == primary_tag
            marker = " ⭐主账号" if is_primary else ""
            label_txt  = f"  `{label}`" if label else ""
            lines.append(f"• `{tag}`{label_txt}{marker}")
        embed.description = "\n".join(lines)

    embed.set_footer(text=f"共 {len(accounts)} 个账号 · /id share 可公开分享")
    return embed


def build_id_share_embed(
    member: discord.Member,
    battletag: str,
    label: Optional[str],
    summary: Optional[dict],
) -> discord.Embed:
    comp  = (summary or {}).get("competitive") or {}
    color = _embed_color(comp) if comp else 0x4488FF

    embed = discord.Embed(
        title=f"🎮  {member.display_name} 的 Overwatch ID",
        color=color,
        timestamp=_now(),
    )
    embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)
    avatar = (summary or {}).get("avatar", "")
    embed.set_thumbnail(url=avatar or member.display_avatar.url)

    embed.add_field(name="BattleTag", value=f"`{battletag}`", inline=True)
    if label:
        embed.add_field(name="备注", value=label, inline=True)

    if comp:
        lines = []
        for role in ("tank", "damage", "support"):
            rd = comp.get(role)
            if rd:
                lines.append(
                    f"{ROLE_EMOJIS[role]} {ROLE_LABELS[role]}: "
                    f"{_fmt_rank(rd.get('division', 'Unranked'), rd.get('tier', 0))}"
                )
        if lines:
            embed.add_field(name="🏅 当前段位", value="\n".join(lines), inline=False)

    embed.set_footer(text="复制 BattleTag 即可添加好友")
    return embed
