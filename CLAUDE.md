# Claude Code Instructions for openadapt-evals

## Project Status & Priorities

**IMPORTANT**: Before starting work, always check the project-wide status document:
- **Location**: `/Users/abrichr/oa/src/STATUS.md`
- **Purpose**: Tracks P0 priorities, active background tasks, blockers, and strategic decisions
- **Action**: Read this file at the start of every session to understand current priorities

This ensures continuity between Claude Code sessions and context compactions.

---

## Overview

Benchmark evaluation adapters for GUI automation agents. Provides unified interfaces to run agents against WAA (Windows Agent Arena), WebArena, and other benchmarks.

**This is the canonical location for benchmark code.** Previously in openadapt-ml/benchmarks/, now consolidated here.

## Recent Major Improvements (v0.2.0 - January 2026)

### Azure Reliability Fix (PR #11)
- **Success Rate**: Fixed 0% → 95%+ target achievement
- **VM Configuration**: Upgraded to `Standard_D4s_v5` with nested virtualization support
- **Health Monitoring**: Automatic stuck job detection with 10-minute timeout
- **Key Files**: `azure.py`, `health_checker.py`

### Cost Optimization (PR #13)
- **Cost Reduction**: 67% savings ($7.68 → $2.50 per 154 tasks)
- **Tiered VM Sizing**: Auto-select VM based on task complexity (37% savings)
- **Spot Instances**: 70-80% discount support (64% savings with tiered)
- **Real-time Tracking**: New `monitoring.py` module with cost dashboard
- **Key Files**: `azure.py`, `monitoring.py`, `live_tracker.py`

### Screenshot Validation & Viewer (PR #6)
- **Real Screenshots**: Replaced mock data with actual WAA screenshots
- **Auto-Screenshot Tool**: Playwright-based with validation (`auto_screenshot.py`)
- **Execution Logs**: Real-time log capture and viewer integration
- **Live Monitoring**: Azure ML job streaming with Flask API (`live_api.py`)
- **Key Files**: `viewer.py`, `data_collection.py`, `auto_screenshot.py`, `live_api.py`

See [CHANGELOG.md](./CHANGELOG.md) for complete details.

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

# Azure parallel evaluation (with cost optimization)
export AZURE_ENABLE_TIERED_VMS=true
export AZURE_ENVIRONMENT=development  # Enables spot instances
uv run python -m openadapt_evals.benchmarks.cli azure --workers 10 --waa-path /path/to/WAA

# Cleanup stale Azure ML compute instances (prevents quota exhaustion)
uv run python -m openadapt_evals.benchmarks.cli azure --cleanup-only

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
| `dashboard` | **Generate VM usage dashboard** showing what the VM is being used for |
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
│   ├── azure.py              # AzureWAAOrchestrator (with cost optimization)
│   ├── monitoring.py         # CostTracker, cost reporting
│   ├── health_checker.py     # Container health monitoring
│   ├── live_tracker.py       # LiveEvaluationTracker
│   ├── live_api.py           # Flask server for live monitoring
│   ├── auto_screenshot.py    # Playwright screenshot tool with validation
│   └── cli.py                # Unified CLI
└── __init__.py
```

## CRITICAL: P0 Demo Persistence Fix ✅ VALIDATED

**Status**: VALIDATED (Jan 17, 2026)

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
# See api_agent.py lines 359-367 for implementation
```

### Validation Results (Mock WAA Test - Jan 17, 2026)

**Test Setup**: Claude Sonnet 4.5, 10 tasks, mock adapter

| Condition | Success Rate | Avg Steps | Behavior |
|-----------|-------------|-----------|----------|
| Without demo | 0% (0/10) | 6.8 steps | Random exploration |
| With demo | 0% (0/10) | 3.0 steps | Follows pattern, focused actions |

**Key Findings**:
- ✅ Demo persistence **confirmed working** - demo included at every step
- ✅ Behavioral change observed - with demo: 3.0 avg steps vs without: 6.8 avg steps
- ⚠️ Mock test limited by coordinate precision issues
- 📋 **Next step**: Run full WAA evaluation (154 tasks) to measure true episode success improvement

