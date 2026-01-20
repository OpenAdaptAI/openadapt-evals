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

# Run live evaluation against WAA server
uv run python -m openadapt_evals.benchmarks.cli live --agent api-claude --server http://vm-ip:5000 --task-ids notepad_1

# Azure parallel evaluation
uv run python -m openadapt_evals.benchmarks.cli azure --workers 10 --waa-path /path/to/WAA

# All-in-one VM startup
uv run python -m openadapt_evals.benchmarks.cli up
```

## CLI Commands

| Command | Description |
|---------|-------------|
| `mock` | Run with mock adapter (testing, no VM) |
| `live` | Run against live WAA server |
| `azure` | Run parallel evaluation on Azure |
| `probe` | Check if WAA server is ready |
| `view` | Generate HTML viewer for results |
| `estimate` | Estimate Azure costs |
| `dashboard` | Generate VM usage dashboard |
| `up` | All-in-one: Start VM + WAA server + wait until ready |
| `vm-start` | Start an Azure VM |
| `vm-stop` | Stop (deallocate) an Azure VM |
| `vm-status` | Check Azure VM status and IP |
| `vm-setup` | Full WAA container setup (automated) |

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
├── server/                    # WAA server extensions
│   ├── evaluate_endpoint.py  # /evaluate endpoint
│   └── waa_server_patch.py   # Deploy script
├── benchmarks/                # Evaluation utilities
│   ├── runner.py             # evaluate_agent_on_benchmark()
│   ├── azure.py              # AzureWAAOrchestrator
│   ├── cli.py                # Unified CLI
│   └── viewer.py             # HTML viewer
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
| `benchmarks/cli.py` | CLI entry point |

## Azure Dashboard

Dashboard auto-launches with `vm-setup`, `up`, `azure` commands. Disable with `--no-dashboard`.
Shows: real-time costs, VM status, activity logs, start/stop controls.

**Files**: `dashboard_server.py`, CLI integration in `cli.py`

## WAA Container Setup

```bash
uv run python -m openadapt_evals.benchmarks.cli vm-setup --auto-verify
```

Automated WAA deployment (95%+ reliability). Fresh VM: 15-20 min, existing: 2-5 min.
Implementation: bash script in cli.py. Use `--help` for troubleshooting.

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

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_API_KEY` | For Claude agents |
| `OPENAI_API_KEY` | For GPT agents |
| `AZURE_SUBSCRIPTION_ID` | Azure subscription |
| `AZURE_ML_RESOURCE_GROUP` | Azure ML resource group |
| `AZURE_ML_WORKSPACE_NAME` | Azure ML workspace |

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

Deploy the endpoint to WAA server:

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
