"""Unit tests for reward-image helpers (_usable_image_url, _benefit_image_url).

Pure functions — no Discord/network/db. conftest.py adds repo root to sys.path.
"""
from __future__ import annotations

from cogs.miner import _usable_image_url, _benefit_image_url


# ── _usable_image_url ──────────────────────────────────────────────
def test_usable_image_url_valid_https():
    url = "https://static-cdn.jtvnw.net/twitch-quests-assets/REWARD/x.png"
    assert _usable_image_url(url) == url


def test_usable_image_url_strips_surrounding_ws():
    assert _usable_image_url("  https://x.com/a.png  ") == "https://x.com/a.png"


def test_usable_image_url_rejects_non_str():
    assert _usable_image_url(None) is None
    assert _usable_image_url(123) is None


def test_usable_image_url_rejects_empty():
    assert _usable_image_url("") is None
    assert _usable_image_url("   ") is None


def test_usable_image_url_rejects_non_http_scheme():
    assert _usable_image_url("data:image/png;base64,xx") is None
    assert _usable_image_url("ftp://host/y") is None


def test_usable_image_url_rejects_no_host():
    assert _usable_image_url("https://") is None


def test_usable_image_url_rejects_internal_whitespace():
    assert _usable_image_url("https:// bad/x.png") is None


def test_usable_image_url_rejects_malformed_ipv6():
    # urlsplit("https://[bad") raises ValueError — must be caught -> None
    assert _usable_image_url("https://[bad") is None


# ── _benefit_image_url ─────────────────────────────────────────────
def test_benefit_image_url_first_valid():
    drop = {"benefits": [{"name": "S", "image_url": "https://cdn/x.png"}]}
    assert _benefit_image_url(drop) == "https://cdn/x.png"


def test_benefit_image_url_empty_benefits():
    assert _benefit_image_url({"benefits": []}) is None


def test_benefit_image_url_missing_key():
    assert _benefit_image_url({"id": "d1"}) is None


def test_benefit_image_url_benefits_not_list():
    # malformed shape (dict instead of list) must NOT raise
    assert _benefit_image_url({"benefits": {"image_url": "https://cdn/x.png"}}) is None


def test_benefit_image_url_item_not_dict():
    drop = {"benefits": ["garbage", {"image_url": "https://cdn/ok.png"}]}
    assert _benefit_image_url(drop) == "https://cdn/ok.png"


def test_benefit_image_url_first_invalid_second_valid():
    drop = {"benefits": [
        {"name": "no image_url key"},
        {"name": "bad url", "image_url": "not-a-url"},
        {"name": "good", "image_url": "https://cdn/good.png"},
    ]}
    assert _benefit_image_url(drop) == "https://cdn/good.png"
