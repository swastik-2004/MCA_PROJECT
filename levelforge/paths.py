"""Path helpers shared by the generator and the edit operations."""
from __future__ import annotations

from collections import deque

from .level import DIRS, EXIT, START, WALL, Level


def bfs_dist(level: Level, src: tuple[int, int]) -> dict:
    """Step distances from src, treating doors as open and hazards as walkable."""
    dist = {src: 0}
    q = deque([src])
    while q:
        r, c = q.popleft()
        for dr, dc in DIRS:
            nr, nc = r + dr, c + dc
            if 0 <= nr < level.height and 0 <= nc < level.width and (nr, nc) not in dist \
                    and level.tile(nr, nc) != WALL:
                dist[(nr, nc)] = dist[(r, c)] + 1
                q.append((nr, nc))
    return dist


def main_path(level: Level) -> list[tuple[int, int]]:
    """Shortest walkable route from S to E (list of cells including both ends)."""
    starts, exits = level.find(START), level.find(EXIT)
    if not starts or not exits:
        return []
    s, e = starts[0], exits[0]
    prev = {s: None}
    q = deque([s])
    while q:
        cur = q.popleft()
        if cur == e:
            break
        r, c = cur
        for dr, dc in DIRS:
            n = (r + dr, c + dc)
            if 0 <= n[0] < level.height and 0 <= n[1] < level.width and n not in prev \
                    and level.tile(*n) != WALL:
                prev[n] = cur
                q.append(n)
    if e not in prev:
        return []
    path = [e]
    while prev[path[-1]] is not None:
        path.append(prev[path[-1]])
    return path[::-1]
