"""Integration tests for MinerCog.notifier_loop and _process_link.

Mocks:
- aiohttp via aioresponses (mocks /api/campaigns endpoint)
- self.bot.get_channel via MagicMock returning a channel with AsyncMock send()
- TWITCH_MINERS via monkeypatch

Real:
- sqlite (tmp_db fixture from conftest.py)
- compute_top_drop / _process_link / _push_notification logic
"""
from __future__ import annotations
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import asyncio
import discord
import pytest
import pytest_asyncio
from aioresponses import aioresponses

from cogs.miner import MinerCog


# ─────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_channel():
    """A channel mock whose .send is an AsyncMock."""
    ch = MagicMock()
    ch.send = AsyncMock(return_value=None)
    return ch


@pytest_asyncio.fixture
async def bot_with_channel(tmp_db, mock_channel):
    """Bot mock that returns mock_channel from get_channel() and uses tmp_db."""
    bot = MagicMock()
    bot.db = tmp_db
    bot.get_channel = MagicMock(return_value=mock_channel)
    return bot


@pytest_asyncio.fixture
async def cog(bot_with_channel):
    """A MinerCog with a real aiohttp.ClientSession (closed at the end)."""
    c = MinerCog(bot_with_channel)
    c._session = aiohttp.ClientSession(
        timeout=aiohttp.ClientTimeout(total=5)
    )
    yield c
    if not c._session.closed:
        await c._session.close()


@pytest.fixture
def patch_twitch_miners(monkeypatch):
    """Configure TWITCH_MINERS to map 'twitch_test' → ('localhost', 8080)."""
    import cogs.miner
    monkeypatch.setattr(cogs.miner, "TWITCH_MINERS", {"twitch_test": ("localhost", 8080)})


def _campaigns_payload(top_drop_id="d1", progress=0.5, name="Drop1", in_progress=True,
                       in_progress_extra=None):
    drops = []
    if in_progress:
        drops.append({
            "id": top_drop_id,
            "name": name,
            "current_minutes": 60,
            "required_minutes": 120,
            "progress": progress,
            "is_claimed": False,
        })
    if in_progress_extra:
        drops.extend(in_progress_extra)
    return {
        "campaigns": [{
            "name": "OWCS S1",
            "game_name": "Overwatch",
            "linked": True,
            "active": True,
            "drops": drops,
        }]
    }


async def _seed_link(db, discord_id="u1", guild_id="g1", twitch_user="twitch_test",
                     channel_id="101", last_top_drop_id=None):
    """Insert a twitch_links row with explicit state (bypasses link_twitch reset behavior)."""
    await db._conn.execute(
        "INSERT INTO twitch_links (discord_id, guild_id, twitch_user, "
        "last_interaction_channel_id, last_top_drop_id) VALUES (?, ?, ?, ?, ?)",
        (discord_id, guild_id, twitch_user, channel_id, last_top_drop_id),
    )
    await db._conn.commit()


# ─────────────────────────────────────────────────────────────────────
# 16 integration tests
# ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_notifier_bootstrap_silent(cog, mock_channel, patch_twitch_miners):
    """NULL last_top_drop_id + miner returns top → silent bootstrap (write db, no send)."""
    await _seed_link(cog.bot.db, last_top_drop_id=None)
    with aioresponses() as m:
        m.get("http://localhost:8080/api/campaigns",
              payload=_campaigns_payload(top_drop_id="d_first"))
        await cog.notifier_loop.coro(cog)
    mock_channel.send.assert_not_called()
    rows = await cog.bot.db.iter_links_with_state()
    assert rows[0].last_top_drop_id == "d_first"


@pytest.mark.asyncio
async def test_notifier_no_change_no_send(cog, mock_channel, patch_twitch_miners):
    """last == current top → no send, no db update."""
    await _seed_link(cog.bot.db, last_top_drop_id="d_same")
    with aioresponses() as m:
        m.get("http://localhost:8080/api/campaigns",
              payload=_campaigns_payload(top_drop_id="d_same"))
        await cog.notifier_loop.coro(cog)
    mock_channel.send.assert_not_called()
    rows = await cog.bot.db.iter_links_with_state()
    assert rows[0].last_top_drop_id == "d_same"


