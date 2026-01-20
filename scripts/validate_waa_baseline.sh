#!/bin/bash
# Validate WAA Baseline - Run vanilla WAA to establish baseline performance
#
# This script runs vanilla WAA (via run.py) on a small set of tasks to:
# 1. Verify WAA setup is working
# 2. Establish baseline success rate
# 3. Validate task configs and evaluators
#
# Prerequisites:
# - Azure VM running with waa-auto container
# - OpenAI API key (GPT-4o access)
# - WAA evaluation_examples_windows directory

set -e

# Configuration
VM_IP="${WAA_VM_IP:-localhost}"
DOCKER_CONTAINER="waa-auto"
WAA_CLIENT_DIR="/waa/client"
RESULTS_DIR="/tmp/waa_baseline_$(date +%Y%m%d_%H%M%S)"

echo "=== WAA Baseline Validation ==="
echo "VM IP: $VM_IP"
echo "Results: $RESULTS_DIR"
echo ""

# Check OpenAI API key
if [ -z "$OPENAI_API_KEY" ]; then
    echo "ERROR: OPENAI_API_KEY not set"
    echo "Export it: export OPENAI_API_KEY=sk-..."
    exit 1
fi

echo "Step 1: Creating minimal test configuration..."

# Create test_baseline.json with 3 simple tasks
cat > /tmp/test_baseline.json << 'EOF'
{
    "notepad": ["366de66e-cbae-4d72-b042-26390db2b145-WOS"],
    "file_explorer": ["016c9a9d-f2b9-4428-8fdb-f74f4439ece6-WOS"],
    "clock": ["02F10F89-7171-4D37-8550-A00BA8930CDF-WOS"]
}
EOF

# Create config.json with API key
cat > /tmp/config.json << EOF
{
    "OPENAI_API_KEY": "$OPENAI_API_KEY"
}
EOF

echo "Step 2: Copying test configs to VM container..."

# Copy configs to container
docker cp /tmp/test_baseline.json $DOCKER_CONTAINER:$WAA_CLIENT_DIR/test_baseline.json
docker cp /tmp/config.json $DOCKER_CONTAINER:$WAA_CLIENT_DIR/config.json

echo "Step 3: Running vanilla WAA evaluation..."
echo "This will take ~5-10 minutes (3 tasks, max 15 steps each)..."
echo ""

# Run WAA evaluation inside container
docker exec $DOCKER_CONTAINER bash -c "
cd $WAA_CLIENT_DIR && \
python run.py \
    --test_all_meta_path test_baseline.json \
    --model gpt-4o \
    --agent_name navi \
    --som_origin oss \
    --max_steps 15 \
    --observation_type screenshot_a11y_tree \
    --action_space code_block \
    --result_dir $RESULTS_DIR \
    --emulator_ip 172.30.0.2
"

echo ""
echo "Step 4: Extracting results..."

# Get results from container
docker exec $DOCKER_CONTAINER bash -c "
cd $RESULTS_DIR

echo '=== Task Results ==='
for domain_dir in */; do
    domain=\${domain_dir%/}
    if [ -d \"\$domain\" ]; then
        for task_dir in \$domain/*/; do
            task=\${task_dir%/}
            task_name=\$(basename \"\$task\")
            result_file=\"\$task/result.txt\"

            if [ -f \"\$result_file\" ]; then
                score=\$(cat \"\$result_file\")
                echo \"[\$domain] \$task_name: \$score\"
            else
                echo \"[\$domain] \$task_name: ERROR (no result file)\"
            fi
        done
    fi
done

echo ''
echo '=== Overall Stats ==='
echo \"Total tasks: \$(find . -name 'result.txt' | wc -l)\"

# Calculate average score
total=0
count=0
for result in \$(find . -name 'result.txt'); do
    score=\$(cat \"\$result\")
    total=\$(echo \"\$total + \$score\" | bc)
    count=\$((count + 1))
done

if [ \$count -gt 0 ]; then
    avg=\$(echo \"scale=2; \$total / \$count\" | bc)
    echo \"Average score: \$avg\"
    echo \"Success rate: \$(echo \"scale=0; \$avg * 100\" | bc)%\"
else
    echo \"No results found!\"
fi
"

echo ""
echo "Step 5: Downloading detailed results..."

# Copy results directory from container to local
mkdir -p ./baseline_results
docker cp $DOCKER_CONTAINER:$RESULTS_DIR ./baseline_results/

echo ""
echo "=== Baseline Validation Complete ==="
echo ""
echo "Results saved to: ./baseline_results/"
echo ""
echo "Next steps:"
echo "1. Review detailed results in ./baseline_results/"
echo "2. Verify task configs loaded properly (check logs for 'TESTING ON TASK CONFIG PATH')"
echo "3. Verify evaluators ran (check logs for 'Running evaluator(s)')"
echo "4. Compare with our WAALiveAdapter implementation"
echo ""
echo "To run with our integration:"
echo "  uv run python -m openadapt_evals.benchmarks.cli live \\"
echo "    --agent api-claude \\"
echo "    --server http://localhost:5000 \\"
echo "    --waa-examples-path /path/to/evaluation_examples_windows \\"
echo "    --task-ids notepad_366de66e-cbae-4d72-b042-26390db2b145-WOS,file_explorer_016c9a9d-f2b9-4428-8fdb-f74f4439ece6-WOS,clock_02F10F89-7171-4D37-8550-A00BA8930CDF-WOS"
