"""
The agentic optimisation loop, built with LangGraph.

    design brief ──► GENERATOR ──► SIMULATE (parallel) ──► decide ──► FINALIZE
                                      ▲                      │
                                      │                      ▼
                                  OPTIMIZER ◄───────────── CRITIC

  * Generator  (GenAI)  writes an initial level grid from the design brief.
  * Simulate   (HPC)    runs hundreds of bot playthroughs per candidate in parallel
                        and keeps the best candidate (accept / reject with rollback).
  * Critic     (agent)  reads the metrics and explains WHY the level falls short.
  * Optimizer  (agent)  proposes several alternative edit plans; each becomes a
                        candidate level that is simulated next round.
  * Finalize   (GenAI)  writes designer notes explaining what changed and why.

Every LLM step has a rule-based fallback, so the loop always completes.
"""
from __future__ import annotations

import json
import random
from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from .edits import OPS_HELP, apply_edits
from .generator import random_candidate
from .level import Level, repair, validate
from .llm import LLM, LLMError
from .metrics import quality
from .parallel import ParallelRunner


PROBLEM_IDS = ["too_hard", "too_easy", "low_engagement", "backtracking",
               "low_skill_expression", "low_tension", "high_tension"]

SCORE_GUIDE = """How the quality score (0-1) is computed - optimise the TOTAL, not one component:
- balance (largest weight): completion rate close to the target. Overshooting is penalised exactly
  like undershooting: 100% completion with a 71% target scores badly. Do not make the level trivial.
- engagement: explorer coin collection and share of the map explored (coins off the main route help).
- flow: low backtracking (loops/shortcuts help).
- skill: cautious bots should finish clearly more often than rushers. Hazards ON the main route that
  can be walked around reward careful play; making everything safe removes skill expression.
- tension: HP lost by finishers close to its target. Potions lower HP loss; monsters/traps raise it.
Size the edit to the gap: if a target is far off (e.g. completion 100% vs 71%), use bigger edits
(count 2-4, or several edits together). One extra monster in a wide room changes little, because
bots walk around it. Near the target, use small edits (count 1) so you do not overshoot.
Edits that cannot apply are skipped (e.g. add_lock when the level already has a door) - check the
'not applied' feedback and do not repeat them."""


class LoopState(TypedDict, total=False):
    brief: dict
    candidates: list            # list of {"level": dict, "plan": str, "edit_log": [...]}
    best: dict                  # {"level", "metrics", "quality", "plan"}
    history: list               # one entry per round
    critique: dict
    tried: dict                 # reflection memory: problem -> number of failed fix attempts
    skipped: list               # plans from last round where no edit could be applied
    round: int
    max_rounds: int
    log: list                   # human-readable agent trace
    designer_notes: str


def _metrics_brief(m: dict) -> dict:
    keys = ["completion_rate", "death_rate", "timeout_rate", "avg_damage", "backtrack_ratio",
            "exploration", "coin_collection", "hp_lost_by_finishers", "per_persona_completion"]
    return {k: (round(m[k], 3) if isinstance(m[k], float) else m[k]) for k in keys}


