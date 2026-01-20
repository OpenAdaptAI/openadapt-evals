#!/bin/bash

# Helper script to check monitoring progress

OUTPUT_FILE="/private/tmp/claude/-Users-abrichr-oa-src/tasks/ba37ebd.output"

if [ ! -f "$OUTPUT_FILE" ]; then
    echo "Monitor is not running or output file not found."
    exit 1
fi

echo "=========================================="
echo "MONITOR STATUS"
echo "=========================================="
echo ""

# Show last 40 lines of output
tail -40 "$OUTPUT_FILE"

echo ""
echo "=========================================="
echo "To follow live updates, run:"
echo "  tail -f $OUTPUT_FILE"
echo "=========================================="
