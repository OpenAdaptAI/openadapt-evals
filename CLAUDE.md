# Claude Code Instructions for openadapt-evals

## MANDATORY: Branches and Pull Requests

**NEVER push directly to main. ALWAYS use feature branches and pull requests.**

1. Create a feature branch: `git checkout -b feat/description` or `fix/description`
2. Make commits on the branch
3. Push the branch: `git push -u origin branch-name`
4. Create a PR: `gh pr create --title "..." --body "..."`
5. Only merge via PR (never `git push origin main`)

This is a hard rule with NO exceptions, even for "small" changes.

### PR Titles MUST Use Conventional Commit Format

PR titles become the squash merge commit message on main. `python-semantic-release` parses these to decide version bumps. **If the PR title doesn't follow the format, no release is created.**

```
fix: short description          → patch bump (0.0.x)
feat: short description         → minor bump (0.x.0)
fix(scope): short description   → patch bump with scope
feat!: breaking change          → major bump (x.0.0)
```

**Types**: feat, fix, docs, style, refactor, perf, test, chore, ci

**Rules**: Lowercase type, colon+space, imperative mood, no period, max 72 chars.

**Examples**:
- `fix: guard empty metric_results in evaluate endpoint`
- `feat: add demo-conditioned evaluation script`
- `fix(agent): return error instead of done on CU agent failures`

**Wrong** (will NOT trigger a release):
- `Fix scoring and agent error handling` (no `fix:` prefix)
- `Update PolicyAgent` (no type prefix)

When merging with `gh pr merge --squash`, GitHub uses the PR title as the commit message — so the title format is what matters.

---

## Project Status

**Before starting work**, read the project-wide status document:
- **Location**: `/Users/abrichr/oa/src/STATUS.md`
- Tracks P0 priorities, active tasks, blockers, and strategic decisions

---

## Overview

Evaluation infrastructure for GUI agent benchmarks. Provides benchmark adapters, agent interfaces, Azure VM management, and result visualization for running agents against WAA (Windows Agent Arena) and other benchmarks.

## Quick Start

```bash
# Install
uv sync

# Mock evaluation (no VM required)
openadapt-evals mock --tasks 10

# Live evaluation (uses localhost:5001 by default)
openadapt-evals run --agent api-claude --task notepad_1

# Full control
openadapt-evals live --agent api-claude --server http://localhost:5001 --task-ids notepad_1
```

---

## WAA Benchmark Workflow

### Architecture

```
LOCAL MACHINE                          AZURE VM (Ubuntu)
+-----------------------+              +------------------------+
|  oa-vm CLI            |  SSH Tunnel  |  Docker                |
|  (pool management)    | -----------> |  +- QEMU (Win 11)     |
|                       |  :5001->:5000|     +- WAA Flask API   |
|  openadapt-evals      |  :8006->:8006|     +- Agent           |
|  (benchmark runner)   |              |                        |
+-----------------------+              +------------------------+
```

Two CLI entry points:
- `openadapt-evals` -- benchmark execution (run, mock, live, view, probe)
- `oa-vm` -- VM and pool management (pool-create, pool-wait, vm setup-waa, etc.)

SSH tunnels are required (Azure NSG blocks direct port access). The `vm monitor` command manages them automatically.

### Step-by-Step

All commands run from `/Users/abrichr/oa/src/openadapt-evals`.

```bash
# 1. Create VM(s)
oa-vm pool-create --workers 1       # single VM
oa-vm pool-create --workers 3       # parallel

# 2. Wait for WAA ready
oa-vm pool-wait

# 3. Run benchmark
openadapt-evals run --agent api-claude --task notepad_1     # single task
openadapt-evals run --agent noop --task notepad_1           # smoke test (no API key)
oa-vm pool-run --tasks 10                                   # distributed across pool

# 4. View results
openadapt-evals view --run-name live_eval

# 5. Cleanup (stop billing)
oa-vm pool-cleanup -y
```

### Key Points

1. Default server is `localhost:5001` (matches SSH tunnel to VM:5000)
2. WAA runs inside Windows (QEMU inside Docker on the Ubuntu VM)
3. Results stored in `benchmark_results/`
4. Use `oa-vm vm setup-waa` for WAA container deployment on a VM (15-20 min fresh, 2-5 min existing)

---

## CLI Reference

### Benchmark CLI (`openadapt-evals`)

| Command    | Description                                 |
|------------|---------------------------------------------|
| `run`      | Live evaluation (localhost:5001 default)     |
| `mock`     | Mock adapter, no VM required                 |
| `live`     | Live WAA server, full control                |
| `probe`    | Check if WAA server is ready                 |
| `view`     | Generate HTML viewer for results             |
| `estimate` | Estimate Azure costs                         |
| `dashboard`| Generate VM usage dashboard                  |
| `up`       | All-in-one: start VM + WAA + wait            |

### VM/Pool CLI (`oa-vm`)