class AgentSystem:
    def __init__(self, runner: ParallelRunner, llm: LLM, runs_per_persona: int = 150,
                 candidates_per_round: int = 4, seed: int = 0, verbose: bool = True,
                 start: str = "auto", start_level: Level | None = None):
        """start: 'auto' (LLM writes the first level when online), 'llm', or 'procedural'
        (always start from the procedural level, so methods can be compared fairly).
        start_level: an existing level to optimise (e.g. one players complained about);
        when given, the generator skips level creation and uses it as-is."""
        self.start = start
        self.start_level = start_level
        self.runner = runner
        self.llm = llm
        self.runs = runs_per_persona
        self.k = candidates_per_round
        self.seed = seed
        self.verbose = verbose

    def say(self, state: LoopState, msg: str) -> None:
        state.setdefault("log", []).append(msg)
        if self.verbose:
            print(msg, flush=True)

    # ------------------------------------------------------------------ nodes
    def generator(self, state: LoopState) -> LoopState:
        brief = state["brief"]
        level = None
        if self.start_level is not None:
            level = Level.from_dict(self.start_level.to_dict())
            level.name = "initial"
            self.say(state, f"[Generator] loaded the existing level '{self.start_level.name}' "
                            f"({level.width}x{level.height}) to be optimised; no new level generated")
        elif self.llm.online and self.start in ("auto", "llm"):
            try:
                level = self._llm_generate(brief)
                self.say(state, f"[Generator] LLM ({self.llm.describe()}) wrote a {level.width}x{level.height} level")
            except LLMError as e:
                self.say(state, f"[Generator] LLM failed ({str(e)[:80]}); using procedural generator")
        if level is None:
            level = random_candidate(self.seed)
            level.name = "initial"
            why = "procedural start requested" if self.start == "procedural" else "offline mode"
            self.say(state, f"[Generator] procedural generator created the initial level ({why})")
        state["candidates"] = [{"level": level.to_dict(), "plan": "initial design", "edit_log": []}]
        state["round"] = 0
        state["history"] = []
        return state

    def _llm_generate(self, brief: dict) -> Level:
        goals = "\n".join(f"- {g['description']} ({g['share']:.0%} of reviews): {g['design_modification']}"
                          for g in brief.get("design_goals", [])[:5])
        system = ("You are a game level designer. You design small top-down dungeon levels as ASCII grids.\n"
                  "Tiles: # wall, . floor, S start (exactly one), E exit (exactly one), K key, D locked door, "
                  "M monster, T trap, H health potion, C coin.\n"
                  "Rules: grid 21-25 columns x 13-15 rows, every row the same length, outer border all '#', "
                  "the exit must be reachable from the start (a door needs a key reachable before it). "
                  "Design guidance: build 4-7 small rooms joined by 1-tile-wide corridors, so hazards in "
                  "corridors cannot simply be walked around. Include roughly 5-8 monsters, 3-6 traps, "
                  "4-6 coins mostly in side rooms/dead ends, 1-3 potions, and optionally one key + door "
                  "guarding the exit. Avoid large empty open areas. A level everyone finishes without "
                  "losing HP is a failed design.")
        user = (f"Player feedback says:\n{goals}\n\n"
                f"Design a level for these players. Target: about {brief['target_completion']:.0%} of "
                f"players should finish. Return JSON: "
                '{"name": "...", "notes": "one sentence design intent", "grid": ["row1", "row2", ...]}')
        data = self.llm.chat_json(system, user, temperature=0.7)
        lvl = Level(name=str(data.get("name", "llm_level"))[:40], grid=[str(r) for r in data["grid"]],
                    notes=str(data.get("notes", ""))[:200])
        errs = validate(lvl)
        if errs:
            # one self-correction attempt, then deterministic repair
            try:
                fix = self.llm.chat_json(system, user + "\n\nYour previous grid had problems: " +
                                         "; ".join(errs) + "\nPrevious grid:\n" + "\n".join(lvl.grid) +
                                         "\nReturn a corrected JSON object.", temperature=0.3)
                lvl2 = Level(lvl.name, [str(r) for r in fix["grid"]], lvl.notes)
                if not validate(lvl2):
                    return lvl2
                lvl = lvl2
            except (LLMError, KeyError, TypeError):
                pass
            lvl = repair(lvl, seed=self.seed)
            if validate(lvl):
                raise LLMError("generated level could not be repaired")
        return lvl

    def simulate(self, state: LoopState) -> LoopState:
        cands = state["candidates"]
        metrics = self.runner.evaluate_many([c["level"] for c in cands], self.runs,
                                            base_seed=self.seed * 100000 + 1)
        brief = state["brief"]
        scored = []
        for c, m in zip(cands, metrics):
            q = quality(m, brief)
            scored.append({**c, "metrics": m, "quality": q})
        n_sims = len(cands) * self.runs * 3
        sps = metrics[0].get("sweep_sims_per_second", 0)
        rnd = state["round"]
        self.say(state, f"[Simulate] round {rnd}: {len(cands)} candidate(s) x {self.runs * 3} playthroughs "
                        f"= {n_sims} sims on {self.runner.workers} worker(s) ({sps:.0f} sims/s)")
        top = max(scored, key=lambda s: s["quality"]["total"])
        prev = state.get("best")
        for s in scored:
            self.say(state, f"           - {s['plan'][:70]:<70} score={s['quality']['total']:.3f} "
                            f"completion={s['metrics']['completion_rate']:.2f}")
        if prev is None or top["quality"]["total"] > prev["quality"]["total"] + 1e-4:
            state["best"] = top
            decision = "accepted"
        else:
            decision = "rejected (kept previous best)"
        # Reflection: remember which diagnosed problem we failed to fix, so the
        # critic shifts attention instead of repeating itself.
        crit = state.get("critique")
        if crit and decision != "accepted":
            tried = state.setdefault("tried", {})
            tried[crit.get("priority", "?")] = tried.get(crit.get("priority", "?"), 0) + 1
        self.say(state, f"[Simulate] best candidate {decision}; best score so far "
                        f"{state['best']['quality']['total']:.3f}")
        state["history"].append({
            "round": rnd,
            "candidates": [{"plan": s["plan"], "edit_log": s["edit_log"], "quality": s["quality"],
                            "metrics": _metrics_brief(s["metrics"]), "level": s["level"]} for s in scored],
            "decision": decision,
            "accepted_plan": top["plan"] if decision == "accepted" else None,
            "accepted_edits": top["edit_log"] if decision == "accepted" else [],
            "best_score": state["best"]["quality"]["total"],
            "best_quality": state["best"]["quality"],
            "best_metrics": _metrics_brief(state["best"]["metrics"]),
            "best_level": state["best"]["level"],
            "sweep_seconds": metrics[0].get("sweep_seconds"),
            "sims": n_sims,
        })
        return state

    def should_continue(self, state: LoopState) -> str:
        if state["round"] >= state["max_rounds"]:
            return "finalize"
        if state["best"]["quality"]["total"] >= 0.92:
            self.say(state, "[Router] quality target reached, stopping early")
            return "finalize"
        return "critic"

    # ------------------------------------------------------------------
    def critic(self, state: LoopState) -> LoopState:
        best, brief = state["best"], state["brief"]
        crit = None
        if self.llm.online:
            try:
                crit = self._llm_critic(best, brief, state.get("tried", {}))
                crit["source"] = "llm"
            except (LLMError, KeyError, TypeError) as e:
                self.say(state, f"[Critic] LLM failed ({str(e)[:60]}); using rules")
        if crit is None:
            crit = rule_critic(best["metrics"], best["quality"], brief, Level.from_dict(best["level"]),
                               state.get("tried", {}))
            crit["source"] = "rules"
        state["critique"] = crit
        if state.get("tried"):
            self.say(state, f"[Critic] memory of unsuccessful fixes: {state['tried']}")
        for d in crit.get("diagnosis", [])[:4]:
            self.say(state, f"[Critic] {d.get('problem')}: {d.get('cause')}")
        self.say(state, f"[Critic] priority -> {crit.get('priority')}")
        return state

    def _llm_critic(self, best: dict, brief: dict, tried: dict) -> dict:
        facts = rule_critic(best["metrics"], best["quality"], brief, Level.from_dict(best["level"]))
        system = ("You are a game-design critic analysing simulated playtests of a dungeon level. "
                  "Three bot types played it: rusher (ignores danger), cautious (avoids danger), "
                  "explorer (collects items). Diagnose why the level misses its design targets.\n"
                  + SCORE_GUIDE)
        user = (f"Design targets: completion rate {brief['target_completion']}, "
                f"HP lost by finishers {brief['target_tension']}.\n"
                f"Quality components: {json.dumps(best['quality'])}\n"
                f"Metrics: {json.dumps(_metrics_brief(best['metrics']))}\n"
                f"Measured gaps from the simulator: {json.dumps([d['cause'] for d in facts['diagnosis']])}\n"
                f"Level contents: {json.dumps(Level.from_dict(best['level']).summary())}\n"
                f"Priorities already tried WITHOUT improving the score (choose a different one unless "
                f"nothing else is wrong): {json.dumps(tried)}\n"
                f"Grid:\n" + "\n".join(best["level"]["grid"]) +
                f"\n\nUse ONLY these problem ids: {PROBLEM_IDS}.\n"
                'Return a JSON object: {"diagnosis": [{"problem": "<id>", "cause": "short evidence from the '
                'numbers", "fix": "short suggestion"}], "priority": "<id>"} with at most 4 diagnosis items.')
        data = self.llm.chat_json(system, user, temperature=0.3)
        diag = [d for d in data.get("diagnosis", []) if isinstance(d, dict) and d.get("problem") in PROBLEM_IDS]
        if not diag:
            raise LLMError("critic returned no valid diagnosis")
        if data.get("priority") not in PROBLEM_IDS:
            data["priority"] = diag[0]["problem"]
        data["diagnosis"] = diag
        return data

    def optimizer(self, state: LoopState) -> LoopState:
        best = state["best"]
        level = Level.from_dict(best["level"])
        plans = None
        if self.llm.online:
            try:
                plans = self._llm_plans(best, state["critique"], state["history"][-1],
                                        state.get("skipped", []))
            except (LLMError, KeyError, TypeError) as e:
                self.say(state, f"[Optimizer] LLM failed ({str(e)[:60]}); using rules")
        if not plans:
            plans = rule_plans(state["critique"], self.k, seed=self.seed + state["round"])
        state["round"] += 1
        cands, skipped = [], []
        for i, p in enumerate(plans[: self.k]):
            new, log = apply_edits(level, p.get("edits", []), seed=self.seed * 1000 + state["round"] * 10 + i)
            applied = [x for x in log if x.startswith("applied")]
            if not applied:
                skipped.append({"plan": str(p.get("rationale", ""))[:100], "why": log[:3]})
                self.say(state, f"            - (not applied) {str(p.get('rationale', ''))[:60]}: {'; '.join(log)[:80]}")
                continue
            new.name = f"r{state['round']}_c{i}"
            cands.append({"level": new.to_dict(), "plan": p.get("rationale", "edit plan"), "edit_log": log})
        if not cands:  # nothing applicable: perturb randomly so the search can continue
            new, log = apply_edits(level, [{"op": "add_loop"}, {"op": "add", "tile": "C", "count": 1, "where": "side"}],
                                   seed=self.seed + state["round"])
            new.name = f"r{state['round']}_fallback"
            cands.append({"level": new.to_dict(), "plan": "fallback perturbation", "edit_log": log})
        self.say(state, f"[Optimizer] round {state['round']}: proposed {len(cands)} candidate edit plan(s)")
        for c in cands:
            self.say(state, f"            - {c['plan'][:80]}  -> {'; '.join(x for x in c['edit_log'] if x.startswith('applied'))[:90]}")
        state["candidates"] = cands
        state["skipped"] = skipped
        return state

    def _llm_plans(self, best: dict, critique: dict, last_round: dict, skipped: list | None = None) -> list:
        tried = [{"plan": c["plan"][:120],
                  "applied": [x[9:] for x in c["edit_log"] if x.startswith("applied")],
                  "not_applied": [x for x in c["edit_log"] if not x.startswith("applied")],
                  "total": c["quality"]["total"],
                  "completion": c["metrics"]["completion_rate"]}
                 for c in last_round.get("candidates", []) if c.get("edit_log")]
        system = ("You are a level-optimisation agent. You improve a dungeon level by choosing structured "
                  "edit operations, then a simulator scores each plan.\n" + OPS_HELP + "\n" + SCORE_GUIDE)
        user = (f"Critique: {json.dumps(critique.get('diagnosis', []))}\n"
                f"Priority: {critique.get('priority', '')}\n"
                f"Current best quality: {json.dumps(best['quality'])}\n"
                f"Current completion rate: {best['metrics']['completion_rate']:.2f}\n"
                f"Level contents: {json.dumps(Level.from_dict(best['level']).summary())}\n"
                f"Plans tried last round and their simulated results (learn from these; the current best "
                f"total is {best['quality']['total']}): {json.dumps(tried)}\n"
                f"Plans that could not be applied at all last round: {json.dumps(skipped or [])}\n"
                f"Propose {self.k} DIFFERENT alternative plans (each 1-2 edits) so they can be compared "
                f"in simulation. Return a JSON object: "
                '{"plans": [{"rationale": "one sentence", "edits": [ {...}, ... ]}, ...]}')
        data = self.llm.chat_json(system, user, temperature=0.8)
        plans = data.get("plans") if isinstance(data, dict) else data
        if not isinstance(plans, list) or not plans:
            raise LLMError("optimizer returned no plans")
        return plans

    def finalize(self, state: LoopState) -> LoopState:
        h = state["history"]
        first, last = h[0], h[-1]
        notes = None
        if self.llm.online:
            try:
                notes = self.llm.chat(
                    "You are a game designer writing short designer notes for a report.",
                    f"Initial quality {json.dumps(first['best_quality'])}, metrics {json.dumps(first['best_metrics'])}.\n"
                    f"Final quality {json.dumps(last['best_quality'])}, metrics {json.dumps(last['best_metrics'])}.\n"
                    f"Accepted edits per round: {json.dumps([r['accepted_edits'] for r in h[1:]])[:1500]}\n"
                    "Write 4-6 sentences explaining what changed and why, in plain language.", temperature=0.5)
            except LLMError:
                notes = None
        if not notes:
            notes = template_notes(first, last, state["brief"])
        state["designer_notes"] = notes.strip()
        self.say(state, f"[Finalize] score {first['best_score']:.3f} -> {last['best_score']:.3f} "
                        f"after {state['round']} optimisation round(s)")
        return state

    # ------------------------------------------------------------------
    def build_graph(self):
        g = StateGraph(LoopState)
        g.add_node("generator", self.generator)
        g.add_node("simulate", self.simulate)
        g.add_node("critic", self.critic)
        g.add_node("optimizer", self.optimizer)
        g.add_node("finalize", self.finalize)
        g.set_entry_point("generator")
        g.add_edge("generator", "simulate")
        g.add_conditional_edges("simulate", self.should_continue,
                                {"critic": "critic", "finalize": "finalize"})
        g.add_edge("critic", "optimizer")
        g.add_edge("optimizer", "simulate")
        g.add_edge("finalize", END)
        return g.compile()

    def run(self, brief: dict, max_rounds: int = 5) -> dict:
        graph = self.build_graph()
        return graph.invoke({"brief": brief, "max_rounds": max_rounds, "log": []},
                            {"recursion_limit": 100})


