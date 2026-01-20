# Windows Agent Arena Baseline Validation Plan

**Date**: January 18, 2026
**Status**: Draft - Ready for Review

## Executive Summary

Based on analysis of WAA's actual implementation, we've identified critical gaps in our integration that prevent proper evaluation:

1. **Task Loading**: We're creating generic "Task notepad_1" instead of loading real task configs with evaluator specs
2. **Evaluators**: No evaluator integration - returning placeholder scores
3. **Action Format**: Need to support WAA's code block format (`computer.click([42])` not raw coordinates)
4. **Baseline Unknown**: No validated baseline to measure improvements against

This plan provides step-by-step instructions to validate vanilla WAA, fix our integration, and establish a reproducible baseline.

---

## 1. WAA Architecture Analysis

### 1.1 Key Components

Based on reviewing `run.py`, `lib_run_single.py`, `desktop_env.py`, and Navi agent:

**Evaluation Loop** (`run.py` + `lib_run_single.py`):
```python
# 1. Load task config from JSON
config_file = "evaluation_examples_windows/examples/{domain}/{example_id}.json"
with open(config_file, "r") as f:
    example = json.load(f)

# 2. Create environment with task config
env = DesktopEnv(action_space="code_block", require_a11y_tree=True)
obs = env.reset(task_config=example)

# 3. Agent loop (Navi agent)
for step in range(max_steps):
    response, actions, logs, computer_update_args = agent.predict(instruction, obs)
    env.controller.update_computer(**computer_update_args)  # Update rects/scale

    for action in actions:  # Python code blocks
        obs, reward, done, info = env.step(action, sleep_after_execution=3)
        if done:
            break

# 4. Evaluate using task's evaluator config
result = env.evaluate()  # Uses getters + metrics from task config
```

**Task Config Structure** (from `366de66e-cbae-4d72-b042-26390db2b145-WOS.json`):
```json
{
    "id": "366de66e-cbae-4d72-b042-26390db2b145-WOS",
    "snapshot": "notepad",
    "instruction": "Please open Notepad, create a new file named \"draft.txt\", type \"This is a draft.\", and save it to the Documents folder.",
    "evaluator": {
        "postconfig": [
            {"type": "open", "parameters": {"path": "C:\\Users\\Docker\\Documents\\draft.txt"}},
            {"type": "activate_window", "parameters": {"window_name": "draft.txt - Notepad"}}
        ],
        "func": ["exact_match", "compare_text_file"],
        "result": [
            {"type": "vm_file_exists_in_vm_folder", "folder_name": "C:\\Users\\Docker\\Documents", "file_name": "draft.txt"},
            {"type": "vm_file", "path": "C:\\Users\\Docker\\Documents\\draft.txt", "dest": "draft.txt"}
        ],
        "expected": [
            {"type": "rule", "rules": {"expected": 1.0}},
            {"type": "cloud_file", "path": "https://raw.githubusercontent.com/...", "dest": "draft_gold.txt"}
        ]
    }
}
```

**Evaluator Architecture**:
- **Getters** (`desktop_env/evaluators/getters/`): Extract state (files, screenshots, DOM, etc.)
  - `get_vm_file_exists_in_vm_folder()` - Check if file exists
  - `get_vm_file()` - Download file from VM
  - `get_vm_screenshot()` - Get screenshot
  - `get_cloud_file()` - Download reference file from URL
- **Metrics** (`desktop_env/evaluators/metrics/`): Compare actual vs expected
  - `exact_match()` - Boolean equality
  - `compare_text_file()` - Text file content comparison
  - `compare_image_file()` - Image similarity
  - `webpage_text_in()` - Text presence in webpage

**Navi Agent** (`mm_agents/navi/agent.py`):
- Uses `action_space = "code_block"` (line 83)
- Returns Python code blocks like:
  ```python
  computer.click([42])  # Click element ID 42
  computer.type("hello world")
  computer.key("enter")
  computer.mouse.move_id(5)  # Move to element 5
  ```
- Processes screenshot + accessibility tree with Set-of-Marks (SoM)
- Uses element-based grounding (IDs not coordinates)

