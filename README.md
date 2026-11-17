# LevelForge
### An Agentic Digital Twin Framework for Feedback-Driven Autonomous Game-Level Generation and Optimization

Player reviews are mined into design problems (GenAI), an agent loop proposes level edits
(Agentic AI, LangGraph), and every candidate level is play-tested by thousands of simulated
players running in parallel worker processes (MCA / HPC). The output is an optimised level,
research-grade metrics, scaling benchmarks, and a playable browser prototype.

```
reviews ─► GenAI review mining ─► design brief (targets + weights)
                                        │
                     ┌──────────────────▼──────────────────┐
                     │  GENERATOR  (LLM / procedural)      │
                     └──────────────────┬──────────────────┘
                                        ▼
      ┌──────────► SIMULATE: N candidates x 450 playthroughs on 5 processes
      │                  (rusher / cautious / explorer bots)  -> accept / reject
      │                                 │
  OPTIMIZER  ◄──── CRITIC (diagnosis + memory of failed fixes)
  (k edit plans)                        │
                                        ▼
                         FINALIZE: designer notes + report.html
```

---

## 1. Setup (Windows, once)

Needs Python 3.10 or newer. Open **Command Prompt** in this folder:

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
```

## 2. Run the demo (5 parallel workers)

```bat
python run_demo.py
```

Then open `outputs\report.html` in your browser. It contains the review analysis, the
score-per-round chart, every candidate the agents tried, before/after levels, animated bot
replays, and the final level as a playable game (arrow keys / WASD).

Useful options: `--workers 5 --rounds 6 --runs 150 --candidates 4 --seed 4`

### Optimise an existing level (the "level players complained about")

```bat
python run_demo.py --offline --level data\problem_level.txt --out outputs_problem
```

`--level` loads an existing level (a text grid or a `.json` from a previous run) and optimises it
instead of generating a new one. `data\problem_level.txt` is the same starting level as the main
rule-based demo, so it reproduces the 0.477 → 0.895 result. Draw your own level in the same tile
format (see the comments at the top of the file); the run stops with a clear message if the level is
not playable (for example, the exit cannot be reached).

### Play the game (for the presentation)

`run_demo.py` builds and opens **LevelForge: Breach** (`breach.html`) when it finishes: a
first-person 3D shooter (Three.js) whose three levels come from your runs. Reopen any time:

```bat
python play.py            :: 3D first-person game (levels from outputs\ and outputs_llm\)
python play.py --2d       :: top-down 2D version of the same game
python play.py --arcade   :: the older pixel-art arcade view
```

- Level 1 **BEFORE AI**: the generated level before optimisation (rule run, `outputs\`)
- Level 2 **AI-OPTIMISED**: the same level after the agents fixed it (rule run)
- Level 3 **AI-DESIGNED**: the level the LLM designed and optimised (`outputs_llm\`)

Controls: press ENTER, then click the game to capture the mouse. Mouse look, WASD move, click fire,
SHIFT sprint, SPACE dash, R reload, ESC pause/release mouse, M music, G graphics quality.
If it runs slowly it switches to low graphics by itself. On laptops with two GPUs, set Chrome to
"High performance" (Windows Settings > System > Display > Graphics) so it uses the RTX card.
The menu also has **AI LAB**: the optimisation chart, the agent log and the simulated players' paths.

How to explain it: the shooter is the game; the simulator is its *digital twin*, a simplified
turn-based model with the same level layout and the same values (health, drone health, mine
damage, med-kit healing). All research numbers are measured on the twin.

## 2b. The agent team: A2A + MCP + master-worker (main demo)

`run_team.py` runs the same optimisation as a **team of 9 agents** that talk over the
**A2A protocol**, use the digital twin through an **MCP server**, and play-test on an explicit
**master-worker** simulation cluster.

```bat
pip install -r requirements.txt                                  :: once: adds a2a-sdk and mcp
python run_team.py --level data\problem_level.txt                :: LLM agents (needs the Groq key)
python run_team.py --level data\problem_level.txt --offline      :: rule-based agents, no API calls
python run_team.py --level data\problem_level.txt --chaos        :: a simulation worker crashes in round 2
python run_team.py --start llm                                   :: the Level Architect (LLM) designs the level
```

```
                 you ── A2A ──► DIRECTOR (master agent, :9100)
                                   │  discovers the others from their Agent Cards, then delegates:
     ┌────────────┬────────────────┼──────────────┬───────────────┬──────────────┬──────────┐
 Review       Level          Playtest       Difficulty /      QA            Reporter
 Analyst      Architect      Analyst        Layout / Reward   Validator     (:9108)
 (:9101)      (:9102)        (:9103)        Specialists       (:9107)
                 │              │           (:9104-9106)         │
                 └──── MCP ─────┴──────────────────────────────────┘
                         levelforge-twin MCP server (:9150)
                         validate_level, apply_edits, evaluate_levels, cluster_status, kill_worker ...
                                   │
                         MASTER ── W1  W2  W3  W4  W5   (simulation worker processes)
