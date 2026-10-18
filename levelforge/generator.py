"""
Procedural level generator.

Used in two places:
  1. as the *offline fallback* when no LLM API key is configured, and
  2. to create random "raw" candidate levels for the baseline experiment.

It builds rooms connected by corridors, then scatters content.
"""
from __future__ import annotations

import random

from .level import (COIN, DOOR, EXIT, FLOOR, KEY, MONSTER, POTION, START, TRAP, WALL,
                    Level, bfs_reachable, exit_reachable)
from .paths import main_path


def _carve_room(g, r, c, h, w):
    for i in range(r, r + h):
        for j in range(c, c + w):
            g[i][j] = FLOOR


def _carve_corridor(g, a, b, rng):
    (r1, c1), (r2, c2) = a, b
    if rng.random() < 0.5:
        for c in range(min(c1, c2), max(c1, c2) + 1):
            g[r1][c] = FLOOR
        for r in range(min(r1, r2), max(r1, r2) + 1):
            g[r][c2] = FLOOR
    else:
        for r in range(min(r1, r2), max(r1, r2) + 1):
            g[r][c1] = FLOOR
        for c in range(min(c1, c2), max(c1, c2) + 1):
            g[r2][c] = FLOOR


def generate(seed: int = 0, width: int = 23, height: int = 15, monsters: int = 5,
             traps: int = 4, coins: int = 4, potions: int = 2, lock: bool = True,
             name: str | None = None) -> Level:
    rng = random.Random(seed)
    g = [[WALL] * width for _ in range(height)]
    rooms = []
    for _ in range(200):
        if len(rooms) >= 7:
            break
        h, w = rng.randint(3, 5), rng.randint(3, 7)
        r, c = rng.randint(1, height - h - 1), rng.randint(1, width - w - 1)
        if any(r - 1 < rr + hh and rr - 1 < r + h and c - 1 < cc + ww and cc - 1 < c + w
               for rr, cc, hh, ww in rooms):
            continue
        rooms.append((r, c, h, w))
    rooms.sort(key=lambda x: x[1])  # left to right
    for room in rooms:
        _carve_room(g, *room)
    centers = [(r + h // 2, c + w // 2) for r, c, h, w in rooms]
    for a, b in zip(centers, centers[1:]):
        _carve_corridor(g, a, b, rng)

    sr, sc = centers[0]
    er, ec = centers[-1]
    g[sr][sc], g[er][ec] = START, EXIT
    lvl = Level(name or f"proc_{seed}", ["".join(r) for r in g])

    if lock:
        lvl = _add_lock(lvl, rng) or lvl

    lvl = scatter(lvl, rng, MONSTER, monsters, prefer="main")
    lvl = scatter(lvl, rng, TRAP, traps, prefer="main")
    lvl = scatter(lvl, rng, COIN, coins, prefer="side")
    lvl = scatter(lvl, rng, POTION, potions, prefer="side")
    return lvl


def _add_lock(lvl: Level, rng: random.Random) -> Level | None:
    """Put a door on a chokepoint near the exit and a key somewhere before it."""
    path = main_path(lvl)
    if len(path) < 6:
        return None
    start = lvl.find(START)[0]
    for cell in reversed(path[1:-2]):  # walk back from the exit
        rows = [list(r) for r in lvl.grid]
        rows[cell[0]][cell[1]] = DOOR
        test = Level(lvl.name, ["".join(r) for r in rows])
        before = bfs_reachable(test, start, has_key=False)
        if lvl.find(EXIT)[0] in before:
            continue  # not a chokepoint
        spots = [p for p in before if test.tile(*p) == FLOOR and p != start]
        if not spots:
            return None
        far = sorted(spots, key=lambda p: abs(p[0] - start[0]) + abs(p[1] - start[1]))
        kr, kc = rng.choice(far[len(far) // 2:])
        rows[kr][kc] = KEY
        out = Level(lvl.name, ["".join(r) for r in rows])
        return out if exit_reachable(out) else None
    return None


def scatter(lvl: Level, rng: random.Random, tile: str, n: int, prefer: str = "any") -> Level:
    """Place n copies of a tile on empty floor. prefer: 'main' path, 'side' areas, or 'any'."""
    if n <= 0:
        return lvl
    on_path = set(main_path(lvl))
    s, e = lvl.find(START)[0], lvl.find(EXIT)[0]
    empty = [(r, c) for r in range(lvl.height) for c in range(lvl.width)
             if lvl.tile(r, c) == FLOOR and abs(r - s[0]) + abs(c - s[1]) > 2
             and abs(r - e[0]) + abs(c - e[1]) > 1]
    main = [p for p in empty if p in on_path]
    side = [p for p in empty if p not in on_path]
    rng.shuffle(main)
    rng.shuffle(side)
    pool = {"main": main + side, "side": side + main}.get(prefer, empty)
    if prefer == "any":
        rng.shuffle(pool)
    rows = [list(r) for r in lvl.grid]
    placed = 0
    for r, c in pool:
        if placed >= n:
            break
        # never block the only route with something impassable (all hazards are passable)
        rows[r][c] = tile
        placed += 1
    return Level(lvl.name, ["".join(r) for r in rows], lvl.notes, dict(lvl.meta))


def random_candidate(seed: int) -> Level:
    """A deliberately 'raw' level with random, often unbalanced, content counts."""
    rng = random.Random(seed * 31 + 7)
    return generate(seed=seed, monsters=rng.randint(2, 11), traps=rng.randint(1, 10),
                    coins=rng.randint(0, 6), potions=rng.randint(0, 3),
                    lock=rng.random() < 0.6, name=f"raw_{seed}")
