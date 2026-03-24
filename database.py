from __future__ import annotations
import asyncio
import json
import logging
from typing import Any, Optional

from config import DATABASE_URL, DATABASE_PATH, MAX_SNAPSHOTS_PER_PLAYER

logger = logging.getLogger(__name__)

# ──────────────────────────────────────────────────────────── DDL (PostgreSQL)
_PG_DDL = [
    """CREATE TABLE IF NOT EXISTS players (
        discord_id    TEXT NOT NULL,
        guild_id      TEXT NOT NULL,
        battletag     TEXT NOT NULL,
        registered_at TIMESTAMP DEFAULT NOW(),
        last_updated  TIMESTAMP,
        PRIMARY KEY (discord_id, guild_id)
    )""",
    """CREATE TABLE IF NOT EXISTS stats_snapshots (
        id              SERIAL PRIMARY KEY,
        discord_id      TEXT NOT NULL,
        guild_id        TEXT NOT NULL,
        snapshot_type   TEXT DEFAULT 'periodic',
        session_id      TEXT,
        games_played    INTEGER,
        games_won       INTEGER,
        eliminations    INTEGER,
        deaths          INTEGER,
        damage_dealt    INTEGER,
        healing_done    INTEGER,
        time_played_sec INTEGER,
        competitive_data TEXT,
        raw_data        TEXT,
        created_at      TIMESTAMP DEFAULT NOW()
    )""",
    """CREATE TABLE IF NOT EXISTS match_sessions (
        session_id  TEXT PRIMARY KEY,
        guild_id    TEXT NOT NULL,
        created_by  TEXT NOT NULL,
        started_at  TIMESTAMP DEFAULT NOW(),
        ended_at    TIMESTAMP,
        status      TEXT DEFAULT 'active'
    )""",
    """CREATE TABLE IF NOT EXISTS player_goals (
        discord_id      TEXT NOT NULL,
        guild_id        TEXT NOT NULL,
        role            TEXT NOT NULL,
        target_division TEXT NOT NULL,
        target_tier     INTEGER NOT NULL DEFAULT 5,
        set_at          TIMESTAMP DEFAULT NOW(),
        PRIMARY KEY (discord_id, guild_id, role)
    )""",
    """CREATE TABLE IF NOT EXISTS weekly_channels (
        guild_id    TEXT PRIMARY KEY,
        channel_id  TEXT NOT NULL,
        set_by      TEXT NOT NULL,
        set_at      TIMESTAMP DEFAULT NOW()
    )""",
    """CREATE INDEX IF NOT EXISTS idx_snap_player
        ON stats_snapshots(discord_id, guild_id, created_at DESC)""",
    """CREATE INDEX IF NOT EXISTS idx_players_guild
        ON players(guild_id)""",
]

# ──────────────────────────────────────────────────────────── DDL (SQLite)
_SQLITE_DDL = """
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
    snapshot_type   TEXT DEFAULT 'periodic',
    session_id      TEXT,
    games_played    INTEGER,
    games_won       INTEGER,
    eliminations    INTEGER,
    deaths          INTEGER,
    damage_dealt    INTEGER,
    healing_done    INTEGER,
    time_played_sec INTEGER,
    competitive_data TEXT,
    raw_data        TEXT,
    created_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS match_sessions (
    session_id  TEXT PRIMARY KEY,
    guild_id    TEXT NOT NULL,
    created_by  TEXT NOT NULL,
    started_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ended_at    TIMESTAMP,
    status      TEXT DEFAULT 'active'
);
CREATE TABLE IF NOT EXISTS player_goals (
    discord_id      TEXT NOT NULL,
    guild_id        TEXT NOT NULL,
    role            TEXT NOT NULL,
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
CREATE INDEX IF NOT EXISTS idx_snap_player
    ON stats_snapshots(discord_id, guild_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_players_guild
    ON players(guild_id);
"""


def _use_postgres() -> bool:
    return bool(DATABASE_URL)


