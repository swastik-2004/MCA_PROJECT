"""
LevelForge demo: reviews -> design brief -> agentic optimisation loop with
parallel simulation -> HTML report with replays and a playable final level.

    python run_demo.py                       # 5 workers, offline if no API key
    python run_demo.py --workers 5 --rounds 6
    python run_demo.py --reviews data/steam_reviews.csv --review-limit 400
    python run_demo.py --level data/problem_level.txt   # optimise an existing level

Set GROQ_API_KEY (or GEMINI_API_KEY) to switch the agents from rule-based to LLM-driven.
"""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime
from pathlib import Path

from levelforge import simulator
from levelforge.agents import AgentSystem
from levelforge.level import Level
from levelforge.llm import LLM
from levelforge.parallel import DEFAULT_WORKERS, ParallelRunner, cpu_count
from levelforge.arcade import build_arcade
from levelforge.report import build_report
from levelforge.reviews import TAXONOMY, build_brief, label_reviews, load_reviews

ROOT = Path(__file__).parent


def banner(text: str) -> None:
    print("\n" + "=" * 78 + f"\n  {text}\n" + "=" * 78, flush=True)


def record_traces(level: Level, seed: int = 7) -> dict:
    out = {}
    for p in simulator.PERSONAS:
        res = simulator.Simulation(level, p, seed, record=True).run()
        outcome = "reached the exit" if res.completed else "died" if res.died else "ran out of steps"
        out[p] = {"trace": res.trace, "result": outcome}
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--workers", type=int, default=DEFAULT_WORKERS, help="parallel worker processes (default 5)")
    ap.add_argument("--rounds", type=int, default=6, help="optimisation rounds")
    ap.add_argument("--runs", type=int, default=150, help="playthroughs per bot type per candidate")
    ap.add_argument("--candidates", type=int, default=4, help="candidate edit plans per round")
    ap.add_argument("--seed", type=int, default=4)
    ap.add_argument("--reviews", default=str(ROOT / "data" / "sample_reviews_synthetic.csv"))
    ap.add_argument("--review-limit", type=int, default=400)
    ap.add_argument("--offline", action="store_true", help="ignore API keys, use rule-based agents")
    ap.add_argument("--start", choices=["auto", "llm", "procedural"], default="auto",
                    help="first level: LLM-written (auto/llm) or the procedural one. Use 'procedural' to "
                         "compare rule vs LLM agents from the same starting level")
    ap.add_argument("--level", help="optimise an existing level instead of generating one "
                    "(.txt grid or .json), e.g. data/problem_level.txt")
    ap.add_argument("--out", default=str(ROOT / "outputs"))
    ap.add_argument("--no-open", action="store_true", help="do not pop open the game window at the end")
    args = ap.parse_args()

    start_level = None
    if args.level:
        from levelforge.level import validate
        if not Path(args.level).is_file():
            raise SystemExit(f"Level file not found: {args.level}")
        start_level = Level.load(args.level)
        errs = validate(start_level)
        if errs:
            raise SystemExit(f"Level file {args.level} is not playable: " + "; ".join(errs))

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    llm = LLM(provider="offline") if args.offline else LLM()
    t_start = time.perf_counter()

    banner("LevelForge | Agentic Digital Twin for Game-Level Optimisation")
    print(f"  Agents      : {llm.describe()}")
    if not llm.online and not args.offline:
        print("                (no API key found: put GROQ_API_KEY=... in the .env file to enable the LLM)")
    print(f"  Parallelism : {args.workers} worker processes (this machine has {cpu_count()} logical cores)")
    if start_level is not None:
        print(f"  Start level : {args.level} (existing level, will be optimised)")
    print(f"  Budget      : {args.rounds} rounds x {args.candidates} candidates x {args.runs * 3} playthroughs")

    # ---------------------------------------------------------------- stage 1
    banner("Stage 1 | GenAI review mining -> design brief")
    reviews = load_reviews(args.reviews, args.review_limit)
    labeled = label_reviews(reviews, llm)
    brief = build_brief(labeled)
    print(f"  {len(reviews)} reviews from {Path(args.reviews).name} "
          f"(labelled by {'LLM' if any(r['labeler'] == 'llm' for r in labeled) else 'keyword rules'})")
    for k, v in sorted(brief["problem_share"].items(), key=lambda kv: -kv[1]):
        print(f"    {TAXONOMY[k][0]:<36} {'#' * int(v * 50):<25} {v:5.0%}")
    print(f"  -> target completion {brief['target_completion']:.0%}, "
          f"target HP lost {brief['target_tension']:.0%}, weights {brief['weights']}")
    (out / "review_labels.json").write_text(json.dumps(labeled, indent=2), encoding="utf-8")
    (out / "design_brief.json").write_text(json.dumps(brief, indent=2), encoding="utf-8")

    # ---------------------------------------------------------------- stage 2
    banner(f"Stage 2 | Agent loop (LangGraph) with {args.workers} parallel simulators")
    with ParallelRunner(args.workers) as runner:
        system = AgentSystem(runner, llm, runs_per_persona=args.runs,
                             candidates_per_round=args.candidates, seed=args.seed,
                             start=args.start, start_level=start_level)
        t0 = time.perf_counter()
        state = system.run(brief, max_rounds=args.rounds)
        loop_seconds = time.perf_counter() - t0

    history = state["history"]
    initial = Level.from_dict(history[0]["best_level"])
    final = Level.from_dict(state["best"]["level"])
    final.name = "optimised"
    total_sims = sum(h["sims"] for h in history)
    sim_seconds = sum(h["sweep_seconds"] for h in history)

    # ---------------------------------------------------------------- stage 3
    banner("Stage 3 | Outputs")
    initial.save(out / "initial_level.json")
    final.save(out / "final_level.json")
    (out / "history.json").write_text(json.dumps(history, indent=2), encoding="utf-8")
    (out / "agent_log.txt").write_text("\n".join(state["log"]), encoding="utf-8")
    report = {
        "llm": llm.describe(), "workers": args.workers,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "brief": brief, "problem_names": {k: v[0] for k, v in TAXONOMY.items()},
        "history": history, "log": state["log"],
        "initial_level": initial.to_dict(), "final_level": final.to_dict(),
        "traces": {"initial": record_traces(initial), "final": record_traces(final)},
        "designer_notes": state["designer_notes"],
        "total_sims": total_sims, "sim_seconds": sim_seconds,
        "rules": {k: getattr(simulator, k) for k in ("START_HP", "MAX_HP", "MONSTER_HP", "MONSTER_HIT_CHANCE",
                                                     "TRAP_TRIGGER_CHANCE", "TRAP_DAMAGE", "LUNGE_CHANCE",
                                                     "POTION_HEAL")},
    }
    (out / "report.html").write_text(build_report(report), encoding="utf-8")
    (out / "arcade.html").write_text(build_arcade(report), encoding="utf-8")

    print("  Initial level:".ljust(40) + "Optimised level:")
    for a, b in zip(initial.grid, final.grid):
        print(f"  {a:<38}{b}")
    print(f"\n  Quality score : {history[0]['best_score']:.3f} -> {history[-1]['best_score']:.3f}")
    print(f"  Simulations   : {total_sims:,} playthroughs in {sim_seconds:.1f}s "
          f"({total_sims / sim_seconds:,.0f}/s on {args.workers} workers)")
    print(f"  Agent loop    : {loop_seconds:.1f}s total, LLM calls: {llm.calls}, rate-limit waits: {llm.rate_limit_waits}, failed steps: {llm.failures}")
    if llm.disabled_reason:
        print(f"  WARNING       : LLM was disabled during the run ({llm.disabled_reason[:90]}).")
        print("                  Agents used rule-based fallbacks. Test the connection: python -m levelforge.llm")
    print(f"  Designer notes: {state['designer_notes']}")
    print(f"\n  Report  -> {out / 'report.html'}")
    print(f"  Arcade  -> {out / 'arcade.html'}   (reopen any time: python play.py --arcade)")
    print(f"  All outputs in {out}   (total {time.perf_counter() - t_start:.1f}s)")
    try:  # rebuild the shooter game from all runs (this one included) and open it
        from levelforge.shooter import build_game, find_runs
        runs = find_runs(ROOT)
        if not any(name == out.name for name, _ in runs):
            runs.append((out.name, report))
        game = ROOT / "breach.html"
        game.write_text(build_game(runs), encoding="utf-8")
        print(f"  Game    -> {game}   (reopen any time: python play.py)")
        if not args.no_open:
            import webbrowser
            webbrowser.open(game.resolve().as_uri())
    except Exception as e:  # the game is optional; never fail the run because of it
        print(f"  (game not built: {e})")


if __name__ == "__main__":
    main()
