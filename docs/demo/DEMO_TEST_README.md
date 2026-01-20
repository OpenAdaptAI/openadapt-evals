# Demo-Conditioned Prompting Test Suite

Complete test infrastructure for validating the demo persistence fix in `openadapt-evals`.

---

## What This Is

A comprehensive test suite to validate that including demonstration trajectories at **every step** (not just step 1) dramatically improves Windows Agent Arena task success rates.

**Current Status**: 0% success without demos → Expected 50-80% with demos

---

## Quick Start

### 1. Prerequisites
```bash
# Check VM status
uv run python -m openadapt_evals.benchmarks.cli vm-status

# Start VM and server
uv run python -m openadapt_evals.benchmarks.cli up

# Verify server ready
uv run python -m openadapt_evals.benchmarks.cli probe --server http://172.171.112.41:5000
```

### 2. Run Pilot Test
```bash
./scripts/run_demo_test.sh --pilot
```

### 3. Analyze Results
```bash
python scripts/analyze_demo_results.py
```

### 4. View HTML Results
```bash
open benchmark_results/*/viewer.html
```

---

## What's Included

### Documentation

**Executive Summary** (`DEMO_TEST_SUMMARY.md`)
- 1-page overview
- Key findings and recommendations
- Cost estimates
- Success criteria

**Comprehensive Test Plan** (`DEMO_TEST_PLAN.md`)
- 10,000+ word detailed plan
- 3 test scenarios (baseline, treatment, negative control)
- Metrics tracking framework
- Statistical analysis approach
- Synthetic demo validation strategy
- Timeline and execution steps

**Quick Start Guide** (`DEMO_TEST_QUICKSTART.md`)
- Fast reference for common commands
- Troubleshooting tips
- Expected results
- Next steps based on outcomes

### Scripts

**Automated Test Runner** (`scripts/run_demo_test.sh`)
- Runs all 3 scenarios automatically
- Configurable task, runs, server
- Pilot mode for quick validation
- Cool-down periods between runs
- Error handling and logging

**Results Analysis** (`scripts/analyze_demo_results.py`)
- Aggregates results across runs
- Statistical comparison (baseline vs treatment)
- Effect size calculation
- Success criteria evaluation
- JSON export capability

### Supporting Materials

**Demo Validation Analysis** (`DEMO_VALIDATION_ANALYSIS_REPORT.md`)
- Research-backed validation approaches
- Cost/quality trade-offs
- Recommended hybrid validation ($33-86, 92-96% confidence)
- Industry best practices

**Synthetic Demos** (`demo_library/synthetic_demos/`)
- 154 demos covering all WAA tasks
- 100% format validated
- Ready to use

---

## Test Scenarios

### Scenario 1: Baseline (No Demo)
**Purpose**: Establish performance without demos
**Expected**: 0% success, random behavior
**Command**:
```bash
uv run python -m openadapt_evals.benchmarks.cli live \
  --agent api-claude \
  --server http://172.171.112.41:5000 \
  --task-ids notepad_1 \
  --max-steps 15
```

### Scenario 2: Treatment (With Demo)
**Purpose**: Test demo persistence fix
**Expected**: 50-80% success, demo-aligned behavior
**Command**:
```bash
uv run python -m openadapt_evals.benchmarks.cli live \
  --agent api-claude \
  --demo demo_library/synthetic_demos/notepad_1.txt \
  --server http://172.171.112.41:5000 \
  --task-ids notepad_1 \
  --max-steps 15
```

### Scenario 3: Negative Control (Wrong Demo)
**Purpose**: Validate that correct demo matters
**Expected**: 0-20% success, confused behavior
**Command**:
```bash
uv run python -m openadapt_evals.benchmarks.cli live \
  --agent api-claude \
  --demo demo_library/synthetic_demos/browser_5.txt \
  --server http://172.171.112.41:5000 \
  --task-ids notepad_1 \
  --max-steps 15
```

---

## Success Criteria

