"""
Run one LevelForge agent as an A2A server.

    python -m levelforge.team.serve playtest --base-port 9100 --mcp http://127.0.0.1:9150/mcp

run_team.py starts all of them for you.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys

import uvicorn

from .a2a_kit import build_app, build_card
from .agents import HANDLERS, ROSTER


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("agent", choices=list(ROSTER))
    ap.add_argument("--base-port", type=int, default=9100)
    ap.add_argument("--mcp", default="http://127.0.0.1:9150/mcp")
    args = ap.parse_args()
    name, offset, description, skills = ROSTER[args.agent]
    port = args.base_port + offset
    card = build_card(name, description, skills, port)
    if args.agent == "director":
        from .director import director_handler_factory, enable_ansi
        enable_ansi()
        handler = asyncio.run(director_handler_factory(args.base_port, args.mcp))
    else:
        handler = HANDLERS[args.agent]
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    if args.agent != "director":   # the Director's console is the demo output: keep it clean
        print(f"[{name}] A2A server on http://127.0.0.1:{port}  (card: /.well-known/agent-card.json)",
              file=sys.stderr, flush=True)
    uvicorn.run(build_app(card, handler, args.mcp), host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
