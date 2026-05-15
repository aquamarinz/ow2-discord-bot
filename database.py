from __future__ import annotations
from dataclasses import dataclass
import logging
import re
from typing import Optional

import config

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LinkState:
    discord_id: str
    guild_id: str
    twitch_user: str
    last_interaction_channel_id: str | None
    last_top_drop_id: str | None


_DDL = """
CREATE TABLE IF NOT EXISTS players (
    discord_id    TEXT NOT NULL,
    guild_id      TEXT NOT NULL,
    battletag     TEXT NOT NULL,
    registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (discord_id, guild_id)
);
CREATE TABLE IF NOT EXISTS player_accounts (
    discord_id  TEXT NOT NULL,
    guild_id    TEXT NOT NULL,
    battletag   TEXT NOT NULL,
    label       TEXT,
    added_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (discord_id, guild_id, battletag)
);
CREATE TABLE IF NOT EXISTS twitch_links (
    discord_id  TEXT NOT NULL,
    guild_id    TEXT NOT NULL,
    twitch_user TEXT NOT NULL,
    linked_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (discord_id, guild_id)
);
CREATE INDEX IF NOT EXISTS idx_players_guild ON players(guild_id);
CREATE INDEX IF NOT EXISTS idx_twitch_links_user ON twitch_links(twitch_user);
"""


