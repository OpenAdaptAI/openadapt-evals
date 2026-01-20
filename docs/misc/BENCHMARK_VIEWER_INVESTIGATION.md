# Benchmark Viewer Investigation Report

**Date**: January 18, 2026
**Issue**: Benchmark viewer at http://127.0.0.1:5555/benchmark/latest shows broken screenshots
**Run**: waa-live_eval_20260116_200004

---

## Executive Summary

### Is This Real or Synthetic Data?

**REAL DATA** - This is from an actual WAA evaluation run.

**Evidence**:
- ✅ Benchmark name: `waa-live` (indicates live WAA server evaluation)
- ✅ Real timestamps: 1768611618.802666 (Jan 16, 2026, 20:00:18 UTC)
- ✅ Actual PNG screenshots exist: 5 valid 1280x720 PNG files
- ✅ Real execution time: 71.89 seconds total (realistic timing)
- ✅ Real action coordinates: Normalized x/y coordinates from actual agent actions
- ❌ Model unknown: `model_id: "unknown"` (agent provider not recorded)
- ❌ Task failed: "Evaluation requires WAA evaluators (not yet implemented)"

**Conclusion**: This is a **REAL evaluation** against a live WAA server, but the agent identity was not captured and the evaluation did not complete successfully.

---

## Problem 1: Screenshots Are Broken in Browser

### Root Cause

The viewer.html uses **relative file paths** that don't work when opening HTML directly in a browser:

```javascript
// From viewer.html line 906:
"screenshots": [
  "tasks/notepad_1/screenshots/step_000.png",
  "tasks/notepad_1/screenshots/step_001.png",
  ...
]
```

