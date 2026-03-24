from __future__ import annotations
"""
OW2 API client with OverFast API as primary and owapi.eu as fallback.

All public methods return None on hard failure and a dict with '_private': True
when the player's profile is set to private.
"""
import asyncio
import logging
from typing import Any, Optional

import aiohttp

from config import API_REQUEST_DELAY, OVERFAST_API_BASE, OWAPI_FALLBACK_BASE

logger = logging.getLogger(__name__)

_TIMEOUT = aiohttp.ClientTimeout(total=10)
_HEADERS = {"User-Agent": "OW2-Discord-Bot/1.0 (github.com/discord-ow-bot)"}


class OWAPIClient:
    def __init__(self) -> None:
        self._session: Optional[aiohttp.ClientSession] = None
        self._closing = False

    async def _sess(self) -> aiohttp.ClientSession:
        if self._closing:
            raise RuntimeError("Client is shutting down")
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(timeout=_TIMEOUT, headers=_HEADERS)
        return self._session

    async def close(self) -> None:
        self._closing = True
        if self._session and not self._session.closed:
            await self._session.close()
        self._session = None

    # ----------------------------------------------------------------- low-level
    async def _get(self, url: str) -> Optional[dict[str, Any]]:
        sess = await self._sess()
        try:
            async with sess.get(url) as resp:
                if resp.status == 200:
                    return await resp.json(content_type=None)
                if resp.status == 404:
                    logger.debug("404 for %s", url)
                    return None
                if resp.status in (422, 451):
                    # OverFast uses 422 for private profiles
                    return {"_private": True}
                logger.warning("HTTP %s for %s", resp.status, url)
                return None
        except asyncio.TimeoutError:
            logger.warning("Timeout: %s", url)
            return None
        except Exception as exc:
            logger.error("GET %s failed: %s", url, exc)
            return None

    # --------------------------------------------------------------- public API
    async def get_player_summary(self, battletag: str) -> Optional[dict[str, Any]]:
        """
        Returns a normalized summary dict, or None if the API is unreachable.
        Summary dict keys: battletag, username, avatar, endorsement,
                           competitive {role: {division, tier, rank_icon}}, _private
        """
        tag = battletag.replace("#", "-")

        # ---- primary: OverFast ----
        data = await self._get(f"{OVERFAST_API_BASE}/players/{tag}/summary")
        if data is not None:
            return self._parse_overfast_summary(battletag, data)

        # ---- fallback: owapi.eu ----
        await asyncio.sleep(API_REQUEST_DELAY)
        data = await self._get(f"{OWAPI_FALLBACK_BASE}/profile/pc/{tag}")
        if data is not None:
            return self._parse_fallback_summary(battletag, data)

        return None

    async def get_player_stats(self, battletag: str) -> Optional[dict[str, Any]]:
        """
        Returns a normalized stats dict suitable for snapshot storage.
        Keys: battletag, games_played, games_won, eliminations, deaths,
              damage_dealt, healing_done, time_played_seconds,
              eliminations_per_10, deaths_per_10, damage_per_10, healing_per_10,
              win_percentage, competitive, _private
        """
        tag = battletag.replace("#", "-")

        # We need both summary (for comp rank) and stats/summary
        summary_task = self._get(f"{OVERFAST_API_BASE}/players/{tag}/summary")
        stats_task   = self._get(f"{OVERFAST_API_BASE}/players/{tag}/stats/summary")
        summary_raw, stats_raw = await asyncio.gather(summary_task, stats_task)

        if stats_raw is not None and not stats_raw.get("_private"):
            result = self._parse_overfast_stats(battletag, stats_raw)
            # Attach competitive info from summary
            if summary_raw and not summary_raw.get("_private"):
                summary_parsed = self._parse_overfast_summary(battletag, summary_raw)
                result["competitive"] = summary_parsed.get("competitive", {})
            return result

        if (stats_raw and stats_raw.get("_private")) or (
            summary_raw and summary_raw.get("_private")
        ):
            return {"_private": True, "battletag": battletag}

        # ---- fallback ----
        await asyncio.sleep(API_REQUEST_DELAY)
        data = await self._get(f"{OWAPI_FALLBACK_BASE}/stats/pc/{tag}")
        if data:
            return self._parse_fallback_stats(battletag, data)

        return None

    async def validate_battletag(self, battletag: str) -> tuple[bool, bool]:
        """Returns (player_exists, is_private)."""
        summary = await self.get_player_summary(battletag)
        if summary is None:
            return False, False
        if summary.get("_private"):
            return True, True
        return True, False

    # ------------------------------------------------------------- parsers
    def _parse_overfast_summary(self, battletag: str, data: dict) -> dict:
        if data.get("_private") or data.get("privacy") == "private":
            return {"_private": True, "battletag": battletag}

        comp_raw = data.get("competitive", {}) or {}
        # OverFast may nest under "pc"
        if "pc" in comp_raw:
            comp_raw = comp_raw["pc"] or {}

        competitive: dict[str, dict] = {}
        for role in ("tank", "damage", "support"):
            rd = comp_raw.get(role) or {}
            if rd.get("division"):
                competitive[role] = {
                    "division": rd.get("division", "Unranked"),
                    "tier":     rd.get("tier", 0),
                    "rank_icon": rd.get("rank_icon", ""),
                }

        return {
            "battletag":   battletag,
            "username":    data.get("username") or battletag.split("#")[0],
            "avatar":      data.get("avatar", ""),
            "endorsement": (data.get("endorsement") or {}).get("level", 0),
            "competitive": competitive,
            "_private":    False,
        }

    def _parse_overfast_stats(self, battletag: str, data: dict) -> dict:
        gen = data.get("general") or {}

        return {
            "battletag":            battletag,
            "games_played":         gen.get("games_played") or 0,
            "games_won":            gen.get("games_won") or 0,
            "eliminations":         int(gen.get("eliminations") or 0),
            "deaths":               int(gen.get("deaths") or 0),
            "damage_dealt":         int(gen.get("damage_dealt") or 0),
            "healing_done":         int(gen.get("healing_done") or 0),
            "time_played_seconds":  self._parse_time(gen.get("time_played", "0")),
            "eliminations_per_10":  float(gen.get("eliminations_avg_per_10min") or 0),
            "deaths_per_10":        float(gen.get("deaths_avg_per_10min") or 0),
            "damage_per_10":        float(gen.get("damage_avg_per_10min") or 0),
            "healing_per_10":       float(gen.get("healing_avg_per_10min") or 0),
            "win_percentage":       float(gen.get("win_percentage") or 0),
            "competitive":          {},   # filled by get_player_stats
            "_private":             False,
        }

    def _parse_fallback_summary(self, battletag: str, data: dict) -> dict:
        return {
            "battletag":   battletag,
            "username":    data.get("name") or battletag.split("#")[0],
            "avatar":      data.get("icon") or data.get("portrait", ""),
            "endorsement": data.get("endorsement", 0),
            "competitive": {},
            "_private":    bool(data.get("private")),
        }

    def _parse_fallback_stats(self, battletag: str, data: dict) -> dict:
        combat  = data.get("combat") or data.get("stats", {}).get("combat", {}) or {}
        assists = data.get("assists") or data.get("stats", {}).get("assists", {}) or {}
        game    = data.get("game") or data.get("stats", {}).get("game", {}) or {}

        return {
            "battletag":           battletag,
            "games_played":        game.get("gamesPlayed") or 0,
            "games_won":           game.get("gamesWon") or 0,
            "eliminations":        int(combat.get("eliminations") or 0),
            "deaths":              int(combat.get("deaths") or 0),
            "damage_dealt":        int(combat.get("damageDone") or 0),
            "healing_done":        int(assists.get("healingDone") or 0),
            "time_played_seconds": 0,
            "eliminations_per_10": 0.0,
            "deaths_per_10":       0.0,
            "damage_per_10":       0.0,
            "healing_per_10":      0.0,
            "win_percentage":      0.0,
            "competitive":         {},
            "_private":            False,
        }

    @staticmethod
    def _parse_time(value) -> int:
        """Convert 'H:MM:SS' / 'MM:SS' / int seconds to integer seconds."""
        if isinstance(value, (int, float)):
            return int(value)
        try:
            parts = str(value).split(":")
            if len(parts) == 3:
                return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])
            if len(parts) == 2:
                return int(parts[0]) * 60 + int(parts[1])
        except (ValueError, AttributeError):
            pass
        return 0
