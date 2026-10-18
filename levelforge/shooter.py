"""
LevelForge: Breach - a real-time shooter built on the levels the agents produced.
Default: first-person 3D (Three.js). Also available: the top-down 2D version (mode="2d").

The game is the "real" game; the simulator in simulator.py is its digital twin: a simplified,
turn-based model of it. Both use the same level grids and the same values (player health,
drone health, mine damage, med-kit healing), read from the run data.

Levels (from your runs):
    1  BEFORE AI     - the generated level before optimisation   (rule-based run, initial)
    2  AI-OPTIMISED  - the same level after the agents fixed it    (rule-based run, final)
    3  AI-DESIGNED   - the level an LLM designed, then optimised    (LLM run, final)
"""
from __future__ import annotations

import json
from pathlib import Path

from .arcade import data_from_report

HERE = Path(__file__).parent
TEMPLATE_2D = HERE / "breach_template.html"
TEMPLATE_3D = HERE / "breach3d_template.html"
BUNDLE_3D = HERE / "vendor" / "breach3d.bundle.js"   # Three.js r186 + game code, prebuilt with esbuild


def find_runs(root: Path) -> list[tuple[str, dict]]:
    """All runs (folder name, run data) under root/outputs*/report.html, newest first."""
    reports = sorted(root.glob("outputs*/report.html"), key=lambda p: p.stat().st_mtime, reverse=True)
    runs = []
    for rep in reports:
        try:
            runs.append((rep.parent.name, data_from_report(rep)))
        except (ValueError, json.JSONDecodeError):
            continue
    return runs


def _is_rules(run: dict) -> bool:
    return str(run.get("llm", "")).startswith("offline")


def _llm_designed(run: dict) -> bool:
    return any(line.startswith("[Generator] LLM") and "wrote" in line for line in run.get("log", []))


def pick_runs(runs: list[tuple[str, dict]]):
    """Choose the rule-based run and the LLM-designed run (preferring the default folder names)."""
    def choose(cands, preferred):
        for name, r in cands:
            if name == preferred:
                return name, r
        return cands[0] if cands else None
    rules = choose([x for x in runs if _is_rules(x[1])], "outputs")
    llm = choose([x for x in runs if not _is_rules(x[1]) and _llm_designed(x[1])], "outputs_llm")
    return rules, llm


def _level(title: str, source: str, level: dict, hist_entry: dict) -> dict:
    m = hist_entry["best_metrics"]
    return {"title": title, "source": source, "grid": level["grid"], "quality": hist_entry["best_score"],
            "completion": m["completion_rate"], "persona": m["per_persona_completion"],
            "damage": m.get("avg_damage", 0.0)}


def _lab_run(label: str, run: dict) -> dict:
    hist = [{k: v for k, v in h.items() if k not in ("best_level",)} for h in run["history"]]
    for h in hist:  # drop candidate grids to keep the file small
        h["candidates"] = [{"plan": c["plan"], "quality": c["quality"]} for c in h["candidates"]]
    return {"label": label, "llm": run["llm"], "workers": run["workers"], "total_sims": run["total_sims"],
            "history": hist, "log": run["log"], "final_grid": run["final_level"]["grid"],
            "traces": run["traces"]["final"]}


def build_game(runs: list[tuple[str, dict]], mode: str = "3d") -> str:
    """mode '3d': first-person Three.js game (default). mode '2d': the top-down neon shooter."""
    if not runs:
        raise ValueError("no runs found - run: python run_demo.py")
    rules, llm = pick_runs(runs)
    levels, lab = [], []
    base = rules or llm or runs[0]
    name, run = base
    h = run["history"]
    who = "rule-based agents" if _is_rules(run) else f"LLM agents ({run['llm'].split(':')[-1]})"
    levels.append(_level("BEFORE AI", "Generated level, before any optimisation", run["initial_level"], h[0]))
    levels.append(_level("AI-OPTIMISED", f"The same level after {len(h) - 1} rounds of fixes by {who}",
                         run["final_level"], h[-1]))
    lab.append(_lab_run(f"{'RULE-BASED' if _is_rules(run) else 'LLM'} AGENTS · {name}", run))
    if llm and llm is not base:
        lname, lrun = llm
        model = lrun["llm"].split(":")[-1]
        levels.append(_level("AI-DESIGNED", f"Designed from player reviews by {model}, then optimised by LLM agents",
                             lrun["final_level"], lrun["history"][-1]))
        lab.append(_lab_run(f"LLM AGENTS · {lname}", lrun))
    data = {"levels": levels, "runs": lab, "rules": run["rules"],
            "totalSims": sum(r["total_sims"] for r in lab)}
    payload = json.dumps(data).replace("</", "<\\/")
    if mode == "2d":
        return TEMPLATE_2D.read_text(encoding="utf-8").replace("__GAME_DATA__", payload)
    bundle = BUNDLE_3D.read_text(encoding="utf-8").replace("</script", "<\\/script")
    html = TEMPLATE_3D.read_text(encoding="utf-8").replace("__GAME_DATA__", payload)
    return html.replace("__BUNDLE__", bundle)


def write_game(root: Path, out: Path | None = None, mode: str = "3d") -> Path:
    out = out or root / ("breach.html" if mode == "3d" else "breach2d.html")
    out.write_text(build_game(find_runs(root), mode), encoding="utf-8")
    return out
