# Comprehensive Test Plan: Demo-Conditioned Prompting Validation

**Date**: January 18, 2026
**Status**: Ready to Execute (Waiting for WAA Baseline)
**Target**: Validate demo persistence fix with real WAA evaluation
**Expected Impact**: 0% baseline → significant improvement in episode success rate

---

## Executive Summary

This test plan validates the demo-conditioned prompting fix in `openadapt-evals` which ensures demonstrations are included at EVERY step (not just step 1). Mock testing showed behavioral change (6.8 avg steps → 3.0 avg steps), and we now need real WAA validation.

**Critical Dependencies**:
- ✅ Demo persistence fix implemented (api_agent.py lines 371-379)
- ✅ 154 synthetic demos generated and validated
- ⏳ WAA baseline needed (currently 0% success from Jan 16 evals)
- ⏳ Understanding of "good" performance metrics

---

## Part 1: Baseline Establishment (Reference Other Agent's Work)

### 1.1 Wait for Vanilla WAA Baseline

**DO NOT** proceed with demo testing until baseline is established.

**Required Baseline Metrics**:
- Success rate on notepad tasks (simple)
- Success rate on browser tasks (medium)
- Success rate on office tasks (complex)
- Average steps to completion
- Average time per task
- Common failure modes

**Baseline Status** (as of Jan 18, 2026):
```
Current Results (Jan 16, 2026 - WITHOUT demos):
- 7 evaluations run
- 0/7 success rate (0%)
- All single-task evaluations (notepad_1)
- Average ~5 steps per attempt
- Tasks incomplete

Location: /Users/abrichr/oa/src/openadapt-evals/benchmark_results/waa-live_eval_20260116_*
```

**What We Need**:
1. Confirmed baseline success rate across task types
2. Understanding of typical failure patterns
3. Established performance "floor"
4. Statistical variance (run same task 3-5 times)

**Action**: Wait for other agent to complete baseline validation before proceeding.

---

## Part 2: Demo Test Design

### 2.1 Task Selection Strategy

#### Phase 1: Pilot Test (1-2 tasks)
Start small to validate the approach before scaling.

**Recommended Pilot Tasks**:

| Task ID | Domain | Complexity | Steps | Why Selected |
|---------|--------|-----------|-------|--------------|
| `notepad_1` | notepad | Simple | 7 | Baseline already exists, quick to run |
| `browser_5` | browser | Medium | 10 | Tests multi-step navigation |

**Alternative**: `paint_1` (simple drawing task, visual validation)

#### Phase 2: Domain Sampling (10-15 tasks)
After pilot success, test across all domains.

**Stratified Sample**:
- **Simple** (4-7 steps): 4 tasks (notepad_1, paint_1, clock_1, media_1)
- **Medium** (8-15 steps): 6 tasks (browser_5, file_explorer_3, settings_2, edge_2, vscode_1, coding_2)
- **Complex** (16-24 steps): 4 tasks (office_5, coding_10, browser_15, file_explorer_12)

**Total**: 14 tasks covering all 11 domains

#### Phase 3: Full Evaluation (154 tasks)
After domain sampling validates the approach.

**Configuration**:
```bash
# Azure parallel evaluation with all tasks
uv run python -m openadapt_evals.benchmarks.cli azure \
    --agent api-claude \
    --demo-library demo_library/synthetic_demos \
    --workers 10 \
    --waa-path /path/to/WAA \
    --max-steps 15
```

### 2.2 Demo Selection Strategy

#### Option A: Synthetic Demos (Recommended for Initial Test)

**Pros**:
- All 154 tasks have corresponding demos
- Consistent quality (validated)
- Immediate availability
- Reproducible

**Cons**:
- Not tested in real execution
- May have coordinate precision issues
- Synthetic nature (no visual verification)

**Quality Assessment** (from DEMO_VALIDATION_ANALYSIS_REPORT.md):
- Expected baseline quality: 82% (research-backed)
- Format validation: 154/154 pass (100%)
- Recommended validation: Hybrid multi-stage ($33-86, 2 days)

**Decision**: Start with synthetic demos, identify failures, improve as needed.

#### Option B: Manual Demos (Future Enhancement)

**Use Cases**:
- Synthetic demo fails repeatedly
- Complex multi-app workflows
- Edge cases not captured by generation

**Process**:
1. Record manual demo using OpenAdapt
2. Convert to text format
3. Validate and test
4. Replace synthetic version

**Timeline**: 10-15 min per demo (manual recording + conversion)

### 2.3 Measurement Framework

#### Primary Metrics

**Episode Success Rate**:
- Definition: Task completed successfully per WAA evaluators
- Current baseline: 0%
- Target improvement: >50% (conservative), >80% (optimistic)
- Measurement: WAA native `/evaluate` endpoint

**First-Action Accuracy**:
- Definition: Agent takes correct first action
- Research baseline (without demo): 33%
- Research baseline (with demo): 100%
- Measurement: Manual review of step 1 screenshots