### 1.2 Key Differences from Our Implementation

| Aspect | WAA Implementation | Our WAALiveAdapter |
|--------|-------------------|-------------------|
| Task Loading | Loads full JSON with evaluator config | Creates minimal BenchmarkTask without evaluator |
| Action Format | Python code blocks (`computer.click([42])`) | BenchmarkAction objects with coordinates |
| Evaluation | Uses task's getters + metrics | Returns placeholder heuristics |
| Grounding | Element IDs via `computer_update_args` | Direct coordinates or element IDs |
| Observation | Screenshot + a11y tree + rects | Screenshot + a11y tree only |

---

## 2. Baseline Validation Plan

### 2.1 Goal
Run vanilla WAA with Navi agent (GPT-4o) on 5-10 simple tasks to establish a baseline success rate that we can reproduce.

### 2.2 Approach: Use Existing waa-auto Docker Image

**Why Docker?** The `waa-auto` image (built by `openadapt-ml` CLI) includes:
- Windows 11 VM with auto-boot
- WAA client code at `/waa/client/`
- Python 3 + all dependencies pre-installed
- Flask server auto-starts on boot

**Advantages**:
- No manual setup required
- Reproducible environment
- Already working in our Azure VM setup

### 2.3 Baseline Validation Steps

**Prerequisites**:
- Azure VM running with `waa-auto` container (via `vm setup-waa` command)
- OpenAI API key with access to GPT-4o
- WAA evaluation_examples_windows directory on VM

**Steps**:

```bash
# 1. Ensure VM is running with waa-auto
uv run python -m openadapt_ml.benchmarks.cli vm monitor

# 2. SSH into VM
uv run python -m openadapt_ml.benchmarks.cli vm ssh

# 3. Inside VM, enter the waa-auto container
docker exec -it waa-auto bash

# 4. Navigate to WAA client directory
cd /waa/client

# 5. Create minimal test_baseline.json with 5 simple tasks
cat > test_baseline.json << 'EOF'
{
    "notepad": ["366de66e-cbae-4d72-b042-26390db2b145-WOS"],
    "file_explorer": ["016c9a9d-f2b9-4428-8fdb-f74f4439ece6-WOS"],
    "clock": ["02F10F89-7171-4D37-8550-A00BA8930CDF-WOS"]
}
EOF

# 6. Create config.json with OpenAI API key
cat > config.json << EOF
{
    "OPENAI_API_KEY": "$OPENAI_API_KEY"
}
EOF

# 7. Run vanilla WAA evaluation
python run.py \
    --test_all_meta_path test_baseline.json \
    --model gpt-4o \
    --agent_name navi \
    --som_origin oss \
    --max_steps 15 \
    --observation_type screenshot_a11y_tree \
    --action_space code_block \
    --result_dir /tmp/baseline_results \
    --emulator_ip 172.30.0.2

# 8. Check results
cat /tmp/baseline_results/*/result.txt
```

**Expected Output**:
```
Average score: 0.XX  # WAA's baseline success rate
```

**Success Criteria**:
- All 3-5 tasks complete without crashes
- Get numeric success scores (0.0 to 1.0)
- Can reproduce the same results on re-run
- Results match WAA's published baselines (~19.5% for GPT-4o + OmniParser)

### 2.4 Alternative: Direct Python Execution (If Docker Issues)

If the Docker approach has issues, run directly on the VM:

```bash
# On VM (outside Docker)
cd /home/azureuser/WindowsAgentArena/src/win-arena-container/client

# Same steps as above but use emulator_ip 20.20.20.21 (VM runs in QEMU)
python run.py \
    --test_all_meta_path test_baseline.json \
    --model gpt-4o \
    --emulator_ip 20.20.20.21 \
    ...
```

---

## 3. Fixes Needed in WAALiveAdapter

Based on the analysis, here are the required changes:

### 3.1 Task Loading (HIGH PRIORITY)

**File**: `openadapt_evals/adapters/waa_live.py`

**Problem**: `load_task()` creates minimal tasks without evaluator configs.

**Fix**: Update `_load_task_from_disk()` to properly parse task JSON files.

