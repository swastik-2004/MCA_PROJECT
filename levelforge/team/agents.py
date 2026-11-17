"""
The LevelForge agent team. Each agent below runs as its own A2A server (see serve.py).

    Director (master agent)  - plans every round and delegates work over A2A
    Review Analyst           - player reviews -> design brief                 (GenAI)
    Level Architect          - loads, generates or LLM-designs the level      (GenAI + MCP)
    Playtest Analyst         - play-tests levels on the cluster, diagnoses    (MCP -> master-worker)
    Difficulty Specialist    - monsters, traps, potions: completion and damage
    Layout Specialist        - loops, locks, hazard placement: flow and skill expression
    Reward Specialist        - coins and side rewards: engagement
    QA Validator             - applies plans through MCP, rejects broken / duplicate candidates
    Reporter                 - designer notes for the developer                (GenAI)

Every agent works with or without an LLM: with GROQ_API_KEY set the reasoning steps use the
LLM, otherwise (or if a call fails) the same rule-based logic as the original agent loop.
"""
from __future__ import annotations

import asyncio
import json
import os
import random

from ..agents import (PLAYBOOK, PROBLEM_IDS, SCORE_GUIDE, _metrics_brief, _op_str, llm_critic,
                      llm_generate_level, rule_critic, template_notes)
from ..level import Level
from ..llm import LLM, LLMError
from ..reviews import build_brief, label_reviews, load_reviews
from .a2a_kit import AgentContext


def make_llm() -> LLM:
    factory = os.environ.get("LEVELFORGE_LLM_FACTORY")   # "module:function", used by tests
    if factory:
        import importlib
        mod, fn = factory.split(":")
        return getattr(importlib.import_module(mod), fn)()
    return LLM(provider="offline") if os.environ.get("LEVELFORGE_OFFLINE") == "1" else LLM()


LLM_ = None


def llm() -> LLM:
    global LLM_
    if LLM_ is None:
        LLM_ = make_llm()
    return LLM_


# =========================================================================== roster
# key: (display name, port offset from the base port, description, skills)
ROSTER = {
    "director": ("Director", 0,
                 "Master agent. Runs the optimisation of a game level by delegating work to the other "
                 "agents over A2A, accepting or rejecting candidates and keeping a memory of failed fixes.",
                 [{"id": "optimise_level", "name": "Optimise a level",
                   "description": "Reviews + level in, optimised level + full history out."}]),
    "review": ("Review Analyst", 1, "Reads player reviews, labels each with design problems, builds the design brief.",
               [{"id": "build_brief", "name": "Build design brief",
                 "description": "Reviews -> problem shares -> target completion, target HP loss, score weights."}]),
    "architect": ("Level Architect", 2, "Provides the starting level: loads the problem level, or designs one.",
                  [{"id": "initial_level", "name": "Initial level",
                    "description": "mode=file|llm|procedural -> a validated playable level."}]),
    "playtest": ("Playtest Analyst", 3,
                 "Play-tests levels with simulated players on the master-worker cluster (via MCP) and "
                 "diagnoses why a level misses its targets.",
                 [{"id": "playtest", "name": "Play-test levels",
                   "description": "Levels -> metrics and quality score per level (one parallel job)."},
                  {"id": "diagnose", "name": "Diagnose level",
                   "description": "Metrics -> prioritised list of design problems."}]),
    "difficulty": ("Difficulty Specialist", 4, "Proposes edits to monsters, traps and potions.",
                   [{"id": "propose", "name": "Propose difficulty edits",
                     "description": "Diagnosis -> edit plans for completion rate and damage."}]),
    "layout": ("Layout Specialist", 5, "Proposes layout edits: loops, locks, hazard placement.",
               [{"id": "propose", "name": "Propose layout edits",
                 "description": "Diagnosis -> edit plans for backtracking and skill expression."}]),
    "reward": ("Reward Specialist", 6, "Proposes reward edits: coins and side-area incentives.",
               [{"id": "propose", "name": "Propose reward edits",
                 "description": "Diagnosis -> edit plans for engagement and exploration."}]),
    "qa": ("QA Validator", 7, "Applies proposed plans via MCP and rejects broken, empty or duplicate candidates.",
           [{"id": "validate_plans", "name": "Validate plans",
             "description": "Plans -> playable candidate levels + rejected plans with reasons."}]),
    "reporter": ("Reporter", 8, "Writes designer notes explaining what changed and why.",
                 [{"id": "write_notes", "name": "Write designer notes",
                   "description": "Run history -> short notes for the developer."}]),
}
WORKER_KEYS = [k for k in ROSTER if k != "director"]
SPECIALISTS = ["difficulty", "layout", "reward"]

