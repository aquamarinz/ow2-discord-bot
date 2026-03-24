"""
Role-aware scoring for match analysis.

Input:  list of player delta dicts (stats gained during one match session)
Output: scored + titled player list, sorted best → worst
"""
from typing import Any

# Expected stats per game, used as normalization baselines
_BASELINES: dict[str, dict[str, float]] = {
    "tank":    {"eliminations": 12, "deaths": 6, "damage_dealt": 9_000,  "healing_done": 500},
    "damage":  {"eliminations": 20, "deaths": 6, "damage_dealt": 12_000, "healing_done": 200},
    "support": {"eliminations":  8, "deaths": 5, "damage_dealt":  3_000, "healing_done": 9_000},
}

# Per-role contribution weights (positive = good, negative = bad)
_WEIGHTS: dict[str, dict[str, float]] = {
    "tank":    {"eliminations": 0.20, "deaths": -0.35, "damage_dealt": 0.25, "healing_done": 0.05, "win": 0.15},
    "damage":  {"eliminations": 0.35, "deaths": -0.30, "damage_dealt": 0.35, "healing_done": 0.00, "win": 0.15},
    "support": {"eliminations": 0.05, "deaths": -0.30, "damage_dealt": 0.05, "healing_done": 0.45, "win": 0.15},
}


def infer_role(delta: dict[str, Any]) -> str:
    """Guess a player's role from their match stats delta."""
    healing = delta.get("healing_done") or 0
    damage  = delta.get("damage_dealt")  or 0
    elims   = delta.get("eliminations")  or 0

    if healing >= 3_000:
        return "support"
    if damage >= 6_000 and elims < 10:
        return "tank"
    return "damage"


def _normalize(value: float, baseline: float) -> float:
    """Map a raw value to a 0–2 scale relative to its baseline."""
    if baseline <= 0:
        return 0.0
    return min(2.0, value / baseline)


def compute_scores(player_deltas: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Assign a 0–100 performance score to each player.
    Returns list sorted best → worst.
    """
    scored = []
    for d in player_deltas:
        role     = d.get("inferred_role") or infer_role(d)
        weights  = _WEIGHTS.get(role,  _WEIGHTS["damage"])
        baseline = _BASELINES.get(role, _BASELINES["damage"])

        elims   = float(d.get("eliminations")  or 0)
        deaths  = float(d.get("deaths")        or 0)
        damage  = float(d.get("damage_dealt")  or 0)
        healing = float(d.get("healing_done")  or 0)
        won     = bool(d.get("games_won"))

        raw = (
            weights["eliminations"] * _normalize(elims,   baseline["eliminations"]) * 50
            + weights["deaths"]     * _normalize(deaths,  baseline["deaths"])       * 50
            + weights["damage_dealt"] * _normalize(damage,  baseline["damage_dealt"]) * 50
            + weights["healing_done"] * _normalize(healing, baseline["healing_done"]) * 50
            + weights["win"]        * (1.5 if won else 0.5)                          * 50
        )
        # Centre around 50 and clamp
        score = max(0.0, min(100.0, raw + 50))

        scored.append({
            **d,
            "role":    role,
            "elims":   int(elims),
            "deaths":  int(deaths),
            "damage":  int(damage),
            "healing": int(healing),
            "won":     won,
            "score":   round(score, 1),
            "title":   None,
        })

    scored.sort(key=lambda p: p["score"], reverse=True)
    return scored


def assign_titles(scored: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Stamp fun titles onto the scored list.
      战神  – highest composite score
      战犯  – most deaths relative to contribution (not the same player as 战神)
      唐    – lowest role-normalised score among the remaining middle pack
    """
    if not scored:
        return scored

    result = [dict(p) for p in scored]

    # --- 战神 ---
    result[0].update(
        title="战神",
        title_emoji="🏆",
        title_color=0xFFD700,
        title_reason=_reason_warlord(result[0]),
    )

    # --- 战犯: highest "feeder score" = deaths*3 – score*0.3 ---
    feeder_scores = [p["deaths"] * 3 - p["score"] * 0.3 for p in result]
    feeder_idx    = feeder_scores.index(max(feeder_scores))
    if feeder_idx == 0 and len(result) > 1:
        feeder_idx = 1  # Don't double-assign 战神
    result[feeder_idx].update(
        title="战犯",
        title_emoji="☠️",
        title_color=0xFF4444,
        title_reason=_reason_feeder(result[feeder_idx]),
    )

    # --- 唐: worst score among unassigned players (requires ≥3 players) ---
    unassigned = [p for p in result if p["title"] is None]
    if unassigned:
        tang = min(unassigned, key=lambda p: p["score"])
        tang_idx = next(i for i, p in enumerate(result) if p is tang)
        result[tang_idx].update(
            title="唐",
            title_emoji="😅",
            title_color=0x9B59B6,
            title_reason=_reason_tang(result[tang_idx]),
        )

    # --- default label for everyone else ---
    for p in result:
        if p["title"] is None:
            p.update(
                title="普通战士",
                title_emoji="⚔️",
                title_color=0x4488FF,
                title_reason="中规中矩的表现",
            )

    return result


# ------------------------------------------------------------------ reason strings
def _reason_warlord(p: dict) -> str:
    role = p.get("role", "damage")
    if role == "support":
        return f"治疗 {p['healing']:,} · 奶盾全队制胜"
    if role == "tank":
        return f"击杀 {p['elims']} · 坦线无可撼动"
    return f"击杀 {p['elims']} · 伤害 {p['damage']:,}"


def _reason_feeder(p: dict) -> str:
    return f"阵亡 {p['deaths']} 次 · 综合得分 {p['score']:.0f}"


def _reason_tang(p: dict) -> str:
    role = p.get("role", "damage")
    if role == "support":
        return f"治疗量 {p['healing']:,} · 奶妈效率有待提升"
    if role == "tank":
        return f"坦克贡献不足 · 得分 {p['score']:.0f}"
    return f"输出 {p['damage']:,} · 伤害担当末位"
