"""Unit tests for notifier message builders (spec §3.5, §3.3 budget)."""
from __future__ import annotations

from cogs.miner import (
    NOTIFY_CONTENT_BUDGET,
    build_claim_message,
    build_campaign_message,
)


def test_claim_message_single_group():
    content, img = build_claim_message("42", [{
        "campaign": "OWCS Day 3", "drops": ["Esports Loot Box"],
        "done": False, "image_url": "https://cdn.example/x.png"}])
    assert content == (
        "<@42> 🎉 已领取掉宝:**Esports Loot Box** _(OWCS Day 3)_")
    assert img == "https://cdn.example/x.png"


def test_claim_message_multi_group_done_marker():
    content, img = build_claim_message("42", [
        {"campaign": "A", "drops": ["D1", "D2"], "done": True, "image_url": None},
        {"campaign": "B", "drops": ["D3"], "done": False,
         "image_url": "https://cdn.example/b.png"},
    ])
    assert content == (
        "<@42> 🎉 已领取掉宝:**D1**、**D2** _(A)_ ✅ 全部领完\n"
        "**D3** _(B)_")
    assert img == "https://cdn.example/b.png"   # first non-None wins


def test_campaign_message():
    content = build_campaign_message("42", [
        {"campaign": "Day 4", "game": "Overwatch", "drop_count": 5}])
    assert content == (
        "<@42> ⛏️ 开始挖新活动:**Day 4** _(Overwatch · 5 个掉宝)_")


def test_campaign_message_multi_joined():
    content = build_campaign_message("42", [
        {"campaign": "X", "game": "OW", "drop_count": 1},
        {"campaign": "Y", "game": "BF6", "drop_count": 2}])
    assert content == (
        "<@42> ⛏️ 开始挖新活动:**X** _(OW · 1 个掉宝)_、**Y** _(BF6 · 2 个掉宝)_")


def test_claim_message_truncated_at_budget():
    groups = [{"campaign": f"C{i}", "drops": [f"Drop-{i}-" + "x" * 40],
               "done": False, "image_url": None} for i in range(60)]
    content, _ = build_claim_message("42", groups)
    assert len(content) <= NOTIFY_CONTENT_BUDGET
    assert content.endswith("…等 60 个")


def test_campaign_message_truncated_at_budget():
    events = [{"campaign": "C" + "y" * 60, "game": "G", "drop_count": 3}
              for _ in range(40)]
    content = build_campaign_message("42", events)
    assert len(content) <= NOTIFY_CONTENT_BUDGET
    assert content.endswith("…等 40 个")
