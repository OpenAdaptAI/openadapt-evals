"""Benchmark adapters for evaluation infrastructure.

This module provides adapters for integrating various GUI benchmarks
with the evaluation framework:
- WAAAdapter: Windows Agent Arena (requires WAA repo)
- WAAMockAdapter: Mock adapter for testing (no Windows required)
- WAALiveAdapter: HTTP adapter for remote WAA server

Available adapters:
    - BenchmarkAdapter: Abstract base class
    - StaticDatasetAdapter: For static trajectory datasets
    - WAAAdapter: Full WAA integration
    - WAAMockAdapter: Testing adapter
    - WAALiveAdapter: Remote HTTP adapter

Example:
    ```python
    from openadapt_evals.adapters import WAAMockAdapter, WAALiveAdapter

    # For local testing (no Windows VM)
    adapter = WAAMockAdapter(num_tasks=10)

    # For remote evaluation
    adapter = WAALiveAdapter(server_url="http://vm-ip:5000")
    ```
"""

from openadapt_evals.adapters.base import (
    BenchmarkAction,
    BenchmarkAdapter,
    BenchmarkObservation,
    BenchmarkResult,
    BenchmarkTask,
    StaticDatasetAdapter,
    UIElement,
)
from openadapt_evals.adapters.waa import WAAAdapter, WAAConfig, WAAMockAdapter
from openadapt_evals.adapters.waa_live import WAALiveAdapter, WAALiveConfig

__all__ = [
    # Base classes
    "BenchmarkAdapter",
    "BenchmarkTask",
    "BenchmarkObservation",
    "BenchmarkAction",
    "BenchmarkResult",
    "StaticDatasetAdapter",
    "UIElement",
    # WAA adapters
    "WAAAdapter",
    "WAAConfig",
    "WAAMockAdapter",
    "WAALiveAdapter",
    "WAALiveConfig",
]