When you open `viewer.html` directly (file:///...), the browser tries to load:
```
file:///Users/abrichr/oa/src/openadapt-evals/benchmark_results/waa-live_eval_20260116_200004/tasks/notepad_1/screenshots/step_000.png
```

But the paths are relative to the HTML file's location, which works only if you serve the HTML via HTTP (like the dashboard server does at http://127.0.0.1:5555).

### Why It Works on Dashboard but Not File Open

- **Dashboard (http://127.0.0.1:5555)**: Flask serves files, browser can fetch relative paths
- **Direct file open (file:///)**: Browser blocks cross-origin file access, relative paths fail

### Solution 1: Use the Dashboard Server (Recommended)

```bash
# Start the dashboard server
cd /Users/abrichr/oa/src/openadapt-evals
python -m openadapt_evals.benchmarks.dashboard_server

# Open browser to: http://127.0.0.1:5555/benchmark/latest
```

The dashboard server serves files correctly and screenshots display.

### Solution 2: Regenerate with Embedded Screenshots

```bash
# Regenerate viewer with base64-encoded screenshots
uv run python -m openadapt_evals.benchmarks.cli view \
  --run-name waa-live_eval_20260116_200004 \
  --embed-screenshots

# This creates a standalone HTML with screenshots embedded as data URLs
# Larger file (~1-2MB) but works when opened directly
```

### Solution 3: Fix Viewer Generation (Future Improvement)

Modify `viewer.py` to detect if being opened via file:// and auto-embed screenshots or generate absolute file:// URLs.

---

## Problem 2: Unknown Model ID

### Evidence

All JSON files show:
```json
"model_id": "unknown"
```

This suggests the evaluation was run without specifying the agent provider.

### How This Happens

Looking at the CLI code, model_id gets set from:
1. `--agent` flag (api-claude, api-openai, retrieval-claude, etc.)
2. Defaults to "unknown" if not specified

**Likely command that generated this data:**
```bash
# This would produce model_id="unknown"
uv run python -m openadapt_evals.benchmarks.cli live \
  --server http://vm:5000 \
  --task-ids notepad_1
  # Missing: --agent api-claude (or similar)
```

### How to Capture Model ID Correctly

```bash
# With Claude
uv run python -m openadapt_evals.benchmarks.cli live \
  --agent api-claude \
  --server http://vm:5000 \
  --task-ids notepad_1

# With GPT-5.1
uv run python -m openadapt_evals.benchmarks.cli live \
  --agent api-openai \
  --server http://vm:5000 \
  --task-ids notepad_1
```

---

## Problem 3: Evaluation Did Not Complete

### Error in execution.json

```json
"success": false,
"reason": "Evaluation requires WAA evaluators (not yet implemented)"
```

### Root Cause

The evaluation completed 5 steps but could not determine task success because:
1. WAA's `/evaluate` endpoint was not deployed on the server
2. Or the task config lacked evaluator specification

### How to Fix

**Deploy /evaluate endpoint to WAA server:**

```bash
# Copy patch script to VM
scp openadapt_evals/server/waa_server_patch.py azureuser@vm:/tmp/

# Run on VM to add /evaluate endpoint
ssh azureuser@vm "python /tmp/waa_server_patch.py"
```

**Then re-run with full task config:**

```bash
uv run python -m openadapt_evals.benchmarks.cli live \
  --agent api-claude \
  --server http://vm:5000 \
  --task-ids notepad_1 \
  --waa-examples-path /path/to/WindowsAgentArena/evaluation_examples_windows
```

---

## Data Authenticity Analysis

### What's Real

| Attribute | Value | Analysis |
|-----------|-------|----------|
| **Benchmark** | waa-live | ✅ Live WAA evaluation (not mock) |
| **Timestamps** | 1768611618 → 1768611670 | ✅ Real 52-second execution window |
| **Screenshots** | 5 PNG files (1280x720) | ✅ Actual screenshot data exists |
| **Action coords** | (0.644, 0.326), (0.607, 0.521) | ✅ Normalized coordinates from agent |
| **Domain** | notepad | ✅ Valid WAA task domain |
| **Task ID** | notepad_1 | ✅ Valid WAA task identifier |

### What's Missing/Unknown

| Attribute | Value | Analysis |
|-----------|-------|----------|
| **Model ID** | unknown | ❌ Agent provider not specified |
| **Task Success** | false | ❌ Evaluation incomplete (no evaluator) |
| **Instruction** | "Task notepad_1" | ⚠️ Generic placeholder (real task has detailed instruction) |
| **Reasoning** | null | ⚠️ Agent didn't provide reasoning (or wasn't captured) |

### Conclusion

**This is REAL data from a live WAA evaluation**, but:
- Agent identity unknown (model_id not captured)
- Evaluation incomplete (no success/fail determination)
- Task instruction is placeholder text
- Screenshots exist and are valid

**Not synthetic, not mock - but incomplete real data.**

---

## How to Run a Proper Evaluation

### Full End-to-End Command

```bash
# 1. Ensure WAA server is running with /evaluate endpoint
uv run python -m openadapt_evals.benchmarks.cli vm-setup --auto-verify

# 2. Deploy /evaluate endpoint
scp openadapt_evals/server/waa_server_patch.py azureuser@vm:/tmp/
ssh azureuser@vm "python /tmp/waa_server_patch.py"

# 3. Run evaluation with all proper flags
uv run python -m openadapt_evals.benchmarks.cli live \
  --agent api-claude \
  --server http://$(az vm show --name waa-eval-vm --resource-group OPENADAPT-AGENTS --show-details --query publicIps -o tsv):5000 \
  --task-ids notepad_1 \
  --demo demo_library/synthetic_demos/notepad_1.txt \
  --waa-examples-path /path/to/WindowsAgentArena/evaluation_examples_windows

# 4. Generate viewer with embedded screenshots
uv run python -m openadapt_evals.benchmarks.cli view \
  --run-name waa-live_eval_$(date +%Y%m%d_%H%M%S) \
  --embed-screenshots

# 5. Open dashboard
python -m openadapt_evals.benchmarks.dashboard_server
# Navigate to: http://127.0.0.1:5555/benchmark/latest
```

### Expected Output

With proper setup, you should see:
- Model ID: "anthropic/claude-sonnet-4-5" (or similar)
- Success: true/false (actual determination)
- Instruction: Full task description
- Reasoning: Agent's thought process at each step
- Screenshots: Displayed correctly in viewer

---

## Directory Structure (For Reference)

```
benchmark_results/waa-live_eval_20260116_200004/
├── metadata.json          # ✅ Exists - benchmark config
├── summary.json           # ✅ Exists - aggregate results
├── viewer.html            # ✅ Exists - HTML viewer (screenshots broken when opened directly)
└── tasks/
    └── notepad_1/
        ├── task.json      # ✅ Exists - task definition
        ├── execution.json # ✅ Exists - execution trace
        └── screenshots/   # ✅ Exists - 5 PNG files
            ├── step_000.png (1280x720, valid PNG)
            ├── step_001.png (1280x720, valid PNG)
            ├── step_002.png (1280x720, valid PNG)
            ├── step_003.png (1280x720, valid PNG)
            └── step_004.png (1280x720, valid PNG)
```

---

## Recommendations

### Immediate Actions

1. **Use Dashboard Server**: Always view results via http://127.0.0.1:5555, not by opening HTML directly
2. **Specify Agent**: Always use `--agent api-claude` (or similar) to capture model_id
3. **Deploy /evaluate**: Add /evaluate endpoint to WAA server for proper success/fail evaluation

### Future Improvements

1. **Auto-detect Agent**: Infer model_id from environment variables if not specified
2. **Fallback Evaluation**: Implement client-side evaluators when server doesn't support /evaluate
3. **Better HTML Paths**: Generate absolute file:// URLs or auto-embed screenshots for standalone viewing
4. **Validation**: Add CLI warning if model_id is "unknown" before starting evaluation

---

## User Question: "I believe this is synthetic right, not the benchmark data?"

**Answer**: No, this is **REAL data from an actual WAA evaluation** (not synthetic).

**Why you might think it's synthetic**:
- ❌ Model ID shows "unknown" (looks like placeholder)
- ❌ Task instruction is generic "Task notepad_1" (not detailed)
- ❌ Screenshots broken in browser (suggests missing data)
- ❌ Evaluation failed (incomplete run)

**But it's actually real**:
- ✅ 5 valid PNG screenshots exist (1280x720 pixels each)
- ✅ Real timestamps from Jan 16, 2026 (71.89 seconds of execution)
- ✅ Benchmark type is "waa-live" (indicates live server, not mock)
- ✅ Real normalized action coordinates from agent

**The data is incomplete/poorly configured, but it's real.**

---

## Next Steps

1. Start dashboard server to view screenshots correctly
2. Re-run evaluation with proper flags (--agent, --waa-examples-path)
3. Deploy /evaluate endpoint to WAA server
4. Consider this run as "test data" and mark dashboard accordingly

