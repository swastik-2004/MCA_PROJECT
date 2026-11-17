"""
The Director: the master agent of the LevelForge team.

It owns the optimisation loop but does none of the specialist work itself. Every step is
delegated over A2A to a worker agent discovered from its Agent Card:

    round 0   Review Analyst  -> brief
              Level Architect -> starting level
              Playtest Analyst [playtest] -> baseline score   (MCP -> master-worker cluster)
    round r   Playtest Analyst [diagnose] -> problems + priority
              Difficulty / Layout / Reward Specialists [propose]  (in parallel; the specialist that
                  owns the priority problem gets more plan slots)
              QA Validator -> playable, distinct candidates          (MCP apply_edits)
              Playtest Analyst [playtest] -> scores for all candidates in ONE parallel job
              Director decides: accept the best or roll back; remembers failed priorities
    end       Reporter -> designer notes
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time

from .a2a_kit import AgentContext, Peers
from .agents import OWNER, ROSTER, SPECIALISTS, WORKER_KEYS

C = {"dim": "\033[2m", "b": "\033[1m", "cyan": "\033[36m", "mag": "\033[35m", "yel": "\033[33m",
     "grn": "\033[32m", "red": "\033[31m", "blue": "\033[34m", "x": "\033[0m"}
if os.environ.get("NO_COLOR"):
    C = {k: "" for k in C}


ANSI = re.compile(r"\033\[[0-9;]*m")


def out(text: str = "") -> None:
    print(text, flush=True)


def assign(diagnosis: list, k: int) -> tuple[dict, list]:
    """Route each diagnosed problem to the specialist that owns it.

    Same budget split as the single-agent loop: the top problem gets k-2 plans, the next two
    problems one plan each. With only two problems the Director adds one merged plan (top
    problem + second problem, from two different specialists); spare slots go to exploration.
    Returns ({specialist: [{"problem", "n"}]}, problems_to_merge).
    """
    probs = [d["problem"] for d in diagnosis][:3] or ["fine-tune"]
    quota = [max(1, k - 2)] + [1] * (len(probs) - 1)
    plan: dict[str, list] = {}
    used = 0
    def give(spec: str, prob: str, n: int) -> None:
        for a in plan.setdefault(spec, []):
            if a["problem"] == prob:
                a["n"] += n
                return
        plan[spec].append({"problem": prob, "n": n})

    for prob, q in zip(probs, quota):
        q = min(q, k - used)
        if q <= 0:
            break
        if prob == "fine-tune":      # nothing clearly wrong: small changes from two specialists
            give("reward", "explore", (q + 1) // 2)
            if q // 2:
                give("layout", "explore", q // 2)
        else:
            give(OWNER.get(prob, "reward"), prob, q)
        used += q
    merge = probs[:2] if len(probs) > 1 and used < k else []
    spare = k - used - (1 if merge else 0)
    for i in range(max(0, spare)):   # spare slots: exploration, alternating rewards and layout
        give("reward" if i % 2 == 0 else "layout", "explore", 1)
    return plan, merge


class Director:
    def __init__(self, base_port: int, mcp_url: str):
        self.base_port = base_port
        self.mcp_url = mcp_url
        self.peers = Peers()
        self.trace: list[dict] = []
        self.log: list[str] = []
        self.round = 0
        self.quiet = 0

    def say(self, text: str, plain: str | None = None) -> None:
        if self.quiet < 1:
            out(text)
        self.log.append(ANSI.sub("", plain if plain is not None else text))

    async def call(self, key: str, payload: dict, label: str | None = None) -> dict:
        name = ROSTER[key][0]
        t0 = time.perf_counter()
        res = await self.peers.send(key, payload)
        ms = round((time.perf_counter() - t0) * 1000)
        tr = res.pop("_trace", {})
        mcp = [c["tool"] for c in tr.get("mcp_calls", [])]
        self.trace.append({"round": self.round, "from": "Director", "to": name,
                           "skill": payload.get("skill", "?"), "ms": ms, "mcp": mcp})
        mcp_txt = f"  {C['mag']}MCP {', '.join(sorted(set(mcp)))}{C['x']}" if mcp else ""
        self.say(f" {C['cyan']}A2A{C['x']}  Director → {C['b']}{name}{C['x']} "
                 f"{C['dim']}[{payload.get('skill', '?')}]{C['x']}{mcp_txt}  {C['dim']}{ms} ms{C['x']}",
                 f"[A2A] Director -> {name} [{payload.get('skill', '?')}]"
                 + (f" MCP {', '.join(sorted(set(mcp)))}" if mcp else "") + f" ({ms} ms)")
        return res

    def detail(self, text: str) -> None:
        self.say(f"      {text}", f"      {text}")

    async def discover(self) -> list[dict]:
        cards = []
        for key in WORKER_KEYS:
            url = f"http://127.0.0.1:{self.base_port + ROSTER[key][1]}"
            card = await self.peers.discover(key, url)
            cards.append({"key": key, "name": card.name, "url": url,
                          "skills": [s.id for s in card.skills], "description": card.description})
        return cards

    # ------------------------------------------------------------------ the job
    async def optimise(self, p: dict) -> dict:
        rounds, k, runs, seed = int(p.get("rounds", 6)), int(p.get("candidates", 4)), int(p.get("runs", 150)), int(p.get("seed", 4))
        chaos_round = p.get("chaos_round")
        self.quiet = int(p.get("quiet", 0))
        sim_seed = seed * 100000 + 1
        t_start = time.perf_counter()
        cards = await self.discover()
        self.say(f"\n{C['b']}Director{C['x']} discovered {len(cards)} agents from their A2A Agent Cards:",
                 f"Director discovered {len(cards)} agents from their A2A Agent Cards:")
        for c in cards:
            self.detail(f"{c['name']:<22} {C['dim']}{c['url']}  skills: {', '.join(c['skills'])}{C['x']}")

        # ---------------------------------------------------------- round 0
        self.round = 0
        self.say(f"\n{C['b']}━━ Setup ━━{C['x']}", "== Setup ==")
        if p.get("brief"):          # experiments pass one shared brief to every method
            rv = {"brief": p["brief"], "labeled": [], "labeler": "provided"}
            self.detail("design brief provided by the caller")
        else:
            rv = await self.call("review", {"skill": "build_brief", "reviews_path": p["reviews_path"],
                                            "limit": p.get("review_limit", 400)})
            self.detail(rv["note"])
        brief = rv["brief"]
        self.detail(f"brief: target completion {brief['target_completion']:.0%}, "
                    f"target HP lost {brief['target_tension']:.0%}")
        arch = await self.call("architect", {"skill": "initial_level", "mode": p.get("mode", "auto"),
                                             "grid": p.get("grid"), "name": p.get("level_name"),
                                             "brief": brief, "seed": seed})
        self.detail(arch["note"])
        level = arch["level"]
        pt = await self.call("playtest", {"skill": "playtest", "grids": [level["grid"]], "runs": runs,
                                          "seed": sim_seed, "brief": brief})
        self.cluster_line(pt["job"])
        r0 = pt["results"][0]
        best = {"level": level, "metrics": r0["metrics"], "quality": r0["quality"], "plan": "initial design",
                "agent": ROSTER["architect"][0]}
        self.detail(f"baseline score {C['b']}{best['quality']['total']:.3f}{C['x']}, "
                    f"completion {best['metrics']['completion_rate']:.0%}")
        history = [self.record(0, [{"plan": "initial design", "agent": ROSTER["architect"][0], "edit_log": [],
                                    "grid": level["grid"], **r0}], best, "accepted", pt["job"], {}, [])]
        tried: dict[str, int] = {}
        feedback: list = []
        avoid: list = []          # shared team memory: edit lists already tried on the current best level

        # ---------------------------------------------------------- optimisation rounds
        for r in range(1, rounds + 1):
            self.round = r
            self.say(f"\n{C['b']}━━ Round {r} ━━{C['x']}", f"== Round {r} ==")
            dg = await self.call("playtest", {"skill": "diagnose", "best": best, "brief": brief, "tried": tried})
            crit = dg["critique"]
            if tried:
                self.detail(f"{C['dim']}memory of failed priorities: {tried}{C['x']}")
            for d in crit["diagnosis"][:3]:
                self.detail(f"{d['problem']}: {d.get('cause', '')}")
            routing, merge = assign(crit["diagnosis"], k)
            self.detail(f"priority {C['yel']}{crit['priority']}{C['x']}; routing: "
                        + "; ".join(f"{ROSTER[sp][0]} ← " + ", ".join(f"{a['problem']} x{a['n']}" for a in al)
                                    for sp, al in routing.items()))

            # the specialists work in parallel
            jobs = {sp: self.call(sp, {"skill": "propose", "assignments": al, "critique": crit, "best": best,
                                       "brief": brief, "round": r, "seed": seed, "feedback": feedback,
                                       "avoid": avoid})
                    for sp, al in routing.items()}
            answers = await asyncio.gather(*jobs.values(), return_exceptions=True)
            plans = []
            for sp, a in zip(jobs, answers):
                if isinstance(a, Exception):
                    self.detail(f"{C['red']}{ROSTER[sp][0]} failed: {a}{C['x']}")
                    continue
                plans += a["plans"]
            if merge:   # the Director combines two specialists' ideas into one extra plan
                parts = [next((pl for pl in plans if pl.get("problem") == pr), None) for pr in merge]
                if all(parts):
                    plans.append({"problem": "+".join(merge), "agent": "Director (merge)",
                                  "edits": parts[0]["edits"] + parts[1]["edits"],
                                  "rationale": f"merge {parts[0]['agent'].split()[0]} + {parts[1]['agent'].split()[0]}: "
                                               + parts[0]["rationale"].split(": ", 1)[-1] + " + "
                                               + parts[1]["rationale"].split(": ", 1)[-1]})
            for pl in plans:
                self.detail(f"{C['dim']}{pl['agent']:<22}{C['x']} {pl['rationale'][:78]}")

            qa = await self.call("qa", {"skill": "validate_plans", "grid": best["level"]["grid"], "plans": plans,
                                        "seed": seed, "round": r})
            self.detail(qa["note"] + "".join(f"; rejected {x.get('agent', '?')}: {x['why'][:50]}"
                                             for x in qa["rejected"][:2]))
            cands = qa["candidates"]

            if chaos_round and r == int(chaos_round):
                ctx = AgentContext("Director", self.mcp_url)
                await ctx.mcp("inject_fault", {"jobs": 1})
                self.detail(f"{C['red']}fault injection armed: a simulation worker will crash during this job{C['x']}")

            pt = await self.call("playtest", {"skill": "playtest", "grids": [c["grid"] for c in cands],
                                              "runs": runs, "seed": sim_seed, "brief": brief})
            self.cluster_line(pt["job"])
            scored = [{**c, **res} for c, res in zip(cands, pt["results"])]
            top = max(scored, key=lambda s: s["quality"]["total"])
            for s in scored:
                mark = f" {C['grn']}← best{C['x']}" if s is top else ""
                who = s["agent"].replace(" Specialist", "").replace(" (merge)", "")
                self.detail(f"{who[:10]:<10} {s['plan'][:56]:<56} score {s['quality']['total']:.3f} "
                            f"compl {s['metrics']['completion_rate']:.0%}{mark}")
            prev = best["quality"]["total"]
            for pl in plans:
                k_ = json.dumps(pl["edits"], sort_keys=True)
                if k_ not in avoid:
                    avoid.append(k_)
            if top["quality"]["total"] > prev + 1e-4:
                avoid = []        # new best level: earlier attempts no longer apply
                best = {"level": {"name": f"r{r}", "grid": top["grid"], "notes": ""}, "metrics": top["metrics"],
                        "quality": top["quality"], "plan": top["plan"], "agent": top["agent"]}
                decision = "accepted"
                self.say(f" {C['grn']}DECIDE{C['x']} accepted {top['agent']}'s plan: {prev:.3f} → "
                         f"{C['b']}{best['quality']['total']:.3f}{C['x']}",
                         f"[Director] accepted {top['agent']}'s plan: {prev:.3f} -> {best['quality']['total']:.3f}")
            else:
                decision = "rejected (kept previous best)"
                tried[crit["priority"]] = tried.get(crit["priority"], 0) + 1
                self.say(f" {C['yel']}DECIDE{C['x']} no candidate beat {prev:.3f}: rolled back; "
                         f"remembering that '{crit['priority']}' fixes failed",
                         f"[Director] rejected all; rolled back; tried {tried}")
            feedback = [{"agent": s["agent"], "plan": s["plan"][:100], "total": s["quality"]["total"],
                         "completion": s["metrics"]["completion_rate"],
                         "accepted": s is top and decision == "accepted"} for s in scored]
            history.append(self.record(r, scored, best, decision, pt["job"], crit, qa["rejected"],
                                       top if decision == "accepted" else None))
            if best["quality"]["total"] >= 0.92:
                self.say(" Director: quality target reached, stopping early")
                break

        # ---------------------------------------------------------- report
        self.round = len(history)
        accepted = [{"round": h["round"], "agent": h.get("accepted_agent"), "edits": h["accepted_edits"]}
                    for h in history[1:] if h["accepted_plan"]]
        rep = await self.call("reporter", {"skill": "write_notes", "first": history[0], "last": history[-1],
                                           "brief": brief, "accepted": accepted})
        self.say(f"\n {C['b']}Designer notes{C['x']} ({rep['source']}): {rep['notes']}",
                 f"[Reporter] {rep['notes']}")
        return {"brief": brief, "labeled": rv["labeled"], "labeler": rv["labeler"],
                "initial_level": history[0]["best_level"], "final_level": best["level"],
                "history": history, "log": self.log, "designer_notes": rep["notes"],
                "notes_source": rep["source"], "level_source": arch["source"],
                "agents": cards, "a2a_trace": self.trace,
                "seconds": round(time.perf_counter() - t_start, 1)}

    def cluster_line(self, job: dict) -> None:
        pw = job.get("per_worker_sims", {})
        mx = max(pw.values()) if pw else 1
        alive = job.get("workers_alive", len(pw))
        crashed = len(job.get("events", []))
        self.detail(f"{C['blue']}cluster{C['x']}: {job['sims']} sims in {job['seconds']:.2f} s "
                    f"({job['sims_per_second']:.0f}/s) on {alive} workers"
                    + (f" ({crashed} replaced)" if crashed else ""))
        self.detail("  ".join(f"{w} {'█' * max(1, round(8 * n / mx))} {n}" for w, n in pw.items()))
        for ev in job.get("events", []):
            self.detail(f"{C['red']}worker W{ev['worker']} crashed → master re-queued {ev['requeued_sims']} sims"
                        + (f" → replacement W{ev['replacement']} started" if ev.get("replacement") else "")
                        + f"; job still completed{C['x']}")

    @staticmethod
    def record(rnd, scored, best, decision, job, crit, rejected, top=None) -> dict:
        from ..agents import _metrics_brief
        n_sims = job["sims"]
        return {
            "round": rnd,
            "candidates": [{"plan": s["plan"], "agent": s.get("agent"), "edit_log": s.get("edit_log", []),
                            "quality": s["quality"], "metrics": _metrics_brief(s["metrics"]),
                            "level": {"name": "candidate", "grid": s["grid"]}} for s in scored],
            "decision": decision,
            "accepted_plan": (top["plan"] if top else ("initial design" if rnd == 0 else None)),
            "accepted_agent": (top["agent"] if top else None),
            "accepted_edits": (top.get("edit_log", []) if top else []),
            "best_score": best["quality"]["total"], "best_quality": best["quality"],
            "best_metrics": _metrics_brief(best["metrics"]), "best_level": best["level"],
            "sweep_seconds": job["seconds"], "sims": n_sims, "cluster_job": job,
            "critique": crit, "rejected": rejected,
        }


async def director_handler_factory(base_port: int, mcp_url: str):
    async def handler(payload: dict, ctx) -> dict:
        d = Director(base_port, mcp_url)
        try:
            return await d.optimise(payload)
        finally:
            await d.peers.close()
    return handler


def enable_ansi() -> None:
    if sys.platform == "win32":
        os.system("")  # turns on ANSI colour handling in the Windows console
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
