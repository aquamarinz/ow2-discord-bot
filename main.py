from __future__ import annotations
import asyncio
import logging
import os

import discord
from discord.ext import commands, tasks
from dotenv import load_dotenv

from api.client import OWAPIClient
from config import SNAPSHOT_INTERVAL_MINUTES
from database import Database

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

_COGS = [
    "cogs.registration",
    "cogs.stats",
    "cogs.leaderboard",
    "cogs.analysis",
    "cogs.trends",
    "cogs.compare",
    "cogs.history",
    "cogs.streak",
    "cogs.server_stats",
    "cogs.goals",
    "cogs.lookup",
    "cogs.stadium",
]


class OWBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.members = True
        super().__init__(command_prefix="!", intents=intents)

        self.db: Database      = Database()
        self.api: OWAPIClient  = OWAPIClient()

    # --------------------------------------------------------- lifecycle
    async def setup_hook(self) -> None:
        await self.db.initialize()

        for cog in _COGS:
            await self.load_extension(cog)
            logger.info("Loaded cog: %s", cog)

        await self.tree.sync()
        logger.info("Slash commands synced globally")

        self._snapshot_task.start()

    async def close(self) -> None:
        self._snapshot_task.cancel()
        await self.api.close()
        await super().close()

    async def on_ready(self) -> None:
        logger.info("Logged in as %s (ID: %s)", self.user, self.user.id)
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="Overwatch 2 战场",
            )
        )

    async def on_app_command_error(
        self,
        interaction: discord.Interaction,
        error: discord.app_commands.AppCommandError,
    ) -> None:
        logger.error("Slash command error: %s", error, exc_info=error)
        msg = "命令执行时发生未知错误，请稍后重试。"

        embed = discord.Embed(title="❌ 命令出错", description=msg, color=0xFF4444)
        try:
            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception:
            pass

    # ------------------------------------------- periodic snapshot task
    @tasks.loop(minutes=SNAPSHOT_INTERVAL_MINUTES)
    async def _snapshot_task(self) -> None:
        logger.info("Periodic snapshot run starting…")
        players = await self.db.get_all_players()

        for player in players:
            try:
                stats = await self.api.get_player_stats(player["battletag"])
                if stats and not stats.get("_private"):
                    await self.db.save_snapshot(
                        player["discord_id"], player["guild_id"], stats
                    )
                    await self.db.cleanup_old_snapshots(
                        player["discord_id"], player["guild_id"]
                    )
            except Exception as exc:
                logger.warning("Snapshot failed for %s: %s", player["battletag"], exc)

            # Polite rate-limiting between players
            await asyncio.sleep(1.0)

        logger.info("Periodic snapshot run complete (%d players)", len(players))

    @_snapshot_task.before_loop
    async def _before_snapshot(self) -> None:
        await self.wait_until_ready()


def main() -> None:
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("DISCORD_TOKEN environment variable is not set.")

    bot = OWBot()
    bot.run(token, log_handler=None)  # We handle logging above


if __name__ == "__main__":
    main()
