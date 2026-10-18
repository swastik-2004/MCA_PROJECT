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

- `paper\LevelForge_paper.pdf`: the compiled paper (7 pages, IEEE conference two-column).
- `paper\LevelForge_paper_overleaf.zip`: upload to Overleaf (New Project > Upload Project), then Recompile.
- `paper\latex\`: the same sources (`main.tex`, `refs.bib`, figures). Text in **red** inside `[...]` still
  needs your details (team names, emails, CPU, cores, RAM, Python version).
- `paper\paper_draft.md` is the older plain-text draft; the LaTeX version is the one to submit.

## 5. Where each requirement lives

| Requirement | What it is | Code |
|---|---|---|
| **GenAI** | Review labelling into a design-problem taxonomy; LLM writes the initial level grid; designer notes | `levelforge/reviews.py`, `agents.py` (generator, finalize) |
| **Agentic AI** | LangGraph state machine: generator → simulate → critic → optimizer loop with conditional routing, accept/reject with rollback, and a reflection memory of failed fixes | `levelforge/agents.py` |
| **MCA / HPC** | Embarrassingly parallel Monte-Carlo play-testing on a process pool; all candidates batched into one parallel sweep; chunked task dispatch; scaling benchmark | `levelforge/parallel.py`, `benchmark.py` |
| **Digital twin** | Grid level model + turn-based simulator + three bot personas | `levelforge/level.py`, `simulator.py` |
| **Research** | Quality metric, baselines, sign test, convergence curves | `levelforge/metrics.py`, `experiments.py` |

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