**Average Steps to Completion**:
- Current baseline: ~5 steps (incomplete tasks)
- Expected with demo: 7-12 steps (task-dependent)
- Indicates agent efficiency

**Time to Completion**:
- Current baseline: ~71.89 seconds (incomplete)
- Expected with demo: Task-dependent (correlates with step count)

#### Secondary Metrics

**Demo Adherence**:
- How closely agent follows demo pattern
- Measured by comparing action sequences
- Manual review of execution logs

**Coordinate Precision**:
- Are click coordinates accurate?
- Do actions land on intended targets?
- Screenshot analysis

**Reasoning Quality**:
- Does agent reasoning match demo reasoning?
- Extraction from API logs

**Error Recovery**:
- How does agent handle deviations?
- Does demo help recover from errors?

---

## Part 3: Test Scenarios

### 3.1 Scenario 1: Without Demo (Baseline Control)

**Purpose**: Replicate baseline to confirm consistent behavior

**Configuration**:
```bash
uv run python -m openadapt_evals.benchmarks.cli live \
    --agent api-claude \
    --server http://172.171.112.41:5000 \
    --task-ids notepad_1 \
    --max-steps 15 \
    --output-dir benchmark_results/baseline_without_demo
```

**Expected Results** (based on Jan 16 evals):
- Success rate: 0%
- Avg steps: 5-7
- Behavior: Random exploration, no task completion

**Run Count**: 3 times to establish variance

### 3.2 Scenario 2: With Demo (Treatment)

**Purpose**: Test demo persistence fix

**Configuration**:
```bash
uv run python -m openadapt_evals.benchmarks.cli live \
    --agent api-claude \
    --demo demo_library/synthetic_demos/notepad_1.txt \
    --server http://172.171.112.41:5000 \
    --task-ids notepad_1 \
    --max-steps 15 \
    --output-dir benchmark_results/with_demo
```

**Expected Results**:
- Success rate: 50-100% (optimistic: 80%+)
- Avg steps: 7-9 (demo has 7 steps)
- Behavior: Follows demo pattern, completes task

**Run Count**: 3 times to establish variance

**Validation Checks**:
1. Demo included in API logs at EVERY step
2. Agent actions match demo pattern
3. Task completed successfully per WAA evaluator

### 3.3 Scenario 3: With Wrong Demo (Negative Control)

**Purpose**: Ensure agent isn't succeeding by chance

**Configuration**:
```bash
# Use browser_5 demo for notepad_1 task (deliberate mismatch)
uv run python -m openadapt_evals.benchmarks.cli live \
    --agent api-claude \
    --demo demo_library/synthetic_demos/browser_5.txt \
    --server http://172.171.112.41:5000 \
    --task-ids notepad_1 \
    --max-steps 15 \
    --output-dir benchmark_results/wrong_demo
```

**Expected Results**:
- Success rate: 0-20% (agent confused by wrong pattern)
- Avg steps: Variable (agent tries to reconcile demo with task)
- Behavior: Confusion, may attempt browser actions in notepad context

**Run Count**: 1-2 times (negative control)

**Purpose**: Validates that improvement comes from CORRECT demo, not just having any demo.

### 3.4 Scenario 4: Retrieval-Augmented Agent (Advanced)

**Purpose**: Test automatic demo selection

**Configuration**:
```bash
uv run python -m openadapt_evals.benchmarks.cli live \
    --agent retrieval-claude \
    --demo-library demo_library/synthetic_demos \
    --server http://172.171.112.41:5000 \
    --task-ids notepad_1,browser_5,paint_1 \
    --max-steps 15 \
    --output-dir benchmark_results/retrieval_agent
```

**Expected Results**:
- Similar to Scenario 2 if retrieval is accurate
- Check: Does agent select correct demo?
- Metric: Retrieval accuracy (correct demo selected?)

**Run Count**: 3-5 tasks

### 3.5 Metrics Tracking Matrix

| Scenario | Success Rate | Avg Steps | Time | Demo Adherence | Notes |
|----------|-------------|-----------|------|----------------|-------|
| 1. No Demo | 0% | 5-7 | ~72s | N/A | Baseline |
| 2. With Demo | ?% | ? | ? | ? | Treatment |
| 3. Wrong Demo | ?% | ? | ? | ? | Negative control |
| 4. Retrieval | ?% | ? | ? | ? | Advanced |

Fill in during execution.

---

## Part 4: Test Execution Plan

### 4.1 Pre-Execution Checklist

**Infrastructure**:
- [ ] Azure VM running (`waa-eval-vm`)
- [ ] WAA server started and responsive
- [ ] Server IP confirmed: `http://172.171.112.41:5000`
- [ ] `/evaluate` endpoint deployed on WAA server
- [ ] API keys set: `ANTHROPIC_API_KEY`

