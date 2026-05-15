"""Unit tests for compute_top_drop helper (no Discord/network/db dependencies)."""
from __future__ import annotations

from cogs.miner import compute_top_drop


def _drop(id="d1", current_minutes=10, required_minutes=60, is_claimed=False, progress=0.5, name="Drop"):
    return {
        "id": id,
        "name": name,
        "current_minutes": current_minutes,
        "required_minutes": required_minutes,
        "is_claimed": is_claimed,
        "progress": progress,
    }


def _campaign(linked=True, active=True, name="Camp", game_name="Overwatch", drops=None):
    return {
        "name": name,
        "game_name": game_name,
        "linked": linked,
        "active": active,
        "drops": drops or [],
    }


def test_compute_top_drop_empty():
    """Empty campaigns → None."""
    assert compute_top_drop({"campaigns": []}) is None


def test_compute_top_drop_unlinked_filtered():
    """linked=False campaigns are filtered out."""
    data = {"campaigns": [_campaign(linked=False, drops=[_drop(progress=0.9)])]}
    assert compute_top_drop(data) is None


def test_compute_top_drop_inactive_filtered():
    """active=False campaigns are filtered out."""
    data = {"campaigns": [_campaign(active=False, drops=[_drop(progress=0.9)])]}
    assert compute_top_drop(data) is None


def test_compute_top_drop_zero_progress_filtered():
    """Drops with current_minutes=0 are filtered out (not yet started)."""
    data = {"campaigns": [_campaign(drops=[_drop(current_minutes=0, progress=0.0)])]}
    assert compute_top_drop(data) is None


def test_compute_top_drop_claimed_filtered():
    """Already-claimed drops are filtered out."""
    data = {"campaigns": [_campaign(drops=[_drop(is_claimed=True, progress=0.9)])]}
    assert compute_top_drop(data) is None


def test_compute_top_drop_pick_highest():
    """When multiple in-progress drops exist, the highest-progress one wins."""
    data = {"campaigns": [_campaign(drops=[
        _drop(id="dA", progress=0.3, name="A"),
        _drop(id="dB", progress=0.8, name="B"),
        _drop(id="dC", progress=0.5, name="C"),
    ])]}
    top = compute_top_drop(data)
    assert top is not None
    assert top["id"] == "dB"
    assert top["drop_name"] == "B"


def test_compute_top_drop_returns_all_fields():
    """The returned dict contains all required fields with correct types."""
    data = {"campaigns": [_campaign(
        name="OWCS S1",
        game_name="Overwatch",
        drops=[_drop(id="d42", current_minutes=120, required_minutes=180, progress=0.667, name="Zenyatta Spray")],
    )]}
    top = compute_top_drop(data)
    assert top is not None
    assert top["id"] == "d42"
    assert top["drop_name"] == "Zenyatta Spray"
    assert top["game"] == "Overwatch"
    assert top["campaign"] == "OWCS S1"
    assert top["current_min"] == 120
    assert top["required_min"] == 180
    assert top["progress"] == 0.667
    assert isinstance(top["progress"], float)


def test_compute_top_drop_skips_missing_id():
    """A drop with id=None / empty string is skipped — must NOT win top.

    Without this guard, set_last_top_drop(None) would reset the row's
    last_top_drop_id back to NULL and silently swallow the next real switch.
    """
    data = {"campaigns": [_campaign(drops=[
        _drop(id=None, progress=0.99, name="malformed"),
        _drop(id="", progress=0.95, name="also malformed"),
        _drop(id="d_real", progress=0.10, name="real but low"),
    ])]}
    top = compute_top_drop(data)
    assert top is not None
    assert top["id"] == "d_real"
    assert top["drop_name"] == "real but low"
