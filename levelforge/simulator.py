"""
Turn-based dungeon simulator with rule-based player bots.

Each simulated playthrough is independent and seeded, which makes the workload
embarrassingly parallel: the parallel runner just farms (level, persona, seed)
tasks out to worker processes.

Bot personalities (no learning, pure planning with A*-style Dijkstra):
    rusher    - shortest path to the exit, ignores danger
    cautious  - avoids monsters and traps, heals when low on HP
    explorer  - collects coins/potions first, then heads to the exit
"""
from __future__ import annotations

import heapq
import random
from dataclasses import dataclass, field

from .level import (COIN, DIRS, DOOR, EXIT, FLOOR, KEY, MONSTER, POTION, START, TRAP,
                    WALL, Level)

PERSONAS = ("rusher", "cautious", "explorer")

MAX_HP = 12
START_HP = 10

# Tunable game rules -------------------------------------------------------
MONSTER_HP = 3
MONSTER_HIT_CHANCE = 0.6
TRAP_TRIGGER_CHANCE = 0.6
TRAP_DAMAGE = 3
LUNGE_CHANCE = 0.25          # monster hits you when you walk next to it
POTION_HEAL = 4

# Per-persona path costs: how much each bot "dislikes" entering a tile
COSTS = {
    #            trap  monster  next-to-monster
    "rusher":   (1.0,  2.0,     0.0),
    "cautious": (10.0, 25.0,    4.0),
    "explorer": (4.0,  6.0,     1.5),
}


@dataclass
class RunResult:
    persona: str
    seed: int
    completed: bool = False
    died: bool = False
    timeout: bool = False
    steps: int = 0
    hp_left: int = 0
    damage_taken: int = 0
    fights: int = 0
    trap_hits: int = 0
    coins_collected: int = 0
    coins_total: int = 0
    potions_used: int = 0
    unique_tiles: int = 0
    open_tiles: int = 0
    trace: list = field(default_factory=list)   # [(r, c, hp, event)] when recording

    def to_dict(self) -> dict:
        d = self.__dict__.copy()
        if not d["trace"]:
            d.pop("trace")
        return d


