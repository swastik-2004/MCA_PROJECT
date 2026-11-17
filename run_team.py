"""
LevelForge multi-agent team: A2A agents + MCP tools + master-worker simulation cluster.

    python run_team.py --level data/problem_level.txt            # fix the problem level
    python run_team.py --start llm                               # the LLM designs a level first
    python run_team.py --level data/problem_level.txt --chaos    # crash a simulation worker mid-run
    python run_team.py --offline ...                             # rule-based agents, no API calls

What starts (all on this laptop, 127.0.0.1):
    MCP server  levelforge-twin      :9150   digital-twin tools + master-worker cluster (5 workers)
    A2A agents  Director (master)    :9100   delegates every step to the workers below
                Review Analyst       :9101   Level Architect   :9102   Playtest Analyst  :9103
                Difficulty Spec.     :9104   Layout Spec.      :9105   Reward Spec.      :9106
                QA Validator         :9107   Reporter          :9108

Outputs go to outputs_team/ (report.html with the agent trace, logs/, team_result.json) and
the 3D game (breach.html) is rebuilt as usual.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).parent


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--level", help="existing level to optimise (.txt grid or .json)")
    ap.add_argument("--start", choices=["auto", "llm", "procedural"], default="auto",
                    help="when no --level is given: LLM-designed (auto/llm) or procedural first level")
    ap.add_argument("--rounds", type=int, default=6)
    ap.add_argument("--candidates", type=int, default=4, help="candidate plans per round (shared by specialists)")
    ap.add_argument("--runs", type=int, default=150, help="playthroughs per bot type per candidate")
    ap.add_argument("--seed", type=int, default=4)
    ap.add_argument("--workers", type=int, default=5, help="simulation worker processes")
    ap.add_argument("--reviews", default=str(ROOT / "data" / "sample_reviews_synthetic.csv"))
    ap.add_argument("--review-limit", type=int, default=400)
    ap.add_argument("--offline", action="store_true", help="rule-based agents, no API calls")
    ap.add_argument("--chaos", nargs="?", type=int, const=2, default=None, metavar="ROUND",
                    help="crash one simulation worker during round ROUND (default 2) to show fault tolerance")
    ap.add_argument("--base-port", type=int, default=9100)
    ap.add_argument("--mcp-port", type=int, default=9150)
    ap.add_argument("--out", default=str(ROOT / "outputs_team"))
    ap.add_argument("--no-open", action="store_true")
    args = ap.parse_args()

    sys.path.insert(0, str(ROOT))
    from levelforge.level import Level, validate
    from levelforge.team.agents import ROSTER
    from levelforge.team.director import C, enable_ansi
    enable_ansi()

    out = Path(args.out)
    (out / "logs").mkdir(parents=True, exist_ok=True)
    mode, grid, level_name = args.start, None, None
    if args.level:
        if not Path(args.level).is_file():
            raise SystemExit(f"Level file not found: {args.level}")
        lvl = Level.load(args.level)
        if validate(lvl):
            raise SystemExit(f"Level file {args.level} is not playable: " + "; ".join(validate(lvl)))
        mode, grid, level_name = "file", lvl.grid, lvl.name

    from levelforge.llm import LLM
    from levelforge.team.runtime import TeamRuntime
    llm = LLM(provider="offline") if args.offline else LLM()
    bar = "=" * 78
    print(f"\n{bar}\n  LevelForge agent team | A2A agents + MCP tools + master-worker cluster\n{bar}")
    print(f"  Agents' LLM : {llm.describe()}")
    print(f"  MCP server  : levelforge-twin at http://127.0.0.1:{args.mcp_port}/mcp  "
          f"({args.workers} simulation workers)")
    print(f"  A2A agents  : {len(ROSTER)} servers on ports {args.base_port}-{args.base_port + len(ROSTER) - 1}")
    print(f"  Budget      : {args.rounds} rounds x {args.candidates} candidates x {args.runs * 3} playthroughs"
          + (f"   | fault injection in round {args.chaos}" if args.chaos else ""))
    print(f"\n  starting {len(ROSTER) + 1} servers + {args.workers} simulation workers ...", end="", flush=True)
    team = TeamRuntime(args.workers, args.offline, args.base_port, args.mcp_port, out / "logs")
    try:
        team.start()
    except RuntimeError as e:
        raise SystemExit(f"\n  {e}")
    try:
        print(f" ready in {team.startup_seconds:.1f}s")
        job = {"reviews_path": args.reviews, "review_limit": args.review_limit, "mode": mode, "grid": grid,
               "level_name": level_name, "rounds": args.rounds, "candidates": args.candidates,
               "runs": args.runs, "seed": args.seed, "chaos_round": args.chaos}
        result = team.optimise(job)
        stats = team.cluster_status()
    finally:
        team.stop()

    write_outputs(out, result, stats, args, llm)


def write_outputs(out: Path, res: dict, stats: dict, args, llm) -> None:
    from levelforge import simulator
    from levelforge.arcade import build_arcade
    from levelforge.level import Level
    from levelforge.report import build_report
    from levelforge.reviews import TAXONOMY
    from levelforge.team.director import C

    history = res["history"]
    initial = Level.from_dict(res["initial_level"])
    final = Level.from_dict(res["final_level"])
    final.name = "optimised"

    def traces(level):
        outp = {}
        for p in simulator.PERSONAS:
            r = simulator.Simulation(level, p, 7, record=True).run()
            outp[p] = {"trace": r.trace, "result": "reached the exit" if r.completed else
                       "died" if r.died else "ran out of steps"}
        return outp

    total_sims = sum(h["sims"] for h in history)
    sim_seconds = sum(h["sweep_seconds"] for h in history)
    failures = sum(len(h["cluster_job"].get("events", [])) for h in history)
    report = {
        "llm": llm.describe() + " · A2A agent team", "workers": args.workers,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M"), "brief": res["brief"],
        "problem_names": {k: v[0] for k, v in TAXONOMY.items()}, "history": history, "log": res["log"],
        "initial_level": initial.to_dict(), "final_level": final.to_dict(),
        "traces": {"initial": traces(initial), "final": traces(final)},
        "designer_notes": res["designer_notes"], "total_sims": total_sims, "sim_seconds": sim_seconds,
        "rules": {k: getattr(simulator, k) for k in ("START_HP", "MAX_HP", "MONSTER_HP", "MONSTER_HIT_CHANCE",
                                                     "TRAP_TRIGGER_CHANCE", "TRAP_DAMAGE", "LUNGE_CHANCE",
                                                     "POTION_HEAL")},
        "team": {"agents": res["agents"], "a2a_trace": res["a2a_trace"], "cluster": stats,
                 "worker_failures": failures, "seconds": res["seconds"]},
    }
    (out / "report.html").write_text(build_report(report), encoding="utf-8")
    (out / "arcade.html").write_text(build_arcade(report), encoding="utf-8")
    (out / "team_result.json").write_text(json.dumps(res, indent=1), encoding="utf-8")
    (out / "agent_log.txt").write_text("\n".join(res["log"]), encoding="utf-8")
    (out / "history.json").write_text(json.dumps(history, indent=1), encoding="utf-8")
    initial.save(out / "initial_level.json")
    final.save(out / "final_level.json")

    n_msgs = len(res["a2a_trace"])
    n_mcp = sum(len(t["mcp"]) for t in res["a2a_trace"])
    by_agent: dict[str, int] = {}
    for h in history[1:]:
        if h.get("accepted_agent"):
            by_agent[h["accepted_agent"]] = by_agent.get(h["accepted_agent"], 0) + 1
    bar = "=" * 78
    print(f"\n{bar}\n  Result\n{bar}")
    print(f"  Quality score   : {history[0]['best_score']:.3f} -> {C['b']}{history[-1]['best_score']:.3f}{C['x']}"
          f"   (completion {history[0]['best_metrics']['completion_rate']:.0%} -> "
          f"{history[-1]['best_metrics']['completion_rate']:.0%}, target {res['brief']['target_completion']:.0%})")
    print(f"  Accepted plans  : " + (", ".join(f"{a} x{n}" for a, n in by_agent.items()) or "none"))
    print(f"  A2A messages    : {n_msgs} between {len(res['agents']) + 1} agents;  MCP tool calls: {n_mcp}")
    print(f"  Simulations     : {total_sims:,} playthroughs in {sim_seconds:.1f}s on {args.workers} workers"
          f" (master-worker); worker crashes survived: {failures}")
    print(f"  Total time      : {res['seconds']:.0f}s")
    print(f"\n  Report  -> {out / 'report.html'}")
    print(f"  Logs    -> {out / 'logs'}")
    try:
        from levelforge.shooter import build_game, find_runs
        runs = find_runs(ROOT)
        game = ROOT / "breach.html"
        game.write_text(build_game(runs), encoding="utf-8")
        print(f"  Game    -> {game}   (python play.py)")
    except Exception as e:
        print(f"  (game not rebuilt: {e})")
    if not args.no_open:
        import webbrowser
        webbrowser.open((out / "report.html").resolve().as_uri())


if __name__ == "__main__":
    main()
