# Simple Agent Prompt Template

**Purpose**: This template enforces simplicity principles when creating Claude Code agent prompts.

**Last Updated**: 2026-01-18

---

## Template Structure

Copy this template when creating prompts for Claude Code agents:

```markdown
# [TASK NAME]

## Context
[1-2 sentences: What problem are we solving?]

## Simplicity Checklist (VERIFY BEFORE STARTING)

Before writing any code, verify:
- [ ] This solves a real, immediate problem (not theoretical)
- [ ] Can be done in <100 lines (ideally <50)
- [ ] Simplest approach (not most elegant)
- [ ] Provides 80% of value (not 100% perfection)

**If any checkbox is NO → STOP and simplify the requirement**

## Task

[Clear description of what to do]

## Guidelines

**Default to simplicity**:
1. Use functions, not classes (unless you need inheritance/state)
2. Inline code is fine if used once (extract on 3rd use)
3. Real data, not mocks
4. Working code > perfect design
5. Delete > keep (when in doubt)

**Red flags to avoid**:
- ❌ Creating utility classes used in one place
- ❌ Writing design docs for non-existent code
- ❌ Multiple implementations of same thing
- ❌ TODOs that return empty strings
- ❌ Building frameworks before 3+ use cases

## Success Criteria

[What does "done" look like?]
- Code works (passes tests)
- <100 lines (ideally <50)
- No duplication
- Can explain in 1 sentence

## Files

**Read these first**:
- [List files to read for context]

**Modify**:
- [List files to change]

**Create** (only if absolutely necessary):
- [List new files, if any]

## Examples

**Good approach**:
```python
# Simple, direct, works
def solve_problem(input):
    return result
```

**Bad approach**:
```python
# Over-engineered, unnecessary abstraction
class ProblemSolverOrchestrator:
    def __init__(self, config):
        self.config = config
        self.solver = ProblemSolver()
        self.validator = ResultValidator()
    # ... 100 more lines
```

## Validation Checklist

After implementation, verify:
- [ ] Code actually runs (not just syntactically correct)
- [ ] Can explain what it does in 1 sentence
- [ ] No duplication (checked existing code)
- [ ] No TODOs or commented-out code
- [ ] Tests prove it works
- [ ] <100 lines total
```

---

## Example Prompt Using This Template

Here's a concrete example:

```markdown
# Add VM Health Check to CLI

## Context
We need to check if Azure VM is healthy before running evaluations. Currently we assume it's ready and fail later.

## Simplicity Checklist (VERIFY BEFORE STARTING)

Before writing any code, verify:
- [x] This solves a real, immediate problem (users waste time on failed evals)
- [x] Can be done in <100 lines (just add a health check function)
- [x] Simplest approach (call `az vm show`, check powerState)
- [x] Provides 80% of value (catches 80% of issues: VM stopped, deallocated)

**All checkboxes YES → Proceed**

## Task

Add a `check_vm_healthy()` function to cli.py that:
1. Checks if VM is in "running" state
2. Checks if public IP is accessible
3. Returns True/False
4. Used by cmd_azure() before starting evaluation

## Guidelines

**Default to simplicity**:
1. Use function (not class) - stateless check
2. Use existing Azure CLI commands (no SDK)
3. No retry logic yet (YAGNI - you aren't gonna need it)
4. Inline in cli.py (only used in one place so far)

**Red flags to avoid**:
- ❌ Creating HealthChecker class (overkill for one function)
- ❌ Implementing circuit breaker (not needed yet)
- ❌ Multi-layer health checks (just check VM state)

## Success Criteria

- Function works (returns True for running VM, False otherwise)
- <20 lines
- Used in cmd_azure() before starting eval
- No dependencies beyond subprocess
- Can explain: "Checks if VM is running and has IP"

## Files

**Read these first**:
- cli.py (lines 462-757, see how vm-setup does VM operations)

**Modify**:
- cli.py (add check_vm_healthy function, call from cmd_azure)

**Create**:
- None (inline in existing file)

## Examples

**Good approach**:
```python
def check_vm_healthy(vm_name: str, resource_group: str) -> bool:
    """Check if VM is running and has public IP."""
    # Check power state
    result = subprocess.run([
        "az", "vm", "show",
        "--name", vm_name,
        "--resource-group", resource_group,
        "--query", "powerState",
        "-o", "tsv",
    ], capture_output=True, text=True)

    if result.returncode != 0 or "running" not in result.stdout.lower():
        return False

    # Check public IP exists
    result = subprocess.run([
        "az", "vm", "show",
        "--name", vm_name,
        "--resource-group", resource_group,
        "--show-details",
        "--query", "publicIps",
        "-o", "tsv",
    ], capture_output=True, text=True)

    return bool(result.stdout.strip())
```

**Bad approach** (DON'T DO THIS):
```python
class VMHealthChecker:
    def __init__(self, vm_name: str, resource_group: str, config: HealthConfig):
        self.vm_name = vm_name
        self.resource_group = resource_group
        self.config = config
        self.circuit_breaker = CircuitBreaker()
        self.retry_policy = RetryPolicy()

    def check_all_layers(self) -> List[HealthCheckResult]:
        # ... 100 lines of over-engineered health checking
```

## Validation Checklist

After implementation, verify:
- [x] Code actually runs (tested with real VM)
- [x] Can explain: "Checks VM powerState and publicIps"
- [x] No duplication (only one health check function)
- [x] No TODOs
- [x] Test proves it works (returns True for running VM)
- [x] <20 lines (actually 18 lines)
```

