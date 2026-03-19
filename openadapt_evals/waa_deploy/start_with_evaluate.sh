#!/bin/bash
# Start the evaluate server in background (runs on Docker Linux side)
# The evaluate server provides /evaluate and /task/<id> endpoints using
# WAA's evaluator modules from /client/desktop_env/evaluators/

EVAL_SERVER="/evaluate_server.py"

# Validate evaluate_server.py before starting
if [ -L "$EVAL_SERVER" ]; then
    echo "ERROR: $EVAL_SERVER is a symlink to $(readlink "$EVAL_SERVER"), not a real file." >&2
    echo "The Docker image was built incorrectly. Rebuild with evaluate_server.py in the build context." >&2
elif [ ! -f "$EVAL_SERVER" ]; then
    echo "ERROR: $EVAL_SERVER does not exist." >&2
    echo "The Docker image is missing the evaluate server. Rebuild the image." >&2
elif [ ! -s "$EVAL_SERVER" ]; then
    echo "ERROR: $EVAL_SERVER is empty (0 bytes)." >&2
    echo "The Docker image was built with a corrupt evaluate_server.py. Rebuild the image." >&2
elif ! grep -q '/probe' "$EVAL_SERVER" || ! grep -q '/evaluate' "$EVAL_SERVER"; then
    echo "ERROR: $EVAL_SERVER is missing expected Flask routes (/probe, /evaluate)." >&2
    echo "File content (first 5 lines):" >&2
    head -5 "$EVAL_SERVER" >&2
    echo "The file may be corrupt. Rebuild the image." >&2
else
    cd /client
    python "$EVAL_SERVER" > /tmp/evaluate_server.log 2>&1 &
    echo "Evaluate server started on port 5050 (PID: $!)"
fi

# Execute the command passed as arguments (e.g., /entry.sh --prepare-image false)
# If no CMD is provided (empty $@), fall through to /run/entry.sh which is the
# dockurr/windows entrypoint that boots the Windows VM.
if [ $# -eq 0 ]; then
    echo "No CMD specified, using default: /run/entry.sh"
    exec /run/entry.sh
else
    exec "$@"
fi
