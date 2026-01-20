# Simplicity Principles

**Philosophy**: "Less is more. 80/20 impact/complexity. Working code beats elegant design."

**Last Updated**: 2026-01-18

---

## Core Principle: The 80/20 Rule

**Before writing ANY code, ask**: "Does this provide 80% of the value with 20% of the complexity?"

If the answer is no, DELETE or SIMPLIFY until it does.

---

## When to Write Code

Write code when:
- ✅ It solves a real, immediate problem (not a theoretical future one)
- ✅ You can implement it in <100 lines
- ✅ It will be used in 2+ places (for abstractions)
- ✅ A simple function will do the job
- ✅ You've tried the simplest approach first and it doesn't work

**Examples**:
- ✅ `vm-setup` command: 305 lines, works end-to-end, solves real problem
- ✅ Inline bash script: If it works and you only need it once, keep it inline
- ✅ Helper function: Extract when used 2+ times, not before

---

## When to Delete Code

Delete code when:
- ❌ It's never called (dead code)
- ❌ It returns empty strings or TODOs (non-functional stubs)
- ❌ There's a simpler 10-line alternative
- ❌ It duplicates existing functionality
- ❌ It describes non-existent features (design docs for unimplemented code)
- ❌ You're not sure what it does (if you don't understand it, users won't either)

**Examples**:
- ❌ 6000 lines of design docs describing classes that don't exist → DELETE
- ❌ Utility class used in one place → Inline it
- ❌ Function that returns "" with a TODO comment → DELETE the function
- ❌ Multiple implementations of the same thing → Keep best one, delete others

---

## How to Identify High Leverage Patterns

**The 1-2 Pattern Rule**: Focus on the 1-2 highest impact patterns, not 10 edge cases.

**Steps**:
1. **Measure** what actually happens (real data, not assumptions)
2. **Identify** the top 2 patterns that cover 80% of cases
3. **Implement** ONLY those 2 patterns well
4. **Ignore** the remaining 20% until proven necessary

**Example from openadapt-evals**:
- Problem: Container management logic duplicated 3x
- Pattern analysis: 90% of operations are "check if exists" + "start if stopped"
- High leverage solution: `DockerContainerManager` with 2 methods
- Low leverage (avoid): 50 methods covering every edge case

**Anti-pattern**:
- Writing 10 utility methods before you know what's needed
- Creating frameworks before you have 3+ concrete use cases
- Building abstractions for "future flexibility"

---

## Red Flags for Over-Engineering

Watch for these warning signs:

### 🚩 Classes When Functions Work
```python
# ❌ Over-engineered
class GreetingGenerator:
    def __init__(self, name: str):
        self.name = name

    def generate(self) -> str:
        return f"Hello, {self.name}!"

# ✅ Simple
def greet(name: str) -> str:
    return f"Hello, {name}!"
```

**Rule**: Use classes ONLY when you need:
- Shared state across multiple method calls
- Inheritance or polymorphism
- Complex lifecycle management

Otherwise, use functions.

### 🚩 Documentation Describing Non-Existent Code
```markdown
❌ BAD: WAA_RELIABILITY_PLAN.md (2,250 lines)
  - Describes VMSetupOrchestrator class → NOT IMPLEMENTED
  - Promises CircuitBreaker pattern → NOT IMPLEMENTED
  - Shows retry utilities → NOT IMPLEMENTED
  - Creates false expectations

✅ GOOD: Implementation notes in docstrings
  - Documents what IS implemented
  - Notes what's planned vs done
  - Links to actual working code
```

**Rule**: Documentation should describe reality, not aspirations. Design docs are fine but mark them clearly as "DESIGN ONLY".

### 🚩 Abstractions Before Use Cases
```python
# ❌ Over-engineered (built before needed)
class AbstractContainerOrchestrator(ABC):
    @abstractmethod
    def pre_setup_hook(self): pass

    @abstractmethod
    def post_setup_hook(self): pass

    # ... 15 more abstract methods

# ✅ Simple (built after 3rd use case)
def setup_container(image: str, ports: dict):
    """Setup container. Used in vm-setup, server-start, up commands."""
    # Simple implementation
```