```

| Part | What it is | Code |
|---|---|---|
| **A2A** | Agent2Agent protocol v1.0 (official `a2a-sdk`). Every agent is its own HTTP server with an Agent Card at `/.well-known/agent-card.json`; the Director sends JSON-RPC `SendMessage` tasks and gets results back as task artifacts. | `levelforge/team/` |
| **More agents** | Director (master) + 8 workers. The 3 specialists each own part of the problem (difficulty, layout, rewards) and are asked **in parallel**; the one that owns the top problem gets more plan slots, the QA Validator filters their plans, the Director accepts the best or rolls back. | `levelforge/team/agents.py`, `director.py` |
| **MCP** | Model Context Protocol server (official `mcp` SDK) exposing the digital twin as 10 tools. The agents use it over HTTP; Claude Desktop can use the same server over stdio. | `levelforge/mcp_server.py`, `mcp_twin.py` |
| **Master-worker** | The master splits each job into chunks of 8 simulations, gives each worker 2 at a time, hands out more as results come back (dynamic load balancing), watches every worker process and re-queues the work of a crashed worker on a replacement. | `levelforge/cluster.py` |

Outputs go to `outputs_team\`: `report.html` now has an **Agent team** section (agent cards, the
A2A message trace per round, simulations per worker per round, crashes survived), plus
`logs\` (one log per agent and for the MCP server) and `team_result.json`.

**Fault-tolerance demo, live:** while `run_team.py` is running, open a second terminal and run
`python kill_worker.py`. The run prints the crash, the re-queued simulations and the replacement
worker, and finishes with exactly the same numbers.

**Use the MCP server from Claude Desktop:** copy the block from `mcp_config_example.json` into
Claude Desktop's config file (Settings > Developer > Edit Config), restart Claude Desktop, then ask:
*"Use levelforge-twin to evaluate this level and improve it"* and paste a level grid.

If a port is busy (another run still open), close it or use `--base-port 9200 --mcp-port 9250`.

## 3. Turn on the LLM (optional but recommended for the GenAI marks)

Without a key everything still runs, using rule-based agents. With a free Groq key
(console.groq.com/keys) the generator, critic, optimizer, review labeller and designer notes all
become LLM-driven.

1. Open the `.env` file in this folder (VS Code shows it in the Explorer).
2. Replace `your_groq_key_here` with your key: `GROQ_API_KEY=gsk_...` (no quotes, no spaces).
3. Save, then run `python run_demo.py`. The first lines should say `Agents : groq:openai/gpt-oss-120b`.

`.env` is listed in `.gitignore`, so the key is not uploaded if you push this to GitHub.
Gemini also works (`GEMINI_API_KEY=...`), and `LLM_MODEL=...` changes the model.
Every LLM step falls back to rules if a call fails, so the demo cannot break mid-presentation.

### Troubleshooting the LLM

Test the connection with one tiny call:

```bat
python -m levelforge.llm
```

| Message | Meaning |
|---|---|
| `No API key found` | `.env` is missing or not next to `run_demo.py`, or the key line is wrong |
| `API key rejected (401)` | Key typo or revoked key: create a new one at console.groq.com/keys |
| `request blocked (403) ... 1010` | Cloudflare blocked the client. The code sends a User-Agent to prevent this; if it persists, try another network (some college Wi-Fi/VPNs are blocked) |
| `model ... not found (404)` | Set `LLM_MODEL=` in `.env` to a model listed at console.groq.com/docs/models |
| `HTTP 429` | Free-tier rate limit; the client waits and retries automatically |

After a permanent error the run switches to rule-based agents for the rest of the run, instead
of retrying every step, and prints a WARNING in the summary.

## 4. Results for the paper

```bat
python benchmark.py
python experiments.py
```

| Script | Produces | Used for |
|---|---|---|
| `benchmark.py` | `outputs\benchmark\scaling.png`, `chunksize.png`, `scaling.csv` | MCA section: speedup, efficiency, Karp-Flatt, Amdahl fit, chunk-size/IPC overhead |
| `experiments.py` | `outputs\experiments\comparison.png`, `results_table.md` | Main result: agent vs random search vs no optimisation, same budget |
| `run_demo.py` | `outputs\report.html`, `history.json`, `agent_log.txt` | Demo + qualitative figures |

`experiments.py` compares random search, the rule-based agent and (if a key is set) the LLM agent,
all starting from the SAME procedural level with the same simulation budget. Offline it takes a few
minutes; with the LLM it makes roughly 15 API calls per level, so start with `--levels 4`.
`--offline` skips the LLM agent; `--methods random,rule_agent,llm_agent` picks methods.

To compare rule vs LLM agents in the demo from the same starting level:

```bat
python run_demo.py --offline --out outputs_rules
python run_demo.py --start procedural --out outputs_llm_same_start
python run_demo.py --out outputs_llm          (LLM also designs the first level)
```

### The paper (IEEE format, LaTeX)

- `paper\LevelForge_paper.pdf`: the compiled paper (8 pages, IEEE conference two-column).
- `paper\LevelForge_paper_overleaf.zip`: upload to Overleaf (New Project > Upload Project), then Recompile.
- `paper\latex\`: the same sources (`main.tex`, `refs.bib`, figures). Text in **red** inside `[...]` still
  needs your details (team names, emails, CPU, cores, RAM, Python version) or numbers from
  `python benchmark_cluster.py` (run `python run_team.py --offline --level data\problem_level.txt` first,
  so the benchmark can also measure the A2A/MCP overhead).
- `paper\paper_draft.md` is the older plain-text draft; the LaTeX version is the one to submit.

## 4b. CI/CD: tests, website, teamwork

`.github/workflows/ci-cd.yml` runs on GitHub Actions:

| Trigger | What happens |
|---|---|
| every push / pull request | `pytest` on Linux and Windows: digital twin, master-worker crash recovery, MCP tools, and full offline runs of `run_demo.py` and `run_team.py` |
| merge to `main` | `scripts/build_site.py` builds a website (3D game, single-agent and agent-team reports, agent map, paper) and deploys it to GitHub Pages |

Run the same checks locally with `pip install pytest` then `python -m pytest -q`, and build the site
with `python scripts/build_site.py` (writes `site/`). How the team works with branches and pull
requests: see `CONTRIBUTING.md`.

## 5. Where each requirement lives

| Requirement | What it is | Code |
|---|---|---|
| **GenAI** | Review labelling into a design-problem taxonomy; LLM writes the initial level grid; designer notes | `levelforge/reviews.py`, `agents.py` (generator, finalize) |
| **Agentic AI** | LangGraph state machine: generator → simulate → critic → optimizer loop with conditional routing, accept/reject with rollback, and a reflection memory of failed fixes | `levelforge/agents.py` |
| **MCA / HPC** | Embarrassingly parallel Monte-Carlo play-testing on a process pool; all candidates batched into one parallel sweep; chunked task dispatch; scaling benchmark | `levelforge/parallel.py`, `benchmark.py` |
| **Digital twin** | Grid level model + turn-based simulator + three bot personas | `levelforge/level.py`, `simulator.py` |
| **Research** | Quality metric, baselines, sign test, convergence curves | `levelforge/metrics.py`, `experiments.py` |
| **A2A multi-agent** | Director + 8 worker agents as A2A servers | `levelforge/team/`, `run_team.py` |
| **MCP** | Digital twin as MCP tools (HTTP for the team, stdio for Claude Desktop) | `levelforge/mcp_server.py`, `mcp_twin.py` |
| **Master-worker** | Explicit master with dynamic scheduling and crash recovery | `levelforge/cluster.py`, `kill_worker.py` |

## 6. Project layout

```
levelforge/
  level.py       level format, validation, repair (the digital twin)
  simulator.py   game rules + rusher / cautious / explorer bots
  metrics.py     metrics + quality score (targets come from reviews)
  parallel.py    multiprocessing runner (default 5 workers)
  generator.py   procedural generator (offline fallback + baseline)
  edits.py       structured edit operations the optimizer agent can use
  reviews.py     review mining -> taxonomy -> design brief
  llm.py         Groq / Gemini client (stdlib only) with offline mode
  agents.py      LangGraph agent loop
  report.py      self-contained HTML report
  cluster.py     master-worker simulation cluster (dynamic scheduling, crash recovery)
  mcp_server.py  digital twin as an MCP server (10 tools)
  team/          A2A agent team: a2a_kit.py (A2A server/client), agents.py (8 workers),
                 director.py (master agent), runtime.py (starts/stops everything), serve.py
