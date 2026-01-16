"""Agent implementations for benchmark evaluation.

This module provides agent interfaces and implementations for evaluating
GUI automation agents on standardized benchmarks.

Available agents:
    - BenchmarkAgent: Abstract base class for agents
    - ScriptedAgent: Follows predefined action sequence
    - RandomAgent: Takes random actions (baseline)
    - SmartMockAgent: Designed to pass mock adapter tests
    - ApiAgent: Uses Claude/GPT APIs directly (for WAA)
    - PolicyAgent: Uses local trained policy model

Example:
    ```python
    from openadapt_evals.agents import ApiAgent, ScriptedAgent

    # Use API agent with Claude
    agent = ApiAgent(provider="anthropic")

    # Use scripted agent for replay
    agent = ScriptedAgent([
        BenchmarkAction(type="click", x=0.5, y=0.5),
        BenchmarkAction(type="done"),
    ])
    ```
"""

from openadapt_evals.agents.base import (
    BenchmarkAgent,
    action_to_string,
    format_accessibility_tree,
    parse_action_response,
)
from openadapt_evals.agents.scripted_agent import (
    RandomAgent,
    ScriptedAgent,
    SmartMockAgent,
)
from openadapt_evals.agents.api_agent import ApiAgent

# Lazy import for PolicyAgent (requires openadapt-ml models)
def __getattr__(name: str):
    """Lazy import for PolicyAgent to avoid circular dependencies."""
    if name == "PolicyAgent":
        from openadapt_evals.agents.policy_agent import PolicyAgent
        return PolicyAgent
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    # Base
    "BenchmarkAgent",
    # Implementations
    "ScriptedAgent",
    "RandomAgent",
    "SmartMockAgent",
    "ApiAgent",
    "PolicyAgent",
    # Utilities
    "action_to_string",
    "format_accessibility_tree",
    "parse_action_response",
]
