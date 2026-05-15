"""Twitch account linking cog — /twitch link and /twitch unlink."""
from __future__ import annotations
import logging

import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger(__name__)


class TwitchLinkCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    twitch = app_commands.Group(
        name="twitch",
        description="绑定 Twitch 账号（用于 /miner 查询）",
        guild_only=True,
    )

    @twitch.command(name="link", description="绑定你的 Twitch 用户名")
    @app_commands.describe(username="你的 Twitch 用户名（3-25 位字母/数字/下划线）")
    async def link(self, interaction: discord.Interaction, username: str) -> None:
        # Defer FIRST (always within 3s window). Then do I/O. Use followup to reply.
        # Prevents discord.errors.HTTPException 40060 "Interaction has already been
        # acknowledged" from any race / latency between cmd dispatch and our response.
        await interaction.response.defer(ephemeral=True, thinking=True)
        try:
            # database.link_twitch internally normalizes (strip+lower) and validates regex
            await self.bot.db.link_twitch(
                str(interaction.user.id),
                str(interaction.guild_id),
                username,
            )
        except ValueError as e:
            logger.info("Twitch link rejected: %s", e)
            await interaction.followup.send(
                "❌ Twitch 用户名格式不对（3-25 位字母/数字/下划线，会自动 lowercase）",
                ephemeral=True,
            )
            return

        canonical = username.strip().lower()
        embed = discord.Embed(
            title="✅ Twitch 账号已绑定",
            description=f"已绑定到 **{canonical}**",
            color=0x9146FF,  # Twitch purple
        )
        embed.set_footer(text="跑 /miner 查看挂机进度")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @twitch.command(name="unlink", description="解绑 Twitch 账号")
    async def unlink(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True, thinking=True)
        deleted = await self.bot.db.unlink_twitch(
            str(interaction.user.id),
            str(interaction.guild_id),
        )
        if deleted:
            await interaction.followup.send(
                "🔓 已解绑 Twitch 账号。",
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                "你本来就没绑定 Twitch 账号。",
                ephemeral=True,
            )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TwitchLinkCog(bot))
