"""
Play LevelForge: Breach - a first-person 3D shooter built from your runs' levels.

    python play.py             # build + open the 3D game from all runs in outputs*/
    python play.py --2d        # the top-down 2D version of the same game
    python play.py --arcade    # the older pixel-art arcade view of the newest run

No API calls and no re-simulation: it reads the run data saved in each report.html.
Level 1/2 come from the rule-based run (outputs/), level 3 from the LLM run (outputs_llm/).
"""
from __future__ import annotations

import sys
import webbrowser
from pathlib import Path

from levelforge.arcade import build_arcade, data_from_report
from levelforge.shooter import write_game

ROOT = Path(__file__).parent


def open_arcade() -> Path:
    reports = sorted(ROOT.glob("outputs*/report.html"), key=lambda q: q.stat().st_mtime, reverse=True)
    if not reports:
        raise SystemExit("No runs found yet. Run: python run_demo.py")
    arcade = reports[0].parent / "arcade.html"
    arcade.write_text(build_arcade(data_from_report(reports[0])), encoding="utf-8")
    webbrowser.open(arcade.resolve().as_uri())
    return arcade


def open_game(mode: str = "3d") -> Path:
    try:
        path = write_game(ROOT, mode=mode)
    except ValueError as e:
        raise SystemExit(str(e))
    webbrowser.open(path.resolve().as_uri())
    return path


if __name__ == "__main__":
    if "--arcade" in sys.argv:
        print(f"Arcade opened: {open_arcade()}")
    elif "--2d" in sys.argv:
        print(f"2D game opened: {open_game('2d')}")
        print("Press ENTER. WASD move, mouse aim, click fire, SPACE dash, R reload, ESC pause, M music.")
    else:
        print(f"3D game opened: {open_game('3d')}")
        print("Press ENTER, then click the game to capture the mouse. Mouse look, WASD move, click fire,")
        print("SHIFT sprint, SPACE dash, R reload, ESC pause, M music, G graphics quality.")
