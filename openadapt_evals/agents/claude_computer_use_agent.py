"""Claude Computer Use agent for benchmark evaluation.

This module provides an agent that uses Anthropic's native computer_use tool
for GUI automation. Unlike ApiAgent which asks Claude to output action strings
and parses them via regex, this agent uses the structured tool_use/tool_result
protocol where Claude directly outputs typed action dicts.

Key advantages over ApiAgent:
- Claude was specifically trained for coordinate prediction via computer_use
- Structured action output (no regex parsing, no ambiguity)
- Multi-turn conversation maintained across steps
- Built-in screenshot handling via tool_result

Usage:
    from openadapt_evals.agents import ClaudeComputerUseAgent

    agent = ClaudeComputerUseAgent()
    action = agent.act(observation, task)

    # With demo conditioning
    agent = ClaudeComputerUseAgent(demo="Step 1: Click Start menu...")
"""

from __future__ import annotations

import base64
import logging
import os
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import Image

from openadapt_evals.adapters.base import (
    BenchmarkAction,
    BenchmarkObservation,
    BenchmarkTask,
)
from openadapt_evals.agents.base import BenchmarkAgent

logger = logging.getLogger("openadapt_evals.agents.claude_cu")

# Load .env file if it exists
try:
    from dotenv import load_dotenv

    current_dir = Path.cwd()
    for path in [current_dir] + list(current_dir.parents):
        env_file = path / ".env"
        if env_file.exists():
            load_dotenv(env_file)
            break
except ImportError:
    pass

# Tool version and beta string for Opus 4.6 / Sonnet 4.6
COMPUTER_TOOL_TYPE = "computer_20251124"
COMPUTER_USE_BETA = "computer-use-2025-11-24"


