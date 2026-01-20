# Phase 0 Evaluation Quick Start

**Task Set**: 20 representative WAA tasks (13% of 154-task suite)
**Files**: 
- Task documentation: `PHASE0_TASK_SET.md`
- Task ID list: `PHASE0_TASKS.txt`
- Demo library: `demo_library/synthetic_demos/`

## Quick Commands

### Run Complete Phase 0 Evaluation

```bash
# Load task IDs
TASK_IDS=$(cat PHASE0_TASKS.txt | tr '\n' ',' | sed 's/,$//')

# Run with demo augmentation (experimental condition)
uv run python -m openadapt_evals.benchmarks.cli live \
    --agent retrieval-claude \
    --demo-library demo_library \
    --server http://YOUR_VM_IP:5000 \
    --task-ids $TASK_IDS \
    --max-steps 20 \
    --save-screenshots

# Run without demo (control baseline)
uv run python -m openadapt_evals.benchmarks.cli live \
    --agent api-claude \
    --server http://YOUR_VM_IP:5000 \
    --task-ids $TASK_IDS \
    --max-steps 20 \
    --save-screenshots
```

### Run Single Task (Testing)

```bash
# Test with demo
uv run python -m openadapt_evals.benchmarks.cli live \
    --agent api-claude \
    --demo demo_library/synthetic_demos/notepad_1.txt \
    --server http://YOUR_VM_IP:5000 \
    --task-ids notepad_1

# Test without demo
uv run python -m openadapt_evals.benchmarks.cli live \
    --agent api-claude \
    --server http://YOUR_VM_IP:5000 \
    --task-ids notepad_1
```

### Run by Complexity

```bash
# Simple tasks only (4-7 steps)
SIMPLE="notepad_1,browser_4,paint_10,file_explorer_1,media_3"
uv run python -m openadapt_evals.benchmarks.cli live \
    --agent retrieval-claude \
    --demo-library demo_library \
    --server http://YOUR_VM_IP:5000 \
    --task-ids $SIMPLE

# Medium tasks only (8-12 steps)  
MEDIUM="notepad_3,browser_2,office_1,settings_1,settings_3,file_explorer_3,file_explorer_9,file_explorer_6,clock_2"
uv run python -m openadapt_evals.benchmarks.cli live \
    --agent retrieval-claude \
    --demo-library demo_library \
    --server http://YOUR_VM_IP:5000 \
    --task-ids $MEDIUM

# Complex tasks only (13+ steps)
COMPLEX="notepad_5,browser_5,browser_7,office_4,office_9,settings_2"
uv run python -m openadapt_evals.benchmarks.cli live \
    --agent retrieval-claude \
    --demo-library demo_library \
    --server http://YOUR_VM_IP:5000 \
    --task-ids $COMPLEX
```

### Run by Domain

```bash
# Notepad tasks (3 tasks)
uv run python -m openadapt_evals.benchmarks.cli live \
    --agent retrieval-claude \
    --demo-library demo_library \
    --server http://YOUR_VM_IP:5000 \
    --task-ids notepad_1,notepad_3,notepad_5

# Browser tasks (4 tasks)
uv run python -m openadapt_evals.benchmarks.cli live \
    --agent retrieval-claude \
    --demo-library demo_library \
    --server http://YOUR_VM_IP:5000 \
    --task-ids browser_2,browser_4,browser_5,browser_7

# Office tasks (3 tasks)
uv run python -m openadapt_evals.benchmarks.cli live \
    --agent retrieval-claude \
    --demo-library demo_library \
    --server http://YOUR_VM_IP:5000 \
    --task-ids office_1,office_4,office_9

# Settings tasks (3 tasks)
uv run python -m openadapt_evals.benchmarks.cli live \
    --agent retrieval-claude \
    --demo-library demo_library \
    --server http://YOUR_VM_IP:5000 \
    --task-ids settings_1,settings_2,settings_3

# File Explorer tasks (4 tasks)
uv run python -m openadapt_evals.benchmarks.cli live \
    --agent retrieval-claude \
    --demo-library demo_library \
    --server http://YOUR_VM_IP:5000 \
    --task-ids file_explorer_1,file_explorer_3,file_explorer_6,file_explorer_9
```

## Expected Results

### Control Baseline (No Demo)
- First-action accuracy: ~33%
- Episode success: ~0%
- Average steps per task: ~8-10

### Experimental (With Demo)
- First-action accuracy: ~100% (3x improvement)
- Episode success: ~40-60% (target)
- Average steps per task: ~6-8 (more efficient)

## Analysis

After running both conditions:

```bash
# Generate comparison report
uv run python -m openadapt_evals.benchmarks.cli view \
    --run-name phase0_with_demo \
    --run-name phase0_no_demo \
    --compare

# Or analyze results programmatically
python << PYEOF
import json
from pathlib import Path

# Load results
with_demo = json.loads(Path("benchmark_results/phase0_with_demo/results.json").read_text())
no_demo = json.loads(Path("benchmark_results/phase0_no_demo/results.json").read_text())

# Compare first-action accuracy
with_demo_first = sum(r['first_action_correct'] for r in with_demo['results']) / len(with_demo['results'])
no_demo_first = sum(r['first_action_correct'] for r in no_demo['results']) / len(no_demo['results'])

print(f"First-action accuracy:")
print(f"  With demo: {with_demo_first*100:.1f}%")
print(f"  No demo:   {no_demo_first*100:.1f}%")
print(f"  Improvement: {(with_demo_first/no_demo_first - 1)*100:.1f}%")

# Compare episode success
with_demo_success = sum(r['success'] for r in with_demo['results']) / len(with_demo['results'])
no_demo_success = sum(r['success'] for r in no_demo['results']) / len(no_demo['results'])

print(f"\nEpisode success:")
print(f"  With demo: {with_demo_success*100:.1f}%")
print(f"  No demo:   {no_demo_success*100:.1f}%")
if no_demo_success > 0:
    print(f"  Improvement: {(with_demo_success/no_demo_success - 1)*100:.1f}%")
else:
    print(f"  Improvement: N/A (baseline is 0%)")
PYEOF
```

## Verification

Check all demos exist:

```bash
for task in $(cat PHASE0_TASKS.txt); do
    if [ ! -f "demo_library/synthetic_demos/${task}.txt" ]; then
        echo "MISSING: $task"
    fi
done
```

Expected: No output (all demos exist)

## Troubleshooting

**WAA server not responding:**
```bash
# Check VM status
uv run python -m openadapt_evals.benchmarks.cli vm-status

# Start WAA server
uv run python -m openadapt_evals.benchmarks.cli up --auto-verify
```

**Demo not loading:**
```bash
# Validate demo format
uv run python -m openadapt_evals.benchmarks.validate_demos \
    --demo-file demo_library/synthetic_demos/TASK_ID.txt
```

**Agent errors:**
```bash
# Check API keys
echo $ANTHROPIC_API_KEY
echo $OPENAI_API_KEY

# Test agent standalone
python << PYEOF
from openadapt_evals import ApiAgent

agent = ApiAgent(provider="anthropic")
print("Agent initialized successfully")
PYEOF
```

## Next Steps

1. Run control baseline (no demo)
2. Run experimental condition (with demo)
3. Compare results
4. Analyze failure modes
5. Iterate on demo quality if needed
6. Scale to full 154-task suite

## References

- Full documentation: `PHASE0_TASK_SET.md`
- Task IDs: `PHASE0_TASKS.txt`
- Demo library: `demo_library/synthetic_demos/`
- WAA baseline plan: `WAA_BASELINE_VALIDATION_PLAN.md`
