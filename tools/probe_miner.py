"""One-shot probe: connect to rangermix miner via socket.io, dump events.

Usage:
    python tools/probe_miner.py <miner_host:port>
    # e.g.
    python tools/probe_miner.py localhost:8080
    python tools/probe_miner.py 192.168.50.170:8080

This script is for spec/plan-time discovery, not runtime use. Output goes to
stdout; capture with `tee` if you want to keep it.

Listens for 60 seconds. To surface more events, manually toggle miner state
(e.g., add/remove a game in the Web UI) while it's running.
"""
from __future__ import annotations
import asyncio
import sys
from datetime import datetime

import socketio


async def main(host: str) -> None:
    url = f"http://{host}"
    sio = socketio.AsyncClient(logger=False, engineio_logger=False)
    seen_events: set[str] = set()

    @sio.on("*")
    async def catch_all(event: str, *args):
        ts = datetime.now().isoformat(timespec="seconds")
        seen_events.add(event)
        payload_preview = repr(args)[:500]
        print(f"[{ts}] event={event!r} args={payload_preview}")
        print(f"  (arg types: {[type(a).__name__ for a in args]})")
        print()

    @sio.event
    async def connect():
        print(f"[connect] socket opened, sid={sio.sid}")

    @sio.event
    async def disconnect():
        print("[disconnect] socket closed")

    @sio.event
    async def connect_error(data):
        print(f"[connect_error] {data}")

    print(f"Connecting to {url} ...")
    try:
        await sio.connect(url, transports=["websocket", "polling"])
    except Exception as e:
        print(f"[fatal] connect failed: {e}")
        print(
            f"\nIf this errors with CORS / Origin, try adding "
            f"`headers={{'Origin': '{url}'}}` in sio.connect()."
        )
        await sio.disconnect()
        sys.exit(1)

    print("\nListening for 60 seconds. Trigger miner state changes via Web UI to surface more events.\n")
    await asyncio.sleep(60)
    await sio.disconnect()

    print("\n=== Summary ===")
    print(f"Unique events seen: {sorted(seen_events)}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python tools/probe_miner.py <host:port>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
