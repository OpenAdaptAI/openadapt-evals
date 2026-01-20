#!/bin/bash
# Full WAA integration validation: baseline + demo-conditioned tests

set -e  # Exit on error

cd /Users/abrichr/oa/src/openadapt-evals

echo "========================================="
echo "WAA Integration Validation"
echo "========================================="

# Step 1: Wait for WAA server to be ready
echo ""
echo "Step 1: Checking WAA server..."
uv run python -m openadapt_evals.benchmarks.cli probe --server http://172.171.112.41:5000 --wait
echo "✅ WAA server is ready!"

# Step 2: Run baseline (no demo)
echo ""
echo "Step 2: Running BASELINE (no demo)..."
echo "Tasks: notepad_1, chrome_1, file_explorer_1"
echo "Max steps: 15 per task"
echo ""

uv run python -m openadapt_evals.benchmarks.cli live \
    --agent api-claude \
    --server http://172.171.112.41:5000 \
    --task-ids notepad_1,chrome_1,file_explorer_1 \
    --max-steps 15 \
    --output benchmark_results/baseline_no_demo \
    --run-name baseline_no_demo

echo "✅ Baseline complete!"

# Step 3: Run demo-conditioned test
echo ""
echo "Step 3: Running TREATMENT (with demos)..."
echo "Tasks: notepad_1, file_explorer_1"
echo "Using synthetic demos from demo_library/"
echo ""

# Run notepad with demo
uv run python -m openadapt_evals.benchmarks.cli live \
    --agent api-claude \
    --server http://172.171.112.41:5000 \
    --task-ids notepad_1 \
    --demo demo_library/synthetic_demos/notepad_1.txt \
    --max-steps 15 \
    --output benchmark_results/treatment_with_demo \
    --run-name treatment_notepad_demo

# Run file_explorer with demo
uv run python -m openadapt_evals.benchmarks.cli live \
    --agent api-claude \
    --server http://172.171.112.41:5000 \
    --task-ids file_explorer_1 \
    --demo demo_library/synthetic_demos/file_explorer_1.txt \
    --max-steps 15 \
    --output benchmark_results/treatment_with_demo \
    --run-name treatment_file_explorer_demo

echo "✅ Demo tests complete!"

# Step 4: Generate viewers
echo ""
echo "Step 4: Generating HTML viewers..."

uv run python -m openadapt_evals.benchmarks.cli view \
    --run-name baseline_no_demo \
    --benchmark-dir benchmark_results/baseline_no_demo \
    --embed-screenshots

uv run python -m openadapt_evals.benchmarks.cli view \
    --run-name treatment_notepad_demo \
    --benchmark-dir benchmark_results/treatment_with_demo \
    --embed-screenshots

uv run python -m openadapt_evals.benchmarks.cli view \
    --run-name treatment_file_explorer_demo \
    --benchmark-dir benchmark_results/treatment_with_demo \
    --embed-screenshots

echo "✅ Viewers generated!"

# Step 5: Print summary
echo ""
echo "========================================="
echo "VALIDATION COMPLETE!"
echo "========================================="
echo ""
echo "Results saved to:"
echo "  - benchmark_results/baseline_no_demo/"
echo "  - benchmark_results/treatment_with_demo/"
echo ""
echo "Next steps:"
echo "  1. Review summary.json files for success rates"
echo "  2. Open HTML viewers to inspect task executions"
echo "  3. Compare baseline vs treatment performance"
echo ""
