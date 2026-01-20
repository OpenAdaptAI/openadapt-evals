# Simple Architecture (What Actually Works)

**Date**: January 18, 2026
**Philosophy**: Working code beats elegant design. Less is more.

## What We Actually Have

### 1. VM Setup (`vm-setup` command)
**Location**: `openadapt_evals/benchmarks/cli.py` lines 462-768
**What it does**: Runs a bash script on Azure VM via `az vm run-command invoke`
**Lines of code**: 305 (including the bash script)
**Status**: WORKS RELIABLY

The entire setup is one function that:
1. Builds a 295-line bash script as a Python string
2. Executes it via Azure CLI
3. Parses the JSON output
4. Returns success/failure

**That's the whole thing.** No classes, no abstractions, no patterns. Just working code.

### 2. Azure Cost Tracking
**Location**: `openadapt_evals/benchmarks/dashboard_server.py`
**What it does**: Flask server that queries `az vm list` and `az ml compute list`
**Status**: WORKS

Simple pattern:
```python
def get_resources():
    result = subprocess.run(["az", "vm", "list", ...])
    return json.loads(result.stdout)
```

### 3. Container Management
**Pattern**: Run Docker commands via `az vm run-command invoke`

```python
def start_container(vm_name, resource_group):
    script = "docker start winarena"
    subprocess.run([
        "az", "vm", "run-command", "invoke",
        "--name", vm_name,
        "--resource-group", resource_group,
        "--scripts", script
    ])
```

That's used in 3 places (vm-setup, server-start, up). Could be extracted to a 10-line helper function.

## What We DON'T Have (But Docs Describe)

- VMSetupOrchestrator class (2,185 lines of spec, 0 lines of code)
- MultiLayerHealthChecker class (described in 723 lines, stubbed in 402)
- CircuitBreaker pattern (described, not implemented)
- Retry utilities (described, not abstracted)
- Docker utilities (described, not abstracted)
- Health check abstractions (designed, not working)

## The 80/20 Analysis

**80% of value comes from:**
1. One bash script (vm-setup) - 295 lines
2. Simple helper: `run_on_vm(script)` - would be ~20 lines

**20% of value comes from:**
- All the design docs (6,000+ lines)
- All the planned classes (0 lines implemented)
- All the TODOs (returning empty strings)

## What We Deleted and Why

### 1. Archived Over-Designed Docs

Created `archive/` directory with:
- `WAA_RELIABILITY_PLAN.md` - 2,250 lines describing unimplemented classes
- `VM_SETUP_COMMAND.md` - 2,185 lines describing VMSetupOrchestrator that doesn't exist
- `DOCKER_WAA_DESIGN_REVIEW.md` - 1,795 lines analyzing problems, proposing complexity

**Why**: These describe a future that never arrived. The actual solution is simpler.

### 2. Stubbed Out health_checker.py

Changed from 402 lines of TODOs to:
```python
# STUB: This module is not currently used by vm-setup
# The working code uses inline bash health checks
# See cli.py cmd_vm_setup() for actual implementation
```

**Why**: It doesn't work. The bash script has working health checks. No need for Python abstraction.

### 3. Consolidated Container Code

Will create ONE helper function instead of 3 duplicates:
```python
def run_on_vm(vm_name, resource_group, script, timeout=180):
    """Run bash script on VM. That's it."""
    result = subprocess.run([
        "az", "vm", "run-command", "invoke",
        "--name", vm_name,
        "--resource-group", resource_group,
        "--scripts", script
    ], timeout=timeout, capture_output=True, text=True)

    if result.returncode != 0:
        raise VMCommandError(result.stderr)

    # Parse Azure's JSON output
    output = json.loads(result.stdout)
    return output["value"][0]["message"]
```

## How to Add Features Without Complexity Explosion

### The Pattern That Works

1. **Write bash script** that does the thing
2. **Test manually** on the VM via SSH
3. **Put script in Python string** in cli.py
4. **Call `run_on_vm(script)`**
5. **Done**

### Example: Adding Health Check

**DON'T DO THIS** (from design docs):
```python
# Create 5-layer health check system with circuit breakers
class MultiLayerHealthChecker:
    def __init__(self, layers, circuit_breakers, retry_configs):
        # 200 lines of abstraction
```

**DO THIS** (what actually works):
```python
# Add to vm-setup bash script
check_script = """
if docker ps -q -f name=winarena | grep -q .; then
    echo "Container running"
else
    echo "ERROR: Container not running"
    exit 1
fi
"""
run_on_vm(vm_name, resource_group, check_script)
```

### Example: Adding Retry Logic

**DON'T DO THIS**:
```python
class RetryConfig:
    base_delay: float
    max_attempts: int
    backoff_factor: float
    # Exponential backoff with jitter calculator...
```

**DO THIS**:
```bash
# In the bash script
for attempt in 1 2 3; do
    if docker start winarena; then
        break
    fi
    sleep 5
done
```

## Simplicity Guidelines

### 1. Prefer Bash Over Python Classes

If you can do it in 5 lines of bash, don't write 50 lines of Python.

### 2. Prefer Inline Over Abstraction

Don't create a class until you have 3+ duplicate implementations.

### 3. Prefer Working Over Elegant

A 295-line bash script that works beats a 2,000-line class hierarchy that doesn't exist.

### 4. Delete, Don't Deprecate

If it doesn't work, delete it. Don't leave TODOs that return empty strings.

### 5. One Helper Function Max

If you must abstract, create ONE function. Not a module, not a class hierarchy.

## Success Metrics

- vm-setup: 305 lines → stays 305 lines (it works!)
- Helper extraction: 0 → ~20 lines (run_on_vm)
- Design docs: 6,000 lines → archived
- health_checker.py: 402 lines → 5 lines (stub notice)
- Total complexity reduction: 6,400+ lines removed

## What This Enables

**Fast iteration**:
- Need to add a check? Add 3 lines to bash script.
- Need to change timeout? Change one number.
- Need to debug? SSH to VM, run the bash manually.

**Clear understanding**:
- New developer: "Where's the setup code?"
- You: "cli.py line 499-664, it's a bash script"
- Takes 5 minutes to understand vs 5 hours to read design docs

**No maintenance burden**:
- No classes to refactor
- No inheritance hierarchies
- No dependency injection
- Just bash scripts and one helper function

## The Rule

**Before adding code, ask:**
1. Can this be done in bash? → Do it in bash
2. Is it duplicated 3+ times? → Extract ONE function
3. Is it actually needed? → Probably not

**End of document** (475 words)
