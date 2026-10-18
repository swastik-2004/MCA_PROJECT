"""
Multicore scaling benchmark (the MCA / HPC results for the paper).

Measures how simulation throughput scales with the number of worker processes:

    speedup     S(p) = T(1) / T(p)
    efficiency  E(p) = S(p) / p
    Karp-Flatt  e(p) = (1/S - 1/p) / (1 - 1/p)    experimentally determined serial fraction
    Amdahl fit  S(p) = 1 / (f + (1 - f) / p)      with f = mean Karp-Flatt value

Also compares chunk sizes to show inter-process communication overhead, and
reports process-pool start-up cost separately (it is large on Windows).

    python benchmark.py                    # workers 1..5 (+ all cores if more)
    python benchmark.py --max-workers 8 --runs 300 --repeats 3
"""
from __future__ import annotations

import argparse
import csv
import json
import statistics
import time
from multiprocessing import Pool
from pathlib import Path

from levelforge.generator import random_candidate
from levelforge.parallel import _task, auto_chunksize, cpu_count, make_tasks

ROOT = Path(__file__).parent


def workload(n_levels: int, runs: int) -> list:
    tasks = []
    for i in range(n_levels):
        tasks += make_tasks(random_candidate(100 + i).to_dict(), runs, base_seed=i * 99991)
    return tasks


def time_sequential(tasks) -> float:
    t0 = time.perf_counter()
    for t in tasks:
        _task(t)
    return time.perf_counter() - t0


