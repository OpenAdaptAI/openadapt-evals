# Agent Improvement: Options and Tradeoffs

## Current State

- Qwen3-VL-2B fine-tuned on 3 demos: **0% on WAA** (degenerate click loop, overfit)
- Qwen3-VL-2B zero-shot: **0% on WAA** (conceptually correct actions, wrong coordinates)
- Claude ApiAgent: **0% on WAA** (hard tasks, coordinate accuracy issues)
- WAA Navi baseline (GPT-4V + SoM): **19.5%** on WAA
- Human: **74.5%** on WAA

**Root cause**: Every agent we've tried outputs raw pixel coordinates. Coordinate
prediction from screenshots is the hardest part of GUI automation. We're solving the
hardest subproblem first and failing. The infrastructure already supports element-based
grounding (accessibility tree, target_node_id) but no agent uses it.

---

## Options

### A. Continue Current Approach: Fine-Tune on More Coordinate-Based Demos

**What**: Record more demos via VNC, annotate, train Qwen3-VL-2B on 50+ demos.

**Pros**:
- Pipeline already built end-to-end
- No architecture changes needed
- Directly validates demo-conditioned thesis

**Cons**:
- 3 demos → overfitting; more demos help but coordinate prediction is fundamentally
  hard for 2B models (SeeClick needed 270K examples, OS-Atlas needed 13M)
- Human demo recording is the bottleneck (manual VNC work)
- Doesn't address the core problem: pixel coordinate accuracy
- Research shows 2B models need dedicated grounding pre-training (Stage 1 SFT) before
  they can reliably predict coordinates

**Estimated effort**: 2-3 days (recording) + 1 day (training)
**Expected outcome**: Marginal improvement, likely still 0% on hard WAA tasks
**Ralph-loopable**: No (requires human demo recording)

---

### B. DAgger: Claude Code Labels Eval Screenshots as Training Data

**What**: Run eval, Claude Code looks at each screenshot, determines correct action,
writes as training data. Train on Modal. Repeat.

**Pros**:
- Eliminates human demo recording bottleneck
- Fully automatable in a ralph loop
- Each iteration generates new data from new screen states

**Cons**:
- **Wasteful**: Using $15/M-token model to label data for $0.10/M-token model
- **Circular**: Claude also can't reliably determine pixel coordinates (it scores 0% too)
- **Noisy labels**: If teacher can't solve the task, training data quality is poor
- Doesn't compound — linear cost per label
- Doesn't address the fundamental coordinate prediction problem

**Estimated effort**: 2-3 days to build pipeline
**Expected outcome**: Marginal — training on noisy labels from a failing teacher
**Ralph-loopable**: Yes, but the loop converges to garbage

---

### C. Accessibility Tree Grounding: Use Element IDs Instead of Coordinates

**What**: Include the a11y tree in the agent's prompt. Agent outputs `click_id("Submit")`
instead of `click(x=589, y=965)`. The adapter already maps element IDs to coordinates.

**Pros**:
- **Sidesteps coordinate prediction entirely** — the hardest part
- Infrastructure already exists (WAA adapter extracts a11y tree + element rects)
- BenchmarkAction already has `target_node_id` field
- Mock adapter scores based on element IDs — instant validation
- Works with any base model without fine-tuning (in-context learning)
- Fast iteration: prompt engineering, no training needed

**Cons**:
- A11y trees are often incomplete/incorrect in real Windows apps
- Custom-drawn UI elements invisible to accessibility APIs
- Large a11y trees may overwhelm small models (token budget)
- Base Qwen3-VL wasn't trained on element-ID actions (may need fine-tuning)
- Platform-dependent (UIA for Windows, different for web/Linux)

**Estimated effort**: 4-6 hours for basic implementation
**Expected outcome**: Non-zero scores on mock tasks immediately; real WAA depends on
a11y tree quality for specific tasks
**Ralph-loopable**: Yes — iterate on prompt format, tree formatting, element selection

---

