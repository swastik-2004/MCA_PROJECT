"""
Research experiment: does critic-guided agentic optimisation beat a fair baseline?

For each of N starting levels (different seeds) we compare:

    raw          the initial procedural level, no optimisation
    random       random search: same rounds, candidates and simulations, random edits
    rule_agent   critic -> optimizer loop with rule-based reasoning
    llm_agent    the same loop with LLM reasoning (only when an API key is configured)

All methods start from the SAME level and get exactly the same simulation budget and
accept/reject rule, so any difference comes from HOW edits are chosen.

    python experiments.py                       # 8 levels; adds the LLM agent if a key is set
    python experiments.py --levels 4 --offline  # rules only, no API calls
    python experiments.py --methods random,rule_agent
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import random
import statistics
import time
from pathlib import Path

from levelforge.agents import AgentSystem, LoopState
from levelforge.edits import apply_edits
from levelforge.level import Level
from levelforge.llm import LLM
from levelforge.parallel import DEFAULT_WORKERS, ParallelRunner
from levelforge.reviews import build_brief, label_reviews, load_reviews

ROOT = Path(__file__).parent
TILES = ["M", "T", "H", "C"]


def random_plan(rng: random.Random) -> dict:
    edits = []
    for _ in range(rng.randint(1, 2)):
        kind = rng.choice(["add", "remove", "add", "remove", "add_loop", "remove_lock"])
        if kind in ("add", "remove"):
            edits.append({"op": kind, "tile": rng.choice(TILES), "count": rng.randint(1, 2),
                          "where": rng.choice(["main", "side", "any"])})
        else:
            edits.append({"op": kind})
    return {"rationale": "random: " + json.dumps(edits), "edits": edits}


class RandomSearch(AgentSystem):
    """Same loop and budget as the agent, but no critic and random edits."""

    def critic(self, state: LoopState) -> LoopState:
        state["critique"] = {"diagnosis": [], "priority": "random"}
        return state

    def optimizer(self, state: LoopState) -> LoopState:
        rng = random.Random(self.seed * 7777 + state["round"])
        level = Level.from_dict(state["best"]["level"])
        state["round"] += 1
        cands = []
        attempts = 0
        while len(cands) < self.k and attempts < self.k * 5:
            attempts += 1
            p = random_plan(rng)
            new, log = apply_edits(level, p["edits"], seed=rng.randint(0, 10 ** 6))
            if any(x.startswith("applied") for x in log):
                cands.append({"level": new.to_dict(), "plan": p["rationale"], "edit_log": log})
        state["candidates"] = cands or [{"level": level.to_dict(), "plan": "no-op", "edit_log": []}]
        return state

    def finalize(self, state: LoopState) -> LoopState:
        state["designer_notes"] = ""
        return state


def sign_test_p(wins: int, losses: int) -> float:
    """Two-sided exact sign test."""
    n = wins + losses
    if n == 0:
        return 1.0
    k = min(wins, losses)
    p = sum(math.comb(n, i) for i in range(0, k + 1)) / 2 ** n
    return min(1.0, 2 * p)


def wilcoxon_p(diffs: list[float]) -> float:
    """Exact two-sided Wilcoxon signed-rank test (pure Python, fine for n <= 20).
    Unlike the sign test, it uses how large each paired difference is, not only its sign."""
    d = [x for x in diffs if abs(x) > 1e-12]
    n = len(d)
    if n == 0:
        return 1.0
    order = sorted(range(n), key=lambda i: abs(d[i]))
    ranks = [0.0] * n
    i = 0
    while i < n:  # average ranks for ties
        j = i
        while j + 1 < n and abs(abs(d[order[j + 1]]) - abs(d[order[i]])) < 1e-12:
            j += 1
        for k in range(i, j + 1):
            ranks[order[k]] = (i + j) / 2 + 1
        i = j + 1
    w_plus = sum(r for r, x in zip(ranks, d) if x > 0)
    total = sum(ranks)
    if n > 20:  # normal approximation
        mu, sd = total / 2, (n * (n + 1) * (2 * n + 1) / 24) ** 0.5
        z = abs(w_plus - mu) / sd
        return min(1.0, math.erfc(z / 2 ** 0.5))
    dist = {0.0: 1}
    for r in ranks:  # exact null distribution of W+
        new = dict(dist)
        for w, c in dist.items():
            new[w + r] = new.get(w + r, 0) + c
        dist = new
    obs = min(w_plus, total - w_plus)
    tail = sum(c for w, c in dist.items() if w <= obs + 1e-9) / 2 ** n
    return min(1.0, 2 * tail)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--levels", type=int, default=8)
    ap.add_argument("--rounds", type=int, default=6)
    ap.add_argument("--candidates", type=int, default=4)
    ap.add_argument("--runs", type=int, default=100)
    ap.add_argument("--workers", type=int, default=DEFAULT_WORKERS)
    ap.add_argument("--reviews", default=str(ROOT / "data" / "sample_reviews_synthetic.csv"))
    ap.add_argument("--offline", action="store_true", help="skip the LLM agent")
    ap.add_argument("--methods", default="", help="comma list from random,rule_agent,llm_agent")
    ap.add_argument("--out", default=str(ROOT / "outputs" / "experiments"))
    args = ap.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    llm = LLM(provider="offline") if args.offline else LLM()
    rules = LLM(provider="offline")
    methods = [m for m in (args.methods.split(",") if args.methods else
                           ["random", "rule_agent"] + (["llm_agent"] if llm.online else [])) if m]
    if "llm_agent" in methods and not llm.online:
        print("No API key: dropping llm_agent")
        methods.remove("llm_agent")
    # Same design brief for every method (labelled once, by the LLM if available).
    brief = build_brief(label_reviews(load_reviews(args.reviews), llm))
    print(f"Methods: {methods} | LLM: {llm.describe()} | {args.workers} workers | {args.levels} levels x "
          f"{args.rounds} rounds x {args.candidates} candidates x {args.runs * 3} sims\n")

    factories = {
        "random": lambda r, seed: RandomSearch(r, rules, args.runs, args.candidates, seed, False, "procedural"),
        "rule_agent": lambda r, seed: AgentSystem(r, rules, args.runs, args.candidates, seed, False, "procedural"),
        "llm_agent": lambda r, seed: AgentSystem(r, llm, args.runs, args.candidates, seed, False, "procedural"),
    }
    rows, curves = [], {m: [] for m in methods}
    t0 = time.perf_counter()
    with ParallelRunner(args.workers) as runner:
        for seed in range(args.levels):
            row = {"level_seed": seed}
            for m in methods:
                h = factories[m](runner, seed).run(brief, max_rounds=args.rounds)["history"]
                curves[m].append([r["best_score"] for r in h])
                row["raw"] = h[0]["best_score"]
                row["raw_completion"] = round(h[0]["best_metrics"]["completion_rate"], 3)
                row[m] = h[-1]["best_score"]
                row[f"{m}_completion"] = round(h[-1]["best_metrics"]["completion_rate"], 3)
            rows.append(row)
            print(f"  level {seed}: raw {row['raw']:.3f} | " +
                  " | ".join(f"{m} {row[m]:.3f}" for m in methods), flush=True)
    elapsed = time.perf_counter() - t0

    def ms(key):
        v = [r[key] for r in rows]
        return statistics.mean(v), (statistics.stdev(v) if len(v) > 1 else 0.0)

    pairs = []
    for a, b in (("rule_agent", "random"), ("llm_agent", "random"), ("llm_agent", "rule_agent")):
        if a in methods and b in methods:
            w = sum(r[a] > r[b] + 1e-9 for r in rows)
            lo = sum(r[a] < r[b] - 1e-9 for r in rows)
            pairs.append({"a": a, "b": b, "wins": w, "losses": lo,
                          "mean_diff": statistics.mean(r[a] - r[b] for r in rows),
                          "sign_test_p": sign_test_p(w, lo),
                          "wilcoxon_p": wilcoxon_p([r[a] - r[b] for r in rows])})
    summary = {"levels": len(rows), "rounds": args.rounds, "candidates": args.candidates,
               "sims_per_candidate": args.runs * 3, "llm": llm.describe(), "llm_calls": llm.calls,
               "seconds": round(elapsed, 1), "target_completion": brief["target_completion"],
               "raw": ms("raw"), **{m: ms(m) for m in methods}, "comparisons": pairs}

    with open(out / "results.csv", "w", newline="", encoding="utf-8") as fh:
        wr = csv.DictWriter(fh, fieldnames=list(rows[0]))
        wr.writeheader()
        wr.writerows(rows)
    (out / "summary.json").write_text(json.dumps({"summary": summary, "rows": rows, "curves": curves},
                                                 indent=2), encoding="utf-8")
    labels = {"raw": "No optimisation (raw)", "random": "Random search (same budget)",
              "rule_agent": "Agent loop, rule-based reasoning", "llm_agent": f"Agent loop, LLM reasoning ({llm.model})"}
    table = ["| Method | Mean quality | Std | Mean completion |", "|---|---|---|---|",
             f"| {labels['raw']} | {summary['raw'][0]:.3f} | {summary['raw'][1]:.3f} | {ms('raw_completion')[0]:.0%} |"]
    for m in methods:
        table.append(f"| {labels[m]} | {summary[m][0]:.3f} | {summary[m][1]:.3f} | {ms(m + '_completion')[0]:.0%} |")
    table.append("")
    for p in pairs:
        table.append(f"{p['a']} vs {p['b']}: wins {p['wins']}/{len(rows)}, losses {p['losses']}, "
                     f"mean diff {p['mean_diff']:+.3f}, Wilcoxon signed-rank p = {p['wilcoxon_p']:.3f} "
                     f"(sign test p = {p['sign_test_p']:.3f})")
    table.append(f"Target completion from reviews: {brief['target_completion']:.0%}. All methods start from the same "
                 f"procedural level; budget {args.rounds} rounds x {args.candidates} candidates x {args.runs * 3} playthroughs.")
    (out / "results_table.md").write_text("\n".join(table) + "\n", encoding="utf-8")
    print("\n" + "\n".join(table))

    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        colors = {"raw": "#999999", "random": "#d95f02", "rule_agent": "#1b6ca8", "llm_agent": "#1b9e77"}
        short = {"raw": "No optimisation", "random": "Random search", "rule_agent": "Rule agent", "llm_agent": "LLM agent"}
        names = ["raw"] + methods
        fig, ax = plt.subplots(1, 2, figsize=(12, 4.4))
        ax[0].bar([short[n] for n in names], [summary[n][0] for n in names], yerr=[summary[n][1] for n in names],
                  color=[colors[n] for n in names], capsize=6)
        ax[0].set(ylabel="quality score", title=f"Final quality ({len(rows)} levels, mean \u00b1 sd)", ylim=(0, 1))
        for m in methods:
            c = curves[m]
            n = min(len(x) for x in c)
            ax[1].plot(range(n), [statistics.mean(x[i] for x in c) for i in range(n)], "o-",
                       color=colors[m], lw=2, label=short[m])
        ax[1].set(xlabel="optimisation round", ylabel="best quality so far (mean)", title="Convergence")
        ax[1].legend()
        for a in ax:
            a.grid(alpha=0.3)
        fig.tight_layout()
        fig.savefig(out / "comparison.png", dpi=150)
        plt.close(fig)
    except ImportError:
        pass
    print(f"\nOutputs -> {out}  ({elapsed:.0f}s, LLM calls: {llm.calls})")


if __name__ == "__main__":
    main()
