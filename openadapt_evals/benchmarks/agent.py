"""DEPRECATED: Import from openadapt_evals.agents instead.

This module is kept for backward compatibility only.
All classes are re-exported from openadapt_evals.agents.
"""

import warnings

warnings.warn(
    "openadapt_evals.benchmarks.agent is deprecated. "
    "Please import from openadapt_evals.agents instead.",
    DeprecationWarning,
    stacklevel=2,
)

# Re-export from canonical location
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

__all__ = [
    "BenchmarkAgent",
    "RandomAgent",
    "ScriptedAgent",
    "SmartMockAgent",
    "ApiAgent",
    "action_to_string",
    "format_accessibility_tree",
    "parse_action_response",
]
