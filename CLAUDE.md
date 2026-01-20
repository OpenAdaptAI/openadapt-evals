# Claude Code Instructions for openadapt-evals

## 🚨 Simplicity Guidelines (READ THIS FIRST!)

**CRITICAL**: Read this BEFORE writing any code.

**Philosophy**: "Less is more. 80/20 impact/complexity. Working code beats elegant design."

### For Claude Code Agents

**Default to the simplest approach**:
- ✅ **Functions, not classes** - Use classes only when you need inheritance or shared state
- ✅ **Inline bash scripts are fine** - If they work and solve the problem, don't wrap them in Python classes
- ✅ **Don't write design docs for code that doesn't exist** - Document reality, not aspirations
- ✅ **1-2 helper functions max, not frameworks** - Extract abstractions only after 3rd use
- ✅ **If you're writing >100 lines, ask: can this be 10 lines?** - Challenge complexity

### Before Writing Code, Ask

1. **Does this solve a real, immediate problem?** (not theoretical)
2. **Can I do this in <100 lines?** (ideally <50)
3. **Is this the simplest approach?** (not the most elegant)
4. **Does this provide 80% of value?** (not 100% perfection)

**If NO to any → STOP. Simplify or delete the requirement.**

### Red Flags (What NOT to Do)

Our recent over-engineering examples from this repo:

#### ❌ Example 1: Design Docs for Non-Existent Code
**What we did**: Wrote 6,000+ lines (WAA_RELIABILITY_PLAN.md, VM_SETUP_COMMAND.md) describing VMSetupOrchestrator, CircuitBreaker, RetryConfig
**What existed**: 305-line bash script in cli.py that worked fine
**Problem**: Developers tried to import non-existent classes, wasted hours
**Lesson**: Document what IS, not what MIGHT BE

#### ❌ Example 2: Utility Classes Used Once
**What we did**: Created elaborate utility classes for one-time use
**What we should have done**: Inline the 10 lines
**Problem**: Added complexity without benefit
**Lesson**: Extract only after 3rd use

#### ❌ Example 3: Multiple Implementations
**What we did**: Container start logic in 3 places (cmd_vm_setup, cmd_server_start, cmd_up) - 487 lines total
**What we should have done**: One function (40 lines)
**Problem**: Inconsistent behavior, hard to maintain
**Lesson**: DRY - Don't Repeat Yourself

#### ❌ Example 4: TODOs That Return Empty Strings
```python
def _get_job_logs(self, job_name: str) -> str:
    # TODO: Implement
    return ""  # LIES TO CALLER! health_checker.py line 289
```
**Lesson**: Delete non-functional code. If it doesn't work, it shouldn't exist.

#### ❌ Example 5: Bash Scripts Wrapped in Python
**What we considered**: Wrapping working 295-line bash script in Python orchestrator
**What we realized**: Bash works fine, don't add layers
**Lesson**: If it works, ship it. Don't add abstraction for "elegance"

### Decision Framework Checklist

**Use this before writing ANY code**:

```
Before writing:
□ Is it necessary? (solves real problem now, not theoretical)
□ Is it simple? (<100 lines, no dependencies if avoidable)
□ Is it the 80% solution? (covers common case, ignores edge cases)

If all 3 aren't YES → STOP and simplify
```

### Quick Reference Card

**When in doubt**:
- Ship working code > perfect design
- 10 lines > 100 lines
- Functions > classes
- Inline > abstraction (until 3rd use)
- Delete > keep (if unsure)
- Real data > mocks
- Tests > docs

**The best code is the code you didn't write.**

**Full guidelines**: `/Users/abrichr/oa/src/openadapt-evals/SIMPLICITY_PRINCIPLES.md` (431 lines)

---

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

### Auto-Launching Azure Dashboard (NEW - January 2026)
- **Auto-Launch**: Dashboard automatically opens when Azure resources start
- **Real-Time Monitoring**: Live cost tracking, resource status, and activity logs
- **Resource Control**: Stop/start VMs directly from dashboard UI
- **Cost Alerts**: Automatic warnings when costs exceed thresholds
- **Activity Tracking**: Shows current tasks, actions, and progress
- **Key Files**: `dashboard_server.py`, CLI integration in `cli.py`

### Azure Reliability Fix (PR #11)
- **Success Rate**: Fixed 0% → 95%+ target achievement
- **VM Configuration**: Upgraded to `Standard_D4s_v5` with nested virtualization support
- **Health Monitoring**: Inline bash health checks in vm-setup command
- **Key Files**: `azure.py`, `cli.py` (vm-setup command)

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

