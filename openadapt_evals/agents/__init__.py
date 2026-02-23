"""Agent implementations for benchmark evaluation.

This module provides agent interfaces and implementations for evaluating
GUI automation agents on standardized benchmarks.

Available agents:
    - BenchmarkAgent: Abstract base class for agents
    - ScriptedAgent: Follows predefined action sequence
    - RandomAgent: Takes random actions (baseline)
    - SmartMockAgent: Designed to pass mock adapter tests
    - ApiAgent: Uses Claude/GPT APIs directly (for WAA)
    - ClaudeComputerUseAgent: Uses Claude's native computer_use tool
    - Qwen3VLAgent: Uses Qwen3-VL for local inference
    - PolicyAgent: Uses local trained policy model
    - RetrievalAugmentedAgent: Automatically retrieves demos from a library
    - BaselineAgent: Unified baselines using openadapt-ml (Claude/GPT/Gemini)

Example:
    ```python
    from openadapt_evals.agents import ApiAgent, ScriptedAgent, RetrievalAugmentedAgent

    # Use API agent with Claude
    agent = ApiAgent(provider="anthropic")

    # Use retrieval-augmented agent with automatic demo selection
    agent = RetrievalAugmentedAgent(
        demo_library_path="/path/to/demo_library",
        provider="anthropic",
    )

    # Use scripted agent for replay
    agent = ScriptedAgent([
        BenchmarkAction(type="click", x=0.5, y=0.5),
        BenchmarkAction(type="done"),
    ])

    # Use Qwen3-VL agent for local inference
    from openadapt_evals.agents import Qwen3VLAgent
    agent = Qwen3VLAgent(model_path="Qwen/Qwen3-VL-8B-Instruct")

    # Use unified baseline agent (requires openadapt-ml)
    from openadapt_evals.agents import BaselineAgent
    agent = BaselineAgent.from_alias("gemini-3-pro")
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
from openadapt_evals.agents.claude_computer_use_agent import ClaudeComputerUseAgent
from openadapt_evals.agents.retrieval_agent import RetrievalAugmentedAgent

# Lazy imports for agents requiring additional dependencies
def __getattr__(name: str):
    """Lazy import for agents requiring additional dependencies."""
    if name == "PolicyAgent":
        from openadapt_evals.agents.policy_agent import PolicyAgent
        return PolicyAgent
    if name == "BaselineAgent":
        from openadapt_evals.agents.baseline_agent import BaselineAgent
        return BaselineAgent
    if name == "Qwen3VLAgent":
        from openadapt_evals.agents.qwen3vl_agent import Qwen3VLAgent
        return Qwen3VLAgent
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

__all__ = [
    # Base
    "BenchmarkAgent",
    # Implementations
    "ScriptedAgent",
    "RandomAgent",
    "SmartMockAgent",
    "ApiAgent",
    "ClaudeComputerUseAgent",
    "Qwen3VLAgent",
    "PolicyAgent",
    "RetrievalAugmentedAgent",
    "BaselineAgent",
    # Utilities
    "action_to_string",
    "format_accessibility_tree",
    "parse_action_response",
]
