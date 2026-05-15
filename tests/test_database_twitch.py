"""Tests for twitch_links DB helpers."""
import pytest


@pytest.mark.asyncio
async def test_link_twitch_writes_lowercase(tmp_db):
    await tmp_db.link_twitch("user1", "guild1", "Warn", "test_ch")
    row = await tmp_db.get_twitch_link("user1", "guild1")
    assert row is not None
    assert row["twitch_user"] == "warn"


@pytest.mark.asyncio
async def test_link_twitch_strips_whitespace(tmp_db):
    await tmp_db.link_twitch("user1", "guild1", "  alice  ", "test_ch")
    row = await tmp_db.get_twitch_link("user1", "guild1")
    assert row["twitch_user"] == "alice"


@pytest.mark.asyncio
async def test_link_twitch_rejects_invalid_chars(tmp_db):
    with pytest.raises(ValueError, match="invalid"):
        await tmp_db.link_twitch("user1", "guild1", "bad@name!", "test_ch")


@pytest.mark.asyncio
async def test_link_twitch_rejects_too_short(tmp_db):
    with pytest.raises(ValueError):
        await tmp_db.link_twitch("user1", "guild1", "ab", "test_ch")  # < 3 chars


@pytest.mark.asyncio
async def test_link_twitch_rejects_too_long(tmp_db):
    with pytest.raises(ValueError):
        await tmp_db.link_twitch("user1", "guild1", "x" * 26, "test_ch")  # > 25 chars


@pytest.mark.asyncio
async def test_link_twitch_upsert_overwrites(tmp_db):
    await tmp_db.link_twitch("user1", "guild1", "alice", "test_ch")
    await tmp_db.link_twitch("user1", "guild1", "bob", "test_ch")
    row = await tmp_db.get_twitch_link("user1", "guild1")
    assert row["twitch_user"] == "bob"


@pytest.mark.asyncio
async def test_unlink_twitch_returns_true_when_deletes(tmp_db):
    await tmp_db.link_twitch("user1", "guild1", "alice", "test_ch")
    deleted = await tmp_db.unlink_twitch("user1", "guild1")
    assert deleted is True
    assert await tmp_db.get_twitch_link("user1", "guild1") is None


@pytest.mark.asyncio
async def test_unlink_twitch_returns_false_when_no_record(tmp_db):
    deleted = await tmp_db.unlink_twitch("user1", "guild1")
    assert deleted is False


@pytest.mark.asyncio
async def test_two_discord_users_can_share_twitch_account(tmp_db):
    await tmp_db.link_twitch("user1", "guild1", "alice", "test_ch")
    await tmp_db.link_twitch("user2", "guild1", "alice", "test_ch")
    row1 = await tmp_db.get_twitch_link("user1", "guild1")
    row2 = await tmp_db.get_twitch_link("user2", "guild1")
    assert row1["twitch_user"] == row2["twitch_user"] == "alice"


# ─────────────────────────────────────────────────────────────
# v2 migration + LinkState + state methods + new link_twitch
# ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_migration_idempotent(tmp_db):
    """Running _migrate_v2 a second time doesn't error; columns exist."""
    await tmp_db._migrate_v2()  # tmp_db already migrated once via initialize; this is the 2nd call
    cur = await tmp_db._conn.execute(
        "SELECT last_interaction_channel_id, last_top_drop_id FROM twitch_links LIMIT 0"
    )
    await cur.close()


@pytest.mark.asyncio
async def test_migration_on_old_db(tmp_path, monkeypatch):
    """An existing db without new columns gets them added by initialize()."""
    import aiosqlite
    import config
    db_path = str(tmp_path / "old.db")
    monkeypatch.setattr(config, "DATABASE_PATH", db_path)
    conn = await aiosqlite.connect(db_path)
    await conn.execute(
        """CREATE TABLE twitch_links (
               discord_id  TEXT NOT NULL,
               guild_id    TEXT NOT NULL,
               twitch_user TEXT NOT NULL,
               linked_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
               PRIMARY KEY (discord_id, guild_id)
           )"""
    )
    await conn.execute(
        "INSERT INTO twitch_links (discord_id, guild_id, twitch_user) VALUES (?, ?, ?)",
        ("u1", "g1", "twitch_old"),
    )
    await conn.commit()
    await conn.close()

    from database import Database
    db = Database()
    await db.initialize()
    try:
        cur = await db._conn.execute(
            "SELECT discord_id, last_interaction_channel_id, last_top_drop_id "
            "FROM twitch_links WHERE discord_id = ?",
            ("u1",),
        )
        row = await cur.fetchone()
        await cur.close()
        assert row["discord_id"] == "u1"
        assert row["last_interaction_channel_id"] is None
        assert row["last_top_drop_id"] is None
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_iter_links_with_state_empty(tmp_db):
    """No links → empty list."""
    rows = await tmp_db.iter_links_with_state()
    assert rows == []


