from __future__ import annotations
"""
/match start   — snapshot all registered players' stats before a game
/match analyze — diff post-game stats against the snapshot, generate war report
/match cancel  — discard the active session
"""
import asyncio
import logging
import uuid
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from utils.embeds import build_match_analysis_embed
from utils.scoring import assign_titles, compute_scores, infer_role

logger = logging.getLogger(__name__)


class MatchGroup(app_commands.Group):
    def __init__(self, bot: commands.Bot) -> None:
        super().__init__(name="match", description="对局分析：战神 · 战犯 · 唐")
        self.bot = bot

    # ------------------------------------------------------------ /match start
    @app_commands.command(name="start", description="开始对局记录——在进入游戏前使用")
    async def match_start(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()

        guild_id = str(interaction.guild_id)

        # Guard: only one active session per guild
        existing = await self.bot.db.get_active_session(guild_id)
        if existing:
            await interaction.followup.send(
                embed=discord.Embed(
                    title="⚠️ 已有进行中的对局",
                    description=(
                        "服务器已有一个进行中的对局记录。\n"
                        "使用 `/match analyze` 完成当前对局，或 `/match cancel` 放弃。"
                    ),
                    color=0xFFAA00,
                )
            )
            return

        players = await self.bot.db.get_all_players(guild_id)
        if not players:
            await interaction.followup.send(
                embed=discord.Embed(
                    title="❌ 无已注册玩家",
                    description="服务器暂无成员注册 Overwatch 账号。",
                    color=0xFF4444,
                )
            )
            return

        session_id = str(uuid.uuid4())[:8].upper()
        await self.bot.db.create_match_session(session_id, guild_id, str(interaction.user.id))

        # Notify and start snapshotting
        await interaction.followup.send(
            embed=discord.Embed(
                title="⏳ 正在记录赛前数据…",
                description=f"正在为 **{len(players)}** 名玩家记录赛前快照，请稍等。",
                color=0x4488FF,
            )
        )

        ok_count: int = 0
        failed: list[str] = []
        for p in players:
            try:
                stats = await self.bot.api.get_player_stats(p["battletag"])
                if stats and not stats.get("_private"):
                    await self.bot.db.save_snapshot(
                        p["discord_id"], guild_id, stats,
                        snapshot_type="match_start", session_id=session_id,
                    )
                    ok_count += 1
                else:
                    failed.append(p["battletag"])
            except Exception as exc:
                logger.error("Snapshot failed for %s: %s", p["battletag"], exc)
                failed.append(p["battletag"])
            await asyncio.sleep(0.5)

        embed = discord.Embed(
            title="⚔️ 对局记录已开始",
            description=(
                f"**场次 ID:** `{session_id}`\n"
                f"已为 **{ok_count}** 名玩家记录赛前数据。\n\n"
                "去打一场吧！结束后使用 `/match analyze` 查看战报。"
            ),
            color=0x44FF88,
        )
        if failed:
            embed.add_field(
                name="⚠️ 以下玩家未能记录（主页可能设为私密）",
                value="\n".join(f"• `{bt}`" for bt in failed),
                inline=False,
            )
        await interaction.edit_original_response(embed=embed)

    # ---------------------------------------------------------- /match analyze
    @app_commands.command(name="analyze", description="分析刚结束的对局，评出战神和战犯")
    async def match_analyze(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer()

        guild_id = str(interaction.guild_id)
        session  = await self.bot.db.get_active_session(guild_id)
        if not session:
            await interaction.followup.send(
                embed=discord.Embed(
                    title="❌ 无进行中的对局",
                    description="请先使用 `/match start` 开始记录对局。",
                    color=0xFF4444,
                )
            )
            return

        session_id = session["session_id"]
        players    = await self.bot.db.get_all_players(guild_id)

        await interaction.followup.send(
            embed=discord.Embed(
                title="⏳ 正在分析战报…",
                description="正在获取赛后数据，请稍等。",
                color=0x4488FF,
            )
        )

        deltas: list[dict] = []
        for p in players:
            try:
                pre = await self.bot.db.get_session_snapshot(
                    p["discord_id"], guild_id, session_id
                )
                if not pre:
                    continue

                cur = await self.bot.api.get_player_stats(p["battletag"])
                if not cur or cur.get("_private"):
                    continue

                # Save post-game snapshot for records
                await self.bot.db.save_snapshot(
                    p["discord_id"], guild_id, cur,
                    snapshot_type="match_end", session_id=session_id,
                )

                delta = {
                    "discord_id":  p["discord_id"],
                    "battletag":   p["battletag"],
                    "eliminations": _pos_delta(cur, pre, "eliminations"),
                    "deaths":       _pos_delta(cur, pre, "deaths"),
                    "damage_dealt": _pos_delta(cur, pre, "damage_dealt"),
                    "healing_done": _pos_delta(cur, pre, "healing_done"),
                    "games_played": _pos_delta(cur, pre, "games_played"),
                    "games_won":    _pos_delta(cur, pre, "games_won"),
                }
                delta["inferred_role"] = infer_role(delta)
                deltas.append(delta)
            except Exception as exc:
                logger.error("Analysis error for %s: %s", p["battletag"], exc)
            await asyncio.sleep(0.5)

        await self.bot.db.close_session(session_id)

        if len(deltas) < 2:
            await interaction.edit_original_response(
                embed=discord.Embed(
                    title="⚠️ 数据不足",
                    description=(
                        "没有足够玩家数据来生成报告。\n"
                        "可能原因：玩家未参与对局、主页设为私密，或 API 暂时不可用。"
                    ),
                    color=0xFFAA00,
                )
            )
            return

        # Attach display names
        guild = interaction.guild
        for d in deltas:
            m = guild.get_member(int(d["discord_id"]))
            d["display_name"] = m.display_name if m else d["battletag"].split("#")[0]

        titled = assign_titles(compute_scores(deltas))
        await interaction.edit_original_response(
            embed=build_match_analysis_embed(titled, session_id)
        )

    # ----------------------------------------------------------- /match cancel
    @app_commands.command(name="cancel", description="取消当前进行中的对局记录")
    async def match_cancel(self, interaction: discord.Interaction) -> None:
        await interaction.response.defer(ephemeral=True)

        guild_id = str(interaction.guild_id)
        session  = await self.bot.db.get_active_session(guild_id)
        if not session:
            await interaction.followup.send(
                embed=discord.Embed(
                    title="❌ 无进行中的对局",
                    description="当前没有进行中的对局记录。",
                    color=0xFF4444,
                ),
                ephemeral=True,
            )
            return

        await self.bot.db.close_session(session["session_id"])
        await interaction.followup.send(
            embed=discord.Embed(
                title="✅ 对局记录已取消",
                description=f"场次 `{session['session_id']}` 已取消。",
                color=0x888888,
            ),
            ephemeral=True,
        )


def _pos_delta(cur: dict, pre: dict, key: str) -> int:
    """Compute max(0, cur[key] - pre[key]), treating missing values as 0."""
    return max(0, (cur.get(key) or 0) - (pre.get(key) or 0))


class AnalysisCog(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot  = bot
        self._grp = MatchGroup(bot)
        bot.tree.add_command(self._grp)

    async def cog_unload(self) -> None:
        self.bot.tree.remove_command("match")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AnalysisCog(bot))
