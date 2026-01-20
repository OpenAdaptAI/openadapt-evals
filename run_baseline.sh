#!/bin/bash
# Run baseline validation (no demo) on 3 simple tasks

cd /Users/abrichr/oa/src/openadapt-evals

echo "Running baseline validation (no demo)..."

uv run python -m openadapt_evals.benchmarks.cli live \
    --agent api-claude \
    --server http://172.171.112.41:5000 \
    --task-ids notepad_1,chrome_1,file_explorer_1 \
    --max-steps 15 \
    --output benchmark_results/baseline_no_demo \
    --run-name baseline_no_demo

echo "Baseline complete!"
