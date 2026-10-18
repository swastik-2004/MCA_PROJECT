"""
Aggregate per-run results into level metrics and a single quality score.

The quality score is the objective the agent loop tries to improve. Its targets
come from the design brief (which is derived from player reviews), so the same
level can score differently for different player audiences.
"""
from __future__ import annotations

from statistics import mean

DEFAULT_BRIEF = {
    "target_completion": 0.65,   # share of all playthroughs that reach the exit
    "target_tension": 0.40,      # share of HP lost by players who finish
    "weights": {"balance": 0.35, "engagement": 0.20, "flow": 0.15,
                "skill": 0.15, "tension": 0.15},
}


def _clip(x: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, x))


def _rate(runs, key) -> float:
    return mean(1.0 if r[key] else 0.0 for r in runs) if runs else 0.0


def aggregate(runs: list[dict]) -> dict:
    by = {}
    for r in runs:
        by.setdefault(r["persona"], []).append(r)
    done = [r for r in runs if r["completed"]]
    explorer = by.get("explorer", [])
    m = {
        "runs": len(runs),
        "completion_rate": _rate(runs, "completed"),
        "death_rate": _rate(runs, "died"),
        "timeout_rate": _rate(runs, "timeout"),
        "avg_steps_completed": mean(r["steps"] for r in done) if done else 0.0,
        "avg_damage": mean(r["damage_taken"] for r in runs) if runs else 0.0,
        "avg_fights": mean(r["fights"] for r in runs) if runs else 0.0,
        "avg_trap_hits": mean(r["trap_hits"] for r in runs) if runs else 0.0,
        "backtrack_ratio": mean(
            (r["steps"] - (r["unique_tiles"] - 1)) / r["steps"] for r in runs if r["steps"]
        ) if runs else 0.0,
        "exploration": mean(r["unique_tiles"] / max(1, r["open_tiles"]) for r in runs) if runs else 0.0,
        "coin_collection": mean(
            r["coins_collected"] / r["coins_total"] for r in explorer if r["coins_total"]
        ) if explorer and explorer[0]["coins_total"] else 0.0,
        "hp_lost_by_finishers": mean(r["damage_taken"] / 10 for r in done) if done else 1.0,
        "per_persona_completion": {p: _rate(rs, "completed") for p, rs in sorted(by.items())},
        "per_persona_death": {p: _rate(rs, "died") for p, rs in sorted(by.items())},
    }
    return m


def quality(metrics: dict, brief: dict | None = None) -> dict:
    """Return component scores (0..1) and the weighted total."""
    b = {**DEFAULT_BRIEF, **(brief or {})}
    w = {**DEFAULT_BRIEF["weights"], **b.get("weights", {})}
    tc, tt = b["target_completion"], b["target_tension"]

    cr = metrics["completion_rate"]
    balance = _clip(1 - abs(cr - tc) / max(tc, 1 - tc))

    engagement = _clip(0.6 * metrics["coin_collection"] + 0.4 * min(1.0, metrics["exploration"] / 0.6))

    flow = _clip(1 - metrics["backtrack_ratio"] * 2)

    pc = metrics["per_persona_completion"]
    # Skill expression: careful play should beat reckless play, but not trivially.
    spread = pc.get("cautious", 0) - pc.get("rusher", 0)
    skill = _clip(spread / 0.35) if pc.get("cautious", 0) > 0 else 0.0

    tension = _clip(1 - abs(metrics["hp_lost_by_finishers"] - tt) / max(tt, 1 - tt))

    comps = {"balance": balance, "engagement": engagement, "flow": flow,
             "skill": skill, "tension": tension}
    total = sum(comps[k] * w[k] for k in comps) / sum(w.values())
    return {**{k: round(v, 4) for k, v in comps.items()}, "total": round(total, 4)}
