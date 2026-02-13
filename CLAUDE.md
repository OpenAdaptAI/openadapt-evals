# Claude Code Instructions for openadapt-evals

## Project Status & Priorities

**IMPORTANT**: Before starting work, always check the project-wide status document:
- **Location**: `/Users/abrichr/oa/src/STATUS.md`
- **Purpose**: Tracks P0 priorities, active background tasks, blockers, and strategic decisions
- **Action**: Read this file at the start of every session to understand current priorities

---

## Overview

Benchmark evaluation adapters for GUI automation agents. Provides unified interfaces to run agents against WAA (Windows Agent Arena), WebArena, and other benchmarks.

**This is the canonical location for benchmark code.** Previously in openadapt-ml/benchmarks/, now consolidated here.

## Recent Major Improvements (v0.2.0 - January 2026)

### Azure Reliability Fix (PR #11)
- **Success Rate**: Fixed 0% → 95%+ target achievement
- **VM Configuration**: Upgraded to `Standard_D4s_v5` with nested virtualization support
- **Health Monitoring**: Automatic stuck job detection with 10-minute timeout

### Cost Optimization (PR #13)
- **Cost Reduction**: 67% savings ($7.68 → $2.50 per 154 tasks)
- **Tiered VM Sizing**: Auto-select VM based on task complexity
- **Spot Instances**: 70-80% discount support

### Screenshot Validation & Viewer (PR #6)
- **Real Screenshots**: Replaced mock data with actual WAA screenshots
- **Auto-Screenshot Tool**: Playwright-based with validation

See [CHANGELOG.md](./CHANGELOG.md) for complete details.

## Quick Start

```bash
# Install
uv sync

# Run mock evaluation (no VM required)
uv run python -m openadapt_evals.benchmarks.cli mock --tasks 10

# Run live evaluation (simplified - uses localhost:5001 by default)
uv run python -m openadapt_evals.benchmarks.cli run --agent api-openai --task notepad_1

# Run live evaluation (full control)
uv run python -m openadapt_evals.benchmarks.cli live --agent api-claude --server http://localhost:5001 --task-ids notepad_1

# Azure parallel evaluation
uv run python -m openadapt_evals.benchmarks.cli azure --workers 10 --waa-path /path/to/WAA

# All-in-one VM startup
uv run python -m openadapt_evals.benchmarks.cli up
```

---

## WAA BENCHMARK WORKFLOW (COMPLETE GUIDE)

### Architecture Overview

All evaluation infrastructure lives in openadapt-evals. Three CLI entry points:

- `oa` — unified CLI (`oa evals run`, `oa evals mock`)
- `oa-vm` — VM/pool management (`oa-vm pool-create`, `oa-vm status`)
- `openadapt-evals` — legacy entry point

```
LOCAL MACHINE (openadapt-evals)
├── oa-vm CLI (VM + pool management)
│   - create / delete    # Single VM lifecycle
│   - pool-create / pool-cleanup  # Multi-VM pools
│   - vm monitor         # Dashboard + SSH tunnels
│   - pool-run           # Distributed benchmark execution
│
├── oa CLI (benchmark execution)
│   - evals run          # Simplified benchmark run
│   - evals live         # Full control live eval
│   - evals mock         # No VM needed
│
└── SSH Tunnels (auto-managed by vm monitor)
    - localhost:5001 → VM:5000 (WAA Flask API)
    - localhost:8006 → VM:8006 (noVNC)

AZURE VM (Ubuntu)
└── Docker
    └── windowsarena/winarena:latest
        └── QEMU (Windows 11)
            ├── WAA Flask server (port 5000)
            └── Navi agent (executes tasks)
```

### Step-by-Step Workflow

All commands run from openadapt-evals (`cd /Users/abrichr/oa/src/openadapt-evals`).

**Step 1: Create VM Pool**
```bash
# Single VM for quick tests
oa-vm pool-create --workers 1

# Multiple VMs for parallel evaluation
oa-vm pool-create --workers 3
```

**Step 2: Wait for WAA Ready**
```bash
oa-vm pool-wait
```

**Step 3: Run Benchmark**
```bash
# Quick smoke test (no API key needed)
uv run python -m openadapt_evals.benchmarks.cli run --agent noop --task notepad_1

# With OpenAI
uv run python -m openadapt_evals.benchmarks.cli run --agent api-openai --task notepad_1

# With Claude
uv run python -m openadapt_evals.benchmarks.cli run --agent api-claude --task notepad_1

# Distributed across pool
oa-vm pool-run --tasks 10
```

**Step 4: View Results**
```bash
uv run python -m openadapt_evals.benchmarks.cli view --run-name live_eval
```

**Step 5: Cleanup (Stop Billing)**
```bash
oa-vm pool-cleanup -y
```

### Key Points

