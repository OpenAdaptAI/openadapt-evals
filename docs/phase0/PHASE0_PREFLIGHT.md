# Phase 0 Demo-Augmentation Pre-Flight Checklist

**Date**: 2026-01-18
**Phase**: Phase 0 - Demo-Augmentation Baseline
**Budget**: $400 (estimated $4.40 for test, $220 for full run)

## Overview

This checklist ensures all infrastructure is ready before running the full Phase 0 evaluation with 240 runs (20 tasks × 2 models × 2 conditions × 3 trials).

## Pre-Flight Checks

### 1. Task Set Definition

- [x] **20-task set defined** - `/Users/abrichr/oa/src/openadapt-evals/PHASE0_TASKS.txt`
  - File exists: Yes
  - Contains 20 tasks: Verify with `grep -v '^#' PHASE0_TASKS.txt | wc -l`
  - Tasks span diverse domains: notepad, browser, office, calculator, etc.

**Verification**:
```bash
cat PHASE0_TASKS.txt | grep -v '^#' | grep -v '^[[:space:]]*$' | wc -l
# Expected: 20
```

### 2. Demo Library

- [ ] **All 20 demos exist**
  - Location: `demo_library/synthetic_demos/`
  - Format: `{task_id}.txt`
  - Contains: TASK, DOMAIN, STEPS, EXPECTED_OUTCOME

**Verification**:
```bash
for task in $(cat PHASE0_TASKS.txt | grep -v '^#' | grep -v '^[[:space:]]*$'); do
    if [ ! -f "demo_library/synthetic_demos/${task}.txt" ]; then
        echo "Missing: ${task}.txt"
    fi
done
# Expected: No output (all demos present)
```

### 3. API Configuration

- [ ] **ANTHROPIC_API_KEY configured**
  ```bash
  echo $ANTHROPIC_API_KEY
  # Should output: sk-ant-...
  ```

- [ ] **OPENAI_API_KEY configured**
  ```bash
  echo $OPENAI_API_KEY
  # Should output: sk-...
  ```

- [ ] **API keys have sufficient credits**
  - Claude: Check at https://console.anthropic.com/settings/billing
  - OpenAI: Check at https://platform.openai.com/account/usage
  - Required: ~$250 per key (Phase 0 estimate: $220 total)

### 4. Mock Adapter Testing

- [x] **Mock adapter works**
  ```bash
  uv run python -m openadapt_evals.benchmarks.cli mock --tasks 1
  ```
  - Expected: 100% success rate
  - Expected: Results saved to `benchmark_results/`

- [x] **Demo loading works**
  ```bash
  uv run python -m openadapt_evals.benchmarks.cli mock --tasks 1 \
    --demo demo_library/synthetic_demos/notepad_1.txt
  ```
  - Expected: Demo loaded message
  - Expected: 100% success rate

### 5. API Agent Testing

⚠️ **Note**: API keys in .env have insufficient credits. Need new keys before testing.

- [ ] **Claude agent works**
  ```bash
  export ANTHROPIC_API_KEY=sk-...
  uv run python -m openadapt_evals.benchmarks.cli mock --agent api-claude --tasks 1
  ```
  - Expected: Agent initializes
  - Expected: API call succeeds or fails gracefully
  - Expected: Cost tracked

- [ ] **OpenAI agent works**
  ```bash
  export OPENAI_API_KEY=sk-...
  uv run python -m openadapt_evals.benchmarks.cli mock --agent api-openai --tasks 1
  ```
  - Expected: Agent initializes
  - Expected: API call succeeds or fails gracefully
  - Expected: Cost tracked

### 6. Demo Persistence (P0 Fix)

- [x] **Demo persists across steps**
  - Code verified: `openadapt_evals/agents/api_agent.py` lines 374-382
  - Demo included at EVERY step, not just step 1
  - This is the critical P0 fix for episode success

**Verification**:
```python
from openadapt_evals import ApiAgent
from pathlib import Path

demo = Path("demo_library/synthetic_demos/notepad_1.txt").read_text()
agent = ApiAgent(provider="anthropic", demo=demo)

# Verify demo is stored
assert agent.demo == demo
assert len(agent.demo) > 0

# Reset and verify demo persists
agent.reset()
assert agent.demo == demo
```

### 7. Results Saving

- [x] **Results directory created**
  ```bash
  ls -la benchmark_results/
  ```
  - Expected: Multiple run directories

- [x] **Results have correct structure**
  ```bash
  ls benchmark_results/waa-mock_eval_*/
  ```
  - Expected: `metadata.json`, `summary.json`, `tasks/`

- [x] **Task results include all fields**
  ```bash
  cat benchmark_results/waa-mock_eval_*/tasks/*/execution.json | jq .
  ```
  - Expected fields: `task_id`, `success`, `score`, `num_steps`, `total_time_seconds`, `steps`, `logs`

### 8. Metrics Collection

- [x] **Episode success tracked** - `execution.json: success` (bool)
- [x] **Number of steps tracked** - `execution.json: num_steps` (int)
- [x] **Execution time tracked** - `execution.json: total_time_seconds` (float)
- [ ] **First action correct** - NOT IMPLEMENTED (optional for Phase 0)
- [ ] **Failure mode** - NOT IMPLEMENTED (optional for Phase 0)
- [ ] **Cost tracking** - Needs API usage integration

**Note**: Core metrics (success, steps, time) are sufficient for Phase 0. Optional metrics can be added later.

### 9. Cost Tracking

- [ ] **Cost estimates calculated**
  - Phase 0 configuration: 20 tasks × 2 models × 2 conditions × 3 trials = 240 runs
  - Expected cost: $220 (from integration test estimates)
  - See `tests/test_phase0_integration.py::TestPhase0CostEstimation` for details

