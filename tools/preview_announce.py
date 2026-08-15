"""One-shot visual preview: post a sample campaign-launch announce.

Renders a REAL /api/campaigns snapshot through the production code path
(diff_tick → build_campaign_announce) and posts once to a channel, so the
2x2 gallery / thumbnail / drop list can be eyeballed before merging.

Usage (on the Pi — DISCORD_TOKEN lives in the container env):
  cd ~/services/discord-bot
  docker compose run --rm --entrypoint python discord-bot \
      -m tools.preview_announce /app/snapshot.json <channel_id> [name-filter]

snapshot.json: raw /api/campaigns JSON (e.g. curl from a miner).
name-filter:   optional substring to pick a campaign by name.
"""
from __future__ import annotations
import asyncio
import json
import os
import sys

import discord

from cogs.miner import build_campaign_announce, diff_tick


def pick_event(payload: dict, name_filter: str | None) -> dict:
    # Empty prior state (NOT None: None is the silent baseline) makes every
    # active campaign with progress emit an event through the real code path.
    result = diff_tick({"drops": {}, "mining": set()}, payload)
    if result is None:
        sys.exit("snapshot is not a valid /api/campaigns payload")
    _, _, events = result
    if name_filter:
        events = [e for e in events if name_filter.lower() in e["campaign"].lower()]
    if not events:
        sys.exit("no active campaign with progress matched; try another snapshot/filter")
    return events[0]


async def main() -> None:
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    with open(sys.argv[1], encoding="utf-8") as f:
        payload = json.load(f)
    channel_id = int(sys.argv[2])
    event = pick_event(payload, sys.argv[3] if len(sys.argv) > 3 else None)
    content, embeds = build_campaign_announce(["preview"], event)
    # strip the fake mention; keep the rest of the real content
    content = content.split("⛏️", 1)[1]
    content = "⛏️" + content + "\n_(preview_announce.py 样例,非真实事件)_"

    intents = discord.Intents.none()
    client = discord.Client(intents=intents)
    state = {"ok": False}

    @client.event
    async def on_ready() -> None:
        try:
            channel = await client.fetch_channel(channel_id)
            await channel.send(content=content, embeds=embeds)
            print(f"sent to #{channel} OK")
            state["ok"] = True
        finally:
            await client.close()

    await client.start(os.environ["DISCORD_TOKEN"])
    if not state["ok"]:
        sys.exit("send FAILED (see traceback above)")


if __name__ == "__main__":
    asyncio.run(main())
