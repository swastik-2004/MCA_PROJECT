"""
Crash one simulation worker of a running agent team (fault-tolerance demo).

Run this in a SECOND terminal while `python run_team.py ...` is running:

    python kill_worker.py          # kills a busy worker
    python kill_worker.py 3        # kills worker W3

The master notices the dead process, re-queues its unfinished simulations and starts a
replacement worker; the run finishes with exactly the same results.
"""
import asyncio
import sys


async def main(wid: int, url: str) -> None:
    from mcp import Client
    async with Client(url) as c:
        r = await c.call_tool("kill_worker", {"worker_id": wid})
        killed = (r.structured_content or {}).get("killed")
        print(f"Killed {killed}. Watch the run: the master re-queues its work and starts a replacement."
              if killed else "No worker to kill (is run_team.py running?)")


if __name__ == "__main__":
    wid = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 0
    port = 9150
    for i, a in enumerate(sys.argv):
        if a == "--mcp-port" and i + 1 < len(sys.argv):
            port = int(sys.argv[i + 1])
    try:
        asyncio.run(main(wid, f"http://127.0.0.1:{port}/mcp"))
    except Exception as e:
        print(f"Could not reach the MCP server on port {port}: is run_team.py running? ({type(e).__name__})")