- [ ] **Budget approved**
  - Estimated: $220
  - Buffer: $180 (for retries, errors)
  - Total budget: $400

### 10. Integration Tests

- [x] **All integration tests pass**
  ```bash
  uv run pytest tests/test_phase0_integration.py -v
  ```
  - Expected: 11 tests passed
  - Tests cover: mock adapter, demo loading, API agents, metrics, cost estimation

**Latest Results** (2026-01-18):
```
tests/test_phase0_integration.py::TestPhase0Infrastructure::test_mock_adapter_loads_tasks PASSED
tests/test_phase0_integration.py::TestPhase0Infrastructure::test_demo_loads_correctly PASSED
tests/test_phase0_integration.py::TestPhase0Infrastructure::test_zero_shot_condition PASSED
tests/test_phase0_integration.py::TestPhase0Infrastructure::test_demo_conditioned_condition PASSED
tests/test_phase0_integration.py::TestPhase0Infrastructure::test_api_agent_creation_claude PASSED
tests/test_phase0_integration.py::TestPhase0Infrastructure::test_api_agent_creation_openai PASSED
tests/test_phase0_integration.py::TestPhase0Infrastructure::test_results_save_correctly PASSED
tests/test_phase0_integration.py::TestPhase0Infrastructure::test_metrics_calculated_correctly PASSED
tests/test_phase0_integration.py::TestPhase0Infrastructure::test_demo_persistence_in_agent PASSED
tests/test_phase0_integration.py::TestPhase0CostEstimation::test_api_usage_tracking_structure PASSED
tests/test_phase0_integration.py::TestPhase0CostEstimation::test_cost_calculation_logic PASSED

======================== 11 passed, 1 warning in 1.18s =========================
```

### 11. End-to-End Test

- [ ] **Run end-to-end test script**
  ```bash
  ./scripts/phase0_test.sh
  ```
  - Expected: All test suites pass
  - Expected: Dry run completes successfully
  - Expected: Status and analysis scripts work

- [ ] **Run single task integration test** (OPTIONAL)
  ```bash
  ./scripts/phase0_test.sh --integration
  ```
  - Requires WAA server running
  - Tests 1 task with real API calls
  - Verifies end-to-end pipeline

## Cost Estimates

Based on integration test calculations:

### Test Configuration (80 runs)
- Tasks: 2 (for testing)
- Models: 2 (Claude Sonnet 4.5, GPT-4)
- Conditions: 2 (zero-shot, demo-conditioned)
- Trials: 10
- **Total runs**: 80
- **Total cost**: $4.40
  - Claude: $1.80
  - GPT-4: $2.60

### Full Phase 0 Configuration (240 runs)
- Tasks: 20
- Models: 2 (Claude Sonnet 4.5, GPT-4)
- Conditions: 2 (zero-shot, demo-conditioned)
- Trials: 3
- **Total runs**: 240
- **Estimated cost**: $220
  - Claude: $90
  - GPT-4: $130

### Budget
- **Estimated**: $220
- **Buffer**: $180 (for retries, errors, longer tasks)
- **Total Budget**: $400

## Readiness Status

### ✓ Ready
- [x] Mock adapter infrastructure
- [x] Demo loading system
- [x] API agent creation (both models)
- [x] Demo persistence (P0 fix)
- [x] Results saving and structure
- [x] Core metrics (success, steps, time)
- [x] Integration test suite
- [x] Cost estimation

### ⚠️ Needs Attention
- [ ] Valid API keys with sufficient credits
- [ ] All 20 demos validated
- [ ] 20-task set finalized
- [ ] Budget approval ($400)
- [ ] End-to-end test script run

### 🔧 Optional (Can Add Later)
- [ ] First action correctness metric
- [ ] Failure mode classification
- [ ] Real-time cost tracking during evaluation
- [ ] Automatic retry on API failures

## Running Phase 0

Once all checks pass, run Phase 0:

### Week 1: Zero-Shot Baseline (120 runs)
```bash
./scripts/phase0_runner.sh \
  --condition zero-shot \
  --tasks all \
  --trials 3
```

Expected:
- 120 results (20 tasks × 2 models × 3 trials)
- ~$110 cost
- Baseline success rates for both models

### Week 2: Demo-Conditioned (120 runs)
```bash
./scripts/phase0_runner.sh \
  --condition demo-conditioned \
  --tasks all \
  --trials 3
```

Expected:
- 120 results (20 tasks × 2 models × 3 trials)
- ~$110 cost
- Improved success rates with demo guidance

### Analysis
```bash
./scripts/phase0_analyze.py \
  --results-dir phase0_results \
  --export phase0_analysis.json
```

Expected outputs:
- Success rate comparison (zero-shot vs demo)
- Per-model analysis
- Statistical significance tests
- Cost breakdown

## Emergency Contacts

- **Budget Issues**: Check OpenAdaptAI billing accounts
- **API Rate Limits**: Anthropic/OpenAI support
- **Infrastructure Bugs**: GitHub Issues at openadaptai/openadapt-evals

## Sign-Off

Before proceeding to full Phase 0:

- [ ] All "Ready" items checked
- [ ] All "Needs Attention" items resolved
- [ ] Budget approved
- [ ] API keys configured with sufficient credits
- [ ] Integration tests passing

**Signed Off By**: _________________
**Date**: _________________

## Notes

- Phase 0 is expected to take 2 weeks (Week 1: zero-shot, Week 2: demo-conditioned)
- Results will inform Phase 1 retrieval strategy
- Monitor costs closely - pause if approaching budget limits
- Save all results for later analysis