# Setup WAA container on Azure VM (automated, 15-20 min)
uv run python -m openadapt_evals.benchmarks.cli vm-setup --auto-verify

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
| `azure` | Run parallel evaluation on Azure (auto-launches dashboard) |
| `probe` | Check if WAA server is ready |
| `view` | Generate HTML viewer for results |
| `estimate` | Estimate Azure costs |
| `dashboard` | **DEPRECATED**: Use auto-launching dashboard from vm-setup/up/azure instead |
| `monitor-dashboard` | **NEW**: Launch standalone monitoring dashboard for Azure resources |
| `vm-setup` | **Automated WAA deployment**: Setup Docker container with health checks (15-20 min, auto-launches dashboard) |
| `up` | **All-in-one**: Start VM + WAA server + wait until ready (auto-launches dashboard) |
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
│   ├── health_checker.py     # STUB - actual health checks in cli.py vm-setup
│   ├── live_tracker.py       # LiveEvaluationTracker
│   ├── live_api.py           # Flask server for live monitoring
│   ├── auto_screenshot.py    # Playwright screenshot tool with validation
│   ├── vm_utils.py           # ONE helper function: run_on_vm()
│   └── cli.py                # Unified CLI (includes vm-setup bash script)
└── __init__.py
```

## Auto-Launching Azure Dashboard

**CRITICAL USER REQUIREMENT**: "When Azure resources are running I want it to be implemented such that it automatically launches a browser view into the resources currently being used, how much does it cost and for what exactly are we paying."

The dashboard automatically launches when you run:
- `vm-setup` - Sets up WAA container
- `up` - Starts VM and WAA server
- `azure` - Runs parallel evaluation

### Features

**Real-Time Cost Tracking**:
- Cost per hour, day, week, month
- Breakdown by resource type (compute, storage, network)
- Automatic alerts when costs exceed $5/hour
- Historical cost trends

**Active Resources**:
- VMs with status, size, location
- Azure ML compute instances
- Docker containers
- Public/private IPs
- Uptime tracking

**Live Activity**:
- Current task being evaluated
- Task progress (e.g., "5/154 tasks completed")
- Recent actions taken by agent
- Action count
- Real-time logs

**Resource Controls**:
- Stop/Start buttons for each resource
- One-click VM deallocation to save costs
- Quick actions with confirmation

**Auto-Refresh**:
- Dashboard updates every 5 seconds
- No manual refresh needed
- Real-time cost and status updates

### Usage

**Automatic Launch** (Default):
```bash
# Dashboard auto-launches when VM starts
uv run python -m openadapt_evals.benchmarks.cli vm-setup

# Dashboard auto-launches when resources start
uv run python -m openadapt_evals.benchmarks.cli up

# Dashboard auto-launches when evaluation starts
uv run python -m openadapt_evals.benchmarks.cli azure --workers 10 --waa-path /path/to/WAA
```

**Disable Auto-Launch**:
```bash
# Add --no-dashboard to any command
uv run python -m openadapt_evals.benchmarks.cli vm-setup --no-dashboard
uv run python -m openadapt_evals.benchmarks.cli up --no-dashboard
uv run python -m openadapt_evals.benchmarks.cli azure --workers 10 --no-dashboard
```

**Standalone Launch**:
```bash
# Run dashboard server standalone
python -m openadapt_evals.benchmarks.dashboard_server

# Custom port
python -m openadapt_evals.benchmarks.dashboard_server --port 8080

# Don't auto-open browser
python -m openadapt_evals.benchmarks.dashboard_server --no-open
```

**Programmatic Usage**:
```python
from openadapt_evals.benchmarks.dashboard_server import ensure_dashboard_running

# Ensure dashboard is running and open browser
dashboard_url = ensure_dashboard_running(auto_open=True)
print(f"Dashboard: {dashboard_url}")

