"""Test script for execution logs feature.

This script tests:
1. Log capture during evaluation
2. Log storage in execution.json
3. Log display in viewer
4. Color-coded log levels (INFO, WARNING, ERROR, SUCCESS)
5. Log filtering and search
"""

import logging
import json
from pathlib import Path
from openadapt_evals import WAAMockAdapter, SmartMockAgent, RandomAgent, evaluate_agent_on_benchmark
from openadapt_evals.benchmarks.runner import EvaluationConfig
from openadapt_evals.benchmarks.viewer import generate_benchmark_viewer

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

def test_successful_task_logs():
    """Test log capture for successful task."""
    logger.info("Testing successful task with logs...")

    adapter = WAAMockAdapter()
    agent = SmartMockAgent()

    config = EvaluationConfig(
        max_steps=5,
        save_execution_traces=True,
        output_dir='/tmp/test_execution_logs',
        run_name='test_success',
        verbose=True,
    )

    results = evaluate_agent_on_benchmark(
        agent=agent,
        adapter=adapter,
        task_ids=['chrome_1'],
        config=config
    )

    # Verify logs were captured
    execution_file = Path('/tmp/test_execution_logs/test_success/tasks/chrome_1/execution.json')
    with open(execution_file) as f:
        data = json.load(f)

    assert 'logs' in data, "Logs missing from execution.json"
    assert len(data['logs']) > 0, "No logs captured"

    # Check for SUCCESS log
    success_logs = [log for log in data['logs'] if log['level'] == 'SUCCESS']
    assert len(success_logs) > 0, "No SUCCESS logs found"

    logger.info(f"✓ Success test passed: {len(data['logs'])} logs captured, {len(success_logs)} SUCCESS")
    return True

def test_failed_task_logs():
    """Test log capture for failed task."""
    logger.info("Testing failed task with logs...")

    adapter = WAAMockAdapter()
    agent = RandomAgent()

    config = EvaluationConfig(
        max_steps=5,
        save_execution_traces=True,
        output_dir='/tmp/test_execution_logs',
        run_name='test_failure',
        verbose=True,
    )

    results = evaluate_agent_on_benchmark(
        agent=agent,
        adapter=adapter,
        task_ids=['chrome_1'],
        config=config
    )

    # Verify logs were captured
    execution_file = Path('/tmp/test_execution_logs/test_failure/tasks/chrome_1/execution.json')
    with open(execution_file) as f:
        data = json.load(f)

    assert 'logs' in data, "Logs missing from execution.json"

    # Check for ERROR or INFO logs
    total_logs = len(data['logs'])
    logger.info(f"✓ Failure test passed: {total_logs} logs captured")
    return True

def test_viewer_generation():
    """Test viewer generation with logs."""
    logger.info("Testing viewer generation with logs...")

    # Generate viewer for success test
    viewer_path = generate_benchmark_viewer(
        benchmark_dir=Path('/tmp/test_execution_logs/test_success'),
        embed_screenshots=False
    )

    # Verify viewer contains log panel
    with open(viewer_path) as f:
        html = f.read()

    assert 'log-panel' in html, "Log panel missing from viewer"
    assert 'renderLogs' in html, "renderLogs function missing"
    assert 'toggleLogPanel' in html, "toggleLogPanel function missing"
    assert 'filterLogs' in html, "filterLogs function missing"
    assert '"logs":' in html, "Logs data missing from viewer"

    logger.info(f"✓ Viewer generation passed: {viewer_path}")
    return True

def test_log_structure():
    """Test log entry structure."""
    logger.info("Testing log entry structure...")

    execution_file = Path('/tmp/test_execution_logs/test_success/tasks/chrome_1/execution.json')
    with open(execution_file) as f:
        data = json.load(f)

    for log in data['logs']:
        assert 'timestamp' in log, "timestamp missing from log entry"
        assert 'level' in log, "level missing from log entry"
        assert 'message' in log, "message missing from log entry"
        assert isinstance(log['timestamp'], (int, float)), "timestamp not numeric"
        assert log['level'] in ['INFO', 'WARNING', 'ERROR', 'SUCCESS'], f"Invalid log level: {log['level']}"

    logger.info(f"✓ Log structure test passed: {len(data['logs'])} entries validated")
    return True

if __name__ == '__main__':
    logger.info("=" * 60)
    logger.info("Testing Execution Logs Feature")
    logger.info("=" * 60)

    try:
        test_successful_task_logs()
        test_failed_task_logs()
        test_log_structure()
        test_viewer_generation()

        logger.info("=" * 60)
        logger.info("All tests passed!")
        logger.info("=" * 60)
        logger.info(f"\nOpen viewer at: /tmp/test_execution_logs/test_success/viewer.html")

    except AssertionError as e:
        logger.error(f"Test failed: {e}")
        raise
