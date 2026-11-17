"""
Master-worker simulation cluster - the explicit HPC / multicore engine.

    MASTER (this process)                      WORKERS (one process each)
    ---------------------                      --------------------------
    splits a job into chunks of <= 8 sims       W1  recv chunk -> simulate -> send results
    keeps a ready queue of chunks          ---> W2  recv chunk -> simulate -> send results
    gives each worker 2 chunks (prefetch)       W3  ...
    sends a new chunk when one comes back  <--- results + time taken
    watches every worker's process sentinel
    if a worker dies: re-queue its unfinished chunks and start a replacement worker

Why an explicit master instead of multiprocessing.Pool?
  * Pool hides scheduling. Here the master decides who gets which work (dynamic
    self-scheduling: fast workers simply come back for more), which is the classic
    master-worker pattern from the multicore course.
  * Fault tolerance: Pool hangs or loses tasks if a worker is killed. The master
    detects the death through the process sentinel and re-runs the lost chunks, so
    the result is still complete and identical (every task is seeded).
  * Observability: per-worker counts, busy time and failures are reported, which the
    agents and the report show.

Each worker has its own Pipe (no shared queue), so killing one worker can never
corrupt a lock that other workers need.
"""
from __future__ import annotations

import multiprocessing as mp
import os
import random
import sys
import time
from collections import deque
from multiprocessing.connection import wait

from .metrics import aggregate
from .simulator import PERSONAS, simulate

DEFAULT_WORKERS = 5
CHUNK = 8          # sims per chunk (benchmark.py: small chunks balance load best)
PREFETCH = 2       # chunks in flight per worker, so a worker never waits for the master


def _log(msg: str) -> None:
    # stderr only: stdout may be an MCP stdio channel
    print(msg, file=sys.stderr, flush=True)


def worker_main(wid: int, conn) -> None:
    """Worker loop: receive a chunk, simulate it, send the results back."""
    while True:
        try:
            msg = conn.recv()
        except (EOFError, OSError):
            break
        if msg is None:
            break
        job, cid, tasks = msg
        t0 = time.perf_counter()
        results = [simulate(level, persona, seed) for level, persona, seed in tasks]
        try:
            conn.send((job, cid, results, time.perf_counter() - t0))
        except (BrokenPipeError, OSError):
            break


def make_tasks(level_dict: dict, runs_per_persona: int, base_seed: int = 0) -> list:
    """Same task list (and seeds) as parallel.make_tasks, so results are identical."""
    return [(level_dict, p, base_seed + i * 7919 + j)
            for j, p in enumerate(PERSONAS) for i in range(runs_per_persona)]


class _Worker:
    def __init__(self, wid: int, ctx):
        self.wid = wid
        self.conn, child = ctx.Pipe()
        self.proc = ctx.Process(target=worker_main, args=(wid, child), daemon=True,
                                name=f"levelforge-W{wid}")
        self.proc.start()
        child.close()
        self.inflight: deque = deque()
        self.alive = True
        self.sims = 0
        self.chunks = 0
        self.busy = 0.0


