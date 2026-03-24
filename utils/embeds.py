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

    title_str = stats.get("title") or ""
    title_line = f"「{title_str}」" if title_str else ""

    embed = discord.Embed(
        title=f"📊  {stats.get('username', member.display_name)} 的战绩",
        description=title_line or None,
        color=color,
        timestamp=_now(),
    )
    embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)
    avatar = stats.get("avatar", "")
    embed.set_thumbnail(url=avatar or member.display_avatar.url)

    # Namecard as banner image
    namecard = stats.get("namecard", "")
    if namecard:
        embed.set_image(url=namecard)

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

    # -- Highlights / fun stats --
    highlights = []
    mk = career.get("multikill_best", 0)
    if mk >= 3:
        highlights.append(f"💣 最高多杀: **{mk}连**")
    env = career.get("environmental_kills", 0)
    if env:
        highlights.append(f"🕳️ 环境击杀: **{env}**")
    fire = career.get("time_spent_on_fire", 0)
    if fire:
        fire_pct = career.get("on_fire_pct", 0)
        pct_str = f" ({fire_pct}%)" if fire_pct else ""
        highlights.append(f"🔥 火力全开: **{_fmt_time(fire)}**{pct_str}")
    obj_kills = career.get("objective_kills", 0)
    if obj_kills:
        highlights.append(f"🎯 目标击杀: **{obj_kills}**")
    solo = career.get("solo_kills", 0)
    if solo:
        highlights.append(f"🗡️ 单独击杀: **{solo}**")
    melee = career.get("melee_final_blows", 0)
    if melee:
        highlights.append(f"👊 近战终结: **{melee}**")
    cards = career.get("cards", 0)
    if cards:
        highlights.append(f"🃏 获得卡片: **{cards}**")
    if highlights:
        embed.add_field(
            name="✨ 亮点数据",
            value="\n".join(highlights),
            inline=False,
        )

    # -- Top heroes --
    top_heroes = stats.get("top_heroes") or []
    if top_heroes:
        lines = []
        for h in top_heroes[:5]:
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
) -> discord.Embed:
    embed = discord.Embed(
        title=f"🎮  {member.display_name} 的 Overwatch ID",
        color=0x4488FF,
        timestamp=_now(),
    )
    embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)
    embed.set_thumbnail(url=member.display_avatar.url)

    embed.add_field(name="BattleTag", value=f"`{battletag}`", inline=True)
    if label:
        embed.add_field(name="备注", value=label, inline=True)

    embed.set_footer(text="复制 BattleTag 即可添加好友")
    return embed


