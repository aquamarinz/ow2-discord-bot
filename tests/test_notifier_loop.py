"""Integration tests for MinerCog.notifier_loop and _process_link.

Mocks:
- aiohttp via aioresponses (mocks /api/campaigns endpoint)
- self.bot.get_channel via MagicMock returning a channel with AsyncMock send()
- TWITCH_MINERS via monkeypatch

Real:
- sqlite (tmp_db fixture from conftest.py)
- diff_tick / _process_link / _push_notification logic

State semantics under test are spec
docs/superpowers/specs/2026-08-01-miner-notifier-claim-campaign-only-design.md
(raspberry_pi repo): silent baseline, claim-transition push, new-campaign
push, merge/append-only memory.
"""
from __future__ import annotations
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import discord
import pytest
import pytest_asyncio
from aioresponses import aioresponses

from cogs.miner import MinerCog

CAMPAIGNS_URL = "http://localhost:8080/api/campaigns"


# ─────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_channel():
    ch = MagicMock()
    ch.send = AsyncMock(return_value=None)
    return ch


@pytest_asyncio.fixture
async def bot_with_channel(tmp_db, mock_channel):
    bot = MagicMock()
    bot.db = tmp_db
    bot.get_channel = MagicMock(return_value=mock_channel)
    return bot


@pytest_asyncio.fixture
async def cog(bot_with_channel):
    c = MinerCog(bot_with_channel)
    c._session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5))
    yield c
    if not c._session.closed:
        await c._session.close()


@pytest.fixture
def patch_twitch_miners(monkeypatch):
    import cogs.miner
    monkeypatch.setattr(cogs.miner, "TWITCH_MINERS", {"twitch_test": ("localhost", 8080)})


def _payload(drops_claimed=(False,), campaign_id="c1", name="OWCS Day 3",
             active=True, linked=True, minutes=30):
    """One campaign; one drop per entry in drops_claimed."""
    drops = [
        {"id": f"d{i}", "name": f"Drop{i}", "is_claimed": claimed,
         "current_minutes": minutes,
         "benefits": [{"image_url": "https://cdn.example/r.png"}]}
        for i, claimed in enumerate(drops_claimed)
    ]
    return {"campaigns": [{
        "id": campaign_id, "name": name, "game_name": "Overwatch",
        "linked": linked, "active": active, "drops": drops,
    }]}


async def _seed_link(db, discord_id="u1", guild_id="g1", twitch_user="twitch_test",
                     channel_id="101"):
    await db._conn.execute(
        "INSERT INTO twitch_links (discord_id, guild_id, twitch_user, "
        "last_interaction_channel_id) VALUES (?, ?, ?, ?)",
        (discord_id, guild_id, twitch_user, channel_id),
    )
    await db._conn.commit()


async def _tick(cog, payload):
    with aioresponses() as m:
        m.get(CAMPAIGNS_URL, payload=payload)
        await cog.notifier_loop.coro(cog)


# ─────────────────────────────────────────────────────────────────────
# Tests
# ─────────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_baseline_then_claim_pushes_once(cog, mock_channel, patch_twitch_miners):
    """Silent baseline; claim transition pushes 🎉 with reward embed; idempotent."""
    await _seed_link(cog.bot.db)
    await _tick(cog, _payload((False,)))
    mock_channel.send.assert_not_awaited()          # baseline silent

    await _tick(cog, _payload((True,)))
    assert mock_channel.send.await_count == 1
    kwargs = mock_channel.send.call_args.kwargs
    assert "🎉 已领取掉宝" in kwargs["content"]
    assert "**Drop0**" in kwargs["content"]
    assert "✅ 全部领完" in kwargs["content"]        # only drop now claimed
    assert kwargs["embeds"][0].image.url == "https://cdn.example/r.png"

    await _tick(cog, _payload((True,)))
    assert mock_channel.send.await_count == 1       # no repeat


