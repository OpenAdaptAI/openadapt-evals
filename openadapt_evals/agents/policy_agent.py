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


class PolicyAgent(BenchmarkAgent):
    """Agent that uses a trained policy model from openadapt-ml.

    This agent loads a trained VLM policy model and uses it for
    benchmark evaluation. The model is expected to be trained using
    the openadapt-ml training pipeline.

    Args:
        checkpoint_path: Path to model checkpoint.
        model_name: Name of the model architecture (default: qwen3-vl).
        device: Device to run on ('cuda' or 'cpu').
        use_accessibility_tree: Whether to include a11y tree in prompts.
    """

    def __init__(
        self,
        checkpoint_path: str | None = None,
        model_name: str = "qwen3-vl",
        device: str = "cuda",
        use_accessibility_tree: bool = True,
    ):
        self.checkpoint_path = checkpoint_path
        self.model_name = model_name
        self.device = device
        self.use_accessibility_tree = use_accessibility_tree

        # Lazy load model to avoid import overhead
        self._model = None
        self._processor = None

    def _load_model(self) -> None:
        """Load the model from checkpoint."""
        if self._model is not None:
            return

        try:
            # Import from openadapt-ml
            from openadapt_ml.vlm import load_model_and_processor

            self._model, self._processor = load_model_and_processor(
                model_name=self.model_name,
                checkpoint_path=self.checkpoint_path,
                device=self.device,
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

        # Build prompt
        prompt = self._build_prompt(observation, task, history)

        # Get model prediction
        try:
            response = self._run_inference(observation, prompt)
            action = self._parse_response(response, observation)
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
        """Build prompt for the model.

        Args:
            observation: Current observation.
            task: Task being performed.
            history: Previous steps.

        Returns:
            Prompt string.
        """
        parts = [f"TASK: {task.instruction}"]

        # Add context
        if observation.window_title:
            parts.append(f"Current window: {observation.window_title}")

        # Add accessibility tree if enabled
        if self.use_accessibility_tree and observation.accessibility_tree:
            from openadapt_evals.agents.base import format_accessibility_tree
            tree_str = format_accessibility_tree(observation.accessibility_tree)
            if len(tree_str) > 4000:
                tree_str = tree_str[:4000] + "\n... (truncated)"
            parts.append(f"UI Elements:\n{tree_str}")

        # Add history
        if history:
            from openadapt_evals.agents.base import action_to_string
            history_str = "\n".join(
                f"Step {i+1}: {action_to_string(action)}"
                for i, (_, action) in enumerate(history[-5:])
            )
            parts.append(f"Previous actions:\n{history_str}")

        parts.append("\nWhat is the next action?")
        return "\n\n".join(parts)

    def _run_inference(self, observation: BenchmarkObservation, prompt: str) -> str:
        """Run model inference.

        Args:
            observation: Observation with screenshot.
            prompt: Prompt text.

        Returns:
            Model response text.
        """
        from openadapt_ml.vlm import run_inference

        # Get screenshot as PIL Image
        if observation.screenshot:
            from PIL import Image
            from io import BytesIO
            image = Image.open(BytesIO(observation.screenshot))
        else:
            raise ValueError("No screenshot in observation")

        response = run_inference(
            model=self._model,
            processor=self._processor,
            image=image,
            prompt=prompt,
            device=self.device,
        )
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
        # Nothing to reset for policy agent
        pass
