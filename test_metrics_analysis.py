"""Analyze available metrics from benchmark results."""

import json
from pathlib import Path

def analyze_metrics():
    """Analyze what metrics are collected in benchmark results."""

    # Find a recent result
    results_dir = Path("benchmark_results")
    latest_run = sorted(results_dir.glob("waa-mock_eval_*"))[-1]

    print(f"Analyzing: {latest_run.name}\n")

    # Load summary
    summary_path = latest_run / "summary.json"
    summary = json.loads(summary_path.read_text())

    print("="*60)
    print("SUMMARY METRICS")
    print("="*60)
    for key, value in summary.items():
        if key != "tasks":
            print(f"  {key}: {value}")

    # Load task execution
    task_dirs = list((latest_run / "tasks").iterdir())
    if task_dirs:
        task_dir = task_dirs[0]
        execution_path = task_dir / "execution.json"
        execution = json.loads(execution_path.read_text())

        print(f"\n{'='*60}")
        print(f"TASK-LEVEL METRICS ({task_dir.name})")
        print("="*60)

        # Top-level task metrics
        top_level_keys = [k for k in execution.keys() if k not in ['steps', 'logs']]
        for key in top_level_keys:
            value = execution[key]
            print(f"  {key}: {value}")

        # Check what's in steps
        if execution['steps']:
            step = execution['steps'][0]
            print(f"\n{'='*60}")
            print(f"STEP-LEVEL METRICS (step 0)")
            print("="*60)
            for key, value in step.items():
                if key != 'action':
                    print(f"  {key}: {value}")

            # Action structure
            print(f"\n{'='*60}")
            print(f"ACTION STRUCTURE")
            print("="*60)
            for key, value in step['action'].items():
                print(f"  {key}: {value}")

        # Check logs
        if execution['logs']:
            print(f"\n{'='*60}")
            print(f"LOG STRUCTURE (first log)")
            print("="*60)
            first_log = execution['logs'][0]
            for key, value in first_log.items():
                print(f"  {key}: {value}")

    # Check metadata
    metadata_path = latest_run / "metadata.json"
    metadata = json.loads(metadata_path.read_text())

    print(f"\n{'='*60}")
    print(f"METADATA")
    print("="*60)
    for key, value in metadata.items():
        print(f"  {key}: {value}")

    # Summary of available metrics
    print(f"\n{'='*60}")
    print(f"METRICS SUMMARY FOR PHASE 0")
    print("="*60)

    print("\n✓ Episode-Level Metrics:")
    print("  - episode_success (bool) -> summary.json: success")
    print("  - num_steps (int) -> summary.json: avg_steps, execution.json: num_steps")
    print("  - execution_time_seconds (float) -> execution.json: total_time_seconds")
    print("  - score (float) -> execution.json: score")

    print("\n⚠️  Metrics NOT Currently Tracked:")
    print("  - first_action_correct (bool) -> needs implementation")
    print("  - failure_mode (str) -> needs implementation")
    print("  - cost_dollars (float) -> needs API usage tracking")

    print("\n✓ Additional Tracked Metrics:")
    print("  - task_id (str)")
    print("  - model_id (str)")
    print("  - error (str or null)")
    print("  - reason (str) -> evaluation reason")
    print("  - screenshots per step")
    print("  - detailed logs with timestamps")

    return {
        "has_success": True,
        "has_num_steps": True,
        "has_execution_time": True,
        "has_first_action": False,
        "has_failure_mode": False,
        "has_cost": False
    }


if __name__ == "__main__":
    metrics_status = analyze_metrics()

    print(f"\n{'='*60}")
    print("METRICS READINESS FOR PHASE 0")
    print("="*60)

    required_metrics = {
        "episode_success": metrics_status["has_success"],
        "first_action_correct": metrics_status["has_first_action"],
        "num_steps": metrics_status["has_num_steps"],
        "failure_mode": metrics_status["has_failure_mode"],
        "cost_dollars": metrics_status["has_cost"],
        "execution_time_seconds": metrics_status["has_execution_time"]
    }

    ready = 0
    total = len(required_metrics)

    for metric, has_it in required_metrics.items():
        status = "✓" if has_it else "✗"
        print(f"  [{status}] {metric}")
        if has_it:
            ready += 1

    print(f"\nReadiness: {ready}/{total} metrics available")

    if ready < total:
        print("\n⚠️  Some metrics need implementation before Phase 0")
        print("   However, core metrics (success, steps, time) are available")
        print("   Can proceed with limited metrics or add missing ones")
