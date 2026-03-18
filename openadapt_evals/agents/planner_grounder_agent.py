"""Planner-Grounder agent for GUI automation.

Separates "what to do" (planner) from "where to click" (grounder).

The planner sees the screenshot + accessibility tree and outputs a
high-level instruction. The grounder sees the screenshot + instruction
and outputs precise pixel coordinates.

Usage:
    from openadapt_evals.agents import PlannerGrounderAgent

    # Both planner and grounder as API model names
    agent = PlannerGrounderAgent(
        planner="claude-sonnet-4-20250514",
        grounder="gpt-4.1-mini",
        planner_provider="anthropic",
        grounder_provider="openai",
    )

    # Planner as existing agent instance, grounder via HTTP
    agent = PlannerGrounderAgent(
        planner=my_api_agent,
        grounder="http",
        grounder_provider="http",
        grounder_endpoint="http://gpu-box:8080",
    )
"""

from __future__ import annotations

import logging
from typing import Any

from openadapt_evals.adapters.base import (
    BenchmarkAction,
    BenchmarkObservation,
    BenchmarkTask,
)
from openadapt_evals.agents.base import (
    BenchmarkAgent,
    action_to_string,
    format_accessibility_tree,
)

logger = logging.getLogger(__name__)

# Maximum number of recent actions to include in planner context.
_MAX_HISTORY_ACTIONS = 10

# Prompt templates -------------------------------------------------------

_PLANNER_SYSTEM = (
    "You are a desktop automation planner. Given the current screenshot, "
    "accessibility tree, and task, decide the single next action the agent "
    "should take. Be precise and unambiguous in your instruction."
)

_PLANNER_PROMPT = """\
Task: {task_instruction}

Previous actions:
{action_history}

Accessibility tree:
{a11y_tree}

Look at the screenshot and decide the next action.

Output a JSON object with exactly these fields:
{{"decision": "COMMAND" | "DONE" | "FAIL", "instruction": "<what to do next>", "reasoning": "<brief explanation>"}}

Rules:
- Use "COMMAND" when there is a concrete next step to take.
- Use "DONE" when the task appears to be completed.
- Use "FAIL" when the task cannot be completed (e.g. required element missing).
- The instruction must describe WHAT to interact with, not pixel coordinates.
"""

_GROUNDER_SYSTEM = (
    "You are a GUI grounding model. Given a screenshot and a natural-language "
    "instruction, output the precise action with coordinates to execute."
)

_GROUNDER_PROMPT = """\
Instruction: {instruction}

Look at the screenshot and output a JSON object describing the action:
{{"type": "click" | "type" | "key" | "scroll" | "drag", "x": <0.0-1.0>, "y": <0.0-1.0>, "text": "...", "key": "...", "scroll_direction": "up"|"down", "end_x": <0.0-1.0>, "end_y": <0.0-1.0>}}

Include only the fields relevant to the action type:
- click: type, x, y
- type: type, text
- key: type, key
- scroll: type, scroll_direction
- drag: type, x, y, end_x, end_y
"""


