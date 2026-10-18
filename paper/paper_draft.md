> **Superseded:** the submission version is the IEEE LaTeX paper in `paper/latex/` (PDF: `paper/LevelForge_paper.pdf`). This file is kept as the earlier plain-text draft.

# An Agentic Digital Twin Framework for Feedback-Driven Autonomous Game-Level Generation and Optimization

*Draft with real results from runs on 4 Oct 2026. Items marked [fill] need your details. Verify
every reference before submitting. Figures are in the `outputs` folder (paths given below).*

---

## Abstract

Designing game levels that match what players want is slow and largely manual. We present
LevelForge, a framework that closes the loop between player feedback and level design. Player
reviews are labelled by a large language model (GPT-OSS-120B) into a taxonomy of actionable design
problems, which sets measurable design targets. A multi-agent system implemented as a LangGraph
state machine generates a level, play-tests it through a digital twin with three simulated player
personas, diagnoses its weaknesses, and proposes alternative structured edits. Because every
simulated playthrough is independent, play-testing is distributed across a multicore process pool,
evaluating up to 11,250 playthroughs per optimisation run in seconds. On 12 starting levels with an identical
simulation budget, critic-guided optimisation raised mean level quality from 0.572 to 0.783 (+37%)
and outperformed random search (0.758) on 9 of 12 levels (Wilcoxon signed-rank p = 0.034),
reaching random search's final quality after 4 of 6 rounds. Parallel play-testing reached a 3.71×
speedup on 5 workers and 6.47× on 12 logical cores, with an experimentally determined serial
fraction of 0.086. In a smaller study (4 levels), LLM-driven reasoning performed comparably to
rule-based reasoning (0.766 vs 0.787, not significant) while additionally designing levels from
scratch and explaining its changes in natural language.

## 1. Introduction

- **Problem:** player reviews contain rich design feedback ("too hard", "I keep getting lost"),
  but it rarely reaches level design in a measurable form.
- **Gap:** LLMs can generate levels, but generation alone does not guarantee a level is playable,
  balanced, or aligned with player feedback. Judging a level needs many playthroughs, which is
  computationally expensive.
- **Contributions:**
  1. A review-to-brief pipeline that turns free-text feedback into quantitative design targets.
  2. An agentic generate–simulate–critique–optimise loop with structured, validated edit actions,
     simulation feedback to the optimiser, and a reflection memory that redirects the critic after
     failed fixes.
  3. A parallel Monte-Carlo play-testing engine on a multicore process pool, with a scaling and
     task-granularity study.
  4. A controlled comparison of rule-based reasoning, LLM reasoning and random search under the
     same simulation budget and starting levels.

## 2. Related Work

- Search-based procedural content generation [3, 4].
- Machine-learning and LLM level generation [5, 6, 7].
- Persona-based automated play-testing [8].
- LLM agents with reasoning, acting and reflection [9, 10].
- Parallel performance analysis [1, 2].

Our work differs by deriving the objective from player feedback, and by keeping the LLM in a
reasoning role (design, diagnosis, edit selection) while a validator guarantees that every level
remains playable.

## 3. System Design

### 3.1 Review mining (GenAI)
Reviews are labelled in batches by the LLM into six design problems: too hard, too easy,
repetitive, confusing layout, unfair traps, and little reward for exploring (keyword classifier as
offline fallback). Batches are sent concurrently with a thread pool, as the calls are I/O-bound.
Problem shares set the design brief: target completion rate, target HP lost by finishers, and the
weights of the quality score (e.g. more "confusing layout" complaints raise the weight on flow).
For the 48 sample reviews used here, "too hard" was the most common complaint (23%), giving a
target completion rate of 71% and a target HP loss of 35%.

### 3.2 Digital twin
A level is a character grid (wall, start, exit, key, door, monster, trap, potion, coin). A
turn-based simulator implements the rules: stochastic monster fights, traps that trigger with
probability 0.6, monsters that may strike adjacent players, potions, coins and locked doors.
Three rule-based personas plan with Dijkstra search under different cost models: **rusher**
(shortest path), **cautious** (avoids hazards, heals when low) and **explorer** (collects items,
then exits).

