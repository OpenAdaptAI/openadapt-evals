# Claude Code Instructions for openadapt-evals

## Overview

Benchmark evaluation adapters for GUI automation agents. Provides unified interfaces to run agents against WAA (Windows Agent Arena), WebArena, and other benchmarks.

## Quick Start

```bash
# Install
uv sync

# Run mock evaluation (no VM required)
uv run python -m openadapt_evals.benchmarks.cli mock --tasks 10

# Run live evaluation against WAA server
uv run python -m openadapt_evals.benchmarks.cli live --server http://vm-ip:5000 --tasks 20

# Azure parallel evaluation
uv run python -m openadapt_evals.benchmarks.cli azure --workers 10 --tasks 100
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

## Key Files

- `benchmarks/base.py` - BenchmarkAdapter ABC, data classes
- `benchmarks/mock.py` - Mock adapter for testing
- `benchmarks/waa_live.py` - HTTP adapter for remote WAA
- `benchmarks/azure.py` - Azure VM orchestration
- `benchmarks/cli.py` - CLI entry point

## Architecture

```
openadapt_evals/
├── benchmarks/
│   ├── base.py          # BenchmarkAdapter, BenchmarkTask, BenchmarkResult
│   ├── mock.py          # WAAMockAdapter
│   ├── waa_live.py      # WAALiveAdapter (HTTP)
│   ├── azure.py         # AzureWAAOrchestrator
│   └── cli.py           # CLI commands
└── __init__.py
```

## Integration with openadapt-ml

This package is used by openadapt-ml for benchmark evaluation:

```python
from openadapt_evals.benchmarks import WAALiveAdapter, evaluate_agent

adapter = WAALiveAdapter(server_url="http://vm:5000")
results = evaluate_agent(agent, adapter, tasks=20)
```

## Environment Variables

- `OPENAI_API_KEY` - For GPT-based agents
- `ANTHROPIC_API_KEY` - For Claude-based agents
- `AZURE_*` - Azure credentials (see openadapt-ml docs)
