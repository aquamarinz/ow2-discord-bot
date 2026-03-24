from __future__ import annotations
import os

# --- API ---
OVERFAST_API_BASE   = os.getenv("OVERFAST_API_BASE",   "https://overfast-api.tekrop.fr")
OWAPI_FALLBACK_BASE = os.getenv("OWAPI_FALLBACK_BASE", "https://owapi.eu")

# --- Database ---
DATABASE_URL  = os.getenv("DATABASE_URL",  "")
DATABASE_PATH = os.getenv("DATABASE_PATH", "ow_bot.db")

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