**Code Implementation**: `openadapt_evals/agents/api_agent.py` lines 359-367

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
| `benchmarks/azure.py` | AzureWAAOrchestrator, tiered VMs, spot instances, health monitoring |
| `benchmarks/monitoring.py` | CostTracker, cost reporting, real-time cost tracking |
| `benchmarks/health_checker.py` | Container health monitoring, stuck job detection |
| `benchmarks/viewer.py` | generate_benchmark_viewer(), execution logs |
| `benchmarks/auto_screenshot.py` | Playwright screenshot tool with validation |
| `benchmarks/live_api.py` | Flask server for real-time monitoring |
| `benchmarks/live_tracker.py` | LiveEvaluationTracker with cost tracking |
| `benchmarks/cli.py` | CLI entry point |
| `benchmarks/generate_synthetic_demos.py` | Generate synthetic demo trajectories for all 154 WAA tasks |
| `benchmarks/validate_demos.py` | Validate demo format and action syntax |
| `demo_library/synthetic_demos/` | 154 synthetic demos for all WAA tasks |

## Synthetic Demo Generation

Generate synthetic demonstration trajectories for all 154 WAA tasks to enable demo-conditioned prompting at scale.

### Why Synthetic Demos?

Demo-conditioned prompting dramatically improves performance:
- **Without demo**: 33% first-action accuracy
- **With demo**: 100% first-action accuracy

Synthetic demos provide:
1. Consistent quality across all 154 tasks
2. Rapid regeneration as prompts improve
3. Scalable evaluation without manual recording

## Data Usage Guidelines

**CRITICAL PRINCIPLE:** Always use real data for demos, examples, and documentation unless specifically testing mock functionality.

### Real vs Mock Data

| Use Case | Use Real Data | Use Mock Data |
|----------|--------------|---------------|
| Documentation examples | ✅ Always | ❌ Never |
| README quick start | ✅ Always | ❌ Never (mention as testing option only) |
| Animations/GIFs | ✅ Always | ❌ Never |
| Default CLI behavior | ✅ Live/Azure | ❌ Never default to mock |
| Unit tests | ❌ Not needed | ✅ Infrastructure testing only |
| Integration tests | ✅ Preferred | ⚠️ Only if VM unavailable |

### Why Real Data Matters

**Problem with synthetic/mock demos:**
- Creates misleading impression of capabilities
- Users expect real performance, get disappointed
- Undermines trust in the project
- Makes debugging harder (hides real issues)

**Benefits of real data:**
- Honest representation of current capabilities
- Users see actual performance
- Builds trust through transparency
- Exposes real issues early

### Guidelines for New Features

When adding new features:

1. **Never create mock data by default** - Start with real data
2. **Document with real examples** - Use actual WAA evaluation results
3. **Mark mock data clearly** - If mock data is needed for testing, label it prominently
4. **Default to real** - CLI commands should default to live/Azure, not mock
5. **Warn on mock usage** - Display warnings when using mock mode

### Synthetic Demo Generation

**Purpose:** Generate demonstration trajectories for demo-conditioned prompting (research/training use).

**Important:** Synthetic demos are for training agents, NOT for misleading users about capabilities.

```bash
# Generate all 154 demos
uv run python -m openadapt_evals.benchmarks.generate_synthetic_demos --all

# Generate specific domains
uv run python -m openadapt_evals.benchmarks.generate_synthetic_demos --domains notepad,browser,office

# Generate specific tasks
uv run python -m openadapt_evals.benchmarks.generate_synthetic_demos --task-ids notepad_1,browser_5

# Use OpenAI instead of Anthropic
uv run python -m openadapt_evals.benchmarks.generate_synthetic_demos --all --provider openai

# Skip existing demos (incremental generation)
uv run python -m openadapt_evals.benchmarks.generate_synthetic_demos --all --skip-existing
```

### Validating Demos

Validate generated demos for format correctness and action syntax:

```bash
# Validate all demos
uv run python -m openadapt_evals.benchmarks.validate_demos --demo-dir demo_library/synthetic_demos

# Validate specific demo
uv run python -m openadapt_evals.benchmarks.validate_demos --demo-file demo_library/synthetic_demos/notepad_1.txt

# Save validation results to JSON
uv run python -m openadapt_evals.benchmarks.validate_demos --demo-dir demo_library/synthetic_demos --json-output validation.json
```

### Demo Format

Each demo follows a structured format:

