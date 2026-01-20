#!/bin/bash
# Phase 0 Prompting Baseline Runner
# Runs 240 evaluations for demo-augmentation research
#
# Automates running:
# - 20 tasks × 2 models × 2 conditions × 3 trials = 240 evaluations
# - Zero-shot vs demo-conditioned comparison
# - Claude Sonnet 4.5 and GPT-4 models
#
# Features:
# - Checkpoint/resume on failure
# - Rate limit handling with exponential backoff
# - Cost tracking with budget alerts
# - Progress tracking and ETA
# - Systematic result organization
#
# Usage:
#   ./scripts/phase0_runner.sh                     # Run all 240 evaluations
#   ./scripts/phase0_runner.sh --dry-run           # Show plan without executing
#   ./scripts/phase0_runner.sh --tasks notepad_1   # Test with single task
#   ./scripts/phase0_runner.sh --trials 1          # Quick test (80 evals)
#   ./scripts/phase0_runner.sh --resume            # Resume from checkpoint

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m' # No Color

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
TASK_FILE="$PROJECT_ROOT/PHASE0_TASKS.txt"
MODELS=("claude-sonnet-4-5" "gpt-4")
CONDITIONS=("zero-shot" "demo-conditioned")
TRIALS=3
OUTPUT_DIR="$PROJECT_ROOT/phase0_results"
CHECKPOINT_FILE="$OUTPUT_DIR/.checkpoint"
COST_LOG="$OUTPUT_DIR/.cost_log.json"
SERVER_URL=""
MAX_STEPS=15
BUDGET_LIMIT=400  # USD
DRY_RUN=false
RESUME=false
CUSTOM_TASKS=""

# Cost estimates (per API call, average)
CLAUDE_COST_PER_CALL=0.50  # $0.50 avg (varies by task)
GPT4_COST_PER_CALL=1.50    # $1.50 avg (varies by task)

# Parse arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --dry-run)
      DRY_RUN=true
      shift
      ;;
    --resume)
      RESUME=true
      shift
      ;;
    --tasks)
      CUSTOM_TASKS="$2"
      shift 2
      ;;
    --trials)
      TRIALS="$2"
      shift 2
      ;;
    --server)
      SERVER_URL="$2"
      shift 2
      ;;
    --budget)
      BUDGET_LIMIT="$2"
      shift 2
      ;;
    --output-dir)
      OUTPUT_DIR="$2"
      CHECKPOINT_FILE="$OUTPUT_DIR/.checkpoint"
      COST_LOG="$OUTPUT_DIR/.cost_log.json"
      shift 2
      ;;
    --help)
      cat << EOF
Phase 0 Prompting Baseline Runner

Runs 240 evaluations (20 tasks × 2 models × 2 conditions × 3 trials) for
demo-augmentation research baseline.

Usage:
  $0 [options]

Options:
  --dry-run              Show execution plan without running
  --resume               Resume from checkpoint
  --tasks TASK_ID        Run specific task(s) (comma-separated)
  --trials N             Number of trials per condition (default: 3)
  --server URL           WAA server URL (auto-detected if not specified)
  --budget USD           Budget limit in USD (default: 400)
  --output-dir DIR       Output directory (default: phase0_results)
  --help                 Show this message

Examples:
  # Full run (240 evaluations)
  $0

  # Dry run (show plan)
  $0 --dry-run

  # Test with single task
  $0 --tasks notepad_1 --trials 1

  # Resume from checkpoint
  $0 --resume

Cost Estimates:
  - Claude Sonnet 4.5: ~\$0.50 per task
  - GPT-4: ~\$1.50 per task
  - Total for 240 evaluations: ~\$240-400

Output Structure:
  phase0_results/
  ├── zero-shot/
  │   ├── claude-sonnet-4-5/
  │   │   ├── notepad_1_trial1.json
  │   │   ├── notepad_1_trial2.json
  │   │   └── ...
  │   └── gpt-4/
  └── demo-conditioned/
      ├── claude-sonnet-4-5/
      └── gpt-4/

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