**Rule**: Extract abstractions AFTER you have 3+ concrete implementations, not before.

### 🚩 Multiple Implementations of Same Thing
```python
# ❌ Code duplication (from review)
# cli.py cmd_vm_setup: Container start logic (295 lines)
# cli.py cmd_server_start: Container start logic (85 lines)
# cli.py cmd_up: Container start logic (107 lines)
# Total: 487 lines for same operation!

# ✅ Single implementation
# docker_utils.py DockerContainerManager.start_container() (20 lines)
# Used by: vm-setup, server-start, up
# Total: 20 lines + 3 one-line calls
```

**Rule**: If you copy-paste code, you need a function. If you copy-paste a function, you need a module.

### 🚩 TODOs That Return Empty Strings
```python
# ❌ Misleading non-functionality
def _get_job_logs(self, job_name: str) -> str:
    # TODO: Implement log fetching
    return ""  # LIES TO CALLER!

# ✅ Honest about not working
def _get_job_logs(self, job_name: str) -> str:
    raise NotImplementedError("Log fetching not yet implemented")

# ✅ Better: Just delete it until you need it
# (Don't write TODOs for future features)
```

**Rule**: Delete non-functional code. If it doesn't work, it shouldn't exist.

---

## Examples: Good vs Bad

### Example 1: Container Management

**❌ BAD (Over-engineered)**:
- 3 separate implementations (vm-setup, server-start, up)
- 487 total lines for same operation
- Inconsistent error messages
- Hard to test (inline bash scripts)
- Can't reuse across commands

**✅ GOOD (Simple)**:
- 1 `DockerContainerManager` class
- 2 methods: `check_exists()`, `start_container()`
- 40 lines total (including error handling)
- Easy to test (mock subprocess)
- Reused in 3 commands

**Impact**: 487 lines → 40 lines (92% reduction), better quality

### Example 2: Design Documentation

**❌ BAD (Aspirational)**:
- VM_SETUP_COMMAND.md: 2,185 lines
- Describes VMSetupOrchestrator class → doesn't exist
- Shows progress monitoring → not implemented
- Promises retry logic → not implemented
- Result: Developers try to import non-existent classes

**✅ GOOD (Reality-based)**:
- Implementation notes in docstrings (50 lines)
- Documents actual bash script approach
- Notes limitations honestly
- Links to working code
- Result: Developers can actually use it

**Impact**: Eliminates confusion, sets correct expectations

### Example 3: Health Checking

**❌ BAD (Premature abstraction)**:
```python
class AbstractHealthChecker(ABC):
    @abstractmethod
    def check_layer_1(self): pass
    @abstractmethod
    def check_layer_2(self): pass
    # ... 5 abstract methods
    # ... implemented before knowing if needed
```

**✅ GOOD (Proven need first)**:
```bash
# Inline health check (vm-setup, works)
if docker exec winarena bash -c "timeout 2 bash -c '</dev/tcp/localhost/6080'"; then
    echo "✓ Windows booted"
fi
```

Later, AFTER using in 3 places:
```python
class HealthChecker:
    def check_windows_boot(self) -> bool:
        # Extract proven logic
```

**Impact**: Ship working code now, abstract later if needed

---

## Decision Framework

**Before writing code, use this checklist**:

### 1. Is it necessary?
- [ ] Solves a real, current problem (not theoretical)
- [ ] No simpler alternative exists
- [ ] Will be used immediately (not "someday")

### 2. Is it simple?
- [ ] Can explain in 1 sentence
- [ ] <100 lines (ideally <50)
- [ ] No external dependencies if avoidable
- [ ] Works with existing patterns

### 3. Is it the 80% solution?
- [ ] Covers most common case
- [ ] Ignores rare edge cases (for now)
- [ ] Provides 80% value with 20% complexity
- [ ] Can ship it today