class ClaudeComputerUseAgent(BenchmarkAgent):
    """Agent using Claude's native computer_use tool.

    Uses client.beta.messages.create() with the computer_use tool for
    structured action output. Claude predicts pixel coordinates directly
    (it was trained for this), and actions come back as typed dicts
    rather than free text that needs regex parsing.

    Args:
        api_key: Anthropic API key. Falls back to ANTHROPIC_API_KEY env var.
        model: Model to use. Defaults to claude-sonnet-4-6.
        display_width: Width of the display in pixels.
        display_height: Height of the display in pixels.
        demo: Optional demonstration text to include at every step.
        max_tokens: Maximum tokens per API response.
    """

    DEFAULT_MODEL = "claude-sonnet-4-6"

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        display_width: int = 1280,
        display_height: int = 720,
        demo: str | None = None,
        max_tokens: int = 4096,
    ):
        self.model = model or self.DEFAULT_MODEL
        self.display_width = display_width
        self.display_height = display_height
        self.demo = demo
        self.max_tokens = max_tokens

        self.api_key = api_key or os.getenv("ANTHROPIC_API_KEY")
        if not self.api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is required. "
                "Set it in environment or pass api_key parameter."
            )

        try:
            from anthropic import Anthropic

            self._client = Anthropic(api_key=self.api_key)
        except ImportError:
            raise RuntimeError(
                "anthropic package required. Install with: pip install anthropic"
            )

        # Conversation state (maintained across steps within an episode)
        self._messages: list[dict[str, Any]] = []
        self._step_count = 0
        self._last_tool_use_id: str | None = None

        logger.info(
            f"ClaudeComputerUseAgent initialized: model={self.model}, "
            f"display={self.display_width}x{self.display_height}"
        )
        if self.demo:
            logger.info(
                f"Demo provided ({len(self.demo)} chars) - persists across all steps"
            )

    def reset(self) -> None:
        """Reset agent state between episodes."""
        self._messages = []
        self._step_count = 0
        self._last_tool_use_id = None

    # Maximum internal retries for screenshot/wait actions before returning
    MAX_INTERNAL_RETRIES = 5

    def act(
        self,
        observation: BenchmarkObservation,
        task: BenchmarkTask,
        history: list[tuple[BenchmarkObservation, BenchmarkAction]] | None = None,
    ) -> BenchmarkAction:
        """Given observation and task, return next action.

        On the first step, sends the task instruction (with optional demo)
        as the initial user message. On subsequent steps, sends the screenshot
        as a tool_result for the previous tool_use.

        When Claude responds with a screenshot or wait action, this method
        loops internally (sending the screenshot back as a tool_result) rather
        than returning to the runner, since those actions don't affect the
        environment.

        Args:
            observation: Current observation from the environment.
            task: Task being performed.
            history: Optional list of previous (observation, action) pairs.

        Returns:
            Action to execute.
        """
        self._step_count += 1
        screenshot_b64 = self._encode_screenshot(observation)

        if screenshot_b64 is None:
            logger.warning("No screenshot available from environment")
            return BenchmarkAction(
                type="error",
                raw_action={"reason": "no_screenshot", "error_type": "infrastructure"},
            )

        if self._step_count == 1:
            # First step: send task instruction + initial screenshot
            self._messages = self._build_initial_messages(
                task.instruction, screenshot_b64
            )
        else:
            # Subsequent steps: send screenshot as tool_result
            if self._last_tool_use_id:
                tool_result = self._build_tool_result(
                    screenshot_b64, self._last_tool_use_id
                )
                self._messages.append({"role": "user", "content": [tool_result]})

        # Loop: call API, and if Claude requests a screenshot/wait, send the
        # screenshot back and call again (up to MAX_INTERNAL_RETRIES times)
        for attempt in range(self.MAX_INTERNAL_RETRIES + 1):
            response = self._call_api()
            if response is None:
                return BenchmarkAction(
                    type="error",
                    raw_action={"reason": "api_call_failed", "error_type": "infrastructure"},
                )

            # Add assistant response to conversation
            self._messages.append({"role": "assistant", "content": response.content})

            # Check if Claude requested screenshot or wait (internal actions)
            internal_action = self._get_internal_action(response)
            if internal_action is not None:
                logger.info(
                    f"Claude requested '{internal_action}' (attempt {attempt + 1}/"
                    f"{self.MAX_INTERNAL_RETRIES}), sending screenshot back"
                )
                if internal_action == "wait":
                    import time
                    time.sleep(2)
                # Send screenshot as tool_result and loop
                tool_result = self._build_tool_result(
                    screenshot_b64, self._last_tool_use_id
                )
                self._messages.append({"role": "user", "content": [tool_result]})
                continue

            # Real action — return to runner
            return self._process_response(response, observation)

        # Exhausted retries on screenshot/wait — return error (not done)
        logger.warning(
            f"Exhausted {self.MAX_INTERNAL_RETRIES} internal retries on "
            "screenshot/wait actions"
        )
        return BenchmarkAction(
            type="error",
            raw_action={"reason": "max_internal_retries_exceeded", "error_type": "infrastructure"},
        )

    def _build_initial_messages(
        self, instruction: str, screenshot_b64: str | None
    ) -> list[dict[str, Any]]:
        """Build the initial user message with task instruction and optional demo.

        Args:
            instruction: Task instruction text.
            screenshot_b64: Base64-encoded screenshot PNG.

        Returns:
            List with single user message.
        """
        content_parts: list[dict[str, Any]] = []

        # Build text prompt
        text = f"Task: {instruction}"
        if self.demo:
            text = (
                f"Here is a demonstration of a similar completed task:\n\n"
                f"{self.demo}\n\n"
                f"Now complete this task: {instruction}"
            )
        content_parts.append({"type": "text", "text": text})

        # Include initial screenshot as an image
        if screenshot_b64:
            content_parts.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": screenshot_b64,
                    },
                }
            )

        return [{"role": "user", "content": content_parts}]

    def _build_tool_result(
        self, screenshot_b64: str | None, tool_use_id: str
    ) -> dict[str, Any]:
        """Build a tool_result block with a screenshot.

        Args:
            screenshot_b64: Base64-encoded screenshot PNG.
            tool_use_id: ID of the tool_use block this result is for.

        Returns:
            tool_result dict for the messages array.
        """
        content: list[dict[str, Any]] = []
        if screenshot_b64:
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/png",
                        "data": screenshot_b64,
                    },
                }
            )
        else:
            content.append({"type": "text", "text": "Screenshot unavailable."})

        return {
            "type": "tool_result",
            "tool_use_id": tool_use_id,
            "content": content,
        }

    def _call_api(self):
        """Call the Anthropic beta API with computer_use tool.

        Returns:
            API response object, or None on error.
        """
        tools = [
            {
                "type": COMPUTER_TOOL_TYPE,
                "name": "computer",
                "display_width_px": self.display_width,
                "display_height_px": self.display_height,
            }
        ]

        try:
            response = self._client.beta.messages.create(
                model=self.model,
                max_tokens=self.max_tokens,
                messages=self._messages,
                tools=tools,
                betas=[COMPUTER_USE_BETA],
            )
            return response
        except Exception as e:
            logger.error(f"API call failed: {e}")
            return None

    def _process_response(
        self, response: Any, observation: BenchmarkObservation
    ) -> BenchmarkAction:
        """Extract BenchmarkAction from API response.

        Looks for tool_use blocks in the response content. If none found,
        treats as task completion (done).

        Args:
            response: API response object.
            observation: Current observation (for coordinate context).

        Returns:
            Parsed BenchmarkAction.
        """
        for block in response.content:
            if block.type == "tool_use" and block.name == "computer":
                self._last_tool_use_id = block.id
                return self._map_action(block.input, observation)

        # No tool_use block — Claude considers task complete
        text_parts = [b.text for b in response.content if hasattr(b, "text")]
        return BenchmarkAction(
            type="done",
            raw_action={"reason": "no_tool_use", "text": " ".join(text_parts)},
        )

    def _map_action(
        self, tool_input: dict[str, Any], observation: BenchmarkObservation
    ) -> BenchmarkAction:
        """Map Claude computer_use tool input to BenchmarkAction.

        Args:
            tool_input: The input dict from the tool_use block.
            observation: Current observation for coordinate normalization.

        Returns:
            BenchmarkAction with normalized [0,1] coordinates.
        """
        action_type = tool_input.get("action", "")
        raw = {"claude_action": tool_input}

        # Click actions
        if action_type in (
            "left_click",
            "right_click",
            "middle_click",
            "double_click",
            "triple_click",
        ):
            coord = tool_input.get("coordinate", [0, 0])
            x_norm = coord[0] / self.display_width
            y_norm = coord[1] / self.display_height
            ba_type = "click"
            raw["click_variant"] = action_type
            return BenchmarkAction(
                type=ba_type, x=x_norm, y=y_norm, raw_action=raw
            )

        # Type action
        if action_type == "type":
            return BenchmarkAction(
                type="type", text=tool_input.get("text", ""), raw_action=raw
            )

        # Key action
        if action_type == "key":
            key_str = tool_input.get("text", "")
            if "+" in key_str:
                parts = key_str.split("+")
                return BenchmarkAction(
                    type="key",
                    key=parts[-1],
                    modifiers=parts[:-1],
                    raw_action=raw,
                )
            return BenchmarkAction(type="key", key=key_str, raw_action=raw)

        # Scroll action
        if action_type == "scroll":
            direction = tool_input.get("scroll_direction", "down")
            amount = tool_input.get("scroll_amount", 3)
            return BenchmarkAction(
                type="scroll",
                scroll_direction=direction,
                scroll_amount=float(amount),
                raw_action=raw,
            )

        # Drag action
        if action_type == "left_click_drag":
            start = tool_input.get("startCoordinate", [0, 0])
            end = tool_input.get("endCoordinate", [0, 0])
            return BenchmarkAction(
                type="drag",
                x=start[0] / self.display_width,
                y=start[1] / self.display_height,
                end_x=end[0] / self.display_width,
                end_y=end[1] / self.display_height,
                raw_action=raw,
            )

        # Mouse move — treat as a click with no effect for BenchmarkAction
        if action_type == "mouse_move":
            coord = tool_input.get("coordinate", [0, 0])
            raw["is_mouse_move"] = True
            return BenchmarkAction(
                type="click",
                x=coord[0] / self.display_width,
                y=coord[1] / self.display_height,
                raw_action=raw,
            )

        # Screenshot and wait are handled internally by act() loop — they
        # should not reach here. If they do, treat as no-op.
        if action_type in ("screenshot", "wait"):
            logger.warning(
                f"'{action_type}' reached _map_action (should be handled by "
                "act() loop). Treating as no-op."
            )
            return BenchmarkAction(type="done", raw_action=raw)

        # Unknown action
        logger.warning(f"Unknown computer_use action: {action_type}")
        return BenchmarkAction(
            type="done",
            raw_action={"error": f"Unknown action: {action_type}", **raw},
        )

    def _get_internal_action(self, response: Any) -> str | None:
        """Check if response contains a screenshot or wait action.

        These actions don't affect the environment — they're requests from
        Claude to see the current screen or pause briefly. They should be
        handled internally by the act() loop rather than returned to the runner.

        Args:
            response: API response object.

        Returns:
            "screenshot" or "wait" if internal action found, None otherwise.
        """
        for block in response.content:
            if block.type == "tool_use" and block.name == "computer":
                action_type = block.input.get("action", "")
                if action_type in ("screenshot", "wait"):
                    self._last_tool_use_id = block.id
                    return action_type
        return None

    def _encode_screenshot(
        self, observation: BenchmarkObservation
    ) -> str | None:
        """Encode screenshot from observation to base64 PNG.

        Args:
            observation: Current observation.

        Returns:
            Base64-encoded PNG string, or None if no screenshot available.
        """
        screenshot_bytes = observation.screenshot
        if screenshot_bytes is None and observation.screenshot_path:
            try:
                screenshot_bytes = Path(observation.screenshot_path).read_bytes()
            except (FileNotFoundError, OSError):
                pass

        if screenshot_bytes is None:
            return None

        # Ensure it's PNG format and reasonable size
        try:
            img = Image.open(BytesIO(screenshot_bytes))
            # Update display dimensions from actual screenshot if needed
            if observation.viewport:
                self.display_width, self.display_height = observation.viewport
            elif img.size != (self.display_width, self.display_height):
                self.display_width, self.display_height = img.size

            buf = BytesIO()
            img.save(buf, format="PNG")
            return base64.b64encode(buf.getvalue()).decode("utf-8")
        except Exception as e:
            logger.warning(f"Failed to process screenshot: {e}")
            # Fall back to raw bytes
            return base64.b64encode(screenshot_bytes).decode("utf-8")
