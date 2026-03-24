from __future__ import annotations
"""
Discord embed builders for every command in the bot.
All output uses embeds — no raw text responses.
"""
from datetime import datetime
from typing import Any, Optional

import discord

from config import RANK_COLORS, RANK_EMOJIS, RANK_ORDER, ROLE_EMOJIS, ROLE_LABELS


# ------------------------------------------------------------------ small helpers
def _best_rank(competitive: dict) -> tuple[str, int]:
    """Return (division, tier) of the highest rank across all roles."""
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


# ------------------------------------------------------------------ /stats
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
        timestamp=datetime.utcnow(),
    )
    embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)

    avatar = summary.get("avatar", "")
    embed.set_thumbnail(url=avatar if avatar else member.display_avatar.url)

    # BattleTag + endorsement
    embed.add_field(name="🎮 BattleTag",   value=f"`{summary.get('battletag', '—')}`", inline=True)
    embed.add_field(name="⭐ 信誉等级",     value=f"Lv.{summary.get('endorsement', 0)}" if summary.get("endorsement") else "—", inline=True)
    embed.add_field(name="\u200b",          value="\u200b", inline=True)

    # Competitive ranks
    if comp:
        lines = []
        for role in ("tank", "damage", "support"):
            rd = comp.get(role)
            if rd:
                lines.append(
                    f"{ROLE_EMOJIS[role]} **{ROLE_LABELS[role]}**: "
                    f"{_fmt_rank(rd.get('division','Unranked'), rd.get('tier',0))}"
                )
        embed.add_field(
            name="🏅 竞技段位",
            value="\n".join(lines) if lines else "本赛季暂未参与竞技",
            inline=False,
        )
    else:
        embed.add_field(name="🏅 竞技段位", value="本赛季暂未参与竞技", inline=False)

    # Stats
    if stats and not stats.get("_private"):
        played = stats.get("games_played") or 0
        won    = stats.get("games_won")    or 0
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


# ------------------------------------------------------------------ /rank
def build_rank_embed(member: discord.Member, summary: dict[str, Any]) -> discord.Embed:
    comp  = summary.get("competitive") or {}
    color = _embed_color(comp)

    embed = discord.Embed(
        title=f"🏅  {summary.get('username', member.display_name)} 的竞技段位",
        color=color,
    )
    avatar = summary.get("avatar", "")
    embed.set_thumbnail(url=avatar if avatar else member.display_avatar.url)

    if not comp:
        embed.description = "本赛季暂未参与竞技模式"
    else:
        for role in ("tank", "damage", "support"):
            rd = comp.get(role)
            if rd:
                embed.add_field(
                    name=f"{ROLE_EMOJIS[role]} {ROLE_LABELS[role]}",
                    value=_fmt_rank(rd.get("division", "Unranked"), rd.get("tier", 0)),
                    inline=True,
                )

    embed.set_footer(text=f"BattleTag: {summary.get('battletag', '—')}")
    return embed


# ------------------------------------------------------------------ /leaderboard
def build_leaderboard_embed(
    ranked: list[dict[str, Any]],
    guild: discord.Guild,
    requester_pos: Optional[int],
) -> discord.Embed:
    embed = discord.Embed(
        title=f"🏆  {guild.name} · Overwatch 2 排行榜",
        color=0xFFD700,
        timestamp=datetime.utcnow(),
    )
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)

    MEDALS = {1: "🥇", 2: "🥈", 3: "🥉"}
    lines  = []

    for i, p in enumerate(ranked[:15], 1):
        medal    = MEDALS.get(i, f"`#{i:2d}`")
        username = p.get("username") or p["battletag"].split("#")[0]
        comp     = p.get("competitive") or {}

        # Best rank across roles
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
        name   = member.mention if member else f"**{username}**"
        lines.append(f"{medal} {name} — {best_txt}")

    embed.description = "\n".join(lines) or "暂无数据"

    if len(ranked) > 15:
        embed.add_field(
            name="", value=f"*还有 {len(ranked) - 15} 名成员未显示*", inline=False
        )
    if requester_pos:
        embed.add_field(
            name="📍 你的位置",
            value=f"第 **{requester_pos}** 名 / 共 {len(ranked)} 名",
            inline=False,
        )

    embed.set_footer(text="数据每5分钟缓存刷新 · 仅供参考")
    return embed


