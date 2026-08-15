"""Unit tests for diff_tick — pure notifier state transition (no I/O)."""
from __future__ import annotations

from cogs.miner import diff_tick, DROPS_STATE_CAP, MINING_STATE_CAP


def _c(cid="c1", name="OWCS Day 3", game="Overwatch", linked=True, active=True,
       drops=()):
    return {"id": cid, "name": name, "game_name": game,
            "linked": linked, "active": active, "drops": list(drops)}


def _d(did="d1", name="Esports Loot Box", claimed=False, minutes=10,
       image="https://cdn.example/img.png"):
    return {"id": did, "name": name, "is_claimed": claimed,
            "current_minutes": minutes,
            "benefits": [{"image_url": image}]}


def _payload(*campaigns):
    return {"campaigns": list(campaigns)}


# ── payload validity (§3.2 gate / spec test 9) ──────────────────────

def test_invalid_payload_returns_none():
    assert diff_tick(None, "nope") is None
    assert diff_tick(None, {}) is None
    assert diff_tick(None, {"campaigns": "x"}) is None


# ── baseline (§3.1 / spec test 2) ───────────────────────────────────

def test_baseline_is_silent_and_records():
    st, claims, camps = diff_tick(
        None, _payload(_c(drops=[_d(claimed=True), _d(did="d2")])))
    assert claims == [] and camps == []
    assert st["drops"] == {"d1": True, "d2": False}
    assert st["mining"] == {"c1"}


# ── claim transition (spec tests 1, 6) ──────────────────────────────

def test_claim_transition_fires_once():
    st0, _, _ = diff_tick(None, _payload(_c(drops=[_d()])))
    st1, claims, _ = diff_tick(st0, _payload(_c(drops=[_d(claimed=True)])))
    assert len(claims) == 1
    g = claims[0]
    assert g["campaign"] == "OWCS Day 3"
    assert g["drops"] == ["Esports Loot Box"]
    assert g["done"] is True          # only drop of campaign now claimed
    assert g["image_url"] == "https://cdn.example/img.png"
    # same payload again → no repeat
    _, claims2, _ = diff_tick(st1, _payload(_c(drops=[_d(claimed=True)])))
    assert claims2 == []


def test_first_seen_already_claimed_is_silent():
    st0, _, _ = diff_tick(None, _payload(_c(drops=[_d()])))
    # a NEW drop appears already claimed → record, no event (§3.2 R1-M1)
    _, claims, _ = diff_tick(
        st0, _payload(_c(drops=[_d(), _d(did="dX", claimed=True)])))
    assert claims == []


def test_multi_claims_same_tick_grouped_by_campaign():
    p0 = _payload(_c(drops=[_d(), _d(did="d2", name="Icon")]),
                  _c(cid="c2", name="S3", drops=[_d(did="d3", name="Spray")]))
    st0, _, _ = diff_tick(None, p0)
    p1 = _payload(_c(drops=[_d(claimed=True), _d(did="d2", name="Icon")]),
                  _c(cid="c2", name="S3", drops=[_d(did="d3", name="Spray",
                                                    claimed=True)]))
    _, claims, _ = diff_tick(st0, p1)
    assert [g["campaign"] for g in claims] == ["OWCS Day 3", "S3"]
    assert claims[0]["done"] is False    # d2 still unclaimed
    assert claims[1]["done"] is True


# ── claim ignores linked/active flags (spec tests 7, 17) ────────────

def test_claim_fires_even_when_inactive_or_unlinked():
    st0, _, _ = diff_tick(None, _payload(_c(drops=[_d()])))
    _, claims, _ = diff_tick(
        st0, _payload(_c(linked=False, active=False, drops=[_d(claimed=True)])))
    assert len(claims) == 1 and claims[0]["done"] is True


# ── campaign events (spec tests 3, 5, 13) ───────────────────────────

def test_new_campaign_with_progress_announces_once():
    st0, _, _ = diff_tick(None, _payload(_c(drops=[_d()])))
    p1 = _payload(_c(drops=[_d()]),
                  _c(cid="c2", name="Day 4", drops=[_d(did="d9", minutes=1)]))
    st1, _, camps = diff_tick(st0, p1)
    assert len(camps) == 1
    ev = camps[0]
    assert ev["campaign"] == "Day 4" and ev["game"] == "Overwatch"
    assert ev["drop_count"] == 1
    assert ev["id"] == "c2"
    # progress → 0 → back, and transient disappearance → never re-announce
    st2, _, camps2 = diff_tick(st1, _payload(_c(drops=[_d()])))
    assert camps2 == []
    _, _, camps3 = diff_tick(st2, p1)
    assert camps3 == []


def test_campaign_without_progress_not_announced():
    st0, _, _ = diff_tick(None, _payload(_c(drops=[_d()])))
    _, _, camps = diff_tick(
        st0, _payload(_c(drops=[_d()]),
                      _c(cid="c2", name="Idle", drops=[_d(did="d9", minutes=0)])))
    assert camps == []


def test_inactive_campaign_not_announced():
    st0, _, _ = diff_tick(None, _payload(_c(drops=[_d()])))
    _, _, camps = diff_tick(
        st0, _payload(_c(drops=[_d()]),
                      _c(cid="c2", name="Ended", active=False,
                         drops=[_d(did="d9", minutes=5)])))
    assert camps == []


