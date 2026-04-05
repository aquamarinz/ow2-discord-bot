"""One-time migration: export PostgreSQL data to SQLite.

Usage:
    DATABASE_URL=postgres://... python migrate_pg_to_sqlite.py [output.db]

Run this BEFORE removing the PostgreSQL add-on from Railway.
After verifying the .db file, upload it to the Railway volume at /data/ow_bot.db.
"""
from __future__ import annotations
import asyncio
import sys
import os


async def migrate(pg_url: str, sqlite_path: str) -> None:
    import asyncpg
    import aiosqlite

    pg = await asyncpg.connect(pg_url)
    db = await aiosqlite.connect(sqlite_path)

    # Create tables
    await db.executescript("""
        CREATE TABLE IF NOT EXISTS players (
            discord_id TEXT NOT NULL, guild_id TEXT NOT NULL,
            battletag TEXT NOT NULL, registered_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (discord_id, guild_id)
        );
        CREATE TABLE IF NOT EXISTS player_accounts (
            discord_id TEXT NOT NULL, guild_id TEXT NOT NULL,
            battletag TEXT NOT NULL, label TEXT,
            added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (discord_id, guild_id, battletag)
        );
    """)

    # Migrate players
    rows = await pg.fetch("SELECT discord_id, guild_id, battletag FROM players")
    for r in rows:
        await db.execute(
            "INSERT OR REPLACE INTO players (discord_id, guild_id, battletag) VALUES (?, ?, ?)",
            (r["discord_id"], r["guild_id"], r["battletag"]),
        )
    print(f"Migrated {len(rows)} players")

    # Migrate accounts
    rows = await pg.fetch("SELECT discord_id, guild_id, battletag, label FROM player_accounts")
    for r in rows:
        await db.execute(
            "INSERT OR REPLACE INTO player_accounts (discord_id, guild_id, battletag, label) VALUES (?, ?, ?, ?)",
            (r["discord_id"], r["guild_id"], r["battletag"], r["label"]),
        )
    print(f"Migrated {len(rows)} accounts")

    await db.commit()
    await db.close()
    await pg.close()
    print(f"Done → {sqlite_path}")


def main() -> None:
    pg_url = os.getenv("DATABASE_URL")
    if not pg_url:
        print("ERROR: set DATABASE_URL to your PostgreSQL connection string")
        sys.exit(1)
    out = sys.argv[1] if len(sys.argv) > 1 else "ow_bot.db"
    asyncio.run(migrate(pg_url, out))


if __name__ == "__main__":
    main()