**Code**:
- [ ] Latest code pulled from main branch
- [ ] Demo persistence fix verified (api_agent.py:371-379)
- [ ] Synthetic demos validated (154/154 pass)
- [ ] Baseline results reviewed

**Verification Commands**:
```bash
# Check VM status
uv run python -m openadapt_evals.benchmarks.cli vm-status

# Test server connectivity
uv run python -m openadapt_evals.benchmarks.cli probe --server http://172.171.112.41:5000

# Verify demo files exist
ls -l demo_library/synthetic_demos/notepad_1.txt

# Check API key
echo $ANTHROPIC_API_KEY | head -c 10
```

### 4.2 Step-by-Step Execution

#### Step 1: Start Infrastructure

```bash
# Start VM and WAA server (all-in-one command)
uv run python -m openadapt_evals.benchmarks.cli up

# Wait for server ready (probe until success)
uv run python -m openadapt_evals.benchmarks.cli probe --server http://172.171.112.41:5000
```

**Expected Output**:
```
VM waa-eval-vm started successfully
Waiting for VM to boot (180s)...
Starting WAA server...
Server is ready: http://172.171.112.41:5000
```

#### Step 2: Run Baseline (Scenario 1)

```bash
# Run without demo (3 times for variance)
for i in {1..3}; do
  uv run python -m openadapt_evals.benchmarks.cli live \
    --agent api-claude \
    --server http://172.171.112.41:5000 \
    --task-ids notepad_1 \
    --max-steps 15 \
    --output-dir benchmark_results/baseline_no_demo_run${i}

  sleep 30  # Cool-down between runs
done
```

**Expected Duration**: 3 × 2 min = 6 minutes

**Validation**:
- Check 3 result directories created
- Verify success rate is 0% (baseline)
- Review screenshots for random behavior

#### Step 3: Run Treatment (Scenario 2)

```bash
# Run with correct demo (3 times for variance)
for i in {1..3}; do
  uv run python -m openadapt_evals.benchmarks.cli live \
    --agent api-claude \
    --demo demo_library/synthetic_demos/notepad_1.txt \
    --server http://172.171.112.41:5000 \
    --task-ids notepad_1 \
    --max-steps 15 \
    --output-dir benchmark_results/with_demo_run${i}

  sleep 30
done
```

**Expected Duration**: 3 × 2 min = 6 minutes

**Validation**:
- Check API logs for demo inclusion at EVERY step
- Compare action sequences to demo
- Check success rate (should be >0%)

#### Step 4: Run Negative Control (Scenario 3)

```bash
# Run with wrong demo
uv run python -m openadapt_evals.benchmarks.cli live \
  --agent api-claude \
  --demo demo_library/synthetic_demos/browser_5.txt \
  --server http://172.171.112.41:5000 \
  --task-ids notepad_1 \
  --max-steps 15 \
  --output-dir benchmark_results/wrong_demo
```

**Expected Duration**: 2 minutes

**Validation**:
- Success should be low (0-20%)
- Agent should show confusion in logs

#### Step 5: Analyze Results

```bash
# Generate comparison viewer
uv run python -m openadapt_evals.benchmarks.cli view \
  --run-name baseline_no_demo_run1 \
  --run-name with_demo_run1 \
  --run-name wrong_demo

# Open viewers
open benchmark_results/baseline_no_demo_run1/viewer.html
open benchmark_results/with_demo_run1/viewer.html
open benchmark_results/wrong_demo/viewer.html
```

**Analysis**:
1. Compare success rates
2. Review step-by-step execution
3. Check coordinate accuracy
4. Identify failure patterns

#### Step 6: Stop Infrastructure

```bash
# Stop VM to save costs
uv run python -m openadapt_evals.benchmarks.cli vm-stop
```

### 4.3 Data Collection Script

Create automated collection:

```bash
#!/bin/bash
# demo_test_collection.sh

set -e

echo "=== Demo Test Collection Script ==="
echo "Starting at $(date)"

# Configuration
SERVER="http://172.171.112.41:5000"
TASK="notepad_1"
RUNS=3

# 1. Start infrastructure
echo "Starting VM and server..."
uv run python -m openadapt_evals.benchmarks.cli up

# 2. Baseline runs
echo "Running baseline (no demo) - $RUNS runs..."
for i in $(seq 1 $RUNS); do
  echo "Baseline run $i..."
  uv run python -m openadapt_evals.benchmarks.cli live \
    --agent api-claude \
    --server $SERVER \
    --task-ids $TASK \
    --max-steps 15 \
    --output-dir benchmark_results/baseline_run${i}
  sleep 30
done

# 3. Treatment runs
echo "Running treatment (with demo) - $RUNS runs..."
for i in $(seq 1 $RUNS); do
  echo "Treatment run $i..."
  uv run python -m openadapt_evals.benchmarks.cli live \
    --agent api-claude \
    --demo demo_library/synthetic_demos/${TASK}.txt \
    --server $SERVER \
    --task-ids $TASK \
    --max-steps 15 \
    --output-dir benchmark_results/treatment_run${i}
  sleep 30
done

# 4. Negative control
echo "Running negative control (wrong demo)..."
uv run python -m openadapt_evals.benchmarks.cli live \
  --agent api-claude \
  --demo demo_library/synthetic_demos/browser_5.txt \
  --server $SERVER \
  --task-ids $TASK \
  --max-steps 15 \
  --output-dir benchmark_results/negative_control

# 5. Stop infrastructure
echo "Stopping VM..."
uv run python -m openadapt_evals.benchmarks.cli vm-stop

echo "=== Collection Complete ==="
echo "Finished at $(date)"
echo "Results in: benchmark_results/"
```

