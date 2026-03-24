from __future__ import annotations
import asyncio
import json
import logging
from typing import Any, Optional

import aiosqlite

from config import DATABASE_PATH, MAX_SNAPSHOTS_PER_PLAYER

logger = logging.getLogger(__name__)

_DDL = """
CREATE TABLE IF NOT EXISTS players (
    discord_id  TEXT NOT NULL,
    guild_id    TEXT NOT NULL,
    battletag   TEXT NOT NULL,
    registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_updated  TIMESTAMP,
    PRIMARY KEY (discord_id, guild_id)
);

CREATE TABLE IF NOT EXISTS stats_snapshots (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    discord_id      TEXT NOT NULL,
    guild_id        TEXT NOT NULL,
    snapshot_type   TEXT DEFAULT 'periodic',   -- 'periodic' | 'match_start' | 'match_end'
    session_id      TEXT,
    games_played    INTEGER,
    games_won       INTEGER,
    eliminations    INTEGER,
    deaths          INTEGER,
    damage_dealt    INTEGER,
    healing_done    INTEGER,
    time_played_sec INTEGER,
    competitive_data TEXT,                      -- JSON: role -> {division, tier}
    raw_data        TEXT,                       -- Full JSON blob from API
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS match_sessions (
    session_id  TEXT PRIMARY KEY,
    guild_id    TEXT NOT NULL,
    created_by  TEXT NOT NULL,
    started_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ended_at    TIMESTAMP,
    status      TEXT DEFAULT 'active'           -- 'active' | 'completed'
);

CREATE INDEX IF NOT EXISTS idx_snap_player
    ON stats_snapshots(discord_id, guild_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_players_guild
    ON players(guild_id);

CREATE TABLE IF NOT EXISTS player_goals (
    discord_id      TEXT NOT NULL,
    guild_id        TEXT NOT NULL,
    role            TEXT NOT NULL,   -- 'tank' | 'damage' | 'support'
    target_division TEXT NOT NULL,
    target_tier     INTEGER NOT NULL DEFAULT 5,
    set_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (discord_id, guild_id, role)
);

CREATE TABLE IF NOT EXISTS weekly_channels (
    guild_id    TEXT PRIMARY KEY,
    channel_id  TEXT NOT NULL,
    set_by      TEXT NOT NULL,
    set_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


class Database:
    def __init__(self, path: str = DATABASE_PATH):
        self.path = path

    async def initialize(self) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.executescript(_DDL)
            await db.commit()
        logger.info("Database ready at %s", self.path)

    # ------------------------------------------------------------------ helpers
    async def _fetchone(self, sql: str, params: tuple = ()) -> Optional[dict]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(sql, params)
            row = await cur.fetchone()
            return dict(row) if row else None

    async def _fetchall(self, sql: str, params: tuple = ()) -> list[dict]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(sql, params)
            rows = await cur.fetchall()
            return [dict(r) for r in rows]

    # ------------------------------------------------------------------ players
    async def register_player(self, discord_id: str, guild_id: str, battletag: str) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """INSERT INTO players (discord_id, guild_id, battletag)
                   VALUES (?, ?, ?)
                   ON CONFLICT(discord_id, guild_id)
                   DO UPDATE SET battletag = excluded.battletag,
                                 last_updated = CURRENT_TIMESTAMP""",
                (discord_id, guild_id, battletag),
            )
            await db.commit()

    async def unregister_player(self, discord_id: str, guild_id: str) -> bool:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(
                "DELETE FROM players WHERE discord_id = ? AND guild_id = ?",
                (discord_id, guild_id),
            )
            await db.commit()
            return cur.rowcount > 0

    async def get_player(self, discord_id: str, guild_id: str) -> Optional[dict]:
        return await self._fetchone(
            "SELECT * FROM players WHERE discord_id = ? AND guild_id = ?",
            (discord_id, guild_id),
        )

    async def get_all_players(self, guild_id: Optional[str] = None) -> list[dict]:
        if guild_id:
            return await self._fetchall(
                "SELECT * FROM players WHERE guild_id = ?", (guild_id,)
            )
        return await self._fetchall("SELECT * FROM players")

    # ---------------------------------------------------------------- snapshots
    async def save_snapshot(
        self,
        discord_id: str,
        guild_id: str,
        stats: dict[str, Any],
        snapshot_type: str = "periodic",
        session_id: Optional[str] = None,
    ) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """INSERT INTO stats_snapshots
                   (discord_id, guild_id, snapshot_type, session_id,
                    games_played, games_won, eliminations, deaths,
                    damage_dealt, healing_done, time_played_sec,
                    competitive_data, raw_data)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    discord_id,
                    guild_id,
                    snapshot_type,
                    session_id,
                    stats.get("games_played"),
                    stats.get("games_won"),
                    stats.get("eliminations"),
                    stats.get("deaths"),
                    stats.get("damage_dealt"),
                    stats.get("healing_done"),
                    stats.get("time_played_seconds"),
                    json.dumps(stats.get("competitive")),
                    json.dumps(stats),
                ),
            )
            await db.commit()

    def _decode_snapshot(self, row: dict) -> dict:
        for key in ("competitive_data", "raw_data"):
            if row.get(key):
                try:
                    row[key] = json.loads(row[key])
                except (json.JSONDecodeError, TypeError):
                    row[key] = {}
        return row

    async def get_latest_snapshot(
        self,
        discord_id: str,
        guild_id: str,
        snapshot_type: Optional[str] = None,
    ) -> Optional[dict]:
        if snapshot_type:
            row = await self._fetchone(
                """SELECT * FROM stats_snapshots
                   WHERE discord_id=? AND guild_id=? AND snapshot_type=?
                   ORDER BY created_at DESC LIMIT 1""",
                (discord_id, guild_id, snapshot_type),
            )
        else:
            row = await self._fetchone(
                """SELECT * FROM stats_snapshots
                   WHERE discord_id=? AND guild_id=?
                   ORDER BY created_at DESC LIMIT 1""",
                (discord_id, guild_id),
            )
        return self._decode_snapshot(row) if row else None

    async def get_session_snapshot(
        self, discord_id: str, guild_id: str, session_id: str
    ) -> Optional[dict]:
        """Return the earliest snapshot for a given match session (pre-match data)."""
        row = await self._fetchone(
            """SELECT * FROM stats_snapshots
               WHERE discord_id=? AND guild_id=? AND session_id=?
               ORDER BY created_at ASC LIMIT 1""",
            (discord_id, guild_id, session_id),
        )
        return self._decode_snapshot(row) if row else None

    async def get_trend_snapshots(
        self, discord_id: str, guild_id: str, limit: int = 50
    ) -> list[dict]:
        rows = await self._fetchall(
            """SELECT * FROM stats_snapshots
               WHERE discord_id=? AND guild_id=? AND snapshot_type='periodic'
               ORDER BY created_at DESC LIMIT ?""",
            (discord_id, guild_id, limit),
        )
        return [self._decode_snapshot(r) for r in rows]

    async def cleanup_old_snapshots(
        self, discord_id: str, guild_id: str, keep: int = MAX_SNAPSHOTS_PER_PLAYER
    ) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """DELETE FROM stats_snapshots
                   WHERE discord_id=? AND guild_id=? AND snapshot_type='periodic'
                     AND id NOT IN (
                         SELECT id FROM stats_snapshots
                         WHERE discord_id=? AND guild_id=? AND snapshot_type='periodic'
                         ORDER BY created_at DESC LIMIT ?
                     )""",
                (discord_id, guild_id, discord_id, guild_id, keep),
            )
            await db.commit()

    # --------------------------------------------------------- match sessions
    async def create_match_session(
        self, session_id: str, guild_id: str, created_by: str
    ) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """INSERT OR REPLACE INTO match_sessions
                   (session_id, guild_id, created_by, status)
                   VALUES (?, ?, ?, 'active')""",
                (session_id, guild_id, created_by),
            )
            await db.commit()

    async def get_active_session(self, guild_id: str) -> Optional[dict]:
        return await self._fetchone(
            """SELECT * FROM match_sessions
               WHERE guild_id=? AND status='active'
               ORDER BY started_at DESC LIMIT 1""",
            (guild_id,),
        )

    async def close_session(self, session_id: str) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """UPDATE match_sessions
                   SET status='completed', ended_at=CURRENT_TIMESTAMP
                   WHERE session_id=?""",
                (session_id,),
            )
            await db.commit()

    async def get_match_history(self, guild_id: str, limit: int = 10) -> list[dict]:
        return await self._fetchall(
            """SELECT ms.session_id, ms.created_by, ms.started_at, ms.ended_at,
                      COUNT(DISTINCT ss.discord_id) AS participant_count
               FROM match_sessions ms
               LEFT JOIN stats_snapshots ss
                   ON ms.session_id = ss.session_id AND ss.snapshot_type = 'match_end'
               WHERE ms.guild_id = ? AND ms.status = 'completed'
               GROUP BY ms.session_id
               ORDER BY ms.started_at DESC
               LIMIT ?""",
            (guild_id, limit),
        )

    async def get_session_participants(self, guild_id: str, session_id: str) -> list[dict]:
        return await self._fetchall(
            """SELECT DISTINCT ss.discord_id,
                      COALESCE(p.battletag, ss.discord_id) AS battletag
               FROM stats_snapshots ss
               LEFT JOIN players p
                   ON ss.discord_id = p.discord_id AND ss.guild_id = p.guild_id
               WHERE ss.guild_id = ? AND ss.session_id = ? AND ss.snapshot_type = 'match_end'""",
            (guild_id, session_id),
        )

    # ------------------------------------------------------------------ goals
    async def set_goal(
        self, discord_id: str, guild_id: str, role: str, division: str, tier: int
    ) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """INSERT INTO player_goals (discord_id, guild_id, role, target_division, target_tier)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(discord_id, guild_id, role)
                   DO UPDATE SET target_division = excluded.target_division,
                                 target_tier     = excluded.target_tier,
                                 set_at          = CURRENT_TIMESTAMP""",
                (discord_id, guild_id, role, division, tier),
            )
            await db.commit()

    async def get_goals(self, discord_id: str, guild_id: str) -> list[dict]:
        return await self._fetchall(
            "SELECT * FROM player_goals WHERE discord_id = ? AND guild_id = ?",
            (discord_id, guild_id),
        )

    async def delete_goal(self, discord_id: str, guild_id: str, role: str) -> bool:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(
                "DELETE FROM player_goals WHERE discord_id=? AND guild_id=? AND role=?",
                (discord_id, guild_id, role),
            )
            await db.commit()
            return cur.rowcount > 0

    # --------------------------------------------------------- weekly channels
    async def set_weekly_channel(
        self, guild_id: str, channel_id: str, set_by: str
    ) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """INSERT INTO weekly_channels (guild_id, channel_id, set_by)
                   VALUES (?, ?, ?)
                   ON CONFLICT(guild_id)
                   DO UPDATE SET channel_id = excluded.channel_id,
                                 set_by     = excluded.set_by,
                                 set_at     = CURRENT_TIMESTAMP""",
                (guild_id, channel_id, set_by),
            )
            await db.commit()

    async def get_weekly_channel(self, guild_id: str) -> Optional[dict]:
        return await self._fetchone(
            "SELECT * FROM weekly_channels WHERE guild_id = ?", (guild_id,)
        )

    async def get_all_weekly_channels(self) -> list[dict]:
        return await self._fetchall("SELECT * FROM weekly_channels")

    async def disable_weekly_channel(self, guild_id: str) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "DELETE FROM weekly_channels WHERE guild_id = ?", (guild_id,)
            )
            await db.commit()

    # ------------------------------------------- time-filtered snapshots
    async def get_snapshots_since(
        self, discord_id: str, guild_id: str, since_iso: str
    ) -> list[dict]:
        rows = await self._fetchall(
            """SELECT * FROM stats_snapshots
               WHERE discord_id=? AND guild_id=? AND snapshot_type='periodic'
                 AND created_at >= ?
               ORDER BY created_at DESC""",
            (discord_id, guild_id, since_iso),
        )
        return [self._decode_snapshot(r) for r in rows]