# Hero-specific stat key → Chinese label
_HERO_STAT_LABELS: dict[str, str] = {
    # Common ability stats
    "helix_rocket_kills": "螺旋飞弹击杀",
    "helix_rocket_accuracy": "螺旋飞弹命中率",
    "tactical_visor_kills": "战术目镜击杀",
    "self_healing": "自我治疗",
    "long_range_final_blows": "远程终结",
    "self_destruct_kills": "自毁击杀",
    "micro_missile_kills": "微型飞弹击杀",
    "call_mech_kills": "召唤机甲击杀",
    "graviton_surge_kills": "引力弹击杀",
    "high_energy_kills": "高能量击杀",
    "average_energy": "平均能量",
    "primary_fire_accuracy": "主武器命中率",
    "secondary_fire_accuracy": "副武器命中率",
    "charged_shot_kills": "蓄力射击击杀",
    "overclock_kills": "超频击杀",
    "disruptor_shot_kills": "干扰射击击杀",
    "charged_shot_accuracy": "蓄力射击命中率",
    "fire_strike_kills": "烈焰打击击杀",
    "charge_kills": "冲锋击杀",
    "earthshatter_kills": "裂地猛击击杀",
    "rocket_hammer_melee_accuracy": "火箭锤命中率",
    "primal_rage_kills": "原始暴怒击杀",
    "jump_pack_kills": "喷射背包击杀",
    "players_knocked_back": "击退玩家",
    "damage_blocked": "伤害阻挡",
    "damage_absorbed": "伤害吸收",
    "scoped_accuracy": "开镜命中率",
    "scoped_critical_hit_accuracy": "开镜暴击率",
    "nano_boost_assists": "纳米激素助攻",
    "enemies_slept": "催眠敌人",
    "biotic_grenade_kills": "生物手雷击杀",
    "dragon_blade_kills": "龙刃击杀",
    "dragonblade_kills": "龙刃击杀",
    "deflection_kills": "招架击杀",
    "swift_strike_kills": "影击杀",
    "dragonstrike_kills": "龙矢击杀",
    "storm_arrow_kills": "岚矢击杀",
    "deadeye_kills": "神射击杀",
    "fan_the_hammer_kills": "转轮击杀",
    "magnetic_grenade_kills": "磁力手雷击杀",
    "death_blossom_kills": "死亡绽放击杀",
    "teleporter_pads_destroyed": "传送面板摧毁",
    "players_teleported": "传送玩家",
    "sentry_turret_kills": "哨戒炮击杀",
    "players_saved": "拯救玩家",
    "resurrection_assists": "复活助攻",
    "blaster_kills": "冲击枪击杀",
    "coalescence_kills": "聚合射线击杀",
    "coalescence_healing": "聚合射线治疗",
    "biotic_orb_kills": "生化之珠击杀",
    "biotic_orb_healing": "生化之珠治疗",
    "sound_barriers_provided": "音障提供",
    "sonic_amplifier_kills": "音波枪击杀",
    "bob_kills": "鲍勃击杀",
    "dynamite_kills": "延时雷管击杀",
    "coach_gun_kills": "散弹枪击杀",
    "duplicate_kills": "复制击杀",
    "sticky_bombs_kills": "粘性炸弹击杀",
    "focusing_beam_kills": "聚焦光线击杀",
    "overclock_kills": "超频击杀",
    "meteor_strike_kills": "毁天灭地击杀",
    "shields_created": "护盾创建",
    "enemies_emp_d": "EMP影响敌人",
    "enemies_hacked": "入侵敌人",
    "whole_hog_kills": "全面猪攻击杀",
    "hook_accuracy": "钩锁命中率",
    "enemies_hooked": "钩中敌人",
    "hook_kills": "钩锁击杀",
    "accretion_kills": "质量吸附击杀",
    "gravitic_flux_kills": "重力坍缩击杀",
    "terra_surge_kills": "拉玛刹大招击杀",
    "minefield_kills": "地雷击杀",
    "grappling_claw_kills": "抓钩击杀",
    "piledriver_kills": "重力坠击击杀",
    "kitsune_rush_assists": "狐灵冲刺助攻",
    "kunai_kills": "苦无击杀",
    "suzu_saves": "铃铛拯救",
    "petal_platform_saves": "花瓣平台拯救",
    "tree_of_life_healing": "生命之树治疗",
    "thorn_volley_kills": "荆棘齐射击杀",
    "javelin_kills": "标枪击杀",
    "energy_javelin_kills": "能量标枪击杀",
    "fortify_damage_blocked": "强固伤害阻挡",
    "spike_kills": "尖刺击杀",
    "overclock_kills_most_in_game": "单局最多超频击杀",
    "railgun_kills": "磁轨炮击杀",
    "railgun_critical_hits": "磁轨炮暴击",
    "solar_rifle_kills": "日光步枪击杀",
    "captive_sun_kills": "囚日击杀",
    "healing_pylon_healing_done": "治疗晶塔治疗量",
    "stellar_flare_kills": "星耀击杀",
    "glide_kills": "滑翔击杀",
    "orbital_ray_assists": "天穹光线助攻",
    "orbital_ray_kills": "天穹光线击杀",
    "hyper_rounds_kills": "超级弹药击杀",
    "pulsar_torpedoes_kills": "脉冲鱼雷击杀",
    "clobber_kills": "锤击击杀",
    "drill_dash_kills": "钻地冲刺击杀",
    "burrow_damage_done": "钻地伤害",
}


def _format_hero_stat(key: str, value: Any) -> Optional[str]:
    """Format a hero_specific stat into a readable line. Skip per-10 and most-in-game variants."""
    # Skip avg_per_10_min and most_in_game variants (we show them separately if needed)
    if "avg_per_10_min" in key or "most_in_game" in key or "most_in_life" in key:
        return None
    label = _HERO_STAT_LABELS.get(key, key.replace("_", " ").title())
    if isinstance(value, float):
        return f"**{label}**: {value:.1f}"
    if isinstance(value, int) and "accuracy" in key:
        return f"**{label}**: {value}%"
    return f"**{label}**: {value:,}" if isinstance(value, (int, float)) else f"**{label}**: {value}"


