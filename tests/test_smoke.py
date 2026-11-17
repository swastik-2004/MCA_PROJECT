"""End-to-end smoke tests: the two demo scripts run offline and write their outputs."""
import json
import os
import subprocess
import sys

from conftest import ROOT

ENV = {**os.environ, "NO_COLOR": "1", "PYTHONIOENCODING": "utf-8"}


def run(args, timeout=600):
    r = subprocess.run([sys.executable, *args], cwd=ROOT, env=ENV, capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=timeout)
    assert r.returncode == 0, (r.stdout[-3000:] + "\n" + r.stderr[-3000:])
    return r


def test_single_agent_demo(tmp_path):
    out = tmp_path / "demo"
    run(["run_demo.py", "--offline", "--level", "data/problem_level.txt", "--rounds", "1", "--runs", "20",
         "--workers", "2", "--no-open", "--out", str(out)])
    assert (out / "report.html").stat().st_size > 10_000
    history = json.loads((out / "history.json").read_text(encoding="utf-8"))
    assert len(history) == 2


def test_agent_team(tmp_path):
    out = tmp_path / "team"
    run(["run_team.py", "--offline", "--level", "data/problem_level.txt", "--rounds", "2", "--runs", "20",
         "--workers", "2", "--chaos", "1", "--no-open", "--out", str(out),
         "--base-port", "9300", "--mcp-port", "9350"])
    res = json.loads((out / "team_result.json").read_text(encoding="utf-8"))
    assert len(res["history"]) == 3
    assert len(res["agents"]) == 8                       # the Director found all 8 workers
    skills = {t["skill"] for t in res["a2a_trace"]}
    assert {"build_brief", "playtest", "diagnose", "propose", "validate_plans", "write_notes"} <= skills
    crashes = [e for h in res["history"] for e in h["cluster_job"].get("events", [])]
    assert crashes, "the injected worker crash should be recorded"