| Command          | Description                            |
|------------------|----------------------------------------|
| `pool-create`    | Create N VMs with Docker and WAA       |
| `pool-wait`      | Wait until WAA is ready on all workers |
| `pool-run`       | Distribute tasks across pool workers   |
| `pool-status`    | Show status of all pool VMs            |
| `pool-vnc`       | Open VNC to pool workers               |
| `pool-logs`      | Stream logs from all workers           |
| `pool-cleanup`   | Delete all pool VMs and resources      |
| `vm monitor`     | Dashboard with SSH tunnels             |
| `vm setup-waa`   | Deploy WAA container on a VM           |
| `create`         | Create single VM                       |
| `delete`         | Delete VM and all resources            |
| `status`         | Show VM status and IP                  |
| `deallocate`     | Stop VM (preserves disk, stops billing)|

Run `oa-vm --help` for the full list of 50+ commands.

### `run` Command Defaults

- `--server http://localhost:5001`
- `--max-steps 15`
- `--output benchmark_results`
- `--run-name live_eval`

---

## Architecture

```
openadapt_evals/
+-- agents/               # Agent implementations
|   +-- base.py           #   BenchmarkAgent ABC
|   +-- api_agent.py      #   ApiAgent (Claude, GPT)
|   +-- retrieval_agent.py#   RetrievalAugmentedAgent
|   +-- policy_agent.py   #   PolicyAgent (trained models)
+-- adapters/             # Benchmark adapters
|   +-- base.py           #   BenchmarkAdapter ABC + data classes
|   +-- waa/              #   WAA live, mock, and local adapters
+-- infrastructure/       # Azure VM and pool management
|   +-- azure_vm.py       #   AzureVMManager (SDK + az CLI)
|   +-- pool.py           #   PoolManager (multi-VM orchestration)
|   +-- ssh_tunnel.py     #   SSHTunnelManager
|   +-- vm_monitor.py     #   VMMonitor dashboard
|   +-- resource_tracker.py#  Cost tracking
+-- benchmarks/           # Evaluation runner, CLI, viewers
|   +-- runner.py         #   evaluate_agent_on_benchmark()
|   +-- cli.py            #   Benchmark CLI (run, mock, live, view)
|   +-- vm_cli.py         #   VM/Pool CLI (oa-vm, 50+ commands)
|   +-- viewer.py         #   HTML results viewer
|   +-- pool_viewer.py    #   Pool results viewer
|   +-- trace_export.py   #   Training data export
+-- waa_deploy/           # Docker agent deployment
+-- server/               # WAA server extensions (/evaluate endpoint)
+-- config.py             # Settings (pydantic-settings, .env)
+-- __init__.py
```

---

## Demo Persistence (ApiAgent)

The `ApiAgent` includes the demo at EVERY step, not just step 1. This fixes the "100% first-action success / 0% episode success" problem.

```python
from openadapt_evals import ApiAgent

agent = ApiAgent(provider="anthropic", demo="Step 1: Click Start menu\n...")
# Demo persists across all steps automatically
```

---

## Environment Variables

Auto-loaded from `.env` via `config.py` (pydantic-settings). Create `.env` in repo root (not committed to git).

```bash
# .env
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-...
GOOGLE_API_KEY=...
```

| Variable                    | Description                       |
|-----------------------------|-----------------------------------|
| `ANTHROPIC_API_KEY`         | For Claude agents (api-claude)    |
| `OPENAI_API_KEY`            | For GPT agents (api-openai)       |
| `GOOGLE_API_KEY`            | For Google agents                 |
| `AZURE_SUBSCRIPTION_ID`    | Azure subscription                |
| `AZURE_RESOURCE_GROUP`     | Resource group for VMs (default: `openadapt-agents`) |
| `AZURE_CLIENT_ID`          | Service principal auth            |
| `AZURE_CLIENT_SECRET`      | Service principal auth            |
| `AZURE_TENANT_ID`          | Service principal auth            |

Optional override on any command: `[--api-key KEY]`

---

## WAA /evaluate Endpoint

WAALiveAdapter requires `/evaluate` on the WAA server. Deploy it:

```bash
scp openadapt_evals/server/waa_server_patch.py azureuser@vm:/tmp/
ssh azureuser@vm "python /tmp/waa_server_patch.py"
```

See `openadapt_evals/server/evaluate_endpoint.py` for implementation.

---

## Retrieval-Augmented Agent

Auto-retrieves relevant demos from a library:

```bash
openadapt-evals live \
    --agent retrieval-claude \
    --demo-library ./demo_library \
    --server http://localhost:5001
```

Requires: `uv sync --extra retrieval`

---

## Running Tests

```bash
uv run pytest tests/ -v
openadapt-evals mock --tasks 5
```

---

## Key Files

| File                          | Description                          |
|-------------------------------|--------------------------------------|
| `agents/api_agent.py`        | ApiAgent with demo persistence       |
| `agents/retrieval_agent.py`  | Auto demo selection                  |
| `adapters/waa/`              | WAA live, mock, local adapters       |
| `benchmarks/cli.py`          | Benchmark CLI entry point            |
| `benchmarks/vm_cli.py`       | VM/Pool CLI (oa-vm, 50+ commands)    |
| `infrastructure/azure_vm.py` | AzureVMManager                       |
| `infrastructure/pool.py`     | PoolManager for parallel evaluation  |
| `config.py`                  | Settings (pydantic-settings, .env)   |

## PyPI Publishing

Published at https://pypi.org/project/openadapt-evals/. Automated via GitHub Actions on tag push:

```bash
git tag v0.X.Y
git push origin v0.X.Y
```
