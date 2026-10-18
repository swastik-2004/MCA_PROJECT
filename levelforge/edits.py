"""
Edit operations: the "actions" the optimizer agent can take on a level.

Instead of asking an LLM to rewrite the whole grid (which often breaks it), the
optimizer agent chooses a short list of structured edits, e.g.

    {"op": "remove", "tile": "M", "count": 2, "where": "main"}
    {"op": "add",    "tile": "H", "count": 1, "where": "side"}
    {"op": "add_loop", "count": 1}

and this module applies them deterministically. Every edit is validated; an
edit that would make the level unplayable is rejected and logged.
"""
from __future__ import annotations

import random

from .generator import _add_lock, scatter
from .level import (COIN, DOOR, FLOOR, KEY, MONSTER, POTION, TRAP, WALL, Level,
                    validate)
from .paths import bfs_dist, main_path

EDITABLE = {MONSTER: "monster", TRAP: "trap", POTION: "potion", COIN: "coin"}
NAME_TO_TILE = {v: k for k, v in EDITABLE.items()}

OPS_HELP = """Allowed edit operations (JSON objects):
  {"op": "add",    "tile": "M|T|H|C", "count": 1-4, "where": "main|side|any"}
  {"op": "remove", "tile": "M|T|H|C", "count": 1-4, "where": "main|side|any"}
  {"op": "add_loop", "count": 1-2}     # knock out a wall to create a shortcut / loop
  {"op": "add_lock"}                   # add a key + locked door before the exit
  {"op": "remove_lock"}                # remove key and door
Tiles: M monster, T trap, H health potion, C coin.
"main" = on the shortest route from start to exit, "side" = off that route."""


def _norm_tile(t) -> str | None:
    if not isinstance(t, str):
        return None
    t = t.strip()
    if t.upper() in EDITABLE:
        return t.upper()
    return NAME_TO_TILE.get(t.lower().rstrip("s"))


def _remove(lvl: Level, rng, tile: str, n: int, where: str) -> Level:
    on_path = set(main_path(lvl))
    cells = lvl.find(tile)
    main = [p for p in cells if p in on_path]
    side = [p for p in cells if p not in on_path]
    rng.shuffle(main)
    rng.shuffle(side)
    order = {"main": main + side, "side": side + main}.get(where, main + side)
    rows = [list(r) for r in lvl.grid]
    for r, c in order[:n]:
        rows[r][c] = FLOOR
    return Level(lvl.name, ["".join(r) for r in rows], lvl.notes, dict(lvl.meta))


def _add_loop(lvl: Level, n: int) -> Level:
    """Remove the wall that best shortens travel between two open areas."""
    rows = [list(r) for r in lvl.grid]
    for _ in range(n):
        cur = Level(lvl.name, ["".join(r) for r in rows])
        best, best_gain = None, 0
        dist_cache: dict = {}
        for r in range(1, cur.height - 1):
            for c in range(1, cur.width - 1):
                if rows[r][c] != WALL:
                    continue
                for a, b in (((r, c - 1), (r, c + 1)), ((r - 1, c), (r + 1, c))):
                    if rows[a[0]][a[1]] == WALL or rows[b[0]][b[1]] == WALL:
                        continue
                    if a not in dist_cache:
                        dist_cache[a] = bfs_dist(cur, a)
                    d = dist_cache[a].get(b)
                    gain = 50 if d is None else d - 2
                    if gain > best_gain:
                        best, best_gain = (r, c), gain
        if best is None or best_gain < 4:
            break
        rows[best[0]][best[1]] = FLOOR
    return Level(lvl.name, ["".join(r) for r in rows], lvl.notes, dict(lvl.meta))


def _remove_lock(lvl: Level) -> Level:
    rows = [["." if t in (KEY, DOOR) else t for t in r] for r in lvl.grid]
    return Level(lvl.name, ["".join(r) for r in rows], lvl.notes, dict(lvl.meta))


def apply_edits(level: Level, ops: list, seed: int = 0) -> tuple[Level, list[str]]:
    rng = random.Random(seed)
    log: list[str] = []
    cur = level
    for op in ops[:8]:
        if not isinstance(op, dict):
            log.append(f"skipped non-object op: {op!r}")
            continue
        kind = str(op.get("op", "")).lower()
        try:
            n = max(1, min(4, int(op.get("count", 1))))
        except (TypeError, ValueError):
            n = 1
        where = str(op.get("where", "any")).lower()
        if where not in ("main", "side", "any"):
            where = "any"
        tile = _norm_tile(op.get("tile"))

        if kind == "add" and tile:
            new = scatter(cur, rng, tile, n, prefer=where)
            desc = f"add {n} {EDITABLE[tile]} ({where})"
        elif kind == "remove" and tile:
            if not cur.count(tile):
                log.append(f"skipped remove {EDITABLE[tile]}: none present")
                continue
            new = _remove(cur, rng, tile, n, where)
            desc = f"remove {n} {EDITABLE[tile]} ({where})"
        elif kind == "add_loop":
            new = _add_loop(cur, min(n, 2))
            desc = "add loop/shortcut"
        elif kind == "add_lock":
            if cur.count(DOOR):
                log.append("skipped add_lock: level already has a lock")
                continue
            new = _add_lock(cur, rng)
            if new is None:
                log.append("skipped add_lock: no chokepoint found")
                continue
            desc = "add key + locked door"
        elif kind == "remove_lock":
            new = _remove_lock(cur)
            desc = "remove key + locked door"
        else:
            log.append(f"skipped unknown op: {op}")
            continue

        errs = validate(new)
        if errs:
            log.append(f"rejected '{desc}': {errs[0]}")
            continue
        if new.grid == cur.grid:
            log.append(f"no change from '{desc}'")
            continue
        cur = new
        log.append(f"applied: {desc}")
    return cur, log