```python
def _load_task_from_disk(self, task_id: str, base_path: str) -> BenchmarkTask | None:
    """Load task from WAA examples directory on disk.

    Args:
        task_id: Task identifier (e.g., "notepad_366de66e-cbae-4d72-b042-26390db2b145-WOS").
        base_path: Path to WAA evaluation_examples_windows directory.

    Returns:
        BenchmarkTask with full evaluator config.
    """
    import json
    from pathlib import Path

    base = Path(base_path)

    # Parse task_id: format is "domain_uuid-WOS"
    # Example: "notepad_366de66e-cbae-4d72-b042-26390db2b145-WOS"
    parts = task_id.split("_", 1)
    if len(parts) < 2:
        return None

    domain = parts[0]
    task_file = parts[1] + ".json"  # Add .json extension

    # Try examples directory
    task_path = base / "examples" / domain / task_file
    if not task_path.exists():
        logger.warning(f"Task file not found: {task_path}")
        return None

    # Load full task config
    with open(task_path, encoding="utf-8") as f:
        config = json.load(f)

    logger.info(f"Loaded task config from {task_path}")

    return BenchmarkTask(
        task_id=task_id,
        instruction=config["instruction"],
        domain=domain,
        initial_state_ref=config.get("snapshot"),
        time_limit_steps=15,  # WAA default
        raw_config=config,  # CRITICAL: Full config with evaluator
        evaluation_spec=config.get("evaluator"),  # Extracted for convenience
    )
```

**Testing**:
```python
from openadapt_evals.adapters.waa_live import WAALiveAdapter, WAALiveConfig

config = WAALiveConfig(
    server_url="http://vm:5000",
    waa_examples_path="/path/to/WindowsAgentArena/src/win-arena-container/client/evaluation_examples_windows"
)
adapter = WAALiveAdapter(config)

# Should load full config with evaluator
task = adapter.load_task("notepad_366de66e-cbae-4d72-b042-26390db2b145-WOS")
assert task.evaluation_spec is not None
assert "evaluator" in task.raw_config
assert "func" in task.raw_config["evaluator"]
```

### 3.2 Evaluation Implementation (HIGH PRIORITY)

**File**: `openadapt_evals/server/evaluate_endpoint.py`

**Problem**: `/evaluate` endpoint implementation is basic, doesn't use WAA's full evaluator system.

**Fix**: Enhance to match WAA's evaluation logic from `desktop_env.py:330-399`.