### 3.3 Metrics and quality score
Per level: completion, death and timeout rates; damage; backtracking ratio; exploration; coin
collection; per-persona completion. The quality score combines five components in [0, 1]:
balance (completion vs target, penalising both under- and overshoot), engagement, flow (low
backtracking), skill expression (cautious players should out-perform rushers) and tension (HP lost
vs target), weighted by the review-derived brief.

### 3.4 Agentic optimisation loop
A LangGraph state graph: Generator → Simulate → (router) → Critic → Optimizer → Simulate … →
Finalize.
- **Generator:** the LLM writes the initial grid from the design brief. Invalid grids get one
  self-correction attempt, then deterministic repair.
- **Critic:** diagnoses problems using a fixed vocabulary of problem ids. It keeps a memory of
  priorities whose fixes failed and moves to a different priority.
- **Optimizer:** proposes *k* = 4 alternative plans of structured edits (add or remove a tile type
  on or off the main route, open a loop, add or remove a lock). It receives the simulated scores
  of the previous round's plans and which plans could not be applied.
- **Simulate:** evaluates all candidates and keeps the best; otherwise it rolls back.
- **Finalize:** the LLM writes designer notes explaining the changes.

Edits are validated and applied deterministically, so the LLM cannot produce an unplayable level.
The rule-based variant replaces the LLM critic and optimizer with a hand-written diagnosis and
playbook.

### 3.5 Parallel play-testing (MCA)
Each playthrough (level, persona, seed) is an independent task, so the workload is embarrassingly
parallel. Tasks for all candidates of a round are combined into a single sweep over a persistent
process pool (default 5 workers). Processes are used instead of threads because the simulator is
CPU-bound Python and the global interpreter lock would serialise threads. All candidates share the
same seeds (common random numbers), so score differences come from the level, not from luck.

### 3.6 Playable game and its digital twin
The levels are played in LevelForge: Breach, a real-time first-person 3D shooter that runs in the browser
(Three.js, WebGL), with a top-down 2D variant:
hunter drones that chase and shoot, proximity mines, med-kits, data cores, a keycard and blast door,
and an extraction portal. The simulator of Sections 3.2–3.5 is its digital twin: a simplified,
turn-based model of the game that keeps the same level layout and the same values (player
health 10, maximum 12; drone health 3; mine damage 3; med-kit healing 4). Real-time aiming,
dodging and enemy movement are abstracted into discrete encounters so that thousands of
playthroughs can be simulated in seconds. All quality scores in this paper are measured on the
twin, not on human play. The game's campaign presents three levels from the runs above: the level
before optimisation, the same level after optimisation, and an LLM-designed and optimised level.
Modelling shooting directly in the twin is left for future work.

## 4. Experimental Setup

- **Hardware:** laptop with 12 logical cores [fill: CPU model, physical cores, RAM], Windows,
  Python [fill: version]. The GPU was not used.
- **LLM:** GPT-OSS-120B via the Groq API, reasoning effort low.
- **Optimisation study:** 12 procedurally generated starting levels; all methods start from the
  same level; budget per method per level is 6 rounds × 4 candidates × 300 playthroughs. Methods:
  no optimisation (raw), random search (same loop, random edits, no critic), and the agent loop
  with rule-based reasoning.
- **LLM study:** the first 4 of those levels, adding the agent loop with LLM reasoning (99 API
  calls, 425 s total). It is smaller because of free-tier API rate limits.
- **Statistics:** paired comparisons per level; exact Wilcoxon signed-rank test (two-sided) and
  sign test.
- **Scaling study:** 3,600 playthroughs (6 levels × 3 personas × 200) at 1–12 workers, best of 3
  repeats, chunk size n/(4p); then chunk sizes 1, 8, 180, 720 at 5 workers.

## 5. Results

### 5.1 Optimisation quality (12 levels)

