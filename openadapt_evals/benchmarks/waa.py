"""DEPRECATED: Import from openadapt_evals.adapters instead.

This module is kept for backward compatibility only.
All classes are re-exported from openadapt_evals.adapters.waa.
"""

import warnings

warnings.warn(
    "openadapt_evals.benchmarks.waa is deprecated. "
    "Please import from openadapt_evals.adapters instead.",
    DeprecationWarning,
    stacklevel=2,
)

# Re-export from canonical location
from openadapt_evals.adapters.waa import (
    WAA_DOMAINS,
    WAAAdapter,
    WAAConfig,
    WAAMockAdapter,
)

__all__ = [
    "WAA_DOMAINS",
    "WAAAdapter",
    "WAAConfig",
    "WAAMockAdapter",
]
