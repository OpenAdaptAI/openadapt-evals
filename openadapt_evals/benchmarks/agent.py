"""Agent interface for benchmark evaluation.

This module provides the BenchmarkAgent interface that agents must implement
to be evaluated on benchmarks.

Example:
    from openadapt_evals.benchmarks import BenchmarkAgent, ScriptedAgent

    # Create a scripted agent for testing
    agent = ScriptedAgent([
        BenchmarkAction(type="click", x=0.5, y=0.5),
        BenchmarkAction(type="done"),
    ])
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Any

from openadapt_evals.benchmarks.base import (
    BenchmarkAction,
    BenchmarkObservation,
    BenchmarkTask,
)


class BenchmarkAgent(ABC):
    """Abstract interface for agents evaluated on benchmarks.

    Agents must implement the `act` method to receive observations
    and return actions. The agent can maintain internal state across
    steps within an episode.
    """

    @abstractmethod
    def act(
        self,
        observation: BenchmarkObservation,
        task: BenchmarkTask,
        history: list[tuple[BenchmarkObservation, BenchmarkAction]] | None = None,
    ) -> BenchmarkAction:
        """Given observation and task, return next action.

        Args:
            observation: Current observation from the environment.
            task: Task being performed.
            history: Optional list of previous (observation, action) pairs.

        Returns:
            Action to execute.
        """
        pass

    def reset(self) -> None:
        """Reset agent state between episodes.

        Called before starting a new task. Override to clear any
        internal state.
        """
        pass


class ScriptedAgent(BenchmarkAgent):
    """Agent that follows a predefined script of actions.

    Useful for testing benchmark adapters or replaying trajectories.

    Args:
        actions: List of actions to execute in order.
    """

    def __init__(self, actions: list[BenchmarkAction]):
        self.actions = actions
        self._step = 0

    def act(
        self,
        observation: BenchmarkObservation,
        task: BenchmarkTask,
        history: list[tuple[BenchmarkObservation, BenchmarkAction]] | None = None,
    ) -> BenchmarkAction:
        """Return the next scripted action.

        Args:
            observation: Ignored.
            task: Ignored.
            history: Ignored.

        Returns:
            Next action from script, or DONE if script exhausted.
        """
        if self._step < len(self.actions):
            action = self.actions[self._step]
            self._step += 1
            return action
        return BenchmarkAction(type="done")

    def reset(self) -> None:
        """Reset step counter."""
        self._step = 0


class RandomAgent(BenchmarkAgent):
    """Agent that takes random actions.

    Useful for baseline comparisons.

    Args:
        action_types: List of action types to randomly select from.
        seed: Random seed for reproducibility.
    """

    def __init__(
        self,
        action_types: list[str] | None = None,
        seed: int | None = None,
    ):
        import random

        self.action_types = action_types or ["click", "type", "scroll", "done"]
        self.rng = random.Random(seed)

    def act(
        self,
        observation: BenchmarkObservation,
        task: BenchmarkTask,
        history: list[tuple[BenchmarkObservation, BenchmarkAction]] | None = None,
    ) -> BenchmarkAction:
        """Return a random action.

        Args:
            observation: Used to get viewport bounds.
            task: Ignored.
            history: Used to decide when to stop.

        Returns:
            Random action.
        """
        # Stop after many actions
        if history and len(history) > 20:
            return BenchmarkAction(type="done")

        action_type = self.rng.choice(self.action_types)

        if action_type == "click":
            return BenchmarkAction(
                type="click",
                x=self.rng.random(),
                y=self.rng.random(),
            )
        elif action_type == "type":
            return BenchmarkAction(
                type="type",
                text="test",
            )
        elif action_type == "scroll":
            return BenchmarkAction(
                type="scroll",
                scroll_direction=self.rng.choice(["up", "down"]),
            )
        else:
            return BenchmarkAction(type="done")

    def reset(self) -> None:
        """Nothing to reset."""
        pass


class SmartMockAgent(BenchmarkAgent):
    """Agent designed to pass WAAMockAdapter evaluation.

    Performs a fixed sequence of actions that satisfy the mock adapter's
    success criteria. Use for validating the benchmark pipeline locally.

    The mock adapter evaluates success based on:
    - Clicking Submit (ID 4) - primary success path
    - Typing something AND clicking OK (ID 1) - form submission path
    - Calling DONE after at least 2 actions - reasonable completion

    This agent clicks Submit (ID 4) which is the simplest success path.
    """

    def __init__(self):
        """Initialize the agent."""
        self._step = 0
        # Simple action sequence: click Submit button (ID 4), then done
        self._actions = [
            BenchmarkAction(type="click", target_node_id="4"),  # Click Submit
            BenchmarkAction(type="done"),
        ]

    def act(
        self,
        observation: BenchmarkObservation,
        task: BenchmarkTask,
        history: list[tuple[BenchmarkObservation, BenchmarkAction]] | None = None,
    ) -> BenchmarkAction:
        """Return the next scripted action.

        Args:
            observation: Ignored.
            task: Ignored.
            history: Ignored.

        Returns:
            Next action from script, or DONE if script exhausted.
        """
        if self._step < len(self._actions):
            action = self._actions[self._step]
            self._step += 1
            return action
        return BenchmarkAction(type="done")

    def reset(self) -> None:
        """Reset step counter."""
        self._step = 0


def format_accessibility_tree(tree: dict, indent: int = 0) -> str:
    """Format accessibility tree for prompt.

    Args:
        tree: Accessibility tree dict.
        indent: Current indentation level.

    Returns:
        Formatted string representation.
    """
    lines = []
    prefix = "  " * indent

    role = tree.get("role", "unknown")
    name = tree.get("name", "")
    node_id = tree.get("id", tree.get("node_id", ""))

    line = f"{prefix}[{node_id}] {role}"
    if name:
        line += f": {name}"
    lines.append(line)

    for child in tree.get("children", []):
        lines.append(format_accessibility_tree(child, indent + 1))

    return "\n".join(lines)


def action_to_string(action: BenchmarkAction) -> str:
    """Convert BenchmarkAction to string representation.

    Args:
        action: Action to convert.

    Returns:
        String representation.
    """
    if action.type == "click":
        if action.target_node_id:
            return f"CLICK([{action.target_node_id}])"
        if action.target_name:
            return f"CLICK({action.target_name})"
        if action.x is not None and action.y is not None:
            return f"CLICK({action.x:.3f}, {action.y:.3f})"
        return "CLICK()"
    elif action.type == "type":
        return f"TYPE({action.text!r})"
    elif action.type == "key":
        mods = "+".join(action.modifiers or [])
        key = action.key
        if mods:
            return f"KEY({mods}+{key})"
        return f"KEY({key})"
    elif action.type == "scroll":
        return f"SCROLL({action.scroll_direction})"
    elif action.type == "drag":
        if action.x is not None and action.y is not None and action.end_x is not None and action.end_y is not None:
            return f"DRAG({action.x:.3f}, {action.y:.3f}, {action.end_x:.3f}, {action.end_y:.3f})"
        return "DRAG()"
    elif action.type == "done":
        return "DONE()"
    elif action.type == "answer":
        return f"ANSWER({action.answer!r})"
    else:
        return f"{action.type.upper()}()"


def parse_action_response(
    response: str, observation: BenchmarkObservation | None = None
) -> BenchmarkAction:
    """Parse VLM response into BenchmarkAction.

    Handles various response formats:
    - ACTION: CLICK(0.5, 0.3)
    - CLICK(0.5, 0.3)
    - I'll click at coordinates (0.5, 0.3) -> CLICK(0.5, 0.3)

    Args:
        response: Raw VLM response text.
        observation: Current observation (used for coordinate normalization).

    Returns:
        Parsed BenchmarkAction.
    """
    # Store raw response for debugging
    raw_action: dict[str, Any] = {"response": response}

    # Extract action line (look for ACTION: prefix or action pattern)
    action_line = None

    # Try to find ACTION: prefix
    action_match = re.search(r"ACTION:\s*(.+)", response, re.IGNORECASE)
    if action_match:
        action_line = action_match.group(1).strip()
    else:
        # Look for action pattern anywhere in response
        patterns = [
            r"(CLICK\s*\([^)]+\))",
            r"(TYPE\s*\([^)]+\))",
            r"(KEY\s*\([^)]+\))",
            r"(SCROLL\s*\([^)]+\))",
            r"(DRAG\s*\([^)]+\))",
            r"(DONE\s*\(\s*\))",
            r"(ANSWER\s*\([^)]+\))",
        ]
        for pattern in patterns:
            match = re.search(pattern, response, re.IGNORECASE)
            if match:
                action_line = match.group(1).strip()
                break

    if not action_line:
        # Could not parse action, return done
        raw_action["parse_error"] = "No action pattern found"
        return BenchmarkAction(type="done", raw_action=raw_action)

    # Parse CLICK action
    click_match = re.match(
        r"CLICK\s*\(\s*\[?(\d+)\]?\s*\)", action_line, re.IGNORECASE
    )
    if click_match:
        # CLICK([id]) - element ID
        node_id = click_match.group(1)
        return BenchmarkAction(
            type="click",
            target_node_id=node_id,
            raw_action=raw_action,
        )

    click_coords = re.match(
        r"CLICK\s*\(\s*([\d.]+)\s*,\s*([\d.]+)\s*\)", action_line, re.IGNORECASE
    )
    if click_coords:
        # CLICK(x, y) - coordinates
        x = float(click_coords.group(1))
        y = float(click_coords.group(2))

        # Normalize coordinates if they appear to be pixel values
        # If x or y > 1.0, assume pixel coordinates and normalize using viewport
        if observation and observation.viewport and (x > 1.0 or y > 1.0):
            width, height = observation.viewport
            x_norm = x / width
            y_norm = y / height
            raw_action["original_coords"] = {"x": x, "y": y}
            raw_action["normalized"] = True
            x = x_norm
            y = y_norm

        return BenchmarkAction(
            type="click",
            x=x,
            y=y,
            raw_action=raw_action,
        )

    # Parse TYPE action
    type_match = re.match(
        r"TYPE\s*\(\s*[\"'](.+?)[\"']\s*\)", action_line, re.IGNORECASE
    )
    if type_match:
        text = type_match.group(1)
        return BenchmarkAction(
            type="type",
            text=text,
            raw_action=raw_action,
        )

    # Parse KEY action
    key_match = re.match(r"KEY\s*\(\s*(.+?)\s*\)", action_line, re.IGNORECASE)
    if key_match:
        key_str = key_match.group(1)
        # Handle modifier+key format
        if "+" in key_str:
            parts = key_str.split("+")
            key = parts[-1]
            modifiers = parts[:-1]
            return BenchmarkAction(
                type="key",
                key=key,
                modifiers=modifiers,
                raw_action=raw_action,
            )
        return BenchmarkAction(
            type="key",
            key=key_str,
            raw_action=raw_action,
        )

    # Parse SCROLL action
    scroll_match = re.match(
        r"SCROLL\s*\(\s*(up|down)\s*\)", action_line, re.IGNORECASE
    )
    if scroll_match:
        direction = scroll_match.group(1).lower()
        return BenchmarkAction(
            type="scroll",
            scroll_direction=direction,
            raw_action=raw_action,
        )

    # Parse DRAG action
    drag_match = re.match(
        r"DRAG\s*\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*\)",
        action_line,
        re.IGNORECASE,
    )
    if drag_match:
        x = float(drag_match.group(1))
        y = float(drag_match.group(2))
        end_x = float(drag_match.group(3))
        end_y = float(drag_match.group(4))

        # Normalize coordinates if they appear to be pixel values
        if observation and observation.viewport and (x > 1.0 or y > 1.0 or end_x > 1.0 or end_y > 1.0):
            width, height = observation.viewport
            raw_action["original_coords"] = {"x": x, "y": y, "end_x": end_x, "end_y": end_y}
            raw_action["normalized"] = True
            x = x / width
            y = y / height
            end_x = end_x / width
            end_y = end_y / height

        return BenchmarkAction(
            type="drag",
            x=x,
            y=y,
            end_x=end_x,
            end_y=end_y,
            raw_action=raw_action,
        )

    # Parse DONE action
    if re.match(r"DONE\s*\(\s*\)", action_line, re.IGNORECASE):
        return BenchmarkAction(type="done", raw_action=raw_action)

    # Parse ANSWER action
    answer_match = re.match(
        r"ANSWER\s*\(\s*[\"'](.+?)[\"']\s*\)", action_line, re.IGNORECASE
    )
    if answer_match:
        answer = answer_match.group(1)
        return BenchmarkAction(
            type="answer",
            answer=answer,
            raw_action=raw_action,
        )

    # Unknown action format
    raw_action["parse_error"] = f"Unknown action format: {action_line}"
    return BenchmarkAction(type="done", raw_action=raw_action)
