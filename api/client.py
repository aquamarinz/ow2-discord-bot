from __future__ import annotations
"""
OW2 API client – OverFast API primary, owapi.eu fallback.

Public methods return None on hard failure and a dict with '_private': True
when the player's profile is set to private.
"""
import asyncio
import logging
from typing import Any, Optional

import aiohttp

from config import API_REQUEST_DELAY, OVERFAST_API_BASE, OWAPI_FALLBACK_BASE

logger = logging.getLogger(__name__)

_TIMEOUT = aiohttp.ClientTimeout(total=12)
_HEADERS = {"User-Agent": "OW2-Discord-Bot/2.0 (github.com/aquamarinz/ow2-discord-bot)"}


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
        """Normalized summary: battletag, username, avatar, endorsement, competitive, title."""
        tag = battletag.replace("#", "-")
        data = await self._get(f"{OVERFAST_API_BASE}/players/{tag}/summary")
        if data is not None:
            return self._parse_overfast_summary(battletag, data)

        await asyncio.sleep(API_REQUEST_DELAY)
        data = await self._get(f"{OWAPI_FALLBACK_BASE}/profile/pc/{tag}")
        if data is not None:
            return self._parse_fallback_summary(battletag, data)
        return None

    async def get_player_stats(
        self, battletag: str, gamemode: str = "competitive"
    ) -> Optional[dict[str, Any]]:
        """
        Full player stats combining summary + stats/summary + stats/career.

        Returns a rich dict with keys:
          battletag, competitive, general, roles, top_heroes, career, _private
        """
        tag = battletag.replace("#", "-")
        base = f"{OVERFAST_API_BASE}/players/{tag}"

        # "all" = no gamemode filter (combined stats)
        gm_param = f"?gamemode={gamemode}" if gamemode != "all" else ""

        # Fetch endpoints in parallel
        summary_task = self._get(f"{base}/summary")
        stats_task = self._get(f"{base}/stats/summary{gm_param}")
        # /stats/career requires a gamemode param; skip for "all" mode
        if gamemode != "all":
            career_task = self._get(f"{base}/stats/career?gamemode={gamemode}")
            summary_raw, stats_raw, career_raw = await asyncio.gather(
                summary_task, stats_task, career_task
            )
        else:
            summary_raw, stats_raw = await asyncio.gather(summary_task, stats_task)
            career_raw = None

        # Check for private profile
        for raw in (summary_raw, stats_raw, career_raw):
            if raw and raw.get("_private"):
                return {"_private": True, "battletag": battletag}

        if stats_raw is None and career_raw is None:
            # Total API failure – try fallback for basic stats
            await asyncio.sleep(API_REQUEST_DELAY)
            data = await self._get(f"{OWAPI_FALLBACK_BASE}/stats/pc/{tag}")
            if data:
                return self._parse_fallback_stats(battletag, data)
            return None

        result: dict[str, Any] = {
            "battletag": battletag,
            "gamemode": gamemode,
            "_private": False,
        }

        # -- summary (rank, avatar, endorsement) --
        if summary_raw and not summary_raw.get("_private"):
            parsed_summary = self._parse_overfast_summary(battletag, summary_raw)
            result["competitive"] = parsed_summary.get("competitive", {})
            result["username"] = parsed_summary.get("username", "")
            result["avatar"] = parsed_summary.get("avatar", "")
            result["endorsement"] = parsed_summary.get("endorsement", 0)
            result["title"] = parsed_summary.get("title", "")
        else:
            result["competitive"] = {}
            result["username"] = battletag.split("#")[0]
            result["avatar"] = ""
            result["endorsement"] = 0
            result["title"] = ""

        # -- stats/summary (general + roles + top heroes) --
        if stats_raw:
            result["general"] = self._parse_stats_general(stats_raw)
            result["roles"] = self._parse_stats_roles(stats_raw)
            result["top_heroes"] = self._parse_top_heroes(stats_raw, limit=3)
        else:
            result["general"] = {}
            result["roles"] = {}
            result["top_heroes"] = []

        # -- stats/career (per-10-min, best records, hero-specific) --
        if career_raw:
            result["career"] = self._parse_career(career_raw)
        else:
            result["career"] = {}

        return result

    async def validate_battletag(self, battletag: str) -> tuple[bool, bool]:
        """Returns (player_exists, is_private)."""
        summary = await self.get_player_summary(battletag)
        if summary is None:
            return False, False
        if summary.get("_private"):
            return True, True
        return True, False

    # ------------------------------------------------------------- parsers: summary
    def _parse_overfast_summary(self, battletag: str, data: dict) -> dict:
        if data.get("_private") or data.get("privacy") == "private":
            return {"_private": True, "battletag": battletag}

        comp_raw = data.get("competitive", {}) or {}
        if "pc" in comp_raw:
            comp_raw = comp_raw["pc"] or {}

        competitive: dict[str, dict] = {}
        for role in ("tank", "damage", "support"):
            rd = comp_raw.get(role) or {}
            if rd.get("division"):
                competitive[role] = {
                    "division": rd.get("division", "Unranked"),
                    "tier": rd.get("tier", 0),
                    "rank_icon": rd.get("rank_icon", ""),
                }

        return {
            "battletag": battletag,
            "username": data.get("username") or battletag.split("#")[0],
            "avatar": data.get("avatar", ""),
            "title": data.get("title", ""),
            "endorsement": (data.get("endorsement") or {}).get("level", 0),
            "competitive": competitive,
            "_private": False,
        }

    # -------------------------------------------------------- parsers: stats/summary
    @staticmethod
    def _parse_stats_general(data: dict) -> dict:
        """Parse the 'general' section from /stats/summary."""
        gen = data.get("general") or {}
        total = gen.get("total") or {}
        avg = gen.get("average") or {}
        return {
            "games_played": gen.get("games_played", 0),
            "games_won": gen.get("games_won", 0),
            "games_lost": gen.get("games_lost", 0),
            "time_played": gen.get("time_played", 0),  # seconds
            "winrate": gen.get("winrate", 0),
            "kda": gen.get("kda", 0),
            "total_eliminations": total.get("eliminations", 0),
            "total_assists": total.get("assists", 0),
            "total_deaths": total.get("deaths", 0),
            "total_damage": total.get("damage", 0),
            "total_healing": total.get("healing", 0),
            "avg_eliminations": avg.get("eliminations", 0),
            "avg_assists": avg.get("assists", 0),
            "avg_deaths": avg.get("deaths", 0),
            "avg_damage": avg.get("damage", 0),
            "avg_healing": avg.get("healing", 0),
        }

    @staticmethod
    def _parse_stats_roles(data: dict) -> dict:
        """Parse the 'roles' section from /stats/summary."""
        roles_raw = data.get("roles") or {}
        roles = {}
        for role_name, rd in roles_raw.items():
            if not rd:
                continue
            total = rd.get("total") or {}
            avg = rd.get("average") or {}
            roles[role_name] = {
                "games_played": rd.get("games_played", 0),
                "games_won": rd.get("games_won", 0),
                "time_played": rd.get("time_played", 0),
                "winrate": rd.get("winrate", 0),
                "kda": rd.get("kda", 0),
                "avg_damage": avg.get("damage", 0),
                "avg_healing": avg.get("healing", 0),
                "avg_eliminations": avg.get("eliminations", 0),
                "avg_deaths": avg.get("deaths", 0),
            }
        return roles

    @staticmethod
    def _parse_top_heroes(data: dict, limit: int = 3) -> list[dict]:
        """Extract top heroes by time played from /stats/summary."""
        heroes_raw = data.get("heroes") or {}
        hero_list = []
        for name, hd in heroes_raw.items():
            if not hd:
                continue
            total = hd.get("total") or {}
            avg = hd.get("average") or {}
            hero_list.append({
                "name": name,
                "games_played": hd.get("games_played", 0),
                "games_won": hd.get("games_won", 0),
                "time_played": hd.get("time_played", 0),
                "winrate": hd.get("winrate", 0),
                "kda": hd.get("kda", 0),
                "avg_damage": avg.get("damage", 0),
                "avg_healing": avg.get("healing", 0),
                "avg_eliminations": avg.get("eliminations", 0),
            })
        hero_list.sort(key=lambda h: h["time_played"], reverse=True)
        return hero_list[:limit]

    # --------------------------------------------------------- parsers: stats/career
    @staticmethod
    def _parse_career(data: dict) -> dict:
        """Parse /stats/career for per-10-min averages, best records, weapon accuracy."""
        # "all-heroes" has aggregate career stats
        all_heroes = data.get("all-heroes") or {}
        avg = all_heroes.get("average") or {}
        best = all_heroes.get("best") or {}
        combat = all_heroes.get("combat") or {}
        game = all_heroes.get("game") or {}

        return {
            # Per-10-min averages
            "eliminations_per_10": avg.get("eliminations_avg_per_10_min", 0),
            "deaths_per_10": avg.get("deaths_avg_per_10_min", 0),
            "hero_damage_per_10": avg.get("hero_damage_done_avg_per_10_min", 0),
            "all_damage_per_10": avg.get("all_damage_done_avg_per_10_min", 0),
            "healing_per_10": avg.get("healing_done_avg_per_10_min", 0),
            "final_blows_per_10": avg.get("final_blows_avg_per_10_min", 0),
            "assists_per_10": avg.get("assists_avg_per_10_min", 0),
            "objective_kills_per_10": avg.get("objective_kills_avg_per_10_min", 0),
            # Best records
            "elim_best_game": best.get("eliminations_most_in_game", 0),
            "damage_best_game": best.get("all_damage_done_most_in_game", 0),
            "healing_best_game": best.get("healing_done_most_in_game", 0),
            "kill_streak_best": best.get("kill_streak_best", 0),
            "multikill_best": best.get("multikill_best", 0),
            # Combat totals
            "weapon_accuracy": combat.get("weapon_accuracy", 0),
            "critical_hit_accuracy": combat.get("critical_hit_accuracy", 0),
            "melee_final_blows": combat.get("melee_final_blows", 0),
            "solo_kills": combat.get("solo_kills", 0),
            # Game
            "time_played": game.get("time_played", 0),
            "games_played": game.get("games_played", 0),
            "games_won": game.get("games_won", 0),
            "win_percentage": game.get("win_percentage", 0),
        }

    # --------------------------------------------------------- parsers: fallback
    def _parse_fallback_summary(self, battletag: str, data: dict) -> dict:
        return {
            "battletag": battletag,
            "username": data.get("name") or battletag.split("#")[0],
            "avatar": data.get("icon") or data.get("portrait", ""),
            "title": "",
            "endorsement": data.get("endorsement", 0),
            "competitive": {},
            "_private": bool(data.get("private")),
        }

    def _parse_fallback_stats(self, battletag: str, data: dict) -> dict:
        combat = data.get("combat") or data.get("stats", {}).get("combat", {}) or {}
        game = data.get("game") or data.get("stats", {}).get("game", {}) or {}

        return {
            "battletag": battletag,
            "gamemode": "unknown",
            "_private": False,
            "competitive": {},
            "username": battletag.split("#")[0],
            "avatar": "",
            "endorsement": 0,
            "title": "",
            "general": {
                "games_played": game.get("gamesPlayed", 0),
                "games_won": game.get("gamesWon", 0),
                "games_lost": 0,
                "time_played": 0,
                "winrate": 0,
                "kda": 0,
                "total_eliminations": int(combat.get("eliminations") or 0),
                "total_deaths": int(combat.get("deaths") or 0),
                "total_damage": int(combat.get("damageDone") or 0),
                "total_healing": 0,
                "total_assists": 0,
                "avg_eliminations": 0,
                "avg_deaths": 0,
                "avg_damage": 0,
                "avg_healing": 0,
                "avg_assists": 0,
            },
            "roles": {},
            "top_heroes": [],
            "career": {},
        }