| Method | Mean quality ± sd | Mean completion (target 71%) |
|---|---|---|
| No optimisation (raw) | 0.572 ± 0.093 | 60% |
| Random search (same budget) | 0.758 ± 0.064 | 78% |
| Agent loop, rule-based reasoning | **0.783 ± 0.061** | 74% |

- Both optimisers improved every level over raw (Wilcoxon p < 0.001 each): +32% for random
  search and +37% for the agent loop.
- The agent loop beat random search on 9 of 12 levels; mean paired gain +0.026, Wilcoxon p =
  0.034, sign test p = 0.146. The sign test ignores how large each difference is, so it is weaker
  here; the agent's wins were larger (up to +0.089) than its losses (at most −0.020).
- The agent loop also landed closer to the completion target (74% vs 78%).

**Convergence (mean best quality per round):**

| Round | 0 | 1 | 2 | 3 | 4 | 5 | 6 |
|---|---|---|---|---|---|---|---|
| Random search | 0.572 | 0.657 | 0.692 | 0.719 | 0.738 | 0.753 | 0.758 |
| Agent loop (rules) | 0.572 | 0.664 | 0.710 | 0.735 | 0.762 | 0.773 | 0.783 |

The agent loop matched random search's final quality by round 4, i.e. with about two thirds of
the simulation budget. Figure: `outputs/experiments_rules/comparison.png`.

### 5.2 LLM reasoning vs rule-based reasoning (4 levels)

| Method | Mean quality ± sd |
|---|---|
| No optimisation (raw) | 0.631 ± 0.012 |
| Random search | 0.757 ± 0.053 |
| Agent loop, rule-based | 0.787 ± 0.026 |
| Agent loop, LLM (GPT-OSS-120B) | 0.766 ± 0.082 |

The LLM agent won 2 of 4 levels against random search and 2 of 4 against the rule-based agent.
With 4 levels no difference is statistically detectable (the smallest possible two-sided sign
test p-value is 0.125), so we report the methods as comparable. The LLM agent had the highest
variance: best result on two levels (0.804, 0.844) and the worst agent result on another (0.655).
Figure: `outputs/experiments/comparison.png`.

### 5.3 Case studies
- **Rule-based demo** (`outputs/report.html`): quality 0.477 → 0.895; completion 32% → 72%;
  backtracking 12% → 4%; completion per persona (rusher/cautious/explorer) 31/31/34% →
  66/100/51%, so careful play is now rewarded.
- **Full LLM pipeline** (`outputs_llm/report.html`): the LLM designed a corridor-based maze from
  the brief (quality 0.604, 100% completion, i.e. too easy). The LLM agents then raised it to 0.879
  with completion 79%, mainly by adding hazards in corridors where bots cannot walk around them.
- **LLM from the rule demo's starting level** (`outputs_llm_same_start/report.html`): 0.475 →
  0.750, versus 0.895 for rule-based reasoning. The LLM repeatedly traded off two targets: it added
  potions to reduce HP loss (78% vs target 35%), but each potion pushed completion above the 71%
  target, so four consecutive rounds were rejected. This shows a limitation of the LLM planner in
  reasoning about competing objectives, even when given the scoring rules.

### 5.4 Parallel scaling (MCA)

| Workers | Time (s) | Sims/s | Speedup | Efficiency | Karp-Flatt e |
|---|---|---|---|---|---|
| 1 | 13.36 | 269 | 1.00 | 100% | – |
| 2 | 7.44 | 484 | 1.80 | 90% | 0.113 |
| 3 | 5.30 | 679 | 2.52 | 84% | 0.095 |
| 4 | 4.22 | 853 | 3.16 | 79% | 0.088 |
| 5 | 3.60 | 999 | 3.71 | 74% | 0.087 |
| 7 | 2.75 | 1307 | 4.85 | 69% | 0.074 |
| 9 | 2.44 | 1477 | 5.48 | 61% | 0.080 |
| 11 | 2.12 | 1701 | 6.31 | 57% | 0.074 |
| 12 | 2.07 | 1743 | 6.47 | 54% | 0.078 |