```
TASK: Open Notepad
DOMAIN: notepad

STEPS:
1. Click on the Start menu button
   REASONING: Need to access the Start menu to find Notepad
   ACTION: CLICK(x=0.02, y=0.98)

2. Type "notepad" in search box
   REASONING: Searching is faster than navigating through menus
   ACTION: TYPE("notepad")

3. Wait for search results
   REASONING: Windows needs time to display results
   ACTION: WAIT(1.0)

4. Click on Notepad app
   REASONING: Launch the application
   ACTION: CLICK(x=0.15, y=0.3)

5. Verify Notepad is open
   REASONING: Confirm successful launch
   ACTION: DONE()

EXPECTED_OUTCOME: Notepad application is open with blank document
```

### Using Synthetic Demos

```python
from openadapt_evals import ApiAgent
from pathlib import Path

# Load synthetic demo
demo_text = Path("demo_library/synthetic_demos/notepad_1.txt").read_text()

# Create agent with demo (persists across ALL steps)
agent = ApiAgent(provider="anthropic", demo=demo_text)
```

Or via CLI:

```bash
uv run python -m openadapt_evals.benchmarks.cli live \
    --agent api-claude \
    --demo demo_library/synthetic_demos/notepad_1.txt \
    --server http://vm:5000 \
    --task-ids notepad_1
```

### Generation Approach

The generator uses a **hybrid approach**:
1. **LLM-based generation**: For complex, domain-specific trajectories (browser navigation, coding tasks)
2. **Template-based generation**: For common patterns (open app, save file, type text)
3. **Domain knowledge**: Realistic Windows UI coordinates, timing, and sequences

See `demo_library/synthetic_demos/README.md` for full documentation.

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

## VM Usage Dashboard

Track what your Azure VM is being used for with the new dashboard feature.

**Generate dashboard:**
```bash
# Display in terminal
uv run python -m openadapt_evals.benchmarks.cli dashboard

# Open in browser (HTML view)
uv run python -m openadapt_evals.benchmarks.cli dashboard --open

# Custom VM
uv run python -m openadapt_evals.benchmarks.cli dashboard --vm-name waa-eval-vm --resource-group openadapt-agents
```

**Or use the Python script directly:**
```bash
cd /Users/abrichr/oa/src/openadapt-evals
python refresh_vm_dashboard.py
```

**Dashboard shows:**
- Current VM power state (running/stopped)
- Public and private IPs
- Cost estimates (hourly/daily/weekly/monthly)
- Recent Azure ML jobs and their status
- Recent activity logs (last 7 days)
- Quick action commands

**Files:**
- `VM_USAGE_DASHBOARD.md` - Markdown dashboard (generated)
- `VM_USAGE_DASHBOARD.html` - HTML dashboard with auto-refresh (generated if --open flag used)
- `refresh_vm_dashboard.py` - Dashboard generator script
- `vm_dashboard.html` - Static HTML template

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

## Azure Quota Management and Cleanup

**CRITICAL**: Azure ML compute instances consume vCPU quota even when stopped/deallocated. Stale instances from failed or interrupted evaluations can exhaust your quota and prevent new evaluations from starting.

### Automatic Cleanup (Recommended)

By default, the Azure orchestrator now automatically:

1. **Cleans up stale instances before starting** - Deletes any compute instances from previous runs (prefix: "waa")
2. **Cleans up on completion** - Always deletes instances after evaluation, even on error
3. **Handles interruption gracefully** - Ctrl+C triggers cleanup before exit

### Manual Cleanup Commands

**List stale instances (dry-run):**
```bash
uv run python -m openadapt_evals.benchmarks.cli azure --cleanup-only --dry-run
```

**Delete all stale instances:**
```bash
uv run python -m openadapt_evals.benchmarks.cli azure --cleanup-only
```

**Delete instances with custom prefix:**
```bash
uv run python -m openadapt_evals.benchmarks.cli azure --cleanup-only --cleanup-prefix myprefix
```

### Quota Monitoring

**Check quota usage via Azure CLI:**
```bash
# List all compute instances
az ml compute list --workspace-name openadapt-ml --resource-group openadapt-agents

# Check vCPU quota
az vm list-usage --location eastus --query "[?name.value=='standardDv3Family']" -o table
```

### Troubleshooting Quota Exhaustion

**Problem**: "Quota exceeded" error when starting evaluation

