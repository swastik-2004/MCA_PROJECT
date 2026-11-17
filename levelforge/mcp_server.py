"""
LevelForge digital twin as an MCP (Model Context Protocol) server.

MCP is the standard way for AI agents to use tools. This server exposes the
digital twin - level validation, structured edits and parallel play-testing on the
master-worker cluster - as MCP tools, so ANY MCP client can use it:

  * the LevelForge agent team (run_team.py) connects over Streamable HTTP
  * Claude Desktop (or any other MCP host) can connect over stdio, so you can ask
    an assistant to "fix this level" and it calls these same tools

    python -m levelforge.mcp_server                       # stdio (for Claude Desktop)
    python -m levelforge.mcp_server --http --port 9150    # HTTP (for the agent team)

Tools
    get_rules          tile legend, game values, edit operations, player types
    validate_level     is a grid playable? (exit reachable, one start, ...)
    generate_level     procedural level from a seed
    repair_level       turn an almost-valid grid into a playable one
    apply_edits        apply structured edit operations (validated)
    level_summary      counts of each tile + an ASCII rendering
    evaluate_levels    play-test levels with the simulated players on the cluster
    cluster_status     workers, their load, failures
    kill_worker        crash one worker (fault-tolerance demo)
    inject_fault       crash a worker during the next simulation job
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
from typing import Any

import anyio
from mcp.server import MCPServer

from . import simulator
from .cluster import DEFAULT_WORKERS, SimCluster
from .edits import OPS_HELP, apply_edits as _apply_edits
from .generator import random_candidate
from .level import Level, repair, validate
from .metrics import DEFAULT_BRIEF, quality

INSTRUCTIONS = """LevelForge digital twin: a simplified, fast model of a top-down dungeon / shooter level.
A level is a list of equal-length strings. Tiles: # wall, . floor, S start, E exit, K key,
D locked door, M monster, T trap, H health potion, C coin. Typical workflow to improve a level:
validate_level -> evaluate_levels (baseline) -> apply_edits (several alternative plans) ->
evaluate_levels on all candidates together -> keep the best. A higher quality.total is better;
completion should be near the brief's target_completion (default 0.65), not 100%."""

mcp = MCPServer("levelforge-twin", instructions=INSTRUCTIONS, version="1.0")

_cluster: SimCluster | None = None
_cluster_lock = threading.Lock()
_workers = int(os.environ.get("LEVELFORGE_WORKERS", DEFAULT_WORKERS))


def cluster() -> SimCluster:
    global _cluster
    with _cluster_lock:
        if _cluster is None:
            _cluster = SimCluster(_workers)
            _cluster.start()
        return _cluster


def _level(grid: list[str], name: str = "level") -> Level:
    return Level(name=name, grid=[str(r) for r in grid])


def _round(v):
    if isinstance(v, float):
        return round(v, 4)
    if isinstance(v, dict):
        return {k: _round(x) for k, x in v.items()}
    return v


# ---------------------------------------------------------------------------- tools
@mcp.tool()
def get_rules() -> dict[str, Any]:
    """Tile legend, game values, allowed edit operations and the simulated player types."""
    return {
        "tiles": {"#": "wall", ".": "floor", "S": "start", "E": "exit", "K": "key", "D": "locked door",
                  "M": "monster (hunter drone in the 3D game)", "T": "trap (proximity mine)",
                  "H": "health potion (med-kit)", "C": "coin (data core)"},
        "rules": {k: getattr(simulator, k) for k in ("START_HP", "MAX_HP", "MONSTER_HP", "MONSTER_HIT_CHANCE",
                                                    "TRAP_TRIGGER_CHANCE", "TRAP_DAMAGE", "LUNGE_CHANCE",
                                                    "POTION_HEAL")},
        "edit_operations": OPS_HELP,
        "players": {"rusher": "shortest path, ignores danger", "cautious": "avoids hazards, heals when low",
                    "explorer": "collects coins and potions, then exits"},
        "default_brief": DEFAULT_BRIEF,
    }


@mcp.tool()
def validate_level(grid: list[str]) -> dict[str, Any]:
    """Check that a level is playable. Returns {"ok": bool, "errors": [...]}."""
    errs = validate(_level(grid))
    return {"ok": not errs, "errors": errs}


@mcp.tool()
def generate_level(seed: int = 0) -> dict[str, Any]:
    """Create a procedural level (the same generator the experiments use)."""
    lvl = random_candidate(int(seed))
    return {"grid": lvl.grid, "summary": lvl.summary()}


