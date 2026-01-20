#!/bin/bash
# Phase 0 Status Monitor
# Shows current progress, cost, ETA, and recent failures
#
# Usage:
#   ./scripts/phase0_status.sh
#   ./scripts/phase0_status.sh --watch    # Auto-refresh every 10s
#   ./scripts/phase0_status.sh --json     # JSON output

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
OUTPUT_DIR="$PROJECT_ROOT/phase0_results"
CHECKPOINT_FILE="$OUTPUT_DIR/.checkpoint"
COST_LOG="$OUTPUT_DIR/.cost_log.json"

WATCH_MODE=false
JSON_OUTPUT=false

# Parse arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --watch)
      WATCH_MODE=true
      shift
      ;;
    --json)
      JSON_OUTPUT=true
      shift
      ;;
    --output-dir)
      OUTPUT_DIR="$2"
      CHECKPOINT_FILE="$OUTPUT_DIR/.checkpoint"
      COST_LOG="$OUTPUT_DIR/.cost_log.json"
      shift 2
      ;;
    --help)
      cat << EOF
Phase 0 Status Monitor

Shows current progress, cost, ETA, and recent failures.

Usage:
  $0 [options]

Options:
  --watch           Auto-refresh every 10 seconds
  --json            Output as JSON
  --output-dir DIR  Results directory (default: phase0_results)
  --help            Show this message

Examples:
  # Show current status
  $0

  # Watch mode (auto-refresh)
  $0 --watch

  # JSON output for scripting
  $0 --json

EOF
      exit 0
      ;;
    *)
      echo -e "${RED}Unknown option: $1${NC}"
      echo "Use --help for usage information"
      exit 1
      ;;
  esac
done

# Check if results exist
if [[ ! -d "$OUTPUT_DIR" ]]; then
  echo -e "${RED}Error: Results directory not found: $OUTPUT_DIR${NC}"
  echo "Have you started the runner yet?"
  echo "  ./scripts/phase0_runner.sh"
  exit 1
fi

if [[ ! -f "$CHECKPOINT_FILE" ]]; then
  echo -e "${RED}Error: Checkpoint file not found: $CHECKPOINT_FILE${NC}"
  echo "The runner may not have been started yet."
  exit 1
fi

# Get status data
get_status() {
  python3 << 'PYEOF'
import json
import sys
from pathlib import Path
from datetime import datetime, timedelta

# Load checkpoint
checkpoint_file = Path(sys.argv[1])
cost_log_file = Path(sys.argv[2])

with open(checkpoint_file) as f:
    checkpoint = json.load(f)

# Load cost log if exists
cost_data = {"total_cost": 0, "runs": []}
if cost_log_file.exists():
    with open(cost_log_file) as f:
        cost_data = json.load(f)

# Calculate stats
total_evals = checkpoint.get("total_evals", 0)
completed = len(checkpoint.get("completed", []))
failed = len(checkpoint.get("failed", []))
remaining = total_evals - completed

# Calculate progress
progress_pct = (completed / total_evals * 100) if total_evals > 0 else 0

# Calculate ETA
start_time_str = checkpoint.get("start_time")
if start_time_str and completed > 0:
    start_time = datetime.fromisoformat(start_time_str.replace('Z', '+00:00'))
    elapsed = datetime.utcnow() - start_time
    seconds_per_eval = elapsed.total_seconds() / completed
    eta_seconds = seconds_per_eval * remaining
    eta = timedelta(seconds=int(eta_seconds))
else:
    eta = None

# Get cost info
total_cost = cost_data.get("total_cost", 0)
budget_limit = cost_data.get("budget_limit", 400)
budget_pct = (total_cost / budget_limit * 100) if budget_limit > 0 else 0

# Recent failures
recent_failures = checkpoint.get("failed", [])[-5:]

# Output JSON
status = {
    "total_evals": total_evals,
    "completed": completed,
    "failed": failed,
    "remaining": remaining,
    "progress_pct": round(progress_pct, 1),
    "total_cost": round(total_cost, 2),
    "budget_limit": budget_limit,
    "budget_pct": round(budget_pct, 1),
    "eta": str(eta) if eta else "Unknown",
    "recent_failures": recent_failures,
    "start_time": start_time_str,
}

print(json.dumps(status, indent=2))
PYEOF
}

