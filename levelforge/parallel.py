"""
Parallel simulation runner - the HPC / multicore part of the project.

Every playthrough (level x persona x seed) is an independent task, so the
workload is embarrassingly parallel. We distribute tasks over a pool of worker
processes (one Python interpreter per core, which side-steps the GIL).

Design choices worth explaining in the viva:
  * processes, not threads: the simulator is pure-Python CPU work, and the GIL
    would serialise threads.
  * chunksize: measured, not assumed. One playthrough costs ~4 ms, far more than
    the cost of sending it to a worker, but playthrough cost varies a lot between
    levels and bot types. Large chunks therefore cause load imbalance (some workers
    finish early and idle). benchmark.py showed chunksize 1-8 beats n/(4p) by ~20%,
    so we use small chunks.
  * a persistent pool: process start-up is expensive on Windows ("spawn"), so
    the agent loop creates one pool and reuses it across optimisation rounds.
"""
from __future__ import annotations

import os
import time
from multiprocessing import Pool

from .metrics import aggregate
from .simulator import PERSONAS, simulate

DEFAULT_WORKERS = 5


def _task(args):
    level_dict, persona, seed = args
    return simulate(level_dict, persona, seed)


def make_tasks(level_dict: dict, runs_per_persona: int, base_seed: int = 0) -> list:
    return [(level_dict, p, base_seed + i * 7919 + j)
            for j, p in enumerate(PERSONAS) for i in range(runs_per_persona)]


def auto_chunksize(n_tasks: int, workers: int) -> int:
    # Small chunks: task durations vary, so fine-grained dispatch balances load better
    # (benchmark: chunksize 1 -> 1205 sims/s, n/(4p)=180 -> 997 sims/s on 5 workers).
    return max(1, min(8, n_tasks // (workers * 64)))


class ParallelRunner:
    """Reusable process pool. Use as a context manager."""

    def __init__(self, workers: int = DEFAULT_WORKERS):
        self.workers = max(1, int(workers))
        self.pool = None

    def __enter__(self):
        if self.workers > 1:
            self.pool = Pool(processes=self.workers)
        return self

    def __exit__(self, *exc):
        if self.pool:
            self.pool.close()
            self.pool.join()

    def run_tasks(self, tasks: list) -> list[dict]:
        if self.workers == 1 or self.pool is None:
            return [_task(t) for t in tasks]
        return self.pool.map(_task, tasks, chunksize=auto_chunksize(len(tasks), self.workers))

    def evaluate(self, level_dict: dict, runs_per_persona: int = 200, base_seed: int = 0) -> dict:
        t0 = time.perf_counter()
        runs = self.run_tasks(make_tasks(level_dict, runs_per_persona, base_seed))
        elapsed = time.perf_counter() - t0
        m = aggregate(runs)
        m["sim_seconds"] = round(elapsed, 4)
        m["sims_per_second"] = round(len(runs) / elapsed, 1) if elapsed else 0.0
        m["workers"] = self.workers
        return m


    def evaluate_many(self, level_dicts: list[dict], runs_per_persona: int = 200,
                      base_seed: int = 0) -> list[dict]:
        """Evaluate several candidate levels in ONE parallel sweep.

        All playthroughs of all candidates go into a single task list, so every
        worker stays busy instead of waiting at a barrier after each level.
        Every candidate uses the same seeds (common random numbers), which makes
        the comparison between candidates fairer.
        """
        t0 = time.perf_counter()
        per = len(PERSONAS) * runs_per_persona
        tasks = [t for ld in level_dicts for t in make_tasks(ld, runs_per_persona, base_seed)]
        runs = self.run_tasks(tasks)
        elapsed = time.perf_counter() - t0
        out = []
        for i in range(len(level_dicts)):
            m = aggregate(runs[i * per:(i + 1) * per])
            m["workers"] = self.workers
            out.append(m)
        for m in out:
            m["sweep_seconds"] = round(elapsed, 4)
            m["sweep_sims_per_second"] = round(len(runs) / elapsed, 1) if elapsed else 0.0
        return out


def cpu_count() -> int:
    return os.cpu_count() or 1