@pytest.mark.asyncio
async def test_iter_links_with_state_multi(tmp_db):
    """3 rows return 3 LinkState instances with discord_id (not discord_user_id)."""
    from database import LinkState
    await tmp_db._conn.execute(
        "INSERT INTO twitch_links (discord_id, guild_id, twitch_user, last_interaction_channel_id, last_top_drop_id) VALUES (?, ?, ?, ?, ?)",
        ("u1", "g1", "twitch1", "ch1", None),
    )
    await tmp_db._conn.execute(
        "INSERT INTO twitch_links (discord_id, guild_id, twitch_user, last_interaction_channel_id, last_top_drop_id) VALUES (?, ?, ?, ?, ?)",
        ("u2", "g1", "twitch2", "ch2", "drop_X"),
    )
    await tmp_db._conn.execute(
        "INSERT INTO twitch_links (discord_id, guild_id, twitch_user, last_interaction_channel_id, last_top_drop_id) VALUES (?, ?, ?, ?, ?)",
        ("u3", "g2", "twitch3", None, None),
    )
    await tmp_db._conn.commit()

    rows = await tmp_db.iter_links_with_state()
    assert len(rows) == 3
    for r in rows:
        assert isinstance(r, LinkState)
        assert hasattr(r, "discord_id")
        assert not hasattr(r, "discord_user_id")

    by_user = {r.discord_id: r for r in rows}
    assert by_user["u1"].twitch_user == "twitch1"
    assert by_user["u1"].last_interaction_channel_id == "ch1"
    assert by_user["u1"].last_top_drop_id is None
    assert by_user["u2"].last_top_drop_id == "drop_X"
    assert by_user["u3"].last_interaction_channel_id is None  # dormant row


@pytest.mark.asyncio
async def test_set_last_interaction_channel(tmp_db):
    """After link_twitch + set, iter returns updated channel_id."""
    await tmp_db.link_twitch("u1", "g1", "twitch1", "initial_ch")
    await tmp_db.set_last_interaction_channel("u1", "g1", "new_ch")
    rows = await tmp_db.iter_links_with_state()
    assert len(rows) == 1
    assert rows[0].last_interaction_channel_id == "new_ch"


@pytest.mark.asyncio
async def test_set_last_top_drop(tmp_db):
    """After link_twitch + set_last_top_drop, iter returns updated drop_id."""
    await tmp_db.link_twitch("u1", "g1", "twitch1", "ch1")
    await tmp_db.set_last_top_drop("u1", "g1", "drop_abc")
    rows = await tmp_db.iter_links_with_state()
    assert rows[0].last_top_drop_id == "drop_abc"


@pytest.mark.asyncio
async def test_link_twitch_resets_top_drop(tmp_db):
    """Relinking the same (user, guild) must reset last_top_drop_id to NULL."""
    await tmp_db.link_twitch("u1", "g1", "twitch1", "ch1")
    await tmp_db.set_last_top_drop("u1", "g1", "drop_existing")
    rows = await tmp_db.iter_links_with_state()
    assert rows[0].last_top_drop_id == "drop_existing"
    await tmp_db.link_twitch("u1", "g1", "twitch1", "ch_new")
    rows = await tmp_db.iter_links_with_state()
    assert rows[0].last_top_drop_id is None      # reset
    assert rows[0].last_interaction_channel_id == "ch_new"


@pytest.mark.asyncio
async def test_link_twitch_new_signature_writes_channel(tmp_db):
    """link_twitch(discord_id, guild_id, twitch_user, channel_id) writes the channel."""
    await tmp_db.link_twitch("u1", "g1", "Twitch_User", "ch42")
    rows = await tmp_db.iter_links_with_state()
    assert len(rows) == 1
    assert rows[0].discord_id == "u1"
    assert rows[0].twitch_user == "twitch_user"  # normalized lowercase
    assert rows[0].last_interaction_channel_id == "ch42"