# ── merge semantics (spec tests 10, 13) ─────────────────────────────

def test_empty_then_full_no_false_events():
    st0, _, _ = diff_tick(None, _payload(_c(drops=[_d(claimed=True)])))
    st1, claims1, camps1 = diff_tick(st0, _payload())          # empty list tick
    assert claims1 == [] and camps1 == []
    assert st1["drops"] == {"d1": True} and st1["mining"] == {"c1"}  # no forgetting
    _, claims2, camps2 = diff_tick(st1, _payload(_c(drops=[_d(claimed=True)])))
    assert claims2 == [] and camps2 == []


def test_absent_then_reappear_claimed_still_fires():
    st0, _, _ = diff_tick(None, _payload(_c(drops=[_d()])))
    st1, _, _ = diff_tick(st0, _payload())                     # drop absent
    _, claims, _ = diff_tick(st1, _payload(_c(drops=[_d(claimed=True)])))
    assert len(claims) == 1                                    # memory retained


# ── missing ids skipped (spec test 16) ──────────────────────────────

def test_missing_ids_skipped_not_crash():
    p = _payload({"name": "no-id", "active": True, "drops": [_d()]},
                 _c(drops=[{"name": "no-id-drop", "is_claimed": True,
                            "current_minutes": 5}, _d()]))
    st, claims, camps = diff_tick(None, p)
    assert st["drops"] == {"d1": False}
    assert st["mining"] == {"c1"}
    assert claims == [] and camps == []


def test_non_string_ids_skipped_not_crash():
    p = _payload(_c(cid=[1], drops=[_d()]),
                 _c(drops=[_d(did=123), _d(did="d2")]))
    st, claims, camps = diff_tick(None, p)
    assert st["drops"] == {"d2": False}
    assert st["mining"] == {"c1"}
    assert claims == [] and camps == []


def test_non_numeric_current_minutes_is_not_progress():
    st, claims, camps = diff_tick(
        None, _payload(_c(drops=[_d(minutes="1")])))
    assert st["drops"] == {"d1": False}
    assert st["mining"] == set()
    assert claims == [] and camps == []


# ── hygiene caps (§3.1) ─────────────────────────────────────────────

def test_drops_cap_sweeps_absent_entries():
    big = {f"old{i}": False for i in range(DROPS_STATE_CAP + 1)}
    st = {"drops": big, "mining": set()}
    st1, _, _ = diff_tick(st, _payload(_c(drops=[_d()])))
    assert st1["drops"] == {"d1": False}


def test_mining_cap_sweeps_absent_entries():
    big = {f"old{i}" for i in range(MINING_STATE_CAP + 1)}
    st = {"drops": {}, "mining": big}
    st1, _, _ = diff_tick(st, _payload(_c(drops=[_d()])))
    assert st1["mining"] == {"c1"}


# ── campaign_events enrichment (2026-08-15 spec §3.1 / test 1) ──────

def test_campaign_event_carries_details():
    st0, _, _ = diff_tick(None, _payload(_c(drops=[_d()])))
    c2 = _c(cid="c2", name="Day 4", drops=[
        _d(did="d9", name="Spray", minutes=1),
        _d(did="d10", name="Icon", minutes=0),
    ])
    c2["game_box_art_url"] = "https://cdn.example/box-120x160.jpg"
    c2["drops"][0]["required_minutes"] = 60
    c2["drops"][1]["required_minutes"] = 480
    _, _, camps = diff_tick(st0, _payload(_c(drops=[_d()]), c2))
    ev = camps[0]
    assert ev["id"] == "c2"
    assert ev["box_art_url"] == "https://cdn.example/box-120x160.jpg"
    assert ev["drops"] == [
        {"name": "Spray", "required_minutes": 60,
         "image_url": "https://cdn.example/img.png"},
        {"name": "Icon", "required_minutes": 480,
         "image_url": "https://cdn.example/img.png"},
    ]


def test_campaign_event_drops_skip_invalid():
    st0, _, _ = diff_tick(None, _payload(_c(drops=[_d()])))
    c2 = _c(cid="c2", drops=[
        {"name": "no-id", "current_minutes": 5},          # 缺 id → 不进 drops
        _d(did="d9", name="", minutes=1),                 # falsy name → "?"
        _d(did="d10", minutes=2),
    ])
    c2["drops"][1]["required_minutes"] = "120"            # 非数值 → None
    c2["drops"][2]["required_minutes"] = -5               # 负数 → None
    _, _, camps = diff_tick(st0, _payload(_c(drops=[_d()]), c2))
    ev = camps[0]
    assert ev["drop_count"] == 2                          # n_valid 口径不变
    assert [d["name"] for d in ev["drops"]] == ["?", "Esports Loot Box"]
    assert [d["required_minutes"] for d in ev["drops"]] == [None, None]


def test_campaign_event_required_minutes_bool_is_none():
    st0, _, _ = diff_tick(None, _payload(_c(drops=[_d()])))
    c2 = _c(cid="c2", drops=[_d(did="d9", minutes=1)])
    c2["drops"][0]["required_minutes"] = True             # bool 不算数值
    _, _, camps = diff_tick(st0, _payload(_c(drops=[_d()]), c2))
    assert camps[0]["drops"][0]["required_minutes"] is None