class PlannerGrounderAgent(BenchmarkAgent):
    """Planner-Grounder architecture for GUI automation.

    Separates "what to do" (planner) from "where to click" (grounder),
    following the pattern established by SeeAct (ICML 2024), UFO2
    (Microsoft 2025), and CODA (2025).

    The planner sees the screenshot + accessibility tree and outputs a
    high-level instruction. The grounder sees the screenshot + instruction
    and outputs precise pixel coordinates.

    Args:
        planner: BenchmarkAgent instance or API model name string.
        grounder: BenchmarkAgent instance or API model name string.
        planner_provider: VLM provider for planner when using a model name
            (``"anthropic"`` or ``"openai"``).
        grounder_provider: VLM provider for grounder when using a model name
            (``"anthropic"``, ``"openai"``, or ``"http"``).
        grounder_endpoint: HTTP endpoint URL when grounder_provider is
            ``"http"``.
        max_history: Maximum number of recent actions to show the planner.
    """

    def __init__(
        self,
        planner: BenchmarkAgent | str,
        grounder: BenchmarkAgent | str,
        planner_provider: str = "anthropic",
        grounder_provider: str = "anthropic",
        grounder_endpoint: str | None = None,
        max_history: int = _MAX_HISTORY_ACTIONS,
    ):
        self._planner = planner
        self._grounder = grounder
        self._planner_provider = planner_provider
        self._grounder_provider = grounder_provider
        self._grounder_endpoint = grounder_endpoint
        self._max_history = max_history

        # Internal action history for planner context.
        self._action_history: list[str] = []

        # Validate grounder_endpoint when using HTTP provider.
        if grounder_provider == "http" and isinstance(grounder, str):
            if not grounder_endpoint:
                raise ValueError(
                    "grounder_endpoint is required when grounder_provider='http'"
                )

        logger.info(
            "PlannerGrounderAgent initialized: "
            "planner=%s (%s), grounder=%s (%s)",
            planner if isinstance(planner, str) else type(planner).__name__,
            planner_provider,
            grounder if isinstance(grounder, str) else type(grounder).__name__,
            grounder_provider,
        )

    def act(
        self,
        observation: BenchmarkObservation,
        task: BenchmarkTask,
        history: list[tuple[BenchmarkObservation, BenchmarkAction]] | None = None,
    ) -> BenchmarkAction:
        """Execute the planner-grounder pipeline.

        1. Call the planner with screenshot + a11y tree + task to get a
           high-level instruction.
        2. If the planner says DONE or FAIL, return immediately.
        3. Call the grounder with screenshot + instruction to get precise
           coordinates.
        4. Return the grounded action.

        Args:
            observation: Current observation from the environment.
            task: Task being performed.
            history: Optional list of previous (observation, action) pairs.

        Returns:
            Action to execute.
        """
        # -- Step 1: Call planner ------------------------------------------
        planner_output = self._call_planner(observation, task)

        decision = planner_output.get("decision", "COMMAND").upper()
        instruction = planner_output.get("instruction", "")
        reasoning = planner_output.get("reasoning", "")

        logger.info(
            "Planner decision=%s, instruction=%r, reasoning=%r",
            decision,
            instruction,
            reasoning,
        )

        if decision == "DONE":
            self._action_history.append("DONE()")
            return BenchmarkAction(
                type="done",
                raw_action={
                    "planner_output": planner_output,
                    "source": "planner",
                },
            )

        if decision == "FAIL":
            self._action_history.append("FAIL()")
            return BenchmarkAction(
                type="done",
                raw_action={
                    "planner_output": planner_output,
                    "source": "planner",
                    "fail_reason": reasoning,
                },
            )

        if not instruction:
            logger.warning("Planner returned empty instruction, treating as DONE")
            self._action_history.append("DONE() [empty instruction]")
            return BenchmarkAction(
                type="done",
                raw_action={
                    "planner_output": planner_output,
                    "parse_error": "empty_instruction",
                },
            )

        # -- Step 2: Call grounder -----------------------------------------
        action = self._call_grounder(observation, instruction)

        # Record for history.
        action_str = action_to_string(action)
        self._action_history.append(f"{action_str} (instruction: {instruction})")

        # Attach planner metadata to the action for debugging.
        if action.raw_action is None:
            action.raw_action = {}
        action.raw_action["planner_output"] = planner_output

        return action

    def reset(self) -> None:
        """Reset agent state between episodes."""
        self._action_history.clear()

        if hasattr(self._planner, "reset"):
            self._planner.reset()
        if hasattr(self._grounder, "reset"):
            self._grounder.reset()

    # -- Private helpers ---------------------------------------------------

    def _call_planner(
        self,
        observation: BenchmarkObservation,
        task: BenchmarkTask,
    ) -> dict[str, Any]:
        """Call the planner to get a high-level instruction.

        Returns:
            Dict with keys ``decision``, ``instruction``, ``reasoning``.
        """
        if not isinstance(self._planner, str):
            # Delegate to the agent's act() — interpret the returned action.
            action = self._planner.act(observation, task)
            return _action_to_planner_output(action)

        # String model name — use vlm_call directly.
        a11y_text = "(not available)"
        if observation.accessibility_tree:
            a11y_text = format_accessibility_tree(observation.accessibility_tree)

        history_text = "(none)" if not self._action_history else "\n".join(
            f"  {i + 1}. {a}"
            for i, a in enumerate(self._action_history[-self._max_history :])
        )

        prompt = _PLANNER_PROMPT.format(
            task_instruction=task.instruction,
            action_history=history_text,
            a11y_tree=a11y_text,
        )

        images = [observation.screenshot] if observation.screenshot else None

        from openadapt_evals.vlm import extract_json, vlm_call

        raw = vlm_call(
            prompt,
            images=images,
            system=_PLANNER_SYSTEM,
            model=self._planner,
            provider=self._planner_provider,
            max_tokens=512,
        )

        logger.debug("Planner raw output: %s", raw[:500])

        parsed = extract_json(raw)
        if parsed is None:
            logger.warning("Failed to parse planner JSON, raw=%s", raw[:200])
            return {"decision": "COMMAND", "instruction": raw.strip(), "reasoning": ""}

        if not isinstance(parsed, dict):
            logger.warning("Planner JSON is not a dict: %s", type(parsed))
            return {"decision": "COMMAND", "instruction": str(parsed), "reasoning": ""}

        return parsed

    def _call_grounder(
        self,
        observation: BenchmarkObservation,
        instruction: str,
        *,
        _retry: bool = True,
    ) -> BenchmarkAction:
        """Call the grounder to get precise coordinates.

        Args:
            observation: Current observation.
            instruction: High-level instruction from the planner.
            _retry: Whether to retry once on parse failure.

        Returns:
            Grounded BenchmarkAction.
        """
        if not isinstance(self._grounder, str):
            # Build a synthetic task with the planner instruction as the
            # instruction, then delegate to the grounder agent.
            synth_task = BenchmarkTask(
                task_id="grounder",
                instruction=instruction,
                domain="desktop",
            )
            return self._grounder.act(observation, synth_task)

        if self._grounder_provider == "http":
            return self._call_grounder_http(observation, instruction)

        # String model name — use vlm_call.
        prompt = _GROUNDER_PROMPT.format(instruction=instruction)
        images = [observation.screenshot] if observation.screenshot else None

        from openadapt_evals.vlm import vlm_call

        raw = vlm_call(
            prompt,
            images=images,
            system=_GROUNDER_SYSTEM,
            model=self._grounder,
            provider=self._grounder_provider,
            max_tokens=256,
        )

        logger.debug("Grounder raw output: %s", raw[:500])

        from openadapt_evals.training.trl_rollout import parse_action_json

        action = parse_action_json(raw)

        # If parsing fell through to "done" (no JSON found) and we haven't
        # retried yet, try once more with a simplified prompt.
        if action.type == "done" and _retry:
            logger.info("Grounder parse failed, retrying with simplified prompt")
            simplified_prompt = (
                f"Where should I click to: {instruction}\n"
                f'Output JSON: {{"type": "click", "x": 0.0-1.0, "y": 0.0-1.0}}'
            )
            raw2 = vlm_call(
                simplified_prompt,
                images=images,
                system=_GROUNDER_SYSTEM,
                model=self._grounder,
                provider=self._grounder_provider,
                max_tokens=128,
            )
            action = parse_action_json(raw2)
            if action.type != "done":
                return action

            logger.warning("Grounder retry also failed, returning done")

        return action

    def _call_grounder_http(
        self,
        observation: BenchmarkObservation,
        instruction: str,
    ) -> BenchmarkAction:
        """Call the grounder via OpenAI-compatible HTTP endpoint.

        Sends the screenshot as a base64-encoded image using the standard
        OpenAI chat completions format, compatible with vLLM, Ollama,
        and any OpenAI-compatible server.

        Args:
            observation: Current observation with screenshot.
            instruction: High-level instruction from the planner.

        Returns:
            Grounded BenchmarkAction.
        """
        import base64
        import json

        import requests

        endpoint = self._grounder_endpoint.rstrip("/")
        if not endpoint.endswith("/v1"):
            endpoint = endpoint.rstrip("/") + "/v1"
        url = f"{endpoint}/chat/completions"

        content = [
            {"type": "text", "text": _GROUNDER_PROMPT.format(instruction=instruction)},
        ]
        if observation.screenshot:
            b64 = base64.b64encode(observation.screenshot).decode()
            content.insert(0, {
                "type": "image_url",
                "image_url": {"url": f"data:image/png;base64,{b64}"},
            })

        payload = {
            "model": "UI-Venus-1.5-8B",
            "messages": [
                {"role": "system", "content": _GROUNDER_SYSTEM},
                {"role": "user", "content": content},
            ],
            "max_tokens": 256,
            "temperature": 0.0,
        }

        try:
            resp = requests.post(url, json=payload, timeout=60)
            resp.raise_for_status()
            raw = resp.json()["choices"][0]["message"]["content"]
        except Exception as exc:
            logger.error("HTTP grounder call failed: %s", exc)
            return BenchmarkAction(type="done")

        logger.debug("HTTP grounder raw output: %s", raw[:500])

        from openadapt_evals.training.trl_rollout import parse_action_json

        return parse_action_json(raw)


def _action_to_planner_output(action: BenchmarkAction) -> dict[str, Any]:
    """Convert a BenchmarkAction from a planner agent to a planner output dict.

    When the planner is an existing BenchmarkAgent, its ``act()`` returns a
    BenchmarkAction. We need to interpret that as planner output.

    Args:
        action: The action returned by the planner agent.

    Returns:
        Dict with ``decision``, ``instruction``, ``reasoning`` keys.
    """
    if action.type == "done":
        return {
            "decision": "DONE",
            "instruction": "",
            "reasoning": action.raw_action.get("reasoning", "") if action.raw_action else "",
        }

    # Use the action string representation as the instruction.
    instruction = action_to_string(action)

    # If there's text in raw_action that looks like an instruction, prefer it.
    if action.raw_action:
        for key in ("instruction", "text", "response"):
            if key in action.raw_action and isinstance(action.raw_action[key], str):
                instruction = action.raw_action[key]
                break

    return {
        "decision": "COMMAND",
        "instruction": instruction,
        "reasoning": "",
    }