class Database:
    def __init__(self) -> None:
        self._conn = None

    async def initialize(self) -> None:
        import aiosqlite
        self._conn = await aiosqlite.connect(config.DATABASE_PATH)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(_DDL)
        await self._conn.commit()
        await self._migrate_v2()
        logger.info("SQLite ready at %s (v2 migration applied)", config.DATABASE_PATH)

    async def _migrate_v2(self) -> None:
        """Idempotent ALTER TABLE for last_interaction_channel_id + last_top_drop_id."""
        cur = await self._conn.execute("PRAGMA table_info(twitch_links)")
        cols = {row[1] for row in await cur.fetchall()}
        await cur.close()
        if "last_interaction_channel_id" not in cols:
            await self._conn.execute(
                "ALTER TABLE twitch_links ADD COLUMN last_interaction_channel_id TEXT"
            )
        if "last_top_drop_id" not in cols:
            await self._conn.execute(
                "ALTER TABLE twitch_links ADD COLUMN last_top_drop_id TEXT"
            )
        await self._conn.commit()

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    async def _execute(self, sql: str, params: tuple = ()) -> int:
        cur = await self._conn.execute(sql, params)
        await self._conn.commit()
        return cur.rowcount

    async def _fetchone(self, sql: str, params: tuple = ()) -> Optional[dict]:
        cur = await self._conn.execute(sql, params)
        row = await cur.fetchone()
        return dict(row) if row else None

    async def _fetchall(self, sql: str, params: tuple = ()) -> list[dict]:
        cur = await self._conn.execute(sql, params)
        rows = await cur.fetchall()
        return [dict(r) for r in rows]

    # ── players (primary / leaderboard account) ──────────────────────────
    async def register_player(self, discord_id: str, guild_id: str, battletag: str) -> None:
        await self._execute(
            """INSERT INTO players (discord_id, guild_id, battletag)
               VALUES (?, ?, ?)
               ON CONFLICT(discord_id, guild_id)
               DO UPDATE SET battletag = excluded.battletag""",
            (discord_id, guild_id, battletag),
        )

    async def unregister_player(self, discord_id: str, guild_id: str) -> bool:
        count = await self._execute(
            "DELETE FROM players WHERE discord_id = ? AND guild_id = ?",
            (discord_id, guild_id),
        )
        return count > 0

    async def get_player(self, discord_id: str, guild_id: str) -> Optional[dict]:
        return await self._fetchone(
            "SELECT * FROM players WHERE discord_id = ? AND guild_id = ?",
            (discord_id, guild_id),
        )

    async def get_all_players(self, guild_id: str) -> list[dict]:
        return await self._fetchall(
            "SELECT * FROM players WHERE guild_id = ?", (guild_id,)
        )

    # ── player_accounts (saved IDs) ───────────────────────────────────────
    async def add_account(
        self, discord_id: str, guild_id: str, battletag: str, label: Optional[str] = None
    ) -> None:
        await self._execute(
            """INSERT INTO player_accounts (discord_id, guild_id, battletag, label)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(discord_id, guild_id, battletag)
               DO UPDATE SET label = excluded.label""",
            (discord_id, guild_id, battletag, label),
        )

    async def remove_account(self, discord_id: str, guild_id: str, battletag: str) -> bool:
        count = await self._execute(
            "DELETE FROM player_accounts WHERE discord_id=? AND guild_id=? AND battletag=?",
            (discord_id, guild_id, battletag),
        )
        return count > 0

    async def get_accounts(self, discord_id: str, guild_id: str) -> list[dict]:
        return await self._fetchall(
            "SELECT * FROM player_accounts WHERE discord_id=? AND guild_id=? ORDER BY added_at",
            (discord_id, guild_id),
        )

    # ── twitch_links (Discord ↔ Twitch self-reported binding) ────────────
    _TWITCH_USER_RE = re.compile(r"^[a-z0-9_]{3,25}$")

    @classmethod
    def _canonical_twitch_user(cls, raw: str) -> str:
        """Strip + lowercase + regex validate. Raises ValueError if invalid."""
        canonical = raw.strip().lower()
        if not cls._TWITCH_USER_RE.match(canonical):
            raise ValueError(
                f"Twitch username '{raw}' invalid after normalization "
                f"(must match {cls._TWITCH_USER_RE.pattern})"
            )
        return canonical

    async def link_twitch(
        self, discord_id: str, guild_id: str, twitch_user: str, channel_id: str
    ) -> None:
        canonical = self._canonical_twitch_user(twitch_user)
        await self._execute(
            """INSERT INTO twitch_links (
                   discord_id, guild_id, twitch_user, last_interaction_channel_id
               ) VALUES (?, ?, ?, ?)
               ON CONFLICT(discord_id, guild_id)
               DO UPDATE SET twitch_user = excluded.twitch_user,
                             last_interaction_channel_id = excluded.last_interaction_channel_id,
                             last_top_drop_id = NULL,
                             linked_at = CURRENT_TIMESTAMP""",
            (discord_id, guild_id, canonical, channel_id),
        )

    async def unlink_twitch(self, discord_id: str, guild_id: str) -> bool:
        count = await self._execute(
            "DELETE FROM twitch_links WHERE discord_id = ? AND guild_id = ?",
            (discord_id, guild_id),
        )
        return count > 0

    async def get_twitch_link(self, discord_id: str, guild_id: str) -> dict | None:
        return await self._fetchone(
            "SELECT * FROM twitch_links WHERE discord_id = ? AND guild_id = ?",
            (discord_id, guild_id),
        )

    async def iter_links_with_state(self) -> list[LinkState]:
        rows = await self._fetchall(
            """SELECT discord_id, guild_id, twitch_user,
                      last_interaction_channel_id, last_top_drop_id
               FROM twitch_links"""
        )
        return [
            LinkState(
                discord_id=r["discord_id"],
                guild_id=r["guild_id"],
                twitch_user=r["twitch_user"],
                last_interaction_channel_id=r["last_interaction_channel_id"],
                last_top_drop_id=r["last_top_drop_id"],
            )
            for r in rows
        ]

    async def set_last_interaction_channel(
        self, discord_id: str, guild_id: str, channel_id: str
    ) -> None:
        await self._execute(
            """UPDATE twitch_links SET last_interaction_channel_id = ?
               WHERE discord_id = ? AND guild_id = ?""",
            (channel_id, discord_id, guild_id),
        )

    async def set_last_top_drop(
        self, discord_id: str, guild_id: str, drop_id: str
    ) -> None:
        await self._execute(
            """UPDATE twitch_links SET last_top_drop_id = ?
               WHERE discord_id = ? AND guild_id = ?""",
            (drop_id, discord_id, guild_id),
        )
