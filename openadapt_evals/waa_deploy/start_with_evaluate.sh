#!/bin/bash
# Start the evaluate server in background (runs on Docker Linux side)
# The evaluate server provides /evaluate and /task/<id> endpoints using
# WAA's evaluator modules from /client/desktop_env/evaluators/
cd /client
python /evaluate_server.py > /tmp/evaluate_server.log 2>&1 &
echo "Evaluate server started on port 5050 (PID: $!)"

# Execute the command passed as arguments (e.g., /entry.sh --prepare-image false)
exec "$@"
