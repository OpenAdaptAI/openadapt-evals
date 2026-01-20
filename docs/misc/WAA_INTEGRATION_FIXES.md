# WAA Integration Fixes - Quick Reference

**Status**: Draft
**Date**: January 18, 2026

## Problem Summary

Our current WAALiveAdapter integration has critical gaps preventing proper evaluation:

1. ❌ **Not loading real task configs** - Creating generic "Task notepad_1" instead of loading JSON with evaluator specs
2. ❌ **No evaluator implementation** - Returning placeholder heuristics instead of real scores
3. ❌ **Missing WAA action format** - Need code blocks (`computer.click([42])`) not just coordinates
4. ❌ **No validated baseline** - Don't know what success rate to expect

## Quick Validation Command

```bash
# Run vanilla WAA baseline (3 tasks, ~10 min)
cd /Users/abrichr/oa/src/openadapt-evals
./scripts/validate_waa_baseline.sh

# Expected output: 0-1 successes out of 3 tasks (~0-33%)
```

## Priority Fixes

### 1. Fix Task Loading (P0)

**File**: `openadapt_evals/adapters/waa_live.py`
**Lines**: 219-260
**Problem**: `_load_task_from_disk()` doesn't load evaluator configs

**Fix**:
```python
def _load_task_from_disk(self, task_id: str, base_path: str) -> BenchmarkTask | None:
    # Parse: "notepad_366de66e-cbae-4d72-b042-26390db2b145-WOS"
    domain, task_file = task_id.split("_", 1)
    task_path = Path(base_path) / "examples" / domain / f"{task_file}.json"

    with open(task_path) as f:
        config = json.load(f)

    return BenchmarkTask(
        task_id=task_id,
        instruction=config["instruction"],
        domain=domain,
        initial_state_ref=config.get("snapshot"),
        time_limit_steps=15,
        raw_config=config,  # CRITICAL: Full config with evaluator
        evaluation_spec=config.get("evaluator"),
    )
```

**Test**:
```python
task = adapter.load_task("notepad_366de66e-cbae-4d72-b042-26390db2b145-WOS")
assert task.evaluation_spec is not None
assert "func" in task.raw_config["evaluator"]
```

### 2. Implement Real Evaluation (P0)

**File**: `openadapt_evals/server/evaluate_endpoint.py`
**Lines**: 86-199
**Problem**: `/evaluate` endpoint doesn't match WAA's evaluation logic

**Fix**: See `WAA_BASELINE_VALIDATION_PLAN.md` section 3.2 for full implementation

**Deploy**:
```bash
# Copy to VM and patch WAA server
scp openadapt_evals/server/waa_server_patch.py azureuser@vm:/tmp/
ssh azureuser@vm "python /tmp/waa_server_patch.py"
```

**Test**:
```bash
curl -X POST http://vm:5000/evaluate \
  -H "Content-Type: application/json" \
  -d @evaluation_examples_windows/examples/notepad/366de66e-cbae-4d72-b042-26390db2b145-WOS.json

# Should return real score (0.0 or 1.0), not heuristic
```

### 3. Add Code Block Format (P1)

**File**: `openadapt_evals/adapters/waa_live.py`
**Lines**: 717-788
**Problem**: `_translate_action()` uses pyautogui, not WAA's computer.* API

**Fix**:
```python
def _translate_action(self, action: BenchmarkAction) -> str | None:
    if action.type == "click":
        if action.target_node_id is not None:
            return f"computer.click([{action.target_node_id}])"
        else:
            return f"computer.mouse.move({action.x}, {action.y}); computer.mouse.click()"

    elif action.type == "type":
        return f'computer.type("{action.text}")'

    elif action.type == "key":
        return f'computer.key("{action.key}")'

    # ... rest of actions
```

## Validation Checklist

Before running full 154-task evaluation:

- [ ] **Baseline validated**
  - [ ] Run `./scripts/validate_waa_baseline.sh`
  - [ ] Get 0-1 successes out of 3 tasks
  - [ ] Verify real scores (0.0 or 1.0), not heuristics
  - [ ] Document baseline in `WAA_BASELINE_RESULTS.md`

- [ ] **Task loading fixed**
  - [ ] Load real JSON from `evaluation_examples_windows/`
  - [ ] Task has `instruction`, `evaluator`, `snapshot` fields
  - [ ] `task.raw_config["evaluator"]` contains getters/metrics config

- [ ] **Evaluation working**
  - [ ] `/evaluate` endpoint deployed on WAA server
  - [ ] Can run getters (e.g., `get_vm_file_exists_in_vm_folder`)
  - [ ] Can run metrics (e.g., `exact_match`, `compare_text_file`)
  - [ ] Returns real scores, not "Fallback evaluation" message