@pytest.mark.asyncio
async def test_no_events_no_send(cog, mock_channel, patch_twitch_miners):
    """Switch-regression sentinel: a top-drop flip without events sends nothing."""
    await _seed_link(cog.bot.db)
    tick1 = {"campaigns": [{
        "id": "c1", "name": "OWCS Day 3", "game_name": "Overwatch",
        "linked": True, "active": True,
        "drops": [
            {"id": "d0", "name": "Drop0", "is_claimed": False,
             "current_minutes": 60, "required_minutes": 120, "progress": 0.5},
            {"id": "d1", "name": "Drop1", "is_claimed": False,
             "current_minutes": 24, "required_minutes": 120, "progress": 0.2},
        ],
    }]}
    tick2 = {"campaigns": [{
        "id": "c1", "name": "OWCS Day 3", "game_name": "Overwatch",
        "linked": True, "active": True,
        "drops": [
            {"id": "d0", "name": "Drop0", "is_claimed": False,
             "current_minutes": 66, "required_minutes": 120, "progress": 0.55},
            {"id": "d1", "name": "Drop1", "is_claimed": False,
             "current_minutes": 108, "required_minutes": 120, "progress": 0.9},
        ],
    }]}
    await _tick(cog, tick1)
    await _tick(cog, tick2)
    mock_channel.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_new_campaign_pushes(cog, mock_channel, patch_twitch_miners):
    """A campaign appearing with progress after baseline → one announce."""
    await _seed_link(cog.bot.db)
    base = _payload((False,))
    await _tick(cog, base)
    two = {"campaigns": base["campaigns"] + _payload(
        (False,), campaign_id="c2", name="Day 4")["campaigns"]}
    await _tick(cog, two)
    assert mock_channel.send.await_count == 1
    kwargs = mock_channel.send.call_args.kwargs
    assert "⛏️ 开始挖新活动" in kwargs["content"] and "**Day 4**" in kwargs["content"]
    assert "<@u1>" in kwargs["content"]
    embeds = kwargs["embeds"]
    assert embeds[0].title == "Day 4"
    assert embeds[0].image.url == "https://cdn.example/r.png"
    assert ("g1", "c2") in cog._announced
    await _tick(cog, two)                            # append-only: no repeat
    assert mock_channel.send.await_count == 1


@pytest.mark.asyncio
async def test_claim_on_inactive_campaign_still_pushes(cog, mock_channel, patch_twitch_miners):
    """active/linked flips must not mask the final claim (spec tests 7/17)."""
    await _seed_link(cog.bot.db)
    await _tick(cog, _payload((False,)))
    await _tick(cog, _payload((True,), active=False, linked=False))
    assert mock_channel.send.await_count == 1
    assert "🎉" in mock_channel.send.call_args.kwargs["content"]


@pytest.mark.asyncio
async def test_dormant_row_baselines_but_never_sends(cog, mock_channel, patch_twitch_miners):
    """No channel → no push, but state still advances (spec test 8)."""
    await _seed_link(cog.bot.db, channel_id=None)
    await _tick(cog, _payload((False,)))
    await _tick(cog, _payload((True,)))
    mock_channel.send.assert_not_awaited()
    key = ("u1", "g1", "twitch_test")
    assert cog._notify_state[key]["drops"]["d0"] is True


@pytest.mark.asyncio
async def test_unreachable_keeps_state_then_recovers(cog, mock_channel, patch_twitch_miners):
    """Connection error skips the tick; recovery aggregates downtime claims."""
    await _seed_link(cog.bot.db)
    await _tick(cog, _payload((False, False)))
    with aioresponses() as m:
        m.get(CAMPAIGNS_URL, exception=aiohttp.ClientConnectionError())
        await cog.notifier_loop.coro(cog)
    mock_channel.send.assert_not_awaited()
    await _tick(cog, _payload((True, True)))
    assert mock_channel.send.await_count == 1        # both claims in one message
    content = mock_channel.send.call_args.kwargs["content"]
    assert "**Drop0**" in content and "**Drop1**" in content