# ------------------------------------------------------------------ /match analyze
def build_match_analysis_embed(
    titled: list[dict[str, Any]], session_id: str
) -> discord.Embed:
    embed = discord.Embed(
        title="⚔️   战场判决   ⚔️",
        description=f"**场次** `{session_id}` · 本场对局战绩分析",
        color=0xFF6B35,
        timestamp=datetime.utcnow(),
    )

    # Special title cards
    for p in titled:
        title = p.get("title")
        if title not in ("战神", "战犯", "唐"):
            continue

        emoji  = p.get("title_emoji", "⚔️")
        name   = p.get("display_name") or p.get("battletag", "???").split("#")[0]
        role   = p.get("role", "damage")
        reason = p.get("title_reason", "")

        value = (
            f"**{name}** · {ROLE_EMOJIS.get(role,'⚔️')} {ROLE_LABELS.get(role, role)}\n"
            f"击杀 **{p.get('elims',0)}** · 阵亡 **{p.get('deaths',0)}**\n"
            f"伤害 **{p.get('damage',0):,}** · 治疗 **{p.get('healing',0):,}**\n"
            f"综合得分: **{p.get('score',0):.0f} / 100**\n"
            f"*{reason}*"
        )
        embed.add_field(name=f"{emoji}  {title}", value=value, inline=False)

    # Full scoreboard
    embed.add_field(name="─" * 32, value="**完整战绩榜**", inline=False)
    lines = []
    for i, p in enumerate(titled, 1):
        won          = "✅" if p.get("won") else "❌"
        role_emoji   = ROLE_EMOJIS.get(p.get("role", "damage"), "⚔️")
        title_emoji  = p.get("title_emoji", "  ")
        name         = p.get("display_name") or p.get("battletag", "???").split("#")[0]
        score        = p.get("score", 0)
        lines.append(
            f"{title_emoji} `#{i}` {won} {role_emoji} **{name}** — {score:.0f}分"
        )
    embed.add_field(name="", value="\n".join(lines), inline=False)

    embed.set_footer(text="战报仅供娱乐 · 数据基于对局前后快照差值估算，非精确统计")
    return embed


# ------------------------------------------------------------------ /trends
def build_trends_embed(
    member: discord.Member,
    battletag: str,
    snapshots: list[dict[str, Any]],
    summary: Optional[dict[str, Any]],
) -> discord.Embed:
    embed = discord.Embed(
        title=f"📈  {member.display_name} 的近期走势",
        color=0x4488FF,
        timestamp=datetime.utcnow(),
    )
    embed.set_thumbnail(url=member.display_avatar.url)

    # Current rank block
    if summary and not summary.get("_private"):
        comp = summary.get("competitive") or {}
        if comp:
            lines = []
            for role in ("tank", "damage", "support"):
                rd = comp.get(role)
                if rd:
                    lines.append(
                        f"{ROLE_EMOJIS[role]} {ROLE_LABELS[role]}: "
                        f"{_fmt_rank(rd.get('division','Unranked'), rd.get('tier',0))}"
                    )
            if lines:
                embed.add_field(name="🏅 当前段位", value="\n".join(lines), inline=False)

    # Stats delta across the N most-recent periodic snapshots
    recent = snapshots[:20]  # ordered newest-first
    if len(recent) >= 2:
        newest, oldest = recent[0], recent[-1]

        def _delta(key: str) -> int:
            return max(0, (newest.get(key) or 0) - (oldest.get(key) or 0))

        games  = _delta("games_played")
        wins   = _delta("games_won")
        elims  = _delta("eliminations")
        deaths = _delta("deaths")
        dmg    = _delta("damage_dealt")
        heal   = _delta("healing_done")

        if games > 0:
            wr    = wins / games * 100
            trend = "📈" if wr >= 50 else "📉"
            embed.add_field(
                name=f"{trend} 近期（约 {games} 场）",
                value=(
                    f"胜场: **+{wins}** / 场次: **+{games}**\n"
                    f"近期胜率: **{wr:.1f}%**"
                ),
                inline=True,
            )
            embed.add_field(
                name="📊 场均数据",
                value=(
                    f"⚔️ 击杀: **{elims/games:.1f}**\n"
                    f"💀 阵亡: **{deaths/games:.1f}**\n"
                    f"💥 伤害: **{dmg/games:,.0f}**\n"
                    f"💚 治疗: **{heal/games:,.0f}**"
                ),
                inline=True,
            )

    # Rank history visualisation (emoji strip, oldest → newest)
    history = _rank_history_strip(recent)
    if history:
        embed.add_field(
            name="📉 段位历史  旧 → 新",
            value=history,
            inline=False,
        )

    embed.add_field(
        name="📝 数据说明",
        value=f"基于最近 **{len(recent)}** 次快照 · 每30分钟自动记录",
        inline=False,
    )
    embed.set_footer(text=f"BattleTag: {battletag}")
    return embed


