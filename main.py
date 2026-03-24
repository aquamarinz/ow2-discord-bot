from __future__ import annotations
import logging
import os

import discord
from discord.ext import commands
from dotenv import load_dotenv

from api.client import OWAPIClient
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
    "cogs.stadium",
    "cogs.identity",
]


class OWBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.members = True
        super().__init__(command_prefix=commands.when_mentioned, intents=intents)
        self.db: Database     = Database()
        self.api: OWAPIClient = OWAPIClient()

    async def setup_hook(self) -> None:
        await self.db.initialize()

        for cog in _COGS:
            await self.load_extension(cog)
            logger.info("Loaded cog: %s", cog)

        await self.tree.sync()
        logger.info("Slash commands synced globally")

    async def close(self) -> None:
        await self.api.close()
        await self.db.close()
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
        embed = discord.Embed(
            title="❌ 命令出错",
            description="命令执行时发生错误，请稍后重试。",
            color=0xFF4444,
        )
        try:
            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception:
            pass


def main() -> None:
    token = os.getenv("DISCORD_TOKEN")
    if not token:
        raise RuntimeError("DISCORD_TOKEN environment variable is not set.")
    OWBot().run(token, log_handler=None)


if __name__ == "__main__":
    main()
