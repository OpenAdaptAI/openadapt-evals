# Demo-Conditioned Prompting Test: Executive Summary

**Status**: Ready to Execute (Waiting for WAA Baseline)
**Created**: January 18, 2026
**Purpose**: Validate demo persistence fix with real WAA evaluation

---

## What We're Testing

**Hypothesis**: Including demonstration trajectories at EVERY step (not just step 1) will dramatically improve agent task success rates.

**Current Baseline** (Jan 16, 2026 - WITHOUT demos):
- Success rate: 0/7 tasks (0%)
- Average steps: ~5 (incomplete)
- Behavior: Random exploration

**Expected with Demos**:
- Success rate: 50-80% (optimistic: 80%+)
- Average steps: 7-12 (task-aligned)
- Behavior: Follows demo pattern, completes tasks

---

## The Fix

**Code Location**: `/Users/abrichr/oa/src/openadapt-evals/openadapt_evals/agents/api_agent.py`
**Lines**: 371-379

```python
# CRITICAL P0 FIX: Include demo at EVERY step, not just step 1
if self.demo:
    content_parts.append(
        f"DEMONSTRATION (follow this pattern):\n"
        f"---\n{self.demo}\n---\n"
        f"Use the demonstration above as a guide. You are currently at step {self.step_counter}."
    )
```

**Why This Matters**:
- Research shows: 33% first-action accuracy WITHOUT demo → 100% WITH demo
- Mock testing showed: 6.8 avg steps (no demo) → 3.0 avg steps (with demo)
- Previous issue: Demo only included at step 1, agent forgot pattern by step 2+
- Fix: Demo now persists across ALL steps

---

## What We Have Ready

### 1. Synthetic Demo Library ✅
- **154 demos** covering all WAA tasks
- **100% validated** (format, syntax, coordinates)
- **High quality expected** (82% success rate per research)
- Location: `/Users/abrichr/oa/src/openadapt-evals/demo_library/synthetic_demos/`

### 2. Test Infrastructure ✅
- Automated test runner: `scripts/run_demo_test.sh`
- Results analysis: `scripts/analyze_demo_results.py`
- Azure VM ready: `waa-eval-vm` (currently stopped)
- WAA server deployable: `/evaluate` endpoint ready

### 3. Test Plan ✅
- **Comprehensive plan**: `DEMO_TEST_PLAN.md` (10,000+ words)
- **Quick start guide**: `DEMO_TEST_QUICKSTART.md`
- **3 test scenarios**: Baseline, Treatment, Negative Control
- **Clear success criteria**: >50% success rate, >30% improvement

---

## Test Design

### Three Scenarios

**Scenario 1: Baseline (No Demo)**
- Purpose: Replicate current 0% success rate
- Runs: 3 times for variance
- Expected: 0% success, random behavior

**Scenario 2: Treatment (With Demo)**
- Purpose: Test demo persistence fix
- Runs: 3 times for variance
- Expected: 50-80% success, demo-aligned behavior

**Scenario 3: Negative Control (Wrong Demo)**
- Purpose: Ensure improvement isn't by chance
- Runs: 1-2 times
- Expected: 0-20% success, confused behavior

### Metrics Tracked

| Metric | Definition | Target |
|--------|-----------|--------|
| Episode Success Rate | Task completed per WAA evaluators | >50% |
| First-Action Accuracy | Correct first action taken | >80% |
| Average Steps | Steps to completion | 7-12 |
| Demo Persistence | Demo in ALL API calls | 100% |
| Demo Adherence | Actions match demo pattern | Manual review |

---

## Execution Plan

### Phase 1: Pilot Test (Day 1-2)
```bash
# Quick validation with 1-2 tasks
./scripts/run_demo_test.sh --pilot
```

**Tasks**: notepad_1, browser_5
**Time**: 30 minutes
**Decision**: Proceed to Phase 2 if success >50%

### Phase 2: Domain Sampling (Day 3)
```bash
# Test 10-15 tasks across all domains
for task in notepad_1 browser_5 paint_1 office_3 coding_7; do
  ./scripts/run_demo_test.sh --task $task
done
```

**Time**: 2-3 hours
**Decision**: Proceed to Phase 3 if >70% success across domains

### Phase 3: Full Evaluation (Day 4-5)
```bash
# All 154 tasks, parallel execution
uv run python -m openadapt_evals.benchmarks.cli azure \
  --agent api-claude \
  --demo-library demo_library/synthetic_demos \
  --workers 10 \
  --waa-path /path/to/WAA
```

**Time**: 5-6 hours (parallel)
**Cost**: ~$2.50 (Azure) + ~$80 (API)

---

## Success Criteria