---

## Anti-Pattern Examples (DON'T USE THESE)

### ❌ Bad Prompt 1: Too Vague

```markdown
# Improve Health Checking

Add better health checking to the system.

Guidelines: Make it robust and production-ready.
```

**Problems**:
- No simplicity checklist
- No concrete success criteria
- "Robust" and "production-ready" invite over-engineering
- No line count limit
- No examples of what to avoid

### ❌ Bad Prompt 2: Over-Specified

```markdown
# Implement Comprehensive Health Monitoring System

Create a multi-layer health checking framework with:
- Abstract base class HealthChecker
- Concrete implementations: VMHealthChecker, ContainerHealthChecker, ServerHealthChecker
- Circuit breaker pattern with exponential backoff
- Metrics collection and alerting
- Retry policies with jitter
- Health check result aggregation
- Dashboard integration

Files to create:
- health_checker.py (base classes)
- vm_health.py (VM-specific)
- container_health.py (container-specific)
- server_health.py (server-specific)
- circuit_breaker.py (circuit breaker implementation)
- retry_policy.py (retry logic)
- health_metrics.py (metrics)
- health_dashboard.py (visualization)

Success: All health checks implemented with <95% test coverage.
```

**Problems**:
- No simplicity checklist (invites over-engineering)
- Assumes we need all these features (no validation of necessity)
- Creates 8 files before knowing if we need them
- No "simplest approach" alternative
- No line count limits
- No concrete use case (theoretical requirements)

### ✅ Good Prompt (Fixed Version)

```markdown
# Add Basic VM Health Check

## Context
Evaluations fail when VM is stopped. Need to check before starting.

## Simplicity Checklist

- [x] Real problem (wasted time on failed evals)
- [x] <100 lines (one function ~20 lines)
- [x] Simplest approach (call az vm show)
- [x] 80% value (catches VM stopped/deallocated)

## Task

Add check_vm_healthy() to cli.py. Checks VM powerState before eval.

## Guidelines

- Use function (not class)
- Use az CLI (not SDK)
- No retry logic (YAGNI)
- Inline in cli.py (one use)

## Success Criteria

- <20 lines
- Returns True/False
- Used in cmd_azure()
- Can explain in 1 sentence

See template for full example.
```

---

## Key Principles Encoded in Template

### 1. Simplicity Checklist (Mandatory)

Every prompt MUST have this checklist. Forces thinking before coding:
- Real, immediate problem?
- <100 lines?
- Simplest approach?
- 80% value?

**If any NO → STOP and simplify**

### 2. Concrete Success Criteria

Not "robust" or "production-ready" (subjective), but:
- Specific line counts (<100, ideally <50)
- Concrete behavior (returns True/False)
- Measurable (has tests that pass)
- Explainable (can describe in 1 sentence)

### 3. Examples of Good vs Bad

Show both approaches:
- ✅ Good: Simple, direct, works
- ❌ Bad: Over-engineered, unnecessary complexity

This teaches by example.

### 4. Red Flags Section

Explicitly list anti-patterns to avoid:
- Creating classes for one-time use
- Building frameworks before 3+ use cases
- Writing design docs for non-existent code
- Multiple implementations of same thing

### 5. Files Section (Minimize Creation)

**Read first** (understand context)
**Modify** (prefer editing to creating)
**Create** (only if absolutely necessary, justify why)

Default: modify existing files, not create new ones.

---

## Usage Instructions

### For Prompt Authors

1. Copy template above
2. Fill in sections
3. Verify simplicity checklist yourself
4. Add concrete examples
5. Specify line count limits
6. Review for over-engineering signals

### For Claude Code Agents

When you receive a prompt:
1. Verify simplicity checklist FIRST
2. If any NO → ask user to simplify requirement
3. Read existing code before writing new code
4. Default to functions, not classes
5. Extract abstractions only after 3rd use
6. Verify success criteria before marking done

### For Reviewers

When reviewing agent work:
1. Check if simplicity checklist was verified
2. Verify line counts (<100 total)
3. Look for over-engineering patterns
4. Check if simpler approach exists
5. Verify working code (not just syntactic)

---

## Template Checklist

Use this when creating prompts:

**Structure**:
- [ ] Has Context (1-2 sentences)
- [ ] Has Simplicity Checklist (4 questions)
- [ ] Has clear Task description
- [ ] Has Guidelines (simplicity defaults)
- [ ] Has Red Flags (anti-patterns)
- [ ] Has Success Criteria (concrete, measurable)
- [ ] Has Files section (read/modify/create)
- [ ] Has Examples (good vs bad)
- [ ] Has Validation Checklist (post-implementation)

**Content**:
- [ ] Line count limits specified (<100, ideally <50)
- [ ] Simplicity checklist filled out
- [ ] Real problem stated (not theoretical)
- [ ] Simplest approach identified
- [ ] Examples show both good and bad approaches
- [ ] Red flags call out specific anti-patterns
- [ ] Success criteria are measurable

**Quality**:
- [ ] Template itself <500 lines
- [ ] Examples are concrete (not abstract)
- [ ] No aspirational features (only immediate needs)
- [ ] Can explain task in 1 sentence

---

## Maintenance

**Update this template when**:
- We discover new anti-patterns
- We identify new red flags
- We find better examples
- We learn from mistakes

**Keep it simple**:
- Template itself should be <500 lines
- Examples should be concrete
- Guidelines should be actionable

**Current version**: 1.0 (2026-01-18)

---

**End of Template** | 349 lines (practicing what we preach!)