# which specialist owns which diagnosed problem
OWNER = {"too_hard": "difficulty", "too_easy": "difficulty", "low_tension": "difficulty",
         "high_tension": "difficulty", "backtracking": "layout", "low_skill_expression": "layout",
         "low_engagement": "reward", "fine-tune": "reward"}
ALLOWED = {  # edit operations each specialist may use
    "difficulty": {"ops": {"add", "remove"}, "tiles": {"M", "T", "H"}},
    "layout": {"ops": {"add_loop", "add_lock", "remove_lock", "add", "remove"}, "tiles": {"M", "T"}},
    "reward": {"ops": {"add", "remove"}, "tiles": {"C", "H"}},
}
ROLE_TEXT = {
    "difficulty": "You control difficulty: monsters (M), traps (T) and health potions (H). Your job is the "
                  "completion rate and the HP lost by finishers.",
    "layout": "You control the layout: loops/shortcuts (add_loop), key+door locks (add_lock/remove_lock) and "
              "WHERE hazards sit (move M/T between main route and side areas). Your job is low backtracking "
              "and skill expression (cautious players should beat rushers).",
    "reward": "You control rewards: coins (C) and side-area potions (H). Your job is engagement: explorers "
              "should find rewards off the main route.",
}


def _allowed(spec: str, op: dict) -> bool:
    a = ALLOWED[spec]
    if op.get("op") not in a["ops"]:
        return False
    return op.get("op") not in ("add", "remove") or str(op.get("tile", "")).upper() in a["tiles"]


# =========================================================================== handlers
async def review_analyst(p: dict, ctx: AgentContext) -> dict:
    reviews = load_reviews(p["reviews_path"], p.get("limit"))
    labeled = await asyncio.to_thread(label_reviews, reviews, llm())
    brief = build_brief(labeled)
    labeler = "llm" if any(r["labeler"] == "llm" for r in labeled) else "keywords"
    top = sorted(brief["problem_share"].items(), key=lambda kv: -kv[1])[:3]
    return {"brief": brief, "labeled": labeled, "labeler": labeler,
            "note": f"{len(reviews)} reviews labelled by {labeler}; top complaints: "
                    + ", ".join(f"{k} {v:.0%}" for k, v in top)}


async def level_architect(p: dict, ctx: AgentContext) -> dict:
    mode, seed, brief = p.get("mode", "auto"), int(p.get("seed", 0)), p["brief"]
    if mode == "file":
        grid = p["grid"]
        v = await ctx.mcp("validate_level", {"grid": grid})
        if not v["ok"]:
            raise ValueError("problem level is not playable: " + "; ".join(v["errors"]))
        return {"level": {"name": p.get("name", "problem_level"), "grid": grid, "notes": ""},
                "source": "file", "note": f"loaded the existing level '{p.get('name', 'level')}'"}
    if mode in ("llm", "auto") and llm().online:
        try:
            lvl = await asyncio.to_thread(llm_generate_level, llm(), brief, seed)
            v = await ctx.mcp("validate_level", {"grid": lvl.grid})
            if v["ok"]:
                return {"level": lvl.to_dict(), "source": "llm",
                        "note": f"LLM ({llm().describe()}) designed a {lvl.width}x{lvl.height} level"}
        except (LLMError, KeyError, TypeError, ValueError):
            pass
    g = await ctx.mcp("generate_level", {"seed": seed})
    return {"level": {"name": "procedural", "grid": g["grid"], "notes": ""}, "source": "procedural",
            "note": "procedural generator created the level"
                    + (" (LLM unavailable)" if mode == "llm" else "")}


async def playtest_analyst(p: dict, ctx: AgentContext) -> dict:
    if p.get("skill") == "diagnose":
        best, brief, tried = p["best"], p["brief"], p.get("tried", {})
        crit = None
        if llm().online:
            try:
                crit = await asyncio.to_thread(llm_critic, llm(), best, brief, tried)
                crit["source"] = "llm"
            except (LLMError, KeyError, TypeError):
                crit = None
        if crit is None:
            crit = rule_critic(best["metrics"], best["quality"], brief, Level.from_dict(best["level"]), tried)
            crit["source"] = "rules"
        crit["diagnosis"] = [{k: v for k, v in d.items() if k != "severity"} for d in crit["diagnosis"]]
        return {"critique": crit}
    # skill: playtest
    res = await ctx.mcp("evaluate_levels", {"grids": p["grids"], "runs_per_persona": p["runs"],
                                            "seed": p["seed"], "brief": p["brief"]})
    if "error" in res:
        raise ValueError(res["error"])
    return res


