"""Tests for twitch_links DB helpers."""
import pytest


@pytest.mark.asyncio
async def test_link_twitch_writes_lowercase(tmp_db):
    await tmp_db.link_twitch("user1", "guild1", "Warn")
    row = await tmp_db.get_twitch_link("user1", "guild1")
    assert row is not None
    assert row["twitch_user"] == "warn"


@pytest.mark.asyncio
async def test_link_twitch_strips_whitespace(tmp_db):
    await tmp_db.link_twitch("user1", "guild1", "  alice  ")
    row = await tmp_db.get_twitch_link("user1", "guild1")
    assert row["twitch_user"] == "alice"


@pytest.mark.asyncio
async def test_link_twitch_rejects_invalid_chars(tmp_db):
    with pytest.raises(ValueError, match="invalid"):
        await tmp_db.link_twitch("user1", "guild1", "bad@name!")


@pytest.mark.asyncio
async def test_link_twitch_rejects_too_short(tmp_db):
    with pytest.raises(ValueError):
        await tmp_db.link_twitch("user1", "guild1", "ab")  # < 3 chars


@pytest.mark.asyncio
async def test_link_twitch_rejects_too_long(tmp_db):
    with pytest.raises(ValueError):
        await tmp_db.link_twitch("user1", "guild1", "x" * 26)  # > 25 chars


@pytest.mark.asyncio
async def test_link_twitch_upsert_overwrites(tmp_db):
    await tmp_db.link_twitch("user1", "guild1", "alice")
    await tmp_db.link_twitch("user1", "guild1", "bob")
    row = await tmp_db.get_twitch_link("user1", "guild1")
    assert row["twitch_user"] == "bob"


@pytest.mark.asyncio
async def test_unlink_twitch_returns_true_when_deletes(tmp_db):
    await tmp_db.link_twitch("user1", "guild1", "alice")
    deleted = await tmp_db.unlink_twitch("user1", "guild1")
    assert deleted is True
    assert await tmp_db.get_twitch_link("user1", "guild1") is None


@pytest.mark.asyncio
async def test_unlink_twitch_returns_false_when_no_record(tmp_db):
    deleted = await tmp_db.unlink_twitch("user1", "guild1")
    assert deleted is False


@pytest.mark.asyncio
async def test_two_discord_users_can_share_twitch_account(tmp_db):
    await tmp_db.link_twitch("user1", "guild1", "alice")
    await tmp_db.link_twitch("user2", "guild1", "alice")
    row1 = await tmp_db.get_twitch_link("user1", "guild1")
    row2 = await tmp_db.get_twitch_link("user2", "guild1")
    assert row1["twitch_user"] == row2["twitch_user"] == "alice"