@pytest.mark.asyncio
async def test_malformed_payload_keeps_state(cog, mock_channel, patch_twitch_miners):
    """dict-without-campaigns is skipped exactly like unreachable (spec test 9)."""
    await _seed_link(cog.bot.db)
    await _tick(cog, _payload((False,)))
    await _tick(cog, {"nope": 1})
    await _tick(cog, _payload((True,)))
    assert mock_channel.send.await_count == 1


@pytest.mark.asyncio
async def test_empty_campaigns_transient_no_false_events(cog, mock_channel, patch_twitch_miners):
    """Empty list must not wipe memory → no false 🎉/⛏️ after reappearance."""
    await _seed_link(cog.bot.db)
    await _tick(cog, _payload((True,)))               # baseline (claimed already)
    await _tick(cog, {"campaigns": []})
    await _tick(cog, _payload((True,)))
    mock_channel.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_relink_rebaselines_and_prunes(cog, mock_channel, patch_twitch_miners, monkeypatch):
    """New twitch_user → new key silent baseline; old key pruned (spec test 11)."""
    import cogs.miner
    monkeypatch.setattr(cogs.miner, "TWITCH_MINERS",
                        {"twitch_test": ("localhost", 8080),
                         "twitch_other": ("localhost", 8080)})
    await _seed_link(cog.bot.db)
    await _tick(cog, _payload((False,)))
    assert ("u1", "g1", "twitch_test") in cog._notify_state
    # relink to another twitch account (link_twitch upserts the same row)
    await cog.bot.db.link_twitch("u1", "g1", "twitch_other", "101")
    await _tick(cog, _payload((True,)))               # claimed on first sight of new key
    mock_channel.send.assert_not_awaited()            # silent baseline for new key
    assert ("u1", "g1", "twitch_test") not in cog._notify_state
    assert ("u1", "g1", "twitch_other") in cog._notify_state


@pytest.mark.asyncio
async def test_send_failure_does_not_kill_loop_or_state(cog, mock_channel, patch_twitch_miners):
    """Forbidden on send → loop survives, state advanced, no retry (spec test 14)."""
    await _seed_link(cog.bot.db)
    await _tick(cog, _payload((False,)))
    mock_channel.send = AsyncMock(side_effect=discord.Forbidden(MagicMock(), "no perms"))
    await _tick(cog, _payload((True,)))
    key = ("u1", "g1", "twitch_test")
    assert cog._notify_state[key]["drops"]["d0"] is True
    mock_channel.send = AsyncMock(return_value=None)
    await _tick(cog, _payload((True,)))
    mock_channel.send.assert_not_awaited()            # no retry of lost message


@pytest.mark.asyncio
async def test_multi_links_isolated(cog, mock_channel, patch_twitch_miners, monkeypatch):
    """One link's failure must not block the other (existing semantics kept)."""
    import cogs.miner
    monkeypatch.setattr(cogs.miner, "TWITCH_MINERS",
                        {"twitch_a": ("localhost", 8080),
                         "twitch_b": ("localhost", 8081)})
    await _seed_link(cog.bot.db, discord_id="uA", twitch_user="twitch_a", channel_id="101")
    await _seed_link(cog.bot.db, discord_id="uB", twitch_user="twitch_b", channel_id="202")
    url_b = "http://localhost:8081/api/campaigns"
    with aioresponses() as m:
        m.get(CAMPAIGNS_URL, exception=aiohttp.ClientConnectionError())
        m.get(url_b, payload=_payload((False,)))
        await cog.notifier_loop.coro(cog)
    with aioresponses() as m:
        m.get(CAMPAIGNS_URL, exception=aiohttp.ClientConnectionError())
        m.get(url_b, payload=_payload((True,)))
        await cog.notifier_loop.coro(cog)
    assert mock_channel.send.await_count == 1         # B's claim delivered