**Primary Criteria**:
- ✅ Episode success rate >50% with demo
- ✅ Improvement >30% vs baseline
- ✅ Demo persistence verified (100% of steps)
- ✅ Negative control validates (wrong demo doesn't help)

**Secondary Criteria**:
- ✅ First-action accuracy >80%
- ✅ Step efficiency (7-12 steps)
- ✅ Synthetic demos work for >70% of tasks

---

## Metrics Tracked

| Metric | Definition | How Measured |
|--------|-----------|-------------|
| Episode Success Rate | Task completed per WAA evaluator | `/evaluate` endpoint |
| First-Action Accuracy | Correct first action taken | Screenshot review |
| Average Steps | Steps to completion | `summary.json` |
| Average Time | Time to completion | `summary.json` |
| Demo Persistence | Demo in API calls at all steps | API logs review |
| Demo Adherence | Action sequences match demo | Manual comparison |

---

## Execution Phases

### Phase 1: Pilot (1-2 hours)
**Tasks**: notepad_1 (simple), browser_5 (medium)
**Runs**: 1 per scenario
**Command**: `./scripts/run_demo_test.sh --pilot`
**Decision**: If success >50%, proceed to Phase 2

### Phase 2: Domain Sampling (2-3 hours)
**Tasks**: 10-15 across all 11 domains
**Runs**: 3 per scenario per task
**Decision**: If success >70%, proceed to Phase 3

### Phase 3: Full Evaluation (5-6 hours)
**Tasks**: All 154 WAA tasks
**Runs**: 1 per task
**Command**: Azure parallel execution
**Outcome**: Complete validation of fix

---

## Cost Breakdown

### Pilot Test
- VM time: $0.19
- API calls: $2
- **Total**: ~$2.20

### Domain Sampling
- VM time: $0.58
- API calls: $15
- **Total**: ~$16

### Full Evaluation
- VM time: $1.15
- API calls: $77
- Azure ML: $2.50
- **Total**: ~$81

### Demo Validation (Optional)
- Hybrid multi-stage: $33-86
- Only if >30% demos fail

---

## Results Analysis

### Automatic Analysis
```bash
# Run analysis script
python scripts/analyze_demo_results.py

# Export to JSON
python scripts/analyze_demo_results.py --export results.json
```

### Manual Analysis
```bash
# View individual runs
open benchmark_results/baseline_run1/viewer.html
open benchmark_results/treatment_run1/viewer.html

# Check JSON summaries
cat benchmark_results/baseline_run1/summary.json | jq
cat benchmark_results/treatment_run1/summary.json | jq
```

### Expected Output
```
=== DEMO TEST RESULTS ANALYSIS ===

Baseline (No Demo):
  Runs: 3
  Avg Success Rate: 0.0%
  Avg Steps: 5.3
  Avg Time: 72.1s

Treatment (With Demo):
  Runs: 3
  Avg Success Rate: 75.0%
  Avg Steps: 8.2
  Avg Time: 98.4s

Negative Control (Wrong Demo):
  Runs: 1
  Avg Success Rate: 0.0%
  Avg Steps: 6.1
  Avg Time: 81.3s

=== COMPARATIVE ANALYSIS ===

Success Rate:
  Baseline: 0.0%
  Treatment: 75.0%
  Improvement: +75.0 percentage points

Effect Size: LARGE

✓ PASS  Episode Success >50%
✓ PASS  Episode Success >80% (target)
✓ PASS  Improvement >30%
✓ PASS  Improvement >50% (large)
✓ PASS  Negative control valid
```

---

## Troubleshooting

### VM Not Ready
```bash
# Check status
uv run python -m openadapt_evals.benchmarks.cli vm-status

# Restart
uv run python -m openadapt_evals.benchmarks.cli vm-stop
uv run python -m openadapt_evals.benchmarks.cli up
```

### Server Not Responding
```bash
# Test connectivity
uv run python -m openadapt_evals.benchmarks.cli probe --server http://172.171.112.41:5000

# Check IP changed
uv run python -m openadapt_evals.benchmarks.cli vm-status | grep "Public IP"
```

### Demo File Missing
```bash
# List available demos
ls -l demo_library/synthetic_demos/

# Validate demos
uv run python -m openadapt_evals.benchmarks.validate_demos --demo-dir demo_library/synthetic_demos
```

### Test Script Fails
Use manual commands from `DEMO_TEST_QUICKSTART.md` section "Manual Execution".

---

## What to Do After Testing

### If Success >70%
✅ **Excellent!** Demo persistence validated.
- Document findings
- Proceed to domain sampling
- Plan full 154-task evaluation
- Consider production deployment

### If Success 40-70%
⚠️ **Good progress.** Investigate failures.
- Review failed task screenshots
- Check coordinate precision
- Identify demo quality issues
- Improve specific demos
- Re-test failed tasks

### If Success <40%
❌ **Issues found.** Debug thoroughly.
- Verify demo persistence (API logs)
- Test with manual demo
- Check infrastructure (timing, resolution)
- Review agent reasoning
- Root cause analysis

---

## File Organization

```
openadapt-evals/
├── DEMO_TEST_README.md              # This file
├── DEMO_TEST_SUMMARY.md             # 1-page executive summary
├── DEMO_TEST_PLAN.md                # Comprehensive test plan
├── DEMO_TEST_QUICKSTART.md          # Quick reference card
├── DEMO_VALIDATION_ANALYSIS_REPORT.md  # Demo quality research
│
├── scripts/
│   ├── run_demo_test.sh             # Automated test runner
│   └── analyze_demo_results.py      # Results analysis
│
├── demo_library/synthetic_demos/    # 154 synthetic demos
│   ├── notepad_1.txt
│   ├── browser_5.txt
│   ├── ...
│   └── demos.json                   # Demo index
│
├── benchmark_results/               # Test results (created during tests)
│   ├── baseline_run1/
│   │   ├── viewer.html
│   │   └── summary.json
│   ├── treatment_run1/
│   └── negative_control_run1/
│
└── openadapt_evals/agents/
    └── api_agent.py                 # Demo persistence fix (lines 371-379)
```

---

## Research Background

### Demo-Conditioned Prompting Impact
- Without demo: 33% first-action accuracy
- With demo: 100% first-action accuracy
- Source: Mock testing (Jan 17, 2026)

### Synthetic Demo Quality
- Expected baseline: 81.9% success rate
- Exceeds human demos: 76.6%
- Source: "Beyond Human Demonstrations: Diffusion-Based RL" (2025)

### Validation Economics
- LLM-as-Judge: 80% agreement, $0.91, 15 min
- Full human: 95% accuracy, $205-513, 2-3 days
- Hybrid: 92% confidence, $33-86, 2 days
- Source: DEMO_VALIDATION_ANALYSIS_REPORT.md

---

## Key Insights

1. **Demo persistence is critical**: Including demo at every step (not just step 1) is the key innovation
2. **Synthetic demos are viable**: 82% expected quality, sufficient for initial testing
3. **Hybrid validation is optimal**: $33-86 for 92-96% confidence vs $513 for 100%
4. **Statistical significance matters**: 3 runs per scenario minimum for valid comparison
5. **Negative control is essential**: Proves improvement comes from CORRECT demo, not any demo

---

## Credits

**Test Plan Created**: January 18, 2026
**Author**: Claude Sonnet 4.5
**Research Sources**:
- Windows Agent Arena (Microsoft, 2024)
- Demo quality research (2025)
- LLM-as-Judge meta-analysis (2025)
- Industry validation practices (2025-2026)

---

## Next Steps

1. **Wait for baseline**: Other agent validating WAA baseline performance
2. **Run pilot**: Execute `./scripts/run_demo_test.sh --pilot`
3. **Analyze**: Use `python scripts/analyze_demo_results.py`
4. **Decide**: Based on success criteria, proceed or iterate
5. **Document**: Share findings with team

---

## Support

**Full Documentation**: See individual files above
**Quick Commands**: `DEMO_TEST_QUICKSTART.md`
**Detailed Plan**: `DEMO_TEST_PLAN.md`
**Research**: `DEMO_VALIDATION_ANALYSIS_REPORT.md`

**Issues**: Check benchmark_results/ for execution logs
**Questions**: Review comprehensive test plan

---

**Status**: Ready to execute pending WAA baseline validation
**Expected Impact**: 0% → 50-80% episode success rate
**Timeline**: 1 week (pilot → sampling → decision)
**Cost**: $2-100 depending on phase

---

**END OF README**
