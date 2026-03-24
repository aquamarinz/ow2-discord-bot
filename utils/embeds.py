from __future__ import annotations
from datetime import datetime, timezone
from typing import Any, Optional

import discord

from config import RANK_COLORS, RANK_EMOJIS, RANK_ORDER, ROLE_EMOJIS, ROLE_LABELS

# Hero name → Chinese display name (common heroes)
_HERO_CN: dict[str, str] = {
    "ana": "安娜", "ashe": "艾什", "baptiste": "巴蒂斯特", "bastion": "堡垒",
    "brigitte": "布丽吉塔", "cassidy": "卡西迪", "dva": "D.Va", "doomfist": "末日铁拳",
    "echo": "回声", "genji": "源氏", "hanzo": "半藏", "hazard": "危境",
    "illari": "伊拉锐", "junker-queen": "渣客女王", "junkrat": "狂鼠",
    "juno": "朱诺", "kiriko": "雾子", "lifeweaver": "生命之梭",
    "lucio": "卢西奥", "mauga": "毛加", "mei": "美", "mercy": "天使",
    "moira": "莫伊拉", "orisa": "奥丽莎", "pharah": "法老之鹰",
    "ramattra": "拉玛刹", "reaper": "死神", "reinhardt": "莱因哈特",
    "roadhog": "路霸", "sigma": "西格玛", "sojourn": "索杰恩",
    "soldier-76": "士兵76", "sombra": "黑影", "symmetra": "秩序之光",
    "torbjorn": "托比昂", "tracer": "猎空", "venture": "探奇",
    "widowmaker": "黑百合", "winston": "温斯顿", "wrecking-ball": "破坏球",
    "zarya": "查莉娅", "zenyatta": "禅雅塔",
}