@pytest.mark.asyncio
@pytest.mark.parametrize("exc", [
    discord.NotFound(MagicMock(), "gone"),
    discord.HTTPException(MagicMock(), "boom"),
])
async def test_notfound_http_exception_swallowed(cog, mock_channel,
                                                 patch_twitch_miners, exc):
    """NotFound/HTTPException on send → loop survives, state advanced (spec test 14)."""
    await _seed_link(cog.bot.db)
    await _tick(cog, _payload((False,)))
    mock_channel.send = AsyncMock(side_effect=exc)
    await _tick(cog, _payload((True,)))
    key = ("u1", "g1", "twitch_test")
    assert cog._notify_state[key]["drops"]["d0"] is True


@pytest.mark.asyncio
async def test_unlink_prunes_state_no_crash(cog, mock_channel, patch_twitch_miners):
    """Row deleted between ticks → state pruned, loop unaffected (spec §3.1)."""
    await _seed_link(cog.bot.db)
    await _tick(cog, _payload((False,)))
    assert ("u1", "g1", "twitch_test") in cog._notify_state
    await cog.bot.db._conn.execute("DELETE FROM twitch_links")
    await cog.bot.db._conn.commit()
    await cog.notifier_loop.coro(cog)                 # no links, no HTTP mock needed
    assert cog._notify_state == {}
    mock_channel.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_restart_rebaselines_silently(cog, mock_channel, patch_twitch_miners):
    """Cleared state (bot restart) → next tick is a silent baseline (spec test 12)."""
    await _seed_link(cog.bot.db)
    await _tick(cog, _payload((False,)))
    cog._notify_state.clear()
    await _tick(cog, _payload((True,)))               # claimed during "downtime"
    mock_channel.send.assert_not_awaited()


@pytest.mark.asyncio
async def test_same_tick_claim_and_new_campaign_two_messages(cog, mock_channel,
                                                             patch_twitch_miners):
    """🎉 and ⛏️ in the same tick → two separate sends (spec §3.5)."""
    await _seed_link(cog.bot.db)
    base = _payload((False,))
    await _tick(cog, base)
    combo = {"campaigns": _payload((True,))["campaigns"] + _payload(
        (False,), campaign_id="c2", name="Day 4")["campaigns"]}
    await _tick(cog, combo)
    assert mock_channel.send.await_count == 2
    contents = [c.kwargs["content"] for c in mock_channel.send.await_args_list]
    assert any("🎉" in c for c in contents)
    assert any("⛏️" in c and "**Day 4**" in c for c in contents)


# ─────────────────────────────────────────────────────────────────────
# Global campaign-launch announce (2026-08-15 spec §3.2)
# ─────────────────────────────────────────────────────────────────────

def _two_links(monkeypatch):
    import cogs.miner
    monkeypatch.setattr(cogs.miner, "TWITCH_MINERS",
                        {"twitch_a": ("localhost", 8080),
                         "twitch_b": ("localhost", 8081)})


URL_A = "http://localhost:8080/api/campaigns"
URL_B = "http://localhost:8081/api/campaigns"


async def _tick2(cog, payload_a, payload_b):
    with aioresponses() as m:
        m.get(URL_A, payload=payload_a)
        m.get(URL_B, payload=payload_b)
        await cog.notifier_loop.coro(cog)


@pytest.mark.asyncio
async def test_second_link_dedupes_cross_tick(cog, mock_channel,
                                              patch_twitch_miners, monkeypatch):
    """spec test 7 (cross-tick): first detector announces, late one is deduped."""
    _two_links(monkeypatch)
    await _seed_link(cog.bot.db, discord_id="uA", twitch_user="twitch_a")
    await _seed_link(cog.bot.db, discord_id="uB", twitch_user="twitch_b")
    base = _payload((False,))
    await _tick2(cog, base, base)                     # both baseline on c1
    new = {"campaigns": base["campaigns"] + _payload(
        (False,), campaign_id="c2", name="Day 4")["campaigns"]}
    await _tick2(cog, new, base)                      # only A sees c2
    assert mock_channel.send.await_count == 1
    await _tick2(cog, new, new)                       # B sees it later → deduped
    assert mock_channel.send.await_count == 1


