from __future__ import annotations
import os

# --- API ---
OVERFAST_API_BASE   = os.getenv("OVERFAST_API_BASE",   "https://overfast-api.tekrop.fr")
OWAPI_FALLBACK_BASE = os.getenv("OWAPI_FALLBACK_BASE", "https://owapi.eu")

# --- Database (SQLite only) ---
# On Railway the volume is mounted at /data; locally falls back to ./ow_bot.db
_DEFAULT_DB_PATH = "/data/ow_bot.db" if os.getenv("RAILWAY_ENVIRONMENT") else "ow_bot.db"
DATABASE_PATH = os.getenv("DATABASE_PATH", _DEFAULT_DB_PATH)

# --- Stadium ---
SUPABASE_STADIUM_URL = os.getenv("SUPABASE_STADIUM_URL", "")
SUPABASE_STADIUM_KEY = os.getenv("SUPABASE_STADIUM_KEY", "")

# --- API request throttle ---
API_REQUEST_DELAY = 0.5   # seconds between fallback retries

# --- Leaderboard cache ---
LEADERBOARD_CACHE_TTL = 300   # seconds

# --- Rank data ---
RANK_COLORS: dict[str, int] = {
    "Bronze":       0xCD7F32,
    "Silver":       0xC0C0C0,
    "Gold":         0xFFD700,
    "Platinum":     0x00FFFF,
    "Diamond":      0x00BFFF,
    "Master":       0x9400D3,
    "Grandmaster":  0xFF8C00,
    "Champion":     0xFF4500,
    "Unranked":     0x888888,
}

RANK_ORDER: dict[str, int] = {
    "Champion":    8,
    "Grandmaster": 7,
    "Master":      6,
    "Diamond":     5,
    "Platinum":    4,
    "Gold":        3,
    "Silver":      2,
    "Bronze":      1,
    "Unranked":    0,
}

RANK_EMOJIS: dict[str, str] = {
    "Bronze":       "🥉",
    "Silver":       "🥈",
    "Gold":         "🥇",
    "Platinum":     "💎",
    "Diamond":      "💠",
    "Master":       "🔮",
    "Grandmaster":  "👑",
    "Champion":     "🏆",
    "Unranked":     "❓",
}

ROLE_EMOJIS: dict[str, str] = {"tank": "🛡️", "damage": "⚔️", "support": "💚"}
ROLE_LABELS: dict[str, str] = {"tank": "坦克", "damage": "输出", "support": "辅助"}

# ─── Twitch miners (for /miner command) ────────────────────────────────
import re as _re_miners  # local alias to not pollute top imports

_TWITCH_USER_RE = _re_miners.compile(r"^[a-z0-9_]{3,25}$")


def parse_twitch_miners(raw: str) -> dict[str, tuple[str, int]]:
    """Parse TWITCH_MINERS env string into {canonical_user: (container_name, port)}.

    Format: ``user1=container1:port1,user2=container2:port2``
    Empty string / whitespace → empty dict.
    Fail-fast on any invalid entry or duplicate canonical user key.
    """
    raw = (raw or "").strip()
    if not raw:
        return {}

    result: dict[str, tuple[str, int]] = {}
    seen_canonicals: set[str] = set()

    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue

        if "=" not in entry:
            raise ValueError(
                f"TWITCH_MINERS entry '{entry}' format: expected user=container:port"
            )
        user_raw, locator = entry.split("=", 1)
        if ":" not in locator:
            raise ValueError(
                f"TWITCH_MINERS entry '{entry}' format: expected user=container:port"
            )

        user = user_raw.strip().lower()
        container, port_str = locator.rsplit(":", 1)
        container = container.strip()
        port_str = port_str.strip()

        if not _TWITCH_USER_RE.match(user):
            raise ValueError(
                f"TWITCH_MINERS entry '{entry}': twitch user '{user_raw}' invalid "
                f"after normalization (must match {_TWITCH_USER_RE.pattern})"
            )
        if not container:
            raise ValueError(f"TWITCH_MINERS entry '{entry}': empty container name")
        try:
            port = int(port_str)
        except ValueError:
            raise ValueError(
                f"TWITCH_MINERS entry '{entry}': port '{port_str}' not numeric"
            )
        if user in seen_canonicals:
            raise ValueError(
                f"TWITCH_MINERS: duplicate canonical user '{user}' "
                f"(remember Alice / alice / ALICE all normalize the same)"
            )

        seen_canonicals.add(user)
        result[user] = (container, port)

    return result


# Parsed once at import; raises on bad config (fail-fast at bot startup)
TWITCH_MINERS = parse_twitch_miners(os.getenv("TWITCH_MINERS", ""))