- Throughput rose 6.5× from 1 to 12 workers. Pool start-up cost 0.13–0.22 s and is paid once per
  run because the pool is reused.
- The Karp-Flatt serial fraction stayed roughly constant (0.074–0.113, mean 0.086). That points to
  a fixed serial portion (task creation, pickling levels, aggregating results) rather than
  overhead growing with the number of workers. Amdahl's law with f = 0.086 bounds speedup at about
  11.6×.
- Efficiency falls further beyond [fill: physical core count] workers because extra workers share
  physical cores via hyper-threading [fill: and the CPU mixes performance and efficiency cores, if
  applicable].
- Figure: `outputs/benchmark/scaling.png`.

**Task granularity (5 workers):**

| Chunk size | Sims/s |
|---|---|
| 1 | 1205 |
| 8 | 1168 |
| 180 (= n/4p) | 997 |
| 720 (= n/p) | 909 |

Contrary to the common advice to batch small tasks, the smallest chunks were fastest (+21% over
n/4p). A playthrough costs about 3.7 ms, much more than dispatching it to a worker, but its cost
varies between levels and personas. Large chunks therefore leave workers idle at the end of a
sweep (load imbalance). Based on this, we changed the runner's default to small chunks (at most 8).
The scaling table above was measured with the earlier n/4p setting, so it is a conservative
estimate. Figure: `outputs/benchmark/chunksize.png`.

## 6. Discussion and Limitations
- The agent loop's main benefit over random search is efficiency: equal quality with about a
  third fewer simulations, and a modest but consistent gain at equal budget.
- LLM reasoning was comparable to hand-written rules but less consistent. Its advantages are
  designing levels from scratch, natural-language explanations, and needing no hand-written
  playbook; its costs are API latency and rate limits (425 s for 4 levels vs seconds offline).
- The personas are rule-based and only approximate human players. The quality score is a designed
  proxy; we do not claim it measures fun.
- The 48 reviews are synthetic; real Steam reviews are needed for claims about actual players.
  LLM labelling varies slightly between runs, so each experiment computes the brief once and
  shares it across methods.
- The LLM study used only 4 levels; more levels are needed to detect differences.

## 7. Conclusion and Future Work
LevelForge turns player feedback into measurable design targets and improves levels toward them
through an agentic loop backed by parallel simulated play-testing. Critic-guided optimisation
beat random search at equal cost, and multicore simulation made thousands of playthroughs per run
practical on a laptop. Future work: real review data, a larger LLM study, learned player models,
multi-objective optimisation (e.g. Pareto search) to address the trade-offs the LLM struggled
with, and a user study with human players.

## References (verify before submission)
1. G. M. Amdahl, "Validity of the single processor approach to achieving large scale computing
   capabilities," AFIPS Spring Joint Computer Conference, 1967.
2. A. H. Karp and H. P. Flatt, "Measuring parallel processor performance," Communications of the
   ACM, 33(5), 1990.
3. J. Togelius, G. N. Yannakakis, K. O. Stanley, C. Browne, "Search-based procedural content
   generation: A taxonomy and survey," IEEE Trans. Computational Intelligence and AI in Games, 2011.
4. N. Shaker, J. Togelius, M. J. Nelson, *Procedural Content Generation in Games*, Springer, 2016.
5. A. Summerville et al., "Procedural content generation via machine learning (PCGML)," IEEE
   Transactions on Games, 2018.
6. G. Todd et al., "Level generation through large language models," Foundations of Digital
   Games (FDG), 2023.
7. S. Sudhakaran et al., "MarioGPT: Open-ended text2level generation through large language
   models," NeurIPS, 2023.
8. C. Holmgård, M. C. Green, A. Liapis, J. Togelius, "Automated playtesting with procedural
   personas through MCTS with evolved heuristics," IEEE Transactions on Games, 2019.
9. S. Yao et al., "ReAct: Synergizing reasoning and acting in language models," ICLR, 2023.
10. N. Shinn et al., "Reflexion: Language agents with verbal reinforcement learning," NeurIPS, 2023.