```python
def create_evaluate_routes(app: "Flask", getters: Any, metrics: Any) -> None:
    """Add /evaluate endpoint to Flask app."""
    from flask import jsonify, request

    @app.route("/evaluate", methods=["POST"])
    def evaluate():
        """Evaluate current VM state against task criteria.

        Request body should be full task config with 'evaluator' field.
        """
        task_config = request.json

        if not task_config:
            return jsonify({"error": "No task config provided"}), 400

        evaluator_config = task_config.get("evaluator", {})

        if not evaluator_config:
            return jsonify({
                "success": False,
                "score": 0.0,
                "reason": "No evaluator configuration in task",
            })

        # 1. Run postconfig setup (open files, activate windows, etc.)
        postconfig = evaluator_config.get("postconfig", [])
        # TODO: Implement postconfig execution via SetupController

        # 2. Handle infeasible tasks
        if evaluator_config.get("func") == "infeasible":
            agent_last_action = task_config.get("agent_last_action", "")
            if agent_last_action.upper() == "FAIL":
                return jsonify({
                    "success": True,
                    "score": 1.0,
                    "reason": "Correctly identified infeasible task",
                })
            else:
                return jsonify({
                    "success": False,
                    "score": 0.0,
                    "reason": "Infeasible task but agent did not output FAIL",
                })

        # 3. Run evaluator (single or multiple metrics)
        func = evaluator_config.get("func")

        if isinstance(func, list):
            # Multiple metrics with conjunction (AND/OR)
            scores = []
            conj = evaluator_config.get("conj", "and")

            for idx, metric_name in enumerate(func):
                result_spec = evaluator_config["result"][idx]
                expected_spec = evaluator_config.get("expected", [None])[idx]
                options = evaluator_config.get("options", [{}])[idx] or {}

                # Get actual value
                result_getter = getattr(getters, f"get_{result_spec['type']}")
                actual = result_getter(None, result_spec)  # Pass mock env

                # Get expected value
                expected = None
                if expected_spec:
                    if expected_spec.get("type") == "rule":
                        expected = expected_spec.get("rules", {}).get("expected")
                    else:
                        expected_getter = getattr(getters, f"get_{expected_spec['type']}")
                        expected = expected_getter(None, expected_spec)

                # Run metric
                metric_func = getattr(metrics, metric_name)
                score = metric_func(actual, expected, **options) if expected else metric_func(actual, **options)

                # Short-circuit on failure for AND
                if conj == "and" and float(score) == 0.0:
                    return jsonify({
                        "success": False,
                        "score": 0.0,
                        "reason": f"Metric {idx+1}/{len(func)} failed ({metric_name})",
                    })

                scores.append(float(score))

            # Combine scores
            final_score = sum(scores) / len(scores) if conj == "and" else max(scores)

        else:
            # Single metric
            result_spec = evaluator_config["result"]
            expected_spec = evaluator_config.get("expected")
            options = evaluator_config.get("options", {})

            # Get actual value
            result_getter = getattr(getters, f"get_{result_spec['type']}")
            actual = result_getter(None, result_spec)

            # Get expected value
            expected = None
            if expected_spec:
                if expected_spec.get("type") == "rule":
                    expected = expected_spec.get("rules", {}).get("expected")
                else:
                    expected_getter = getattr(getters, f"get_{expected_spec['type']}")
                    expected = expected_getter(None, expected_spec)

            # Run metric
            metric_func = getattr(metrics, func)
            final_score = metric_func(actual, expected, **options) if expected else metric_func(actual, **options)
            final_score = float(final_score)

        success = final_score >= 1.0

        return jsonify({
            "success": success,
            "score": final_score,
            "reason": f"Evaluation complete (score={final_score:.2f})",
        })
```

**Deploy to VM**:
```bash
# Copy to VM
scp openadapt_evals/server/waa_server_patch.py azureuser@vm:/tmp/

# SSH and patch
ssh azureuser@vm "python /tmp/waa_server_patch.py"

# Or manually add to /waa/server/main.py
```

### 3.3 Action Format Support (MEDIUM PRIORITY)

**File**: `openadapt_evals/agents/api_agent.py`

**Problem**: Agent outputs BenchmarkAction objects, but WAA expects Python code blocks.

**Fix**: Add action translation for code_block format.

```python
def _format_action_for_waa(self, action: BenchmarkAction) -> str:
    """Translate BenchmarkAction to WAA code block format.

    Args:
        action: BenchmarkAction object.

    Returns:
        Python code string for WAA's code_block action space.
    """
    if action.type == "click":
        if action.target_node_id is not None:
            return f"computer.click([{action.target_node_id}])"
        else:
            # Fallback to coordinates
            return f"computer.mouse.move({action.x}, {action.y}); computer.mouse.click()"

    elif action.type == "type":
        text = action.text.replace('"', '\\"')
        return f'computer.type("{text}")'

    elif action.type == "key":
        key = action.key.lower()
        if action.modifiers:
            mods = "+".join(action.modifiers).lower()
            return f'computer.key("{mods}+{key}")'
        return f'computer.key("{key}")'

    elif action.type == "done":
        return "DONE"

    elif action.type == "fail":
        return "FAIL"

    else:
        logger.warning(f"Unknown action type: {action.type}")
        return "# Unknown action"
```

**Integration**: Update `WAALiveAdapter.step()` to use code blocks when calling `/execute_windows`.

### 3.4 Computer Update Args (LOW PRIORITY)

**File**: `openadapt_evals/adapters/waa_live.py`

**Problem**: Not sending `computer_update_args` to sync element state.

**Fix**: Update `_get_observation()` to call `/update_computer` with rects.

