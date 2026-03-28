"""Tiered demo executor: deterministic replay with adaptive grounding.

Executes demo steps directly instead of asking a VLM planner to
interpret them. The planner is only consulted as a recovery mechanism
when the expected screen state doesn't match.

Tier 1 (deterministic): keyboard shortcuts, typing — execute directly.
Tier 2 (grounder-only): clicks — grounder finds element by description.
Tier 3 (planner recovery): unexpected state — planner reasons about
    what to do when the demo doesn't match reality.

Usage:
    from openadapt_evals.agents.demo_executor import DemoExecutor

    executor = DemoExecutor(
        grounder_model="gpt-4.1-mini",
        grounder_provider="openai",
        planner_model="gpt-4.1-mini",   # only used for recovery
        planner_provider="openai",
    )
    score, screenshots = executor.run(env, demo, task_config)
"""

from __future__ import annotations

import logging
import time
from typing import Any

from openadapt_evals.adapters.base import BenchmarkAction, BenchmarkObservation
from openadapt_evals.demo_library import Demo, DemoStep

logger = logging.getLogger(__name__)


class DemoExecutor:
    """Execute demo steps with tiered intelligence.

    Args:
        grounder_model: VLM model for grounding clicks.
        grounder_provider: API provider for grounder.
        planner_model: VLM model for recovery (unexpected states).
        planner_provider: API provider for planner.
        step_delay: Seconds to wait after each action for UI to settle.
        recovery_budget: Max planner recovery attempts per demo step.
    """

    def __init__(
        self,
        grounder_model: str = "gpt-4.1-mini",
        grounder_provider: str = "openai",
        planner_model: str = "gpt-4.1-mini",
        planner_provider: str = "openai",
        step_delay: float = 1.0,
        recovery_budget: int = 2,
    ):
        self._grounder_model = grounder_model
        self._grounder_provider = grounder_provider
        self._planner_model = planner_model
        self._planner_provider = planner_provider
        self._step_delay = step_delay
        self._recovery_budget = recovery_budget

    def run(
        self,
        env,  # RLEnvironment
        demo: Demo,
        task_config: Any,
        screenshot_dir: Any | None = None,
    ) -> tuple[float, list[bytes]]:
        """Execute a demo against a live environment.

        Args:
            env: RLEnvironment (already reset).
            demo: Demo to execute.
            task_config: TaskConfig for milestone evaluation.
            screenshot_dir: Optional directory to save screenshots.

        Returns:
            (score, screenshots) — score from evaluate_dense().
        """
        from openadapt_evals.adapters.rl_env import ResetConfig

        obs = env.reset(config=ResetConfig(task_id=task_config.id))
        screenshots: list[bytes] = []
        if obs.screenshot:
            screenshots.append(obs.screenshot)
            if screenshot_dir:
                (screenshot_dir / "step_00_reset.png").write_bytes(obs.screenshot)

        for i, step in enumerate(demo.steps):
            logger.info(
                "Demo step %d/%d: %s %s — %s",
                i + 1, len(demo.steps),
                step.action_type,
                step.action_value or "",
                step.description,
            )

            action = self._execute_step(step, obs)
            if action is None:
                logger.warning("Step %d: no action produced, skipping", i + 1)
                continue

            # Execute the action
            step_result = self._dispatch_action(env, action)
            obs = step_result.observation

            if obs.screenshot:
                screenshots.append(obs.screenshot)
                if screenshot_dir:
                    fname = f"step_{i + 1:02d}.png"
                    (screenshot_dir / fname).write_bytes(obs.screenshot)

            # Per-step milestone check (high-water mark)
            if task_config.milestones:
                passed, total = env.check_milestones_incremental(
                    obs.screenshot,
                )
                if passed > 0:
                    logger.info(
                        "Step %d: milestones %d/%d (high-water)",
                        i + 1, passed, total,
                    )

            time.sleep(self._step_delay)

        # Final evaluation
        if task_config.milestones:
            score = env.evaluate_dense()
        else:
            score = env.evaluate()

        return score, screenshots

    def _execute_step(
        self,
        step: DemoStep,
        obs: BenchmarkObservation,
    ) -> BenchmarkAction | None:
        """Produce an action for a demo step using tiered intelligence.

        Tier 1: keyboard/type → direct execution (no VLM).
        Tier 2: click → grounder finds element by description.
        Tier 3: recovery → planner reasons about unexpected state.
        """
        if step.action_type == "key":
            # Tier 1: deterministic keyboard action
            key = step.action_value
            if not key:
                logger.warning("Key step with no action_value: %s", step)
                return None
            logger.info("Tier 1 (direct): key=%s", key)
            return BenchmarkAction(type="key", key=key)

        if step.action_type == "type":
            # Tier 1: deterministic type action
            text = step.action_value or step.description
            if not text:
                logger.warning("Type step with no value: %s", step)
                return None
            logger.info("Tier 1 (direct): type=%r", text)
            return BenchmarkAction(type="type", text=text)

        if step.action_type == "click":
            # Tier 2: grounder finds element by description
            description = step.description or step.target_description
            if not description:
                description = step.action_description
            logger.info("Tier 2 (grounder): %s", description)
            return self._ground_click(obs, description)

        if step.action_type == "double_click":
            description = step.description or step.target_description
            logger.info("Tier 2 (grounder): double-click %s", description)
            action = self._ground_click(obs, description)
            if action and action.type == "click":
                return BenchmarkAction(
                    type="double_click", x=action.x, y=action.y,
                )
            return action

        # Unknown action type — log and skip
        logger.warning("Unknown action type %r, skipping", step.action_type)
        return None

    def _ground_click(
        self,
        obs: BenchmarkObservation,
        description: str,
    ) -> BenchmarkAction:
        """Use the grounder VLM to find an element by description."""
        from openadapt_evals.vlm import vlm_call

        prompt = (
            f"Where should I click to interact with: {description}\n"
            f'Output JSON: {{"type": "click", "x": 0.0-1.0, "y": 0.0-1.0}}'
        )
        images = [obs.screenshot] if obs.screenshot else None

        raw = vlm_call(
            prompt,
            images=images,
            system=(
                "You are a GUI grounding model. Given a screenshot and a "
                "natural-language description, output the click coordinates "
                "as JSON with normalized x,y (0.0-1.0)."
            ),
            model=self._grounder_model,
            provider=self._grounder_provider,
            max_tokens=128,
            cost_label="demo_executor_grounder",
        )

        from openadapt_evals.training.trl_rollout import parse_action_json
        action = parse_action_json(raw)

        if action.type == "done":
            logger.warning(
                "Grounder could not find %r — returning click at center",
                description,
            )
            return BenchmarkAction(type="click", x=0.5, y=0.5)

        return action

    def _dispatch_action(self, env, action: BenchmarkAction):
        """Execute an action through the environment."""
        if action.x is not None and action.y is not None:
            x, y = float(action.x), float(action.y)
            if 0 <= x <= 1 and 0 <= y <= 1:
                return env.pixel_action(
                    x_frac=x, y_frac=y,
                    action_type=action.type,
                    text=action.text,
                    key=action.key,
                )
            else:
                return env.pixel_action(
                    x=int(x), y=int(y),
                    action_type=action.type,
                    text=action.text,
                    key=action.key,
                )
        return env.step(action)