def _rank_score_linear(division: str, tier: int) -> int:
    """Linear rank scale: Bronze 5 = 6, Bronze 1 = 10, Silver 5 = 11, …, Champion 1 = 45."""
    order = RANK_ORDER.get(division, 0)
    if order == 0:
        return 0
    return order * 5 + (6 - tier)


def _fmt_dt(dt_str: str) -> str:
    """Format a SQLite timestamp string to 'YYYY-MM-DD HH:MM'."""
    try:
        dt = datetime.fromisoformat(str(dt_str))
        return dt.strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return str(dt_str) if dt_str else "—"


# ------------------------------------------------------------------ /compare
def build_compare_embed(
    member_a: discord.Member,
    tag_a: str,
    sum_a: Optional[dict],
    stats_a: Optional[dict],
    member_b: discord.Member,
    tag_b: str,
    sum_b: Optional[dict],
    stats_b: Optional[dict],
) -> discord.Embed:
    comp_a = (sum_a or {}).get("competitive") or {}
    comp_b = (sum_b or {}).get("competitive") or {}
    color  = _embed_color(comp_a) if comp_a else _embed_color(comp_b)

    embed = discord.Embed(
        title="⚔️  玩家对比",
        color=color,
        timestamp=datetime.utcnow(),
    )

    # ── Header row ──────────────────────────────────────────────────────────
    def _header_val(member: discord.Member, tag: str, summary: Optional[dict]) -> str:
        private = (summary or {}).get("_private")
        endorse = (summary or {}).get("endorsement")
        lines   = [f"BattleTag: `{tag}`"]
        if endorse:
            lines.append(f"⭐ 信誉 Lv.{endorse}")
        if private:
            lines.append("🔒 主页私密")
        return "\n".join(lines)

    embed.add_field(
        name=f"👤 {member_a.display_name}",
        value=_header_val(member_a, tag_a, sum_a),
        inline=True,
    )
    embed.add_field(
        name=f"👤 {member_b.display_name}",
        value=_header_val(member_b, tag_b, sum_b),
        inline=True,
    )
    embed.add_field(name="\u200b", value="\u200b", inline=True)

    # ── Rank row ─────────────────────────────────────────────────────────────
    def _rank_val(comp: dict) -> str:
        if not comp:
            return "本赛季暂未参与竞技"
        lines = []
        for role in ("tank", "damage", "support"):
            rd = comp.get(role)
            if rd:
                lines.append(
                    f"{ROLE_EMOJIS[role]} {ROLE_LABELS[role]}: "
                    f"{_fmt_rank(rd.get('division', 'Unranked'), rd.get('tier', 0))}"
                )
        return "\n".join(lines) if lines else "本赛季暂未参与竞技"

    embed.add_field(name="🏅 段位", value=_rank_val(comp_a), inline=True)
    embed.add_field(name="🏅 段位", value=_rank_val(comp_b), inline=True)
    embed.add_field(name="\u200b", value="\u200b", inline=True)

    # ── Stats row ────────────────────────────────────────────────────────────
    def _stats_val(stats: Optional[dict]) -> str:
        if not stats or stats.get("_private"):
            return "数据不可用"
        played = stats.get("games_played") or 0
        won    = stats.get("games_won")    or 0
        wr     = won / played * 100 if played else 0
        return (
            f"场次: **{played:,}** · 胜率: **{wr:.1f}%**\n"
            f"⚔️ 击杀/10m: **{stats.get('eliminations_per_10', 0):.1f}**\n"
            f"💀 阵亡/10m: **{stats.get('deaths_per_10', 0):.1f}**\n"
            f"💥 伤害/10m: **{stats.get('damage_per_10', 0):,.0f}**\n"
            f"💚 治疗/10m: **{stats.get('healing_per_10', 0):,.0f}**"
        )

    embed.add_field(name="📊 战绩", value=_stats_val(stats_a), inline=True)
    embed.add_field(name="📊 战绩", value=_stats_val(stats_b), inline=True)
    embed.add_field(name="\u200b", value="\u200b", inline=True)

    embed.set_footer(text="数据来自 OverFast API · 仅供参考")
    return embed


