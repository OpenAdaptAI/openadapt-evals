# Decision: verl-agent/VAGEN for VLM RL Training

**Date**: 2026-03-02
**Status**: Adopted (spike complete, PR #84)
**Stakeholders**: OpenAdapt engineering, RL training partners

## Summary

After a comprehensive review of available RL training frameworks for multi-turn
VLM (Vision-Language Model) desktop automation, we chose **verl-agent/VAGEN**
as our training backend. This document records the reasoning, alternatives
considered, and the key architectural insight that drove the decision.

---

## The Key Insight

**verl-agent enables per-step verification within multi-step rollouts — a
requirement for complex computer-usage tasks that no other framework handles
well.**

Desktop automation tasks are inherently long-horizon: a 15-step episode might
involve navigating menus, typing text, clicking buttons, and verifying results.
Standard GRPO gives you a single reward at the end of the episode (did the task
succeed?), but tells you nothing about which individual steps helped or hurt.

verl-agent's GiGPO (Group-in-Group Policy Optimization) solves this with
**two-level advantage computation**:

1. **Episode-level** (standard GRPO): Did rollout A succeed while rollout B
   failed? Give higher advantage to A's actions.
2. **Step-level** (GiGPO innovation): Across all rollouts, find steps where
   the agent was in the **same state** (same screenshot). Compare the actions
   taken from that state — which ones led to better outcomes? Assign
   per-step advantages accordingly.

This is uniquely valuable for desktop automation because:

- **Episodes are long** (15+ steps), so episode-level signal is diluted
- **Only the final WAA evaluator** tells you if the task succeeded (binary reward)
- **The same intermediate state** (e.g., "File menu is open") appears across
  rollouts — GiGPO exploits this to figure out which click was correct
- **No critic model needed** — GiGPO is critic-free, computing advantages purely
  from group comparisons, keeping GPU memory manageable for large VLMs

Without per-step credit assignment, GRPO on a 15-step episode is like giving a
student a single grade on a 15-question exam without marking which answers were
wrong. GiGPO marks each answer.

---

## The Strategic Framing

> "The environment is the moat, not the training math."

This principle, articulated during our architecture review, drove the decision:

1. **Our core value is the WAA RL environment** — `RLEnvironment` in
   openadapt-evals provides Gym-like reset/step/observe/evaluate for desktop
   automation. Nobody else has this as a turnkey package.

2. **Training math is commodity** — GRPO loss is 15 lines of PyTorch. Anyone
   can write it. The value is in having a standard interface to plug into.

3. **Build on what others have built** — verl-agent has multi-turn VLM support,
   GiGPO, distributed training (FSDP, Ray), vLLM/sglang acceleration. Why
   reimplement any of this?

4. **The training example should be a recipe, not a library** — Users
   `pip install openadapt-evals`, write a 50-line adapter, and train with
   verl-agent. They don't need to install openadapt-ml for GRPO.

> "What's the right way to implement this so that more people will adopt it?
> Is less code better? Should we re-use standard libs and just focus on our
> core value, which is the WAA automation?" — project lead

The answer: yes. Our adapter is ~250 lines of glue. Everything else is
verl-agent's problem.

---

## Comprehensive Framework Review

We evaluated 6 approaches before selecting verl-agent/VAGEN:

### A. TRL GRPOTrainer (HuggingFace)

**Status**: Does NOT support multi-turn VLM GRPO (as of March 2026).

- **Single-turn VLM**: Works. `pixel_values` are buffered in `_buffered_inputs`
  and passed to the training forward pass. Tested with Qwen2.5-VL.
- **Multi-turn VLM**: Broken. Chat templating is applied before the rollout
  logic, flattening structured multimodal data (text + images) into plain text.
  The `rollout_func` receives flattened text, losing image information.
- **Open issues**:
  - [#5120](https://github.com/huggingface/trl/issues/5120): "Preserve
    structured multimodal messages through rollout and generation pipeline"
    (opened Feb 18, 2026, OPEN)
  - [#5119](https://github.com/huggingface/trl/issues/5119): "Decouple
    inference backend from rollout & agent logic" (OPEN)
  - [#4543](https://github.com/huggingface/trl/issues/4543): Multi-step
    training forces one shared prompt across all generations, but multi-step
    trajectories have different prefixes at each turn
- **Verdict**: Not viable for our use case until #5120 is resolved. Monitoring.

### B. Standalone Loss Math (our initial approach)

**What we built**: 15-line `policy_gradient_loss` function + custom training
loop (~546 lines in `openadapt_ml/training/grpo/trainer.py`).

- **Pros**: Works today, simple, no external dependencies beyond HF/PEFT
- **Cons**:
  - Only episode-level rewards (no per-step credit assignment)
  - Reimplements model loading, LoRA setup, optimizer, checkpointing
  - No distributed training support
  - No vLLM/sglang acceleration
  - 546 lines of code we own and must maintain
- **Verdict**: Was the right call when TRL couldn't do multi-turn VLM. Now
  superseded by verl-agent integration.

### C. verl-agent (selected)

**Repository**: [langfengQ/verl-agent](https://github.com/langfengQ/verl-agent)

- **Multi-turn VLM GRPO**: Yes, first-class support
- **GiGPO**: Step-level credit assignment via two-level grouping
- **Qwen2.5-VL tested**: Yes (Sokoban VLM example with `run_sokoban_qwen3vl.sh`)
- **Architecture**: Step-wise interaction paradigm (no full history concatenation),
  customizable memory module per step
- **Algorithms**: GiGPO, GRPO, PPO, DAPO, GSPO, RLOO, REINFORCE++
- **Infrastructure**: Ray-based parallel environments, FSDP training, vLLM/sglang
- **Requirements**: 2+ GPUs minimum, Ray, vLLM
- **Verdict**: Best fit. Purpose-built for multi-turn VLM agent training.

### D. VAGEN / VAGEN-Lite

**Repository**: [mll-lab-nu/VAGEN](https://github.com/mll-lab-nu/VAGEN)

- Built on verl's `agent_loop` abstraction (same ecosystem as verl-agent)
- **Bi-Level GAE** for turn-aware credit assignment
- 3B model achieved 0.82 across 5 agent benchmarks (outperforming GPT-5 at 0.75)
- VAGEN-Lite (Feb 2026): lightweight reimplementation for easier customization
- **Environment protocol**: `GymImageEnv` — async `reset(seed)`, `step(action_str)`,
  `close()`, `system_prompt()`. This is the interface we implemented.
- **Verdict**: Excellent. We implemented its `GymImageEnv` protocol. Compatible
  with both VAGEN and verl-agent.

### E. OpenRLHF

**Repository**: [OpenRLHF/OpenRLHF](https://github.com/OpenRLHF/OpenRLHF)

- Supports multimodal models, has LMM-R1 fork for multimodal RL
- Implements GRPO, PPO, REINFORCE++ with Ray-based distributed training
- **Multi-turn VLM**: Less documented, unclear if fully supported
- **Verdict**: Viable alternative but less proven for multi-turn VLM specifically.

### F. Unsloth

- 1.5-2x speed, 90% less VRAM for Qwen3-VL/Gemma 3
- **Single-turn only** — not suitable for multi-step desktop automation
- **Verdict**: Not applicable.

### Comparison Matrix

| Feature                     | TRL    | Standalone | verl-agent | VAGEN  | OpenRLHF |
|-----------------------------|--------|------------|------------|--------|----------|
| Single-turn VLM GRPO        | Yes    | Yes        | Yes        | Yes    | Yes      |
| Multi-turn VLM GRPO         | **No** | Yes*       | **Yes**    | **Yes**| Unclear  |
| Per-step credit assignment   | No     | No         | **GiGPO**  | **GAE**| No       |
| Distributed training         | Yes    | No         | Yes        | Yes    | Yes      |
| vLLM/sglang acceleration    | Yes    | No         | Yes        | Yes    | Yes      |
| Qwen2.5-VL tested           | Yes    | Yes        | Yes        | Yes    | Yes      |
| Lines of code we maintain   | ~200   | ~546       | **~250**   | ~250   | ~200     |
| Ease of adoption             | High   | N/A        | Medium     | Medium | Medium   |

*Standalone multi-turn VLM works but only has episode-level rewards.

---

## Architecture

```
verl-agent / VAGEN                  openadapt-evals
┌─────────────────────┐             ┌──────────────────────┐
│ GRPOTrainer / GiGPO │             │ WAADesktopEnv        │
│  ↓                  │ GymImageEnv │  ↓                   │
│ AgentLoop           │ ──protocol──│ RLEnvironment        │
│  ↓                  │             │  ↓                   │
│ rollout_worker      │             │ WAALiveAdapter       │
│  (vLLM/sglang)      │             │  ↓                   │
│                     │             │ WAA Flask Server      │
│ They handle:        │             │ We handle:           │
│ - VLM forward pass  │             │ - Desktop automation │
│ - Log-prob storage  │             │ - Task setup/eval    │
│ - GiGPO advantages  │             │ - Action translation │
│ - FSDP training     │             │ - Screenshot capture │
│ - Checkpointing     │             │ - Stuck detection    │
└─────────────────────┘             └──────────────────────┘
```

Our adapter (`WAADesktopEnv`, ~250 lines) translates between:
- **openadapt-evals**: `BenchmarkObservation` (PNG bytes + a11y tree)
- **VAGEN**: `{"obs_str": "...", "multi_modal_input": {"<image>": [PIL.Image]}}`

The `RLEnvironment` in openadapt-evals is the **stable interface**. If
verl-agent is superseded (e.g., TRL fixes #5120), we swap the training backend
by writing a new 250-line adapter. The environment code doesn't change.

---

## What We Get for Free

By delegating to verl-agent, we avoid building and maintaining:

| Capability                        | Lines saved | Complexity saved       |
|-----------------------------------|-------------|------------------------|
| Multi-turn VLM rollout collection | ~200        | Image tensor management|
| GiGPO step-level advantages      | ~300        | State grouping logic   |
| Distributed training (FSDP)      | ~500        | Multi-GPU coordination |
| vLLM/sglang inference            | ~400        | Inference server mgmt  |
| Reference model management       | ~100        | Weight synchronization |
| Advanced logging (WandB, TB)     | ~100        | Metric tracking        |
| **Total**                         | **~1600**   |                        |

---

## Migration Path

1. **Current state**: Standalone trainer in openadapt-ml (PR #34, merged).
   Works, well-tested (56 unit tests + 5 E2E tests). Episode-level rewards only.

2. **Spike complete**: `WAADesktopEnv` adapter in openadapt-evals (PR #84).
   21 tests passing. Implements GymImageEnv protocol.

3. **Next**: Test end-to-end with verl-agent on a GPU machine. If successful,
   the standalone trainer becomes a reference implementation / fallback, and
   verl-agent becomes the recommended training path. **Note**: Both backends
   coexist — see the [Dual Backend Strategy](#dual-backend-strategy) section
   for the comparison plan and dependency approach.

4. **Future**: If TRL resolves #5120 (multi-turn VLM support), evaluate whether
   to switch. TRL has broader adoption; switching would reduce the dependency
   footprint. But only if TRL also adds per-step credit assignment comparable
   to GiGPO.

---

## Dual Backend Strategy

Rather than deprecating the standalone trainer immediately, we maintain both
backends for comparison:

### Backend 1: Standalone (openadapt-ml)

- **Code**: `openadapt_ml/training/grpo/trainer.py` (~546 lines)
- **When to use**: Quick experiments, single-GPU, no Ray/vLLM dependency
- **Limitations**: Episode-level rewards only, no GiGPO, no distributed training
- **Config**: `GRPOConfig(backend="standalone", ...)`

### Backend 2: verl-agent (openadapt-evals)

- **Code**: `openadapt_evals/adapters/verl_env.py` (~250 lines adapter)
- **When to use**: Production training, multi-GPU, GiGPO per-step credit
- **Advantages**: Distributed training, vLLM/sglang, step-level advantages
- **Config**: `configs/train_waa_vagen.yaml`

### Dependency Strategy

The `GymImageEnv` and `GymBaseEnv` abstract base classes (~150 lines) are
**vendored** into `openadapt_evals/adapters/_vendored/` to avoid requiring the
full VAGEN installation. The vendored classes are pure interfaces with only a
`Pillow` dependency. Import priority:

1. `from vagen.envs.gym_image_env import GymImageEnv` (if VAGEN installed)
2. `from openadapt_evals.adapters._vendored.gym_image_env import GymImageEnv` (fallback)

The full VAGEN/verl-agent stack (Ray, vLLM, etc.) is only needed when actually
running distributed training, not for defining or testing environments.

### Comparison Plan

To validate the verl-agent integration provides real value over standalone:

1. Train on the same WAA task with both backends
2. Compare: final reward, training wall time, GPU memory usage
3. Specifically measure whether GiGPO's per-step credit improves sample
   efficiency on long-horizon tasks (15+ steps)
4. Document results in a comparison report

---

## References

- [verl-agent](https://github.com/langfengQ/verl-agent) — GiGPO paper implementation
- [VAGEN](https://github.com/mll-lab-nu/VAGEN) — Multi-turn VLM agent training
- [verl](https://github.com/verl-project/verl) — Volcano Engine RL for LLMs
- [GiGPO paper](https://arxiv.org/html/2505.10978) — Group-in-Group Policy Optimization
- [VAGEN paper](https://arxiv.org/abs/2510.16907) — World Model Reasoning for VLM Agents
- [TRL #5120](https://github.com/huggingface/trl/issues/5120) — Multimodal rollout pipeline
- [TRL #5119](https://github.com/huggingface/trl/issues/5119) — Backend/rollout decoupling
- [TRL GRPOTrainer docs](https://huggingface.co/docs/trl/main/grpo_trainer)
- [TRL PR #3072](https://github.com/huggingface/trl/pull/3072) — Original VLM support
