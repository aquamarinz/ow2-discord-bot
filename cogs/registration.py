from __future__ import annotations
import logging

import discord
from discord import app_commands
from discord.ext import commands

logger = logging.getLogger(__name__)

_PRIVATE_HELP = (
    "你的 Overwatch 主页目前设为**私密**，Bot 无法读取数据。\n\n"
    "**如何改为公开：**\n"
    "1. 打开 Overwatch 2 客户端\n"
    "2. 点击右上角头像 → **选项**\n"
    "3. 在**社交**标签下，将**生涯档案**设为**公开**\n"
    "4. 修改后等约 5 分钟再重新运行此命令"
)


class RegistrationCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="register", description="将你的 Overwatch BattleTag 绑定到 Discord 账号")
    @app_commands.describe(battletag="你的 BattleTag，例如: PlayerName#1234")
    @app_commands.guild_only()
    async def register(self, interaction: discord.Interaction, battletag: str) -> None:
        await interaction.response.defer(ephemeral=True)

        if "#" not in battletag:
            await interaction.followup.send(
                embed=_err("格式错误", "BattleTag 格式应为 `PlayerName#1234`，请检查后重试。"),
                ephemeral=True,
            )
            return

        exists, is_private = await self.bot.api.validate_battletag(battletag)
        if not exists:
            await interaction.followup.send(
                embed=_err("找不到玩家", f"无法找到 BattleTag `{battletag}`，请确认拼写正确。"),
                ephemeral=True,
            )
            return
        if is_private:
            await interaction.followup.send(
                embed=discord.Embed(
                    title="⚠️ 主页设为私密",
                    description=_PRIVATE_HELP,
                    color=0xFFAA00,
                ),
                ephemeral=True,
            )
            return

        discord_id = str(interaction.user.id)
        guild_id   = str(interaction.guild_id)

        await self.bot.db.register_player(discord_id, guild_id, battletag)
        # Also save to accounts list so it shows up in /id list
        await self.bot.db.add_account(discord_id, guild_id, battletag, label="主账号")

        embed = discord.Embed(
            title="✅ 注册成功",
            description=f"已将 `{battletag}` 绑定为你的主账号。",
            color=0x44FF88,
        )
        embed.add_field(name="📊 查看数据",  value="`/stats`",       inline=True)
        embed.add_field(name="🏆 排行榜",    value="`/leaderboard`", inline=True)
        embed.add_field(name="🎮 管理账号",  value="`/id list`",     inline=True)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="unregister", description="解除 Overwatch BattleTag 与 Discord 账号的绑定")
    @app_commands.guild_only()
    async def unregister(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)

        discord_id = str(interaction.user.id)
        guild_id   = str(interaction.guild_id)
        player     = await self.bot.db.get_player(discord_id, guild_id)

        if not player:
            await interaction.followup.send(
                embed=_err("未注册", "你还没有绑定 Overwatch 账号。"), ephemeral=True
            )
            return

        await self.bot.db.unregister_player(discord_id, guild_id)
        await interaction.followup.send(
            embed=discord.Embed(
                title="✅ 已解除绑定",
                description=f"已移除主账号 `{player['battletag']}` 的绑定。\n保存的其他 ID 仍可通过 `/id list` 查看。",
                color=0x888888,
            ),
            ephemeral=True,
        )


def _err(title: str, desc: str) -> discord.Embed:
    return discord.Embed(title=f"❌ {title}", description=desc, color=0xFF4444)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(RegistrationCog(bot))
