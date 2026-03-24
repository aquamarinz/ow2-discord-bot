from __future__ import annotations
"""
/id — Save and share multiple Overwatch accounts.

Commands:
  /id add <battletag> [label]   — Add a BattleTag to your saved list
  /id list                      — Show all your saved accounts (private)
  /id share <battletag>         — Post a selected account publicly in the channel
  /id remove <battletag>        — Remove a saved account
"""
import logging
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from utils.embeds import build_id_list_embed, build_id_share_embed

logger = logging.getLogger(__name__)

_MAX_ACCOUNTS = 10  # per user per guild


class IdGroup(app_commands.Group):
    def __init__(self, bot: commands.Bot) -> None:
        super().__init__(name="id", description="保存并分享你的 Overwatch 账号 ID")
        self.bot = bot

    # ── /id add ──────────────────────────────────────────────────────────
    @app_commands.command(name="add", description="将一个 BattleTag 添加到你的保存列表")
    @app_commands.describe(
        battletag="Overwatch BattleTag，例如 PlayerName#1234",
        label="备注名称（可选），例如"备用号"、"练习号"",
    )
    async def id_add(
        self,
        interaction: discord.Interaction,
        battletag: str,
        label: Optional[str] = None,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        if "#" not in battletag:
            await interaction.followup.send(
                embed=_err("格式错误", "BattleTag 格式应为 `PlayerName#1234`。"),
                ephemeral=True,
            )
            return

        discord_id = str(interaction.user.id)
        guild_id   = str(interaction.guild_id)

        # Check account limit
        existing = await self.bot.db.get_accounts(discord_id, guild_id)
        if len(existing) >= _MAX_ACCOUNTS:
            await interaction.followup.send(
                embed=_err("已达上限", f"每人最多保存 {_MAX_ACCOUNTS} 个账号。\n请先用 `/id remove` 删除不需要的账号。"),
                ephemeral=True,
            )
            return

        # Validate the BattleTag
        exists, _ = await self.bot.api.validate_battletag(battletag)
        if not exists:
            await interaction.followup.send(
                embed=_err("找不到玩家", f"无法找到 BattleTag `{battletag}`，请确认拼写是否正确。"),
                ephemeral=True,
            )
            return

        await self.bot.db.add_account(discord_id, guild_id, battletag, label)
        label_txt = f"（备注：{label}）" if label else ""
        await interaction.followup.send(
            embed=discord.Embed(
                title="✅ 已添加",
                description=f"`{battletag}` {label_txt} 已保存到你的账号列表。\n使用 `/id share` 可在频道里公开分享。",
                color=0x44FF88,
            ),
            ephemeral=True,
        )

    # ── /id list ─────────────────────────────────────────────────────────
    @app_commands.command(name="list", description="查看你保存的所有 Overwatch 账号（仅自己可见）")
    async def id_list(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)

        discord_id = str(interaction.user.id)
        guild_id   = str(interaction.guild_id)
        accounts   = await self.bot.db.get_accounts(discord_id, guild_id)
        primary    = await self.bot.db.get_player(discord_id, guild_id)
        primary_tag = primary["battletag"] if primary else None

        await interaction.followup.send(
            embed=build_id_list_embed(interaction.user, accounts, primary_tag),
            ephemeral=True,
        )

    # ── /id share ────────────────────────────────────────────────────────
    @app_commands.command(name="share", description="在频道里公开分享你的某个 Overwatch 账号")
    @app_commands.describe(battletag="要分享的 BattleTag（从你的保存列表中选择）")
    async def id_share(
        self,
        interaction: discord.Interaction,
        battletag: str,
    ) -> None:
        await interaction.response.defer()

        discord_id = str(interaction.user.id)
        guild_id   = str(interaction.guild_id)
        accounts   = await self.bot.db.get_accounts(discord_id, guild_id)

        # Find the matching account (case-insensitive)
        matched = next(
            (a for a in accounts if a["battletag"].lower() == battletag.lower()),
            None,
        )
        if not matched:
            await interaction.followup.send(
                embed=_err(
                    "账号不在列表中",
                    f"`{battletag}` 不在你的保存列表中。\n先用 `/id add` 添加，或用 `/id list` 查看已保存的账号。",
                ),
                ephemeral=True,
            )
            return

        # Fetch live rank data to show in the share embed
        summary = None
        try:
            summary = await self.bot.api.get_player_summary(matched["battletag"])
            if summary and summary.get("_private"):
                summary = None
        except Exception as exc:
            logger.warning("id share summary fetch failed for %s: %s", matched["battletag"], exc)

        await interaction.followup.send(
            embed=build_id_share_embed(
                interaction.user,
                matched["battletag"],
                matched.get("label"),
                summary,
            )
        )

    @id_share.autocomplete("battletag")
    async def _share_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        discord_id = str(interaction.user.id)
        guild_id   = str(interaction.guild_id)
        accounts   = await self.bot.db.get_accounts(discord_id, guild_id)
        choices = []
        for acc in accounts:
            tag   = acc["battletag"]
            label = acc.get("label") or ""
            name  = f"{tag}  {label}".strip() if label else tag
            if current.lower() in tag.lower() or current.lower() in label.lower():
                choices.append(app_commands.Choice(name=name[:100], value=tag))
        return choices[:25]

    # ── /id remove ───────────────────────────────────────────────────────
    @app_commands.command(name="remove", description="从你的保存列表中移除一个账号")
    @app_commands.describe(battletag="要移除的 BattleTag")
    async def id_remove(
        self,
        interaction: discord.Interaction,
        battletag: str,
    ) -> None:
        await interaction.response.defer(ephemeral=True)

        discord_id = str(interaction.user.id)
        guild_id   = str(interaction.guild_id)
        removed    = await self.bot.db.remove_account(discord_id, guild_id, battletag)

        if removed:
            await interaction.followup.send(
                embed=discord.Embed(
                    title="✅ 已移除",
                    description=f"`{battletag}` 已从你的列表中删除。",
                    color=0x44FF88,
                ),
                ephemeral=True,
            )
        else:
            await interaction.followup.send(
                embed=_err("未找到", f"`{battletag}` 不在你的保存列表中。"),
                ephemeral=True,
            )

    @id_remove.autocomplete("battletag")
    async def _remove_autocomplete(
        self,
        interaction: discord.Interaction,
        current: str,
    ) -> list[app_commands.Choice[str]]:
        return await self._share_autocomplete(interaction, current)


class IdentityCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot   = bot
        self._grp  = IdGroup(bot)
        bot.tree.add_command(self._grp)

    async def cog_unload(self) -> None:
        self.bot.tree.remove_command("id")


def _err(title: str, desc: str) -> discord.Embed:
    return discord.Embed(title=f"❌ {title}", description=desc, color=0xFF4444)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(IdentityCog(bot))
