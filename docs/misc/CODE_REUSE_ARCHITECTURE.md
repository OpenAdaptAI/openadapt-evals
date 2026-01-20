# Code Reuse Architecture: Decision Framework

**Executive Summary**: Adopt a **Hybrid Approach** with clear decision criteria. Maximize code reuse for infrastructure (Azure, Docker, health checks), allow self-contained implementations for adapters and agents. This balances maintainability with flexibility while avoiding both technical debt and coupling hell.

**Last Updated**: 2026-01-18
**Status**: Architectural Decision Record

---

## Table of Contents

1. [Executive Summary & Recommendation](#1-executive-summary--recommendation)
2. [Current State Analysis](#2-current-state-analysis)
3. [Best Practices Research](#3-best-practices-research)
4. [Decision Framework](#4-decision-framework)
5. [Concrete Examples](#5-concrete-examples)
6. [Migration Plan](#6-migration-plan)
7. [Guidelines for Future Agents](#7-guidelines-for-future-agents)

---

## 1. Executive Summary & Recommendation

### The Problem

We've observed Claude Code naturally creating duplicate implementations:
- Multiple retry mechanisms (CLI probing, Azure health checks, container startup)
- Multiple logging configurations (24 files with `logging.getLogger`)
- Multiple Azure CLI subprocess calls (13 files)
- Multiple Docker health checks (CLI setup script, health_checker.py)
- Multiple cost tracking approaches (monitoring.py, live_tracker.py, dashboard_server.py)

### The Question

Should we:
1. **Enforce DRY**: Consolidate everything into shared utilities
2. **Allow duplication**: Keep things self-contained
3. **Hybrid approach**: Strategic reuse with clear boundaries

### The Recommendation: **Hybrid Approach with Clear Boundaries**

**REUSE** these components (infrastructure layer):
- Azure API clients and configuration
- Docker health check logic
- Retry/timeout utilities
- Cost calculation formulas
- Logging configuration

**ALLOW DUPLICATION** for these (application layer):
- Adapter implementations (WAA, OSWorld, future benchmarks)
- Agent implementations (ApiAgent, RetrievalAgent, PolicyAgent)
- CLI command handlers (each command is self-contained)
- Domain-specific evaluators

**Rationale**:
1. **Infrastructure should be shared** - One canonical implementation of "how to check if Docker container is healthy" prevents drift
2. **Adapters should be independent** - Each benchmark may need different approaches; coupling creates fragility
3. **Research code benefits from isolation** - Easy to experiment, compare approaches, publish independently
4. **CLI commands are naturally self-contained** - Each command is an entry point; shared code should be in libraries, not between commands

---

## 2. Current State Analysis

### What Duplication Exists Today

Based on grep analysis of the codebase:

#### 1. **Docker Operations** (9 files)
Files with Docker commands:
- `cli.py` (lines 500-660): vm-setup bash script with Docker pull, run, health checks
- `health_checker.py`: Pattern matching for container startup
- Documentation files: DOCKER_WAA_DESIGN_REVIEW.md, VM_SETUP_COMMAND.md, etc.

**Analysis**:
- **Intentional**: CLI script embeds bash commands for remote execution
- **Accidental**: health_checker.py reimplements log parsing that could be shared
- **Verdict**: Mostly acceptable, but pattern matching logic could be centralized

#### 2. **Azure CLI Calls** (13 files)
Files using `az vm` or `az ml`:
- `cli.py`: VM start/stop/status commands
- `azure.py`: Compute instance creation
- `dashboard_server.py`: Resource querying
- `refresh_vm_dashboard.py`: Standalone dashboard script

**Analysis**:
- **Intentional**: Different use cases (setup vs monitoring vs orchestration)
- **Accidental**: No shared AzureCLI wrapper class
- **Verdict**: Should create shared Azure utilities

#### 3. **Retry Logic** (13 files)
Files with retry patterns:
- `cli.py`: Probe command retry, vm-setup Docker start retry (3 attempts)
- `azure.py`: Uses `tenacity` library for job submission
- `api_agent.py`: API retry with exponential backoff
- `dashboard_server.py`: Resource query retry

**Analysis**:
- **Intentional**: Different retry semantics (immediate vs exponential, different error handling)
- **Accidental**: No shared retry decorator for common case
- **Verdict**: Should provide shared retry utility, allow custom implementations

#### 4. **Logging Setup** (24 files)
Files with `logging.basicConfig` or `logging.getLogger`:
- **basicConfig** (configures root logger): cli.py (line 30), dashboard_server.py
- **getLogger** (creates logger): All 24 files

**Analysis**:
- **Intentional**: Each module should have its own logger (`__name__`)
- **Accidental**: Multiple root logger configurations can conflict
- **Verdict**: ONE shared logging configuration, many module loggers

#### 5. **Cost Tracking** (28 files)
Files with cost estimation/tracking:
- `monitoring.py`: CostTracker class, EvaluationCostReport
- `azure.py`: VM tier costs, task complexity classification
- `dashboard_server.py`: Real-time cost calculation
- `cli.py`: Cost estimation command

**Analysis**:
- **Intentional**: Different use cases (planning vs live tracking vs reporting)
- **Accidental**: Cost data duplicated (VM_TIER_COSTS appears twice)
- **Verdict**: Centralize cost data, allow different tracking approaches

#### 6. **Health Checking** (Multiple implementations)
- `health_checker.py`: ContainerHealthChecker with wait_for_container_start()
- `cli.py` vm-setup: Inline bash health checks (lines 592-660)
- `cli.py` probe command: Server health check with retry (lines 259-299)
- `cli.py` up command: Server probing until ready (lines 1052-1063)

**Analysis**:
- **Health check logic**: Duplicated across Python (health_checker.py) and bash (cli.py)
- **Probe logic**: Duplicated in multiple CLI commands
- **Verdict**: Should consolidate probe logic, keep bash/Python separation for deployment reasons

### Intentional vs Accidental Duplication

| Pattern | Files | Intentional? | Reason |
|---------|-------|--------------|--------|
| Docker commands | 9 | **YES** | Remote execution requires bash scripts |
| Azure CLI calls | 13 | **PARTIAL** | Different use cases, but wrapper would help |
| Retry logic | 13 | **PARTIAL** | Different semantics, but common case could share |
| Logging setup | 24 | **NO** | Root logger config should be once |
| Cost tracking | 28 | **PARTIAL** | Different trackers OK, data should be shared |
| Health checks | 4 | **NO** | Core logic should be shared |

### Current Architecture Strengths

1. **Clean adapter pattern**: WAAMockAdapter, WAALiveAdapter, future OSWorldAdapter are properly isolated
2. **Agent independence**: ApiAgent, RetrievalAgent, PolicyAgent don't depend on each other
3. **CLI command self-containment**: Each command can be understood in isolation
4. **Azure orchestration**: Well-factored into azure.py with monitoring.py, health_checker.py

### Current Architecture Weaknesses

1. **No shared Azure utilities**: Every file reimplements subprocess calls to `az` CLI
2. **No shared retry decorator**: Common patterns (API calls, health checks) reinvent retry logic
3. **Cost data duplication**: VM_TIER_COSTS defined in multiple places
4. **Logging configuration scattered**: Multiple root logger setups can conflict
5. **Health check patterns duplicated**: Container startup, server readiness checks repeated

---

## 3. Best Practices Research

### When Does Code Duplication Make Sense?

Based on industry best practices from successful projects:

#### 1. **The Wrong Abstraction is Worse Than Duplication**
Source: Sandi Metz, "The Wrong Abstraction"

**Key principle**: Prefer duplication over the wrong abstraction. Once you create a shared abstraction, changes cascade and coupling increases.

**Example from our code**:
```python
# GOOD: Each adapter handles errors differently
class WAAMockAdapter:
    def evaluate(self, task_config):
        # Mock always succeeds
        return BenchmarkResult(success=True, ...)

class WAALiveAdapter:
    def evaluate(self, task_config):
        # Live calls WAA server, can fail
        try:
            response = requests.post(...)
        except RequestException:
            return BenchmarkResult(success=False, ...)

# BAD: Shared evaluate() that handles both cases
class SharedAdapter:
    def evaluate(self, task_config, is_mock=False):
        if is_mock:
            return BenchmarkResult(success=True, ...)
        else:
            try:
                response = requests.post(...)
            except RequestException:
                return BenchmarkResult(success=False, ...)
        # Now both adapters are coupled through is_mock flag
```

**When to duplicate**: When components have **similar structure but different behavior**.

#### 2. **Coupling vs Cohesion Trade-off**

**Coupling**: How much one module depends on another
**Cohesion**: How focused a module is on a single responsibility

**Best practice**: Maximize cohesion, minimize coupling.

**Example from our code**:
```python
# HIGH COHESION, LOW COUPLING (GOOD)
class CostTracker:
    """Focused on cost tracking only."""
    def record_worker_cost(self, ...): pass
    def generate_report(self): pass

class LiveEvaluationTracker:
    """Focused on evaluation tracking only."""
    def update_task_progress(self, ...): pass
    def save_screenshot(self, ...): pass

# LOW COHESION, HIGH COUPLING (BAD)
class EvaluationAndCostTracker:
    """Does both tracking and cost calculation."""
    def update_task_progress(self, ...): pass
    def record_cost(self, ...): pass
    def save_screenshot(self, ...): pass
    # Now cost tracking changes affect evaluation tracking
```

**When to share**: When components have **high semantic cohesion** (belong together conceptually).

#### 3. **Successful CLI Tools: kubectl, docker, gh**

Analysis of battle-tested CLI tools:

**kubectl** (Kubernetes):
- **Shared**: API client, authentication, config loading
- **Duplicated**: Each command (get, apply, delete) is self-contained
- **Lesson**: Share the client library, keep command handlers independent

**docker** (Container management):
- **Shared**: Docker daemon client, image handling, container lifecycle
- **Duplicated**: Each subcommand (run, build, push) has custom flags and logic
- **Lesson**: Share low-level APIs, allow high-level commands to diverge

**gh** (GitHub CLI):
- **Shared**: GitHub API client, authentication, HTTP utilities
- **Duplicated**: Each command (pr, issue, repo) has domain-specific logic
- **Lesson**: Share infrastructure, allow domain logic to be independent

**Pattern**: All successful CLI tools follow the same architecture:
```
Shared Infrastructure Layer (DRY)
    ↓
Command Handlers (Allow Duplication)
    ↓
User-Facing CLI
```

#### 4. **Research Codebases: Different Rules**

Research code (like openadapt-evals) has different requirements than production systems:

**Unique needs**:
- **Experimentation**: Need to try different approaches without breaking existing code
- **Publication**: Individual components may be published as separate papers
- **Reproducibility**: Need to lock down exact implementations for benchmark results
- **Comparison**: Need to run multiple implementations side-by-side

**Example**: Our agent implementations
```python
# GOOD for research: Each agent is independent
class ApiAgent:
    """Uses LLM APIs directly."""
    def act(self, observation, task): ...

class RetrievalAgent:
    """Uses retrieval-augmented prompting."""
    def act(self, observation, task): ...

class PolicyAgent:
    """Uses trained RL policy."""
    def act(self, observation, task): ...

# They could share code, but independence allows:
# - Publishing each agent separately
# - Comparing exact implementations
# - Changing one without affecting others
```

**Best practice for research**: Favor independence over code reuse when components might be published/compared separately.

### When Does Shared Code Create Fragility?

#### 1. **Dependency Hell**

**Problem**: When shared code changes, all dependents must update.

**Example from our code**:
```python
# If we created a shared AzureClient class:
class AzureClient:
    def get_vm_status(self, vm_name):
        # v1: Returns string
        return "running"

    # v2: Returns dict (BREAKING CHANGE)
    def get_vm_status(self, vm_name):
        return {"status": "running", "uptime": 3600}

# Now all callers break:
# - cli.py (vm-status command)
# - dashboard_server.py (resource monitoring)
# - azure.py (orchestration)
# - refresh_vm_dashboard.py (standalone script)
```

**Solution**: Use separate implementations when they have different stability requirements.

#### 2. **Versioning Issues**

**Problem**: Shared code needs to maintain backward compatibility.

**Example**:
```python
# Shared retry utility with backward compatibility burden
def retry_with_timeout(func, max_attempts=3, timeout=10):
    # v1: Simple retry

def retry_with_timeout(func, max_attempts=3, timeout=10, exponential_backoff=False):
    # v2: Added exponential backoff (backward compatible but complex)

def retry_with_timeout(func, max_attempts=3, timeout=10, exponential_backoff=False, jitter=False):
    # v3: Added jitter (getting unwieldy)
```

**Alternative**: Let each use case implement exactly what it needs:
```python
# cli.py probe command
for attempt in range(max_attempts):
    try:
        resp = requests.get(url, timeout=5.0)
        if resp.status_code == 200:
            return 0
    except requests.ConnectionError:
        time.sleep(interval)  # Simple retry

# api_agent.py
@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type(RateLimitError)
)
def call_api(self, messages):
    # Complex retry with exponential backoff
```

### Industry Examples

#### Example 1: **Airbnb's Enzyme** (React testing)

**Decision**: Allow different assertion styles rather than forcing one shared approach.

```javascript
// Multiple ways to do the same thing
expect(wrapper.find('.class')).toHaveLength(1);  // Jest
assert(wrapper.find('.class').length === 1);     // Node assert
wrapper.find('.class').should.have.length(1);    // Should.js
```

**Lesson**: Different use cases justify different implementations.

#### Example 2: **Google's Monorepo** (Bazel)

**Decision**: Shared libraries for infrastructure, isolated implementations for products.

**Pattern**:
```
//infrastructure/logging  ← Shared by all
//infrastructure/rpc      ← Shared by all
//products/gmail          ← Independent
//products/drive          ← Independent
```

**Lesson**: Separate infrastructure (reuse) from applications (independence).

---

## 4. Decision Framework

### The Four-Quadrant Model

Classify each component based on two axes:

**Axis 1: Change Frequency**
- High: Changes often (experimental features, new algorithms)
- Low: Changes rarely (stable utilities, proven patterns)

**Axis 2: Coupling Impact**
- High: Changes affect many components
- Low: Changes affect few components

```
                High Coupling Impact
                        │
                        │
           CONSOLIDATE  │  CAREFUL REUSE
       (Shared Library) │  (Abstract Interface)
                        │
─────────────────────────┼─────────────────────────
                        │
        ALLOW DUPLICATE  │  STANDARDIZE
        (Self-Contained) │  (Shared Utility)
                        │
                Low Coupling Impact
```

**Decision rules**:
1. **Consolidate (Low change, High impact)**: Infrastructure that rarely changes but is used everywhere
2. **Careful Reuse (High change, High impact)**: Use interfaces/protocols, not shared code
3. **Allow Duplicate (High change, Low impact)**: Experimental code that affects few components
4. **Standardize (Low change, Low impact)**: Proven patterns used in few places

### Specific Decision Criteria

#### ✅ REUSE if:

1. **Infrastructure**: It's a cross-cutting concern used by multiple components
   - Examples: Azure API client, logging configuration, retry decorators

2. **Data format**: It's a canonical data structure or constant
   - Examples: VM_TIER_COSTS, BenchmarkResult, BenchmarkAction

3. **Algorithm**: It's a proven algorithm with clear semantics
   - Examples: Cost calculation formula, health check state machine

4. **Rarely changes**: The implementation is stable and unlikely to diverge
   - Examples: Docker container name parsing, log pattern matching

5. **Single source of truth**: Bugs fixed in one place should fix all uses
   - Examples: Security vulnerabilities, pricing updates

#### ⚠️ DUPLICATE if:

1. **Different semantics**: Similar structure but different behavior/requirements
   - Examples: Mock adapter vs live adapter, simple retry vs exponential backoff

2. **Experimental**: Code is being actively developed and compared
   - Examples: Different agent implementations, new benchmark adapters

3. **Different stability**: Components have different release/testing requirements
   - Examples: Research code vs production infrastructure

4. **Domain-specific**: Logic is specific to one domain and unlikely to generalize
   - Examples: WAA task evaluation, OSWorld scoring

5. **Publication boundary**: Code might be published/shared independently
   - Examples: Individual agents, benchmark results

#### 🔀 HYBRID APPROACH when:

1. **Share the interface, duplicate the implementation**
   - Example: BenchmarkAdapter ABC, but each adapter implements differently

2. **Share the library, allow custom usage**
   - Example: Provide retry decorator, but allow inline retry loops

3. **Share the data, duplicate the logic**
   - Example: Share VM_TIER_COSTS dict, allow different cost tracking approaches

### Decision Tree

Use this flowchart for new code:

```
Is this code infrastructure (Azure, Docker, logging, retry)?
├─ YES → REUSE (create shared utility)
└─ NO → ↓

Is this code an adapter or agent?
├─ YES → DUPLICATE (keep self-contained)
└─ NO → ↓

Is this code experimental/research?
├─ YES → DUPLICATE (allow experimentation)
└─ NO → ↓

Will changes to this code affect >3 files?
├─ YES → REUSE (reduce coupling)
└─ NO → DUPLICATE (prefer simplicity)
```

---

## 5. Concrete Examples

### Example 1: Docker Health Checks

**Current state**: Three implementations
1. `health_checker.py`: Python-based container health monitoring
2. `cli.py` vm-setup: Bash script with health checks (lines 592-660)
3. `cli.py` probe: Server health probing (lines 259-299)

**Analysis**:
- Health check **logic** (what to check): Should be shared
- Health check **execution** (bash vs Python): Must be duplicated (deployment contexts differ)
- Probe **patterns** (regex for log parsing): Should be shared
- Probe **implementation** (CLI vs library): Can be duplicated

**Recommendation**: **HYBRID**

✅ **Share** (in `openadapt_evals/utils/health_checks.py`):
```python
# Shared pattern definitions
CONTAINER_STARTED_PATTERNS = [
    re.compile(r"Container\s+started", re.IGNORECASE),
    re.compile(r"Executing\s+task", re.IGNORECASE),
    ...
]

CONTAINER_FAILED_PATTERNS = [
    re.compile(r"Container\s+setup\s+failed", re.IGNORECASE),
    ...
]

def check_container_logs(logs: str) -> tuple[bool, str | None]:
    """Check if container has started or failed.

    Returns:
        (started, error_message)
    """
    for pattern in CONTAINER_STARTED_PATTERNS:
        if pattern.search(logs):
            return True, None

    for pattern in CONTAINER_FAILED_PATTERNS:
        if pattern.search(logs):
            error = extract_error_message(logs)
            return False, error

    return False, None  # Still starting
```

⚠️ **Keep duplicated** (bash version for remote execution):
```bash
# cli.py vm-setup (bash script)
# This MUST be bash because it runs remotely on Azure VM
if docker logs winarena | grep -q "Container started"; then
    echo "✓ Container started"
fi
```

⚠️ **Keep duplicated** (CLI probe command):
```python
# cli.py probe command
# This is a user-facing CLI command, should be self-contained
def cmd_probe(args):
    for attempt in range(max_attempts):
        try:
            resp = requests.get(f"{url}/probe", timeout=5.0)
            if resp.status_code == 200:
                print("SUCCESS")
                return 0
        except requests.ConnectionError:
            time.sleep(interval)
```

**Why hybrid?**:
- **Share patterns**: Bug fixes (e.g., adding new log pattern) apply everywhere
- **Duplicate execution**: Bash and Python contexts require different implementations
- **Self-contained CLI**: Command should be understandable without reading utils

### Example 2: Retry Logic

**Current state**: Different retry approaches across files
- `cli.py` probe: Simple loop with sleep
- `azure.py`: tenacity library with exponential backoff
- `api_agent.py`: Custom retry with rate limit handling
- `dashboard_server.py`: While-true retry for resource queries

**Analysis**:
- Simple cases (3 attempts, fixed interval): Common pattern
- Complex cases (exponential backoff, custom predicates): Domain-specific
- API calls: Need rate limit awareness
- Health checks: Need timeout awareness

**Recommendation**: **PROVIDE UTILITY, ALLOW CUSTOM**

✅ **Provide** (in `openadapt_evals/utils/retry.py`):
```python
def simple_retry(
    func: Callable,
    max_attempts: int = 3,
    interval: float = 5.0,
    exceptions: tuple = (Exception,),
) -> Any:
    """Simple retry with fixed interval.

    For complex retry (exponential backoff, jitter, etc.),
    use the tenacity library directly.
    """
    for attempt in range(1, max_attempts + 1):
        try:
            return func()
        except exceptions as e:
            if attempt == max_attempts:
                raise
            logger.warning(f"Attempt {attempt} failed: {e}")
            time.sleep(interval)
```

✅ **Use for simple cases**:
```python
# cli.py probe command
from openadapt_evals.utils.retry import simple_retry

def probe_server(url):
    resp = requests.get(f"{url}/probe", timeout=5.0)
    if resp.status_code != 200:
        raise ValueError(f"Bad status: {resp.status_code}")
    return resp

try:
    simple_retry(
        lambda: probe_server(args.server),
        max_attempts=60,
        interval=5.0,
        exceptions=(requests.ConnectionError, ValueError),
    )
    print("SUCCESS")
except Exception as e:
    print(f"ERROR: {e}")
```

⚠️ **Keep custom for complex cases**:
```python
# api_agent.py - complex retry with rate limit handling
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

@retry(
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type(RateLimitError),
    before_sleep=lambda retry_state: logger.warning(
        f"Rate limited, retrying in {retry_state.next_action.sleep}s"
    ),
)
def call_api(self, messages):
    # Complex retry needs custom configuration
    ...
```

**Why this approach?**:
- **Utility covers 80% case**: Simple retry with fixed interval
- **Library for complex cases**: tenacity provides everything we need
- **No feature creep**: Don't try to build one retry-for-all

### Example 3: Azure API Calls

**Current state**: Direct subprocess calls to `az` CLI in 13 files
- `cli.py`: VM start/stop/status
- `azure.py`: Compute instance creation
- `dashboard_server.py`: Resource listing
- `refresh_vm_dashboard.py`: Standalone dashboard

**Analysis**:
- All use same pattern: `subprocess.run(["az", "vm", ...])`
- Error handling varies (some check returncode, some don't)
- JSON parsing duplicated
- No retry on transient errors

**Recommendation**: **CONSOLIDATE**

✅ **Create shared client** (in `openadapt_evals/utils/azure_client.py`):
```python
from dataclasses import dataclass
import json
import subprocess
from typing import Any

@dataclass
class VMInfo:
    """VM information from Azure."""
    name: str
    status: str
    public_ip: str | None
    size: str
    location: str

class AzureCLI:
    """Wrapper for Azure CLI commands.

    This is a thin wrapper that handles common patterns:
    - JSON parsing
    - Error handling
    - Return code checking

    For complex operations, use Azure SDK directly.
    """

    def __init__(self, subscription_id: str | None = None):
        self.subscription_id = subscription_id

    def run(self, args: list[str], parse_json: bool = True) -> Any:
        """Run az command and return output.

        Args:
            args: Command arguments (e.g., ["vm", "list"])
            parse_json: Whether to parse output as JSON

        Returns:
            Parsed JSON or raw string output

        Raises:
            RuntimeError: If command fails
        """
        cmd = ["az"] + args
        if self.subscription_id:
            cmd.extend(["--subscription", self.subscription_id])

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            raise RuntimeError(
                f"Azure CLI failed: {result.stderr}"
            )

        if parse_json:
            return json.loads(result.stdout)
        return result.stdout.strip()

    def get_vm_status(
        self,
        vm_name: str,
        resource_group: str,
    ) -> VMInfo:
        """Get VM status and details."""
        data = self.run([
            "vm", "show",
            "--name", vm_name,
            "--resource-group", resource_group,
            "--show-details",
            "--query", "{name:name, status:powerState, publicIp:publicIps, "
                       "size:hardwareProfile.vmSize, location:location}",
        ])

        return VMInfo(
            name=data["name"],
            status=data["status"],
            public_ip=data.get("publicIp"),
            size=data["size"],
            location=data["location"],
        )

    def start_vm(self, vm_name: str, resource_group: str) -> None:
        """Start a VM."""
        self.run([
            "vm", "start",
            "--name", vm_name,
            "--resource-group", resource_group,
        ], parse_json=False)

    def stop_vm(self, vm_name: str, resource_group: str, no_wait: bool = False) -> None:
        """Stop (deallocate) a VM."""
        cmd = [
            "vm", "deallocate",
            "--name", vm_name,
            "--resource-group", resource_group,
        ]
        if no_wait:
            cmd.append("--no-wait")

        self.run(cmd, parse_json=False)

    def list_vms(self, resource_group: str | None = None) -> list[VMInfo]:
        """List all VMs."""
        cmd = ["vm", "list", "--show-details"]
        if resource_group:
            cmd.extend(["--resource-group", resource_group])

        data = self.run(cmd)

        return [
            VMInfo(
                name=vm["name"],
                status=vm.get("powerState", "unknown"),
                public_ip=vm.get("publicIps"),
                size=vm.get("hardwareProfile", {}).get("vmSize", "unknown"),
                location=vm.get("location", "unknown"),
            )
            for vm in data
        ]
```

✅ **Use in CLI commands**:
```python
# cli.py
from openadapt_evals.utils.azure_client import AzureCLI

def cmd_vm_status(args):
    azure = AzureCLI()
    vm = azure.get_vm_status(args.vm_name, args.resource_group)

    print(f"VM Name:    {vm.name}")
    print(f"Status:     {vm.status}")
    print(f"Public IP:  {vm.public_ip or 'N/A'}")
    print(f"Size:       {vm.size}")
    print(f"Location:   {vm.location}")

    return 0

def cmd_vm_start(args):
    azure = AzureCLI()
    azure.start_vm(args.vm_name, args.resource_group)

    vm = azure.get_vm_status(args.vm_name, args.resource_group)
    print(f"VM '{vm.name}' started successfully.")
    print(f"Public IP: {vm.public_ip}")

    return 0
```

✅ **Use in dashboard**:
```python
# dashboard_server.py
from openadapt_evals.utils.azure_client import AzureCLI

def get_azure_resources() -> list[ResourceInfo]:
    azure = AzureCLI()

    try:
        vms = azure.list_vms()
        return [
            ResourceInfo(
                resource_type="vm",
                name=vm.name,
                status=vm.status,
                cost_per_hour=estimate_vm_cost(vm.size),
                location=vm.location,
                size=vm.size,
                public_ip=vm.public_ip,
            )
            for vm in vms
        ]
    except Exception as e:
        logger.error(f"Failed to query Azure resources: {e}")
        return []
```

**Why consolidate?**:
- **Single source of truth**: Bug fixes apply everywhere
- **Consistent error handling**: All Azure calls behave the same
- **Easy to test**: Mock AzureCLI instead of subprocess
- **Type safety**: VMInfo dataclass vs raw dicts
- **DRY**: No more duplicated JSON parsing

### Example 4: Cost Tracking

**Current state**: Multiple cost tracking approaches
- `monitoring.py`: CostTracker class for evaluation runs
- `live_tracker.py`: Real-time cost tracking with file output
- `dashboard_server.py`: Live cost calculation for dashboard
- `azure.py`: VM_TIER_COSTS, classify_task_complexity

**Analysis**:
- **Cost data** (VM_TIER_COSTS): Should be centralized
- **Cost calculation** (formula): Should be shared
- **Cost tracking** (different use cases): Can be duplicated

**Recommendation**: **SHARE DATA, DUPLICATE TRACKERS**

✅ **Share cost data** (in `openadapt_evals/utils/azure_costs.py`):
```python
"""Azure VM cost data and utilities.

Pricing data from Azure East US region (regular instances).
Last updated: 2026-01-18
"""

# VM Tiers and their corresponding Azure VM sizes
VM_TIERS = {
    "simple": "Standard_D2_v3",   # 2 vCPUs, 8 GB RAM
    "medium": "Standard_D4_v3",   # 4 vCPUs, 16 GB RAM
    "complex": "Standard_D8_v3",  # 8 vCPUs, 32 GB RAM
}

# Hourly costs for regular (pay-as-you-go) instances
VM_TIER_COSTS = {
    "simple": 0.096,   # $0.096/hour
    "medium": 0.192,   # $0.192/hour
    "complex": 0.384,  # $0.384/hour
}

# Hourly costs for spot instances (70-80% discount)
VM_TIER_SPOT_COSTS = {
    "simple": 0.024,   # ~75% discount
    "medium": 0.048,   # ~75% discount
    "complex": 0.096,  # ~75% discount
}

def get_vm_hourly_cost(vm_size: str, is_spot: bool = False) -> float:
    """Get hourly cost for a VM size.

    Args:
        vm_size: Azure VM size (e.g., "Standard_D4_v3")
        is_spot: Whether this is a spot instance

    Returns:
        Hourly cost in USD

    Raises:
        ValueError: If VM size is unknown
    """
    # Map VM size to tier
    tier = None
    for t, size in VM_TIERS.items():
        if size == vm_size:
            tier = t
            break

    if tier is None:
        raise ValueError(f"Unknown VM size: {vm_size}")

    costs = VM_TIER_SPOT_COSTS if is_spot else VM_TIER_COSTS
    return costs[tier]

def estimate_evaluation_cost(
    num_tasks: int,
    num_workers: int,
    avg_task_duration_minutes: float,
    vm_tier: str = "medium",
    is_spot: bool = False,
) -> dict:
    """Estimate total cost for an evaluation run.

    Args:
        num_tasks: Number of tasks to evaluate
        num_workers: Number of parallel workers
        avg_task_duration_minutes: Average time per task
        vm_tier: VM tier to use (simple/medium/complex)
        is_spot: Whether to use spot instances

    Returns:
        Dict with cost breakdown
    """
    tasks_per_worker = num_tasks / num_workers
    duration_hours = (tasks_per_worker * avg_task_duration_minutes) / 60

    costs = VM_TIER_SPOT_COSTS if is_spot else VM_TIER_COSTS
    hourly_cost = costs[vm_tier]

    total_vm_hours = duration_hours * num_workers
    total_cost = total_vm_hours * hourly_cost

    return {
        "num_tasks": num_tasks,
        "num_workers": num_workers,
        "tasks_per_worker": tasks_per_worker,
        "estimated_duration_hours": duration_hours,
        "total_vm_hours": total_vm_hours,
        "vm_tier": vm_tier,
        "hourly_cost": hourly_cost,
        "is_spot": is_spot,
        "estimated_cost_usd": total_cost,
        "cost_per_task_usd": total_cost / num_tasks,
    }
```

✅ **Import in all cost-related files**:
```python
# azure.py
from openadapt_evals.utils.azure_costs import (
    VM_TIERS,
    VM_TIER_COSTS,
    VM_TIER_SPOT_COSTS,
)

# monitoring.py
from openadapt_evals.utils.azure_costs import (
    VM_TIER_COSTS,
    get_vm_hourly_cost,
)

# dashboard_server.py
from openadapt_evals.utils.azure_costs import get_vm_hourly_cost

# cli.py estimate command
from openadapt_evals.utils.azure_costs import estimate_evaluation_cost
```

⚠️ **Keep separate trackers** (different use cases):
```python
# monitoring.py - Evaluation run cost tracking
class CostTracker:
    """Track costs for a complete evaluation run."""
    def record_worker_cost(self, ...): ...
    def generate_report(self): ...

# live_tracker.py - Real-time tracking with file output
class LiveEvaluationTracker:
    """Track evaluation progress with live updates."""
    def update_task_progress(self, ...): ...
    def get_current_cost(self): ...

# dashboard_server.py - Dashboard display
def get_azure_resources() -> list[ResourceInfo]:
    """Get resources with cost calculation."""
    ...
```

**Why this approach?**:
- **Shared data prevents drift**: When AWS prices change, update once
- **Separate trackers allow flexibility**: Each use case has different needs
- **Clear separation of concerns**: Data layer vs application layer

### Example 5: Logging Configuration

**Current state**: 24 files use `logging.getLogger(__name__)`
- `cli.py` uses `logging.basicConfig()` (line 30)
- `dashboard_server.py` uses `logging.getLogger()` without config
- Other files use `logging.getLogger()` without config

**Analysis**:
- **Root logger config**: Should happen ONCE at application entry point
- **Module loggers**: Should be in every file

**Recommendation**: **CONSOLIDATE ROOT CONFIG, KEEP MODULE LOGGERS**

✅ **Create shared logging setup** (in `openadapt_evals/utils/logging_config.py`):
```python
"""Centralized logging configuration for openadapt-evals.

Call setup_logging() once at application entry point.
"""

import logging
import sys
from pathlib import Path

def setup_logging(
    level: int = logging.INFO,
    log_file: Path | None = None,
    format: str = "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt: str = "%Y-%m-%d %H:%M:%S",
) -> None:
    """Setup logging for the application.

    This should be called ONCE at the application entry point.
    Individual modules should use logging.getLogger(__name__).

    Args:
        level: Logging level (logging.INFO, logging.DEBUG, etc.)
        log_file: Optional file to write logs to
        format: Log message format
        datefmt: Date format for timestamps
    """
    handlers = [logging.StreamHandler(sys.stdout)]

    if log_file:
        handlers.append(logging.FileHandler(log_file))

    logging.basicConfig(
        level=level,
        format=format,
        datefmt=datefmt,
        handlers=handlers,
    )

    # Suppress noisy third-party loggers
    logging.getLogger("azure").setLevel(logging.WARNING)
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("requests").setLevel(logging.WARNING)
```

✅ **Use in CLI entry point**:
```python
# cli.py
from openadapt_evals.utils.logging_config import setup_logging

def main() -> int:
    # Setup logging ONCE at entry point
    setup_logging(level=logging.INFO)

    logger = logging.getLogger(__name__)
    logger.info("Starting openadapt-evals CLI")

    # ... rest of CLI logic
```

✅ **Use in all modules**:
```python
# Every module
import logging

logger = logging.getLogger(__name__)

# Now just use logger
logger.info("Starting evaluation")
logger.warning("Task failed")
logger.error("Connection error", exc_info=True)
```

**Why consolidate?**:
- **One config**: No conflicts from multiple basicConfig() calls
- **Consistent format**: All logs look the same
- **Easy to change**: Update one place to add file logging, change format, etc.
- **Module loggers still independent**: Each module has its own logger name

### Example 6: Adapters (Allow Duplication)

**Current state**: Independent adapter implementations
- `WAAMockAdapter`: In-memory mock for testing
- `WAALiveAdapter`: HTTP client for live WAA server
- Future: `OSWorldAdapter`, `WebArenaAdapter`

**Analysis**:
- Each adapter talks to different backend
- Each has different error modes
- Each might be published/benchmarked independently

**Recommendation**: **ALLOW DUPLICATION** (via shared interface)

✅ **Shared interface only**:
```python
# adapters/base.py
from abc import ABC, abstractmethod

class BenchmarkAdapter(ABC):
    """Abstract base class for benchmark adapters."""

    @abstractmethod
    def load_task(self, task_id: str) -> BenchmarkTask:
        """Load a task by ID."""
        pass

    @abstractmethod
    def reset(self, task: BenchmarkTask) -> Observation:
        """Reset environment for a task."""
        pass

    @abstractmethod
    def step(self, action: BenchmarkAction) -> Observation:
        """Execute an action."""
        pass

    @abstractmethod
    def evaluate(self, task: BenchmarkTask) -> BenchmarkResult:
        """Evaluate current state."""
        pass
```

⚠️ **Independent implementations**:
```python
# adapters/waa.py
class WAAMockAdapter(BenchmarkAdapter):
    """Mock adapter for WAA (no server required)."""

    def load_task(self, task_id: str) -> BenchmarkTask:
        # Mock implementation
        return BenchmarkTask(...)

    def step(self, action: BenchmarkAction) -> Observation:
        # Mock step (always succeeds)
        return Observation(...)

# adapters/waa_live.py
class WAALiveAdapter(BenchmarkAdapter):
    """Live adapter for WAA (requires server)."""

    def __init__(self, config: WAALiveConfig):
        self.server_url = config.server_url
        self.session = requests.Session()

    def load_task(self, task_id: str) -> BenchmarkTask:
        # Load from server
        response = self.session.get(f"{self.server_url}/tasks/{task_id}")
        response.raise_for_status()
        return BenchmarkTask.from_json(response.json())

    def step(self, action: BenchmarkAction) -> Observation:
        # Send action to server
        response = self.session.post(
            f"{self.server_url}/step",
            json=action.to_dict(),
        )
        response.raise_for_status()
        return Observation.from_json(response.json())

# Future: adapters/osworld.py
class OSWorldAdapter(BenchmarkAdapter):
    """Adapter for OSWorld benchmark."""

    def __init__(self, config: OSWorldConfig):
        # Different config, different implementation
        ...
```

**Why allow duplication?**:
- **Different backends**: Mock vs HTTP vs future environments
- **Independent evolution**: Can change mock without affecting live
- **Publication boundary**: Each adapter might be published separately
- **No forced abstraction**: Shared interface, but implementations diverge

---

## 6. Migration Plan

### Phase 1: Create Shared Utilities (Week 1)

**Goal**: Establish infrastructure layer without breaking existing code.

**Tasks**:
1. Create `openadapt_evals/utils/` directory
2. Add `azure_client.py` with AzureCLI wrapper
3. Add `azure_costs.py` with cost data and calculations
4. Add `logging_config.py` with shared logging setup
5. Add `retry.py` with simple_retry utility
6. Add `health_checks.py` with shared patterns

**Deliverables**:
```
openadapt_evals/utils/
├── __init__.py
├── azure_client.py      # AzureCLI wrapper
├── azure_costs.py       # Cost data and calculations
├── logging_config.py    # Shared logging setup
├── retry.py             # Simple retry utility
└── health_checks.py     # Health check patterns
```

**Acceptance criteria**:
- All utilities have tests
- All utilities have docstrings
- No existing code is changed yet (backward compatible)

### Phase 2: Migrate CLI Commands (Week 2)

**Goal**: Update CLI to use shared utilities.

**Tasks**:
1. Update `cmd_vm_status()` to use `AzureCLI.get_vm_status()`
2. Update `cmd_vm_start()` to use `AzureCLI.start_vm()`
3. Update `cmd_vm_stop()` to use `AzureCLI.stop_vm()`
4. Update `cmd_probe()` to use `simple_retry()`
5. Update `main()` to use `setup_logging()`
6. Update `cmd_estimate()` to use `estimate_evaluation_cost()`

**Deliverables**:
- `cli.py` imports from `openadapt_evals.utils.*`
- CLI commands are shorter and more readable
- Tests verify same behavior

**Acceptance criteria**:
- All CLI commands still work
- Tests pass
- Code is shorter (remove ~100 lines of duplicated subprocess calls)

### Phase 3: Migrate Azure Orchestration (Week 3)

**Goal**: Update azure.py and monitoring.py to use shared utilities.

**Tasks**:
1. Update `azure.py` to import from `azure_costs.py`
2. Update `monitoring.py` to import from `azure_costs.py`
3. Update `dashboard_server.py` to use `AzureCLI`
4. Remove duplicated cost data definitions

**Deliverables**:
- Single source of truth for VM costs
- Consistent cost calculations
- Dashboard uses same Azure client as CLI

**Acceptance criteria**:
- Cost calculations are identical to before (no regression)
- Tests pass
- No duplicated cost data

### Phase 4: Migrate Health Checks (Week 4)

**Goal**: Consolidate health check logic.

**Tasks**:
1. Update `health_checker.py` to use `health_checks.py` patterns
2. Keep bash scripts as-is (remote execution requirement)
3. Document separation: shared patterns vs execution context

**Deliverables**:
- Shared health check patterns
- Bash and Python both use same patterns (where possible)
- Clear comments explaining why bash is separate

**Acceptance criteria**:
- Health checks work the same
- Adding new pattern only requires updating one file
- Tests verify pattern matching

### Phase 5: Documentation and Cleanup (Week 5)

**Goal**: Document new architecture and clean up old code.

**Tasks**:
1. Update CLAUDE.md with new architecture section
2. Update README.md with shared utilities
3. Add architecture diagram
4. Remove TODOs and deprecated code
5. Add migration guide for contributors

**Deliverables**:
- Updated documentation
- Architecture decision record (this document)
- Contributor guidelines

**Acceptance criteria**:
- New contributors know when to reuse vs duplicate
- All shared utilities are documented
- Examples show how to use utilities

### Phase 6: Monitoring and Iteration (Ongoing)

**Goal**: Monitor for accidental duplication and improve utilities.

**Tasks**:
1. Add pre-commit hook to detect new Azure subprocess calls
2. Add linter rule to detect new cost data definitions
3. Add note to PR template about code reuse
4. Review quarterly for new duplication patterns

**Deliverables**:
- Pre-commit hooks
- Linter config
- PR template update

**Acceptance criteria**:
- PRs are checked for accidental duplication
- New utilities are added when patterns emerge
- Architecture document is kept up-to-date

### Migration Checklist

Before migrating code, check:

- [ ] Does shared utility exist? (If not, create it first)
- [ ] Are there tests for the shared utility?
- [ ] Will migration break existing code? (If yes, add backward compat)
- [ ] Are all call sites updated? (grep to find all uses)
- [ ] Do tests still pass?
- [ ] Is documentation updated?

### Rollback Plan

If migration causes issues:

1. **Git revert**: Each phase is a separate PR, easy to revert
2. **Feature flag**: Add flag to use old code path temporarily
3. **Gradual migration**: Migrate one file at a time, not all at once

Example feature flag:
```python
# cli.py
USE_NEW_AZURE_CLIENT = os.getenv("USE_NEW_AZURE_CLIENT", "true") == "true"

if USE_NEW_AZURE_CLIENT:
    from openadapt_evals.utils.azure_client import AzureCLI
    azure = AzureCLI()
    vm = azure.get_vm_status(...)
else:
    # Old code path
    result = subprocess.run(["az", "vm", "show", ...])
    ...
```

---

## 7. Guidelines for Future Agents

### For Claude Code Agents

When adding new code, ask these questions:

#### Question 1: Is this infrastructure or application code?

**Infrastructure** (shared): Azure API, Docker, logging, retry, cost data
**Application** (isolated): Adapters, agents, CLI commands, evaluators

👉 **If infrastructure**: Use or create shared utility in `openadapt_evals/utils/`
👉 **If application**: Keep self-contained in appropriate module

#### Question 2: How many files would use this code?

**1-2 files**: Duplicate (not worth abstracting)
**3-5 files**: Consider shared utility (check if already exists)
**6+ files**: Definitely create shared utility

👉 **If 1-2**: Keep code inline, add TODO if pattern might grow
👉 **If 3+**: Check `openadapt_evals/utils/` first, create if needed

#### Question 3: Is this code experimental or stable?

**Experimental**: Being actively changed, compared, researched
**Stable**: Proven pattern, unlikely to change

👉 **If experimental**: Allow duplication for now, consolidate later
👉 **If stable**: Use or create shared utility

#### Question 4: Will different use cases need different implementations?

**Same semantics**: All uses need same behavior
**Different semantics**: Uses need different behavior

👉 **If same**: Shared utility
👉 **If different**: Duplicate with shared interface

### Quick Reference

```
┌─────────────────────────────────────────────────┐
│  ALWAYS USE SHARED UTILITIES FOR:               │
│  - Azure CLI calls                              │
│  - Cost calculations                            │
│  - Logging setup                                │
│  - Health check patterns                        │
│  - Simple retry                                 │
└─────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────┐
│  ALLOW DUPLICATION FOR:                         │
│  - Adapters (different backends)                │
│  - Agents (different algorithms)                │
│  - CLI commands (self-contained entry points)   │
│  - Experimental code (actively changing)        │
└─────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────┐
│  BEFORE CREATING NEW SHARED CODE:               │
│  1. Check if it already exists in utils/        │
│  2. Ensure 3+ files would use it                │
│  3. Write tests                                 │
│  4. Document in docstring                       │
│  5. Update this architecture doc                │
└─────────────────────────────────────────────────┘
```

### Code Review Checklist

When reviewing PRs, check:

**Shared utilities**:
- [ ] Is this infrastructure code that should be in `utils/`?
- [ ] Is there already a utility for this? (check before duplicating)
- [ ] Are there tests for the new utility?
- [ ] Is the utility documented?

**New duplication**:
- [ ] Is this duplication intentional? (add comment if yes)
- [ ] Is there a shared utility we should use instead?
- [ ] Will this pattern be used in 3+ files? (if yes, create utility)

**Breaking changes**:
- [ ] Does this change affect shared utilities?
- [ ] Are all call sites updated?
- [ ] Is there a migration path for old code?

### Examples for Common Scenarios

#### Scenario 1: Adding a new benchmark adapter

```python
# ✅ CORRECT: Independent implementation
# adapters/osworld.py

from openadapt_evals.adapters.base import BenchmarkAdapter

class OSWorldAdapter(BenchmarkAdapter):
    """Adapter for OSWorld benchmark."""

    def __init__(self, config: OSWorldConfig):
        # OSWorld-specific implementation
        self.env = OSWorldEnvironment(config)

    def load_task(self, task_id: str) -> BenchmarkTask:
        # OSWorld has different task format than WAA
        task_data = self.env.get_task(task_id)
        return BenchmarkTask.from_osworld(task_data)

# Rationale:
# - Different backend (OSWorld vs WAA)
# - Different task format
# - Will be published separately
# - Should NOT share code with WAAAdapter
```

#### Scenario 2: Adding Azure VM cost for new region

```python
# ✅ CORRECT: Update shared cost data
# openadapt_evals/utils/azure_costs.py

VM_TIER_COSTS_BY_REGION = {
    "eastus": {
        "simple": 0.096,
        "medium": 0.192,
        "complex": 0.384,
    },
    "westus": {  # NEW
        "simple": 0.104,
        "medium": 0.208,
        "complex": 0.416,
    },
}

def get_vm_hourly_cost(
    vm_size: str,
    is_spot: bool = False,
    region: str = "eastus",
) -> float:
    """Get hourly cost for a VM size in a region."""
    ...

# Rationale:
# - Cost data is infrastructure
# - Used by multiple components
# - Single source of truth prevents drift
```

#### Scenario 3: Adding a new CLI command

```python
# ✅ CORRECT: Self-contained command using shared utilities
# cli.py

from openadapt_evals.utils.azure_client import AzureCLI
from openadapt_evals.utils.retry import simple_retry

def cmd_vm_restart(args: argparse.Namespace) -> int:
    """Restart an Azure VM."""
    azure = AzureCLI()  # Use shared client

    print(f"Restarting VM '{args.vm_name}'...")

    # Use shared retry for robustness
    try:
        simple_retry(
            lambda: azure.restart_vm(args.vm_name, args.resource_group),
            max_attempts=3,
            interval=5.0,
        )
    except Exception as e:
        print(f"ERROR: Failed to restart VM: {e}")
        return 1

    print("VM restarted successfully.")
    return 0

# Rationale:
# - Command logic is self-contained
# - Uses shared Azure client (infrastructure)
# - Uses shared retry utility (infrastructure)
# - Easy to understand without reading other files
```

#### Scenario 4: Adding a new agent

```python
# ✅ CORRECT: Independent implementation
# agents/mcts_agent.py

from openadapt_evals.agents.base import BenchmarkAgent

class MCTSAgent(BenchmarkAgent):
    """Agent using Monte Carlo Tree Search."""

    def __init__(self, simulations: int = 1000):
        self.simulations = simulations
        self.tree = MCTSTree()

    def act(
        self,
        observation: Observation,
        task: BenchmarkTask,
    ) -> BenchmarkAction:
        # MCTS-specific implementation
        # Completely different from ApiAgent or PolicyAgent
        best_action = self.tree.search(observation, self.simulations)
        return best_action

# Rationale:
# - Different algorithm (MCTS vs API vs Policy)
# - Will be compared against other agents
# - Might be published separately
# - Should NOT share code with other agents
```

### When to Ask for Architecture Review

Request review from a human if:

1. **Creating new shared utility**: Affects multiple components
2. **Large refactoring**: Moving code between modules
3. **Breaking changes**: Changing shared interfaces
4. **Uncertain about duplication**: Not sure if code should be shared
5. **Performance-critical code**: Retry logic, API calls, etc.

### Red Flags (Ask Before Proceeding)

🚩 **Copy-pasting code between files**: Consider if this should be a shared utility
🚩 **Changing shared utility signature**: This affects all callers, needs migration plan
🚩 **Adding third shared implementation**: Two is comparison, three suggests pattern needs consolidation
🚩 **Circular imports**: Sign of wrong module boundaries
🚩 **"Just for now" duplication**: Always becomes permanent

---

## Appendix A: Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                    openadapt-evals                          │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│  INFRASTRUCTURE LAYER (Shared, DRY)                         │
├─────────────────────────────────────────────────────────────┤
│  utils/                                                     │
│  ├── azure_client.py       ← AzureCLI wrapper               │
│  ├── azure_costs.py        ← Cost data & calculations       │
│  ├── logging_config.py     ← Logging setup                  │
│  ├── retry.py              ← Simple retry utility           │
│  └── health_checks.py      ← Health check patterns          │
└─────────────────────────────────────────────────────────────┘
                             ▲
                             │ import
                             │
┌─────────────────────────────────────────────────────────────┐
│  APPLICATION LAYER (Allow Duplication)                      │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  adapters/                  agents/                         │
│  ├── base.py (ABC)         ├── base.py (ABC)               │
│  ├── waa.py                ├── api_agent.py                 │
│  ├── waa_live.py           ├── retrieval_agent.py           │
│  └── osworld.py            ├── policy_agent.py              │
│     (future)               └── mcts_agent.py (future)       │
│                                                             │
│  benchmarks/                                                │
│  ├── cli.py                 ← CLI entry point               │
│  ├── azure.py               ← Azure orchestration           │
│  ├── monitoring.py          ← Cost tracking                 │
│  ├── health_checker.py      ← Health monitoring             │
│  └── dashboard_server.py    ← Dashboard                     │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

**Key principles**:
1. **Infrastructure layer is shared** (DRY): One implementation of Azure API, costs, retry, logging
2. **Application layer allows duplication**: Adapters, agents, orchestration can diverge
3. **Clear boundaries**: Infrastructure is in `utils/`, application is in domain modules
4. **One-way dependency**: Application imports infrastructure, never the reverse

---

## Appendix B: Migration Examples

### Example: Migrating Azure CLI Calls

**Before** (duplicated code):
```python
# cli.py (3 places)
result = subprocess.run(
    ["az", "vm", "show", "--name", vm_name, "--resource-group", rg],
    capture_output=True,
    text=True,
)
if result.returncode != 0:
    print(f"ERROR: {result.stderr}")
    return 1
data = json.loads(result.stdout)

# dashboard_server.py (1 place)
result = subprocess.run(
    ["az", "vm", "list"],
    capture_output=True,
    text=True,
)
vms = json.loads(result.stdout)

# azure.py (2 places)
subprocess.run(["az", "ml", "compute", "create", ...])
```

**After** (shared utility):
```python
# utils/azure_client.py
class AzureCLI:
    def get_vm_status(self, vm_name, rg) -> VMInfo: ...
    def list_vms(self) -> list[VMInfo]: ...
    def create_compute(self, name, size) -> None: ...

# cli.py
azure = AzureCLI()
vm = azure.get_vm_status(args.vm_name, args.resource_group)

# dashboard_server.py
azure = AzureCLI()
vms = azure.list_vms()

# azure.py
azure = AzureCLI()
azure.create_compute(name, size)
```

**Benefits**:
- 6 subprocess calls → 1 shared implementation
- Consistent error handling
- Type safety (VMInfo dataclass)
- Easy to mock for tests

### Example: Migrating Cost Data

**Before** (duplicated data):
```python
# azure.py
VM_TIER_COSTS = {
    "simple": 0.096,
    "medium": 0.192,
    "complex": 0.384,
}

# monitoring.py (copy-pasted)
VM_TIER_COSTS = {
    "simple": 0.096,
    "medium": 0.192,
    "complex": 0.384,
}

# dashboard_server.py (hardcoded)
def estimate_cost(vm_size):
    if vm_size == "Standard_D2_v3":
        return 0.096
    elif vm_size == "Standard_D4_v3":
        return 0.192
    ...
```

**After** (shared data):
```python
# utils/azure_costs.py
VM_TIER_COSTS = {
    "simple": 0.096,
    "medium": 0.192,
    "complex": 0.384,
}

def get_vm_hourly_cost(vm_size: str) -> float:
    # Implementation with mapping

# All files import from here
from openadapt_evals.utils.azure_costs import VM_TIER_COSTS
```

**Benefits**:
- One source of truth
- Price updates happen once
- No drift between files

---

## Appendix C: Related Reading

### Academic Papers

1. **"The Wrong Abstraction"** by Sandi Metz (2014)
   - Link: https://sandimetz.com/blog/2016/1/20/the-wrong-abstraction
   - Summary: Prefer duplication over the wrong abstraction

2. **"On the Criteria To Be Used in Decomposing Systems into Modules"** by D.L. Parnas (1972)
   - Classic paper on information hiding and module boundaries

3. **"Out of the Tar Pit"** by Ben Moseley and Peter Marks (2006)
   - On complexity and state management

### Industry Examples

1. **Google's Monorepo**: Shared infrastructure, isolated products
2. **Kubernetes**: Shared client library, independent controllers
3. **Django**: Reusable apps with clear boundaries

### Tools

1. **PMD Copy/Paste Detector**: Find duplicated code
2. **SonarQube**: Code quality metrics including duplication
3. **jscpd**: Copy-paste detector for multiple languages

---

## Appendix D: Decision Log

Track architectural decisions here:

| Date | Decision | Rationale | Status |
|------|----------|-----------|--------|
| 2026-01-18 | Adopt hybrid approach | Balance maintainability with flexibility | ✅ Approved |
| 2026-01-18 | Create utils/ for infrastructure | Consolidate Azure, cost, logging, retry | 📋 Planned |
| 2026-01-18 | Keep adapters independent | Different backends, publication boundaries | ✅ Approved |
| 2026-01-18 | Keep agents independent | Different algorithms, research code | ✅ Approved |

---

## Document Metadata

- **Created**: 2026-01-18
- **Last Updated**: 2026-01-18
- **Author**: Claude Code Agent (Sonnet 4.5)
- **Status**: Draft for Review
- **Next Review**: After Phase 1 migration (Week 1)

