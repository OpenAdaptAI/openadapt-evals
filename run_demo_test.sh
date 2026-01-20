#!/bin/bash
# Run demo-conditioned test with synthetic demos

cd /Users/abrichr/oa/src/openadapt-evals

echo "Running demo-conditioned test..."

# For notepad and file_explorer, we have exact matching demos
# For chrome, we'll use browser_1 demo as a close match

uv run python -m openadapt_evals.benchmarks.cli live \
    --agent api-claude \
    --server http://172.171.112.41:5000 \
    --task-ids notepad_1,file_explorer_1 \
    --demo demo_library/synthetic_demos/notepad_1.txt \
    --max-steps 15 \
    --output benchmark_results/treatment_with_demo \
    --run-name treatment_with_demo

echo "Demo test complete!"