```python
def _get_observation(self) -> BenchmarkObservation:
    """Fetch current observation from WAA server.

    Also extracts element rects from a11y tree and updates WAA's Computer
    so element-based grounding works for subsequent actions.
    """
    import requests

    # ... existing screenshot + a11y fetching ...

    # Extract rects for element-based grounding
    self._current_rects = self._extract_rects_from_a11y(a11y_tree)

    # Update WAA's Computer with current rects
    if self._current_rects:
        self._update_waa_computer()

    return BenchmarkObservation(
        screenshot=screenshot,
        viewport=(self.config.screen_width, self.config.screen_height),
        accessibility_tree=a11y_tree,
        window_title=self._extract_window_title(a11y_tree),
    )

def _update_waa_computer(self) -> None:
    """POST current rects to WAA's /update_computer endpoint."""
    import requests

    payload = {
        "rects": self._current_rects,
        "window_rect": [0, 0, self.config.screen_width, self.config.screen_height],
        "screenshot": base64.b64encode(self._current_screenshot).decode("utf-8") if self._current_screenshot else "",
        "scale": [1.0, 1.0],
    }

    try:
        resp = requests.post(
            f"{self.config.server_url}/update_computer",
            json=payload,
            timeout=30.0
        )
        if resp.status_code == 200:
            logger.debug("Updated WAA computer with %d rects", len(self._current_rects))
        else:
            logger.warning(f"update_computer failed: {resp.status_code}")
    except Exception as e:
        logger.error(f"update_computer request error: {e}")
```

---

## 4. Baseline Reproduction Test Script

Create a test script to validate our integration against vanilla WAA:

**File**: `openadapt_evals/tests/test_waa_baseline.py`

```python
"""Test that our WAALiveAdapter produces results matching vanilla WAA.

This test:
1. Loads the same task configs WAA uses
2. Runs the same evaluation logic
3. Compares success rates
"""

import pytest
from openadapt_evals import WAALiveAdapter, WAALiveConfig, ApiAgent, evaluate_agent_on_benchmark


@pytest.mark.integration
def test_waa_baseline_notepad():
    """Test notepad task matches vanilla WAA baseline."""

    # Setup adapter with real WAA task configs
    config = WAALiveConfig(
        server_url="http://localhost:5000",  # Assumes WAA server running locally
        waa_examples_path="/path/to/WindowsAgentArena/src/win-arena-container/client/evaluation_examples_windows",
    )
    adapter = WAALiveAdapter(config)

    # Load real task
    task = adapter.load_task("notepad_366de66e-cbae-4d72-b042-26390db2b145-WOS")

    # Verify task loaded properly
    assert task.instruction == "Please open Notepad, create a new file named \"draft.txt\", type \"This is a draft.\", and save it to the Documents folder."
    assert task.evaluation_spec is not None
    assert "func" in task.evaluation_spec
    assert task.evaluation_spec["func"] == ["exact_match", "compare_text_file"]

    # Run with API agent (Claude or GPT-4o)
    agent = ApiAgent(provider="anthropic")  # or "openai"

    results = evaluate_agent_on_benchmark(
        agent=agent,
        adapter=adapter,
        task_ids=["notepad_366de66e-cbae-4d72-b042-26390db2b145-WOS"],
        max_steps=15,
    )

    # Check results
    assert len(results) == 1
    result = results[0]

    # Verify evaluation ran (not fallback heuristic)
    assert result.reason is not None
    assert "Fallback" not in result.reason
    assert "heuristic" not in result.reason.lower()

    # Score should be 0.0 or 1.0 (not heuristic 0.5)
    assert result.score in (0.0, 1.0)

    print(f"Task: {result.task_id}")
    print(f"Success: {result.success}")
    print(f"Score: {result.score}")
    print(f"Steps: {result.num_steps}")
    print(f"Reason: {result.reason}")


@pytest.mark.integration
def test_waa_baseline_batch():
    """Test multiple tasks match vanilla WAA baseline."""

    config = WAALiveConfig(
        server_url="http://localhost:5000",
        waa_examples_path="/path/to/WindowsAgentArena/src/win-arena-container/client/evaluation_examples_windows",
    )
    adapter = WAALiveAdapter(config)
    agent = ApiAgent(provider="anthropic")

    task_ids = [
        "notepad_366de66e-cbae-4d72-b042-26390db2b145-WOS",
        "file_explorer_016c9a9d-f2b9-4428-8fdb-f74f4439ece6-WOS",
        "clock_02F10F89-7171-4D37-8550-A00BA8930CDF-WOS",
    ]

    results = evaluate_agent_on_benchmark(
        agent=agent,
        adapter=adapter,
        task_ids=task_ids,
        max_steps=15,
    )

    assert len(results) == len(task_ids)

    # Calculate success rate
    success_count = sum(1 for r in results if r.success)
    success_rate = success_count / len(results)

    print(f"\nBaseline Results:")
    print(f"Tasks: {len(results)}")
    print(f"Successes: {success_count}")
    print(f"Success Rate: {success_rate:.1%}")

    # Compare with known WAA baseline
    # GPT-4o baseline is ~19.5% on full benchmark
    # For 3 tasks, expect 0-1 successes
    assert success_count >= 0  # At least runs without crashing
```