_GAMEMODE_LABEL = {"all": "全部数据", "competitive": "竞技比赛", "quickplay": "快速比赛"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _best_rank(competitive: dict) -> tuple[str, int]:
    best_div, best_tier, best_score = "Unranked", 5, 0
    for rd in competitive.values():
        if not isinstance(rd, dict):
            continue
        div = rd.get("division", "Unranked")
        tier = rd.get("tier", 5)
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


def _hero_name(key: str) -> str:
    return _HERO_CN.get(key, key.replace("-", " ").title())


def _embed_color(competitive: dict) -> int:
    div, _ = _best_rank(competitive)
    return RANK_COLORS.get(div, 0x4488FF)


def _bar(pct: float, length: int = 10) -> str:
    """Simple text progress bar."""
    filled = round(pct / 100 * length)
    return "▰" * filled + "▱" * (length - filled)


# ── /stats ────────────────────────────────────────────────────────────────────
def build_stats_embed(
    member: discord.Member,
    stats: dict[str, Any],
) -> discord.Embed:
    """Build a rich stats embed from the new get_player_stats() result."""
    comp = stats.get("competitive") or {}
    color = _embed_color(comp)
    gamemode = stats.get("gamemode", "competitive")
    mode_label = _GAMEMODE_LABEL.get(gamemode, gamemode)

    embed = discord.Embed(
        title=f"📊  {stats.get('username', member.display_name)} 的战绩",
        color=color,
        timestamp=_now(),
    )
    embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)
    avatar = stats.get("avatar", "")
    embed.set_thumbnail(url=avatar or member.display_avatar.url)

    # -- Header: BattleTag + endorsement + mode --
    embed.add_field(
        name="🎮 BattleTag",
        value=f"`{stats.get('battletag', '—')}`",
        inline=True,
    )
    endorse = stats.get("endorsement")
    embed.add_field(
        name="⭐ 信誉等级",
        value=f"Lv.{endorse}" if endorse else "—",
        inline=True,
    )
    embed.add_field(name="🎯 模式", value=f"**{mode_label}**", inline=True)

    # -- Competitive ranks --
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

    # -- General overview --
    gen = stats.get("general") or {}
    played = gen.get("games_played", 0)
    won = gen.get("games_won", 0)
    lost = gen.get("games_lost", 0)
    winrate = gen.get("winrate", 0)
    kda = gen.get("kda", 0)

    if played:
        embed.add_field(
            name="🎯 总览",
            value=(
                f"场次: **{played}**　胜/负: **{won}**/**{lost}**\n"
                f"胜率: **{winrate:.1f}%** {_bar(winrate)}\n"
                f"KDA: **{kda:.2f}**\n"
                f"游戏时间: **{_fmt_time(gen.get('time_played', 0))}**"
            ),
            inline=False,
        )

        # -- Per-game averages from stats/summary --
        avg_elim = gen.get("avg_eliminations", 0)
        avg_death = gen.get("avg_deaths", 0)
        avg_dmg = gen.get("avg_damage", 0)
        avg_heal = gen.get("avg_healing", 0)
        embed.add_field(
            name="📈 场均数据",
            value=(
                f"⚔️ 击杀: **{avg_elim:.1f}**\n"
                f"💀 阵亡: **{avg_death:.1f}**\n"
                f"💥 伤害: **{avg_dmg:,.0f}**\n"
                f"💚 治疗: **{avg_heal:,.0f}**"
            ),
            inline=True,
        )

    # -- Per-10-min from stats/career --
    career = stats.get("career") or {}
    elim10 = career.get("eliminations_per_10", 0)
    if elim10:  # career data available
        embed.add_field(
            name="⏱ 每10分钟均值",
            value=(
                f"⚔️ 击杀: **{elim10:.1f}**\n"
                f"💀 阵亡: **{career.get('deaths_per_10', 0):.1f}**\n"
                f"💥 伤害: **{career.get('hero_damage_per_10', 0):,.0f}**\n"
                f"💚 治疗: **{career.get('healing_per_10', 0):,.0f}**"
            ),
            inline=True,
        )

    # -- Best records --
    elim_best = career.get("elim_best_game", 0)
    if elim_best:
        acc = career.get("weapon_accuracy", 0)
        embed.add_field(
            name="🏆 最佳记录",
            value=(
                f"单局最高击杀: **{elim_best}**\n"
                f"单局最高伤害: **{career.get('damage_best_game', 0):,}**\n"
                f"最长连杀: **{career.get('kill_streak_best', 0)}**\n"
                f"命中率: **{acc}%**" + (
                    f"　暴击率: **{career.get('critical_hit_accuracy', 0)}%**"
                    if career.get("critical_hit_accuracy") else ""
                )
            ),
            inline=False,
        )

    # -- Top heroes --
    top_heroes = stats.get("top_heroes") or []
    if top_heroes:
        lines = []
        for h in top_heroes[:3]:
            name = _hero_name(h["name"])
            hw = h.get("winrate", 0)
            lines.append(
                f"**{name}** — {h['games_played']}场 "
                f"胜率{hw:.0f}% KDA {h.get('kda', 0):.1f} "
                f"({_fmt_time(h['time_played'])})"
            )
        embed.add_field(
            name="🦸 常用英雄",
            value="\n".join(lines),
            inline=False,
        )

    # -- Role breakdown --
    roles = stats.get("roles") or {}
    if roles:
        lines = []
        for role_key in ("tank", "damage", "support"):
            rd = roles.get(role_key)
            if not rd or not rd.get("games_played"):
                continue
            emoji = ROLE_EMOJIS.get(role_key, "")
            label = ROLE_LABELS.get(role_key, role_key)
            rw = rd.get("winrate", 0)
            lines.append(
                f"{emoji} **{label}**: {rd['games_played']}场 "
                f"胜率{rw:.0f}% KDA {rd.get('kda', 0):.1f}"
            )
        if lines:
            embed.add_field(
                name="🎭 职责分布",
                value="\n".join(lines),
                inline=False,
            )

    embed.set_footer(text=f"数据来自 OverFast API · {mode_label} · 仅供参考")
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
    lines = []
    for i, p in enumerate(ranked[:15], 1):
        medal = MEDALS.get(i, f"`#{i:2d}`")
        comp = p.get("competitive") or {}
        best_txt, best_score = "未定级", 0
        for role in ("damage", "tank", "support"):
            rd = comp.get(role)
            if rd:
                div = rd.get("division", "Unranked")
                tier = rd.get("tier", 5)
                score = RANK_ORDER.get(div, 0) * 10 + (6 - tier)
                if score > best_score:
                    best_score = score
                    best_txt = _fmt_rank(div, tier)
        member = guild.get_member(int(p["discord_id"]))
        name = member.mention if member else f"**{p.get('username', p['battletag'].split('#')[0])}**"
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
            tag = acc["battletag"]
            label = acc.get("label") or ""
            is_primary = tag == primary_tag
            marker = " ⭐主账号" if is_primary else ""
            label_txt = f"  `{label}`" if label else ""
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
    comp = (summary or {}).get("competitive") or {}
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