# ---------------------------------------------------------------------------
# Rule-based fallbacks (offline mode)
# ---------------------------------------------------------------------------
def rule_critic(m: dict, q: dict, brief: dict, level: Level, tried: dict | None = None) -> dict:
    tc, tt = brief["target_completion"], brief["target_tension"]
    cr = m["completion_rate"]
    pc = m["per_persona_completion"]
    diag = []
    if cr < tc - 0.07:
        diag.append({"problem": "too_hard", "cause": f"only {cr:.0%} of runs finish (target {tc:.0%}); "
                     f"avg damage {m['avg_damage']:.1f}, {m['avg_fights']:.1f} fights per run",
                     "fix": "remove hazards from the main route or add a potion", "severity": tc - cr})
    elif cr > tc + 0.07:
        diag.append({"problem": "too_easy", "cause": f"{cr:.0%} of runs finish (target {tc:.0%})",
                     "fix": "add a monster or trap on the main route", "severity": cr - tc})
    if q["engagement"] < 0.6:
        diag.append({"problem": "low_engagement", "cause": f"explorer collects {m['coin_collection']:.0%} "
                     f"of {level.count('C')} coins; exploration {m['exploration']:.0%}",
                     "fix": "add coins in side areas", "severity": 0.6 - q["engagement"]})
    if q["flow"] < 0.65:
        diag.append({"problem": "backtracking", "cause": f"{m['backtrack_ratio']:.0%} of steps revisit tiles",
                     "fix": "add a loop/shortcut", "severity": 0.65 - q["flow"]})
    spread = pc.get("cautious", 0) - pc.get("rusher", 0)
    if q["skill"] < 0.5:
        diag.append({"problem": "low_skill_expression", "cause": f"cautious finishes {pc.get('cautious', 0):.0%} "
                     f"vs rusher {pc.get('rusher', 0):.0%} (spread {spread:+.0%})",
                     "fix": "put avoidable hazards on the main route" if spread < 0.1 else
                     "move hazards off forced corridors", "severity": (0.5 - q["skill"]) * 0.6})
    hp = m["hp_lost_by_finishers"]
    if q["tension"] < 0.6:
        diag.append({"problem": "low_tension" if hp < tt else "high_tension",
                     "cause": f"finishers lose {hp:.0%} of HP (target {tt:.0%})",
                     "fix": "add a monster" if hp < tt else "add a health potion",
                     "severity": (0.6 - q["tension"]) * 0.7})
    tried = tried or {}
    for d in diag:  # demote problems we already failed to fix
        d["severity"] *= 0.4 ** tried.get(d["problem"], 0)
    diag.sort(key=lambda d: -d["severity"])
    return {"diagnosis": diag, "priority": diag[0]["problem"] if diag else "fine-tune"}


