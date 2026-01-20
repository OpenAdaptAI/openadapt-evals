# Demo Test Quick Start Guide

Fast reference for executing demo-conditioned prompting validation tests.

---

## TL;DR - Run Everything

```bash
# 1. Start VM and server
uv run python -m openadapt_evals.benchmarks.cli up

# 2. Run full test suite (3 runs each: baseline, treatment, negative control)
./scripts/run_demo_test.sh

# 3. View results
python scripts/analyze_demo_results.py
```

---

## Prerequisites Checklist

- [ ] VM is running: `uv run python -m openadapt_evals.benchmarks.cli vm-status`
- [ ] Server is ready: `uv run python -m openadapt_evals.benchmarks.cli probe --server http://172.171.112.41:5000`
- [ ] API key set: `echo $ANTHROPIC_API_KEY`
- [ ] Demo files exist: `ls demo_library/synthetic_demos/notepad_1.txt`

---

## Quick Commands

### Pilot Test (1 task, 1 run each)
```bash
./scripts/run_demo_test.sh --pilot
```

### Full Test (1 task, 3 runs each)
```bash
./scripts/run_demo_test.sh
```

### Custom Task
```bash
./scripts/run_demo_test.sh --task browser_5
```

### Skip Baseline (Already Have It)
```bash
./scripts/run_demo_test.sh --skip-baseline
```

### Analyze Results
```bash
python scripts/analyze_demo_results.py
python scripts/analyze_demo_results.py --export results.json
```

---

## Manual Execution (If Scripts Fail)

### Baseline (No Demo)
```bash
uv run python -m openadapt_evals.benchmarks.cli live \
  --agent api-claude \
  --server http://172.171.112.41:5000 \
  --task-ids notepad_1 \
  --max-steps 15 \
  --output-dir benchmark_results/baseline_run1
```

### Treatment (With Demo)
```bash
uv run python -m openadapt_evals.benchmarks.cli live \
  --agent api-claude \
  --demo demo_library/synthetic_demos/notepad_1.txt \
  --server http://172.171.112.41:5000 \
  --task-ids notepad_1 \
  --max-steps 15 \
  --output-dir benchmark_results/treatment_run1
```

### Negative Control (Wrong Demo)
```bash
uv run python -m openadapt_evals.benchmarks.cli live \
  --agent api-claude \
  --demo demo_library/synthetic_demos/browser_5.txt \
  --server http://172.171.112.41:5000 \
  --task-ids notepad_1 \
  --max-steps 15 \
  --output-dir benchmark_results/negative_run1
```

---

## View Results

### HTML Viewer
```bash
open benchmark_results/baseline_run1/viewer.html
open benchmark_results/treatment_run1/viewer.html
```

### JSON Summary
```bash
cat benchmark_results/baseline_run1/summary.json | jq
```

### Compare All
```bash
python scripts/analyze_demo_results.py
```

---

## Expected Results

| Scenario | Expected Success | Expected Steps |
|----------|-----------------|----------------|
| Baseline (no demo) | 0% | 5-7 |
| Treatment (with demo) | 50-80% | 7-9 |
| Negative (wrong demo) | 0-20% | Variable |

**Success Criteria**: Treatment success rate >50% AND better than baseline AND better than negative control.

---

## Troubleshooting

### Server Not Ready
```bash
# Check status
uv run python -m openadapt_evals.benchmarks.cli vm-status

# Restart
uv run python -m openadapt_evals.benchmarks.cli vm-stop
uv run python -m openadapt_evals.benchmarks.cli up
```

### Demo File Not Found
```bash
# Check demo exists
ls -l demo_library/synthetic_demos/notepad_1.txt

# Validate all demos
uv run python -m openadapt_evals.benchmarks.validate_demos --demo-dir demo_library/synthetic_demos
```

### Out of Money / API Quota
```bash
# Check costs
cat benchmark_results/*/summary.json | jq '.avg_time_seconds'

# Estimated cost per task: ~$0.50 (Claude API)
# Full test (9 runs): ~$4.50
```

---

## Next Steps After Testing

### If Success Rate >70%
✅ **Great!** Proceed to domain sampling:
```bash
./scripts/run_demo_test.sh --task notepad_1
./scripts/run_demo_test.sh --task browser_5
./scripts/run_demo_test.sh --task paint_1
./scripts/run_demo_test.sh --task office_3
```

### If Success Rate 40-70%
⚠️ **Good progress.** Investigate failures:
1. Review failed task screenshots
2. Check coordinate precision
3. Adjust demo if needed
4. Re-test

### If Success Rate <40%
❌ **Issues found.** Debug:
1. Verify demo persistence (check API logs)
2. Test with manual demo
3. Check for infrastructure issues
4. Review agent reasoning

---

## Full Documentation

- **Comprehensive Test Plan**: `DEMO_TEST_PLAN.md`
- **Demo Validation Analysis**: `DEMO_VALIDATION_ANALYSIS_REPORT.md`
- **Real Evaluation Results**: `REAL_EVALUATION_RESULTS.md`
- **Development Guidelines**: `CLAUDE.md`

---

## File Locations

```
openadapt-evals/
├── scripts/
│   ├── run_demo_test.sh              # Automated test runner
│   └── analyze_demo_results.py       # Results analysis
├── demo_library/synthetic_demos/     # 154 synthetic demos
│   ├── notepad_1.txt
│   ├── browser_5.txt
│   └── ...
├── benchmark_results/                # Test results
│   ├── baseline_run1/
│   ├── treatment_run1/
│   └── negative_run1/
├── DEMO_TEST_PLAN.md                 # Full test plan
└── DEMO_TEST_QUICKSTART.md           # This file
```

---

**Created**: January 18, 2026
**Status**: Ready to execute after WAA baseline validation