- [ ] **Integration tested**
  - [ ] Run our WAALiveAdapter on same 3 tasks
  - [ ] Success rate matches vanilla WAA (±10%)
  - [ ] No crashes or errors
  - [ ] Detailed logs show real evaluation, not fallback

## Testing Commands

```bash
# 1. Validate vanilla WAA baseline (10 min)
cd /Users/abrichr/oa/src/openadapt-evals
./scripts/validate_waa_baseline.sh

# 2. Test task loading fix
uv run python -c "
from openadapt_evals import WAALiveAdapter, WAALiveConfig
config = WAALiveConfig(waa_examples_path='/path/to/evaluation_examples_windows')
adapter = WAALiveAdapter(config)
task = adapter.load_task('notepad_366de66e-cbae-4d72-b042-26390db2b145-WOS')
assert task.evaluation_spec is not None
print('✓ Task loading works')
"

# 3. Test /evaluate endpoint
curl -X POST http://localhost:5000/evaluate \
  -H "Content-Type: application/json" \
  -d @evaluation_examples_windows/examples/notepad/366de66e-cbae-4d72-b042-26390db2b145-WOS.json

# 4. Run our integration on same tasks
uv run python -m openadapt_evals.benchmarks.cli live \
  --agent api-claude \
  --server http://localhost:5000 \
  --waa-examples-path /path/to/evaluation_examples_windows \
  --task-ids notepad_366de66e-cbae-4d72-b042-26390db2b145-WOS

# 5. Compare results
# Vanilla: 0-1/3 (~0-33%)
# Ours:    Should match ±10%
```

## Expected Baseline Performance

From WAA's published results:

| Agent | Success Rate | Source |
|-------|-------------|--------|
| Navi (GPT-4o + OmniParser) | 19.5% | SOTA |
| GPT-4o (vision only) | 12-15% | Without grounding |
| Claude Sonnet 3.5 | 10-12% | Vision-based |

**For 3-task validation**:
- Expected: 0-1 successes (~0-33%)
- Success criteria: Reproducible, real evaluation, no crashes

## Files to Review

| File | Purpose | Status |
|------|---------|--------|
| `WAA_BASELINE_VALIDATION_PLAN.md` | Full validation plan | ✅ Created |
| `scripts/validate_waa_baseline.sh` | Baseline test script | ✅ Created |
| `adapters/waa_live.py` | Live adapter impl | ⚠️ Needs fixes |
| `server/evaluate_endpoint.py` | Evaluator endpoint | ⚠️ Needs enhancement |
| `tests/test_waa_baseline.py` | Integration tests | 📋 TODO |
| `docs/WAA_BASELINE_RESULTS.md` | Baseline results doc | 📋 TODO |

## Next Steps

1. **Run validation script** (10 min)
   ```bash
   ./scripts/validate_waa_baseline.sh
   ```

2. **Review results** (5 min)
   - Check `./baseline_results/` for detailed logs
   - Verify task configs loaded
   - Verify evaluators ran
   - Document scores

3. **Fix task loading** (30 min)
   - Update `_load_task_from_disk()`
   - Test with real task IDs
   - Verify evaluator configs present

4. **Fix evaluation** (1 hour)
   - Enhance `/evaluate` endpoint
   - Deploy to WAA server
   - Test with curl
   - Verify real scores returned

5. **Integration test** (30 min)
   - Run our adapter on same 3 tasks
   - Compare with vanilla baseline
   - Document in `WAA_BASELINE_RESULTS.md`

6. **Full evaluation** (2-3 hours)
   - Run all 154 tasks
   - Generate benchmark viewer
   - Compare with published baselines

**Total Estimated Time**: 4-6 hours

## Questions to Answer

1. **Does vanilla WAA run successfully on our VM setup?**
   - Run `validate_waa_baseline.sh` to find out

2. **What is the actual baseline success rate?**
   - Will be documented after validation

3. **Do our task configs match WAA's format?**
   - Check logs for "TESTING ON TASK CONFIG PATH"

4. **Are evaluators running properly?**
   - Check logs for "Running evaluator(s)" and scores

5. **Can we reproduce vanilla WAA results?**
   - Compare our integration with baseline

## Success Criteria

✅ **Baseline validated** when:
- Vanilla WAA runs without crashes
- Get real scores (0.0 or 1.0)
- Results are reproducible
- Match expected baseline (~0-33% for 3 tasks)

✅ **Integration fixed** when:
- Our adapter produces same results as vanilla
- Real evaluators used (not fallback)
- Task configs loaded properly
- Ready to test demo improvements

✅ **Ready for full evaluation** when:
- 3-task validation passes
- Integration test passes
- Baseline documented
- No known issues