# Display status (pretty)
display_status() {
  local status=$(get_status "$CHECKPOINT_FILE" "$COST_LOG")

  if [[ "$JSON_OUTPUT" == true ]]; then
    echo "$status"
    return
  fi

  # Parse JSON
  local total_evals=$(echo "$status" | python3 -c "import sys, json; print(json.load(sys.stdin)['total_evals'])")
  local completed=$(echo "$status" | python3 -c "import sys, json; print(json.load(sys.stdin)['completed'])")
  local failed=$(echo "$status" | python3 -c "import sys, json; print(json.load(sys.stdin)['failed'])")
  local remaining=$(echo "$status" | python3 -c "import sys, json; print(json.load(sys.stdin)['remaining'])")
  local progress_pct=$(echo "$status" | python3 -c "import sys, json; print(json.load(sys.stdin)['progress_pct'])")
  local total_cost=$(echo "$status" | python3 -c "import sys, json; print(json.load(sys.stdin)['total_cost'])")
  local budget_limit=$(echo "$status" | python3 -c "import sys, json; print(json.load(sys.stdin)['budget_limit'])")
  local budget_pct=$(echo "$status" | python3 -c "import sys, json; print(json.load(sys.stdin)['budget_pct'])")
  local eta=$(echo "$status" | python3 -c "import sys, json; print(json.load(sys.stdin)['eta'])")

  # Clear screen in watch mode
  if [[ "$WATCH_MODE" == true ]]; then
    clear
  fi

  # Header
  echo -e "${BOLD}${BLUE}╔════════════════════════════════════════════════════════════════╗${NC}"
  echo -e "${BOLD}${BLUE}║${NC}${BOLD}            Phase 0: Prompting Baseline Status                 ${BLUE}║${NC}"
  echo -e "${BOLD}${BLUE}╚════════════════════════════════════════════════════════════════╝${NC}"
  echo ""
  echo -e "${BOLD}Last Updated:${NC} $(date)"
  echo ""

  # Progress
  echo -e "${BOLD}${CYAN}Progress:${NC}"
  echo -e "  Completed: ${GREEN}${completed}${NC} / ${total_evals} (${progress_pct}%)"
  echo -e "  Failed:    ${RED}${failed}${NC}"
  echo -e "  Remaining: ${YELLOW}${remaining}${NC}"
  echo ""

  # Progress bar
  local bar_width=50
  local filled=$((completed * bar_width / total_evals))
  local empty=$((bar_width - filled))
  echo -n "  ["
  for ((i=0; i<filled; i++)); do echo -n "█"; done
  for ((i=0; i<empty; i++)); do echo -n "░"; done
  echo "] ${progress_pct}%"
  echo ""

  # Cost
  echo -e "${BOLD}${CYAN}Cost:${NC}"
  echo -e "  Total:  \$${total_cost} / \$${budget_limit} (${budget_pct}%)"

  if (( $(python3 -c "print(1 if $budget_pct >= 90 else 0)") )); then
    echo -e "  ${RED}${BOLD}WARNING: Approaching budget limit!${NC}"
  elif (( $(python3 -c "print(1 if $budget_pct >= 75 else 0)") )); then
    echo -e "  ${YELLOW}Caution: 75%+ of budget used${NC}"
  fi

  # Cost bar
  local cost_bar_width=50
  local cost_filled=$(python3 -c "print(int($budget_pct * $cost_bar_width / 100))")
  local cost_empty=$((cost_bar_width - cost_filled))
  echo -n "  ["
  for ((i=0; i<cost_filled; i++)); do echo -n "█"; done
  for ((i=0; i<cost_empty; i++)); do echo -n "░"; done
  echo "] ${budget_pct}%"
  echo ""

  # ETA
  echo -e "${BOLD}${CYAN}Time:${NC}"
  echo -e "  ETA: ${eta}"
  echo ""

  # Recent failures
  if [[ $failed -gt 0 ]]; then
    echo -e "${BOLD}${YELLOW}Recent Failures:${NC}"
    echo "$status" | python3 << 'PYEOF'
import json
import sys

data = json.load(sys.stdin)
failures = data.get("recent_failures", [])

if not failures:
    print("  (None)")
else:
    for f in failures:
        eval_id = f.get("id", "unknown")
        error = f.get("error", "unknown error")
        print(f"  - {eval_id}")
        print(f"    Error: {error}")
PYEOF
    echo ""

    if [[ $failed -gt 5 ]]; then
      echo -e "  ${CYAN}... and $((failed - 5)) more (see $CHECKPOINT_FILE)${NC}"
      echo ""
    fi
  fi

  # Next steps
  echo -e "${BOLD}${CYAN}Next Steps:${NC}"
  echo ""

  if [[ $remaining -gt 0 ]]; then
    echo -e "  ${YELLOW}Evaluation in progress...${NC}"
    echo ""
    echo -e "  To see detailed logs:"
    echo -e "    ${CYAN}tail -f phase0_results/*/*.log${NC}"
  else
    echo -e "  ${GREEN}All evaluations complete!${NC}"
    echo ""
    echo -e "  Analyze results:"
    echo -e "    ${CYAN}python scripts/phase0_analyze.py${NC}"
  fi
  echo ""

  if [[ "$WATCH_MODE" == true ]]; then
    echo -e "${CYAN}Refreshing in 10 seconds... (Ctrl+C to stop)${NC}"
  fi
}

# Main
main() {
  if [[ "$WATCH_MODE" == true ]]; then
    while true; do
      display_status
      sleep 10
    done
  else
    display_status
  fi
}

main