@pytest.mark.asyncio
async def test_second_link_dedupes_same_tick(cog, mock_channel,
                                             patch_twitch_miners, monkeypatch):
    """spec test 7 (same tick): serial processing, second hit is deduped."""
    _two_links(monkeypatch)
    await _seed_link(cog.bot.db, discord_id="uA", twitch_user="twitch_a")
    await _seed_link(cog.bot.db, discord_id="uB", twitch_user="twitch_b")
    base = _payload((False,))
    await _tick2(cog, base, base)
    new = {"campaigns": base["campaigns"] + _payload(
        (False,), campaign_id="c2", name="Day 4")["campaigns"]}
    await _tick2(cog, new, new)                       # both see c2 same tick
    assert mock_channel.send.await_count == 1
    assert "<@uA>" in mock_channel.send.call_args.kwargs["content"]
    assert "<@uB>" in mock_channel.send.call_args.kwargs["content"]


@pytest.mark.asyncio
async def test_dormant_detector_leaves_announce_to_live_link(
        cog, mock_channel, patch_twitch_miners, monkeypatch):
    """spec test 8: dormant link neither sends nor marks; live link announces."""
    _two_links(monkeypatch)
    await _seed_link(cog.bot.db, discord_id="uA", twitch_user="twitch_a",
                     channel_id=None)                 # dormant
    await _seed_link(cog.bot.db, discord_id="uB", twitch_user="twitch_b")
    base = _payload((False,))
    await _tick2(cog, base, base)
    new = {"campaigns": base["campaigns"] + _payload(
        (False,), campaign_id="c2", name="Day 4")["campaigns"]}
    await _tick2(cog, new, base)                      # only dormant A sees c2
    mock_channel.send.assert_not_awaited()
    assert ("g1", "c2") not in cog._announced         # not marked
    await _tick2(cog, new, new)                       # live B sees it later
    assert mock_channel.send.await_count == 1


@pytest.mark.asyncio
async def test_send_failure_not_marked_no_self_retry_other_link_retries(
        cog, mock_channel, patch_twitch_miners, monkeypatch):
    """spec test 9: fail → unmarked; failed link never self-retries (mining
    append-only must NOT be unwound); another link retries successfully."""
    _two_links(monkeypatch)
    await _seed_link(cog.bot.db, discord_id="uA", twitch_user="twitch_a")
    await _seed_link(cog.bot.db, discord_id="uB", twitch_user="twitch_b")
    base = _payload((False,))
    await _tick2(cog, base, base)
    new = {"campaigns": base["campaigns"] + _payload(
        (False,), campaign_id="c2", name="Day 4")["campaigns"]}
    mock_channel.send = AsyncMock(side_effect=discord.Forbidden(MagicMock(), "x"))
    await _tick2(cog, new, base)                      # A announce fails
    assert ("g1", "c2") not in cog._announced
    failed_count = mock_channel.send.await_count
    await _tick2(cog, new, base)                      # A again ×2 → no self-retry
    await _tick2(cog, new, base)
    assert mock_channel.send.await_count == failed_count
    mock_channel.send = AsyncMock(return_value=None)
    await _tick2(cog, new, new)                       # B detects → retry OK
    assert mock_channel.send.await_count == 1
    assert ("g1", "c2") in cog._announced


