#!/bin/bash
# Phase 0 Test Harness
# Tests the Phase 0 runner infrastructure without making API calls
#
# Usage:
#   ./scripts/phase0_test.sh                # Run all tests
#   ./scripts/phase0_test.sh --quick        # Quick smoke test only
#   ./scripts/phase0_test.sh --integration  # Full integration test (1 task)

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
TEST_OUTPUT="$PROJECT_ROOT/phase0_test_results"

QUICK_MODE=false
INTEGRATION_MODE=false

# Parse arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    --quick)
      QUICK_MODE=true
      shift
      ;;
    --integration)
      INTEGRATION_MODE=true
      shift
      ;;
    --help)
      cat << EOF
Phase 0 Test Harness

Tests the Phase 0 runner infrastructure without making API calls.

Usage:
  $0 [options]

Options:
  --quick        Quick smoke test only (no API calls)
  --integration  Full integration test (1 task, real API call)
  --help         Show this message

Examples:
  # Run all tests (no API calls)
  $0

  # Quick smoke test
  $0 --quick

  # Integration test with 1 real task
  $0 --integration

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

# Test counter
TESTS_RUN=0
TESTS_PASSED=0
TESTS_FAILED=0

# Test runner
run_test() {
  local test_name="$1"
  local test_command="$2"

  TESTS_RUN=$((TESTS_RUN + 1))

  echo -e "${CYAN}[TEST $TESTS_RUN]${NC} $test_name"

  if eval "$test_command" > /dev/null 2>&1; then
    echo -e "${GREEN}  ✓ PASS${NC}"
    TESTS_PASSED=$((TESTS_PASSED + 1))
  else
    echo -e "${RED}  ✗ FAIL${NC}"
    TESTS_FAILED=$((TESTS_FAILED + 1))
    return 1
  fi
}

# Print header
print_header() {
  echo -e "${BOLD}${BLUE}╔════════════════════════════════════════════════════════════════╗${NC}"
  echo -e "${BOLD}${BLUE}║${NC}${BOLD}              Phase 0 Test Harness                             ${BLUE}║${NC}"
  echo -e "${BOLD}${BLUE}╚════════════════════════════════════════════════════════════════╝${NC}"
  echo ""
}

# Test 1: Check required files exist
test_files_exist() {
  echo -e "${BOLD}Test Suite 1: File Existence${NC}"
  echo ""

  run_test "PHASE0_TASKS.txt exists" "test -f $PROJECT_ROOT/PHASE0_TASKS.txt"
  run_test "phase0_runner.sh exists" "test -f $SCRIPT_DIR/phase0_runner.sh"
  run_test "phase0_analyze.py exists" "test -f $SCRIPT_DIR/phase0_analyze.py"
  run_test "phase0_status.sh exists" "test -f $SCRIPT_DIR/phase0_status.sh"

  echo ""
}

# Test 2: Check scripts are executable
test_scripts_executable() {
  echo -e "${BOLD}Test Suite 2: Script Executability${NC}"
  echo ""

  run_test "phase0_runner.sh is executable" "test -x $SCRIPT_DIR/phase0_runner.sh"
  run_test "phase0_analyze.py is executable" "test -x $SCRIPT_DIR/phase0_analyze.py"
  run_test "phase0_status.sh is executable" "test -x $SCRIPT_DIR/phase0_status.sh"

  echo ""
}

# Test 3: Check task file format
test_task_file_format() {
  echo -e "${BOLD}Test Suite 3: Task File Format${NC}"
  echo ""

  run_test "PHASE0_TASKS.txt has 20 tasks" "test $(grep -v '^#' $PROJECT_ROOT/PHASE0_TASKS.txt | grep -v '^[[:space:]]*$' | wc -l) -eq 20"
  run_test "All tasks have corresponding demos" "for task in \$(grep -v '^#' $PROJECT_ROOT/PHASE0_TASKS.txt | grep -v '^[[:space:]]*$'); do test -f $PROJECT_ROOT/demo_library/synthetic_demos/\${task}.txt || exit 1; done"

  echo ""
}

# Test 4: Check runner help works
test_runner_help() {
  echo -e "${BOLD}Test Suite 4: Runner Help${NC}"
  echo ""

  run_test "phase0_runner.sh --help works" "$SCRIPT_DIR/phase0_runner.sh --help"
  run_test "phase0_status.sh --help works" "$SCRIPT_DIR/phase0_status.sh --help"
  run_test "phase0_analyze.py --help works" "$SCRIPT_DIR/phase0_analyze.py --help"

  echo ""
}

# Test 5: Dry run
test_dry_run() {
  echo -e "${BOLD}Test Suite 5: Dry Run${NC}"
  echo ""

  # Clean up test output
  rm -rf "$TEST_OUTPUT"

  run_test "Dry run with single task" "$SCRIPT_DIR/phase0_runner.sh --dry-run --tasks notepad_1 --trials 1 --output-dir $TEST_OUTPUT"
  run_test "Checkpoint file created" "test -f $TEST_OUTPUT/.checkpoint"
  run_test "Cost log created" "test -f $TEST_OUTPUT/.cost_log.json"

  echo ""
}

# Test 6: Status script
test_status_script() {
  echo -e "${BOLD}Test Suite 6: Status Script${NC}"
  echo ""

  # Use test output from dry run
  if [[ -d "$TEST_OUTPUT" ]]; then
    run_test "Status script works (text)" "$SCRIPT_DIR/phase0_status.sh --output-dir $TEST_OUTPUT"
    run_test "Status script works (JSON)" "$SCRIPT_DIR/phase0_status.sh --output-dir $TEST_OUTPUT --json"
  else
    echo -e "${YELLOW}  Skipping (no test output)${NC}"
  fi

  echo ""
}