# ═══════════════════════════════════════════════════════════ PostgreSQL backend
class _PgBackend:
    def __init__(self, dsn: str):
        self._dsn = dsn
        self._pool = None

    async def initialize(self) -> None:
        import asyncpg
        self._pool = await asyncpg.create_pool(self._dsn, min_size=2, max_size=10)
        async with self._pool.acquire() as conn:
            for stmt in _PG_DDL:
                await conn.execute(stmt)
        logger.info("PostgreSQL ready")

    async def close(self) -> None:
        if self._pool:
            await self._pool.close()

    async def execute(self, sql: str, params: tuple = ()) -> int:
        async with self._pool.acquire() as conn:
            result = await conn.execute(sql, *params)
            # asyncpg returns "DELETE 3" / "UPDATE 1" etc.
            parts = result.split() if result else []
            return int(parts[-1]) if len(parts) >= 2 and parts[-1].isdigit() else 0

    async def fetchone(self, sql: str, params: tuple = ()) -> Optional[dict]:
        async with self._pool.acquire() as conn:
            row = await conn.fetchrow(sql, *params)
            return dict(row) if row else None

    async def fetchall(self, sql: str, params: tuple = ()) -> list[dict]:
        async with self._pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
            return [dict(r) for r in rows]


# ═══════════════════════════════════════════════════════════ SQLite backend
class _SqliteBackend:
    def __init__(self, path: str):
        self._path = path

    async def initialize(self) -> None:
        import aiosqlite
        async with aiosqlite.connect(self._path) as db:
            await db.executescript(_SQLITE_DDL)
            await db.commit()
        logger.info("SQLite ready at %s", self._path)

    async def close(self) -> None:
        pass

    async def execute(self, sql: str, params: tuple = ()) -> int:
        import aiosqlite
        async with aiosqlite.connect(self._path) as db:
            cur = await db.execute(sql, params)
            await db.commit()
            return cur.rowcount

    async def fetchone(self, sql: str, params: tuple = ()) -> Optional[dict]:
        import aiosqlite
        async with aiosqlite.connect(self._path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(sql, params)
            row = await cur.fetchone()
            return dict(row) if row else None

    async def fetchall(self, sql: str, params: tuple = ()) -> list[dict]:
        import aiosqlite
        async with aiosqlite.connect(self._path) as db:
            db.row_factory = aiosqlite.Row
            cur = await db.execute(sql, params)
            rows = await cur.fetchall()
            return [dict(r) for r in rows]


# ═══════════════════════════════════════════════════════════ Param helper
def _p(*args) -> tuple:
    """Return args tuple — placeholder conversion handled at query level."""
    return args


def _q(sql: str) -> str:
    """Convert SQLite-style ? placeholders to PostgreSQL $1, $2, ... if needed."""
    if not _use_postgres():
        return sql
    out, idx = [], 0
    for ch in sql:
        if ch == "?":
            idx += 1
            out.append(f"${idx}")
        else:
            out.append(ch)
    return "".join(out)


# ═══════════════════════════════════════════════════════════ Database class
class Database:
    def __init__(self):
        if _use_postgres():
            self._backend = _PgBackend(DATABASE_URL)
        else:
            self._backend = _SqliteBackend(DATABASE_PATH)

    async def initialize(self) -> None:
        await self._backend.initialize()

    async def close(self) -> None:
        await self._backend.close()

    # ------------------------------------------------------------------ helpers
    async def _fetchone(self, sql: str, params: tuple = ()) -> Optional[dict]:
        return await self._backend.fetchone(_q(sql), params)

    async def _fetchall(self, sql: str, params: tuple = ()) -> list[dict]:
        return await self._backend.fetchall(_q(sql), params)

    async def _execute(self, sql: str, params: tuple = ()) -> int:
        return await self._backend.execute(_q(sql), params)

    # ------------------------------------------------------------------ players
    async def register_player(self, discord_id: str, guild_id: str, battletag: str) -> None:
        await self._execute(
            """INSERT INTO players (discord_id, guild_id, battletag)
               VALUES (?, ?, ?)
               ON CONFLICT(discord_id, guild_id)
               DO UPDATE SET battletag = excluded.battletag,
                             last_updated = NOW()"""
            if _use_postgres() else
            """INSERT INTO players (discord_id, guild_id, battletag)
               VALUES (?, ?, ?)
               ON CONFLICT(discord_id, guild_id)
               DO UPDATE SET battletag = excluded.battletag,
                             last_updated = CURRENT_TIMESTAMP""",
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
        await self._execute(
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

    def _decode_snapshot(self, row: dict) -> dict:
        for key in ("competitive_data", "raw_data"):
            val = row.get(key)
            if val and isinstance(val, str):
                try:
                    row[key] = json.loads(val)
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
        if _use_postgres():
            await self._execute(
                """DELETE FROM stats_snapshots
                   WHERE discord_id=? AND guild_id=? AND snapshot_type='periodic'
                     AND id NOT IN (
                         SELECT id FROM stats_snapshots
                         WHERE discord_id=? AND guild_id=? AND snapshot_type='periodic'
                         ORDER BY created_at DESC LIMIT ?
                     )""",
                (discord_id, guild_id, discord_id, guild_id, keep),
            )
        else:
            await self._execute(
                """DELETE FROM stats_snapshots
                   WHERE discord_id=? AND guild_id=? AND snapshot_type='periodic'
                     AND id NOT IN (
                         SELECT id FROM stats_snapshots
                         WHERE discord_id=? AND guild_id=? AND snapshot_type='periodic'
                         ORDER BY created_at DESC LIMIT ?
                     )""",
                (discord_id, guild_id, discord_id, guild_id, keep),
            )

    # --------------------------------------------------------- match sessions
    async def create_match_session(
        self, session_id: str, guild_id: str, created_by: str
    ) -> None:
        await self._execute(
            """INSERT INTO match_sessions (session_id, guild_id, created_by, status)
               VALUES (?, ?, ?, 'active')
               ON CONFLICT(session_id) DO UPDATE SET
                   status='active', started_at={}""".format(
                "NOW()" if _use_postgres() else "CURRENT_TIMESTAMP"
            ),
            (session_id, guild_id, created_by),
        )

    async def get_active_session(self, guild_id: str) -> Optional[dict]:
        return await self._fetchone(
            """SELECT * FROM match_sessions
               WHERE guild_id=? AND status='active'
               ORDER BY started_at DESC LIMIT 1""",
            (guild_id,),
        )

    async def close_session(self, session_id: str) -> None:
        await self._execute(
            """UPDATE match_sessions
               SET status='completed', ended_at={}
               WHERE session_id=?""".format(
                "NOW()" if _use_postgres() else "CURRENT_TIMESTAMP"
            ),
            (session_id,),
        )

    async def get_match_history(self, guild_id: str, limit: int = 10) -> list[dict]:
        return await self._fetchall(
            """SELECT ms.session_id, ms.created_by, ms.started_at, ms.ended_at,
                      COUNT(DISTINCT ss.discord_id) AS participant_count
               FROM match_sessions ms
               LEFT JOIN stats_snapshots ss
                   ON ms.session_id = ss.session_id AND ss.snapshot_type = 'match_end'
               WHERE ms.guild_id = ? AND ms.status = 'completed'
               GROUP BY ms.session_id, ms.created_by, ms.started_at, ms.ended_at
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
        await self._execute(
            """INSERT INTO player_goals (discord_id, guild_id, role, target_division, target_tier)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(discord_id, guild_id, role)
               DO UPDATE SET target_division = excluded.target_division,
                             target_tier     = excluded.target_tier,
                             set_at          = {}""".format(
                "NOW()" if _use_postgres() else "CURRENT_TIMESTAMP"
            ),
            (discord_id, guild_id, role, division, tier),
        )

    async def get_goals(self, discord_id: str, guild_id: str) -> list[dict]:
        return await self._fetchall(
            "SELECT * FROM player_goals WHERE discord_id = ? AND guild_id = ?",
            (discord_id, guild_id),
        )

    async def delete_goal(self, discord_id: str, guild_id: str, role: str) -> bool:
        count = await self._execute(
            "DELETE FROM player_goals WHERE discord_id=? AND guild_id=? AND role=?",
            (discord_id, guild_id, role),
        )
        return count > 0

    # --------------------------------------------------------- weekly channels
    async def set_weekly_channel(
        self, guild_id: str, channel_id: str, set_by: str
    ) -> None:
        await self._execute(
            """INSERT INTO weekly_channels (guild_id, channel_id, set_by)
               VALUES (?, ?, ?)
               ON CONFLICT(guild_id)
               DO UPDATE SET channel_id = excluded.channel_id,
                             set_by     = excluded.set_by,
                             set_at     = {}""".format(
                "NOW()" if _use_postgres() else "CURRENT_TIMESTAMP"
            ),
            (guild_id, channel_id, set_by),
        )

    async def get_weekly_channel(self, guild_id: str) -> Optional[dict]:
        return await self._fetchone(
            "SELECT * FROM weekly_channels WHERE guild_id = ?", (guild_id,)
        )

    async def get_all_weekly_channels(self) -> list[dict]:
        return await self._fetchall("SELECT * FROM weekly_channels")

    async def disable_weekly_channel(self, guild_id: str) -> None:
        await self._execute(
            "DELETE FROM weekly_channels WHERE guild_id = ?", (guild_id,)
        )

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