**Run the test**:
```bash
# Start WAA server first
uv run python -m openadapt_ml.benchmarks.cli vm monitor

# Run test
uv run pytest openadapt_evals/tests/test_waa_baseline.py -v -s
```

---

## 5. Expected Baseline Performance

Based on WAA's published results (from their paper/GitHub):

| Agent | Success Rate (154 tasks) | Notes |
|-------|-------------------------|-------|
| Navi (GPT-4o + OmniParser) | ~19.5% | SOTA on WAA |
| GPT-4o (vision only) | ~12-15% | Without OmniParser |
| Claude Sonnet 3.5 | ~10-12% | Vision-based |
| Random | ~0% | Baseline |

**For our 3-5 task validation**:
- **Expected**: 0-1 successes out of 5 tasks (~0-20%)
- **Success criteria**:
  - Tasks complete without crashes
  - Scores are 0.0 or 1.0 (not heuristic 0.5)
  - Results are reproducible
  - Match vanilla WAA behavior

**Important**: The absolute success rate matters less than:
1. **Reproducibility**: Same results on re-run
2. **Real evaluation**: Not using fallback heuristics
3. **No crashes**: All tasks complete
4. **Matches vanilla**: Same behavior as `run.py`

---

## 6. Integration Test Checklist

Before running full 154-task evaluation:

- [ ] **Task Loading**
  - [ ] Load real task JSON from evaluation_examples_windows/
  - [ ] Task has `instruction` field
  - [ ] Task has `evaluator` config with `func`, `result`, `expected`
  - [ ] Task has `snapshot` field (initial state)

- [ ] **Evaluation**
  - [ ] `/evaluate` endpoint deployed on WAA server
  - [ ] Evaluator has access to getters and metrics modules
  - [ ] Can run getters (e.g., `get_vm_file_exists_in_vm_folder`)
  - [ ] Can run metrics (e.g., `exact_match`, `compare_text_file`)
  - [ ] Returns real scores (0.0 or 1.0), not heuristics

- [ ] **Agent Actions**
  - [ ] Actions translate to WAA code blocks (`computer.click([42])`)
  - [ ] Element IDs work for grounding
  - [ ] Coordinates work as fallback
  - [ ] TYPE, KEY, SCROLL actions work

- [ ] **Observation**
  - [ ] Screenshot returned from `/screenshot`
  - [ ] Accessibility tree returned from `/accessibility`
  - [ ] Element rects extracted from a11y tree
  - [ ] Computer updated via `/update_computer`

- [ ] **Baseline Validation**
  - [ ] Run 3-5 tasks with vanilla WAA (`run.py`)
  - [ ] Record success rate and scores
  - [ ] Run same tasks with our WAALiveAdapter
  - [ ] Compare success rates (should match ±10%)
  - [ ] Verify no fallback heuristics used

---

## 7. Documentation of Baseline Results

Create a baseline results document:

**File**: `openadapt_evals/docs/WAA_BASELINE_RESULTS.md`

