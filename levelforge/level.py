"""
Level representation (the "digital twin" of a game level).

A level is a rectangular grid of single-character tiles stored as a list of strings.
This format is deliberately simple so an LLM can read and write it reliably.

Tiles
-----
    #  wall              .  floor
    S  player start      E  exit
    K  key               D  door (needs a key)
    M  monster           T  trap (may hurt when stepped on)
    H  health potion     C  coin / treasure (optional content)
"""
from __future__ import annotations

import json
import random
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

WALL, FLOOR, START, EXIT = "#", ".", "S", "E"
KEY, DOOR, MONSTER, TRAP = "K", "D", "M", "T"
POTION, COIN = "H", "C"

VALID_TILES = set("#.SEKDMTHC")
PASSABLE_WITHOUT_KEY = set(".SEKMTHC")  # door is the only conditional tile

DIRS = [(0, 1), (1, 0), (0, -1), (-1, 0)]


@dataclass
class Level:
    name: str
    grid: list[str]
    notes: str = ""
    meta: dict = field(default_factory=dict)

    # ---------- basic geometry ----------
    @property
    def height(self) -> int:
        return len(self.grid)

    @property
    def width(self) -> int:
        return len(self.grid[0]) if self.grid else 0

    def tile(self, r: int, c: int) -> str:
        return self.grid[r][c]

    def find(self, ch: str) -> list[tuple[int, int]]:
        return [(r, c) for r, row in enumerate(self.grid) for c, t in enumerate(row) if t == ch]

    def count(self, ch: str) -> int:
        return sum(row.count(ch) for row in self.grid)

    def floor_tiles(self) -> int:
        return sum(1 for row in self.grid for t in row if t != WALL)

    # ---------- serialisation ----------
    def to_dict(self) -> dict:
        return {"name": self.name, "grid": list(self.grid), "notes": self.notes, "meta": self.meta}

    @staticmethod
    def from_dict(d: dict) -> "Level":
        return Level(name=d.get("name", "level"), grid=[str(r) for r in d["grid"]],
                     notes=d.get("notes", ""), meta=d.get("meta", {}))

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2), encoding="utf-8")

    @staticmethod
    def load(path: str | Path) -> "Level":
        """Load a level from .json (this project's format) or a plain-text grid (.txt).
        In a .txt file every non-empty line is one grid row; lines starting with ';' are comments."""
        path = Path(path)
        text = path.read_text(encoding="utf-8")
        if path.suffix.lower() == ".json":
            return Level.from_dict(json.loads(text))
        rows = [ln.rstrip() for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith(";")]
        return Level(name=path.stem, grid=rows)

    def pretty(self) -> str:
        return "\n".join(self.grid)

    def summary(self) -> dict:
        return {
            "size": f"{self.width}x{self.height}",
            "monsters": self.count(MONSTER), "traps": self.count(TRAP),
            "potions": self.count(POTION), "coins": self.count(COIN),
            "keys": self.count(KEY), "doors": self.count(DOOR),
            "open_tiles": self.floor_tiles(),
        }


# ---------------------------------------------------------------------------
# Reachability helpers
# ---------------------------------------------------------------------------
def bfs_reachable(level: Level, start: tuple[int, int], has_key: bool) -> set[tuple[int, int]]:
    """Tiles reachable from start. Doors are passable only when has_key is True."""
    seen = {start}
    q = deque([start])
    while q:
        r, c = q.popleft()
        for dr, dc in DIRS:
            nr, nc = r + dr, c + dc
            if not (0 <= nr < level.height and 0 <= nc < level.width):
                continue
            if (nr, nc) in seen:
                continue
            t = level.tile(nr, nc)
            if t == WALL or (t == DOOR and not has_key):
                continue
            seen.add((nr, nc))
            q.append((nr, nc))
    return seen