# ----------------------------------------------------------------- /history
def build_history_embed(
    sessions: list[dict],
    guild: discord.Guild,
) -> discord.Embed:
    embed = discord.Embed(
        title=f"📜  {guild.name} · 对局历史",
        color=0x4488FF,
        timestamp=datetime.utcnow(),
    )
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)

    lines = []
    for i, s in enumerate(sessions, 1):
        dt    = _fmt_dt(s.get("started_at", ""))
        sid   = s.get("session_id", "?")
        count = s.get("participant_count", 0)
        lines.append(f"`#{i:2d}`  ⚔️ **{sid}**  ·  {dt}  ·  {count} 名玩家")

    embed.description = "\n".join(lines)
    embed.set_footer(text=f"共 {len(sessions)} 条已完成对局记录")
    return embed


# ------------------------------------------------------------------ /streak
def build_streak_embed(
    member: discord.Member,
    battletag: str,
    game_results: list[str],
) -> discord.Embed:
    if not game_results:
        embed = discord.Embed(
            title=f"📊  {member.display_name} 的连胜追踪",
            description="暂时没有找到对局记录。\n快照至少需要记录到两场游戏才能计算。",
            color=0x888888,
        )
        embed.set_footer(text=f"BattleTag: {battletag}")
        return embed

    # Current streak
    kind  = game_results[0]
    count = 0
    for r in game_results:
        if r == kind:
            count += 1
        else:
            break

    if kind == "W":
        streak_txt = f"🔥 **{count} 连胜**"
        color      = 0x44FF88
    else:
        streak_txt = f"❄️ **{count} 连败**"
        color      = 0xFF4444

    embed = discord.Embed(
        title=f"🎯  {member.display_name} 的近期连胜",
        color=color,
        timestamp=datetime.utcnow(),
    )
    embed.set_thumbnail(url=member.display_avatar.url)

    embed.add_field(name="当前状态", value=streak_txt, inline=True)

    total  = len(game_results)
    wins   = game_results.count("W")
    recent_wr = wins / total * 100 if total else 0
    embed.add_field(
        name=f"近期约 {total} 场",
        value=f"胜率 **{recent_wr:.1f}%** ({wins}胜{total - wins}负)",
        inline=True,
    )
    embed.add_field(name="\u200b", value="\u200b", inline=True)

    # Emoji trail (newest-left, up to 20)
    trail = " ".join("✅" if r == "W" else "❌" for r in game_results[:20])
    embed.add_field(
        name="近期走势  新 → 旧",
        value=trail or "—",
        inline=False,
    )

    embed.set_footer(text=f"BattleTag: {battletag}  ·  基于快照差值估算，非精确场次顺序")
    return embed


