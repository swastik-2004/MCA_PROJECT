# Working on LevelForge together

Every change goes through a pull request. GitHub Actions tests it on Linux and Windows, a teammate
reviews it, and when it is merged into `main` the website (game, reports, agent map, paper) is
rebuilt and deployed to GitHub Pages automatically.

```
your branch ──push──► Pull request ──► CI: tests (Linux + Windows) ──► review ──► merge to main
                                                                                      │
                                       GitHub Pages ◄── deploy ◄── build website ◄────┘
```

## One-time setup (repo owner)

1. **Add your friends:** repo **Settings → Collaborators → Add people** (their GitHub usernames).
2. **Turn on Pages:** **Settings → Pages → Build and deployment → Source: GitHub Actions**.
   Private repo? Pages needs GitHub Pro, which is free with the GitHub Student Developer Pack.
   Otherwise make the repo public.
3. **Protect `main`:** **Settings → Branches → Add branch ruleset** (or classic rule) for `main`:
   require a pull request with 1 approval, and require the status checks
   `Tests (ubuntu-latest)` and `Tests (windows-latest)` to pass. Nobody pushes to `main` directly.

## One-time setup (everyone)

```bat
git clone https://github.com/swastik-2004/MCA_PROJECT.git
cd MCA_PROJECT
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt pytest
copy .env.example .env          :: put your OWN Groq key in .env; it is git-ignored, never commit it
python -m pytest -q             :: should say "9 passed"
```

## Every change

```bat
git switch main
git pull
git switch -c genai/better-review-labels      :: one branch per change: <role>/<what>
:: ... edit code ...
python -m pytest -q                           :: run the tests before you push
git add -A
git commit -m "Label reviews in batches of 32"
git push -u origin genai/better-review-labels
```

Then open the pull request on GitHub (it shows a "Compare & pull request" button), ask a teammate
to review, wait for the green checks, and merge. The site updates a few minutes later.

## Who owns what

| Role | Branch prefix | Main files |
|---|---|---|
| Agentic AI lead / integration | `agents/` | `levelforge/team/`, `levelforge/agents.py`, `levelforge/edits.py`, `run_team.py`, `run_demo.py` |
| GenAI / LLM | `genai/` | `levelforge/reviews.py`, `levelforge/llm.py`, `data/` |
| Multicore / HPC | `mca/` | `levelforge/cluster.py`, `levelforge/parallel.py`, `benchmark*.py` |
| Digital twin, evaluation, game | `twin/` | `levelforge/simulator.py`, `levelforge/metrics.py`, `experiments.py`, `levelforge/shooter.py` |

Anyone can review anyone's pull request; the owner of the files should approve.

## Rules

- Never commit `.env` or any API key. CI runs without a key (rule-based agents only).
- Keep the tests green. If you change behaviour on purpose, update the test in `tests/` in the same pull request.
- `outputs*/`, `site/` and `breach.html` are generated and git-ignored.
- To change level 3 of the online game, refresh `showcase/llm_run/report.html` (see `showcase/README.md`).