def time_parallel(tasks, workers: int, chunksize: int | None = None) -> tuple[float, float]:
    """Returns (compute_seconds, pool_startup_seconds)."""
    t0 = time.perf_counter()
    with Pool(workers) as pool:
        pool.map(_task, tasks[:workers], chunksize=1)        # warm-up: workers start + import
        t1 = time.perf_counter()
        pool.map(_task, tasks, chunksize=chunksize or auto_chunksize(len(tasks), workers))
        t2 = time.perf_counter()
    return t2 - t1, t1 - t0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-workers", type=int, default=max(5, min(cpu_count(), 12)))
    ap.add_argument("--levels", type=int, default=6)
    ap.add_argument("--runs", type=int, default=200, help="playthroughs per bot type per level")
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--out", default=str(ROOT / "outputs" / "benchmark"))
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    tasks = workload(args.levels, args.runs)
    workers_list = sorted({1, 2, 3, 4, 5, args.max_workers} | set(range(1, args.max_workers + 1, 2)))
    workers_list = [w for w in workers_list if w <= args.max_workers]
    print(f"Workload: {len(tasks):,} independent playthroughs ({args.levels} levels x 3 bots x {args.runs})")
    print(f"Machine : {cpu_count()} logical cores | testing workers {workers_list} | {args.repeats} repeats each\n")

    rows = []
    seq = min(time_sequential(tasks) for _ in range(args.repeats))
    print(f"  sequential (no pool) : {seq:7.2f}s   {len(tasks) / seq:8.0f} sims/s")
    for w in workers_list:
        if w == 1:
            comp, start = seq, 0.0
        else:
            res = [time_parallel(tasks, w) for _ in range(args.repeats)]
            comp = min(r[0] for r in res)
            start = statistics.mean(r[1] for r in res)
        s = seq / comp
        e = s / w
        kf = (1 / s - 1 / w) / (1 - 1 / w) if w > 1 else 0.0
        rows.append({"workers": w, "seconds": round(comp, 4), "pool_startup_s": round(start, 4),
                     "sims_per_s": round(len(tasks) / comp, 1), "speedup": round(s, 3),
                     "efficiency": round(e, 3), "karp_flatt": round(kf, 4)})
        print(f"  {w:2d} worker(s)          : {comp:7.2f}s   {len(tasks) / comp:8.0f} sims/s   "
              f"speedup {s:5.2f}x   efficiency {e:5.0%}   serial fraction {kf:6.3f}   "
              f"(pool start {start:.2f}s)")

    # Only use runs with workers <= cores: beyond that the CPU is oversubscribed and
    # the Karp-Flatt metric measures contention rather than the serial fraction.
    kfs = [r["karp_flatt"] for r in rows if 1 < r["workers"] <= cpu_count()]
    if any(r["workers"] > cpu_count() for r in rows):
        print(f"\n  Note: runs with more workers than the {cpu_count()} cores are oversubscribed; "
              "excluded from the Amdahl fit.")
    f = max(0.0, statistics.mean(kfs)) if kfs else 0.0
    print(f"\n  Amdahl serial fraction estimate f = {f:.3f}  ->  max theoretical speedup ~ "
          f"{(1 / f if f > 0 else float('inf')):.1f}x")

    # chunksize experiment at 5 workers (or max)
    cw = min(5, args.max_workers)
    chunk_rows = []
    if cw > 1:
        print(f"\n  Chunk size experiment ({cw} workers):")
        sizes = sorted({1, auto_chunksize(len(tasks), cw), 8, 32, max(1, len(tasks) // (4 * cw)),
                        max(1, len(tasks) // cw)})
        for cs in sizes:
            t = min(time_parallel(tasks, cw, cs)[0] for _ in range(args.repeats))
            chunk_rows.append({"chunksize": cs, "seconds": round(t, 4), "sims_per_s": round(len(tasks) / t, 1)})
            tag = "  <- default" if cs == auto_chunksize(len(tasks), cw) else ""
            print(f"    chunksize {cs:5d}: {t:6.2f}s  {len(tasks) / t:8.0f} sims/s{tag}")

    with open(out / "scaling.csv", "w", newline="", encoding="utf-8") as fh:
        wr = csv.DictWriter(fh, fieldnames=list(rows[0]))
        wr.writeheader()
        wr.writerows(rows)
    (out / "benchmark.json").write_text(json.dumps({
        "tasks": len(tasks), "cores": cpu_count(), "sequential_s": seq, "scaling": rows,
        "amdahl_serial_fraction": f, "chunksize": chunk_rows}, indent=2), encoding="utf-8")

    try:
        plot(rows, chunk_rows, f, out)
        print(f"\n  Charts -> {out}")
    except ImportError:
        print("\n  (install matplotlib to get charts)")
    print(f"  Data   -> {out / 'scaling.csv'}")


def plot(rows, chunk_rows, f, out: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    ws = [r["workers"] for r in rows]
    sp = [r["speedup"] for r in rows]
    ef = [r["efficiency"] for r in rows]
    fig, ax = plt.subplots(1, 3, figsize=(15, 4.4))
    ax[0].plot(ws, ws, "--", color="#999", label="ideal (linear)")
    grid = [x / 4 for x in range(4, 4 * max(ws) + 1)]
    ax[0].plot(grid, [1 / (f + (1 - f) / p) for p in grid], ":", color="#d95f02", label=f"Amdahl fit (f={f:.3f})")
    ax[0].plot(ws, sp, "o-", color="#1b6ca8", lw=2, label="measured")
    ax[0].set(xlabel="worker processes", ylabel="speedup", title="Speedup vs workers")
    ax[0].legend()
    ax[1].bar([str(w) for w in ws], [e * 100 for e in ef], color="#1b6ca8")
    ax[1].set(xlabel="worker processes", ylabel="efficiency (%)", title="Parallel efficiency", ylim=(0, 110))
    ax[2].plot(ws, [r["sims_per_s"] for r in rows], "o-", color="#1b9e77", lw=2)
    ax[2].set(xlabel="worker processes", ylabel="simulations / second", title="Throughput")
    for a in ax:
        a.grid(alpha=0.3)
    fig.tight_layout()
    fig.savefig(out / "scaling.png", dpi=150)
    plt.close(fig)

    if chunk_rows:
        fig, a = plt.subplots(figsize=(6, 4))
        a.bar([str(r["chunksize"]) for r in chunk_rows], [r["sims_per_s"] for r in chunk_rows], color="#7570b3")
        a.set(xlabel="chunk size (tasks per message)", ylabel="simulations / second",
              title="Effect of chunk size (IPC overhead)")
        a.grid(alpha=0.3, axis="y")
        fig.tight_layout()
        fig.savefig(out / "chunksize.png", dpi=150)
        plt.close(fig)


if __name__ == "__main__":
    main()