PLAYBOOK = {
    "too_hard": [[{"op": "remove", "tile": "M", "count": 1, "where": "main"}],
                 [{"op": "remove", "tile": "T", "count": 2, "where": "main"}],
                 [{"op": "add", "tile": "H", "count": 1, "where": "main"}],
                 [{"op": "remove", "tile": "M", "count": 2, "where": "any"}, {"op": "add", "tile": "H", "count": 1, "where": "side"}],
                 [{"op": "remove", "tile": "T", "count": 1, "where": "main"}, {"op": "remove", "tile": "M", "count": 1, "where": "main"}]],
    "too_easy": [[{"op": "add", "tile": "M", "count": 1, "where": "main"}],
                 [{"op": "add", "tile": "T", "count": 2, "where": "main"}],
                 [{"op": "remove", "tile": "H", "count": 1, "where": "any"}],
                 [{"op": "add", "tile": "M", "count": 2, "where": "any"}]],
    "low_engagement": [[{"op": "add", "tile": "C", "count": 2, "where": "side"}],
                       [{"op": "add", "tile": "C", "count": 3, "where": "side"}],
                       [{"op": "add", "tile": "C", "count": 1, "where": "side"}, {"op": "add", "tile": "H", "count": 1, "where": "side"}]],
    "backtracking": [[{"op": "add_loop", "count": 1}], [{"op": "add_loop", "count": 2}], [{"op": "remove_lock"}]],
    "low_skill_expression": [[{"op": "add", "tile": "T", "count": 1, "where": "main"}, {"op": "add_loop", "count": 1}],
                             [{"op": "remove", "tile": "T", "count": 1, "where": "main"}, {"op": "add", "tile": "T", "count": 1, "where": "side"}],
                             [{"op": "add", "tile": "M", "count": 1, "where": "main"}, {"op": "add_loop", "count": 1}]],
    "low_tension": [[{"op": "add", "tile": "M", "count": 1, "where": "main"}], [{"op": "remove", "tile": "H", "count": 1, "where": "any"}]],
    "high_tension": [[{"op": "add", "tile": "H", "count": 1, "where": "main"}], [{"op": "remove", "tile": "M", "count": 1, "where": "main"}]],
    "fine-tune": [[{"op": "add", "tile": "C", "count": 1, "where": "side"}], [{"op": "add_loop", "count": 1}]],
}


