"""
GenAI review mining: player reviews -> design-problem taxonomy -> design brief.

Rather than plain sentiment analysis, each review is turned into actionable
game-design problems (e.g. "too hard", "repetitive", "confusing layout").
Those problem frequencies then set the targets and weights that the level
optimizer is scored against.

Online mode: an LLM labels reviews in batches. Batches are sent concurrently
with a thread pool (LLM calls are I/O-bound, so threads are the right tool here,
in contrast to the CPU-bound simulator which uses processes).
Offline mode: a keyword classifier produces the same labels.
"""
from __future__ import annotations

import csv
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from .llm import LLM, LLMError
from .metrics import DEFAULT_BRIEF

# problem id -> (description, keywords for the offline classifier)
TAXONOMY = {
    "too_hard":        ("Difficulty too high / punishing",
                        ["too hard", "brutal", "punishing", "insane", "wrecked", "impossible",
                         "too strong", "hit like", "gave up", "quit", "frustrat", "difficulty spike",
                         "not enough heal", "too rare", "barely any health", "forgiving"]),
    "too_easy":        ("Too easy / no challenge",
                        ["too easy", "no challenge", "never felt in danger", "run past"]),
    "repetitive":      ("Repetitive / lacks variety",
                        ["repetitive", "same", "monotonous", "samey", "variety", "boring", "grindy"]),
    "confusing_layout": ("Confusing layout / backtracking",
                        ["lost", "confusing", "backtrack", "dead end", "back and forth", "retrace",
                         "maze", "walking back", "shortcut"]),
    "unfair_traps":    ("Unfair traps on forced routes",
                        ["trap"]),
    "empty_levels":    ("Little reward for exploring",
                        ["empty", "nothing to find", "no reason to explore", "no reward",
                         "nothing to do", "lifeless"]),
}
POSITIVES = {
    "exploration": ["explor", "treasure", "secret", "hidden", "coins"],
    "tense_combat": ["tense", "every fight", "challenging but fair", "tough but", "risky"],
    "skill_rewarded": ["careful", "rewarded", "pays off", "patterns"],
}


# ---------------------------------------------------------------------------
def load_reviews(path: str | Path, limit: int | None = None) -> list[dict]:
    with open(path, newline="", encoding="utf-8", errors="ignore") as f:
        reader = csv.DictReader(f)
        cols = {c.lower(): c for c in (reader.fieldnames or [])}
        text_col = next((cols[c] for c in ("review_text", "review", "content", "text") if c in cols), None)
        if text_col is None:
            raise ValueError(f"no review text column found in {path}; columns: {reader.fieldnames}")
        out = []
        for i, row in enumerate(reader):
            text = (row.get(text_col) or "").strip()
            if len(text) < 8:
                continue
            out.append({"id": len(out) + 1, "text": text[:600]})
            if limit and len(out) >= limit:
                break
    return out


def classify_offline(text: str) -> tuple[list[str], list[str]]:
    t = text.lower()
    problems = [k for k, (_, kws) in TAXONOMY.items() if any(kw in t for kw in kws)]
    positives = [k for k, kws in POSITIVES.items() if any(kw in t for kw in kws)]
    # a review praising difficulty is not a "too hard" complaint
    if "too hard" not in t and any(p in positives for p in ("tense_combat", "skill_rewarded")) \
            and "too_hard" in problems and "forgiving" not in t:
        problems.remove("too_hard")
    return problems, positives


LABEL_SYSTEM = ("You are a game-design analyst. For each player review, extract actionable "
                "design problems using ONLY these ids: " + ", ".join(TAXONOMY) +
                "; and praised aspects using ONLY: " + ", ".join(POSITIVES) + ".")


