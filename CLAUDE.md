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

# Run with automatic demo retrieval (requires openadapt-retrieval)
uv run python -m openadapt_evals.benchmarks.cli live --agent retrieval-claude --demo-library ./demo_library --server http://vm-ip:5000 --task-ids notepad_1

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
| `live` | Run against live WAA server (supports --agent api-claude, api-openai, retrieval-claude, retrieval-openai) |
| `azure` | Run parallel evaluation on Azure |
| `probe` | Check if WAA server is ready |
| `view` | Generate HTML viewer for results |
| `estimate` | Estimate Azure costs |
| `up` | **All-in-one**: Start VM + WAA server + wait until ready |
| `vm-start` | Start an Azure VM |
| `vm-stop` | Stop (deallocate) an Azure VM |
| `vm-status` | Check Azure VM status and IP |
| `server-start` | Start WAA server on VM via run-command |

## Architecture

```
openadapt_evals/
├── agents/                    # Agent implementations
│   ├── __init__.py
│   ├── base.py               # BenchmarkAgent ABC
│   ├── api_agent.py          # ApiAgent (Claude/GPT-5.1, P0 demo fix!)
│   ├── retrieval_agent.py    # RetrievalAugmentedAgent (auto demo selection)
│   ├── policy_agent.py       # PolicyAgent (wraps openadapt-ml models)
│   └── scripted_agent.py     # ScriptedAgent, RandomAgent, SmartMockAgent
├── adapters/                  # Benchmark adapters
│   ├── __init__.py
│   ├── base.py               # BenchmarkAdapter ABC, data classes
│   ├── waa.py                # WAAAdapter, WAAMockAdapter
│   └── waa_live.py           # WAALiveAdapter (HTTP, with /evaluate support)
├── server/                    # WAA server extensions
│   ├── __init__.py
│   ├── evaluate_endpoint.py  # /evaluate endpoint for WAA server
│   └── waa_server_patch.py   # Script to patch WAA server with /evaluate
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
| `agents/retrieval_agent.py` | RetrievalAugmentedAgent with automatic demo selection |
| `agents/base.py` | BenchmarkAgent ABC, parse_action_response() |
| `adapters/base.py` | BenchmarkAdapter ABC, BenchmarkTask, BenchmarkAction |
| `adapters/waa.py` | WAAAdapter (full WAA integration), WAAMockAdapter |
| `adapters/waa_live.py` | WAALiveAdapter (HTTP, calls /evaluate endpoint) |
| `server/evaluate_endpoint.py` | /evaluate endpoint for WAA server integration |
| `server/waa_server_patch.py` | Script to deploy /evaluate to WAA server |
| `benchmarks/runner.py` | evaluate_agent_on_benchmark(), compute_metrics() |
| `benchmarks/cli.py` | CLI entry point |

## Retrieval-Augmented Agent (Automatic Demo Selection)

The `RetrievalAugmentedAgent` automatically retrieves the most relevant demo from a library based on the current task and screenshot. This enables automatic demo selection without manual specification.

```python
from openadapt_evals import RetrievalAugmentedAgent

# Initialize with demo library
agent = RetrievalAugmentedAgent(
    demo_library_path="/path/to/demo_library",
    provider="anthropic",  # or "openai"
    embedding_dim=512,     # embedding dimension for retrieval
    top_k=3,               # number of demos to consider
)

# The agent automatically retrieves the best demo for each task
action = agent.act(observation, task)

# Get retrieval statistics
stats = agent.get_retrieval_stats()
print(f"Used demos: {stats['demos_used']}")
```

**Requirements:**
- Install with: `uv sync --extra retrieval` (adds openadapt-retrieval dependency)
- Demo library structure: directory with `.txt` files containing `TASK:` and `DOMAIN:` headers

**CLI Usage:**
```bash
# With Claude
uv run python -m openadapt_evals.benchmarks.cli live \
    --agent retrieval-claude \
    --demo-library ./demo_library \
    --server http://vm:5000 \
    --task-ids notepad_1

# With GPT-5.1
uv run python -m openadapt_evals.benchmarks.cli live \
    --agent retrieval-openai \
    --demo-library ./demo_library \
    --server http://vm:5000 \
    --task-ids notepad_1
```

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

## Azure VM Management

The CLI includes commands to manage Azure VMs programmatically - no manual Azure portal or RDP needed.

**All-in-one startup:**
```bash
# Start VM, boot, start WAA server, wait until ready
uv run python -m openadapt_evals.benchmarks.cli up

# With custom VM name
uv run python -m openadapt_evals.benchmarks.cli up --vm-name my-waa-vm --resource-group MY-RG
```

**Individual commands:**
```bash
# Check VM status
uv run python -m openadapt_evals.benchmarks.cli vm-status

# Start VM only
uv run python -m openadapt_evals.benchmarks.cli vm-start

# Start WAA server on running VM
uv run python -m openadapt_evals.benchmarks.cli server-start

# Stop VM (deallocate to stop billing)
uv run python -m openadapt_evals.benchmarks.cli vm-stop
```

**Defaults:**
- VM Name: `waa-eval-vm`
- Resource Group: `OPENADAPT-AGENTS`

**Prerequisites:**
- Azure CLI installed and logged in (`az login`)
- VM with WAA installed at `/home/azureuser/WindowsAgentArena/`

## WAA /evaluate Endpoint

The `WAALiveAdapter.evaluate()` method calls a `/evaluate` endpoint on the WAA server that runs WAA's native evaluators (getters + metrics) to determine task success.

### Deploying the /evaluate Endpoint

The WAA server needs the `/evaluate` endpoint to be added. Use one of these methods:

**Option 1: Run the patch script on the VM**
```bash
# Copy to VM and run
scp openadapt_evals/server/waa_server_patch.py azureuser@vm:/tmp/
ssh azureuser@vm "python /tmp/waa_server_patch.py"
```

**Option 2: Add to WAA's main.py manually**
See `openadapt_evals/server/waa_server_patch.py` for the code to add.

**Option 3: Use standalone evaluator (fallback)**
```python
from openadapt_evals.server.evaluate_endpoint import create_standalone_evaluator

# Creates evaluator that works without WAA's evaluator modules
evaluate = create_standalone_evaluator("http://vm:5000")
result = evaluate(task_config)
```

### Task Configuration for Evaluation

For proper evaluation, tasks need evaluator configs in `raw_config`:

```python
from openadapt_evals import WAALiveAdapter, WAALiveConfig

# Option A: Set waa_examples_path to load configs from disk
config = WAALiveConfig(
    server_url="http://vm:5000",
    waa_examples_path="/path/to/WindowsAgentArena/src/win-arena-container/client/evaluation_examples_windows"
)
adapter = WAALiveAdapter(config)

# Option B: Load task with full config
adapter = WAALiveAdapter(WAALiveConfig(server_url="http://vm:5000"))
task = adapter.load_task_from_json("notepad_1", {
    "instruction": "Open Notepad and type hello",
    "evaluator": {
        "func": "exact_match",
        "result": {"type": "vm_file", "path": "C:/test.txt"},
        "expected": {"type": "rule", "rules": {"match": "hello"}}
    }
})
```

## Running Tests

```bash
# Run all tests
uv run pytest tests/ -v

# Run mock evaluation (basic sanity check)
uv run python -m openadapt_evals.benchmarks.cli mock --tasks 5

# Test evaluate endpoint
uv run pytest tests/test_evaluate_endpoint.py -v

# Test imports
uv run python -c "from openadapt_evals import ApiAgent, WAAMockAdapter; print('OK')"
```
