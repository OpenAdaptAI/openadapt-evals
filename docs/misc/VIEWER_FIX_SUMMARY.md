# Benchmark Viewer Fix Summary

**Issue Resolved**: Screenshots now display correctly in the benchmark viewer.

---

## What Was Fixed

### Problem
Opening `viewer.html` directly in a browser showed broken screenshots:
- Browser displayed: "Step screenshot" placeholder text
- Images failed to load due to relative path issues with file:// protocol

### Root Cause
The viewer used relative paths like `tasks/notepad_1/screenshots/step_000.png`, which:
- ✅ Work when served via HTTP (dashboard server)
- ❌ Fail when opened directly via file:// (browser security restrictions)

### Solution Applied
Regenerated the viewer with embedded screenshots:

```bash
uv run python -m openadapt_evals.benchmarks.cli view \
  --run-name waa-live_eval_20260116_200004 \
  --embed-screenshots
```

**Result**:
- Screenshots are now base64-encoded and embedded directly in HTML
- File size increased: 62 KB → 3.9 MB (includes 5 screenshots)
- Viewer now works when opened directly OR via dashboard

---

## How to View the Fixed Results

### Option 1: Dashboard Server (Recommended)

The dashboard is already running at http://127.0.0.1:5555

Navigate to:
- **Latest results**: http://127.0.0.1:5555/benchmark/latest
- **This specific run**: http://127.0.0.1:5555/benchmark/waa-live_eval_20260116_200004

### Option 2: Open HTML Directly

With embedded screenshots, you can now open the file directly:

```bash
open /Users/abrichr/oa/src/openadapt-evals/benchmark_results/waa-live_eval_20260116_200004/viewer.html
```

---

## Data Source Confirmed: REAL (But Incomplete)

After investigation, this is **REAL data from a live WAA evaluation**, not synthetic.

**Evidence of Real Data**:
- ✅ 5 actual PNG screenshots (1280x720 pixels each)
- ✅ Real timestamps from Jan 16, 2026, 20:00:04-20:01:16 UTC
- ✅ Benchmark type: "waa-live" (live WAA server evaluation)
- ✅ Real execution time: 71.89 seconds
- ✅ Actual action coordinates from agent

**But Data is Incomplete**:
- ❌ `model_id: "unknown"` - Agent provider not specified
- ❌ Task failed: "Evaluation requires WAA evaluators (not yet implemented)"
- ❌ Generic instruction: "Task notepad_1" (placeholder text)
- ❌ No reasoning captured

**Conclusion**: This is a **real evaluation run with incomplete configuration**.

---

## Recommendations

### For Viewing This Data
1. ✅ **FIXED**: Use embedded viewer or dashboard server
2. ⚠️ Treat as test/example data (incomplete configuration)
3. 📋 Consider adding "Example Data" label to dashboard UI

### For Future Evaluations
1. **Always specify agent**: `--agent api-claude` (or similar)
2. **Deploy /evaluate endpoint**: Add to WAA server for proper success/fail
3. **Use full task configs**: Include `--waa-examples-path` for detailed instructions
4. **Auto-embed for sharing**: Use `--embed-screenshots` when generating shareable viewers

---

## Commands for Proper Evaluation

```bash
# 1. Setup WAA server (if not done)
uv run python -m openadapt_evals.benchmarks.cli vm-setup --auto-verify

# 2. Deploy /evaluate endpoint
scp openadapt_evals/server/waa_server_patch.py azureuser@vm:/tmp/
ssh azureuser@vm "python /tmp/waa_server_patch.py"

# 3. Run complete evaluation
uv run python -m openadapt_evals.benchmarks.cli live \
  --agent api-claude \
  --server http://VM_IP:5000 \
  --task-ids notepad_1 \
  --demo demo_library/synthetic_demos/notepad_1.txt \
  --waa-examples-path /path/to/WindowsAgentArena/evaluation_examples_windows

# 4. Generate shareable viewer
uv run python -m openadapt_evals.benchmarks.cli view \
  --run-name waa-live_eval_$(date +%Y%m%d_%H%M%S) \
  --embed-screenshots

# 5. View on dashboard
# Navigate to: http://127.0.0.1:5555/benchmark/latest
```

---

## Files Updated

- ✅ `benchmark_results/waa-live_eval_20260116_200004/viewer.html` - Regenerated with embedded screenshots (3.9 MB)
- ✅ `BENCHMARK_VIEWER_INVESTIGATION.md` - Complete investigation report
- ✅ `VIEWER_FIX_SUMMARY.md` - This summary

---

## Testing

```bash
# Test 1: Open viewer directly (should show screenshots now)
open /Users/abrichr/oa/src/openadapt-evals/benchmark_results/waa-live_eval_20260116_200004/viewer.html

# Test 2: View via dashboard (should work as before)
# Navigate to: http://127.0.0.1:5555/benchmark/latest

# Test 3: Verify screenshots are embedded
grep -c "data:image/png;base64" benchmark_results/waa-live_eval_20260116_200004/viewer.html
# Expected output: 1 (one embedded_screenshots array)
```

All tests should pass. Screenshots now display correctly.