@pytest.mark.asyncio
async def test_notifier_change_sends(cog, mock_channel, patch_twitch_miners):
    """last != current top → send once + db update."""
    await _seed_link(cog.bot.db, last_top_drop_id="d_old")
    with aioresponses() as m:
        m.get("http://localhost:8080/api/campaigns",
              payload=_campaigns_payload(top_drop_id="d_new", name="NewDrop"))
        await cog.notifier_loop.coro(cog)
    assert mock_channel.send.call_count == 1
    call = mock_channel.send.call_args
    assert "<@u1>" in call.kwargs["content"]
    assert "NewDrop" in call.kwargs["content"]
    assert "切到新挂宝目标" in call.kwargs["content"]
    assert isinstance(call.kwargs["embed"], discord.Embed)
    rows = await cog.bot.db.iter_links_with_state()
    assert rows[0].last_top_drop_id == "d_new"


@pytest.mark.asyncio
async def test_notifier_miner_unreachable(cog, mock_channel, patch_twitch_miners):
    """aiohttp raises → no send, no db update."""
    await _seed_link(cog.bot.db, last_top_drop_id="d_old")
    with aioresponses() as m:
        m.get("http://localhost:8080/api/campaigns",
              exception=asyncio.TimeoutError())
        await cog.notifier_loop.coro(cog)
    mock_channel.send.assert_not_called()
    rows = await cog.bot.db.iter_links_with_state()
    assert rows[0].last_top_drop_id == "d_old"


@pytest.mark.asyncio
async def test_notifier_channel_not_found(cog, mock_channel, patch_twitch_miners):
    """get_channel returns None → no send, no exception, db STILL updates."""
    cog.bot.get_channel = MagicMock(return_value=None)
    await _seed_link(cog.bot.db, last_top_drop_id="d_old")
    with aioresponses() as m:
        m.get("http://localhost:8080/api/campaigns",
              payload=_campaigns_payload(top_drop_id="d_new"))
        await cog.notifier_loop.coro(cog)
    rows = await cog.bot.db.iter_links_with_state()
    assert rows[0].last_top_drop_id == "d_new"


@pytest.mark.asyncio
async def test_notifier_channel_forbidden(cog, mock_channel, patch_twitch_miners):
    """send raises Forbidden → swallowed, db still updates."""
    mock_channel.send.side_effect = discord.Forbidden(
        response=MagicMock(status=403, reason="Forbidden"), message="no perms"
    )
    await _seed_link(cog.bot.db, last_top_drop_id="d_old")
    with aioresponses() as m:
        m.get("http://localhost:8080/api/campaigns",
              payload=_campaigns_payload(top_drop_id="d_new"))
        await cog.notifier_loop.coro(cog)
    rows = await cog.bot.db.iter_links_with_state()
    assert rows[0].last_top_drop_id == "d_new"


@pytest.mark.asyncio
async def test_notifier_no_in_progress_drop(cog, mock_channel, patch_twitch_miners):
    """0 in-progress drops → no send, no db update (D12: preserve last_top_drop_id)."""
    await _seed_link(cog.bot.db, last_top_drop_id="d_old")
    with aioresponses() as m:
        m.get("http://localhost:8080/api/campaigns",
              payload=_campaigns_payload(in_progress=False))
        await cog.notifier_loop.coro(cog)
    mock_channel.send.assert_not_called()
    rows = await cog.bot.db.iter_links_with_state()
    assert rows[0].last_top_drop_id == "d_old"


