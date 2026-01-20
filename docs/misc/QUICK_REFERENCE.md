# Quick Reference - Benchmark Viewer Issue

**TL;DR**: Screenshots are now fixed. Data is REAL (not synthetic) but incomplete. Use dashboard at http://127.0.0.1:5555/benchmark/latest

---

## Problem → Solution

| Problem | Solution | Status |
|---------|----------|--------|
| Screenshots show "Step screenshot" | Regenerated with embedded images | ✅ FIXED |
| "Is this synthetic data?" | No, it's REAL (but incomplete config) | ✅ CONFIRMED |
| Model ID shows "unknown" | Re-run with `--agent api-claude` | 📋 TODO |
| Evaluation failed | Deploy /evaluate endpoint to WAA | 📋 TODO |

---

## View Results Now

```bash
# Option 1: Dashboard (recommended)
# Open browser to: http://127.0.0.1:5555/benchmark/latest

# Option 2: Open HTML directly (now works with embedded screenshots)
open /Users/abrichr/oa/src/openadapt-evals/benchmark_results/waa-live_eval_20260116_200004/viewer.html
```

---

## Run Proper Evaluation

```bash
# Full working command:
uv run python -m openadapt_evals.benchmarks.cli live \
  --agent api-claude \
  --server http://VM_IP:5000 \
  --task-ids notepad_1 \
  --demo demo_library/synthetic_demos/notepad_1.txt \
  --waa-examples-path /path/to/WAA/evaluation_examples_windows

# Then generate shareable viewer:
uv run python -m openadapt_evals.benchmarks.cli view \
  --run-name waa-live_eval_$(date +%Y%m%d_%H%M%S) \
  --embed-screenshots
```

---

## What This Data Is

**REAL evaluation data** from Jan 16, 2026, but:
- ✅ Real screenshots (5 PNG files, 1280x720)
- ✅ Real timestamps (71.89 seconds execution)
- ✅ Real actions from agent
- ❌ Model ID unknown (--agent not specified)
- ❌ Evaluation failed (no /evaluate endpoint)
- ❌ Generic instruction (no task config)

**Label**: Incomplete Test Data

---

## Documentation

| File | Purpose |
|------|---------|
| `INVESTIGATION_COMPLETE.md` | Full summary (recommended read) |
| `BENCHMARK_VIEWER_INVESTIGATION.md` | Detailed investigation (60+ sections) |
| `VIEWER_FIX_SUMMARY.md` | Fix details and testing |
| `QUICK_REFERENCE.md` | This file - quick lookup |

---

## Key Commands

```bash
# View latest results
http://127.0.0.1:5555/benchmark/latest

# Regenerate viewer with embedded screenshots
uv run python -m openadapt_evals.benchmarks.cli view \
  --run-name RESULT_DIR_NAME --embed-screenshots

# Check dashboard status
curl http://127.0.0.1:5555/health

# Start dashboard if needed
python -m openadapt_evals.benchmarks.dashboard_server
```

---

## Next Steps

1. ✅ Screenshots fixed (embedded in HTML)
2. ✅ Data source confirmed (REAL, not synthetic)
3. 📋 Run proper evaluation with correct flags
4. 📋 Deploy /evaluate endpoint to WAA server
5. 📋 Consider adding "data quality" badges to dashboard UI

**Status**: Issue resolved. Ready for proper evaluation.