run_team.py      agent team demo (A2A + MCP + master-worker)
kill_worker.py   crash a simulation worker during a team run
mcp_twin.py      MCP server entry point for Claude Desktop
run_demo.py      full demo
benchmark.py     multicore scaling benchmark
experiments.py   agent vs baselines
data/            synthetic sample reviews (see data/README.md for real Steam data)
paper/           paper draft
```

## 7. Viva cheat sheet

- **Why processes, not threads?** The simulator is CPU-bound pure Python; the GIL serialises
  threads. Review labelling uses threads because LLM calls are I/O-bound.
- **Why is it embarrassingly parallel?** Each playthrough is independent and seeded; workers
  never communicate, so there is no synchronisation except the final gather.
- **What chunk size, and why?** We measured it: one playthrough costs ~4 ms, which is much more
  than the cost of sending it to a worker, but playthrough cost varies between levels and bot types.
  Big chunks (180 tasks) left some workers idle at the end (load imbalance): 997 sims/s vs
  1,205 sims/s with chunk size 1. So the runner now uses small chunks (at most 8).
- **Why doesn't speedup reach 5× on 5 workers (3.71×)?** Amdahl's law: serial parts (task
  creation, pickling levels, result aggregation). The Karp-Flatt metric estimates that serial
  fraction at about 0.086 and it stays roughly constant as workers increase, which points to fixed
  serial work rather than growing overhead; Amdahl then caps speedup near 11.6×. Above the number of
  physical cores, extra workers share cores through hyper-threading, and laptop CPUs may mix
  performance and efficiency cores, so efficiency drops further (54% at 12 workers).
- **Why structured edits instead of letting the LLM rewrite the grid?** LLMs often break
  grid constraints. Structured edits are validated and applied deterministically, so the
  agent's reasoning is LLM-driven but every resulting level is guaranteed playable.
- **What makes it agentic, not a pipeline?** The router decides whether to continue, the
  simulate step accepts or rejects candidates (rollback to best), and the critic changes its
  priority based on memory of failed fixes.
- **What does "same random numbers" mean?** Every candidate is tested with the same seeds,
  so differences in score come from the level, not from luck.
- **Limitations:** bots are rule-based, not human; the quality score is a designed proxy for
  fun, not a measurement of it; the sample reviews are synthetic unless you load real data.