@pytest.mark.asyncio
async def test_notifier_multi_users_processed(cog, mock_channel, monkeypatch):
    """2 links, both with switches → 2 sends, 2 db updates."""
    import cogs.miner
    monkeypatch.setattr(cogs.miner, "TWITCH_MINERS", {
        "twitch_a": ("hostA", 8080),
        "twitch_b": ("hostB", 8080),
    })
    await _seed_link(cog.bot.db, discord_id="uA", guild_id="g1",
                     twitch_user="twitch_a", channel_id="101", last_top_drop_id="A_old")
    await _seed_link(cog.bot.db, discord_id="uB", guild_id="g1",
                     twitch_user="twitch_b", channel_id="202", last_top_drop_id="B_old")
    with aioresponses() as m:
        m.get("http://hostA:8080/api/campaigns",
              payload=_campaigns_payload(top_drop_id="A_new"))
        m.get("http://hostB:8080/api/campaigns",
              payload=_campaigns_payload(top_drop_id="B_new"))
        await cog.notifier_loop.coro(cog)
    assert mock_channel.send.call_count == 2


@pytest.mark.asyncio
async def test_notifier_malformed_campaigns_shape(cog, mock_channel, patch_twitch_miners):
    """campaigns key missing / drops key missing → no send, no db update, no exception."""
    await _seed_link(cog.bot.db, last_top_drop_id="d_old")
    with aioresponses() as m:
        m.get("http://localhost:8080/api/campaigns", payload={})  # no "campaigns" key
        await cog.notifier_loop.coro(cog)
    mock_channel.send.assert_not_called()
    rows = await cog.bot.db.iter_links_with_state()
    assert rows[0].last_top_drop_id == "d_old"


@pytest.mark.asyncio
async def test_notifier_invalid_json_body(cog, mock_channel, patch_twitch_miners):
    """Invalid JSON body → ValueError caught in network layer; no send, no db update."""
    await _seed_link(cog.bot.db, last_top_drop_id="d_old")
    with aioresponses() as m:
        m.get("http://localhost:8080/api/campaigns", body="<not json>",
              headers={"Content-Type": "application/json"})
        await cog.notifier_loop.coro(cog)
    mock_channel.send.assert_not_called()
    rows = await cog.bot.db.iter_links_with_state()
    assert rows[0].last_top_drop_id == "d_old"


@pytest.mark.asyncio
async def test_notifier_compute_top_drop_exception_isolated(
    cog, mock_channel, monkeypatch
):
    """If compute_top_drop raises for one link, the next link still processes."""
    import cogs.miner
    monkeypatch.setattr(cogs.miner, "TWITCH_MINERS", {
        "twitch_a": ("hostA", 8080),
        "twitch_b": ("hostB", 8080),
    })
    await _seed_link(cog.bot.db, discord_id="uA", twitch_user="twitch_a",
                     channel_id="101", last_top_drop_id="A_old")
    await _seed_link(cog.bot.db, discord_id="uB", guild_id="g2", twitch_user="twitch_b",
                     channel_id="202", last_top_drop_id="B_old")

    calls = {"n": 0}
    def raising_compute(data):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("boom")
        return {"id": "B_new", "drop_name": "B", "game": "Overwatch",
                "campaign": "C", "current_min": 30, "required_min": 60, "progress": 0.5}
    monkeypatch.setattr(cogs.miner, "compute_top_drop", raising_compute)

    with aioresponses() as m:
        m.get("http://hostA:8080/api/campaigns", payload={})
        m.get("http://hostB:8080/api/campaigns", payload={})
        await cog.notifier_loop.coro(cog)
    # Second user notified despite first raising
    assert mock_channel.send.call_count == 1
    rows = {r.discord_id: r for r in await cog.bot.db.iter_links_with_state()}
    assert rows["uA"].last_top_drop_id == "A_old"  # error → no update
    assert rows["uB"].last_top_drop_id == "B_new"


@pytest.mark.asyncio
async def test_notifier_channel_send_http_exception(cog, mock_channel, patch_twitch_miners):
    """send raises HTTPException (rate limit etc) → swallowed, db still updates."""
    mock_channel.send.side_effect = discord.HTTPException(
        response=MagicMock(status=500, reason="Server"), message="upstream"
    )
    await _seed_link(cog.bot.db, last_top_drop_id="d_old")
    with aioresponses() as m:
        m.get("http://localhost:8080/api/campaigns",
              payload=_campaigns_payload(top_drop_id="d_new"))
        await cog.notifier_loop.coro(cog)
    rows = await cog.bot.db.iter_links_with_state()
    assert rows[0].last_top_drop_id == "d_new"