### D. Set-of-Mark (SoM) Visual Prompting

**What**: Overlay numbered labels on UI elements in the screenshot. Model picks a number
instead of predicting coordinates. This is what WAA's Navi baseline uses (19.5%).

**Pros**:
- **Proven on WAA**: Navi achieves 19.5% with SoM + GPT-4V
- Combines visual + semantic information (up to 57% improvement in WAA paper)
- OmniParser already exists in `openadapt-grounding` repo
- Works with any VLM — no special fine-tuning needed
- Visual marks are more intuitive for models than raw a11y tree text

**Cons**:
- Adds preprocessing step (detection model inference per screenshot)
- Visual clutter can confuse smaller models
- OmniParser deployment adds infrastructure complexity
- Mark quality depends on detection model — small/overlapping elements problematic
- Additional latency per step

**Estimated effort**: 1-2 days (deploy OmniParser, integrate into eval pipeline)
**Expected outcome**: Significant improvement if using GPT-4V/Claude; uncertain for 2B
**Ralph-loopable**: Partially — Claude Code can iterate on SoM configuration, mark
filtering, prompt format

---

### E. Two-Stage SFT: Grounding Pre-Training + Agentic Fine-Tuning

**What**: The standard approach that works at 2B-3B scale. First train on millions of
(screenshot, element description) → coordinate pairs. Then fine-tune on task trajectories.

**Evidence**:
- Qwen-GUI-3B: 86.4% on ScreenSpot-v2 with only 24K examples (single RTX 4090)
- Smol2Operator: Functional GUI agent from 2.2B base with two-phase SFT
- Jedi dataset: Took OSWorld from 23% → 51% with grounding data alone

**Pros**:
- **Industry-standard approach** — proven at exactly our model scale
- Massive open-source grounding datasets available (OS-Atlas 13M, Jedi 4M)
- Addresses the root cause (coordinate accuracy)
- Compatible with demo-conditioned inference afterward
- Could use Modal for training

**Cons**:
- Requires significant training compute (Stage 1 is large-scale)
- Need to curate/adapt grounding datasets for Windows desktop
- Two separate training phases to manage
- More complex pipeline than current approach
- Stage 1 may take hours on A10G (millions of examples)

**Estimated effort**: 3-5 days (dataset prep + Stage 1 training + Stage 2 fine-tuning)
**Expected outcome**: Dramatically better grounding accuracy; competitive with SOTA at 2B
**Ralph-loopable**: Partially — hyperparameter tuning and dataset selection iterations

---

### F. RL (GRPO) After SFT

**What**: After SFT, apply Group Relative Policy Optimization using eval scores as reward.
Generate N candidate actions per step, score them, train on the best ones.

**Evidence**:
- SE-GUI: 47.3% on ScreenSpot-Pro with only 3K samples + GRPO, beating UI-TARS-72B
- GTA1: 45.2% on OSWorld with GRPO + test-time scaling
- CRAFT-GUI: Curriculum GRPO outperforms prior SOTA by 5-10%

**Pros**:
- **Extremely sample-efficient** (3K samples can beat 72B models)
- Uses eval scores directly as reward signal — naturally fits our pipeline
- Pushes beyond SFT ceiling
- Self-improving: generates its own training signal from environment interaction

**Cons**:
- Requires SFT base first (Option E as prerequisite)
- RL training is finicky — reward shaping, hyperparameters
- Need infrastructure for generating multiple candidates per step
- More complex to implement than SFT
- Needs environment interaction during training (VM must be running)

**Estimated effort**: 5-7 days (after SFT base)
**Expected outcome**: Could match or exceed SOTA at 2B if SFT base is solid
**Ralph-loopable**: Yes — RL hyperparameter tuning + reward shaping iterations

---

### G. Use Existing Open-Source GUI Agents Directly