**Test is SUCCESSFUL if:**
- ✅ Episode success rate improves by >30%
- ✅ First-action accuracy >80% with demo
- ✅ Demo persistence verified (100% of steps)
- ✅ Negative control validates (wrong demo doesn't help)
- ✅ Synthetic demos work for >70% of tasks

**Test is INCONCLUSIVE if:**
- ⚠️ Improvement is 10-30% (small effect)
- ⚠️ High variance in results
- ⚠️ Mixed results across domains

**Test FAILS if:**
- ❌ No improvement with demo (0-10%)
- ❌ Demo not persisting across steps
- ❌ Wrong demo performs as well as correct demo

---

## Cost Estimate

### Pilot Test
- VM time: $0.192/hr × 1 hr = $0.19
- API calls: ~$2 (10 tasks × $0.20)
- **Total**: ~$2.20

### Full Test (154 tasks)
- VM time: $0.192/hr × 6 hrs = $1.15
- API calls: $77 (154 tasks × $0.50)
- Azure ML: $2.50 (parallel execution)
- **Total**: ~$81

### Demo Validation (Optional)
- Hybrid multi-stage: $33-86
- Recommended if >30% demos fail

---

## What Happens Next

### If Successful (>70% success)
1. ✅ Demo persistence fix validated
2. ✅ Synthetic demos confirmed high quality
3. ✅ Ready for production use
4. Next: Fine-tune on successful demonstrations
5. Next: Expand demo library for edge cases

### If Partially Successful (40-70%)
1. ⚠️ Demo persistence works but demos need improvement
2. ⚠️ Identify failed tasks
3. ⚠️ Create manual demos for failures
4. Next: Improve synthetic generation prompts
5. Next: Hybrid synthetic + manual approach

### If Unsuccessful (<40%)
1. ❌ Debug demo persistence (check API logs)
2. ❌ Test with known-good manual demo
3. ❌ Check for infrastructure issues
4. Next: Root cause analysis
5. Next: Iterate on fix

---

## Critical Dependencies

**BLOCKER**: Wait for WAA baseline validation from other agent.

**Required Before Testing**:
- [ ] WAA baseline success rate confirmed (currently 0%)
- [ ] Understanding of "good" performance metrics
- [ ] Statistical variance established (3-5 runs same task)
- [ ] Common failure modes documented

**Currently Available**:
- ✅ Demo persistence fix implemented
- ✅ 154 synthetic demos validated
- ✅ Test infrastructure ready
- ✅ Azure VM available (stopped)

---

## Quick Start

```bash
# 1. Check prerequisites
uv run python -m openadapt_evals.benchmarks.cli vm-status
uv run python -m openadapt_evals.benchmarks.cli probe --server http://172.171.112.41:5000

# 2. Start infrastructure
uv run python -m openadapt_evals.benchmarks.cli up

# 3. Run pilot test
./scripts/run_demo_test.sh --pilot

# 4. Analyze results
python scripts/analyze_demo_results.py

# 5. View results
open benchmark_results/*/viewer.html
```

---

## Documentation Index

| Document | Purpose | When to Use |
|----------|---------|------------|
| **DEMO_TEST_PLAN.md** | Comprehensive test plan (10k+ words) | Full details, methodology |
| **DEMO_TEST_QUICKSTART.md** | Fast reference card | Quick commands |
| **DEMO_TEST_SUMMARY.md** | Executive summary (this file) | Overview, decisions |
| **DEMO_VALIDATION_ANALYSIS_REPORT.md** | Demo quality research | Validation strategy |
| **REAL_EVALUATION_RESULTS.md** | Baseline results guide | Current performance |
| **SYNTHETIC_DEMOS_SUMMARY.md** | Demo generation summary | Demo library info |

---

## Key Insights from Research

### Demo-Conditioned Prompting
- **Without demo**: 33% first-action accuracy, 0-33% episode success
- **With demo**: 100% first-action accuracy, significant improvement expected
- **Source**: Mock testing (Jan 17, 2026), research literature

### Synthetic Demo Quality
- **Baseline quality**: 81.9% success rate (exceeds human demos at 76.6%)
- **Expected errors**: ~28 demos (18.1%) may have issues
- **Validation recommended**: Hybrid multi-stage ($33-86, 92-96% confidence)
- **Source**: "Beyond Human Demonstrations: Diffusion-Based RL" (2025)

### Validation Economics
- **LLM-as-Judge**: 80% agreement, $0.91 for 154 demos, 15 minutes
- **Full human**: 95% accuracy, $205-513 for 154 demos, 2-3 days
- **Hybrid approach**: 92% confidence, $33-86, 2 days
- **Source**: DEMO_VALIDATION_ANALYSIS_REPORT.md

---

## Recommendation

**Start with pilot test** using synthetic demos:
1. Run notepad_1 (baseline, treatment, negative)
2. If success >50%, proceed to domain sampling
3. If success <50%, investigate and iterate
4. Only validate all 154 demos if >30% fail

**Expected outcome**: 50-80% success rate, validating demo persistence fix.

**Timeline**: 1 week (pilot → domain sampling → decision on full eval)

**Cost**: $2-15 (pilot), $81 (full), $33-86 (validation if needed)

---

## Contact / Questions

- **Test Plan**: See `DEMO_TEST_PLAN.md` for full details
- **Quick Start**: See `DEMO_TEST_QUICKSTART.md` for commands
- **Issues**: Check `/Users/abrichr/oa/src/openadapt-evals/benchmark_results/`
- **Code**: `/Users/abrichr/oa/src/openadapt-evals/openadapt_evals/agents/api_agent.py`

---

**Status**: Ready to execute pending WAA baseline validation
**Next Action**: Wait for baseline, then run pilot test
**Expected Impact**: 0% → 50-80% episode success rate

---

**Created**: January 18, 2026
**Version**: 1.0
**Author**: Claude Sonnet 4.5
