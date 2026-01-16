"""DEPRECATED: Import from openadapt_evals.adapters instead.

This module is kept for backward compatibility only.
All classes are re-exported from openadapt_evals.adapters.base.
"""

import warnings

warnings.warn(
    "openadapt_evals.benchmarks.base is deprecated. "
    "Please import from openadapt_evals.adapters instead.",
    DeprecationWarning,
    stacklevel=2,
)

# Re-export from canonical location
from openadapt_evals.adapters.base import (
    BenchmarkAction,
    BenchmarkAdapter,
    BenchmarkObservation,
    BenchmarkResult,
    BenchmarkTask,
    StaticDatasetAdapter,
    UIElement,
)

__all__ = [
    "BenchmarkAction",
    "BenchmarkAdapter",
    "BenchmarkObservation",
    "BenchmarkResult",
    "BenchmarkTask",
    "StaticDatasetAdapter",
    "UIElement",
]
