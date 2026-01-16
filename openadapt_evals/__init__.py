"""OpenAdapt Evals: Evaluation infrastructure for GUI agent benchmarks.

This package provides:
- Benchmark adapters for Windows Agent Arena (WAA), OSWorld, WebArena, etc.
- Agent interfaces for evaluation
- Execution trace collection for replay viewers
- Metrics for grounding and trajectory evaluation

Quick Start:
    ```python
    from openadapt_evals import (
        WAAMockAdapter,
        SmartMockAgent,
        evaluate_agent_on_benchmark,
        compute_metrics,
    )

    # Create mock adapter for testing
    adapter = WAAMockAdapter(num_tasks=10)

    # Create agent
    agent = SmartMockAgent()

    # Run evaluation
    results = evaluate_agent_on_benchmark(agent, adapter, max_steps=15)

    # Compute metrics
    metrics = compute_metrics(results)
    print(f"Success rate: {metrics['success_rate']:.1%}")
    ```

For benchmark viewer:
    ```python
    from openadapt_evals import generate_benchmark_viewer
    from pathlib import Path

    # Generate HTML viewer from benchmark results
    generate_benchmark_viewer(
        benchmark_dir=Path("benchmark_results/my_run"),
        output_path=Path("benchmark_results/my_run/viewer.html"),
    )
    ```
"""

__version__ = "0.1.0"

# Re-export main interfaces from benchmarks module
from openadapt_evals.benchmarks import (
    # Base classes
    BenchmarkAction,
    BenchmarkAdapter,
    BenchmarkAgent,
    BenchmarkObservation,
    BenchmarkResult,
    BenchmarkTask,
    StaticDatasetAdapter,
    UIElement,
    # Agents
    RandomAgent,
    ScriptedAgent,
    SmartMockAgent,
    # Evaluation
    EvaluationConfig,
    compute_domain_metrics,
    compute_metrics,
    evaluate_agent_on_benchmark,
    # WAA
    WAAAdapter,
    WAAConfig,
    WAAMockAdapter,
    # Viewer
    generate_benchmark_viewer,
    # Data collection
    ExecutionTraceCollector,
    LiveEvaluationTracker,
    save_execution_trace,
    # Utilities
    action_to_string,
    format_accessibility_tree,
    parse_action_response,
)

__all__ = [
    # Version
    "__version__",
    # Base classes
    "BenchmarkAdapter",
    "BenchmarkTask",
    "BenchmarkObservation",
    "BenchmarkAction",
    "BenchmarkResult",
    "StaticDatasetAdapter",
    "UIElement",
    # Agents
    "BenchmarkAgent",
    "ScriptedAgent",
    "RandomAgent",
    "SmartMockAgent",
    # Evaluation
    "EvaluationConfig",
    "evaluate_agent_on_benchmark",
    "compute_metrics",
    "compute_domain_metrics",
    # WAA
    "WAAAdapter",
    "WAAConfig",
    "WAAMockAdapter",
    # Viewer
    "generate_benchmark_viewer",
    # Data collection
    "ExecutionTraceCollector",
    "save_execution_trace",
    "LiveEvaluationTracker",
    # Utilities
    "action_to_string",
    "format_accessibility_tree",
    "parse_action_response",
]
