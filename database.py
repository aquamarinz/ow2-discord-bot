from __future__ import annotations
import logging
from typing import Optional

from config import DATABASE_URL, DATABASE_PATH

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────── PostgreSQL DDL
_PG_DDL = [
    """CREATE TABLE IF NOT EXISTS players (
        discord_id    TEXT NOT NULL,
        guild_id      TEXT NOT NULL,
        battletag     TEXT NOT NULL,
        registered_at TIMESTAMP DEFAULT NOW(),
        PRIMARY KEY (discord_id, guild_id)
    )""",
    """CREATE TABLE IF NOT EXISTS player_accounts (
        discord_id  TEXT NOT NULL,
        guild_id    TEXT NOT NULL,
        battletag   TEXT NOT NULL,
        label       TEXT,
        added_at    TIMESTAMP DEFAULT NOW(),
        PRIMARY KEY (discord_id, guild_id, battletag)
    )""",
    """CREATE INDEX IF NOT EXISTS idx_players_guild ON players(guild_id)""",
]

# ─────────────────────────────────────────────────────── SQLite DDL
_SQLITE_DDL = """
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
CREATE INDEX IF NOT EXISTS idx_players_guild ON players(guild_id);
"""


def _use_postgres() -> bool:
    return bool(DATABASE_URL)


def _now() -> str:
    return "NOW()" if _use_postgres() else "CURRENT_TIMESTAMP"


def _q(sql: str) -> str:
    """Convert ? placeholders to $1, $2, ... for PostgreSQL."""
    if not _use_postgres():
        return sql
    out: list[str] = []
    idx = 0
    in_quote = False
    for ch in sql:
        if ch == "'":
            in_quote = not in_quote
            out.append(ch)
        elif ch == "?" and not in_quote:
            idx += 1
            out.append(f"${idx}")
        else:
            out.append(ch)
    return "".join(out)


# ═══════════════════════════════════════════════════════ PostgreSQL backend
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


# ═══════════════════════════════════════════════════════ SQLite backend
class _SqliteBackend:
    def __init__(self, path: str):
        self._path = path
        self._conn = None

    async def initialize(self) -> None:
        import aiosqlite
        self._conn = await aiosqlite.connect(self._path)
        self._conn.row_factory = aiosqlite.Row
        await self._conn.executescript(_SQLITE_DDL)
        await self._conn.commit()
        logger.info("SQLite ready at %s", self._path)

    async def close(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None

    async def execute(self, sql: str, params: tuple = ()) -> int:
        cur = await self._conn.execute(sql, params)
        await self._conn.commit()
        return cur.rowcount

    async def fetchone(self, sql: str, params: tuple = ()) -> Optional[dict]:
        cur = await self._conn.execute(sql, params)
        row = await cur.fetchone()
        return dict(row) if row else None

    async def fetchall(self, sql: str, params: tuple = ()) -> list[dict]:
        cur = await self._conn.execute(sql, params)
        rows = await cur.fetchall()
        return [dict(r) for r in rows]


# ═══════════════════════════════════════════════════════ Database
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

    def _q(self, sql: str) -> str:
        return _q(sql)

    async def _execute(self, sql: str, params: tuple = ()) -> int:
        return await self._backend.execute(_q(sql), params)

    async def _fetchone(self, sql: str, params: tuple = ()) -> Optional[dict]:
        return await self._backend.fetchone(_q(sql), params)

    async def _fetchall(self, sql: str, params: tuple = ()) -> list[dict]:
        return await self._backend.fetchall(_q(sql), params)

    # ── players (primary / leaderboard account) ──────────────────────────
    async def register_player(self, discord_id: str, guild_id: str, battletag: str) -> None:
        await self._execute(
            f"""INSERT INTO players (discord_id, guild_id, battletag)
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
            f"""INSERT INTO player_accounts (discord_id, guild_id, battletag, label)
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