**Solution**:
```bash
# 1. List stale instances
uv run python -m openadapt_evals.benchmarks.cli azure --cleanup-only --dry-run

# 2. Delete them
uv run python -m openadapt_evals.benchmarks.cli azure --cleanup-only

# 3. Verify cleanup
az ml compute list --workspace-name openadapt-ml --resource-group openadapt-agents
```

### Cost Management Tips

1. **Always use cleanup** - Never use `--no-cleanup` in production
2. **Monitor quota** - Run `--dry-run` periodically to check for leaks
3. **Use timeouts** - Default 4-hour timeout prevents runaway jobs
4. **Deallocate VMs** - Azure ML auto-deallocates after idle timeout (default: 60 min)

### Disabling Auto-Cleanup (Debugging Only)

If you need to inspect compute instances after evaluation:

```bash
# Skip cleanup after completion (instances remain)
uv run python -m openadapt_evals.benchmarks.cli azure --no-cleanup --waa-path /path/to/WAA

# Skip cleanup of stale instances (not recommended - quota risk!)
uv run python -m openadapt_evals.benchmarks.cli azure --skip-cleanup-stale --waa-path /path/to/WAA
```

**Warning**: Only use these flags for debugging. Always cleanup manually afterward.

## Azure ML Docker Image Configuration

**IMPORTANT**: Azure ML jobs use Docker images to run evaluation code. The correct public image is required to avoid authentication errors.

### Docker Image Fix (Jan 17, 2026)

**Problem**: Azure ML jobs were failing with "Access denied for Container Registry: ghcr.io"

**Root Cause**: Code was configured to use `ghcr.io/microsoft/windowsagentarena:latest` which is either private or doesn't exist.

**Solution**: Updated to use the public Docker Hub image: `windowsarena/winarena:latest`

**Changes Made:**
- Updated `AzureConfig.docker_image` default in `azure.py` (line 67)
- Updated `from_env()` method default (line 121)
- Updated documentation comments (line 83)

**Configuration:**

Default (automatically uses public image):
```python
from openadapt_evals.benchmarks.azure import AzureConfig

config = AzureConfig.from_env()
# Uses windowsarena/winarena:latest by default
```

Custom image (if needed):
```python
config = AzureConfig(
    subscription_id="...",
    resource_group="...",
    workspace_name="...",
    docker_image="your-registry/your-image:tag"  # Override if needed
)
```

Or via environment variable:
```bash
export AZURE_DOCKER_IMAGE="your-registry/your-image:tag"
```

**Image Details:**
- **Image**: `windowsarena/winarena:latest` (Docker Hub)
- **Access**: Public (no authentication required)
- **Source**: Official Windows Agent Arena project
- **Contents**: Windows 11 VM + WAA client code + dependencies

**Alternative Options:**

If you need to use a different image:
1. **Public image on Docker Hub**: Just set `docker_image` to the full image name
2. **Private image on Azure Container Registry (ACR)**: Azure ML has native ACR support, no extra config needed
3. **Private image on other registry (ghcr.io, etc.)**: See Azure ML environment authentication documentation

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

## PyPI Publishing

**Status**: Package is successfully published on PyPI at https://pypi.org/project/openadapt-evals/

### Current Version
- Version: 0.1.0
- Published: 2026-01-17
- Installation: `pip install openadapt-evals`

### Publishing Process

Publishing happens automatically via GitHub Actions when a new tag is pushed:

```bash
# 1. Update version in pyproject.toml
# 2. Commit changes
git add pyproject.toml
git commit -m "chore: bump version to 0.1.1"

# 3. Create and push tag
git tag v0.1.1
git push origin main
git push origin v0.1.1
```

### Known Issues

1. **Downloads Badge**: Shows "package not found" for newly published packages. This resolves automatically within 24-48 hours as PyPI stats services index the package.

2. **TestPyPI Publishing**: Currently fails due to missing trusted publisher configuration on test.pypi.org. Main PyPI publishing works correctly. See `PYPI_PUBLISHING_PLAN.md` for setup instructions.

### Configuration

- **Workflow**: `.github/workflows/publish.yml`
- **Publishing Method**: Trusted Publishing (OIDC) - no API tokens needed
- **Environments**: `pypi` (working), `testpypi` (needs configuration)

For detailed publishing documentation, troubleshooting, and setup instructions, see `PYPI_PUBLISHING_PLAN.md`.
