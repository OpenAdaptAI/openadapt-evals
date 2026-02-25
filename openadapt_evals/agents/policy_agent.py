"""Policy-based agent using trained models from openadapt-ml.

This module provides an agent that uses trained policy models from
openadapt-ml for benchmark evaluation. It imports the model classes
from openadapt-ml to avoid code duplication.

Example:
    from openadapt_evals.agents import PolicyAgent

    # Load a trained checkpoint
    agent = PolicyAgent(checkpoint_path="/path/to/checkpoint")
    action = agent.act(observation, task)
"""

from __future__ import annotations

import logging
from typing import Any

from openadapt_evals.agents.base import BenchmarkAgent
from openadapt_evals.adapters.base import (
    BenchmarkAction,
    BenchmarkObservation,
    BenchmarkTask,
)

logger = logging.getLogger("openadapt_evals.agents.policy")

# System prompt — MUST match openadapt_ml.training.convert_demos.SYSTEM_PROMPT
SYSTEM_PROMPT = (
    "You are a GUI agent. You observe screenshots of a desktop and output "
    "exactly one action per step. Use the following action format:\n"
    "click(x=<int>, y=<int>)\n"
    "double_click(x=<int>, y=<int>)\n"
    "right_click(x=<int>, y=<int>)\n"
    'type(text="<string>")\n'
    'press(keys=["<key1>", ...])\n'
    'scroll(direction="<up|down|left|right>", amount=<int>)\n'
    "drag(from_coord=[<x1>, <y1>], to_coord=[<x2>, <y2>])\n"
    "wait()\n"
    "finished()\n\n"
    "Coordinates are in [0, 1000] range where (0,0) is top-left and "
    "(1000,1000) is bottom-right."
)


class PolicyAgent(BenchmarkAgent):
    """Agent that uses a trained policy model from openadapt-ml.

    This agent loads a trained VLM policy model and uses it for
    benchmark evaluation. The model is expected to be trained using
    the openadapt-ml training pipeline.

    Prompt format is aligned with convert_demos.py training data.

    Args:
        checkpoint_path: Path to LoRA adapter weights.
        model_name: HuggingFace model name (must contain 'Qwen3-VL' or 'Qwen2.5-VL').
        device: Device to run on ('cuda' or 'cpu').
        use_thinking: Whether to include <think> instruction in prompts.
    """

    def __init__(
        self,
        checkpoint_path: str | None = None,
        model_name: str = "Qwen/Qwen3-VL-8B-Instruct",
        device: str = "cuda",
        use_thinking: bool = True,
    ):
        self.checkpoint_path = checkpoint_path
        self.model_name = model_name
        self.device = device
        self.use_thinking = use_thinking

        # Lazy load model to avoid import overhead
        self._model = None
        self._processor = None
        self._previous_actions: list[str] = []

    def _load_model(self) -> None:
        """Load the model adapter from checkpoint."""
        if self._model is not None:
            return

        try:
            import torch
            from openadapt_ml.models.qwen_vl import QwenVLAdapter

            device = torch.device(self.device) if isinstance(self.device, str) else self.device
            lora_config = (
                {"weights_path": self.checkpoint_path}
                if self.checkpoint_path
                else None
            )
            self._model = QwenVLAdapter.from_pretrained(
                model_name=self.model_name,
                lora_config=lora_config,
                device=device,
            )
            logger.info(f"PolicyAgent loaded model from {self.checkpoint_path}")
        except ImportError as e:
            raise RuntimeError(
                "PolicyAgent requires openadapt-ml. "
                "Install with: pip install openadapt-ml"
            ) from e
        except Exception as e:
            raise RuntimeError(f"Failed to load model: {e}") from e

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
        # Ensure model is loaded
        self._load_model()

        # Build prompt (aligned with training format)
        prompt = self._build_prompt(observation, task, history)

        # Get model prediction
        try:
            response = self._run_inference(observation, prompt)
            action = self._parse_response(response, observation)

            # Track action for next step's "Previous actions" section
            from openadapt_evals.agents.base import action_to_string
            self._previous_actions.append(action_to_string(action))

            return action
        except Exception as e:
            logger.error(f"Inference failed: {e}")
            return BenchmarkAction(type="done", raw_action={"error": str(e)})

    def _build_prompt(
        self,
        observation: BenchmarkObservation,
        task: BenchmarkTask,
        history: list[tuple[BenchmarkObservation, BenchmarkAction]] | None = None,
    ) -> str:
        """Build user-turn text aligned with convert_demos.convert_step.

        Format matches training data exactly::

            <image>
            Instruction: {instruction}

            Previous actions:
              Step 0: {action}
              Step 1: {action}

            First reason about what you see in <think>...</think> tags,
            then output exactly one action.

        Args:
            observation: Current observation.
            task: Task being performed.
            history: Previous steps.

        Returns:
            Prompt string.
        """
        parts = ["<image>"]
        parts.append(f"Instruction: {task.instruction}")

        # Previous actions (matches training format)
        if self._previous_actions:
            parts.append("")
            parts.append("Previous actions:")
            for i, act in enumerate(self._previous_actions):
                parts.append(f"  Step {i}: {act}")

        # Tail instruction
        parts.append("")
        if self.use_thinking:
            parts.append(
                "First reason about what you see in <think>...</think> "
                "tags, then output exactly one action."
            )
        else:
            parts.append("Output exactly one action.")

        return "\n".join(parts)

    def _build_sample(self, observation: BenchmarkObservation, prompt: str) -> dict:
        """Build SFT-style sample matching training format from convert_demos.py.

        Args:
            observation: Observation with screenshot.
            prompt: User-turn prompt text (from _build_prompt).

        Returns:
            SFT sample dict with messages and optional images.
        """
        sample = {
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        }
        if observation.screenshot_path:
            sample["images"] = [observation.screenshot_path]
        return sample

    def _run_inference(self, observation: BenchmarkObservation, prompt: str) -> str:
        """Run model inference using SFT-style message format.

        Args:
            observation: Observation with screenshot.
            prompt: User-turn prompt text.

        Returns:
            Model response text.
        """
        if not observation.screenshot:
            raise ValueError("No screenshot in observation")

        sample = self._build_sample(observation, prompt)

        # Use the adapter's generate method (works with both local and remote)
        response = self._model.generate(sample)
        return response

    def _parse_response(
        self, response: str, observation: BenchmarkObservation
    ) -> BenchmarkAction:
        """Parse model response into BenchmarkAction.

        Args:
            response: Model response text.
            observation: Observation for coordinate normalization.

        Returns:
            Parsed action.
        """
        from openadapt_evals.agents.base import parse_action_response
        return parse_action_response(response, observation)

    def reset(self) -> None:
        """Reset agent state between tasks."""
        self._previous_actions = []
