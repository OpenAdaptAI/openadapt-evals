# Claude Code Instructions for openadapt-evals

## Overview

Benchmark evaluation adapters for GUI automation agents. Provides unified interfaces to run agents against WAA (Windows Agent Arena), WebArena, and other benchmarks.

**This is the canonical location for benchmark code.** Previously in openadapt-ml/benchmarks/, now consolidated here.

## Quick Start

```bash
# Install
uv sync

# Run mock evaluation (no VM required)
uv run python -m openadapt_evals.benchmarks.cli mock --tasks 10

# Run live evaluation against WAA server with Claude
uv run python -m openadapt_evals.benchmarks.cli live --agent api-claude --server http://vm-ip:5000 --task-ids notepad_1

# Run live evaluation with GPT-5.1
uv run python -m openadapt_evals.benchmarks.cli live --agent api-openai --server http://vm-ip:5000 --task-ids notepad_1

# Include demo trajectory (P0 fix: demo persists across ALL steps)
uv run python -m openadapt_evals.benchmarks.cli live --agent api-claude --demo demo.txt --server http://vm-ip:5000 --task-ids notepad_1

# Azure parallel evaluation
uv run python -m openadapt_evals.benchmarks.cli azure --workers 10 --waa-path /path/to/WAA

# Check server status
uv run python -m openadapt_evals.benchmarks.cli probe --server http://vm-ip:5000

# Generate HTML viewer
uv run python -m openadapt_evals.benchmarks.cli view --run-name my_eval
```

## CLI Commands

| Command | Description |
|---------|-------------|
| `mock` | Run with mock adapter (testing, no VM) |
| `live` | Run against live WAA server (supports --agent api-claude, api-openai) |
| `azure` | Run parallel evaluation on Azure |
| `probe` | Check if WAA server is ready |
| `view` | Generate HTML viewer for results |
| `estimate` | Estimate Azure costs |

## Architecture

```
openadapt_evals/
├── agents/                    # Agent implementations
│   ├── __init__.py
│   ├── base.py               # BenchmarkAgent ABC
│   ├── api_agent.py          # ApiAgent (Claude/GPT-5.1, P0 demo fix!)
│   ├── policy_agent.py       # PolicyAgent (wraps openadapt-ml models)
│   └── scripted_agent.py     # ScriptedAgent, RandomAgent, SmartMockAgent
├── adapters/                  # Benchmark adapters
│   ├── __init__.py
│   ├── base.py               # BenchmarkAdapter ABC, data classes
│   ├── waa.py                # WAAAdapter, WAAMockAdapter
│   └── waa_live.py           # WAALiveAdapter (HTTP)
├── benchmarks/                # Evaluation utilities
│   ├── runner.py             # evaluate_agent_on_benchmark()
│   ├── data_collection.py    # ExecutionTraceCollector
│   ├── viewer.py             # generate_benchmark_viewer()
│   ├── azure.py              # AzureWAAOrchestrator
│   ├── live_tracker.py       # LiveEvaluationTracker
│   └── cli.py                # Unified CLI
└── __init__.py
```

## CRITICAL: P0 Demo Persistence Fix

The `ApiAgent` class includes a critical fix: **demo is included at EVERY step, not just step 1**.

This is the fix for the "100% first-action success / 0% episode success" problem.

```python
from openadapt_evals import ApiAgent

# Demo persists across ALL steps
agent = ApiAgent(
    provider="anthropic",
    demo="Step 1: Click Start menu\nStep 2: Type 'notepad'\n..."
)

# The demo is included in EVERY API call, not just the first
# See api_agent.py lines 287-296 for implementation
```

## Key Files

| File | Description |
|------|-------------|
| `agents/api_agent.py` | ApiAgent with P0 demo persistence fix |
| `agents/base.py` | BenchmarkAgent ABC, parse_action_response() |
| `adapters/base.py` | BenchmarkAdapter ABC, BenchmarkTask, BenchmarkAction |
| `adapters/waa.py` | WAAAdapter (full WAA integration), WAAMockAdapter |
| `adapters/waa_live.py` | WAALiveAdapter (HTTP to remote WAA server) |
| `benchmarks/runner.py` | evaluate_agent_on_benchmark(), compute_metrics() |
| `benchmarks/cli.py` | CLI entry point |

## Integration with openadapt-ml

This package is standalone - it does NOT require openadapt-ml for basic functionality.

```python
# Standalone usage (no openadapt-ml dependency)
from openadapt_evals import ApiAgent, WAALiveAdapter, evaluate_agent_on_benchmark

agent = ApiAgent(provider="anthropic", demo="Step 1: Click ...")
adapter = WAALiveAdapter(server_url="http://vm:5000")
results = evaluate_agent_on_benchmark(agent, adapter, max_steps=15)
```

For users who want to use openadapt-ml trained models:

```python
# With openadapt-ml trained model
from openadapt_evals import PolicyAgent, WAALiveAdapter

agent = PolicyAgent(checkpoint_path="/path/to/checkpoint")
adapter = WAALiveAdapter(server_url="http://vm:5000")
results = evaluate_agent_on_benchmark(agent, adapter)
```

## Environment Variables

| Variable | Description |
|----------|-------------|
| `ANTHROPIC_API_KEY` | For Claude-based agents (ApiAgent with provider="anthropic") |
| `OPENAI_API_KEY` | For GPT-based agents (ApiAgent with provider="openai") |
| `AZURE_SUBSCRIPTION_ID` | Azure subscription for parallel evaluation |
| `AZURE_ML_RESOURCE_GROUP` | Azure ML resource group |
| `AZURE_ML_WORKSPACE_NAME` | Azure ML workspace name |

## Backward Compatibility

The old imports from `openadapt_ml.benchmarks` still work but emit deprecation warnings:

```python
# OLD (deprecated, shows warning)
from openadapt_ml.benchmarks import WAAMockAdapter  # DeprecationWarning

# NEW (preferred)
from openadapt_evals import WAAMockAdapter  # No warning
```

## Running Tests

```bash
# Run mock evaluation (basic sanity check)
uv run python -m openadapt_evals.benchmarks.cli mock --tasks 5

# Test imports
uv run python -c "from openadapt_evals import ApiAgent, WAAMockAdapter; print('OK')"
```