def exit_reachable(level: Level) -> bool:
    starts, exits = level.find(START), level.find(EXIT)
    if len(starts) != 1 or len(exits) != 1:
        return False
    s, e = starts[0], exits[0]
    first = bfs_reachable(level, s, has_key=False)
    if e in first:
        return True
    # Exit is behind a door: a key must be reachable first.
    if any(k in first for k in level.find(KEY)):
        return e in bfs_reachable(level, s, has_key=True)
    return False


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
def validate(level: Level) -> list[str]:
    """Return a list of problems. An empty list means the level is playable."""
    errs: list[str] = []
    if not level.grid:
        return ["grid is empty"]
    w = len(level.grid[0])
    if any(len(row) != w for row in level.grid):
        errs.append("rows have different lengths")
        return errs
    if not (7 <= level.width <= 40 and 7 <= level.height <= 30):
        errs.append(f"size {level.width}x{level.height} outside 7..40 x 7..30")
    bad = {t for row in level.grid for t in row} - VALID_TILES
    if bad:
        errs.append(f"unknown tiles: {sorted(bad)}")
    if level.count(START) != 1:
        errs.append(f"need exactly 1 start 'S', found {level.count(START)}")
    if level.count(EXIT) != 1:
        errs.append(f"need exactly 1 exit 'E', found {level.count(EXIT)}")
    border = level.grid[0] + level.grid[-1] + "".join(r[0] + r[-1] for r in level.grid)
    if set(border) != {WALL}:
        errs.append("outer border must be all walls '#'")
    if level.count(DOOR) and not level.count(KEY):
        errs.append("level has doors but no key")
    if not errs and not exit_reachable(level):
        errs.append("exit is not reachable from start")
    return errs


# ---------------------------------------------------------------------------
# Repair: turn an almost-valid (e.g. LLM-written) level into a playable one
# ---------------------------------------------------------------------------
def repair(level: Level, seed: int = 0) -> Level:
    rng = random.Random(seed)
    rows = [list(r) for r in level.grid if r]
    if not rows:
        rows = [list("#" * 15) for _ in range(11)]
    w = max(len(r) for r in rows)
    w = min(max(w, 7), 40)
    rows = rows[:30]
    while len(rows) < 7:
        rows.append(list("#" * w))
    rows = [(r + ["#"] * w)[:w] for r in rows]
    h = len(rows)

    # unknown tiles -> floor
    for r in range(h):
        for c in range(w):
            if rows[r][c] not in VALID_TILES:
                rows[r][c] = FLOOR
    # border
    for c in range(w):
        rows[0][c] = rows[h - 1][c] = WALL
    for r in range(h):
        rows[r][0] = rows[r][w - 1] = WALL

    def interior_cells(ch):
        return [(r, c) for r in range(1, h - 1) for c in range(1, w - 1) if rows[r][c] == ch]

    # exactly one S and one E
    for ch, default in ((START, (1, 1)), (EXIT, (h - 2, w - 2))):
        cells = interior_cells(ch)
        for extra in cells[1:]:
            rows[extra[0]][extra[1]] = FLOOR
        if not cells:
            rows[default[0]][default[1]] = ch
    # a door with no key: drop a key near the start
    if any(DOOR in r for r in rows) and not any(KEY in r for r in rows):
        sr, sc = interior_cells(START)[0]
        for dr, dc in DIRS:
            if rows[sr + dr][sc + dc] in (FLOOR, WALL) and 0 < sr + dr < h - 1 and 0 < sc + dc < w - 1:
                rows[sr + dr][sc + dc] = KEY
                break

    fixed = Level(level.name, ["".join(r) for r in rows], level.notes, dict(level.meta))
    if exit_reachable(fixed):
        return fixed

    # carve an L-shaped corridor from S to E (only through walls/doors)
    (sr, sc), (er, ec) = fixed.find(START)[0], fixed.find(EXIT)[0]
    rows = [list(r) for r in fixed.grid]
    r, c = sr, sc
    horizontal_first = rng.random() < 0.5
    path = []
    if horizontal_first:
        while c != ec:
            c += 1 if ec > c else -1
            path.append((r, c))
        while r != er:
            r += 1 if er > r else -1
            path.append((r, c))
    else:
        while r != er:
            r += 1 if er > r else -1
            path.append((r, c))
        while c != ec:
            c += 1 if ec > c else -1
            path.append((r, c))
    for pr, pc in path:
        if rows[pr][pc] in (WALL, DOOR):
            rows[pr][pc] = FLOOR
    return Level(level.name, ["".join(r) for r in rows], level.notes, dict(level.meta))