class SimCluster:
    """Master process of the master-worker cluster. Use as a context manager.

    Same evaluate / evaluate_many interface as ParallelRunner, so either engine can
    drive the agents.
    """

    def __init__(self, workers: int = DEFAULT_WORKERS, chunk: int = CHUNK, respawn: bool = True,
                 on_event=None):
        self.workers = max(1, int(workers))
        self.chunk = max(1, int(chunk))
        self.respawn = respawn
        self.on_event = on_event or (lambda e: None)
        self.ctx = mp.get_context("spawn")      # same behaviour on Windows and Linux
        self.pool: dict[int, _Worker] = {}
        self.next_wid = 1
        self.job = 0
        self.failures = 0
        self.events: list[dict] = []
        self._chaos_jobs = 0                     # how many future jobs should lose a worker
        self._startup_deaths = 0
        self.last_job: dict = {}

    # ------------------------------------------------------------ lifecycle
    def __enter__(self):
        self.start()
        return self

    def __exit__(self, *exc):
        self.close()

    def start(self) -> None:
        for _ in range(self.workers):
            self._spawn()

    def _spawn(self) -> _Worker:
        w = _Worker(self.next_wid, self.ctx)
        self.pool[w.wid] = w
        self.next_wid += 1
        return w

    def close(self) -> None:
        for w in self.pool.values():
            if w.alive:
                try:
                    w.conn.send(None)
                except (BrokenPipeError, OSError):
                    pass
        for w in self.pool.values():
            w.proc.join(timeout=2)
            if w.proc.is_alive():
                w.proc.terminate()
        self.pool.clear()

    def alive_workers(self) -> list[_Worker]:
        return [w for w in self.pool.values() if w.alive]

    # ------------------------------------------------------------ fault injection (demo)
    def kill_worker(self, wid: int | None = None) -> int | None:
        """Hard-kill one worker process (simulates a crash). Returns its id."""
        alive = self.alive_workers()
        if not alive:
            return None
        w = self.pool.get(wid) if wid else None
        if w is None or not w.alive:
            busy = [x for x in alive if x.inflight] or alive
            w = random.choice(busy)
        w.proc.kill()
        return w.wid

    def chaos(self, jobs: int = 1) -> None:
        """Kill one worker part-way through each of the next `jobs` jobs."""
        self._chaos_jobs += max(0, int(jobs))

    # ------------------------------------------------------------ scheduling
    def run_tasks(self, tasks: list) -> list[dict]:
        if not self.pool:
            self.start()
        self.job += 1
        job = self.job
        chunks = [tasks[i:i + self.chunk] for i in range(0, len(tasks), self.chunk)]
        ready = deque(range(len(chunks)))
        results: list = [None] * len(chunks)
        done = 0
        job_events: list[dict] = []
        start_stats = {w.wid: w.sims for w in self.pool.values()}
        chaos_at = None
        if self._chaos_jobs > 0 and len(chunks) >= 4:
            self._chaos_jobs -= 1
            chaos_at = max(1, len(chunks) // 3)
        t0 = time.perf_counter()

        def feed(w: _Worker) -> None:
            while w.alive and len(w.inflight) < PREFETCH and ready:
                cid = ready.popleft()
                try:
                    w.conn.send((job, cid, chunks[cid]))
                except (BrokenPipeError, OSError):
                    ready.appendleft(cid)
                    return
                w.inflight.append(cid)

        def died(w: _Worker) -> None:
            if not w.alive:
                return
            w.alive = False
            lost = [c for c in w.inflight if results[c] is None]
            for c in reversed(lost):
                ready.appendleft(c)          # re-queue at the front
            w.inflight.clear()
            self.failures += 1
            self._startup_deaths = self._startup_deaths + 1 if w.chunks == 0 else 0
            if self._startup_deaths > self.workers + 3:
                raise RuntimeError("worker processes keep dying before doing any work "
                                   "(check that the simulator imports correctly)")
            ev = {"type": "worker_died", "worker": w.wid, "requeued_chunks": len(lost),
                  "requeued_sims": sum(len(chunks[c]) for c in lost),
                  "t": round(time.perf_counter() - t0, 3)}
            if self.respawn:
                nw = self._spawn()
                ev["replacement"] = nw.wid
                start_stats[nw.wid] = 0
                feed(nw)
            job_events.append(ev)
            self.events.append(ev)
            self.on_event(ev)
            _log(f"[master] worker W{w.wid} died; re-queued {ev['requeued_sims']} sims"
                 + (f"; started W{ev['replacement']}" if "replacement" in ev else ""))

        for w in self.alive_workers():
            feed(w)
        while done < len(chunks):
            alive = self.alive_workers()
            if not alive:
                if not self.respawn:
                    raise RuntimeError("all workers died")
                feed(self._spawn())
                continue
            waitables = [w.conn for w in alive] + [w.proc.sentinel for w in alive]
            for obj in wait(waitables, timeout=1.0):
                w = next((x for x in alive if obj is x.conn or obj == x.proc.sentinel), None)
                if w is None or not w.alive:
                    continue
                if obj is w.conn:
                    try:
                        jb, cid, res, secs = w.conn.recv()
                    except (EOFError, OSError):
                        died(w)
                        continue
                    if cid in w.inflight:
                        w.inflight.remove(cid)
                    if jb == job and results[cid] is None:   # ignore duplicates after a re-queue
                        results[cid] = res
                        done += 1
                        w.sims += len(res)
                        w.chunks += 1
                        w.busy += secs
                        if chaos_at is not None and done >= chaos_at:
                            chaos_at = None
                            self.kill_worker()
                    feed(w)
                else:                         # sentinel ready -> process exited
                    died(w)
            # a dead worker's pipe may be readable before its sentinel; double-check
            for w in self.alive_workers():
                if not w.proc.is_alive():
                    died(w)
            for w in self.alive_workers():
                feed(w)
        elapsed = time.perf_counter() - t0
        per_worker = {f"W{wid}": w.sims - start_stats.get(wid, 0)
                      for wid, w in sorted(self.pool.items()) if w.sims - start_stats.get(wid, 0) > 0}
        self.last_job = {"job": job, "sims": len(tasks), "chunks": len(chunks), "seconds": round(elapsed, 4),
                         "sims_per_second": round(len(tasks) / elapsed, 1) if elapsed else 0.0,
                         "workers_alive": len(self.alive_workers()), "per_worker_sims": per_worker,
                         "events": job_events}
        return [r for chunk in results for r in chunk]

    # ------------------------------------------------------------ same API as ParallelRunner
    def evaluate(self, level_dict: dict, runs_per_persona: int = 200, base_seed: int = 0) -> dict:
        return self.evaluate_many([level_dict], runs_per_persona, base_seed)[0]

    def evaluate_many(self, level_dicts: list[dict], runs_per_persona: int = 200,
                      base_seed: int = 0) -> list[dict]:
        """All candidates in ONE sweep with common random numbers (same seeds)."""
        per = len(PERSONAS) * runs_per_persona
        tasks = [t for ld in level_dicts for t in make_tasks(ld, runs_per_persona, base_seed)]
        runs = self.run_tasks(tasks)
        out = []
        for i in range(len(level_dicts)):
            m = aggregate(runs[i * per:(i + 1) * per])
            m["workers"] = self.workers
            m["sweep_seconds"] = self.last_job["seconds"]
            m["sweep_sims_per_second"] = self.last_job["sims_per_second"]
            out.append(m)
        return out

    def status(self) -> dict:
        return {
            "workers_configured": self.workers,
            "workers": [{"id": f"W{w.wid}", "pid": w.proc.pid, "alive": w.alive and w.proc.is_alive(),
                         "sims_done": w.sims, "chunks_done": w.chunks, "busy_seconds": round(w.busy, 3)}
                        for w in self.pool.values()],
            "jobs_run": self.job, "worker_failures": self.failures, "chunk_size": self.chunk,
            "prefetch": PREFETCH, "last_job": self.last_job, "cpu_count": os.cpu_count(),
        }


if __name__ == "__main__":   # quick self-test: python -m levelforge.cluster
    from .generator import random_candidate
    lvl = random_candidate(4).to_dict()
    with SimCluster(5) as c:
        m = c.evaluate(lvl, 150, 1)
        print("completion", m["completion_rate"], c.last_job)
        c.chaos(1)
        m2 = c.evaluate(lvl, 150, 1)
        print("after a crash, same result:", m2["completion_rate"] == m["completion_rate"], c.last_job)