# Start without opening browser
ensure_dashboard_running(auto_open=False)
```

### Dashboard Components

**Cost Summary Card**:
- Hourly cost (live)
- Daily estimate (24h projection)
- Weekly estimate (7d projection)
- Monthly estimate (30d projection)

**Active Resources Card**:
- Running VMs count
- Compute instances count
- Total resources count

**Current Activity Card**:
- Current task instruction
- Progress percentage
- Actions executed count

**Resources List**:
- Each resource shown with:
  - Name and status (running/stopped)
  - Type (VM/Compute/Container)
  - Size (e.g., Standard_D4_v3)
  - Location (e.g., eastus)
  - Cost per hour
  - Start/Stop button

**Recent Actions Log**:
- Last 5 actions from agent
- Step number and action type
- Timestamp

**Recent Logs**:
- Last 10 log entries
- Auto-scrolling
- Monospace font for readability

### Cost Tracking Details

The dashboard queries Azure for:
1. **VMs**: `az vm list` with instance details
2. **Compute**: `az ml compute list` for Azure ML instances
3. **Cost estimates**: Based on VM size pricing (East US region)

**Cost Calculation**:
- Compute: Actual VM hourly rate from Azure pricing
- Storage: ~$0.01/hour per resource (estimate)
- Network: ~$0.05/hour (estimate)
- Total: Sum of all components

**Pricing Data** (East US, regular instances):
- Standard_D2_v3: $0.096/hour
- Standard_D4_v3: $0.192/hour
- Standard_D8_v3: $0.384/hour
- Standard_D4ds_v5: $0.20/hour

### Activity Tracking Details

The dashboard reads:
1. **Live tracking file**: `benchmark_live.json` (from LiveEvaluationTracker)
2. **Log files**: Recent `.log` files in current directory

**Data displayed**:
- Current task instruction
- Tasks completed / total tasks
- Recent actions (type, step number)
- Action count
- Log tail (last 10 lines)

### Installation

Dashboard requires Flask dependencies:

```bash
# Install dashboard dependencies
uv sync --extra dashboard

# Or install all extras
uv sync --extra all
```

**Dependencies**:
- `flask>=3.0.0`
- `flask-cors>=4.0.0`
- `requests>=2.28.0`

### Implementation Files

- `/openadapt_evals/benchmarks/dashboard_server.py` - Dashboard server
- `/openadapt_evals/benchmarks/cli.py` - CLI integration
- Dashboard auto-launches in `cmd_vm_setup()`, `cmd_up()`, `cmd_azure()`

### Technical Details

**Server Architecture**:
- Flask web server on port 5555 (default)
- Runs in background thread (daemon)
- Persistent across CLI command invocations
- Health check endpoint: `/health`

**Data Collection**:
- Resources: Queries Azure CLI every 5 seconds
- Activity: Reads `benchmark_live.json` file
- Logs: Tails recent `.log` files

**Browser Integration**:
- Auto-opens using Python `webbrowser` module
- Opens on first command that starts resources
- Server persists, browser can reconnect

**Security**:
- Binds to localhost (127.0.0.1) only
- No authentication (local use only)
- No remote access

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
| `benchmarks/azure.py` | AzureWAAOrchestrator, tiered VMs, spot instances |
| `benchmarks/monitoring.py` | CostTracker, cost reporting, real-time cost tracking |
| `benchmarks/health_checker.py` | STUB - actual health checks in cli.py vm-setup bash script |
| `benchmarks/vm_utils.py` | ONE helper function: run_on_vm() for executing scripts via Azure |
| `benchmarks/viewer.py` | generate_benchmark_viewer(), execution logs |
| `benchmarks/auto_screenshot.py` | Playwright screenshot tool with validation |
| `benchmarks/live_api.py` | Flask server for real-time monitoring |
| `benchmarks/live_tracker.py` | LiveEvaluationTracker with cost tracking |
| `benchmarks/dashboard_server.py` | **NEW**: Auto-launching Azure resource monitoring dashboard |
| `benchmarks/cli.py` | CLI entry point with dashboard integration |
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

## Screenshot Quality Requirements

**CRITICAL REQUIREMENT: Real Action Screenshots, Not Idle Desktop**

All screenshots used in benchmarks, demos, documentation, and viewers MUST show real actions being performed. Screenshots showing idle Windows desktop with no visible activity are NOT acceptable.

### What Makes a Good Screenshot

**Good screenshots show:**
- ✅ GUI elements being interacted with (buttons, text fields, menus)
- ✅ Mouse cursor visible near or on interactive elements
- ✅ Text being typed (partially complete text visible)
- ✅ State changes (window opening, dialog appearing, form being filled)
- ✅ Action evidence (cursor at insertion point, menu dropdown open, progress bars)

**Bad screenshots show:**
- ❌ Idle Windows 11 desktop with wallpaper and no windows open
- ❌ Blank/empty application windows with no content
- ❌ Loading screens or splash screens
- ❌ Static desktop background with no interaction

### Required Data Sources

**Option A: Real WAA Evaluation** (PREFERRED)
```bash
# Run actual WAA tasks and capture action screenshots
uv run python -m openadapt_evals.benchmarks.cli live \
    --agent api-claude \
    --server http://vm:5000 \
    --task-ids notepad_1,browser_5 \
    --save-screenshots
```

**Option B: Nightshift OpenAdapt Recording** (Real macOS Data)
Use the nightshift recording which contains real user interactions on macOS.
Location: `/path/to/openadapt/recordings/nightshift_recording.db`

**Option C: Live Recording Session**
Record new session performing actual tasks using OpenAdapt.

### Validation

All screenshots MUST pass validation before use:

```python
from openadapt_evals.benchmarks.validate_screenshots import ScreenshotValidator