async def _specialist(spec: str, p: dict) -> dict:
    """Propose plans for the problems the Director assigned to this specialist.

    p["assignments"] = [{"problem": <id or "explore">, "n": <number of plans>}, ...]
    """
    assignments = [a for a in p.get("assignments", []) if int(a.get("n", 0)) > 0]
    n = sum(int(a["n"]) for a in assignments)
    rnd = int(p.get("round", 0))
    plans, source = [], "rules"
    if llm().online and n:
        try:
            plans = await asyncio.to_thread(_llm_specialist_plans, spec, p, assignments)
            source = "llm"
        except (LLMError, KeyError, TypeError, ValueError):
            plans = []
    # rule-based plans per assignment; also tops up when the LLM returned fewer plans than asked
    need = {a["problem"]: int(a["n"]) for a in assignments}
    for pl in plans:
        if need.get(pl.get("problem"), 0) > 0:
            need[pl["problem"]] -= 1
    extra = rule_specialist_plans(spec, [{"problem": k, "n": v} for k, v in need.items() if v > 0],
                                  seed=f"{p.get('seed', 0)}-{rnd}-{spec}", avoid=p.get("avoid", []))
    if extra and source == "llm":
        source = "llm+rules"
    plans = (plans + extra)[:n]
    for pl in plans:
        pl["agent"] = ROSTER[spec][0]
    return {"plans": plans, "source": source,
            "note": f"{len(plans)} plan(s) ({source}) for " + ", ".join(f"{a['problem']} x{a['n']}" for a in assignments)}


EXPLORE = {  # small exploratory changes when the Director has spare plan slots (as in rule_plans)
    "difficulty": PLAYBOOK["low_tension"] + PLAYBOOK["high_tension"],
    "layout": PLAYBOOK["backtracking"][:1] + PLAYBOOK["fine-tune"][1:],
    "reward": PLAYBOOK["fine-tune"][:1] + PLAYBOOK["low_engagement"],
}


def edits_key(edits: list) -> str:
    return json.dumps(edits, sort_keys=True)


def rule_specialist_plans(spec: str, assignments: list, seed="0", avoid: list | None = None) -> list:
    """Playbook plans for the assigned problems. Plans the team already tried on the current
    best level (shared memory passed by the Director as `avoid`) are used last."""
    rng = random.Random(str(seed))
    avoid = set(avoid or [])
    plans = []
    for a in assignments:
        prob, n = a["problem"], int(a["n"])
        pool = EXPLORE[spec] if prob == "explore" else PLAYBOOK.get(prob, EXPLORE[spec])
        options = [o for o in pool if all(_allowed(spec, op) for op in o)] or \
                  [o for o in EXPLORE[spec] if all(_allowed(spec, op) for op in o)]
        rng.shuffle(options)
        options.sort(key=lambda o: edits_key(o) in avoid)   # untried first (stable sort keeps the shuffle)
        for i in range(n):
            edits = options[i] if i < len(options) else rng.choice(options)
            label = "explore" if prob == "explore" else f"fix {prob}"
            plans.append({"problem": prob, "edits": edits,
                          "rationale": f"{label}: " + ", ".join(_op_str(o) for o in edits)})
    return plans