@pytest.mark.asyncio
async def test_notifier_unlink_during_tick(cog, mock_channel, patch_twitch_miners):
    """If a row is deleted between iter and set_last_top_drop, UPDATE is a no-op."""
    await _seed_link(cog.bot.db, last_top_drop_id="d_old")
    original_set = cog.bot.db.set_last_top_drop

    async def delete_then_set(discord_id, guild_id, drop_id):
        # Simulate: user unlinks right before db update
        await cog.bot.db.unlink_twitch(discord_id, guild_id)
        await original_set(discord_id, guild_id, drop_id)
    cog.bot.db.set_last_top_drop = delete_then_set

    with aioresponses() as m:
        m.get("http://localhost:8080/api/campaigns",
              payload=_campaigns_payload(top_drop_id="d_new"))
        # Should not raise even though row is gone before UPDATE
        await cog.notifier_loop.coro(cog)
    rows = await cog.bot.db.iter_links_with_state()
    assert rows == []  # row was unlinked


@pytest.mark.asyncio
async def test_notifier_no_top_then_new_top_notifies(cog, mock_channel, patch_twitch_miners):
    """tick1: top=None (db has d_old) → no send no update. tick2: top=d_new → send + update."""
    await _seed_link(cog.bot.db, last_top_drop_id="d_old")
    # tick 1: no in-progress
    with aioresponses() as m:
        m.get("http://localhost:8080/api/campaigns",
              payload=_campaigns_payload(in_progress=False))
        await cog.notifier_loop.coro(cog)
    mock_channel.send.assert_not_called()
    rows = await cog.bot.db.iter_links_with_state()
    assert rows[0].last_top_drop_id == "d_old"  # preserved

    # tick 2: new top
    with aioresponses() as m:
        m.get("http://localhost:8080/api/campaigns",
              payload=_campaigns_payload(top_drop_id="d_new"))
        await cog.notifier_loop.coro(cog)
    assert mock_channel.send.call_count == 1
    assert "切到新挂宝目标" in mock_channel.send.call_args.kwargs["content"]
    rows = await cog.bot.db.iter_links_with_state()
    assert rows[0].last_top_drop_id == "d_new"


@pytest.mark.asyncio
async def test_notifier_push_uses_status_data_none(cog, mock_channel, patch_twitch_miners):
    """Notification embed uses _build_embed(status_data=None) path → Status = '🟢 正在挂宝'."""
    await _seed_link(cog.bot.db, last_top_drop_id="d_old")
    with aioresponses() as m:
        m.get("http://localhost:8080/api/campaigns",
              payload=_campaigns_payload(top_drop_id="d_new", name="MyDrop"))
        await cog.notifier_loop.coro(cog)
    assert mock_channel.send.call_count == 1
    sent_embed = mock_channel.send.call_args.kwargs["embed"]
    fields_text = "\n".join((f.name or "") + "\n" + (f.value or "") for f in sent_embed.fields)
    assert "🟢 正在挂宝" in fields_text
    assert "MyDrop" in fields_text


@pytest.mark.asyncio
async def test_notifier_missing_drop_id_no_send_no_update(cog, mock_channel, patch_twitch_miners):
    """A drop with id=None in the payload must be skipped — compute_top_drop returns None;
    last_top_drop_id stays at the old value (not corrupted to NULL)."""
    await _seed_link(cog.bot.db, last_top_drop_id="d_legit_old")
    bad_payload = {
        "campaigns": [{
            "name": "Camp", "game_name": "Game", "linked": True, "active": True,
            "drops": [
                {"id": None, "name": "malformed", "current_minutes": 60,
                 "required_minutes": 100, "progress": 0.9, "is_claimed": False},
            ],
        }]
    }
    with aioresponses() as m:
        m.get("http://localhost:8080/api/campaigns", payload=bad_payload)
        await cog.notifier_loop.coro(cog)
    mock_channel.send.assert_not_called()
    rows = await cog.bot.db.iter_links_with_state()
    assert rows[0].last_top_drop_id == "d_legit_old"
