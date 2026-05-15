"""Unit tests for MinerCog._build_embed Chinese localization + None fallback."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from cogs.miner import MinerCog


@pytest.fixture
def cog():
    """A MinerCog instance with a mocked bot - _build_embed is pure / does no async I/O."""
    bot = MagicMock()
    return MinerCog(bot)


def _campaigns(in_progress_drop=None, n_linked_active=1):
    """Build a campaigns_data dict for embed rendering."""
    drops = []
    if in_progress_drop is not None:
        drops = [in_progress_drop]
    campaigns = []
    for _ in range(n_linked_active):
        campaigns.append({
            "name": "OWCS S1",
            "game_name": "Overwatch",
            "linked": True,
            "active": True,
            "drops": drops,
        })
    return {"campaigns": campaigns}


def _drop(id="d1", current_minutes=120, required_minutes=180, progress=0.667,
          is_claimed=False, name="Zenyatta Spray"):
    return {
        "id": id, "name": name,
        "current_minutes": current_minutes,
        "required_minutes": required_minutes,
        "progress": progress,
        "is_claimed": is_claimed,
    }


def _texts(embed):
    """Concatenate all field names + values + title into one string for substring assertions."""
    parts = [embed.title or ""]
    for f in embed.fields:
        parts.append(f.name or "")
        parts.append(f.value or "")
    return "\n".join(parts)


def test_build_embed_chinese_labels(cog):
    """Field names use Chinese labels: 状态, 当前 Drop, 进度, 可挂活动."""
    status_data = {"status": "正在观看: 加藤純一", "login": {"status": "已登录"}}
    drop = _drop(progress=0.7)
    embed = cog._build_embed("zeuswho3211", status_data, _campaigns(in_progress_drop=drop))
    text = _texts(embed)
    assert "状态" in text
    assert "当前 Drop" in text
    assert "进度" in text
    assert "可挂活动" in text
    # No English labels leaked
    assert "Current Drop" not in text
    assert "Progress" not in text
    assert "Eligible campaigns" not in text


def test_build_embed_watching_status(cog):
    """When watching with in-progress drop -> 🟢 正在挂宝."""
    status_data = {"status": "正在观看: somechannel", "login": {"status": "已登录"}}
    drop = _drop(progress=0.5)
    embed = cog._build_embed("user", status_data, _campaigns(in_progress_drop=drop))
    assert "🟢 正在挂宝" in _texts(embed)


def test_build_embed_idle_status(cog):
    """Logged in but no in-progress drop -> 🟡 空闲."""
    status_data = {"status": "等待中", "login": {"status": "已登录"}}
    embed = cog._build_embed("user", status_data, _campaigns(in_progress_drop=None))
    assert "🟡 空闲" in _texts(embed)


def test_build_embed_disconnected_status(cog):
    """Not logged in -> 🔴 离线."""
    status_data = {"status": "未连接", "login": {"status": ""}}
    embed = cog._build_embed("user", status_data, _campaigns(in_progress_drop=None, n_linked_active=0))
    assert "🔴 离线" in _texts(embed)


def test_build_embed_no_drop_chinese(cog):
    """When no in-progress drop, Current Drop value is "当前没有 drop 在挂"."""
    status_data = {"status": "等待中", "login": {"status": "已登录"}}
    embed = cog._build_embed("user", status_data, _campaigns(in_progress_drop=None))
    assert "当前没有 drop 在挂" in _texts(embed)


def test_build_embed_status_data_none_fallback(cog):
    """status_data=None must NOT crash; Status field shows 🟢 正在挂宝 fallback."""
    drop = _drop(progress=0.5)
    embed = cog._build_embed("user", None, _campaigns(in_progress_drop=drop))
    text = _texts(embed)
    assert "🟢 正在挂宝" in text                  # fallback label
    assert "Zenyatta Spray" in text             # drop name still rendered