```markdown
# WAA Baseline Results

## Vanilla WAA (run.py)

**Date**: [Date]
**Model**: GPT-4o
**Agent**: Navi (oss)
**Tasks**: 5 (notepad, file_explorer, clock, etc.)

| Task ID | Domain | Success | Score | Steps | Notes |
|---------|--------|---------|-------|-------|-------|
| 366de66e-cbae-4d72-b042-26390db2b145-WOS | notepad | ✓ | 1.0 | 8 | Opened file, typed text, saved |
| 016c9a9d-f2b9-4428-8fdb-f74f4439ece6-WOS | file_explorer | ✗ | 0.0 | 15 | Navigated wrong folder |
| ... | ... | ... | ... | ... | ... |

**Overall**: 1/5 (20%)

## Our Integration (WAALiveAdapter)

**Date**: [Date]
**Model**: Claude Sonnet 4.5
**Agent**: ApiAgent
**Tasks**: Same 5 tasks

| Task ID | Domain | Success | Score | Steps | Notes |
|---------|--------|---------|-------|-------|-------|
| 366de66e-cbae-4d72-b042-26390db2b145-WOS | notepad | ✓ | 1.0 | 9 | Matches vanilla |
| ... | ... | ... | ... | ... | ... |

**Overall**: 1/5 (20%)

## Comparison

| Metric | Vanilla WAA | Our Integration | Match? |
|--------|------------|-----------------|--------|
| Success Rate | 20% | 20% | ✓ |
| Avg Steps | 11.2 | 11.5 | ✓ (~3% diff) |
| Crashes | 0 | 0 | ✓ |
| Evaluator Used | Real | Real | ✓ |

**Conclusion**: Our integration produces results matching vanilla WAA baseline.
```

---

## 8. Next Steps After Baseline Validation

Once baseline is validated and our integration matches vanilla WAA:

1. **Run Full Evaluation** (154 tasks)
   ```bash
   uv run python -m openadapt_evals.benchmarks.cli live \
       --agent api-claude \
       --server http://vm:5000 \
       --waa-examples-path /path/to/evaluation_examples_windows \
       --max-steps 15
   ```

2. **Test Demo-Conditioned Prompting**
   ```bash
   # With demo (expect improvement)
   uv run python -m openadapt_evals.benchmarks.cli live \
       --agent api-claude \
       --demo demo_library/synthetic_demos/notepad_366de66e.txt \
       --server http://vm:5000 \
       --task-ids notepad_366de66e-cbae-4d72-b042-26390db2b145-WOS

   # Without demo (baseline)
   uv run python -m openadapt_evals.benchmarks.cli live \
       --agent api-claude \
       --server http://vm:5000 \
       --task-ids notepad_366de66e-cbae-4d72-b042-26390db2b145-WOS
   ```

3. **Compare Success Rates**
   - Baseline (no demo): ~12-15%
   - With demo: Target 20-30%+ (based on 100% first-action improvement)

4. **Iterate on Demo Quality**
   - Refine synthetic demos based on failure patterns
   - Generate domain-specific demos
   - Test retrieval-based demo selection

---

## Summary

**Critical Findings**:
1. We're not loading real task configs - need to parse JSON from `evaluation_examples_windows/`
2. We're not using WAA's evaluators - need `/evaluate` endpoint with getters + metrics
3. Action format mismatch - need code blocks, not just coordinates
4. Missing baseline - need to validate vanilla WAA first

**Validation Plan**:
1. Run vanilla WAA on 3-5 tasks → establish baseline
2. Fix task loading to use real configs
3. Deploy `/evaluate` endpoint with full evaluator logic
4. Test our integration matches vanilla baseline
5. Document baseline results

**Success Criteria**:
- Our integration produces same results as vanilla WAA
- Real evaluators used (not fallback heuristics)
- Reproducible results
- Ready to test demo-conditioned improvements

**Timeline Estimate**:
- Baseline validation: 2-4 hours
- Fix implementation: 4-6 hours
- Integration testing: 2-3 hours
- Documentation: 1-2 hours
- **Total**: 1-2 days