# Test 7: Analysis script (on mock data)
test_analysis_script() {
  echo -e "${BOLD}Test Suite 7: Analysis Script${NC}"
  echo ""

  # Create mock results for testing
  mkdir -p "$TEST_OUTPUT/zero-shot/claude-sonnet-4-5"
  mkdir -p "$TEST_OUTPUT/demo-conditioned/claude-sonnet-4-5"

  # Create mock result files
  cat > "$TEST_OUTPUT/zero-shot/claude-sonnet-4-5/notepad_1_trial1.json" << 'EOF'
{
  "summary": {
    "episode_success": false,
    "total_steps": 5,
    "total_cost": 0.50
  }
}
EOF

  cat > "$TEST_OUTPUT/demo-conditioned/claude-sonnet-4-5/notepad_1_trial1.json" << 'EOF'
{
  "summary": {
    "episode_success": true,
    "total_steps": 3,
    "total_cost": 0.55
  }
}
EOF

  run_test "Analysis script works" "$SCRIPT_DIR/phase0_analyze.py --results-dir $TEST_OUTPUT"
  run_test "Analysis export works" "$SCRIPT_DIR/phase0_analyze.py --results-dir $TEST_OUTPUT --export $TEST_OUTPUT/analysis.json"

  echo ""
}

# Test 8: Integration test (1 real task)
test_integration() {
  echo -e "${BOLD}Test Suite 8: Integration Test${NC}"
  echo ""

  if [[ "$INTEGRATION_MODE" != true ]]; then
    echo -e "${YELLOW}  Skipping (use --integration to run)${NC}"
    echo ""
    return
  fi

  # Check if server is available
  local server_url=""
  local vm_ip=$(az vm show --name waa-eval-vm --resource-group OPENADAPT-AGENTS --show-details --query publicIps -o tsv 2>/dev/null || echo "")

  if [[ -n "$vm_ip" ]]; then
    server_url="http://${vm_ip}:5000"
  fi

  if [[ -z "$server_url" ]]; then
    echo -e "${YELLOW}  Skipping (no WAA server available)${NC}"
    echo -e "  Start server with: uv run python -m openadapt_evals.benchmarks.cli up"
    echo ""
    return
  fi

  # Run single task (1 trial, zero-shot only)
  echo -e "${CYAN}Running integration test with real API call...${NC}"
  echo -e "Server: $server_url"
  echo -e "Task: notepad_1 (1 trial, zero-shot only)"
  echo ""

  rm -rf "$TEST_OUTPUT"

  if $SCRIPT_DIR/phase0_runner.sh \
    --tasks notepad_1 \
    --trials 1 \
    --server "$server_url" \
    --output-dir "$TEST_OUTPUT" 2>&1 | tee "$TEST_OUTPUT/integration.log"; then

    echo -e "${GREEN}  ✓ Integration test PASSED${NC}"
    TESTS_PASSED=$((TESTS_PASSED + 1))

    # Verify results
    run_test "Result file created" "test -f $TEST_OUTPUT/zero-shot/claude-sonnet-4-5/notepad_1_trial1.json"
    run_test "Cost was tracked" "test -f $TEST_OUTPUT/.cost_log.json"

  else
    echo -e "${RED}  ✗ Integration test FAILED${NC}"
    TESTS_FAILED=$((TESTS_FAILED + 1))
  fi

  echo ""
}

# Main
main() {
  print_header

  if [[ "$QUICK_MODE" == true ]]; then
    echo -e "${CYAN}Running quick smoke tests...${NC}"
    echo ""
    test_files_exist
    test_scripts_executable
    test_runner_help
  else
    echo -e "${CYAN}Running full test suite...${NC}"
    echo ""
    test_files_exist
    test_scripts_executable
    test_task_file_format
    test_runner_help
    test_dry_run
    test_status_script
    test_analysis_script
    test_integration
  fi

  # Summary
  echo -e "${BOLD}${BLUE}╔════════════════════════════════════════════════════════════════╗${NC}"
  echo -e "${BOLD}${BLUE}║${NC}${BOLD}                    Test Summary                                ${BLUE}║${NC}"
  echo -e "${BOLD}${BLUE}╚════════════════════════════════════════════════════════════════╝${NC}"
  echo ""
  echo -e "${BOLD}Tests Run:    ${TESTS_RUN}${NC}"
  echo -e "${BOLD}${GREEN}Tests Passed: ${TESTS_PASSED}${NC}"

  if [[ $TESTS_FAILED -gt 0 ]]; then
    echo -e "${BOLD}${RED}Tests Failed: ${TESTS_FAILED}${NC}"
    echo ""
    echo -e "${RED}Some tests failed. Please fix before proceeding.${NC}"
    exit 1
  else
    echo -e "${BOLD}${YELLOW}Tests Failed: 0${NC}"
    echo ""
    echo -e "${GREEN}${BOLD}All tests passed! ✓${NC}"
    echo ""
    echo -e "${BOLD}Next Steps:${NC}"
    echo ""
    echo -e "1. Run full Phase 0 evaluation:"
    echo -e "   ${CYAN}./scripts/phase0_runner.sh${NC}"
    echo ""
    echo -e "2. Or test with single task first:"
    echo -e "   ${CYAN}./scripts/phase0_runner.sh --tasks notepad_1 --trials 1${NC}"
    echo ""
  fi

  # Clean up
  if [[ "$INTEGRATION_MODE" != true ]]; then
    echo -e "${YELLOW}Cleaning up test output...${NC}"
    rm -rf "$TEST_OUTPUT"
    echo -e "${GREEN}Done.${NC}"
    echo ""
  fi
}

main
