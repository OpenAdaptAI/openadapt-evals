# GRPO Training Infrastructure: Comprehensive Research Report

**Date**: 2026-03-17
**Scope**: Desktop RL training landscape, per-step credit assignment alternatives, scaling architectures, synthetic environment feasibility

---

## 1. Executive Summary

We evaluated 30+ open-source projects for desktop GUI RL training. Key findings:

1. **HCAPO is the recommended per-step credit method** — ~80-120 lines to add to our standalone GRPO trainer, no extra model, 8.3% compute overhead, no anchor states needed. Beats GiGPO on benchmarks.
2. **VAGEN and verl-agent are separate projects** — our `train_verl_e2e.py` targets the wrong entry point. GiGPO lives in verl-agent, not VAGEN-Lite.
3. **ComputerRL's API-GUI hybrid** and **DART-GUI's entropy filtering** are the highest-impact ideas to incorporate, without adopting either framework.
4. **GUI-Genesis is not applicable** to Windows desktop tasks (mobile web only), but the dense reward concept is valuable.
5. **Our WAADesktopEnv is the only OSS project wrapping WAA for RL training.**

---

## 2. VAGEN vs verl-agent Distinction

**Critical finding**: Our decision doc conflated two separate projects.

| | VAGEN (mll-lab-nu/VAGEN) | verl-agent (langfengQ/verl-agent) |
|---|---|---|
| **Purpose** | Environment framework | Training framework |
| **Credit assignment** | Dropped Bi-Level GAE in Lite | **GiGPO** (what we want) |
| **Env interface** | `GymImageEnv` (what we built) | Own `env_base.py` (different) |
| **Desktop GUI env** | No | No |
| **Entry point** | `vagen.main_ppo` | Own training scripts |
| **Stars** | 431 | 1,700 |

**Impact**: Our `train_verl_e2e.py` targets `vagen.main_ppo` — wrong entry point for GiGPO. VAGEN-Lite only provides vanilla GRPO/PPO, which our standalone trainer already does.