**What**: Instead of training from scratch, use pre-trained GUI agents as the base:
- **UI-TARS-1.5-7B** (ByteDance): Open-source, 40% on OSWorld
- **Smol2Operator-2.2B** (HuggingFace): Open-source, already fine-tuned for GUI
- **Qwen-GUI-3B**: 86.4% ScreenSpot-v2, open-source

**Pros**:
- **Immediately more capable** than our from-scratch fine-tune
- Already trained on grounding (Stage 1 done for us)
- Smol2Operator is 2.2B — same scale as our current model
- Can add demo-conditioning on top (the OpenAdapt differentiator)
- Minimal training needed — just adapt to WAA action format

**Cons**:
- Need to adapt action space to our BenchmarkAction format
- May need format conversion for demo-conditioning
- Less control over training process
- 7B models need more GPU memory (A10G can handle it though)
- Licensing varies (check each model)

**Estimated effort**: 1-2 days (adapt agent wrapper + action format conversion)
**Expected outcome**: Non-zero WAA scores likely (these models can ground reliably)
**Ralph-loopable**: Yes — iterate on prompt engineering, demo format, action parsing

---

### H. Hybrid: Strong Planner + Small Grounder

**What**: Use Claude/GPT for task decomposition and planning ("open Notepad, type text,
save file"), use a small grounding model to execute each sub-step ("click the element
that says 'Search'").

**Evidence**:
- GTA1 (Salesforce): 45.2% on OSWorld with this exact approach
- Separates reasoning (hard, needs large model) from grounding (trainable, small model)

**Pros**:
- Plays to each model's strengths
- Claude is excellent at planning; small models can learn grounding
- Demo-conditioning applies naturally to the planning layer
- Grounding model is cheap to train and run
- Can swap planner (Claude → GPT → local) independently of grounder

**Cons**:
- Two-model inference increases latency and complexity
- API costs for planner (Claude/GPT per step)
- Need to define sub-step interface between planner and grounder
- More moving parts to debug

**Estimated effort**: 3-5 days
**Expected outcome**: Strong if grounding model is reliable (Option E helps)
**Ralph-loopable**: Yes — iterate on planning prompts, sub-step decomposition, grounder

---

### I. Self-Play from Successes (Curriculum Learning)

**What**: Start with the easiest possible tasks. When the agent succeeds, capture the
trajectory as training data. Train on successes. Attempt harder tasks. Repeat.

**Pros**:
- **Self-sustaining data generation** — successes compound
- No human labeling needed once bootstrapped
- Natural curriculum: easy → hard
- Training data is guaranteed correct (it produced success)
- Aligns training distribution with deployment distribution

**Cons**:
- **Chicken-and-egg**: need first success to bootstrap
- If agent can't succeed at anything, loop never starts
- Successful trajectories may not generalize (narrow demonstrations)
- Needs diverse task pool to avoid overfitting to easy tasks
- Selection bias: only trains on what it can already do

**Estimated effort**: 2-3 days (pipeline), ongoing (curriculum design)
**Expected outcome**: Compounding improvement IF bootstrapped; zero if not
**Ralph-loopable**: Yes — this IS a ralph loop by nature

---

### J. Claude Code as Agent Architect (Prompt + Code Iteration Loop)

**What**: Claude Code iterates on the agent's architecture, prompts, and code using eval
scores as the objective function. Not generating training data — modifying the system.

**Interventions Claude Code can make**:
- Modify system prompt (add UI layout hints, chain-of-thought, few-shot examples)
- Add accessibility tree to prompt
- Add SoM preprocessing
- Modify action space (element IDs, text grounding, hybrid)
- Add error recovery (detect stuck loops, try alternatives)
- Change which tasks to attempt (curriculum)
- Modify coordinate handling (normalization, scaling)

**Pros**:
- **Highest leverage per iteration** — each change is architectural, not a single label
- Fast feedback loop (change code → eval → analyze screenshots → iterate)
- Claude Code can reason about WHY failures happen (multimodal analysis)
- No training needed for prompt/architecture changes
- Naturally discovers what Option C-H would prescribe

**Cons**:
- Relies on Claude Code's judgment about what to change
- May get stuck in local optima
- Architecture changes are harder to evaluate than data improvements
- Risk of over-engineering or adding complexity that doesn't help

**Estimated effort**: Ongoing (ralph loop)
**Expected outcome**: Discovers the right architecture through iteration
**Ralph-loopable**: Yes — this is the ideal ralph loop task

---

## Comparison Matrix

| Option | Expected Impact | Time to First Result | Cost | Ralph-Loopable | Addresses Root Cause |
|--------|----------------|---------------------|------|----------------|---------------------|
| A. More demos | Low | Days | Low | No | No (still coordinates) |
| B. DAgger | Low | Days | High | Yes | No (noisy teacher) |
| C. A11y tree | Medium | Hours | Zero | Yes | Yes (sidesteps coords) |
| D. SoM | Medium-High | 1-2 days | Low | Partial | Yes (visual grounding) |
| E. Two-stage SFT | High | 3-5 days | Medium | Partial | Yes (grounding training) |
| F. RL (GRPO) | Very High | 5-7 days | Medium | Yes | Yes (self-improvement) |
| G. Use existing agents | Medium-High | 1-2 days | Low | Yes | Yes (pre-trained grounding) |
| H. Hybrid planner | High | 3-5 days | Medium | Yes | Yes (separation of concerns) |
| I. Self-play | High (if bootstrapped) | 2-3 days | Low | Yes | Partially |
| J. Code iteration | Variable | Hours | Low | Yes | Discovers the answer |

---

## Recommended Strategy

**Phase 0 — Validate the loop (Today, hours)**:
Option J (code iteration) + Option C (a11y tree) on mock tasks. Claude Code modifies
the Qwen3VL agent to use the accessibility tree, runs mock eval, iterates until score > 0.
This proves the ralph loop works and gets first non-zero score. Zero infrastructure cost.

**Phase 1 — Real capability (This week, 1-2 days)**:
Option G (use Smol2Operator or UI-TARS-1.5-7B as base model). These already have
grounding Stage 1 baked in. Wrap them in a BenchmarkAgent, run WAA eval. Add
demo-conditioning on top. This likely produces non-zero WAA scores immediately.

**Phase 2 — The OpenAdapt differentiator (Next week)**:
Option I (self-play) bootstrapped from Phase 1 successes. Agent succeeds at easy tasks →
trajectories become demo library → demo-conditioned agent attempts harder tasks →
successes compound. This validates the core OpenAdapt thesis (demos improve agents)
with a self-sustaining data flywheel.

**Phase 3 — Push to SOTA (Ongoing)**:
Option E (two-stage SFT) + Option F (GRPO) on our own 2B model, trained on the demo
library accumulated from Phase 2. Small, fast, cheap model that rivals 72B models
through targeted training. SE-GUI showed 3K samples + GRPO can beat UI-TARS-72B.

---

## Key Research References

| Paper/System | Scale | Result | Key Technique |
|-------------|-------|--------|---------------|
| SE-GUI | 7B | 47.3% ScreenSpot-Pro | GRPO with 3K samples |
| Qwen-GUI-3B | 3B | 86.4% ScreenSpot-v2 | Two-stage SFT, 24K examples |
| Smol2Operator | 2.2B | Functional GUI agent | Two-phase SFT, open-source |
| UI-TARS-1.5 | 7B | 40% OSWorld | SFT + RL + DPO |
| GTA1 | 7B grounder | 45.2% OSWorld | Separate planner + RL grounder |
| Navi (WAA baseline) | GPT-4V | 19.5% WAA | SoM + CoT |
| PC Agent-E | — | 36% WAA-V2 | 312 demo trajectories (141% improvement) |
| LearnAct | Gemini-1.5-Pro | 51.7% (from 19.3%) | Single demonstration |
| ShowUI-Aloha | — | 60.1% | Demo-conditioned planning |
| Jedi dataset | — | 23%→51% OSWorld | Grounding data alone |