# -------------------------------------------------------------- /server-stats
def build_server_stats_embed(
    guild: discord.Guild,
    player_count: int,
    aggregated: dict,
) -> discord.Embed:
    embed = discord.Embed(
        title=f"📊  {guild.name} · 整体战况",
        color=0x9B59B6,
        timestamp=datetime.utcnow(),
    )
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)

    embed.add_field(name="👥 注册人数", value=f"**{player_count}** 名玩家", inline=True)

    # Rank distribution
    rank_dist = aggregated.get("rank_dist") or {}
    if rank_dist:
        ranked_total = sum(rank_dist.values())
        dist_lines = []
        for div in ("Champion", "Grandmaster", "Master", "Diamond",
                    "Platinum", "Gold", "Silver", "Bronze"):
            cnt = rank_dist.get(div, 0)
            if cnt:
                bar   = "█" * cnt + "░" * max(0, 5 - cnt)
                emoji = RANK_EMOJIS.get(div, "")
                dist_lines.append(f"{emoji} {div:<12} {bar}  {cnt}人")
        if dist_lines:
            embed.add_field(
                name="🏅 段位分布",
                value="```" + "\n".join(dist_lines) + "```",
                inline=False,
            )

    # Most active
    most_active = aggregated.get("most_active")
    if most_active and most_active.get("recent_games", 0) > 0:
        m = guild.get_member(int(most_active["discord_id"]))
        name = m.mention if m else f"**{most_active['battletag'].split('#')[0]}**"
        embed.add_field(
            name="🏆 近期最活跃",
            value=f"{name} — 约 **{most_active['recent_games']}** 场",
            inline=True,
        )

    # Best win rate
    best_wr = aggregated.get("best_wr_player")
    if best_wr and best_wr.get("recent_games", 0) >= 5:
        m = guild.get_member(int(best_wr["discord_id"]))
        name = m.mention if m else f"**{best_wr['battletag'].split('#')[0]}**"
        embed.add_field(
            name="📈 近期最佳胜率",
            value=f"{name} — **{best_wr['recent_wr']:.1f}%** ({best_wr['recent_games']}场)",
            inline=True,
        )

    embed.set_footer(text="数据来自本地快照 · 每30分钟自动更新")
    return embed


# ------------------------------------------------------------------ /goal show
def build_goals_embed(
    member: discord.Member,
    battletag: str,
    goals: list[dict],
    current_comp: dict,
) -> discord.Embed:
    embed = discord.Embed(
        title=f"🎯  {member.display_name} 的段位目标",
        color=_embed_color(current_comp) if current_comp else 0x4488FF,
        timestamp=datetime.utcnow(),
    )
    embed.set_thumbnail(url=member.display_avatar.url)

    goals_by_role = {g["role"]: g for g in goals}
    lines = []

    for role in ("tank", "damage", "support"):
        goal   = goals_by_role.get(role)
        cur_rd = current_comp.get(role) if current_comp else None

        if not goal:
            lines.append(f"{ROLE_EMOJIS[role]} **{ROLE_LABELS[role]}**: 未设置目标")
            continue

        goal_div  = goal["target_division"]
        goal_tier = goal["target_tier"]
        goal_txt  = _fmt_rank(goal_div, goal_tier)

        if not cur_rd or cur_rd.get("division") == "Unranked":
            progress = "暂未参与竞技，无法计算进度"
        else:
            cur_div   = cur_rd.get("division", "Unranked")
            cur_tier  = cur_rd.get("tier", 5)
            cur_txt   = _fmt_rank(cur_div, cur_tier)
            diff      = _rank_score_linear(goal_div, goal_tier) - _rank_score_linear(cur_div, cur_tier)
            if diff <= 0:
                progress = f"当前 {cur_txt} — ✅ **目标已达成！**"
            else:
                progress = f"当前 {cur_txt} — 还差 **{diff}** 小段"

        lines.append(
            f"{ROLE_EMOJIS[role]} **{ROLE_LABELS[role]}** → 目标 {goal_txt}\n"
            f"　{progress}"
        )

    embed.description = "\n\n".join(lines) if lines else "尚未设置任何目标。\n使用 `/goal set` 开始设定目标。"
    embed.set_footer(text=f"BattleTag: {battletag}")
    return embed