1. **One repo** - all VM management AND benchmark execution in openadapt-evals
2. **SSH tunnels required** - Azure NSG blocks direct port access
3. **Default server is localhost:5001** - The `run` command uses this automatically
4. **WAA runs INSIDE Windows** - Not on the Ubuntu host
5. **Results in benchmark_results/** - Use `view` command to see them

---

## CLI Commands

### Benchmark CLI (`openadapt_evals.benchmarks.cli`)

| Command | Description |
|---------|-------------|
| `run` | **Simplified live evaluation** (uses localhost:5001 by default) |
| `mock` | Run with mock adapter (testing, no VM) |
| `live` | Run against live WAA server (full control) |
| `azure` | Run parallel evaluation on Azure |
| `probe` | Check if WAA server is ready |
| `view` | Generate HTML viewer for results |
| `estimate` | Estimate Azure costs |
| `dashboard` | Generate VM usage dashboard |
| `up` | All-in-one: Start VM + WAA server + wait until ready |

### VM/Pool CLI (`oa-vm`)

| Command | Description |
|---------|-------------|
| `pool-create --workers N` | Create N VMs with Docker + WAA |
| `pool-wait` | Wait for WAA server ready on all workers |
| `pool-run --tasks N` | Run N tasks distributed across workers |
| `pool-status` | Show status of all pool VMs |
| `pool-vnc` | Open VNC to pool workers |
| `pool-logs` | Stream logs from all workers |
| `pool-cleanup -y` | Delete all pool VMs and resources |
| `create --fast` | Create single VM |
| `delete` | Delete VM and all resources |
| `status` | Show VM status and IP |
| `vm monitor` | Dashboard + SSH tunnels |
| `deallocate` | Stop VM (preserves disk, stops billing) |
| `azure-ml-quota-wait` | Wait for Azure quota approval |

### `run` Command (Recommended for Live Evaluation)

The `run` command is a simplified wrapper around `live` with good defaults:

```bash
# Single task
uv run python -m openadapt_evals.benchmarks.cli run --agent api-openai --task notepad_1

# Multiple tasks
uv run python -m openadapt_evals.benchmarks.cli run --agent api-openai --tasks notepad_1,notepad_2

# Smoke test (no API key)
uv run python -m openadapt_evals.benchmarks.cli run --agent noop --task notepad_1

# With custom server
uv run python -m openadapt_evals.benchmarks.cli run --server http://localhost:5001 --agent api-claude --task notepad_1
```

**Defaults:**
- `--server http://localhost:5001` (matches openadapt-ml tunnel)
- `--max-steps 15`
- `--output benchmark_results`
- `--run-name live_eval`

## Architecture

```
openadapt_evals/
├── agents/                    # Agent implementations
│   ├── base.py               # BenchmarkAgent ABC
│   ├── api_agent.py          # ApiAgent (Claude/GPT-5.1, P0 demo fix!)
│   ├── retrieval_agent.py    # RetrievalAugmentedAgent
│   └── policy_agent.py       # PolicyAgent (openadapt-ml models)
├── adapters/                  # Benchmark adapters
│   ├── base.py               # BenchmarkAdapter ABC
│   ├── waa.py                # WAAAdapter, WAAMockAdapter
│   └── waa_live.py           # WAALiveAdapter (HTTP)
├── infrastructure/            # Azure VM/pool management (migrated from openadapt-ml)
│   ├── azure_vm.py           # AzureVMManager (SDK + az CLI)
│   ├── pool.py               # PoolManager (multi-VM orchestration)
│   ├── vm_monitor.py         # VMMonitor dashboard
│   ├── azure_ops_tracker.py  # Azure operations tracking
│   ├── resource_tracker.py   # Cost tracking
│   └── ssh_tunnel.py         # SSH tunnel manager
├── waa_deploy/                # Docker agent deployment (migrated from openadapt-ml)
│   ├── api_agent.py          # ApiAgent for WAA container
│   └── Dockerfile            # WAA Docker image
├── server/                    # WAA server extensions
│   ├── evaluate_endpoint.py  # /evaluate endpoint
│   └── waa_server_patch.py   # Deploy script
├── benchmarks/                # Evaluation utilities
│   ├── runner.py             # evaluate_agent_on_benchmark()
│   ├── azure.py              # AzureWAAOrchestrator
│   ├── cli.py                # Benchmark CLI (run, mock, live, view)
│   ├── vm_cli.py             # VM/Pool CLI (oa-vm entry point, 50+ commands)
│   ├── pool_viewer.py        # Pool results HTML viewer
│   ├── trace_export.py       # Training data export
│   └── viewer.py             # HTML viewer
├── config.py                  # Settings (pydantic-settings, .env loading)
└── __init__.py
```

## CRITICAL: P0 Demo Persistence Fix (VALIDATED)

The `ApiAgent` class includes a critical fix: **demo is included at EVERY step, not just step 1**.

This fixes the "100% first-action success / 0% episode success" problem.

```python
from openadapt_evals import ApiAgent

# Demo persists across ALL steps
agent = ApiAgent(provider="anthropic", demo="Step 1: Click Start menu\n...")
```

**Validation** (Jan 17, 2026): Mock test confirmed demo persistence working. With demo: 3.0 avg steps vs without: 6.8 avg steps.

## Key Files

| File | Description |
|------|-------------|
| `agents/api_agent.py` | ApiAgent with P0 demo persistence fix |
| `agents/retrieval_agent.py` | Auto demo selection |
| `adapters/waa_live.py` | HTTP adapter for WAA server |
| `benchmarks/azure.py` | Azure orchestrator with cost optimization |
| `benchmarks/cli.py` | Benchmark CLI entry point |
| `benchmarks/vm_cli.py` | VM/Pool CLI (`oa-vm`, 50+ commands) |
| `infrastructure/azure_vm.py` | AzureVMManager (SDK + az CLI fallback) |
| `infrastructure/pool.py` | PoolManager for parallel evaluation |
| `config.py` | Settings (pydantic-settings, .env loading) |

## Azure Dashboard

Dashboard auto-launches with `vm-setup`, `up`, `azure` commands. Disable with `--no-dashboard`.
Shows: real-time costs, VM status, activity logs, start/stop controls.

**Files**: `dashboard_server.py`, CLI integration in `cli.py`

## WAA Container Setup

```bash
oa-vm vm setup-waa
```

Automated WAA deployment (95%+ reliability). Fresh VM: 15-20 min, existing: 2-5 min.
Implementation: in `benchmarks/vm_cli.py`. Use `--help` for troubleshooting.

## Screenshot Requirements

Screenshots must show real actions, not idle desktops. Use `validate_screenshots.py` to check.

## Data Usage Guidelines

**Always use real data** for demos, documentation, and examples. Mock data only for infrastructure testing.

## Synthetic Demo Generation

Generate demos for all 154 WAA tasks:

```bash
# Generate all demos
uv run python -m openadapt_evals.benchmarks.generate_synthetic_demos --all

# Validate demos
uv run python -m openadapt_evals.benchmarks.validate_demos --demo-dir demo_library/synthetic_demos
```

See `demo_library/synthetic_demos/README.md` for format and usage.

## Retrieval-Augmented Agent

Auto-retrieves relevant demos from a library:

```bash
uv run python -m openadapt_evals.benchmarks.cli live \
    --agent retrieval-claude \
    --demo-library ./demo_library \
    --server http://vm:5000
```

Requires: `uv sync --extra retrieval`

## Integration with openadapt-ml

This package is standalone. For openadapt-ml trained models:

```python
from openadapt_evals import PolicyAgent, WAALiveAdapter

agent = PolicyAgent(checkpoint_path="/path/to/checkpoint")
adapter = WAALiveAdapter(server_url="http://vm:5000")
```

## Environment Variables

**Auto-loaded from `.env` via `config.py`** - no need to pass explicitly on CLI.

```bash
# .env file (create in repo root, not committed to git)
OPENAI_API_KEY=sk-...
ANTHROPIC_API_KEY=sk-ant-...
```

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_API_KEY` | For Claude agents (api-claude) |
| `OPENAI_API_KEY` | For GPT agents (api-openai) |
| `AZURE_SUBSCRIPTION_ID` | Azure subscription |
| `AZURE_ML_RESOURCE_GROUP` | Azure ML resource group |
| `AZURE_ML_WORKSPACE_NAME` | Azure ML workspace |

Optional override on any command: `[--api-key KEY]`

## Azure Quota Management

Stale compute instances exhaust quota. Use cleanup:

```bash
# Delete stale instances
uv run python -m openadapt_evals.benchmarks.cli azure --cleanup-only

# List only (dry-run)
uv run python -m openadapt_evals.benchmarks.cli azure --cleanup-only --dry-run
```

Auto-cleanup is enabled by default. Only use `--no-cleanup` for debugging.

## WAA /evaluate Endpoint

Deploy the endpoint to the WAA server. WAALiveAdapter requires `/evaluate` to
be available; evaluations fail without it:

```bash
scp openadapt_evals/server/waa_server_patch.py azureuser@vm:/tmp/
ssh azureuser@vm "python /tmp/waa_server_patch.py"
```

See `openadapt_evals/server/evaluate_endpoint.py` for implementation.

## Running Tests

```bash
uv run pytest tests/ -v
uv run python -m openadapt_evals.benchmarks.cli mock --tasks 5
```

## PyPI Publishing

Package published at https://pypi.org/project/openadapt-evals/

Publishing via GitHub Actions on tag push:

```bash
git tag v0.1.1
git push origin v0.1.1
```

See `PYPI_PUBLISHING_PLAN.md` for details.