@pytest.mark.asyncio
async def test_different_guilds_announce_separately(cog, mock_channel,
                                                    patch_twitch_miners, monkeypatch):
    """spec test 10: dedupe key is per guild."""
    _two_links(monkeypatch)
    await _seed_link(cog.bot.db, discord_id="uA", guild_id="g1",
                     twitch_user="twitch_a")
    await _seed_link(cog.bot.db, discord_id="uB", guild_id="g2",
                     twitch_user="twitch_b")
    base = _payload((False,))
    await _tick2(cog, base, base)
    new = {"campaigns": base["campaigns"] + _payload(
        (False,), campaign_id="c2", name="Day 4")["campaigns"]}
    await _tick2(cog, new, new)
    assert mock_channel.send.await_count == 2
    assert ("g1", "c2") in cog._announced and ("g2", "c2") in cog._announced


@pytest.mark.asyncio
async def test_multi_new_campaigns_one_message_each(cog, mock_channel,
                                                    patch_twitch_miners):
    """spec test 11: same tick, two new campaigns → two separate messages."""
    await _seed_link(cog.bot.db)
    base = _payload((False,))
    await _tick(cog, base)
    three = {"campaigns": base["campaigns"]
             + _payload((False,), campaign_id="c2", name="Day 4")["campaigns"]
             + _payload((False,), campaign_id="c3", name="Day 5")["campaigns"]}
    await _tick(cog, three)
    assert mock_channel.send.await_count == 2
    contents = [c.kwargs["content"] for c in mock_channel.send.await_args_list]
    assert any("**Day 4**" in c for c in contents)
    assert any("**Day 5**" in c for c in contents)


@pytest.mark.asyncio
async def test_non_discord_send_error_does_not_truncate_tick(cog, mock_channel,
                                                             patch_twitch_miners):
    """A non-discord send exception (transient network) must not swallow the
    REST of this tick's events: c2 fails, c3 still goes out. Both are already
    in append-only `mining`, so a truncated tick loses c3 forever."""
    await _seed_link(cog.bot.db)
    base = _payload((False,))
    await _tick(cog, base)
    three = {"campaigns": base["campaigns"]
             + _payload((False,), campaign_id="c2", name="Day 4")["campaigns"]
             + _payload((False,), campaign_id="c3", name="Day 5")["campaigns"]}
    mock_channel.send = AsyncMock(side_effect=[aiohttp.ClientOSError(), None])
    await _tick(cog, three)
    assert mock_channel.send.await_count == 2         # c2 failed, c3 still sent
    contents = [c.kwargs["content"] for c in mock_channel.send.await_args_list]
    assert "**Day 4**" in contents[0]                 # payload order: c2 first
    assert "**Day 5**" in contents[1]
    assert ("g1", "c2") not in cog._announced         # failure → unmarked
    assert ("g1", "c3") in cog._announced             # success → marked


def test_mentions_by_guild_dedup_and_order():
    """spec test 12: first-seen order, same discord user twice → once,
    dormant links included."""
    from cogs.miner import _mentions_by_guild
    from database import LinkState

    def _l(d, g, t, ch="101"):
        return LinkState(discord_id=d, guild_id=g, twitch_user=t,
                         last_interaction_channel_id=ch, last_top_drop_id=None)

    links = [_l("u1", "g1", "ta"), _l("u2", "g1", "tb", ch=None),
             _l("u1", "g1", "tc"), _l("u3", "g2", "td")]
    assert _mentions_by_guild(links) == {"g1": ["u1", "u2"], "g2": ["u3"]}


@pytest.mark.asyncio
async def test_announced_fifo_cap_evicts_oldest(cog):
    """spec test 13: FIFO eviction at ANNOUNCED_CAP."""
    from cogs.miner import ANNOUNCED_CAP
    for i in range(ANNOUNCED_CAP):
        cog._announced[("g1", f"c{i}")] = None
    cog._mark_announced(("g1", "cNEW"))
    assert len(cog._announced) == ANNOUNCED_CAP
    assert ("g1", "c0") not in cog._announced
    assert ("g1", "cNEW") in cog._announced