**If all 3 checkboxes aren't YES → STOP and simplify**

### Example Application

**Scenario**: Need to run commands on Azure VM

**❌ Complex approach**:
```python
class AzureVMCommandExecutor:
    def __init__(self, config: AzureVMConfig):
        self.config = config
        self.retry_policy = RetryPolicy(...)
        self.circuit_breaker = CircuitBreaker(...)

    def execute_with_retry(self, cmd: Command) -> Result:
        # 200 lines of retry logic, circuit breakers, metrics
```

**Checklist fails**:
- ❌ Is it necessary? Don't need circuit breaker yet
- ❌ Is it simple? 200 lines for running a command
- ❌ Is it 80%? Most calls succeed on first try

**✅ Simple approach**:
```python
def run_vm_command(vm_name: str, resource_group: str, script: str) -> str:
    """Run bash script on Azure VM."""
    result = subprocess.run([
        "az", "vm", "run-command", "invoke",
        "--resource-group", resource_group,
        "--name", vm_name,
        "--command-id", "RunShellScript",
        "--scripts", script,
    ], capture_output=True, text=True)

    if result.returncode != 0:
        raise RuntimeError(f"Command failed: {result.stderr}")

    return result.stdout
```

**Checklist passes**:
- ✅ Necessary: Solves real problem now
- ✅ Simple: 15 lines, no dependencies
- ✅ 80% solution: Handles common case

**Later**, if you need retry (after 3+ failures):
```python
for attempt in range(3):
    try:
        return run_vm_command(vm_name, resource_group, script)
    except RuntimeError:
        if attempt == 2:
            raise
        time.sleep(2 ** attempt)
```

Add complexity ONLY when proven necessary.

---

## Anti-Patterns to Avoid

### ❌ Writing Design Docs for Non-Existent Classes
**What happened**: 6000 lines describing VMSetupOrchestrator, CircuitBreaker, etc.
**What existed**: 305-line bash script in cli.py
**Result**: Confusion, wasted time, false expectations
**Fix**: Delete design docs OR mark as "DESIGN ONLY - NOT IMPLEMENTED"

### ❌ Creating Utility Classes Used in One Place
**What happened**: Created elaborate utility classes, used once
**What should have happened**: Inline the 10 lines
**Fix**: Delete class, inline code at call site

### ❌ Multiple Implementations of Same Thing
**What happened**: Container start logic in 3 places (487 lines)
**What should have happened**: One function (40 lines)
**Fix**: Extract shared function, delete duplicates

### ❌ TODOs That Return Empty Strings
**What happened**: `_get_job_logs()` returns "" with TODO comment
**What should have happened**: Delete function until needed
**Fix**: Delete or raise NotImplementedError

### ❌ Bash Scripts Wrapped in Python Classes
**What happened**: 295-line bash script works fine
**What shouldn't happen**: Wrap in elaborate Python orchestrator class
**What to do**: Keep bash if it works, only migrate if proven pain point

---

## Practical Guidelines

### Functions > Classes (Default to Functions)

**Use functions when**:
- Operation is stateless
- No inheritance needed
- Single responsibility
- Used 1-3 times

**Use classes when**:
- Shared state across calls
- Lifecycle management (setup/teardown)
- Inheritance/polymorphism needed
- Used 5+ times with variations

**Example**:
```python
# ✅ Function (stateless)
def parse_action(response: str) -> Action:
    return Action.from_string(response)

# ❌ Unnecessary class
class ActionParser:
    def parse(self, response: str) -> Action:
        return Action.from_string(response)
```

### Inline > Abstraction (Until 3rd Use)

**Rules**:
1. First time: Write inline
2. Second time: Write inline (copy-paste is OK temporarily)
3. Third time: NOW extract to function

**Why**: You don't know the right abstraction until you've seen 3 use cases.

