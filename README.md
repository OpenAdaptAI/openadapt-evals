# OpenAdapt Evals

> [!IMPORTANT]
> **Lifecycle: Support.** This maintained public repository produces
> qualification and release evidence for OpenAdapt. The seven product targets
> use signed admissions to determine their Production state. Evals supplies
> evidence for those decisions and remains a separate operational tool.
>
> End users don't install Evals to run a workflow. The OpenAdapt product is the
> governed demonstration compiler,
> [`openadapt-flow`](https://github.com/OpenAdaptAI/openadapt-flow), installed
> via the [`OpenAdapt`](https://github.com/OpenAdaptAI/openadapt) launcher
> (`pip install openadapt`). It compiles a demonstrated GUI workflow into a
> deterministic, locally executable program. Healthy runs make no model calls,
> and it halts instead of guessing when verification fails. Lifecycle labels for
> every repository are in the
> [repository lifecycle registry](https://github.com/OpenAdaptAI/.github/blob/main/REPOSITORY_LIFECYCLE.md).

[![Tests](https://github.com/OpenAdaptAI/openadapt-evals/actions/workflows/test.yml/badge.svg)](https://github.com/OpenAdaptAI/openadapt-evals/actions/workflows/test.yml)
[![Build](https://github.com/OpenAdaptAI/openadapt-evals/actions/workflows/release.yml/badge.svg)](https://github.com/OpenAdaptAI/openadapt-evals/actions/workflows/release.yml)
[![PyPI](https://img.shields.io/pypi/v/openadapt-evals.svg)](https://pypi.org/project/openadapt-evals/)
[![Python 3.10+](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Evaluation and benchmarking infrastructure for GUI agents and for
[OpenAdapt](https://github.com/OpenAdaptAI/openadapt), the governed demonstration
compiler. Documentation for the wider project lives at
[docs.openadapt.ai](https://docs.openadapt.ai).

## What this repository is for

OpenAdapt Evals produces the evidence behind OpenAdapt's claims. It runs GUI
agents and compiled OpenAdapt workflows against standardized benchmarks (today,
[Windows Agent Arena (WAA)](https://microsoft.github.io/WindowsAgentArena/)),
provisions and manages the cloud VMs those benchmarks need, and accounts for the
dimensions that matter to a governed compiler:

- **Compiled replay vs zero-shot agent** on the same tasks, scored by each
  benchmark's own verifier rather than by the policy's self-report.
- **Silent wrong-action rate**: how often a run writes an incorrect state without
  signalling failure.
- **Over-halt rate**: how often a run halts when it should have proceeded.
- **Cost and model-call accounting**: model calls, latency, and dollar cost per
  successful task, including the ~0-model-call healthy replay path.

Operators use this package to run qualification and publication gates. If you
want to record, compile, and replay a workflow, use the
[`OpenAdapt`](https://github.com/OpenAdaptAI/openadapt) launcher.

### Qualification and release evidence

The v3 campaign producer records six required classes for each task: healthy,
safe halt, idempotency replay, uncertain delivery, declared attended, and
governed repair. Each task and condition needs at least three signed trials.
Evals derives silent incorrect success and over-halt from the signed runner,
observer, and delivery facts. It doesn't trust author-supplied failure counts.

Campaign payloads and trial receipts stay inside the approved private evidence
boundary. A public lifecycle summary uses the remote-safe decision receipt,
the public qualification admission, and the production acceptance manifest. It
contains aggregate class counts and commitments, without task names,
application or environment values, or live identities.

`scripts/build_production_evidence.py` builds that summary and the paired
content-addressed v2 references. The pair command preserves the raw Sigstore
bundle bytes. Run it only after the referenced objects exist in an exact merged
registry commit. The summary uses a later registry append, which avoids a
commit-hash cycle.

```bash
python scripts/build_production_evidence.py summary \
  --input public-summary-input.json \
  --output production-acceptance-summary.json

python scripts/build_production_evidence.py pair \
  --kind production-acceptance-summary \
  --object production-acceptance-summary.json \
  --sigstore-bundle production-acceptance-summary.sigstore.json \
  --registry-source-commit "$MERGED_REGISTRY_COMMIT" \
  --registry-revision "$REGISTRY_REVISION" \
  --registry-head-sha256 "$REGISTRY_HEAD_SHA256" \
  --output-root public-registry-candidate \
  --references-output production-acceptance-summary.references.json
```

### Relationship to the rest of OpenAdapt

OpenAdapt is a governed demonstration compiler: record once, compile, then
replay deterministically with zero model calls on the healthy path, halting
instead of guessing when verification fails. All execution substrates (web,
Windows, macOS, Linux, RDP, and Citrix/VDI) are first-class in the product. This
repository is where those substrates get measured. Its primary target today is
the Windows substrate via WAA, because WAA gives an independent, reproducible
verifier for real desktop tasks. Substrate maturity across the product is
tracked honestly in the [OpenAdapt docs](https://docs.openadapt.ai); this repo
does not claim maturity it has not measured.

## Benchmark Viewer

![Benchmark Viewer Animation](https://raw.githubusercontent.com/OpenAdaptAI/openadapt-evals/main/animations/benchmark-viewer.webp)

<details>
<summary>More screenshots</summary>

**Task Detail View** (step-by-step replay with screenshots, actions, and execution logs):

![Task Detail View](https://raw.githubusercontent.com/OpenAdaptAI/openadapt-evals/main/docs/screenshots/desktop_task_detail.png)

**Cost Tracking Dashboard** (real-time VM cost monitoring with tiered sizing and spot instances):

![Cost Dashboard](https://raw.githubusercontent.com/OpenAdaptAI/openadapt-evals/main/screenshots/cost_dashboard_preview.png)

</details>

## What is inside

- **openadapt-flow evaluation** (`openadapt_evals/flow/`): the release-path
  eval for a demonstration compiler. A `replay` runner compiles one demonstration
  into an openadapt-flow bundle and replays it against the WAA in-guest server
  with roughly zero model calls, and a `hybrid` agent runs compiled replay first
  with a computer-use fallback only on a detected halt. Both are scored by WAA's
  own task verifier. Driven by `scripts/eval_flow_on_waa.py`, which is dry-run by
  default and hard cost-capped (see below).
- **Meta-benchmark harness** (`openadapt_evals/harness/`): one driver that runs
  the record, compile, replay, heal, verify loop across any registered
  `Environment` and emits one metrics row per `(env, task, mode)`. Success is the
  environment's own verifier verdict, never the policy's self-report. Includes an
  export path to [Inspect AI](https://inspect.aisi.org.uk/) format.
- **Benchmark adapters** (`openadapt_evals/adapters/`): WAA live and mock
  adapters, a `LocalAdapter` for native desktop runs with no VM, a `ScrubMiddleware`
  wrapper that removes PII before the agent sees a screenshot, and a
  verl-compatible environment wrapper. The `BenchmarkAdapter` base is designed to
  extend to other benchmarks such as OSWorld or WebArena; only WAA and local are
  implemented today.
- **Agent interfaces** (`openadapt_evals/agents/`): `PlannerGrounderAgent`
  (dual-model, "what to do" separated from "where to click"), `ApiAgent`
  (Claude or GPT with demo persistence), `DemoGuidedAgent`, `DemoExecutor`
  (tiered deterministic replay), `RetrievalAugmentedAgent`, `ClaudeComputerUseAgent`,
  and `PolicyAgent` for trained models.
- **Cloud VM infrastructure** (`openadapt_evals/infrastructure/`): Azure and AWS
  VM managers behind one `VMProvider` protocol, a `PoolManager` for parallel
  evaluation, SSH tunnel management, a monitoring dashboard, and cost tracking.
- **RL training infrastructure** (`openadapt_evals/training/`, `openenv/`): a
  standalone GRPO trainer with zero openadapt-ml dependency, a TRL `GRPOTrainer`
  rollout function, an AReaL workflow wrapper, an OpenEnv-compatible environment,
  and trajectory logging and caching utilities. This is research-stage.
- **Workflow extraction pipeline** (`openadapt_evals/workflow/`): a four-pass
  pipeline (scrub, transcript, extract, match) for turning desktop recordings
  into structured workflows.
- **Analysis and evidence** (`openadapt_evals/analysis/`, `eval_results/`):
  trace analysis, report generation, and committed performance reports produced
  by `scripts/report_openadapt_performance.py` and
  `scripts/run_current_flow_local_benchmark.py`.
- **CLI tooling**: a `oa` VM lifecycle CLI, an `oa-vm` pool CLI, and an
  `openadapt-evals` benchmark CLI (see [CLI Reference](#cli-reference)).

## Installation

```bash
pip install openadapt-evals
```

With optional dependencies:

```bash
pip install openadapt-evals[training]   # GRPO trainer + Outlines constrained decoding
pip install openadapt-evals[azure]      # Azure VM management
pip install openadapt-evals[aws]        # AWS EC2 management
pip install openadapt-evals[retrieval]  # Demo retrieval agent
pip install openadapt-evals[viewer]     # Live results viewer
pip install openadapt-evals[all]        # Everything
```

For development, clone the repo and use [uv](https://docs.astral.sh/uv/):

```bash
git clone https://github.com/OpenAdaptAI/openadapt-evals.git
cd openadapt-evals
uv sync --extra dev
uv run pytest tests/ -v
```

## Quick Start

### Run a mock evaluation (no VM, no API key)

```bash
openadapt-evals mock --tasks 10
```

### Run a live evaluation against a WAA server

```bash
# Start a single VM (Azure by default)
oa-vm pool-create --workers 1
oa-vm pool-wait

# Or use AWS
oa-vm pool-create --cloud aws --workers 1
oa-vm pool-wait --cloud aws

# Run evaluation
openadapt-evals run --agent api-claude --task notepad_1

# View results
openadapt-evals view --run-name live_eval

# Clean up (stop billing)
oa-vm pool-cleanup -y
```

### Python API

```python
from openadapt_evals import (
    ApiAgent,
    WAALiveAdapter,
    WAALiveConfig,
    evaluate_agent_on_benchmark,
    compute_metrics,
)

adapter = WAALiveAdapter(WAALiveConfig(server_url="http://localhost:5001"))
agent = ApiAgent(provider="anthropic")

results = evaluate_agent_on_benchmark(agent, adapter, task_ids=["notepad_1"])
metrics = compute_metrics(results)
print(f"Success rate: {metrics['success_rate']:.1%}")
```

## Evaluating openadapt-flow on WAA

This is the point of the repository: measuring the demonstration compiler, not
just generic agents. `scripts/eval_flow_on_waa.py` runs openadapt-flow against
WAA in two modes, both scored by WAA's own verifier.

- **replay**: compile one demonstration into a bundle, then replay it via the
  Windows backend against the WAA in-guest server with roughly zero model calls.
  This is the paradigm-correct eval for a compiler.
- **hybrid**: compiled replay first, with a computer-use agent fallback only on a
  detected halt. Directly comparable to a pure agent baseline on the same tasks.

**Safety.** This command is dry-run by default. It never provisions Azure, never
starts a VM, and makes no network calls unless you pass `--live`, which also
requires a reachable WAA server and stays under hard cost caps. A prior uncapped
run was expensive, which is why the caps are mandatory.

```bash
# Cost estimate and plan for a 10-task and a full (154) replay run (no network):
python scripts/eval_flow_on_waa.py --mode replay --tasks 10 --dry-run
python scripts/eval_flow_on_waa.py --mode replay --tasks 154 --dry-run

# Hybrid dry-run assuming a 30% halt/fallback rate:
python scripts/eval_flow_on_waa.py --mode hybrid --tasks 154 --fallback-rate 0.3 --dry-run

# Live run (gated: needs Azure, a revived waa-pool, and maintainer go-ahead):
python scripts/eval_flow_on_waa.py --mode replay --task-ids <id1>,<id2> \
    --bundles ./flow_bundles --server-url http://localhost:5001 --live
```

The `openadapt-eval-flow` console entry point wraps the same script.

### Evidence reports

Bounded, reproducible performance reports are committed under `eval_results/`
and generated by `scripts/report_openadapt_performance.py`,
`scripts/run_current_flow_local_benchmark.py`,
`scripts/run_flow_transaction_probe.py`, and
`scripts/probe_remote_lease_safety.py`, each with an accompanying markdown
summary. These reports are the source for public performance claims and are
intended to be regenerable. Deployment-derived thresholds, tuned adversary
parameters, per-system-of-record oracle recipes, and real customer datasets are
not part of this open repository.

Every report is bound to one exact `openadapt-flow` wheel, so a Flow release can
invalidate it without any commit landing here.
`docs/eval_results/PUBLISHED_EVIDENCE.json` records which evidence set is
current and which release it was measured against, and
`scripts/check_published_evidence_freshness.py` fails when that pin no longer
matches the current published release. The current set also has an
`EVIDENCE_MANIFEST.json` that inventories the verifier scripts, retained
artifacts, public reports, campaign environments, and task/oracle contracts.
The 1.28 set remains stale because its run did not retain an exact browser
revision or installed dependency snapshot. The current 1.31 set records those
facts for every campaign. The check runs offline on every pull request and
against PyPI on a daily schedule (`.github/workflows/evidence-freshness.yml`).
Re-run the comparison and publish a new evidence set rather than editing an old
one: superseded reports stay reproducible against the wheel they were measured
on.

The word `current` means release-fresh. It does not mean production-accepted.
Each campaign records its evidence class, whether it is production acceptance,
and whether it counts silent incorrect success and over-halt. The present set
contains local synthetic and contract-fixture evidence only. See the
[production-readiness evidence boundary](docs/eval_results/PRODUCTION_READINESS.md)
for the missing acceptance tracks and their exit conditions.

See `docs/eval_results/current_flow_v1_31_0_local_20260818/` for the current
comparison and its exact retained campaign reports. The older sets remain
available as stale historical evidence; they were not relabeled.

## More workflows

### Demo-conditioned evaluation

Record demos on a remote VM via VNC, annotate with a VLM, then run
demo-conditioned eval:

```bash
# 1. Pre-flight check: verify all required apps are installed
python scripts/record_waa_demos.py record-waa \
  --tasks 04d9aeaf,0a0faba3 --server http://localhost:5001 --verify

# 2. Record demos interactively (perform actions on VNC, press Enter after each step)
python scripts/record_waa_demos.py record-waa \
  --tasks 04d9aeaf,0a0faba3 --server http://localhost:5001 --output waa_recordings/

# 3. Annotate recordings with a VLM
python scripts/record_waa_demos.py annotate \
  --recordings waa_recordings/ --output annotated_demos/ --provider openai

# 4. Run demo-conditioned eval
python scripts/record_waa_demos.py eval \
  --demo_dir annotated_demos/ --tasks 04d9aeaf,0a0faba3
```

### Full evaluation runner

`scripts/run_full_eval.py` is a production-grade runner with resume support,
per-task error isolation, health checks with exponential backoff, and parallel
pool execution:

```bash
# List tasks without executing
python scripts/run_full_eval.py --dry-run --server-url http://localhost:5001

# Single VM, all WAA tasks, API grounder
python scripts/run_full_eval.py \
    --server-url http://localhost:5001 --grounder-model gpt-4.1-mini

# Parallel across pool VMs
python scripts/run_full_eval.py --grounder-model gpt-4.1-mini --parallel 3
```

### Dedicated grounder endpoint (UI-Venus)

For higher click accuracy, serve
[UI-Venus-1.5-8B](https://huggingface.co/inclusionAI/UI-Venus-1.5-8B) on a GPU
and point the DemoExecutor or PlannerGrounderAgent at it. This replaces general
VLM grounding with a purpose-built GUI grounding model.

```bash
# On a GPU machine (A10G 24GB, RTX 4090, etc.):
bash scripts/serve_ui_venus.sh   # serves at http://0.0.0.0:8000 by default
curl http://gpu-host:8000/v1/models

# Run the full evaluation with the grounder
python scripts/run_full_eval.py \
    --server-url http://localhost:5001 --grounder-endpoint http://gpu-host:8000
```

The endpoint uses the UI-Venus native bounding-box prompt format
(`[x1,y1,x2,y2]`) and is compatible with vLLM, Ollama, or any OpenAI-compatible
server.

### GRPO training with TRL (research-stage)

The RL path trains VLM desktop agents with TRL's `GRPOTrainer` and dense
milestone rewards from WAA environments:

```bash
# Basic training against a live WAA VM
python scripts/train_trl_grpo.py \
    --task-dir ./example_tasks --server-url http://localhost:5001 \
    --model Qwen/Qwen2.5-VL-7B-Instruct --output ./grpo_output

# Mock mode (validates the full pipeline without a VM or GPU)
python scripts/train_trl_grpo.py --task-dir ./example_tasks --mock --output ./grpo_output_mock
```

Key flags: `--constrained-decoding` (Outlines regex, eliminates unparseable
output), `--vision-loss-mode` (exclude, include, or checkpoint),
`--weave-project` (Weave tracing), `--use-vllm` (faster generation),
`--loss-type` (grpo, dapo, or dr_grpo).

## Architecture

```
openadapt_evals/
├── flow/                 # openadapt-flow evaluation (compiler under test)
│   ├── replay_runner.py  #   demonstrate-then-replay against WAA (~0 model calls)
│   ├── hybrid_agent.py   #   compiled replay first, agent fallback on halt
│   ├── cost.py           #   model-call and dollar accounting
│   └── parallels_env.py  #   local Parallels-backed Windows env
├── harness/              # meta-benchmark harness (one driver, one metrics row)
│   ├── runner.py         #   run_meta over any Environment, verifier-scored
│   ├── protocol.py       #   Environment protocol
│   ├── adapters.py       #   BenchmarkAdapter -> Environment bridge
│   └── inspect_export.py #   export to Inspect AI format
├── agents/               # Agent implementations
│   ├── planner_grounder_agent.py  # PlannerGrounderAgent (dual-model)
│   ├── api_agent.py      #   ApiAgent (Claude, GPT) with demo persistence
│   ├── demo_guided_agent.py       # DemoGuidedAgent (demo-conditioned + self-verify)
│   ├── demo_executor.py  #   DemoExecutor (tiered deterministic replay)
│   ├── retrieval_agent.py#   RetrievalAugmentedAgent
│   ├── claude_computer_use_agent.py  # Claude computer-use agent
│   └── policy_agent.py   #   PolicyAgent (trained models)
├── adapters/             # Benchmark adapters
│   ├── base.py           #   BenchmarkAdapter ABC + data classes
│   ├── waa/              #   WAA live + mock adapters
│   ├── local/            #   LocalAdapter (native desktop, no VM)
│   ├── scrub_middleware.py#  ScrubMiddleware (PII removal, strict mode)
│   ├── rl_env.py         #   RLEnvironment (Gymnasium-style wrapper)
│   └── verl_env.py       #   verl-compatible environment wrapper
├── openenv/              # OpenEnv-compatible environment (HTTP + WebSocket)
├── training/             # RL training infrastructure
│   ├── standalone/       #   Standalone GRPO trainer (zero openadapt-ml deps)
│   ├── trl_rollout.py    #   TRL GRPOTrainer rollout_func
│   ├── areal_workflow.py #   AReaL AgentWorkflow wrapper
│   ├── trajectory_logger.py  # SFT data collection
│   └── planner_cache.py  #   pHash-based planner response cache
├── workflow/             # 4-pass workflow extraction (scrub/transcript/extract/match)
├── evaluation/           # Built-in verifiers + verifier registry
├── infrastructure/       # Azure/AWS VM and pool management
│   ├── azure_vm.py, aws_vm.py, vm_provider.py, pool.py
│   ├── ssh_tunnel.py, vm_monitor.py, resource_tracker.py
├── benchmarks/           # Evaluation runner, CLIs, viewers, trace export
├── analysis/             # Trace analysis + report generation
├── cli/                  # Unified `oa` CLI (VM lifecycle)
├── waa_deploy/           # WAA Docker image (QEMU + Windows 11 + Flask) + task setup
├── server/               # WAA server extensions (/evaluate endpoint)
├── task_config.py        # YAML/JSON custom task definitions
├── demo_library.py       # DemoLibrary (directory-based demo storage)
├── correction_*.py       # Human correction capture, store, and parsing
└── config.py             # Settings (pydantic-settings, .env)

scripts/
├── eval_flow_on_waa.py          # Evaluate openadapt-flow on WAA (dry-run default)
├── report_openadapt_performance.py   # Generate committed performance reports
├── run_current_flow_local_benchmark.py  # Local Flow benchmark
├── run_flow_transaction_probe.py     # Transaction outcome taxonomy probe
├── check_published_evidence_freshness.py  # Evidence-vs-release drift guard
├── extract_over_halt_regression.py   # Over-halt regression artifact extractor
├── run_full_eval.py             # Full evaluation runner with resume + parallel
├── collect_distillation_data.py # Teacher trajectory collection for SFT
├── finetune_distilled.py        # Student model LoRA fine-tuning
├── record_waa_demos.py          # Record demos from VNC sessions
└── train_trl_grpo.py            # TRL GRPO RL training
```

### How the WAA stack fits together

```
LOCAL MACHINE                          CLOUD VM (Azure or AWS, Ubuntu)
+---------------------+                +------------------------------+
|  oa-vm CLI          |   SSH Tunnel   |  Docker                      |
|  (pool management)  | ============>  |  +- evaluate_server (:5050)  |
|                     |  :5001 -> :5000|  |  +- /setup, /evaluate     |
|  openadapt-evals    |  :5051 -> :5050|  +- Samba share (/tmp/smb/)  |
|  (benchmark runner) |  :8006 -> :8006|  +- QEMU (Win 11)            |
|                     |                |     +- WAA Flask API (:5000) |
|                     |                |     +- Agent                 |
+---------------------+                +------------------------------+
```

Both cloud backends use the same `VMProvider` protocol. Pass `--cloud azure`
(default) or `--cloud aws` to any pool command. AWS supports nested
virtualization on C8i/M8i/R8i instances; Azure uses `Standard_D8ds_v5`. See
[docs/gpu_e2e_validation/architecture.md](docs/gpu_e2e_validation/architecture.md)
for the full networking and SSH tunnel details, and the CLAUDE.md in this repo
for the Docker `--cap-add NET_ADMIN` requirement and the port 5050 socat bridge.

## CLI Reference

The repository ships three console entry points.

### Benchmark CLI (`openadapt-evals`)

| Command      | Description                                                     |
|--------------|-----------------------------------------------------------------|
| `run`        | Run live evaluation (localhost:5001 default)                    |
| `mock`       | Run with the mock adapter (no VM required)                      |
| `live`       | Run against a WAA server with full control                      |
| `eval-suite` | Automated full-cycle evaluation (zero-shot + demo-conditioned)  |
| `azure`      | Run parallel evaluation on Azure ML                             |
| `probe`      | Check WAA readiness (`--detailed` for 4-layer diagnostics)      |
| `view`       | Generate the HTML results viewer                                |
| `estimate`   | Estimate Azure costs                                            |

### VM lifecycle CLI (`oa`)

Single-VM lifecycle and diagnostics: `setup`, `status`, `start`, `stop`,
`deallocate`, `delete`, `probe`, `logs`, `diag`, `ssh`, `vnc`, `exec`, and
`monitor`. Run `oa --help` for details.

### VM/Pool CLI (`oa-vm`)

| Command         | Description                              |
|-----------------|------------------------------------------|
| `pool-create`   | Create N VMs with Docker and WAA         |
| `pool-wait`     | Wait until WAA is ready on all workers   |
| `pool-run`      | Distribute tasks across pool workers     |
| `pool-status`   | Show status of all pool VMs              |
| `pool-pause`    | Deallocate pool VMs (stop billing)       |
| `pool-resume`   | Restart deallocated pool VMs             |
| `pool-cleanup`  | Delete all pool VMs and resources        |
| `image-create`  | Create a golden image from a pool VM     |
| `vm setup-waa`  | Deploy the WAA container on a VM          |
| `smoke-test-aws`| Verify AWS credentials, AMI, VPC, lifecycle |

All pool commands accept `--cloud azure` (default) or `--cloud aws`. Run
`oa-vm --help` for the full list of 50+ commands.

Additional console entry points: `openadapt-eval-flow` (evaluate openadapt-flow
on WAA), `openadapt-train-grpo`, `openadapt-eval`, `openadapt-collect`,
`openadapt-analyze`, and `openadapt-gpu` (GPU instance lifecycle).

## Configuration

Settings are loaded automatically from environment variables or a `.env` file in
the project root via
[pydantic-settings](https://docs.pydantic.dev/latest/concepts/pydantic_settings/).

```bash
# .env
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...

# Azure (for --cloud azure VM management)
AZURE_SUBSCRIPTION_ID=...
AZURE_ML_RESOURCE_GROUP=...
AZURE_ML_WORKSPACE_NAME=...
```

### AWS authentication

AWS credentials are resolved via
[boto3's default credential chain](https://boto3.amazonaws.com/v1/documentation/api/latest/guide/credentials.html).
SSO (IAM Identity Center) is recommended for interactive use:

```bash
aws configure sso   # one-time guided wizard
aws sso login       # opens browser, caches a short-lived token
oa-vm smoke-test-aws
oa-vm pool-create --cloud aws --workers 1
```

Static keys (`AWS_ACCESS_KEY_ID` and `AWS_SECRET_ACCESS_KEY`) also work but are
not recommended for interactive use, since they do not expire. See
[`openadapt_evals/config.py`](openadapt_evals/config.py) for all settings.

## Custom Agents

Implement the `BenchmarkAgent` interface to evaluate your own agent:

```python
from openadapt_evals import BenchmarkAgent, BenchmarkAction, BenchmarkObservation, BenchmarkTask

class MyAgent(BenchmarkAgent):
    def act(
        self,
        observation: BenchmarkObservation,
        task: BenchmarkTask,
        history: list[tuple[BenchmarkObservation, BenchmarkAction]] | None = None,
    ) -> BenchmarkAction:
        return BenchmarkAction(type="click", x=0.5, y=0.5)

    def reset(self) -> None:
        pass
```

## Contributing

This is research infrastructure and it moves quickly. Contributions are welcome:

```bash
git clone https://github.com/OpenAdaptAI/openadapt-evals.git
cd openadapt-evals
uv sync --extra dev
uv run pytest tests/ -v
```

Branches and pull requests only, never a direct push to `main`. PR titles must
use [conventional commit](https://www.conventionalcommits.org/) format, since
`python-semantic-release` parses them to decide version bumps. See
[CLAUDE.md](https://github.com/OpenAdaptAI/openadapt-evals/blob/main/CLAUDE.md)
for development conventions, the WAA benchmark workflow, and architecture detail.

## Related Projects

| Project | Description |
|---------|-------------|
| [OpenAdapt](https://github.com/OpenAdaptAI/openadapt) | Launcher for the governed demonstration compiler (`pip install openadapt`) |
| [openadapt-flow](https://github.com/OpenAdaptAI/openadapt-flow) | The demonstration compiler itself (record, compile, deterministic replay) |
| [openadapt-ml](https://github.com/OpenAdaptAI/openadapt-ml) | Training and policy runtime |
| [openadapt-capture](https://github.com/OpenAdaptAI/openadapt-capture) | Screen recording and demo sharing |
| [openadapt-consilium](https://github.com/OpenAdaptAI/openadapt-consilium) | Multi-model consensus library |
| [openadapt-grounding](https://github.com/OpenAdaptAI/openadapt-grounding) | UI element localization |

Project documentation: [docs.openadapt.ai](https://docs.openadapt.ai). Full
organization: [github.com/OpenAdaptAI](https://github.com/OpenAdaptAI).

## License

[MIT](https://opensource.org/licenses/MIT)
</content>