**Usage**:
```bash
chmod +x demo_test_collection.sh
./demo_test_collection.sh > demo_test_log.txt 2>&1 &
```

### 4.4 Results Analysis Script

```python
#!/usr/bin/env python3
# analyze_demo_results.py

import json
from pathlib import Path
from typing import Dict, List

def load_summary(result_dir: str) -> Dict:
    """Load summary.json from result directory"""
    summary_path = Path(result_dir) / "summary.json"
    if not summary_path.exists():
        return None
    with open(summary_path) as f:
        return json.load(f)

def analyze_scenario(scenario_name: str, runs: List[str]) -> Dict:
    """Analyze multiple runs of same scenario"""
    summaries = [load_summary(run) for run in runs]
    summaries = [s for s in summaries if s is not None]

    if not summaries:
        return {"error": "No valid summaries found"}

    return {
        "runs": len(summaries),
        "avg_success_rate": sum(s["success_rate"] for s in summaries) / len(summaries),
        "avg_steps": sum(s["avg_steps"] for s in summaries) / len(summaries),
        "avg_time": sum(s["avg_time_seconds"] for s in summaries) / len(summaries),
        "variance_success": max(s["success_rate"] for s in summaries) - min(s["success_rate"] for s in summaries),
    }

def main():
    scenarios = {
        "Baseline (No Demo)": [
            "benchmark_results/baseline_run1",
            "benchmark_results/baseline_run2",
            "benchmark_results/baseline_run3",
        ],
        "Treatment (With Demo)": [
            "benchmark_results/treatment_run1",
            "benchmark_results/treatment_run2",
            "benchmark_results/treatment_run3",
        ],
        "Negative Control (Wrong Demo)": [
            "benchmark_results/negative_control",
        ],
    }

    print("=== Demo Test Results Analysis ===\n")

    for scenario_name, runs in scenarios.items():
        print(f"{scenario_name}:")
        results = analyze_scenario(scenario_name, runs)

        if "error" in results:
            print(f"  Error: {results['error']}\n")
            continue

        print(f"  Runs: {results['runs']}")
        print(f"  Avg Success Rate: {results['avg_success_rate']*100:.1f}%")
        print(f"  Avg Steps: {results['avg_steps']:.1f}")
        print(f"  Avg Time: {results['avg_time']:.1f}s")
        if results['runs'] > 1:
            print(f"  Success Variance: ±{results['variance_success']*100:.1f}%")
        print()

    # Calculate improvement
    baseline = analyze_scenario("Baseline", scenarios["Baseline (No Demo)"])
    treatment = analyze_scenario("Treatment", scenarios["Treatment (With Demo)"])

    if "error" not in baseline and "error" not in treatment:
        improvement = treatment['avg_success_rate'] - baseline['avg_success_rate']
        print(f"=== Overall Improvement ===")
        print(f"Success Rate: {baseline['avg_success_rate']*100:.1f}% → {treatment['avg_success_rate']*100:.1f}%")
        print(f"Improvement: +{improvement*100:.1f} percentage points")
        print(f"Step Efficiency: {baseline['avg_steps']:.1f} → {treatment['avg_steps']:.1f} steps")

if __name__ == "__main__":
    main()
```

**Usage**:
```bash
python analyze_demo_results.py
```

---

## Part 5: Success Criteria

### 5.1 Primary Success Criteria

**Criterion 1: Episode Success Rate Improvement**
- **Definition**: Agent completes task successfully per WAA evaluators
- **Baseline**: 0% (from Jan 16 evals)
- **Minimum Success**: >50% success rate with demo
- **Target Success**: >80% success rate with demo
- **Validation**: WAA `/evaluate` endpoint confirms task completion

**Criterion 2: First-Action Accuracy**
- **Definition**: Agent takes correct first action
- **Baseline (research)**: 33% without demo
- **Target**: >80% with demo (research shows 100% possible)
- **Validation**: Manual review of step 1 screenshots

**Criterion 3: Demo Persistence**
- **Definition**: Demo included in API calls at ALL steps
- **Target**: 100% of steps include demo in prompt
- **Validation**: Review API logs for demo text at steps 1, 2, 3, ..., N

### 5.2 Secondary Success Criteria