def _label_batch(llm: LLM, batch: list[dict]) -> list[dict]:
    user = ("Label these reviews. Return a JSON object "
            '{"reviews": [{"id": <id>, "problems": [...], "positives": [...]}, ...]}.\n\n' +
            "\n".join(f'{r["id"]}: {r["text"]}' for r in batch))
    data = llm.chat_json(LABEL_SYSTEM, user, temperature=0.1)
    if isinstance(data, dict):
        data = data.get("reviews") or data.get("labels") or list(data.values())[0]
    by_id = {}
    for item in data:
        try:
            by_id[int(item["id"])] = item
        except (KeyError, TypeError, ValueError):
            continue
    out = []
    for r in batch:
        item = by_id.get(r["id"])
        if item is None:
            p, pos = classify_offline(r["text"])
            out.append({**r, "problems": p, "positives": pos, "labeler": "rules"})
            continue
        p = [x for x in item.get("problems", []) if x in TAXONOMY]
        pos = [x for x in item.get("positives", []) if x in POSITIVES]
        out.append({**r, "problems": p, "positives": pos, "labeler": "llm"})
    return out


def label_reviews(reviews: list[dict], llm: LLM, batch_size: int = 24, threads: int = 2) -> list[dict]:
    if not llm.online:
        return [{**r, **dict(zip(("problems", "positives"), classify_offline(r["text"]))),
                 "labeler": "rules"} for r in reviews]
    batches = [reviews[i:i + batch_size] for i in range(0, len(reviews), batch_size)]

    def work(b):
        try:
            return _label_batch(llm, b)
        except LLMError:
            return [{**r, **dict(zip(("problems", "positives"), classify_offline(r["text"]))),
                     "labeler": "rules"} for r in b]

    with ThreadPoolExecutor(max_workers=threads) as ex:
        results = list(ex.map(work, batches))
    return [r for batch in results for r in batch]


# ---------------------------------------------------------------------------
ACTIONS = {
    "too_hard": ("Monsters and traps on the critical path", "Too much unavoidable damage",
                 "Remove hazards from the main route, add a health potion",
                 "Completion rate rises toward target"),
    "too_easy": ("Main route", "Exit reachable with no risk",
                 "Add a monster or trap to the main route",
                 "Completion rate falls toward target; HP lost by finishers rises"),
    "repetitive": ("Encounters and rewards", "Low encounter/reward variety",
                   "Add optional coins and side encounters",
                   "Explorer coin collection and exploration rise"),
    "confusing_layout": ("Level topology", "Dead ends force backtracking",
                         "Open a wall to create a loop/shortcut",
                         "Backtrack ratio falls"),
    "unfair_traps": ("Traps on forced corridors", "Damage players cannot avoid",
                     "Move traps off the main route",
                     "Cautious players avoid damage; skill expression rises"),
    "empty_levels": ("Side areas", "No reward for exploring",
                     "Place coins/potions off the main route",
                     "Coin collection and exploration rise"),
}


def build_brief(labeled: list[dict]) -> dict:
    n = max(1, len(labeled))
    counts = Counter(p for r in labeled for p in r["problems"])
    pos = Counter(p for r in labeled for p in r["positives"])
    share = {k: counts.get(k, 0) / n for k in TAXONOMY}

    def clip(x, lo, hi):
        return max(lo, min(hi, x))

    hard_vs_easy = share["too_hard"] - share["too_easy"]
    target_completion = round(clip(DEFAULT_BRIEF["target_completion"] + 0.35 * hard_vs_easy, 0.45, 0.85), 3)
    target_tension = round(clip(DEFAULT_BRIEF["target_tension"] - 0.3 * hard_vs_easy, 0.2, 0.6), 3)
    w = dict(DEFAULT_BRIEF["weights"])
    w["engagement"] += 0.4 * (share["repetitive"] + share["empty_levels"])
    w["flow"] += 0.4 * share["confusing_layout"]
    w["skill"] += 0.4 * share["unfair_traps"]
    w = {k: round(v, 3) for k, v in w.items()}

    goals = []
    for k, s in sorted(share.items(), key=lambda kv: -kv[1]):
        if s == 0:
            continue
        comp, cause, mod, test = ACTIONS[k]
        goals.append({"problem": k, "description": TAXONOMY[k][0], "share": round(s, 3),
                      "affected_component": comp, "possible_cause": cause,
                      "design_modification": mod, "test": test})
    return {
        "reviews_analyzed": len(labeled),
        "problem_share": {k: round(v, 3) for k, v in share.items()},
        "praised": {k: round(pos.get(k, 0) / n, 3) for k in POSITIVES},
        "target_completion": target_completion,
        "target_tension": target_tension,
        "weights": w,
        "design_goals": goals,
    }