# ── /hero ─────────────────────────────────────────────────────────────────────
def _mode_block(cd: dict, mode_label: str) -> Optional[str]:
    """Build a compact text block for one gamemode's career stats."""
    game = cd.get("game") or {}
    gp = game.get("games_played", 0)
    if not gp:
        return None
    avg = cd.get("average") or {}
    best = cd.get("best") or {}
    combat = cd.get("combat") or {}

    lines = [f"**场次:** {gp}　**胜率:** {game.get('win_percentage', 0)}%"]

    e10 = avg.get("eliminations_avg_per_10_min", 0)
    d10 = avg.get("hero_damage_done_avg_per_10_min", 0)
    if e10:
        lines.append(f"每10分钟 — 击杀: {e10:.1f}　伤害: {d10:,.0f}")

    eb = best.get("eliminations_most_in_game", 0)
    ks = best.get("kill_streak_best", 0)
    if eb:
        lines.append(f"单局最高击杀: **{eb}**　最长连杀: **{ks}**")

    acc = combat.get("weapon_accuracy", 0)
    if acc:
        lines.append(f"命中率: **{acc}%**")
    return "\n".join(lines)


def build_hero_embed(
    member: discord.Member,
    data: dict[str, Any],
) -> discord.Embed:
    """Build a detailed hero stats embed."""
    hero_key = data.get("hero_key", "")
    hero_cn = _hero_name(hero_key)
    overview = data.get("overview") or {}

    embed = discord.Embed(
        title=f"🦸  {data.get('username', member.display_name)} · {hero_cn}",
        color=0x4488FF,
        timestamp=_now(),
    )
    embed.set_author(name=member.display_name, icon_url=member.display_avatar.url)

    # Use hero portrait as thumbnail (fallback to player avatar)
    hero_portrait = data.get("hero_portrait", "")
    avatar = data.get("avatar", "")
    embed.set_thumbnail(url=hero_portrait or avatar or member.display_avatar.url)

    # No banner image for hero embed — keep it clean

    if not overview or not overview.get("games_played"):
        embed.description = f"没有找到 {hero_cn} 的游戏数据。"
        return embed

    # -- Overview (combined all modes) --
    played = overview.get("games_played", 0)
    won = overview.get("games_won", 0)
    lost = overview.get("games_lost", 0)
    wr = overview.get("winrate", 0)
    kda = overview.get("kda", 0)
    embed.add_field(
        name="📊 总览（全模式）",
        value=(
            f"场次: **{played}**　胜/负: **{won}**/**{lost}**\n"
            f"胜率: **{wr:.1f}%** {_bar(wr)}\n"
            f"KDA: **{kda:.2f}**\n"
            f"游戏时间: **{_fmt_time(overview.get('time_played', 0))}**"
        ),
        inline=False,
    )

    # Per-game averages
    embed.add_field(
        name="📈 场均数据",
        value=(
            f"⚔️ 击杀: **{overview.get('avg_eliminations', 0):.1f}**\n"
            f"💀 阵亡: **{overview.get('avg_deaths', 0):.1f}**\n"
            f"💥 伤害: **{overview.get('avg_damage', 0):,.0f}**\n"
            f"💚 治疗: **{overview.get('avg_healing', 0):,.0f}**"
        ),
        inline=True,
    )

    # Spacer to push mode blocks to new row
    embed.add_field(name="\u200b", value="\u200b", inline=True)

    # -- Competitive & Quickplay side by side --
    comp_block = _mode_block(data.get("competitive") or {}, "竞技")
    qp_block = _mode_block(data.get("quickplay") or {}, "快速")

    if comp_block:
        embed.add_field(name="🎮 竞技模式", value=comp_block, inline=True)
    if qp_block:
        embed.add_field(name="🎮 快速模式", value=qp_block, inline=True)

    # -- Hero-specific ability stats --
    hero_spec: dict[str, Any] = {}
    for mode_key in ("quickplay", "competitive"):
        cd = data.get(mode_key) or {}
        hs = cd.get("hero_specific") or {}
        hero_spec.update(hs)

    if hero_spec:
        lines = []
        for k, v in hero_spec.items():
            formatted = _format_hero_stat(k, v)
            if formatted:
                lines.append(formatted)
        if lines:
            if len(lines) > 8:
                mid = (len(lines) + 1) // 2
                embed.add_field(
                    name="⚡ 英雄专属数据",
                    value="\n".join(lines[:mid]),
                    inline=True,
                )
                embed.add_field(
                    name="⚡ 续",
                    value="\n".join(lines[mid:]),
                    inline=True,
                )
            else:
                embed.add_field(
                    name="⚡ 英雄专属数据",
                    value="\n".join(lines),
                    inline=False,
                )

    embed.set_footer(text="数据来自 OverFast API · 竞技+快速合并 · 仅供参考")
    return embed