**Criterion 4: Step Efficiency**
- **Definition**: Average steps to completion
- **Baseline**: 5-7 steps (incomplete)
- **Target**: 7-12 steps (task-dependent, demo-aligned)
- **Validation**: Compare to demo step count

**Criterion 5: Negative Control Validation**
- **Definition**: Wrong demo should NOT improve success
- **Target**: Wrong demo success rate < correct demo success rate
- **Validation**: Statistical significance (t-test, p<0.05)

**Criterion 6: Synthetic Demo Quality**
- **Definition**: Synthetic demos work as well as expected
- **Target**: >70% of synthetic demos lead to task success
- **Validation**: Track which demos succeed vs fail

### 5.3 Statistical Significance

**Required Sample Size**:
- Minimum 3 runs per scenario (baseline, treatment, negative)
- Preferred: 5 runs per scenario for robust statistics

**Statistical Tests**:
```python
from scipy import stats

# Compare baseline vs treatment success rates
baseline_successes = [0, 0, 0]  # 3 runs
treatment_successes = [1, 1, 0]  # 3 runs

# Chi-square test
contingency = [[sum(baseline_successes), len(baseline_successes) - sum(baseline_successes)],
               [sum(treatment_successes), len(treatment_successes) - sum(treatment_successes)]]
chi2, p_value = stats.chi2_contingency(contingency)[:2]

print(f"p-value: {p_value}")
if p_value < 0.05:
    print("Statistically significant improvement!")
```

**Effect Size**:
- **Small effect**: 10-20% improvement
- **Medium effect**: 30-50% improvement
- **Large effect**: >50% improvement

**Target**: Medium to large effect size (30%+ improvement)

### 5.4 Edge Cases to Check

**Edge Case 1: Coordinate Precision**
- Do synthetic demo coordinates land on correct UI elements?
- Validation: Screenshot review of click targets
- Fix: Adjust coordinates in synthetic demos if misaligned

**Edge Case 2: Timing Issues**
- Are WAIT() durations sufficient for UI transitions?
- Validation: Check for timing-related failures in logs
- Fix: Increase WAIT() durations in demos

**Edge Case 3: Multi-Step Recovery**
- If agent deviates from demo at step 3, can it recover?
- Validation: Inject error (wrong click) and observe behavior
- Expected: Agent should attempt to correct

**Edge Case 4: Task Variations**
- Does demo work if task instruction is slightly rephrased?
- Validation: Test with task variations
- Expected: Demo should generalize to similar tasks

**Edge Case 5: Screen Resolution**
- Demos assume 1920x1200, what if actual resolution differs?
- Validation: Check VM screen resolution
- Fix: Normalize coordinates work regardless of resolution

---

## Part 6: Synthetic Demo Validation Strategy

### 6.1 Current Synthetic Demo Status

**Generated**: 154/154 demos (100% coverage)
**Validated**: 154/154 format validation (100% pass)
**Execution Tested**: 0/154 (not yet run on real WAA)

**Quality Assessment** (from DEMO_VALIDATION_ANALYSIS_REPORT.md):
- Expected baseline quality: 82% (research-backed)
- Expected errors: ~28 demos (18.1%)
- Error types: coordinate precision, timing, state dependencies

### 6.2 Recommended Validation Approach

Based on comprehensive cost/quality analysis, use **Hybrid Multi-Stage Validation**:

**Stage 1: LLM-as-Judge Review (All 154 demos)**
- Cost: $0.91
- Time: 15 minutes
- Coverage: 100%
- Error detection: 60-70%

**Stage 2: Human Validation (23 demos = 15%)**
- Cost: $31-77
- Time: 3 hours
- Sample: 10% LLM-flagged + 5% random
- Error detection: 25% of total errors

**Stage 3: Execution Testing (10 complex demos)**
- Cost: $8.25
- Time: 4 hours
- Sample: High-risk complex tasks
- Error detection: 7% of total errors

**Total Cost**: $33-86
**Total Time**: 2 days
**Expected Quality**: 92-96% confidence

### 6.3 Should We Use Synthetic or Manual Demos?

**Recommendation**: Start with synthetic, create manual as needed.

**Synthetic Demos - Use When**:
- ✅ Initial testing (all 154 tasks)
- ✅ Establishing baseline with demos
- ✅ Quick iteration and regeneration
- ✅ Consistent quality needed

**Manual Demos - Use When**:
- ❌ Synthetic demo fails repeatedly (>3 failures)
- ❌ Complex multi-app workflows
- ❌ Edge cases not captured by generation
- ❌ Critical production tasks

**Hybrid Approach** (Recommended):
1. Test all 154 synthetic demos
2. Identify consistent failures (e.g., specific task always fails)
3. Create manual demo for failed tasks
4. Re-test with manual demo
5. Update synthetic generation prompts based on learnings

### 6.4 Validating Synthetic Demo Quality

**Immediate Action** (Before Full Test):
Run pilot validation on 10 representative demos:

