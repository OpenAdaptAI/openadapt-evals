"""Benchmark integration for openadapt-evals.

This module provides interfaces and utilities for evaluating GUI agents
on standardized benchmarks like Windows Agent Arena (WAA), OSWorld,
WebArena, and others.

NOTE: The canonical locations for agents and adapters are now:
    - openadapt_evals.agents (BenchmarkAgent, ApiAgent, etc.)
    - openadapt_evals.adapters (BenchmarkAdapter, WAAAdapter, etc.)

This module re-exports from those locations for backward compatibility.

Core classes:
    - BenchmarkAdapter: Abstract interface for benchmark integration
    - BenchmarkAgent: Abstract interface for agents to be evaluated
    - BenchmarkTask, BenchmarkObservation, BenchmarkAction: Data classes

Agent implementations:
    - ScriptedAgent: Follows predefined action sequence
    - RandomAgent: Takes random actions (baseline)
    - SmartMockAgent: Designed to pass mock adapter tests
    - ApiAgent: Uses Claude/GPT APIs directly

Evaluation:
    - evaluate_agent_on_benchmark: Run agent on benchmark tasks
    - compute_metrics: Compute aggregate metrics from results

Example:
    ```python
    from openadapt_evals.benchmarks import (
        BenchmarkAdapter,
        BenchmarkAgent,
        WAAMockAdapter,
        SmartMockAgent,
        evaluate_agent_on_benchmark,
        compute_metrics,
    )

    # Create adapter for specific benchmark (mock for testing)
    adapter = WAAMockAdapter(num_tasks=10)

    # Create agent
    agent = SmartMockAgent()

    # Run evaluation
    results = evaluate_agent_on_benchmark(agent, adapter, max_steps=15)

    # Compute metrics
    metrics = compute_metrics(results)
    print(f"Success rate: {metrics['success_rate']:.1%}")
    ```
"""

# Import from canonical locations (agents/ and adapters/)
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

# Import evaluation utilities from runner
from openadapt_evals.benchmarks.runner import (
    EvaluationConfig,
    compute_domain_metrics,
    compute_metrics,
    evaluate_agent_on_benchmark,
)

# Import data collection utilities
from openadapt_evals.benchmarks.data_collection import (
    ExecutionTraceCollector,
    save_execution_trace,
)
from openadapt_evals.benchmarks.live_tracker import LiveEvaluationTracker

# Import viewer
from openadapt_evals.benchmarks.viewer import generate_benchmark_viewer

# Lazy imports for optional dependencies
def __getattr__(name: str):
    """Lazy import Azure modules (requires azure-ai-ml, azure-identity) and PolicyAgent."""
    if name in ("AzureConfig", "AzureWAAOrchestrator", "AzureMLClient", "estimate_cost"):
        from openadapt_evals.benchmarks import azure
        return getattr(azure, name)
    if name == "PolicyAgent":
        from openadapt_evals.agents import PolicyAgent
        return PolicyAgent
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    # Base classes (from adapters)
    "BenchmarkAdapter",
    "BenchmarkTask",
    "BenchmarkObservation",
    "BenchmarkAction",
    "BenchmarkResult",
    "StaticDatasetAdapter",
    "UIElement",
    # Agents (from agents)
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