**Example**:
```python
# First use (inline)
ip = subprocess.run(["az", "vm", "show", ...], ...).stdout.strip()

# Second use (inline, notice pattern)
ip = subprocess.run(["az", "vm", "show", ...], ...).stdout.strip()

# Third use (NOW extract)
def get_vm_ip(vm_name: str, rg: str) -> str:
    return subprocess.run(["az", "vm", "show", ...], ...).stdout.strip()
```

### Delete > Design (Working Code Only)

**Rules**:
- Delete unused code immediately (don't "save for later")
- Delete design docs that don't match reality
- Delete TODOs older than 2 weeks
- Delete comments explaining what code does (code should be clear)

**What to keep**:
- Working code that's used
- Comments explaining WHY (not what)
- Design docs clearly marked "DESIGN ONLY"

### 10 Lines > 100 Lines (Always Ask "Can This Be Simpler?")

**Before writing 100 lines, try**:
1. Can a library do this? (don't reinvent)
2. Can it be 10 lines? (simplify algorithm)
3. Can it be a bash one-liner? (sometimes shell is simpler)
4. Do you even need it? (maybe delete the requirement)

**Example**:
```python
# ❌ 100 lines of JSON parsing/validation
class JSONValidator:
    def __init__(self): ...
    def validate_schema(self): ...
    # ... 95 more lines

# ✅ 1 line (use library)
data = json.loads(response)  # Raises on invalid JSON
```

### Real > Mock (Use Real Data)

**Rules**:
- Use real Azure VMs, not mocks (for testing Azure code)
- Use real WAA evaluations, not synthetic demos (for results)
- Use real recordings, not fake data (for examples)

**Why**:
- Real data exposes real issues
- Mocks hide problems until production
- Users expect real performance

**When to mock**:
- Unit tests for pure functions
- CI/CD where real resources unavailable
- NEVER for documentation/examples

### Test > Document (Working Code Documents Itself)

**Priority order**:
1. Write working code
2. Write tests proving it works
3. Write minimal usage docs (quick start)
4. (Optional) Write detailed docs if complex

**Don't**:
- Write docs before code exists
- Write docs explaining obvious code
- Write docs that duplicate tests

**Example**:
```python
# ❌ Detailed docstring for obvious code
def add(a: int, b: int) -> int:
    """Add two integers together.

    Args:
        a: The first integer to add
        b: The second integer to add

    Returns:
        The sum of a and b

    Examples:
        >>> add(2, 3)
        5
    """
    return a + b

# ✅ Minimal docstring, code is clear
def add(a: int, b: int) -> int:
    """Sum two integers."""
    return a + b
```

---

## Success Metrics

**How to know if you're following these principles**:

### Code Quality Metrics
- ✅ Most modules < 500 lines
- ✅ Most functions < 50 lines
- ✅ No code duplication > 10 lines
- ✅ Test coverage > 80% for non-trivial code
- ✅ No TODOs older than 2 weeks

### Process Metrics
- ✅ Can explain any function in 1 sentence
- ✅ New features ship in days, not weeks
- ✅ Bugs found in development, not production
- ✅ Refactoring is easy (no "don't touch that" code)
- ✅ New contributors can understand codebase in hours

### Documentation Metrics
- ✅ README < 500 lines
- ✅ Quick start works on first try
- ✅ Examples use real data
- ✅ Docs match actual code
- ✅ No "COMING SOON" sections > 1 month old

**If any metric fails → You're over-engineering. Simplify.**

---

## Quick Reference Card

**Before writing code**:
1. Does this solve a real, immediate problem? (not theoretical)
2. Can I implement it in <100 lines? (ideally <50)
3. Is this the simplest approach? (not the most "elegant")
4. Does this provide 80% value? (not 100% perfection)

**If NO to any → STOP. Simplify or delete the requirement.**

**When in doubt**:
- Ship working code > perfect design
- 10 lines > 100 lines
- Functions > classes
- Inline > abstraction (until 3rd use)
- Delete > keep (if unsure)
- Real data > mocks
- Tests > docs

**Remember**: The best code is the code you didn't write.

---

**End of Document** | 431 lines (practicing what we preach!)
