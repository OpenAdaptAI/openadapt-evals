#!/bin/bash
# Demo Test Collection Script
#
# Automated execution of demo-conditioned prompting validation tests.
# Runs baseline (no demo), treatment (with demo), and negative control (wrong demo).
#
# Usage:
#   ./scripts/run_demo_test.sh                    # Full test (notepad_1, 3 runs each)
#   ./scripts/run_demo_test.sh --task browser_5    # Custom task
#   ./scripts/run_demo_test.sh --pilot             # Quick pilot (1 run each)
#   ./scripts/run_demo_test.sh --help              # Show usage

set -e  # Exit on error

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
SERVER="http://172.171.112.41:5000"
TASK="notepad_1"
RUNS=3
MAX_STEPS=15
PILOT_MODE=false
SKIP_BASELINE=false
SKIP_TREATMENT=false
SKIP_NEGATIVE=false

# Parse arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --task)
      TASK="$2"
      shift 2
      ;;
    --server)
      SERVER="$2"
      shift 2
      ;;
    --runs)
      RUNS="$2"
      shift 2
      ;;
    --pilot)
      PILOT_MODE=true
      RUNS=1
      shift
      ;;
    --skip-baseline)
      SKIP_BASELINE=true
      shift
      ;;
    --skip-treatment)
      SKIP_TREATMENT=true
      shift
      ;;
    --skip-negative)
      SKIP_NEGATIVE=true
      shift
      ;;
    --help)
      echo "Usage: $0 [options]"
      echo ""
      echo "Options:"
      echo "  --task TASK        Task ID to test (default: notepad_1)"
      echo "  --server URL       WAA server URL (default: http://172.171.112.41:5000)"
      echo "  --runs N           Number of runs per scenario (default: 3)"
      echo "  --pilot            Quick pilot mode (1 run per scenario)"
      echo "  --skip-baseline    Skip baseline tests"
      echo "  --skip-treatment   Skip treatment tests"
      echo "  --skip-negative    Skip negative control test"
      echo "  --help             Show this message"
      exit 0
      ;;
    *)
      echo "Unknown option: $1"
      echo "Use --help for usage information"
      exit 1
      ;;
  esac
done

# Print configuration
echo -e "${BLUE}=== Demo Test Collection Script ===${NC}"
echo "Task: $TASK"
echo "Server: $SERVER"
echo "Runs per scenario: $RUNS"
echo "Max steps: $MAX_STEPS"
echo "Pilot mode: $PILOT_MODE"
echo "Start time: $(date)"
echo ""

# Create results directory
RESULTS_BASE="benchmark_results/demo_test_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$RESULTS_BASE"

echo -e "${GREEN}Results will be saved to: $RESULTS_BASE${NC}"
echo ""

# Function to run evaluation
run_eval() {
  local scenario="$1"
  local run_num="$2"
  local demo_arg="$3"
  local output_dir="$RESULTS_BASE/${scenario}_run${run_num}"

  echo -e "${YELLOW}Running $scenario (run $run_num)...${NC}"

  uv run python -m openadapt_evals.benchmarks.cli live \
    --agent api-claude \
    $demo_arg \
    --server "$SERVER" \
    --task-ids "$TASK" \
    --max-steps "$MAX_STEPS" \
    --output-dir "$output_dir" || {
      echo -e "${RED}Error in $scenario run $run_num${NC}"
      return 1
    }

  echo -e "${GREEN}Completed $scenario run $run_num${NC}"
  echo ""
}

# Function to check prerequisites
check_prerequisites() {
  echo -e "${BLUE}Checking prerequisites...${NC}"

  # Check if uv is installed
  if ! command -v uv &> /dev/null; then
    echo -e "${RED}Error: uv not found. Please install it first.${NC}"
    exit 1
  fi

  # Check if demo file exists
  if [[ ! -f "demo_library/synthetic_demos/${TASK}.txt" ]]; then
    echo -e "${YELLOW}Warning: Demo file not found: demo_library/synthetic_demos/${TASK}.txt${NC}"
    echo "Treatment tests may fail."
  fi

  # Check if server is reachable
  echo "Checking server connectivity..."
  if ! uv run python -m openadapt_evals.benchmarks.cli probe --server "$SERVER" &> /dev/null; then
    echo -e "${RED}Error: Server not reachable: $SERVER${NC}"
    echo "Please start the VM and WAA server:"
    echo "  uv run python -m openadapt_evals.benchmarks.cli up"
    exit 1
  fi

  echo -e "${GREEN}Prerequisites OK${NC}"
  echo ""
}

# Main execution
main() {
  # Check prerequisites
  check_prerequisites

  # 1. Baseline runs (no demo)
  if [[ "$SKIP_BASELINE" == false ]]; then
    echo -e "${BLUE}=== Phase 1: Baseline (No Demo) ===${NC}"
    for i in $(seq 1 $RUNS); do
      run_eval "baseline" "$i" "" || true
      sleep 10  # Cool-down between runs
    done
  else
    echo -e "${YELLOW}Skipping baseline tests${NC}"
  fi

  # 2. Treatment runs (with correct demo)
  if [[ "$SKIP_TREATMENT" == false ]]; then
    echo -e "${BLUE}=== Phase 2: Treatment (With Demo) ===${NC}"
    for i in $(seq 1 $RUNS); do
      run_eval "treatment" "$i" "--demo demo_library/synthetic_demos/${TASK}.txt" || true
      sleep 10
    done
  else
    echo -e "${YELLOW}Skipping treatment tests${NC}"
  fi

  # 3. Negative control (wrong demo)
  if [[ "$SKIP_NEGATIVE" == false ]]; then
    echo -e "${BLUE}=== Phase 3: Negative Control (Wrong Demo) ===${NC}"
    # Use a different task's demo (browser_5 if testing notepad_1, vice versa)
    WRONG_DEMO="browser_5"
    if [[ "$TASK" == "browser_5" ]]; then
      WRONG_DEMO="notepad_1"
    fi

    run_eval "negative_control" "1" "--demo demo_library/synthetic_demos/${WRONG_DEMO}.txt" || true
  else
    echo -e "${YELLOW}Skipping negative control test${NC}"
  fi

  # Summary
  echo -e "${GREEN}=== All Tests Complete ===${NC}"
  echo "End time: $(date)"
  echo ""
  echo "Results directory: $RESULTS_BASE"
  echo ""
  echo "To analyze results:"
  echo "  python scripts/analyze_demo_results.py --results-dir $RESULTS_BASE"
  echo ""
  echo "To view individual results:"
  echo "  open ${RESULTS_BASE}/baseline_run1/viewer.html"
  echo "  open ${RESULTS_BASE}/treatment_run1/viewer.html"
  echo "  open ${RESULTS_BASE}/negative_control_run1/viewer.html"
}

# Run main function
main

# Analyze results automatically
echo -e "${BLUE}Analyzing results...${NC}"
python scripts/analyze_demo_results.py --results-dir "$RESULTS_BASE" || {
  echo -e "${YELLOW}Warning: Analysis failed. Run manually:${NC}"
  echo "  python scripts/analyze_demo_results.py --results-dir $RESULTS_BASE"
}
