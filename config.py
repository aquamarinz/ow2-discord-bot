from __future__ import annotations
import os

# --- API ---
OVERFAST_API_BASE = os.getenv("OVERFAST_API_BASE", "https://overfast-api.tekrop.fr")
OWAPI_FALLBACK_BASE = os.getenv("OWAPI_FALLBACK_BASE", "https://owapi.eu")

# Seconds to wait between individual API requests (avoid hammering third-party APIs)
API_REQUEST_DELAY = 0.4

# --- Database ---
DATABASE_PATH = os.getenv("DATABASE_PATH", "ow_bot.db")

# How many periodic snapshots to keep per player
MAX_SNAPSHOTS_PER_PLAYER = 60

# --- Background task ---
# How often (minutes) the bot auto-snapshots every registered player
SNAPSHOT_INTERVAL_MINUTES = 30

# --- Cache TTLs (seconds) ---
LEADERBOARD_CACHE_TTL = 300   # 5 min

# --- Discord embed colours ---
COLOR_SUCCESS  = 0x44FF88
COLOR_ERROR    = 0xFF4444
COLOR_WARNING  = 0xFFAA00
COLOR_INFO     = 0x4488FF
COLOR_GOLD     = 0xFFD700
COLOR_ORANGE   = 0xFF6B35
COLOR_PURPLE   = 0x9B59B6
COLOR_GRAY     = 0x888888

# Rank colours
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

# Numeric priority for sorting (higher = better)
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

ROLE_EMOJIS: dict[str, str]  = {"tank": "🛡️", "damage": "⚔️", "support": "💚"}
ROLE_LABELS: dict[str, str]  = {"tank": "坦克", "damage": "输出", "support": "辅助"}