# Load tasks
load_tasks() {
  if [[ -n "$CUSTOM_TASKS" ]]; then
    echo "$CUSTOM_TASKS" | tr ',' '\n'
  else
    grep -v '^#' "$TASK_FILE" | grep -v '^[[:space:]]*$'
  fi
}

TASKS=($(load_tasks))
TOTAL_TASKS=${#TASKS[@]}
TOTAL_EVALS=$((TOTAL_TASKS * ${#MODELS[@]} * ${#CONDITIONS[@]} * TRIALS))

# Initialize cost tracking
init_cost_tracking() {
  mkdir -p "$OUTPUT_DIR"
  if [[ ! -f "$COST_LOG" ]] || [[ "$RESUME" == false ]]; then
    cat > "$COST_LOG" << EOF
{
  "start_time": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")",
  "budget_limit": $BUDGET_LIMIT,
  "runs": []
}
EOF
  fi
}

# Add cost entry
log_cost() {
  local model="$1"
  local task="$2"
  local cost="$3"
  local tokens_in="$4"
  local tokens_out="$5"

  python3 << EOF
import json
from datetime import datetime

with open("$COST_LOG", "r") as f:
    data = json.load(f)

data["runs"].append({
    "timestamp": datetime.utcnow().isoformat() + "Z",
    "model": "$model",
    "task": "$task",
    "cost": $cost,
    "tokens_input": $tokens_in,
    "tokens_output": $tokens_out
})

total_cost = sum(r["cost"] for r in data["runs"])
data["total_cost"] = round(total_cost, 2)
data["runs_completed"] = len(data["runs"])

with open("$COST_LOG", "w") as f:
    json.dump(data, f, indent=2)

print(f"{total_cost:.2f}")
EOF
}

# Get current total cost
get_total_cost() {
  python3 << EOF
import json
try:
    with open("$COST_LOG", "r") as f:
        data = json.load(f)
    print(data.get("total_cost", 0))
except:
    print(0)
EOF
}

# Check budget
check_budget() {
  local total_cost=$(get_total_cost)
  local budget_pct=$(python3 -c "print(int($total_cost / $BUDGET_LIMIT * 100))")

  if (( $(python3 -c "print(1 if $total_cost > $BUDGET_LIMIT else 0)") )); then
    echo -e "${RED}${BOLD}BUDGET EXCEEDED!${NC}"
    echo -e "${RED}Total cost: \$$total_cost / \$$BUDGET_LIMIT${NC}"
    echo -e "${YELLOW}Stopping execution. Results saved to: $OUTPUT_DIR${NC}"
    exit 1
  elif (( budget_pct >= 90 )); then
    echo -e "${YELLOW}Warning: Budget at ${budget_pct}% (\$$total_cost / \$$BUDGET_LIMIT)${NC}"
  fi
}

# Initialize checkpoint
init_checkpoint() {
  if [[ ! -f "$CHECKPOINT_FILE" ]] || [[ "$RESUME" == false ]]; then
    cat > "$CHECKPOINT_FILE" << EOF
{
  "start_time": "$(date -u +"%Y-%m-%dT%H:%M:%SZ")",
  "total_evals": $TOTAL_EVALS,
  "completed": [],
  "failed": []
}
EOF
  fi
}

# Check if eval is completed
is_completed() {
  local eval_id="$1"
  python3 << EOF
import json
with open("$CHECKPOINT_FILE", "r") as f:
    data = json.load(f)
completed = data.get("completed", [])
print("yes" if "$eval_id" in completed else "no")
EOF
}

# Mark eval as completed
mark_completed() {
  local eval_id="$1"
  python3 << EOF
import json
with open("$CHECKPOINT_FILE", "r") as f:
    data = json.load(f)
if "$eval_id" not in data["completed"]:
    data["completed"].append("$eval_id")
with open("$CHECKPOINT_FILE", "w") as f:
    json.dump(data, f, indent=2)
EOF
}

# Mark eval as failed
mark_failed() {
  local eval_id="$1"
  local error="$2"
  python3 << EOF
import json
with open("$CHECKPOINT_FILE", "r") as f:
    data = json.load(f)
data["failed"].append({"id": "$eval_id", "error": "$error"})
with open("$CHECKPOINT_FILE", "w") as f:
    json.dump(data, f, indent=2)
EOF
}

# Get progress
get_progress() {
  python3 << EOF
import json
with open("$CHECKPOINT_FILE", "r") as f:
    data = json.load(f)
print(len(data.get("completed", [])))
EOF
}

# Estimate ETA
estimate_eta() {
  local completed=$(get_progress)
  local remaining=$((TOTAL_EVALS - completed))

  if [[ $completed -eq 0 ]]; then
    echo "Unknown (no data yet)"
    return
  fi

  # Estimate ~3 minutes per eval (conservative)
  local minutes_per_eval=3
  local eta_minutes=$((remaining * minutes_per_eval))
  local eta_hours=$((eta_minutes / 60))

  if [[ $eta_hours -gt 0 ]]; then
    echo "${eta_hours}h $((eta_minutes % 60))m"
  else
    echo "${eta_minutes}m"
  fi
}

# Detect server URL
detect_server() {
  if [[ -n "$SERVER_URL" ]]; then
    echo "$SERVER_URL"
    return
  fi

  # Try to get VM IP from Azure
  local vm_ip=$(az vm show --name waa-eval-vm --resource-group OPENADAPT-AGENTS --show-details --query publicIps -o tsv 2>/dev/null || echo "")

  if [[ -n "$vm_ip" ]]; then
    echo "http://${vm_ip}:5000"
  else
    echo ""
  fi
}

# Run single evaluation
run_single_evaluation() {
  local condition="$1"
  local model="$2"
  local task="$3"
  local trial="$4"

  local eval_id="${condition}/${model}/${task}_trial${trial}"

  # Check if already completed
  if [[ "$RESUME" == true ]] && [[ $(is_completed "$eval_id") == "yes" ]]; then
    echo -e "${CYAN}[SKIP]${NC} $eval_id (already completed)"
    return 0
  fi

  # Prepare output directory
  local model_slug=$(echo "$model" | tr '/' '-')
  local output_subdir="$OUTPUT_DIR/${condition}/${model_slug}"
  mkdir -p "$output_subdir"

  local output_file="$output_subdir/${task}_trial${trial}.json"

  # Prepare demo argument
  local demo_arg=""
  if [[ "$condition" == "demo-conditioned" ]]; then
    demo_arg="--demo $PROJECT_ROOT/demo_library/synthetic_demos/${task}.txt"
  fi

  # Prepare agent argument
  local agent_arg=""
  if [[ "$model" == "claude-sonnet-4-5" ]]; then
    agent_arg="--agent api-claude"
  elif [[ "$model" == "gpt-4" ]]; then
    agent_arg="--agent api-openai"
  fi

  echo -e "${BLUE}[RUN]${NC} $eval_id"

  if [[ "$DRY_RUN" == true ]]; then
    echo "  Command: uv run python -m openadapt_evals.benchmarks.cli live $agent_arg $demo_arg --server $SERVER_URL --task-ids $task --max-steps $MAX_STEPS --output-dir $output_subdir"
    mark_completed "$eval_id"
    return 0
  fi

  # Run evaluation with retry logic
  local max_retries=3
  local retry_count=0
  local success=false

  while [[ $retry_count -lt $max_retries ]]; do
    if uv run python -m openadapt_evals.benchmarks.cli live \
      $agent_arg \
      $demo_arg \
      --server "$SERVER_URL" \
      --task-ids "$task" \
      --max-steps "$MAX_STEPS" \
      --output-dir "$output_subdir" 2>&1 | tee "${output_subdir}/${task}_trial${trial}.log"; then

      success=true
      break
    else
      retry_count=$((retry_count + 1))
      if [[ $retry_count -lt $max_retries ]]; then
        local backoff=$((retry_count * 30))
        echo -e "${YELLOW}[RETRY]${NC} Attempt $retry_count failed, retrying in ${backoff}s..."
        sleep $backoff
      fi
    fi
  done

  if [[ "$success" == true ]]; then
    # Estimate cost
    local cost=0
    if [[ "$model" == "claude-sonnet-4-5" ]]; then
      cost=$CLAUDE_COST_PER_CALL
    elif [[ "$model" == "gpt-4" ]]; then
      cost=$GPT4_COST_PER_CALL
    fi

    # Log cost (tokens would come from actual run, using estimates here)
    log_cost "$model" "$task" "$cost" "5000" "1000" > /dev/null

    mark_completed "$eval_id"
    echo -e "${GREEN}[DONE]${NC} $eval_id (cost: \$$cost)"

    # Check budget after each run
    check_budget
  else
    mark_failed "$eval_id" "Failed after $max_retries retries"
    echo -e "${RED}[FAIL]${NC} $eval_id"
  fi

  # Rate limiting: wait between calls
  sleep 5
}

# Print header
print_header() {
  echo -e "${BOLD}${BLUE}╔════════════════════════════════════════════════════════════════╗${NC}"
  echo -e "${BOLD}${BLUE}║${NC}${BOLD}     Phase 0: Demo-Augmentation Prompting Baseline Runner     ${BLUE}║${NC}"
  echo -e "${BOLD}${BLUE}╚════════════════════════════════════════════════════════════════╝${NC}"
  echo ""
  echo -e "${BOLD}Configuration:${NC}"
  echo -e "  Tasks:       ${TOTAL_TASKS} ($(echo ${TASKS[@]} | tr ' ' ','))"
  echo -e "  Models:      ${#MODELS[@]} (${MODELS[@]})"
  echo -e "  Conditions:  ${#CONDITIONS[@]} (${CONDITIONS[@]})"
  echo -e "  Trials:      ${TRIALS}"
  echo -e "  Total Evals: ${BOLD}${TOTAL_EVALS}${NC}"
  echo ""
  echo -e "${BOLD}Cost Estimate:${NC}"
  local claude_calls=$((TOTAL_TASKS * TRIALS * 2))  # 2 conditions
  local gpt4_calls=$((TOTAL_TASKS * TRIALS * 2))
  local est_cost=$(python3 -c "print(f'{$claude_calls * $CLAUDE_COST_PER_CALL + $gpt4_calls * $GPT4_COST_PER_CALL:.2f}')")
  echo -e "  Claude calls: $claude_calls × \$$CLAUDE_COST_PER_CALL = \$$(python3 -c "print(f'{$claude_calls * $CLAUDE_COST_PER_CALL:.2f}')")"
  echo -e "  GPT-4 calls:  $gpt4_calls × \$$GPT4_COST_PER_CALL = \$$(python3 -c "print(f'{$gpt4_calls * $GPT4_COST_PER_CALL:.2f}')")"
  echo -e "  ${BOLD}Total: \$${est_cost}${NC} (budget: \$${BUDGET_LIMIT})"
  echo ""
  echo -e "${BOLD}Output:${NC}"
  echo -e "  Directory:   $OUTPUT_DIR"
  echo -e "  Checkpoint:  $CHECKPOINT_FILE"
  echo -e "  Cost Log:    $COST_LOG"
  echo ""

  if [[ "$RESUME" == true ]]; then
    local completed=$(get_progress)
    echo -e "${YELLOW}Resume Mode:${NC}"
    echo -e "  Completed:   $completed / $TOTAL_EVALS"
    echo -e "  Remaining:   $((TOTAL_EVALS - completed))"
    echo ""
  fi

  if [[ "$DRY_RUN" == true ]]; then
    echo -e "${YELLOW}${BOLD}DRY RUN MODE - No API calls will be made${NC}"
    echo ""
  fi
}

# Print progress
print_progress() {
  local completed=$(get_progress)
  local pct=$((completed * 100 / TOTAL_EVALS))
  local total_cost=$(get_total_cost)
  local eta=$(estimate_eta)

  echo ""
  echo -e "${BOLD}Progress: ${completed}/${TOTAL_EVALS} (${pct}%)${NC}"
  echo -e "Cost: \$$total_cost / \$$BUDGET_LIMIT"
  echo -e "ETA: $eta"
  echo ""
}

# Main execution
main() {
  # Detect server
  SERVER_URL=$(detect_server)
  if [[ -z "$SERVER_URL" ]]; then
    echo -e "${RED}Error: Could not detect WAA server URL${NC}"
    echo "Please specify with --server or start the VM:"
    echo "  uv run python -m openadapt_evals.benchmarks.cli up"
    exit 1
  fi

  # Initialize
  init_cost_tracking
  init_checkpoint

  # Print header
  print_header

  if [[ "$DRY_RUN" == false ]]; then
    # Verify server is reachable
    echo -e "${BLUE}Verifying server connectivity...${NC}"
    if ! uv run python -m openadapt_evals.benchmarks.cli probe --server "$SERVER_URL" &> /dev/null; then
      echo -e "${RED}Error: Server not reachable: $SERVER_URL${NC}"
      echo "Please start the VM and WAA server:"
      echo "  uv run python -m openadapt_evals.benchmarks.cli up"
      exit 1
    fi
    echo -e "${GREEN}Server OK: $SERVER_URL${NC}"
    echo ""
  fi

  # Main loop
  local start_time=$(date +%s)

  for condition in "${CONDITIONS[@]}"; do
    echo -e "${BOLD}${CYAN}=== Condition: $condition ===${NC}"
    echo ""

    for model in "${MODELS[@]}"; do
      echo -e "${BOLD}Model: $model${NC}"

      for task in "${TASKS[@]}"; do
        for trial in $(seq 1 $TRIALS); do
          run_single_evaluation "$condition" "$model" "$task" "$trial"
        done
      done

      print_progress
    done
  done

  # Summary
  local end_time=$(date +%s)
  local duration=$((end_time - start_time))
  local hours=$((duration / 3600))
  local minutes=$(((duration % 3600) / 60))

  echo ""
  echo -e "${BOLD}${GREEN}╔════════════════════════════════════════════════════════════════╗${NC}"
  echo -e "${BOLD}${GREEN}║${NC}${BOLD}                    Execution Complete                          ${GREEN}║${NC}"
  echo -e "${BOLD}${GREEN}╚════════════════════════════════════════════════════════════════╝${NC}"
  echo ""
  echo -e "${BOLD}Summary:${NC}"
  echo -e "  Total Evals:  $(get_progress) / $TOTAL_EVALS"
  echo -e "  Total Cost:   \$$(get_total_cost)"
  echo -e "  Duration:     ${hours}h ${minutes}m"
  echo -e "  Results:      $OUTPUT_DIR"
  echo ""
  echo -e "${BOLD}Next Steps:${NC}"
  echo ""
  echo -e "1. Check progress:"
  echo -e "   ${CYAN}./scripts/phase0_status.sh${NC}"
  echo ""
  echo -e "2. Analyze results:"
  echo -e "   ${CYAN}python scripts/phase0_analyze.py${NC}"
  echo ""
  echo -e "3. View individual runs:"
  echo -e "   ${CYAN}open phase0_results/zero-shot/claude-sonnet-4-5/notepad_1_trial1.json${NC}"
  echo ""

  # Check for failures
  local failed_count=$(python3 -c "import json; print(len(json.load(open('$CHECKPOINT_FILE'))['failed']))")
  if [[ $failed_count -gt 0 ]]; then
    echo -e "${YELLOW}Warning: $failed_count evaluation(s) failed${NC}"
    echo -e "See $CHECKPOINT_FILE for details"
    echo ""
  fi
}

# Run main
main
