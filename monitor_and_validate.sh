#!/bin/bash

# Monitor WAA server and automatically run full validation once ready
# Target server: http://172.171.112.41:5000
# Poll interval: 30 seconds

SERVER="http://172.171.112.41:5000"
POLL_INTERVAL=30
MAX_ATTEMPTS=120  # 1 hour maximum wait time (120 * 30 seconds)

echo "=========================================="
echo "WAA Server Monitor & Auto-Validator"
echo "=========================================="
echo "Target server: $SERVER"
echo "Poll interval: ${POLL_INTERVAL}s"
echo "Max wait time: $((MAX_ATTEMPTS * POLL_INTERVAL / 60)) minutes"
echo ""

attempt=1
start_time=$(date +%s)

while [ $attempt -le $MAX_ATTEMPTS ]; do
    current_time=$(date +%s)
    elapsed=$((current_time - start_time))
    elapsed_min=$((elapsed / 60))
    elapsed_sec=$((elapsed % 60))

    echo "[Attempt $attempt/$MAX_ATTEMPTS] (${elapsed_min}m ${elapsed_sec}s elapsed) Probing WAA server..."

    # Probe the server
    if uv run python -m openadapt_evals.benchmarks.cli probe --server "$SERVER" 2>&1; then
        echo ""
        echo "=========================================="
        echo "SUCCESS! WAA server is ready!"
        echo "=========================================="
        echo "Wait time: ${elapsed_min}m ${elapsed_sec}s"
        echo ""
        echo "Starting full validation in 5 seconds..."
        sleep 5

        echo ""
        echo "=========================================="
        echo "RUNNING FULL VALIDATION"
        echo "=========================================="
        echo "Expected runtime: 30-50 minutes"
        echo "Start time: $(date)"
        echo ""

        # Run the full validation script
        bash /Users/abrichr/oa/src/openadapt-evals/run_full_validation.sh

        validation_exit_code=$?

        echo ""
        echo "=========================================="
        echo "VALIDATION COMPLETE"
        echo "=========================================="
        echo "Exit code: $validation_exit_code"
        echo "End time: $(date)"
        echo ""

        if [ $validation_exit_code -eq 0 ]; then
            echo "Full validation completed successfully!"
            exit 0
        else
            echo "Full validation completed with errors (exit code: $validation_exit_code)"
            exit $validation_exit_code
        fi
    fi

    echo "Server not ready yet. Waiting ${POLL_INTERVAL} seconds..."
    echo ""
    sleep $POLL_INTERVAL

    attempt=$((attempt + 1))
done

echo ""
echo "=========================================="
echo "TIMEOUT"
echo "=========================================="
echo "Server did not become ready within $((MAX_ATTEMPTS * POLL_INTERVAL / 60)) minutes"
echo "Please check server status manually"
exit 1
