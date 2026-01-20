#!/usr/bin/env python
"""Test WAA integration: task loading and evaluation."""

import sys
from pathlib import Path

def test_task_loading():
    """Test that we can load real task configs from WAA directory."""
    from openadapt_evals import WAALiveAdapter, WAALiveConfig

    # Configure with real WAA examples path
    config = WAALiveConfig(
        server_url="http://172.171.112.41:5000",  # VM IP
        waa_examples_path="/Users/abrichr/oa/src/openadapt-ml/vendor/WindowsAgentArena/src/win-arena-container/client/evaluation_examples_windows"
    )

    adapter = WAALiveAdapter(config)

    # Test loading tasks by numeric ID
    # Note: domain in the task comes from the JSON's "snapshot" field
    test_cases = [
        ("notepad_1", "notepad"),
        ("chrome_1", "chrome"),
        # For file_explorer, we just verify it loads successfully
        # The actual domain might differ from the directory name
        ("file_explorer_1", None),  # Don't check domain for this one
    ]

    print("Testing task loading...")
    print("=" * 80)

    for task_id, expected_domain in test_cases:
        print(f"\nLoading task: {task_id}")
        task = adapter.load_task(task_id)

        # Verify task loaded successfully
        assert task is not None, f"Failed to load task {task_id}"
        assert task.task_id == task_id, f"Task ID mismatch: {task.task_id} != {task_id}"
        if expected_domain is not None:
            assert task.domain == expected_domain, f"Domain mismatch: {task.domain} != {expected_domain}"

        # Verify real instruction (not generic placeholder)
        assert task.instruction != f"Task {task_id}", f"Generic instruction for {task_id}"
        assert len(task.instruction) > 20, f"Instruction too short for {task_id}"

        # Verify raw_config is populated
        assert task.raw_config is not None, f"No raw_config for {task_id}"
        assert isinstance(task.raw_config, dict), f"raw_config is not dict for {task_id}"
        assert len(task.raw_config) > 0, f"Empty raw_config for {task_id}"

        # Verify evaluator spec exists
        assert task.evaluation_spec is not None, f"No evaluation_spec for {task_id}"
        assert isinstance(task.evaluation_spec, dict), f"evaluation_spec is not dict for {task_id}"
        assert "func" in task.evaluation_spec, f"No 'func' in evaluation_spec for {task_id}"

        print(f"  ✅ Task ID: {task.task_id}")
        print(f"  ✅ Domain: {task.domain}")
        print(f"  ✅ Instruction: {task.instruction[:80]}...")
        print(f"  ✅ Raw config keys: {list(task.raw_config.keys())}")
        print(f"  ✅ Evaluator func: {task.evaluation_spec.get('func')}")

    print("\n" + "=" * 80)
    print("✅ ALL TASK LOADING TESTS PASSED")
    return True


def test_evaluator_functions():
    """Test that evaluator functions are available."""
    from openadapt_evals.server.evaluate_endpoint import StandaloneMetrics, StandaloneGetters

    print("\nTesting evaluator functions...")
    print("=" * 80)

    metrics = StandaloneMetrics()

    # Test exact_match
    assert metrics.exact_match("hello", "hello") == 1.0
    assert metrics.exact_match("hello", "world") == 0.0
    print("  ✅ exact_match")

    # Test compare_text_file
    assert metrics.compare_text_file("This is a test", "This is a test") == 1.0
    assert metrics.compare_text_file("test", "different") < 0.5
    print("  ✅ compare_text_file")

    # Test contains
    assert metrics.contains("hello world", "world") == 1.0
    assert metrics.contains("hello", "xyz") == 0.0
    print("  ✅ contains")

    # Test file_exists (mock test)
    test_file = Path(__file__)
    assert metrics.file_exists(str(test_file), "") == 1.0
    assert metrics.file_exists("/nonexistent/file.txt", "") == 0.0
    print("  ✅ file_exists")

    # Test getters are available
    getters = StandaloneGetters("http://localhost:5000")
    assert hasattr(getters, "get_vm_file")
    assert hasattr(getters, "get_vm_file_exists_in_vm_folder")
    assert hasattr(getters, "get_vm_command_line")
    print("  ✅ StandaloneGetters methods available")

    print("\n" + "=" * 80)
    print("✅ ALL EVALUATOR TESTS PASSED")
    return True


if __name__ == "__main__":
    try:
        # Test task loading
        if not test_task_loading():
            sys.exit(1)

        # Test evaluators
        if not test_evaluator_functions():
            sys.exit(1)

        print("\n" + "=" * 80)
        print("✅✅✅ ALL INTEGRATION TESTS PASSED ✅✅✅")
        print("=" * 80)

    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