```bash
# Validate 10 demos across domains
python -m openadapt_evals.benchmarks.validate_demos \
  --demo-file demo_library/synthetic_demos/notepad_1.txt \
  --demo-file demo_library/synthetic_demos/browser_5.txt \
  --demo-file demo_library/synthetic_demos/office_3.txt \
  --demo-file demo_library/synthetic_demos/coding_7.txt \
  --demo-file demo_library/synthetic_demos/paint_2.txt \
  --demo-file demo_library/synthetic_demos/file_explorer_4.txt \
  --demo-file demo_library/synthetic_demos/settings_6.txt \
  --demo-file demo_library/synthetic_demos/clock_3.txt \
  --demo-file demo_library/synthetic_demos/edge_5.txt \
  --demo-file demo_library/synthetic_demos/vscode_1.txt
```

**Quality Checks**:
1. All pass format validation ✅ (already confirmed)
2. Coordinates in valid range ✅ (0.0-1.0)
3. Actions syntactically correct ✅
4. Reasoning matches actions ✅
5. Step sequences logical ✅

**Execution Test** (1-2 demos):
```bash
# Test notepad_1 with its synthetic demo
uv run python -m openadapt_evals.benchmarks.cli live \
  --agent api-claude \
  --demo demo_library/synthetic_demos/notepad_1.txt \
  --server http://172.171.112.41:5000 \
  --task-ids notepad_1 \
  --max-steps 15
```

**Acceptance Criteria**:
- If succeeds: Synthetic demos work! Proceed with confidence.
- If fails: Analyze failure, adjust demo, re-test.

### 6.5 Demo Improvement Loop

**If synthetic demos have issues**:

```
1. Identify failure pattern
   ↓
2. Categorize error type
   (coordinate, timing, logic, etc.)
   ↓
3. Fix synthetic demo OR create manual demo
   ↓
4. Re-test with fixed demo
   ↓
5. Update generation prompts for future demos
   ↓
6. Regenerate similar demos
   ↓
7. Validate improvements
```

**Example**: If notepad_1 fails due to wrong Start button coordinates:
1. Check actual Start button position (screenshot)
2. Update notepad_1.txt with correct coordinates
3. Re-test
4. Update generation prompt: "Start button at (0.02, 0.98)"
5. Regenerate all demos using Start button
6. Validate batch

---

## Part 7: Full Test Execution Timeline

### Week 1: Preparation and Pilot