def rule_plans(critique: dict, k: int, seed: int = 0) -> list[dict]:
    """Build k alternative plans spread over the top problems (most go to the top one)."""
    rng = random.Random(seed)
    diag = critique.get("diagnosis") or [{"problem": "fine-tune"}]
    probs = [d["problem"] for d in diag][:3] or ["fine-tune"]
    quota = [max(1, k - 2)] + [1] * (len(probs) - 1)
    plans = []
    for prob, q in zip(probs, quota):
        options = list(PLAYBOOK.get(prob, PLAYBOOK["fine-tune"]))
        rng.shuffle(options)
        for edits in options[:q]:
            plans.append({"rationale": f"fix {prob}: " + ", ".join(_op_str(o) for o in edits),
                          "edits": edits})
    if len(probs) > 1 and len(plans) < k:
        combo = rng.choice(PLAYBOOK.get(probs[0], PLAYBOOK["fine-tune"])) + \
            rng.choice(PLAYBOOK.get(probs[1], PLAYBOOK["fine-tune"]))
        plans.append({"rationale": f"fix {probs[0]} + {probs[1]}: " + ", ".join(_op_str(o) for o in combo),
                      "edits": combo})
    while len(plans) < k:  # top up with random fine-tuning
        edits = rng.choice(PLAYBOOK["fine-tune"] + PLAYBOOK["low_engagement"])
        plans.append({"rationale": "explore: " + ", ".join(_op_str(o) for o in edits), "edits": edits})
    return plans[:k]