validator = ScreenshotValidator()
result = validator.validate_single("screenshot.png")

if not result.is_valid:
    raise ValueError(f"Screenshot shows idle desktop, not real actions: {result.errors}")
```

**Validation checks:**
- File integrity (valid PNG/JPEG, correct size)
- Not blank (not all white/black pixels)
- Content variation (>10 unique colors)
- Sequential change (differs from previous screenshot)
- Optional OCR verification (expected text visible)

### Enforcement

This requirement is encoded in:
1. **`docs/screenshots/SCREENSHOT_REQUIREMENTS.md`** - Comprehensive specification of requirements
2. **`CLAUDE.md`** - This section (you're reading it now)
3. **Code docstrings** - `viewer.py`, `auto_screenshot.py`, `validate_screenshots.py`
4. **Default validation** - `validate_screenshots=True` by default in viewer generation
5. **CLI warnings** - Warns when idle screenshots detected

**See `docs/screenshots/SCREENSHOT_REQUIREMENTS.md` for complete details, examples, and troubleshooting.**

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
- `docs/vm/VM_USAGE_DASHBOARD.md` - Markdown dashboard (generated)
- `VM_USAGE_DASHBOARD.html` - HTML dashboard with auto-refresh (generated if --open flag used)
- `refresh_vm_dashboard.py` - Dashboard generator script
- `vm_dashboard.html` - Static HTML template

## WAA Container Setup (vm-setup)

The `vm-setup` command automates complete WAA container deployment from scratch with 95%+ reliability.

**Implementation**: 305 lines of bash script in `cli.py` (lines 499-664), executed via `az vm run-command invoke`.

**What it does:**
1. Validates nested virtualization support on VM (checks /proc/cpuinfo)
2. Starts Docker daemon with retry logic (3 attempts with 5s delays)
3. Pulls `windowsarena/winarena:latest` image (10-15 min)
4. Creates and starts container with proper settings (--device /dev/kvm, port 5000)
5. Waits for Windows to boot (VNC port check, max 10 minutes)
6. Verifies WAA server is responding (curl localhost:5000/probe)
7. Returns server URL and next steps

**Why it works**: Simple bash script, no abstractions, inline health checks.

**Usage:**
```bash
# Automated setup with verification (recommended)
uv run python -m openadapt_evals.benchmarks.cli vm-setup --auto-verify

# Setup without verification
uv run python -m openadapt_evals.benchmarks.cli vm-setup

# Custom VM
uv run python -m openadapt_evals.benchmarks.cli vm-setup \
  --vm-name my-waa-vm \
  --resource-group MY-RG \
  --auto-verify
```

**Timeline:**
- Fresh VM: 15-20 minutes (includes image pull)
- Existing setup: 2-5 minutes (container already exists)

**Features:**
- Idempotent (safe to re-run)
- Multi-stage health checks
- Clear error messages
- Automatic retry on transient failures
- Progress reporting every 30s

**Requirements:**
- Azure VM with nested virtualization (Standard_D4s_v5 or similar)
- Docker installed on VM
- Azure CLI installed locally (`az login`)

**Troubleshooting:**

If setup fails:
```bash
# Check VM supports nested virtualization
az vm show --name waa-eval-vm --resource-group OPENADAPT-AGENTS --query "hardwareProfile.vmSize" -o tsv

# Check Docker status on VM
az vm run-command invoke \
  --resource-group OPENADAPT-AGENTS \
  --name waa-eval-vm \
  --command-id RunShellScript \
  --scripts "systemctl status docker"

# View container logs
az vm run-command invoke \
  --resource-group OPENADAPT-AGENTS \
  --name waa-eval-vm \
  --command-id RunShellScript \
  --scripts "docker logs winarena"
```

**Test the setup:**
```bash
# Run test script
./test_vm_setup.sh

# Or manually verify
uv run python -m openadapt_evals.benchmarks.cli probe \
  --server http://$(az vm show --name waa-eval-vm --resource-group OPENADAPT-AGENTS --show-details --query publicIps -o tsv):5000 \
  --wait
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

2. **TestPyPI Publishing**: Currently fails due to missing trusted publisher configuration on test.pypi.org. Main PyPI publishing works correctly. See `docs/misc/PYPI_PUBLISHING_PLAN.md` for setup instructions.

### Configuration

- **Workflow**: `.github/workflows/publish.yml`
- **Publishing Method**: Trusted Publishing (OIDC) - no API tokens needed
- **Environments**: `pypi` (working), `testpypi` (needs configuration)

For detailed publishing documentation, troubleshooting, and setup instructions, see `docs/misc/PYPI_PUBLISHING_PLAN.md`.