class Simulation:
    def __init__(self, level: Level, persona: str, seed: int, record: bool = False):
        if persona not in PERSONAS:
            raise ValueError(f"unknown persona {persona}")
        self.level = level
        self.persona = persona
        self.rng = random.Random(seed)
        self.record = record
        self.H, self.W = level.height, level.width
        self.grid = [list(r) for r in level.grid]
        self.pos = level.find(START)[0]
        self.grid[self.pos[0]][self.pos[1]] = FLOOR
        self.exit = level.find(EXIT)[0]
        self.hp = START_HP
        self.keys = 0
        self.monster_hp = {p: MONSTER_HP for p in level.find(MONSTER)}
        self.res = RunResult(persona=persona, seed=seed,
                             coins_total=level.count(COIN), open_tiles=level.floor_tiles())
        self.visited = {self.pos}
        self.step_limit = 3 * level.floor_tiles() + 20
        self.explore_budget = int(self.step_limit * 0.55)

    # ------------------------------------------------------------------
    def near_monster(self, r: int, c: int) -> bool:
        for dr, dc in DIRS:
            if self.grid[r + dr][c + dc] == MONSTER:
                return True
        return False

    def enter_cost(self, r: int, c: int) -> float | None:
        t = self.grid[r][c]
        if t == WALL or (t == DOOR and self.keys == 0):
            return None
        trap_c, mon_c, adj_c = COSTS[self.persona]
        cost = 1.0
        if t == TRAP:
            cost += trap_c
        elif t == MONSTER:
            cost += mon_c
        if adj_c and self.near_monster(r, c):
            cost += adj_c
        return cost

    def shortest_paths(self) -> tuple[dict, dict]:
        """Dijkstra from the current position under this persona's cost model."""
        dist = {self.pos: 0.0}
        prev: dict = {}
        pq = [(0.0, self.pos)]
        while pq:
            d, (r, c) = heapq.heappop(pq)
            if d > dist[(r, c)]:
                continue
            for dr, dc in DIRS:
                nr, nc = r + dr, c + dc
                cost = self.enter_cost(nr, nc)
                if cost is None:
                    continue
                nd = d + cost
                if nd < dist.get((nr, nc), float("inf")):
                    dist[(nr, nc)] = nd
                    prev[(nr, nc)] = (r, c)
                    heapq.heappush(pq, (nd, (nr, nc)))
        return dist, prev

    @staticmethod
    def build_path(prev: dict, target) -> list:
        path = [target]
        while path[-1] in prev:
            path.append(prev[path[-1]])
        path.reverse()
        return path[1:]  # drop current position

    def choose_target(self, dist: dict):
        def nearest(tile):
            cands = [(dist[p], p) for p in self._tiles(tile) if p in dist]
            return min(cands)[1] if cands else None

        if self.persona == "cautious" and self.hp <= 5:
            t = nearest(POTION)
            if t:
                return t
        if self.persona == "explorer" and self.res.steps < self.explore_budget and self.hp > 4:
            items = [(dist[p], p) for p in self._tiles(COIN) + self._tiles(POTION) if p in dist]
            if items:
                return min(items)[1]
        if self.exit in dist:
            return self.exit
        return nearest(KEY)

    def _tiles(self, ch):
        return [(r, c) for r in range(self.H) for c in range(self.W) if self.grid[r][c] == ch]

    # ------------------------------------------------------------------
    def fight(self, cell) -> None:
        self.res.fights += 1
        while self.monster_hp[cell] > 0 and self.hp > 0:
            self.monster_hp[cell] -= self.rng.choice((1, 2))
            if self.monster_hp[cell] > 0 and self.rng.random() < MONSTER_HIT_CHANCE:
                dmg = self.rng.choice((1, 2))
                self.hp -= dmg
                self.res.damage_taken += dmg
        if self.monster_hp[cell] <= 0:
            self.grid[cell[0]][cell[1]] = FLOOR

    def step_into(self, cell) -> str:
        """Apply the effects of entering a cell. Returns an event label."""
        r, c = cell
        t = self.grid[r][c]
        event = ""
        if t == MONSTER:
            self.fight(cell)
            event = "fight"
            if self.hp <= 0:
                return "died"
        self.pos = cell
        self.visited.add(cell)
        if t == TRAP and self.rng.random() < TRAP_TRIGGER_CHANCE:
            self.hp -= TRAP_DAMAGE
            self.res.damage_taken += TRAP_DAMAGE
            self.res.trap_hits += 1
            event = "trap"
        elif t == POTION:
            self.hp = min(MAX_HP, self.hp + POTION_HEAL)
            self.res.potions_used += 1
            self.grid[r][c] = FLOOR
            event = "potion"
        elif t == COIN:
            self.res.coins_collected += 1
            self.grid[r][c] = FLOOR
            event = "coin"
        elif t == KEY:
            self.keys += 1
            self.grid[r][c] = FLOOR
            event = "key"
        elif t == DOOR:
            self.grid[r][c] = FLOOR
            event = "door"
        # monsters next to you may lunge
        if self.hp > 0 and t != MONSTER and self.near_monster(r, c) and self.rng.random() < LUNGE_CHANCE:
            self.hp -= 1
            self.res.damage_taken += 1
            event = event or "hit"
        if self.hp <= 0:
            return "died"
        if cell == self.exit:
            return "exit"
        return event

    def run(self) -> RunResult:
        if self.record:
            self.res.trace.append((self.pos[0], self.pos[1], self.hp, "start"))
        path: list = []
        while True:
            if self.res.steps >= self.step_limit:
                self.res.timeout = True
                break
            if not path:
                dist, prev = self.shortest_paths()
                target = self.choose_target(dist)
                if target is None:
                    self.res.timeout = True  # stuck: nothing reachable
                    break
                path = self.build_path(prev, target)
                if not path:
                    self.res.timeout = True
                    break
            cell = path.pop(0)
            self.res.steps += 1
            event = self.step_into(cell)
            if self.record:
                self.res.trace.append((self.pos[0], self.pos[1], max(self.hp, 0), event))
            if event == "died":
                self.res.died = True
                break
            if event == "exit":
                self.res.completed = True
                break
            if event:  # something changed: replan next step
                path = []
        self.res.hp_left = max(self.hp, 0)
        self.res.unique_tiles = len(self.visited)
        return self.res


def simulate(level_dict: dict, persona: str, seed: int, record: bool = False) -> dict:
    """Module-level entry point (picklable, used by worker processes)."""
    lvl = Level.from_dict(level_dict)
    return Simulation(lvl, persona, seed, record).run().to_dict()
