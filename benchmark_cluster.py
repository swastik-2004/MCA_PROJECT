"""
Benchmark of the master-worker cluster (MCA part of the paper, second half).

1. Scaling   - throughput of the explicit master-worker cluster for 1..N workers
               (speedup vs. sequential, efficiency, Karp-Flatt serial fraction)
2. Faults    - the same job with 0, 1 and 2 worker crashes: extra time, and a check that the
               results are bit-for-bit identical (every task is seeded, lost work is re-run)
3. Protocols - if outputs_team/team_result.json exists: how much time the A2A messages and MCP
               calls add on top of the simulations themselves

    python benchmark_cluster.py                     # workers 1..min(cores, 12)
    python benchmark_cluster.py --max-workers 8 --repeats 3
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
import time
from pathlib import Path

from levelforge.cluster import SimCluster
from levelforge.generator import random_candidate
from levelforge.metrics import aggregate
from levelforge.parallel import _task, cpu_count, make_tasks

ROOT = Path(__file__).parent


def workload(n_levels: int, runs: int) -> list:
    tasks = []
    for i in range(n_levels):
        tasks += make_tasks(random_candidate(100 + i).to_dict(), runs, base_seed=i * 99991)
    return tasks


def run_cluster(tasks, workers: int, crashes: int = 0) -> tuple[float, list, dict]:
    with SimCluster(workers) as c:
        c.run_tasks(tasks[:workers * 8])          # warm-up: workers started and imported
        if crashes:
            c.chaos(crashes)
            # chaos() kills one worker per job; split into `crashes` sub-jobs so each loses a worker
            parts = [tasks[i::crashes] for i in range(crashes)]
            t0 = time.perf_counter()
            res = []
            for part in parts:
                res += c.run_tasks(part)
            dt = time.perf_counter() - t0
            # restore the original task order for the identity check
            out = [None] * len(tasks)
            k = 0
            for i, part in enumerate(parts):
                for j in range(len(part)):
                    out[i + j * crashes] = res[k]
                    k += 1
            return dt, out, c.status()
        t0 = time.perf_counter()
        res = c.run_tasks(tasks)
        return time.perf_counter() - t0, res, c.status()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-workers", type=int, default=max(5, min(cpu_count(), 12)))
    ap.add_argument("--levels", type=int, default=6)
    ap.add_argument("--runs", type=int, default=200)
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--out", default=str(ROOT / "outputs" / "benchmark_cluster"))
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    tasks = workload(args.levels, args.runs)
    ws = [w for w in sorted({1, 2, 3, 4, 5, args.max_workers} | set(range(1, args.max_workers + 1, 2)))
          if w <= args.max_workers]
    print(f"Workload: {len(tasks):,} playthroughs | {cpu_count()} logical cores | workers {ws}\n")

    t0 = time.perf_counter()
    for t in tasks:
        _task(t)
    seq = time.perf_counter() - t0
    print(f"  sequential            : {seq:6.2f}s  {len(tasks) / seq:7.0f} sims/s")
    rows = []
    for w in ws:
        best = min(run_cluster(tasks, w)[0] for _ in range(args.repeats))
        s = seq / best
        kf = (1 / s - 1 / w) / (1 - 1 / w) if w > 1 else None
        rows.append({"workers": w, "seconds": round(best, 3), "sims_per_s": round(len(tasks) / best),
                     "speedup": round(s, 2), "efficiency": round(s / w, 3),
                     "karp_flatt": round(kf, 3) if kf is not None else ""})
        print(f"  master-worker, {w:2d} workers: {best:6.2f}s  {len(tasks) / best:7.0f} sims/s  "
              f"speedup {s:5.2f}  efficiency {s / w:4.0%}" + (f"  e={kf:.3f}" if kf is not None else ""))

    # ---------------------------------------------------------------- fault tolerance
    w5 = min(5, args.max_workers)
    print(f"\nFault tolerance ({w5} workers):")
    base_t, base_res, _ = run_cluster(tasks, w5)
    base_m = aggregate(base_res)
    faults = []
    for crashes in (0, 1, 2):
        times = []
        same = True
        for _ in range(args.repeats):
            dt, res, st = run_cluster(tasks, w5, crashes)
            times.append(dt)
            same = same and aggregate(res) == base_m
        faults.append({"crashes": crashes, "seconds": round(min(times), 3), "identical_results": same})
        print(f"  {crashes} crash(es): {min(times):6.2f}s  results identical to the no-crash run: {same}")

    # ---------------------------------------------------------------- protocol overhead
    proto = {}
    tr = ROOT / "outputs_team" / "team_result.json"
    if tr.exists():
        res = json.loads(tr.read_text(encoding="utf-8"))
        trace = res["a2a_trace"]
        sim_s = sum(h["cluster_job"]["seconds"] for h in res["history"])
        play_ms = sum(t["ms"] for t in trace if t["skill"] == "playtest") / 1000
        other = [t["ms"] for t in trace if t["skill"] not in ("playtest",)]
        proto = {"a2a_messages": len(trace), "mcp_calls": sum(len(t["mcp"]) for t in trace),
                 "simulation_seconds": round(sim_s, 2), "playtest_call_seconds": round(play_ms, 2),
                 "protocol_overhead_per_playtest_ms": round((play_ms - sim_s) * 1000 / max(1, sum(
                     1 for t in trace if t["skill"] == "playtest"))),
                 "median_other_message_ms": statistics.median(other) if other else None,
                 "total_seconds": res["seconds"]}
        print(f"\nProtocols (from {tr.name}): {proto}")

    with open(out / "cluster_scaling.csv", "w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=list(rows[0]))
        wr.writeheader()
        wr.writerows(rows)
    (out / "summary.json").write_text(json.dumps({"sequential_seconds": round(seq, 3), "tasks": len(tasks),
                                                  "cores": cpu_count(), "scaling": rows, "faults": faults,
                                                  "protocols": proto}, indent=2), encoding="utf-8")
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, ax = plt.subplots(figsize=(6, 4))
        ax.plot(ws, ws, "--", color="#999", label="ideal")
        ax.plot([r["workers"] for r in rows], [r["speedup"] for r in rows], "o-", color="#7b3294",
                label="master-worker cluster")
        ax.set(xlabel="worker processes", ylabel="speedup vs sequential", title="Master-worker scaling")
        ax.grid(alpha=.3)
        ax.legend()
        fig.tight_layout()
        fig.savefig(out / "cluster_scaling.png", dpi=150)
    except ImportError:
        pass
    print(f"\nOutputs -> {out}")


if __name__ == "__main__":
    main()