def _op_str(o: dict) -> str:
    if o["op"] in ("add", "remove"):
        return f"{o['op']} {o.get('count', 1)}{o['tile']}@{o.get('where', 'any')}"
    return o["op"]


def template_notes(first: dict, last: dict, brief: dict) -> str:
    fm, lm = first["best_metrics"], last["best_metrics"]
    parts = [f"The initial level scored {first['best_score']:.2f}; after optimisation it scores "
             f"{last['best_score']:.2f}."]
    parts.append(f"Completion moved from {fm['completion_rate']:.0%} to {lm['completion_rate']:.0%} "
                 f"against a review-derived target of {brief['target_completion']:.0%}.")
    parts.append(f"Backtracking went from {fm['backtrack_ratio']:.0%} to {lm['backtrack_ratio']:.0%} of steps, "
                 f"and explorers now collect {lm['coin_collection']:.0%} of the coins "
                 f"(was {fm['coin_collection']:.0%}).")
    pc0, pc1 = fm["per_persona_completion"], lm["per_persona_completion"]
    parts.append("Per-player-type completion (rusher / cautious / explorer): "
                 f"{pc0.get('rusher', 0):.0%}/{pc0.get('cautious', 0):.0%}/{pc0.get('explorer', 0):.0%} -> "
                 f"{pc1.get('rusher', 0):.0%}/{pc1.get('cautious', 0):.0%}/{pc1.get('explorer', 0):.0%}.")
    return " ".join(parts)
