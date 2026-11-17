"""Digital twin: levels, simulator, edits and the quality score."""
from conftest import ROOT

from levelforge.edits import apply_edits
from levelforge.generator import random_candidate
from levelforge.level import Level, validate
from levelforge.metrics import aggregate, quality
from levelforge.simulator import PERSONAS, simulate

PROBLEM = ROOT / "data" / "problem_level.txt"


def test_problem_level_is_playable():
    assert validate(Level.load(PROBLEM)) == []


def test_generated_levels_are_playable():
    for seed in range(10):
        assert validate(random_candidate(seed)) == [], f"seed {seed}"


def test_simulation_is_deterministic():
    level = Level.load(PROBLEM).to_dict()
    for persona in PERSONAS:
        assert simulate(level, persona, 7) == simulate(level, persona, 7)


def test_edits_never_break_a_level():
    level = Level.load(PROBLEM)
    plans = [[{"op": "add", "tile": "M", "count": 4, "where": "main"}],
             [{"op": "remove", "tile": "T", "count": 4, "where": "any"}],
             [{"op": "add_loop", "count": 2}, {"op": "add", "tile": "C", "count": 3, "where": "side"}],
             [{"op": "add_lock"}], [{"op": "remove_lock"}], [{"op": "nonsense"}]]
    for seed, plan in enumerate(plans):
        new, _log = apply_edits(level, plan, seed=seed)
        assert validate(new) == [], plan


def test_quality_score_is_between_0_and_1():
    level = Level.load(PROBLEM).to_dict()
    runs = [simulate(level, p, s) for p in PERSONAS for s in range(20)]
    q = quality(aggregate(runs))
    assert 0.0 <= q["total"] <= 1.0
    assert set(q) >= {"balance", "engagement", "flow", "skill", "tension"}