def _llm_specialist_plans(spec: str, p: dict, assignments: list) -> list:
    best, critique, brief = p["best"], p["critique"], p["brief"]
    allowed = ALLOWED[spec]
    causes = {d["problem"]: d.get("cause", "") for d in critique.get("diagnosis", [])}
    tasks = [{"problem": a["problem"], "plans_needed": a["n"],
              "evidence": causes.get(a["problem"], "spare slot: propose a small exploratory change")}
             for a in assignments]
    system = (f"You are the {ROSTER[spec][0]} in a team of game-design agents improving a dungeon level. "
              f"{ROLE_TEXT[spec]}\nYou may ONLY use these operations: {sorted(allowed['ops'])} with tiles "
              f"{sorted(allowed['tiles'])}.\nEdit format: "
              '{"op": "add|remove", "tile": "M|T|H|C", "count": 1-4, "where": "main|side|any"}, '
              '{"op": "add_loop", "count": 1-2}, {"op": "add_lock"}, {"op": "remove_lock"}. '
              '"main" = on the shortest route start->exit, "side" = off it.\n' + SCORE_GUIDE)
    user = (f"Design targets: completion {brief['target_completion']}, HP lost by finishers {brief['target_tension']}.\n"
            f"Full critique from the Playtest Analyst: {json.dumps(critique.get('diagnosis', []))}\n"
            f"Problems the Director assigned to YOU this round: {json.dumps(tasks)}\n"
            f"Current quality: {json.dumps(best['quality'])}\n"
            f"Current metrics: {json.dumps(_metrics_brief(best['metrics']))}\n"
            f"Level contents: {json.dumps(Level.from_dict(best['level']).summary())}\n"
            f"Last round's candidates from ALL specialists and their simulated scores (learn from them): "
            f"{json.dumps(p.get('feedback', []))}\n"
            f"Edit lists already tried on this exact level without success (do not repeat them): "
            f"{json.dumps(p.get('avoid', [])[-12:])}\n"
            f"For each assigned problem propose exactly plans_needed different plans (each 1-2 edits). "
            f"Return JSON: "
            '{"plans": [{"problem": "<assigned problem id>", "rationale": "one sentence", "edits": [ {...} ]}]}')
    data = llm().chat_json(system, user, temperature=0.7)
    plans = data.get("plans") if isinstance(data, dict) else data
    valid = {a["problem"] for a in assignments}
    out = []
    for pl in plans or []:
        if not isinstance(pl, dict):
            continue
        edits = [e for e in pl.get("edits", []) if isinstance(e, dict) and _allowed(spec, e)]
        prob = pl.get("problem") if pl.get("problem") in valid else assignments[0]["problem"]
        if edits:
            out.append({"problem": prob, "rationale": str(pl.get("rationale", "edit plan"))[:160], "edits": edits})
    if not out:
        raise LLMError("no usable plans")
    return out


async def difficulty_specialist(p, ctx):
    return await _specialist("difficulty", p)


async def layout_specialist(p, ctx):
    return await _specialist("layout", p)


async def reward_specialist(p, ctx):
    return await _specialist("reward", p)


async def qa_validator(p: dict, ctx: AgentContext) -> dict:
    grid, seed, rnd = p["grid"], int(p["seed"]), int(p["round"])
    seen = {"\n".join(grid)}
    candidates, rejected = [], []
    for i, plan in enumerate(p["plans"]):
        res = await ctx.mcp("apply_edits", {"grid": grid, "edits": plan.get("edits", []),
                                            "seed": seed * 1000 + rnd * 10 + i})
        key = "\n".join(res["grid"])
        if not res["applied"] or not res["changed"]:
            rejected.append({**plan, "why": "; ".join(res["log"])[:120] or "no edit could be applied"})
            continue
        if key in seen:
            rejected.append({**plan, "why": "duplicate of another candidate"})
            continue
        seen.add(key)
        candidates.append({"plan": plan.get("rationale", "edit plan"), "agent": plan.get("agent", "?"),
                           "grid": res["grid"], "edit_log": res["log"]})
    if not candidates:  # keep the search moving
        res = await ctx.mcp("apply_edits", {"grid": grid, "edits": [{"op": "add_loop"},
                                            {"op": "add", "tile": "C", "count": 1, "where": "side"}],
                                            "seed": seed + rnd})
        candidates.append({"plan": "fallback perturbation", "agent": "QA Validator", "grid": res["grid"],
                           "edit_log": res["log"]})
    return {"candidates": candidates, "rejected": rejected,
            "note": f"{len(candidates)} candidate(s) passed, {len(rejected)} rejected"}


async def reporter(p: dict, ctx: AgentContext) -> dict:
    first, last, brief = p["first"], p["last"], p["brief"]
    notes, source = None, "template"
    if llm().online:
        try:
            notes = await asyncio.to_thread(
                llm().chat, "You are a game designer writing short designer notes for a report.",
                f"Initial quality {json.dumps(first['best_quality'])}, metrics {json.dumps(first['best_metrics'])}.\n"
                f"Final quality {json.dumps(last['best_quality'])}, metrics {json.dumps(last['best_metrics'])}.\n"
                f"Accepted changes per round (and which specialist agent proposed them): "
                f"{json.dumps(p.get('accepted', []))[:1800]}\n"
                "Write 4-6 sentences explaining what changed and why, in plain language.", 0.5)
            source = "llm"
        except LLMError:
            notes = None
    if not notes:
        notes = template_notes(first, last, brief)
    return {"notes": notes.strip(), "source": source}


HANDLERS = {"review": review_analyst, "architect": level_architect, "playtest": playtest_analyst,
            "difficulty": difficulty_specialist, "layout": layout_specialist, "reward": reward_specialist,
            "qa": qa_validator, "reporter": reporter}

__all__ = ["ROSTER", "WORKER_KEYS", "SPECIALISTS", "OWNER", "HANDLERS", "PROBLEM_IDS", "llm"]