@mcp.tool()
def repair_level(grid: list[str], seed: int = 0) -> dict[str, Any]:
    """Deterministically repair an almost-valid grid (border, start/exit, reachability)."""
    lvl = repair(_level(grid), seed=int(seed))
    errs = validate(lvl)
    return {"grid": lvl.grid, "ok": not errs, "errors": errs}


@mcp.tool()
def apply_edits(grid: list[str], edits: list[dict[str, Any]], seed: int = 0) -> dict[str, Any]:
    """Apply structured edit operations (see get_rules). Every edit is validated, so the result
    is always playable; edits that would break the level are skipped and reported in `log`."""
    new, log = _apply_edits(_level(grid), edits, seed=int(seed))
    applied = [x for x in log if x.startswith("applied")]
    return {"grid": new.grid, "log": log, "applied": len(applied), "changed": new.grid != list(grid)}


@mcp.tool()
def level_summary(grid: list[str]) -> dict[str, Any]:
    """Tile counts, size and an ASCII rendering of a level."""
    lvl = _level(grid)
    return {"summary": lvl.summary(), "ascii": "\n".join(lvl.grid), "errors": validate(lvl)}


@mcp.tool()
async def evaluate_levels(grids: list[list[str]], runs_per_persona: int = 150, seed: int = 1,
                          brief: dict[str, Any] | None = None) -> dict[str, Any]:
    """Play-test one or more levels with the simulated players (rusher, cautious, explorer) on the
    master-worker cluster. All levels go into ONE parallel job and share the same random seeds,
    so differences come from the levels. Returns metrics and quality score per level, plus the
    cluster's job report (time, sims/s, sims per worker, worker failures)."""
    levels = [_level(g, f"L{i}").to_dict() for i, g in enumerate(grids)]
    bad = [i for i, g in enumerate(grids) if validate(_level(g))]
    if bad:
        return {"error": f"levels {bad} are not playable; call validate_level first"}
    runs = max(10, min(1000, int(runs_per_persona)))
    b = brief or DEFAULT_BRIEF

    def work():
        c = cluster()
        ms = c.evaluate_many(levels, runs, base_seed=int(seed))
        return ms, dict(c.last_job), len(c.alive_workers())

    metrics, job, alive = await anyio.to_thread.run_sync(work)
    results = [{"metrics": _round(m), "quality": quality(m, b)} for m in metrics]
    return {"results": results, "job": job, "workers_alive": alive}


@mcp.tool()
def cluster_status() -> dict[str, Any]:
    """Workers of the master-worker cluster: process id, alive, simulations done, busy time."""
    return cluster().status()


@mcp.tool()
def kill_worker(worker_id: int = 0) -> dict[str, Any]:
    """Crash one worker process now (fault-tolerance demo). 0 = pick a busy one.
    The master re-queues its unfinished work and starts a replacement."""
    wid = cluster().kill_worker(worker_id or None)
    return {"killed": f"W{wid}" if wid else None}


@mcp.tool()
def inject_fault(jobs: int = 1) -> dict[str, Any]:
    """Crash one worker part-way through each of the next `jobs` simulation jobs."""
    cluster().chaos(jobs)
    return {"armed_jobs": jobs}


@mcp.prompt()
def improve_level(grid: str, target_completion: float = 0.65) -> str:
    """Prompt template: improve a level with the LevelForge tools."""
    return (f"Improve this game level so that about {target_completion:.0%} of simulated players finish it.\n"
            f"Level:\n{grid}\n\nUse the levelforge-twin tools: evaluate the level, propose 3-4 alternative "
            "edit plans with apply_edits, evaluate all candidates together with evaluate_levels, keep the best, "
            "and repeat for a few rounds. Explain each change you keep.")


def main() -> None:
    global _workers
    ap = argparse.ArgumentParser(description="LevelForge digital twin MCP server")
    ap.add_argument("--http", action="store_true", help="serve Streamable HTTP instead of stdio")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=9150)
    ap.add_argument("--workers", type=int, default=_workers)
    args = ap.parse_args()
    _workers = args.workers
    logging.basicConfig(level=logging.WARNING, stream=sys.stderr)
    try:
        if args.http:
            cluster()  # start workers before the first request
            print(f"[mcp] levelforge-twin on http://{args.host}:{args.port}/mcp "
                  f"({_workers} simulation workers)", file=sys.stderr, flush=True)
            mcp.run("streamable-http", host=args.host, port=args.port)
        else:
            mcp.run()
    finally:
        if _cluster is not None:
            _cluster.close()


if __name__ == "__main__":
    main()