# ---------------------------------------------------------- weekly report
def build_weekly_report_embed(guild: discord.Guild, report: dict) -> discord.Embed:
    from datetime import timedelta
    now       = datetime.utcnow()
    week_start = (now - timedelta(days=7)).strftime("%Y-%m-%d")
    week_end   = now.strftime("%Y-%m-%d")

    embed = discord.Embed(
        title=f"📅  {guild.name} · 本周战况汇报",
        description=f"统计周期：**{week_start}** ~ **{week_end}** (UTC)",
        color=0xFFD700,
        timestamp=now,
    )
    if guild.icon:
        embed.set_thumbnail(url=guild.icon.url)

    total_g = report.get("total_games", 0)
    avg_wr  = report.get("avg_wr", 0.0)
    if total_g > 0:
        embed.add_field(
            name="🎮 本周全服",
            value=f"共打了约 **{total_g}** 场\n平均胜率 **{avg_wr:.1f}%**",
            inline=False,
        )

    most_active = report.get("most_active")
    if most_active and most_active.get("games", 0) > 0:
        m    = guild.get_member(int(most_active["discord_id"]))
        name = m.mention if m else f"**{most_active['battletag'].split('#')[0]}**"
        embed.add_field(
            name="🏆 最活跃玩家",
            value=f"{name} — 约 **{most_active['games']}** 场",
            inline=True,
        )

    best_wr = report.get("best_wr_player")
    if best_wr and best_wr.get("games", 0) >= 5:
        m    = guild.get_member(int(best_wr["discord_id"]))
        name = m.mention if m else f"**{best_wr['battletag'].split('#')[0]}**"
        embed.add_field(
            name="📈 本周最佳胜率",
            value=f"{name} — **{best_wr['wr']:.1f}%** ({best_wr['games']}场)",
            inline=True,
        )

    worst_wr = report.get("worst_wr_player")
    if worst_wr and worst_wr.get("games", 0) >= 5 and worst_wr.get("wr", 100) < 45:
        m    = guild.get_member(int(worst_wr["discord_id"]))
        name = m.mention if m else f"**{worst_wr['battletag'].split('#')[0]}**"
        embed.add_field(
            name="😅 本周大冤种",
            value=f"{name} — **{worst_wr['wr']:.1f}%** ({worst_wr['games']}场)",
            inline=True,
        )

    rank_changes = report.get("rank_changes") or []
    if rank_changes:
        change_lines = []
        for rc in rank_changes[:8]:
            m    = guild.get_member(int(rc["discord_id"]))
            name = m.mention if m else f"**{rc['battletag'].split('#')[0]}**"
            for ch in rc["changes"]:
                change_lines.append(f"{name}: {ch}")
        if change_lines:
            embed.add_field(
                name="🏅 本周段位变化",
                value="\n".join(change_lines),
                inline=False,
            )

    if total_g == 0 and not most_active:
        embed.description = (
            f"统计周期：**{week_start}** ~ **{week_end}** (UTC)\n\n"
            "本周没有收集到足够的对局数据。"
        )

    embed.set_footer(text="数据基于每30分钟快照估算 · 每周一 UTC 自动推送")
    return embed


# ------------------------------------------------------------------ /lookup
def build_lookup_embed(
    battletag: str,
    summary: dict,
    stats: Optional[dict],
) -> discord.Embed:
    comp  = summary.get("competitive") or {}
    color = _embed_color(comp)

    username = summary.get("username") or battletag.split("#")[0]
    embed = discord.Embed(
        title=f"🔍  {username} 的战绩",
        color=color,
        timestamp=datetime.utcnow(),
    )

    avatar = summary.get("avatar", "")
    if avatar:
        embed.set_thumbnail(url=avatar)

    embed.add_field(name="🎮 BattleTag", value=f"`{battletag}`", inline=True)
    endorse = summary.get("endorsement")
    embed.add_field(
        name="⭐ 信誉等级",
        value=f"Lv.{endorse}" if endorse else "—",
        inline=True,
    )
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
        won    = stats.get("games_won")    or 0
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


def _rank_history_strip(snapshots: list[dict]) -> str:
    """Build an emoji strip showing rank progression, oldest → newest."""
    ordered = list(reversed(snapshots))
    emojis  = []
    for snap in ordered:
        cd = snap.get("competitive_data")
        if not isinstance(cd, dict):
            continue
        best_div, best_score = "Unranked", 0
        for rd in cd.values():
            if not isinstance(rd, dict):
                continue
            div   = rd.get("division", "Unranked")
            tier  = rd.get("tier", 5)
            score = RANK_ORDER.get(div, 0) * 10 + (6 - tier)
            if score > best_score:
                best_div, best_score = div, score
        emojis.append(RANK_EMOJIS.get(best_div, "❓"))

    if not emojis:
        return ""
    # Show last 10 data points to keep embed compact
    return " → ".join(emojis[-10:])