**Monday**:
- [ ] Review WAA baseline results (other agent's work)
- [ ] Verify infrastructure (VM, server, API keys)
- [ ] Run pre-execution checklist
- [ ] Validate 10 representative synthetic demos

**Tuesday**:
- [ ] Run Pilot Test (notepad_1, browser_5)
  - [ ] 3 baseline runs (no demo)
  - [ ] 3 treatment runs (with demo)
  - [ ] 1 negative control (wrong demo)
- [ ] Analyze pilot results
- [ ] Identify any immediate issues

**Wednesday**:
- [ ] Fix any issues from pilot
- [ ] Run Domain Sampling (10-15 tasks)
- [ ] Collect and analyze results
- [ ] Decision point: Proceed to full eval or iterate?

**Thursday**:
- [ ] If synthetic demos work: Prepare full evaluation
- [ ] If issues found: Create manual demos for failed tasks
- [ ] Document findings

**Friday**:
- [ ] Write interim report
- [ ] Share findings with team
- [ ] Plan full evaluation

### Week 2: Full Evaluation (If Pilot Successful)

**Monday**:
- [ ] Start full Azure evaluation (154 tasks)
- [ ] Monitor live progress
- [ ] Handle any stuck jobs

**Tuesday-Wednesday**:
- [ ] Continue full evaluation
- [ ] Collect results
- [ ] Generate viewers

**Thursday**:
- [ ] Analyze full results
- [ ] Compare to baseline
- [ ] Calculate statistical significance

**Friday**:
- [ ] Write final report
- [ ] Create presentation
- [ ] Document lessons learned

---

## Part 8: Commands Quick Reference

### Infrastructure Management

```bash
# All-in-one startup
uv run python -m openadapt_evals.benchmarks.cli up

# Check VM status
uv run python -m openadapt_evals.benchmarks.cli vm-status

# Test server connectivity
uv run python -m openadapt_evals.benchmarks.cli probe --server http://172.171.112.41:5000

# Stop VM
uv run python -m openadapt_evals.benchmarks.cli vm-stop
```

### Run Tests

```bash
# Baseline (no demo)
uv run python -m openadapt_evals.benchmarks.cli live \
  --agent api-claude \
  --server http://172.171.112.41:5000 \
  --task-ids notepad_1 \
  --max-steps 15 \
  --output-dir benchmark_results/baseline

# Treatment (with demo)
uv run python -m openadapt_evals.benchmarks.cli live \
  --agent api-claude \
  --demo demo_library/synthetic_demos/notepad_1.txt \
  --server http://172.171.112.41:5000 \
  --task-ids notepad_1 \
  --max-steps 15 \
  --output-dir benchmark_results/treatment

# Negative control (wrong demo)
uv run python -m openadapt_evals.benchmarks.cli live \
  --agent api-claude \
  --demo demo_library/synthetic_demos/browser_5.txt \
  --server http://172.171.112.41:5000 \
  --task-ids notepad_1 \
  --max-steps 15 \
  --output-dir benchmark_results/negative

# Multiple tasks (domain sampling)
uv run python -m openadapt_evals.benchmarks.cli live \
  --agent api-claude \
  --demo-library demo_library/synthetic_demos \
  --server http://172.171.112.41:5000 \
  --task-ids notepad_1,browser_5,paint_1,office_3 \
  --max-steps 15 \
  --output-dir benchmark_results/domain_sampling

# Full Azure evaluation (154 tasks, parallel)
uv run python -m openadapt_evals.benchmarks.cli azure \
  --agent api-claude \
  --demo-library demo_library/synthetic_demos \
  --workers 10 \
  --waa-path /path/to/WAA \
  --max-steps 15 \
  --output-dir benchmark_results/full_eval
```

### View Results

```bash
# Generate HTML viewer
uv run python -m openadapt_evals.benchmarks.cli view --run-name baseline

# Open in browser
open benchmark_results/baseline/viewer.html

# Compare results
python analyze_demo_results.py
```

### Validate Demos

```bash
# Validate all synthetic demos
uv run python -m openadapt_evals.benchmarks.validate_demos \
  --demo-dir demo_library/synthetic_demos

# Validate specific demo
uv run python -m openadapt_evals.benchmarks.validate_demos \
  --demo-file demo_library/synthetic_demos/notepad_1.txt

# Save validation to JSON
uv run python -m openadapt_evals.benchmarks.validate_demos \
  --demo-dir demo_library/synthetic_demos \
  --json-output validation_results.json
```

---

## Part 9: Expected Results and Analysis

### 9.1 Hypothesized Outcomes

**Best Case** (80%+ success with demo):
- Demo persistence works as designed
- Synthetic demos are high quality
- Agent follows patterns reliably
- Coordinate precision is adequate

**Likely Case** (50-70% success with demo):
- Demo persistence works
- Some synthetic demos need refinement
- Agent mostly follows patterns
- Some coordinate adjustments needed

**Worst Case** (<30% success with demo):
- Demo persistence has issues OR
- Synthetic demos have fundamental problems OR
- Agent struggles with demo interpretation OR
- Infrastructure issues (timing, resolution, etc.)

### 9.2 Root Cause Analysis Framework

**If success rate is LOW despite demo**:

```
Problem: Low success rate with demo
├── Demo not included in prompts?
│   └── Check API logs for demo text at all steps
│       └── Fix: Verify api_agent.py lines 371-379
│
├── Demo included but agent ignores it?
│   └── Check agent reasoning in logs
│       └── Fix: Improve prompt engineering
│
├── Demo has wrong actions?
│   └── Manual review of demo vs actual task
│       └── Fix: Regenerate or create manual demo
│
├── Coordinate precision issues?
│   └── Check screenshots - do clicks land correctly?
│       └── Fix: Adjust coordinates in demos
│
└── Timing issues (UI not ready)?
    └── Check for premature actions in logs
        └── Fix: Increase WAIT() durations
```

### 9.3 Success Metrics Dashboard

Create live dashboard during testing:

```markdown
## Demo Test Live Results

**Last Updated**: [Timestamp]

### Scenario Comparison

| Metric | Baseline | With Demo | Improvement |
|--------|----------|-----------|-------------|
| Success Rate | 0% | ?% | +?% |
| Avg Steps | 5.0 | ? | ? |
| Avg Time | 72s | ?s | ?s |
| First-Action Accuracy | 33% | ?% | +?% |

### Task-Level Results

| Task | Domain | No Demo | With Demo | Delta |
|------|--------|---------|-----------|-------|
| notepad_1 | notepad | 0/3 | ?/3 | +? |
| browser_5 | browser | 0/3 | ?/3 | +? |
| paint_1 | paint | 0/3 | ?/3 | +? |

### Demo Quality

| Metric | Value |
|--------|-------|
| Demos tested | ?/154 |
| Demos successful | ? |
| Demos failed | ? |
| Success rate | ?% |
```

---

## Part 10: Final Recommendations

### 10.1 Immediate Action Items

**Before Testing**:
1. Wait for WAA baseline validation (other agent)
2. Run demo format validation (verify 154/154 pass)
3. Verify infrastructure (VM, server, API keys)
4. Review this test plan with team

**Pilot Phase** (1-2 days):
1. Test notepad_1 with synthetic demo (3 runs)
2. Compare to baseline (3 runs)
3. Analyze results and decide: proceed or iterate?

**Full Test** (if pilot succeeds):
1. Domain sampling (10-15 tasks, 1 day)
2. Full evaluation (154 tasks, 2 days)
3. Statistical analysis
4. Final report

### 10.2 Decision Matrix

| Pilot Result | Action |
|--------------|--------|
| >70% success | ✅ Proceed to full eval |
| 40-70% success | ⚠️ Improve demos, test 10 more tasks |
| <40% success | ❌ Investigate root cause, iterate on demos |

### 10.3 Resource Requirements

**Time**:
- Preparation: 1 day
- Pilot test: 1 day
- Domain sampling: 1 day
- Full evaluation: 2-3 days
- Analysis and reporting: 1 day
- **Total**: 6-7 days

**Cost**:
- VM time: $0.192/hour × ~20 hours = $3.84
- API calls (Claude): ~$15-25 for all tests
- Azure ML (full eval): ~$2.50 (from cost optimization)
- **Total**: ~$20-30

**Personnel**:
- 1 engineer for execution
- 1 reviewer for analysis
- Periodic check-ins with team

### 10.4 Success Definition

**Test is SUCCESSFUL if**:
1. ✅ Episode success rate improves by >30% with demo
2. ✅ First-action accuracy >80% with demo
3. ✅ Demo persistence verified (100% of steps)
4. ✅ Negative control validates (wrong demo doesn't help)
5. ✅ Synthetic demos work for >70% of tasks

**Test is INCONCLUSIVE if**:
- ⚠️ Improvement is 10-30% (small effect)
- ⚠️ High variance in results (inconsistent)
- ⚠️ Mixed results across domains

**Test FAILS if**:
- ❌ No improvement with demo (0-10%)
- ❌ Demo not persisting across steps
- ❌ Wrong demo performs as well as correct demo

---

## Appendix A: Cost Breakdown

### Synthetic Demo Validation Costs

From DEMO_VALIDATION_ANALYSIS_REPORT.md (Hybrid Multi-Stage):

| Stage | Cost | Time | Coverage |
|-------|------|------|----------|
| LLM Review (154 demos) | $0.91 | 15 min | 100% |
| Human Validation (23 demos) | $31-77 | 3 hrs | 15% |
| Execution Testing (10 demos) | $8.25 | 4 hrs | 6.5% |
| **Total** | **$40-86** | **2 days** | **Multi-layered** |

**Recommended Budget**: $50-100

### Test Execution Costs

| Item | Unit Cost | Quantity | Total |
|------|-----------|----------|-------|
| VM time (D4s_v5) | $0.192/hr | 20 hrs | $3.84 |
| Claude API (pilot) | ~$0.50/task | 20 tasks | $10 |
| Claude API (full) | ~$0.50/task | 154 tasks | $77 |
| Azure ML (full eval) | $2.50 | 1 run | $2.50 |
| **Total (pilot)** | | | **$14** |
| **Total (full)** | | | **$83** |

**Total Project Cost**: $130-170 (validation + testing)

---

## Appendix B: File Locations

### Critical Files

```
/Users/abrichr/oa/src/openadapt-evals/
├── openadapt_evals/agents/api_agent.py         # Demo persistence fix (lines 371-379)
├── demo_library/synthetic_demos/               # 154 synthetic demos
│   ├── notepad_1.txt                           # Pilot test demo
│   ├── browser_5.txt                           # Pilot test demo
│   └── demos.json                              # Demo index
├── benchmark_results/                          # Test results
│   ├── waa-live_eval_20260116_200004/          # Baseline reference
│   └── [new test results]
├── DEMO_VALIDATION_ANALYSIS_REPORT.md          # Demo validation research
├── REAL_EVALUATION_RESULTS.md                  # Baseline results guide
└── DEMO_TEST_PLAN.md                           # This document
```

### Documentation

```
CLAUDE.md                                       # Development guidelines
SESSION_SUMMARY_2026-01-18.md                   # Recent work summary
SYNTHETIC_DEMOS_SUMMARY.md                      # Demo generation summary
COST_OPTIMIZATION.md                            # Cost tracking docs
```

---

## Appendix C: Research References

### Demo-Conditioned Prompting

**Without demo**: 33% first-action accuracy
**With demo**: 100% first-action accuracy
**Source**: Internal mock testing (Jan 17, 2026)

### Synthetic Demo Quality

**Baseline**: 81.9% success rate (synthetic) vs 76.6% (human)
**Source**: "Beyond Human Demonstrations: Diffusion-Based RL" (2025)

### Validation Approaches

**LLM-as-Judge**: 80% agreement with human judgment, 500-5000x cost savings
**Source**: Cameron R. Wolfe, Ph.D. (2025)

**Hybrid Validation**: 80% cost reduction while maintaining quality
**Source**: SuperAnnotate industry practice (2025)

---

## Document Version

**Version**: 1.0
**Created**: January 18, 2026
**Author**: Claude Sonnet 4.5
**Status**: Ready for Execution
**Next Update**: After pilot test completion

---

**END OF TEST PLAN**