**Corrected path**:
- Phase 1: Standalone GRPO trainer (shipped in PR #55)
- Phase 2: If per-step credit needed, consider HCAPO (standalone) before verl-agent (complex)

---

## 3. Per-Step Credit Assignment Methods

### 3.1 Comparison Table

| Criterion | GiGPO | **HCAPO** | iStar | HiPER |
|-----------|-------|-----------|-------|-------|
| **Can add to standalone trainer?** | No (needs verl-agent) | **YES** | Technically, but 2x memory | No (needs verl-agent) |
| **Lines of code** | ~250 adapter + verl stack | **~80-120** | ~150-200 + 2nd model | 500+ + critic |
| **Extra model in memory?** | No | **No** | YES (full policy copy) | YES (critic heads) |
| **Extra compute per step** | Anchor hashing | **8.3% (1 fwd pass/traj)** | ~100% (PRM update) | ~50% (critic + GAE) |
| **Anchor state grouping?** | YES (core limitation) | **No** | No | No |
| **Works with VLMs?** | Yes | Untested (likely yes) | Yes (tested VL-7B) | Untested |
| **Works with binary rewards?** | Yes | **Yes** | Yes | Yes |
| **ALFWorld** | 90.8% | **91.4% (96.9% w/ smoothing)** | N/A | 97.4% |
| **WebShop** | 75.2% | 73.8% | **86.5%** | 83.3% |
| **Public code?** | Yes (verl-agent) | No | No | Yes (verl-agent fork) |

### 3.2 HCAPO: Recommended Approach

**How it works**: Uses the policy LLM itself as a post-hoc critic. After collecting a rollout, it scores each intermediate action conditioned on the final state (hindsight probability). This produces an importance weight for credit assignment.

**Key advantages over GiGPO for desktop tasks**:
- **No anchor state problem**: GiGPO needs identical intermediate states across rollouts. Real desktop screenshots are almost never pixel-identical (mouse position, timing, anti-aliasing). GiGPO's step-level signal would likely be near-zero for WAA.
- **No extra model**: Uses the same policy LLM — one extra non-autoregressive forward pass per trajectory.
- **Do-no-harm mask**: Never penalizes actions in successful trajectories.
- **Temporal smoothing**: Distributes credit to preparatory actions.

**Implementation plan** (~80-120 lines in openadapt-ml):
1. `compute_hindsight_probabilities(model, processor, rollout, final_screenshot)` — ~40 lines
2. `compute_hcapo_advantages(rollouts, hindsight_probs)` — ~30 lines
3. Modifications to `_training_step()` — ~10 lines
4. Config fields: `hcapo_enabled`, `hcapo_omega`, `hcapo_clip_min/max`, `hcapo_temp`, `hcapo_smoothing_alpha`

**Hyperparameters** (robust across benchmarks per authors): omega=1.0, C_min=0.8, C_max=1.2, T_temp=5.0, alpha=0.5.

### 3.3 iStar: Second Choice

Best absolute results (86.5% WebShop) and only method tested with VLMs on visual tasks. But requires **2x GPU memory** (separate PRM model), which is a dealbreaker on A10G (24GB). Only viable on larger GPUs (L40S 48GB+).

### 3.4 GiGPO: Deprioritized

The anchor state matching problem is fundamental for desktop GUI. Screenshots vary in mouse position, animation frames, and rendering artifacts even when the UI state is semantically identical. Our `compute_anchor_state()` (a11y tree hash) partially addresses this, but a11y trees are unreliable on WAA (UIA backend can't always find window elements during transitions).

---

## 4. Scaling Architectures: ComputerRL and DART-GUI

### 4.1 ComputerRL (Zhipu AI)

**Score**: 48.9% OSWorld (open-source SOTA)
**Architecture**: gRPC-based distributed cluster, 1000+ concurrent qemu-in-docker Ubuntu VMs
**License**: Apache 2.0

**Most valuable ideas**:

1. **API-GUI Hybrid Paradigm** — Agent can issue either GUI actions OR programmatic API calls. 103 auto-constructed APIs across LibreOffice Calc (27), Impress (22), Writer (19), Chrome (11), VS Code (12), VLC (12). Yielded **134% improvement** over GUI-only and 3-3.6x faster execution. **Directly applicable to WAA** via `/execute_windows` endpoint with `win32com`/PowerShell commands.

2. **Entropulse** — Alternating RL and SFT phases to prevent entropy collapse:
   - RL Phase 1 (180 steps): 31.9% → 42.0%
   - SFT on successful rollouts: entropy restored
   - RL Phase 2 (180 steps): → 45.8%
   - Simple to implement (~100 lines wrapper around training loop)

3. **OfficeWorld Benchmark** — 180 tasks across LibreOffice Calc/Writer/Impress, directly relevant to our Core4 tasks.

**Not recommended to adopt as platform**: Tightly coupled to OSWorld/Ubuntu and GLM-4 models. Only 8 git commits, sparse docs.

### 4.2 DART-GUI

**Score**: 42.13% OSWorld
**Architecture**: Fully async 4-module design (env cluster, rollout service, data manager, trainer)
**License**: Apache 2.0

**Most valuable ideas**:

1. **Step-wise GRPO with Entropy Filtering** — Train only on top 80% of steps by token entropy. Skips steps where the model is already confident; focuses compute on decision points. Complements (not replaces) per-step credit methods like HCAPO. **Effort: 1-2 weeks.**

2. **Adaptive Data Curation** (4 levels):
   - Task: Experience pool for hard tasks (pre-collect successful trajectories)
   - Trajectory: Dynamic rollout count (fewer for easy tasks)
   - Step: High-entropy filtering (see above)
   - Token: Truncated importance sampling (for async)

3. **Throughput gains**: Environment utilization 12.2% → 67.7% (5.5x) via rollout-wise scheduling. Even with single VM, avoid batch synchronization barriers.

4. **Async architecture pattern** — Critical when scaling to 10+ VMs. Not needed for single-VM validation.

**Not recommended to adopt as platform**: Tightly coupled to OSWorld/Ubuntu, UI-TARS model, Kubernetes, MySQL. Chinese Docker registry (Aliyun).

### 4.3 Integration Roadmap

| Priority | Idea | Source | Effort | Impact |
|----------|------|--------|--------|--------|
| **P0** | HCAPO per-step credit | Paper | 1-2 weeks | Per-step signal without verl-agent |
| **P0** | Entropy-based step filtering | DART-GUI | 1-2 weeks | Focus compute on decision points |
| **P0** | Entropulse (RL/SFT alternation) | ComputerRL | 1 week | Prevent entropy collapse |
| **P1** | API-GUI hybrid actions | ComputerRL | 2-3 weeks | 134% improvement potential on Office tasks |
| **P1** | Experience pool for hard tasks | DART-GUI | 1 week | Supplement sparse success signal |
| **P1** | Dense partial-credit rewards | GUI-Genesis concept | 1-2 weeks | Replace binary with continuous rewards |
| **P2** | Async rollout architecture | DART-GUI | 4-6 weeks | Critical for 10+ VM scaling |
| **P2** | Auto-API construction | ComputerRL | 2 weeks/app | Generalize API-GUI to new apps |

---

## 5. GUI-Genesis: Synthetic Environments

**Paper**: arXiv:2602.14093 (Feb 2026)
**Core idea**: Auto-synthesize Flask web apps that mirror real tasks, with code-native verifiable rewards.

### Assessment for OpenAdapt: **Not applicable in current form.**

- Generates mobile web apps (375x812), not desktop environments
- No desktop benchmark results; transfer gap to Windows is unknown and likely large
- Depends on Kimi k2 (proprietary LLM), no code released
- Average trajectory length ~5.63 steps (ours: 15-30)

### What IS Useful

1. **Dense code-native rewards** — Instead of binary 0/1 from WAA `/evaluate`, define programmatic assertions that check intermediate state:
   - LibreOffice Calc: check cell values via UNO API
   - Writer: check font properties via document inspection
   - VS Code: check settings.json values
   - This gives continuous [0,1] rewards, enabling better credit assignment

2. **PC Agent-E** (arXiv:2505.13909) is more relevant — takes 312 real Windows trajectories, uses Claude to synthesize 9 alternative actions per step, creating trajectory trees. 141% relative improvement on WAA-V2. Closer to our use case.

---

## 6. Competitive Landscape

### Desktop RL Training Systems

| Project | Platform | RL Method | Best Score | Key Innovation |
|---------|----------|-----------|------------|----------------|
| **ComputerRL** | Ubuntu/OSWorld | GRPO + Entropulse | 48.9% OSWorld | API-GUI hybrid, 1000+ VMs |
| **UI-TARS-2** | Win+Linux+Android | Multi-turn RLVR | **50.6% WAA** | Multi-platform (not fully open) |
| **DART-GUI** | Ubuntu/OSWorld | Step-wise GRPO | 42.1% OSWorld | Async 4-module, 1.9x throughput |
| **ARPO** | Ubuntu/OSWorld | GRPO + replay | 29.9% OSWorld | Experience replay buffer |
| **ZeroGUI** | Ubuntu+Android | Online RL | +14% over base | Auto task gen + reward estimation |
| **GUI-Genesis** | Synthetic Flask | GRPO | N/A (mobile) | Synthetic envs, code-native rewards |
| **OpenAdapt** | **Windows/WAA** | **GRPO (+ HCAPO planned)** | Not yet | **Only OSS WAA RL training** |

### Key RL Training Frameworks

| Framework | Stars | GiGPO? | Multi-turn VLM? | Desktop Env? |
|-----------|-------|--------|-----------------|--------------|
| verl | 20k | No | Yes | No |
| Agent Lightning | 15.5k | No | Yes | No |
| OpenRLHF | 9.2k | No | Yes (OpenRLHF-M) | No |
| verl-agent | 1.7k | **Yes** | Yes | No |
| Agent-R1 | 1.3k | No | Yes | No |
| AgentGym-RL | 639 | No | Yes | No |
| VAGEN | 431 | No (dropped) | Yes | No |

---

## 7. Revised Architecture Recommendation

### Phase 1: Standalone GRPO + HCAPO (Current → 2 weeks)
- Standalone GRPO trainer validates RL training works with WAA at all (PR #55 shipped)
- Add HCAPO per-step credit (~80-120 lines, no dependencies)
- Add entropy-based step filtering (~50 lines)
- Add Entropulse wrapper (~100 lines)
- **Goal**: First successful RL training run on Core4 tasks

### Phase 2: Dense Rewards + API-GUI (2-4 weeks)
- Enhance WAA `/evaluate` for dense partial-credit rewards
- Prototype API-GUI hybrid actions for LibreOffice via `win32com`
- Test PC Agent-E trajectory augmentation on our 7 WAA tasks
- **Goal**: Improve sample efficiency enough for practical training

### Phase 3: Scaling (4-8 weeks, when needed)
- Adopt DART-GUI async architecture pattern (reimplemented against our pool infra)
- Scale to 10+ parallel WAA VMs
- Only consider verl-agent if HCAPO proves insufficient
- **Goal**: Production-grade training at scale

### What to Drop
- **VAGEN-Lite as training backend** — vanilla GRPO only, no advantage over standalone
- **GiGPO anchor state approach** — unreliable for pixel-based desktop screenshots
- **GUI-Genesis integration** — mobile web only, no code, proprietary LLM dependency
- **HiPER** — requires verl-agent anyway, adds hierarchical complexity

---

## 8. Sources

### Papers
- ComputerRL: [arxiv.org/abs/2508.14040](https://arxiv.org/abs/2508.14040)
- DART-GUI: [arxiv.org/abs/2509.23866](https://arxiv.org/abs/2509.23866)
- GUI-Genesis: [arxiv.org/abs/2602.14093](https://arxiv.org/abs/2602.14093)
- HCAPO: [arxiv.org/abs/2603.08754](https://arxiv.org/abs/2603.08754)
- iStar: [arxiv.org/abs/2509.19199](https://arxiv.org/abs/2509.19199)
- GiGPO: [arxiv.org/abs/2505.10978](https://arxiv.org/abs/2505.10978)
- HiPER: [arxiv.org/abs/2602.16165](https://arxiv.org/abs/2602.16165)
- VAGEN: [arxiv.org/abs/2510.16907](https://arxiv.org/abs/2510.16907)
- PC Agent-E: [arxiv.org/abs/2505.13909](https://arxiv.org/abs/2505.13909)
- UI-TARS-2: [arxiv.org/abs/2509.02544](https://arxiv.org/abs/2509.02544)
- DigiRL: [arxiv.org/abs/2406.11896](https://arxiv.org/abs/2406.11896)

### Repositories
- ComputerRL: [github.com/thudm/ComputerRL](https://github.com/thudm/ComputerRL)
- DART-GUI: [github.com/Computer-use-agents/dart-gui](https://github.com/Computer-use-agents/dart-gui)
- ARPO: [github.com/dvlab-research/ARPO](https://github.com/dvlab-research/ARPO)
- ZeroGUI: [github.com/OpenGVLab/ZeroGUI](https://github.com/OpenGVLab/ZeroGUI)
- verl: [github.com/verl-project/verl](https://github.com/verl-project/verl)
- verl-agent: [github.com/langfengQ/verl-agent](https://github.com/langfengQ/verl-agent)
- VAGEN: [github.com/mll-lab-nu/VAGEN](https://github.com/mll-lab-nu/VAGEN)
- Agent Lightning: [github.com/microsoft/agent-lightning](https://github.com/microsoft/agent-lightning)
- BrowserGym: [github.com/ServiceNow/BrowserGym](https://github.com/ServiceNow/BrowserGym)
- OSWorld: [github.com/xlang-ai/OSWorld](https://github.com/xlang-ai/OSWorld)
- PC Agent-E: [github.com/GAIR-NLP/PC-Agent-E](https://github.com/GAIR-NLP/PC-Agent-E)
- HiPER: [github.com/JonP07/HiPER-agent](https://github.com/JonP07/HiPER-agent)
