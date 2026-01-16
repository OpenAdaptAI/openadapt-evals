"""OpenAdapt Evals: Evaluation infrastructure for GUI agent benchmarks.

This package provides:
- Benchmark adapters for Windows Agent Arena (WAA), OSWorld, WebArena, etc.
- Agent interfaces for evaluation (including ApiAgent with P0 demo persistence fix)
- Execution trace collection for replay viewers
- Metrics for grounding and trajectory evaluation

Package Structure:
    - openadapt_evals.agents: Agent implementations (BenchmarkAgent, ApiAgent, etc.)
    - openadapt_evals.adapters: Benchmark adapters (WAAAdapter, WAALiveAdapter, etc.)
    - openadapt_evals.benchmarks: Evaluation utilities (runner, metrics, viewer)

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

For API-backed evaluation:
    ```python
    from openadapt_evals import ApiAgent, WAALiveAdapter

    # Use Claude Sonnet 4.5 with demo (P0 fix: demo persists across all steps)
    agent = ApiAgent(
        provider="anthropic",
        demo="Step 1: Click Start menu..."  # Included at EVERY step
    )

    adapter = WAALiveAdapter(server_url="http://vm-ip:5000")
    results = evaluate_agent_on_benchmark(agent, adapter, max_steps=15)
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

# Import from canonical locations
from openadapt_evals.agents import (
    BenchmarkAgent,
    RandomAgent,
    ScriptedAgent,
    SmartMockAgent,
    ApiAgent,
    action_to_string,
    format_accessibility_tree,
    parse_action_response,
)
from openadapt_evals.adapters import (
    BenchmarkAction,
    BenchmarkAdapter,
    BenchmarkObservation,
    BenchmarkResult,
    BenchmarkTask,
    StaticDatasetAdapter,
    UIElement,
    WAAAdapter,
    WAAConfig,
    WAAMockAdapter,
    WAALiveAdapter,
    WAALiveConfig,
)
from openadapt_evals.benchmarks import (
    EvaluationConfig,
    compute_domain_metrics,
    compute_metrics,
    evaluate_agent_on_benchmark,
    generate_benchmark_viewer,
    ExecutionTraceCollector,
    LiveEvaluationTracker,
    save_execution_trace,
)

# Lazy imports for optional dependencies
def __getattr__(name: str):
    """Lazy import for PolicyAgent and Azure modules."""
    if name == "PolicyAgent":
        from openadapt_evals.agents import PolicyAgent
        return PolicyAgent
    if name in ("AzureConfig", "AzureWAAOrchestrator", "AzureMLClient", "estimate_cost"):
        from openadapt_evals.benchmarks import azure
        return getattr(azure, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    # Version
    "__version__",
    # Adapters (base classes)
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
    "ApiAgent",
    "PolicyAgent",
    # Evaluation
    "EvaluationConfig",
    "evaluate_agent_on_benchmark",
    "compute_metrics",
    "compute_domain_metrics",
    # WAA adapters
    "WAAAdapter",
    "WAAConfig",
    "WAAMockAdapter",
    "WAALiveAdapter",
    "WAALiveConfig",
    # Azure (lazy imports)
    "AzureConfig",
    "AzureWAAOrchestrator",
    "AzureMLClient",
    "estimate_cost",
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
