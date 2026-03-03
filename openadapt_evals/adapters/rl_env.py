"""RL Environment wrapper for interactive benchmark adapters.

Provides a Gymnasium-style interface (reset/step/observe/evaluate) for RL
training without requiring gymnasium as a dependency. Wraps any interactive
BenchmarkAdapter to expose a clean rollout-collection API suitable for
GRPO, PPO, or other online RL algorithms.

Reward design:
    Reward is 0.0 during the episode and the WAA evaluator score (0.0-1.0)
    at the final step. This matches GRPO where reward comes from an outcome
    verifier, not per-step shaping.

Example:
    from openadapt_evals.adapters.waa.live import WAALiveAdapter, WAALiveConfig
    from openadapt_evals.adapters.rl_env import RLEnvironment

    adapter = WAALiveAdapter(WAALiveConfig(server_url="http://localhost:5001"))
    env = RLEnvironment(adapter, default_task_id="<WAA_UUID>")

    obs = env.reset()
    for _ in range(15):
        obs_step = env.pixel_action(x_frac=0.5, y_frac=0.5)
        if obs_step.done:
            break
    score = env.evaluate()
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from typing import Any, Callable

from openadapt_evals.adapters.base import (
    BenchmarkAction,
    BenchmarkAdapter,
    BenchmarkObservation,
    BenchmarkTask,
)

logger = logging.getLogger(__name__)


@dataclass
class ResetConfig:
    """Configuration for environment reset.

    Attributes:
        task_id: Specific task to load, or None to use default_task_id.
        task_setup_only: If True (default), only run WAA setup commands (~5s).
            If False, a full environment reset is attempted.
        qemu_reboot: If True, reboot the QEMU Windows VM (~90s). Only useful
            when the VM is in an unrecoverable state. Requires SSH tunnel to
            QEMU monitor port 7100 (not yet implemented).
    """

    task_id: str | None = None
    task_setup_only: bool = True
    qemu_reboot: bool = False


@dataclass
class RolloutStep:
    """Single step in a rollout trajectory.

    Attributes:
        observation: Screenshot + a11y tree after the action.
        action: The action that was executed.
        reward: 0.0 during the episode; final score at the last step.
        done: Whether the episode has ended.
        info: Additional metadata (step index, command executed, etc.).
    """

    observation: BenchmarkObservation
    action: BenchmarkAction
    reward: float
    done: bool
    info: dict[str, Any] = field(default_factory=dict)


class RLEnvironment:
    """Gymnasium-style wrapper for interactive benchmark adapters.

    Provides a reset/step/observe/evaluate cycle suitable for RL training
    loops. No gymnasium dependency required.

    The wrapper is adapter-agnostic: it works with any BenchmarkAdapter
    that implements the interactive interface (reset, step, evaluate).
    For pixel-coordinate convenience methods, the underlying adapter should
    be a WAALiveAdapter (or any adapter with a ``pixel_action`` method).

    Args:
        adapter: An interactive BenchmarkAdapter instance.
        default_task_id: Task ID to use when reset() is called without a
            specific task_id. Required for environments with many tasks.
    """

    def __init__(
        self,
        adapter: BenchmarkAdapter,
        default_task_id: str | None = None,
    ):
        self._adapter = adapter
        self._default_task_id = default_task_id
        self._current_task: BenchmarkTask | None = None
        self._step_count = 0
        self._done = False
        self._trajectory: list[RolloutStep] = []
        self._last_obs: BenchmarkObservation | None = None

    @property
    def adapter(self) -> BenchmarkAdapter:
        """The underlying benchmark adapter."""
        return self._adapter

    @property
    def step_count(self) -> int:
        """Number of steps taken in the current episode."""
        return self._step_count

    @property
    def done(self) -> bool:
        """Whether the current episode has ended."""
        return self._done

    @property
    def trajectory(self) -> list[RolloutStep]:
        """Steps taken in the current episode (read-only copy)."""
        return list(self._trajectory)

    @property
    def screen_size(self) -> tuple[int, int]:
        """Actual screen dimensions (width, height) from the last observation.

        Falls back to the adapter's configured size if no observation has been
        captured yet.
        """
        if self._last_obs is not None and self._last_obs.viewport is not None:
            return self._last_obs.viewport
        if hasattr(self._adapter, "screen_size"):
            return self._adapter.screen_size
        config = getattr(self._adapter, "config", None)
        if config is not None:
            width = getattr(config, "screen_width", 1920)
            height = getattr(config, "screen_height", 1200)
            return (width, height)
        return (1920, 1200)

    def reset(self, config: ResetConfig | None = None) -> BenchmarkObservation:
        """Reset environment to a task's initial state.

        Loads the task, runs WAA setup commands, and returns the initial
        observation (screenshot + accessibility tree).

        Args:
            config: Reset configuration. If None, uses defaults with
                default_task_id.

        Returns:
            Initial BenchmarkObservation.

        Raises:
            ValueError: If no task_id is provided and no default was set.
            RuntimeError: If the adapter cannot connect to the WAA server.
        """
        config = config or ResetConfig()
        task_id = config.task_id or self._default_task_id

        if task_id is None:
            raise ValueError(
                "No task_id provided and no default_task_id set. "
                "Pass task_id in ResetConfig or set default_task_id in constructor."
            )

        # Load and reset the task
        self._current_task = self._adapter.load_task(task_id)
        obs = self._adapter.reset(self._current_task)

        # Reset episode state
        self._step_count = 0
        self._done = False
        self._trajectory = []
        self._last_obs = obs

        logger.info(
            "Environment reset: task=%s, instruction=%s",
            task_id,
            self._current_task.instruction[:80],
        )
        return obs

    def step(self, action: BenchmarkAction) -> RolloutStep:
        """Execute an action and return a RolloutStep.

        Reward is 0.0 during the episode. Use evaluate() after the episode
        ends to get the final task-success score.

        Args:
            action: The action to execute.

        Returns:
            RolloutStep with observation, action, reward=0.0, and done flag.

        Raises:
            RuntimeError: If the environment hasn't been reset yet.
        """
        if self._current_task is None:
            raise RuntimeError("Call reset() before step().")

        if self._done:
            raise RuntimeError(
                "Episode is done. Call reset() to start a new episode."
            )

        obs, done, info = self._adapter.step(action)
        self._step_count += 1
        self._last_obs = obs

        # Check for terminal actions
        if action.type in ("done", "error"):
            done = True

        self._done = done
        info["step"] = self._step_count

        rollout_step = RolloutStep(
            observation=obs,
            action=action,
            reward=0.0,  # Reward comes from evaluate() at episode end
            done=done,
            info=info,
        )
        self._trajectory.append(rollout_step)
        return rollout_step

    def pixel_action(
        self,
        x: int | float | None = None,
        y: int | float | None = None,
        action_type: str = "click",
        text: str | None = None,
        key: str | None = None,
        x_frac: float | None = None,
        y_frac: float | None = None,
    ) -> RolloutStep:
        """Execute a pixel-coordinate action and return a RolloutStep.

        If the underlying adapter has a ``pixel_action`` method (e.g.,
        WAALiveAdapter), delegates to it for normalized fraction support.
        Otherwise, constructs a BenchmarkAction and calls step().

        Args:
            x: X pixel coordinate (absolute).
            y: Y pixel coordinate (absolute).
            action_type: "click", "double_click", "right_click", "type",
                "key", "scroll", "drag".
            text: Text to type (for action_type="type").
            key: Key name (for action_type="key").
            x_frac: X as fraction of screen width (0.0-1.0). Overrides x.
            y_frac: Y as fraction of screen height (0.0-1.0). Overrides y.

        Returns:
            RolloutStep with observation, action, reward=0.0, and done flag.
        """
        # Delegate to adapter's pixel_action if available (handles frac conversion)
        if hasattr(self._adapter, "pixel_action"):
            if self._current_task is None:
                raise RuntimeError("Call reset() before pixel_action().")
            if self._done:
                raise RuntimeError(
                    "Episode is done. Call reset() to start a new episode."
                )

            obs, done, info = self._adapter.pixel_action(
                x=x,
                y=y,
                action_type=action_type,
                text=text,
                key=key,
                x_frac=x_frac,
                y_frac=y_frac,
            )
            self._step_count += 1
            self._last_obs = obs
            self._done = done
            info["step"] = self._step_count

            # Reconstruct the action for the trajectory record
            resolved_x = x
            resolved_y = y
            if x_frac is not None or y_frac is not None:
                if hasattr(self._adapter, "screen_size"):
                    w, h = self._adapter.screen_size
                    resolved_x = int((x_frac or 0.0) * w)
                    resolved_y = int((y_frac or 0.0) * h)

            action = BenchmarkAction(
                type=action_type, x=resolved_x, y=resolved_y, text=text, key=key
            )
            rollout_step = RolloutStep(
                observation=obs,
                action=action,
                reward=0.0,
                done=done,
                info=info,
            )
            self._trajectory.append(rollout_step)
            return rollout_step

        # Fallback: convert fracs to pixels manually and use step()
        if x_frac is not None or y_frac is not None:
            # Try to get screen size from adapter
            if hasattr(self._adapter, "screen_size"):
                w, h = self._adapter.screen_size
            else:
                w, h = 1920, 1200  # WAA default
                logger.warning(
                    "Adapter has no screen_size property; "
                    "using default %dx%d for frac conversion",
                    w,
                    h,
                )
            x = int((x_frac or 0.0) * w)
            y = int((y_frac or 0.0) * h)

        action = BenchmarkAction(type=action_type, x=x, y=y, text=text, key=key)
        return self.step(action)

    def observe(self) -> BenchmarkObservation:
        """Return the current observation without stepping.

        If the adapter has an ``observe()`` method (e.g., WAALiveAdapter),
        delegates to it for a fresh screenshot. Otherwise returns the most
        recent cached observation.

        Returns:
            BenchmarkObservation with screenshot and accessibility tree.

        Raises:
            RuntimeError: If no observation is available (call reset() first).
        """
        if hasattr(self._adapter, "observe"):
            obs = self._adapter.observe()
            self._last_obs = obs
            return obs
        if self._last_obs is not None:
            return self._last_obs
        raise RuntimeError("Call reset() before observe().")

    def evaluate(self) -> float:
        """Run the WAA evaluator on the current VM state.

        Returns the task-success score (0.0-1.0). For binary tasks, this is
        0.0 (failure) or 1.0 (success). Suitable as the terminal reward for
        GRPO or other RL algorithms.

        Returns:
            Score between 0.0 and 1.0.

        Raises:
            RuntimeError: If no task has been loaded (call reset() first).
        """
        if self._current_task is None:
            raise RuntimeError("Call reset() before evaluate().")

        result = self._adapter.evaluate(self._current_task)

        # Backfill reward on the last trajectory step
        if self._trajectory:
            self._trajectory[-1].reward = result.score

        logger.info(
            "Evaluation: task=%s, success=%s, score=%.2f",
            self._current_task.task_id,
            result.success,
            result.score,
        )
        return result.score

    def collect_rollout(
        self,
        agent_fn: Callable[[BenchmarkObservation], BenchmarkAction],
        max_steps: int = 15,
        stuck_window: int = 3,
        task_id: str | None = None,
    ) -> list[RolloutStep]:
        """Collect a complete rollout using an agent function.

        Resets the environment, runs the agent for up to max_steps, evaluates
        the result, and returns the full trajectory with the terminal reward
        backfilled on the last step.

        Includes stuck detection: if the last ``stuck_window`` screenshots
        are identical (by hash), the episode terminates early to avoid
        wasting compute on frozen VMs.

        Args:
            agent_fn: Callable that takes a BenchmarkObservation and returns
                a BenchmarkAction. This is your model's predict function.
            max_steps: Maximum steps per episode.
            stuck_window: Number of consecutive identical screenshots before
                early termination. Set to 0 to disable.
            task_id: Task to run. If None, uses default_task_id.

        Returns:
            List of RolloutStep objects. The last step's reward contains the
            evaluation score; all other rewards are 0.0.
        """
        config = ResetConfig(task_id=task_id)
        obs = self.reset(config)

        screenshot_hashes: list[str] = []

        for step_idx in range(max_steps):
            # Get action from agent
            action = agent_fn(obs)

            # Execute action
            rollout_step = self.step(action)
            obs = rollout_step.observation

            # Track screenshot hashes for stuck detection
            if stuck_window > 0 and obs.screenshot:
                h = hashlib.md5(obs.screenshot).hexdigest()
                screenshot_hashes.append(h)

                if (
                    len(screenshot_hashes) >= stuck_window
                    and len(set(screenshot_hashes[-stuck_window:])) == 1
                ):
                    logger.warning(
                        "Stuck detected: last %d screenshots identical. "
                        "Terminating episode at step %d.",
                        stuck_window,
                        step_idx + 1,
                    )
                    self._done = True
                    rollout_step.done = True
                    break

            if rollout_step.done:
                break

        # Evaluate and backfill reward
        score = self.evaluate()

        logger.info(
            "Rollout complete: %d steps, score=%.2f",
            self._step_count,
            score,
        )
        return list(self._trajectory)
