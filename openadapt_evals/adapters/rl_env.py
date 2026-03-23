"""RL Environment wrapper for interactive benchmark adapters.

Provides a Gymnasium-style interface (reset/step/observe/evaluate) for RL
training without requiring gymnasium as a dependency. Wraps any interactive
BenchmarkAdapter to expose a clean rollout-collection API suitable for
GRPO, PPO, or other online RL algorithms.

Reward design:
    Reward is 0.0 during the episode and the WAA evaluator score (0.0-1.0)
    at the final step. This matches GRPO where reward comes from an outcome
    verifier, not per-step shaping.

    When ``evaluate_every_step=True``, the evaluator is called after each
    step and the score is included in ``info["evaluation_score"]``. The
    reward signal is NOT changed — training code decides how to use the
    per-step evaluation data.

    Dense milestone rewards (via ``evaluate_dense()``) follow standard
    reward shaping techniques from the RL literature. Milestone-based
    partial credit provides gradient signal when sparse binary outcomes
    yield zero gradient (common at the start of GRPO training).

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

    # With per-step evaluation (for RL training loops):
    env = RLEnvironment(adapter, default_task_id="<WAA_UUID>", evaluate_every_step=True)
    obs = env.reset()
    step = env.step(BenchmarkAction(type="click", x=0.5, y=0.3))
    print(step.info["evaluation_score"])  # 0.0 or 1.0

Prior Art:
    - Ng et al., "Policy Invariance Under Reward Transformations:
      Theory and Application to Reward Shaping", ICML 1999. Foundational
      work on potential-based reward shaping for RL.
    - ADMIRE: Wang et al., "ADMIRE: Milestone Rewards for Desktop Agent
      Training", 2025. Dense milestone rewards for GUI agent RL.
    - iStar: Li et al., "Interactive Star Rewards for RL-based GUI
      Agents", 2025. Per-step reward signals for agent training.
    - GUI-Genesis: Chen et al., "GUI-Genesis: Synthetic Reward Models
      for GUI Agent Training", 2025. Learned reward models for desktop
      automation.
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

# Avoid circular import — TaskConfig imported lazily
TYPE_CHECKING = False
if TYPE_CHECKING:
    from openadapt_evals.task_config import TaskConfig

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
        evaluate_every_step: bool = False,
        task_config: TaskConfig | None = None,
    ):
        self._adapter = adapter
        self._default_task_id = default_task_id
        self._evaluate_every_step = evaluate_every_step
        self._task_config = task_config
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

    def load_task_config(self, task_config: TaskConfig) -> None:
        """Set a TaskConfig for dense reward evaluation.

        When set, collect_rollout() and evaluate_dense() use milestone-based
        partial credit instead of binary evaluation.

        Args:
            task_config: A TaskConfig loaded from YAML.
        """
        self._task_config = task_config
        self._default_task_id = task_config.id
        logger.info(
            "Loaded TaskConfig: %s (%d milestones)",
            task_config.name,
            len(task_config.milestones),
        )

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

        # Load the task — prefer TaskConfig if available (avoids server lookup)
        if self._task_config and self._task_config.id == task_id:
            self._current_task = self._task_config.to_benchmark_task()
        elif hasattr(self._adapter, "load_task_from_json") and self._task_config:
            self._current_task = self._adapter.load_task_from_json(
                task_id, self._task_config.to_waa_config()
            )
        else:
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

        # Optional per-step evaluation for RL training loops
        if self._evaluate_every_step and self._current_task is not None:
            try:
                result = self._adapter.evaluate(self._current_task)
                info["evaluation_score"] = result.score
                info["evaluation_success"] = result.success
            except Exception as e:
                logger.warning("Per-step evaluation failed at step %d: %s", self._step_count, e)
                info["evaluation_error"] = str(e)

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

    def observe_pil(self) -> "PIL.Image.Image":
        """Get current screenshot as a PIL Image.

        Convenience wrapper around observe() for VLM/RL training pipelines
        that work with PIL images directly.

        If the underlying adapter has an ``observe_pil()`` method (e.g.,
        WAALiveAdapter), delegates to it. Otherwise calls observe() and
        converts the screenshot bytes to a PIL Image.

        Returns:
            PIL.Image.Image of the current desktop state.

        Raises:
            RuntimeError: If no screenshot is available (call reset() first).
        """
        if hasattr(self._adapter, "observe_pil"):
            return self._adapter.observe_pil()

        import io

        from PIL import Image

        obs = self.observe()
        if not obs.screenshot:
            raise RuntimeError("No screenshot available from adapter")
        return Image.open(io.BytesIO(obs.screenshot))

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

    def evaluate_dense(self) -> float:
        """Evaluate using dense partial rewards via milestones.

        If a TaskConfig with milestones is set, returns the fraction of
        milestones passed (0.0 to 1.0). Falls back to binary evaluate()
        if no TaskConfig or no milestones are defined.

        This gives GRPO gradient signal even when no task fully completes:
        an agent that passes 3/5 milestones gets reward 0.6 vs 0.0 for
        one that passes 0/5.

        Returns:
            Dense reward score between 0.0 and 1.0.
        """
        if self._current_task is None:
            raise RuntimeError("Call reset() before evaluate_dense().")

        # Try milestone evaluation first
        if self._task_config and self._task_config.milestones:
            # Bug 5 fix: Take a FRESH screenshot for evaluation instead of
            # using the cached one from a previous step. The cached screenshot
            # may be from a different phase (e.g., Phase 1 state leaking into
            # Phase 3 evaluation) or may not reflect the current desktop state.
            screenshot = b""
            try:
                fresh_obs = self._adapter.observe()
                if fresh_obs and fresh_obs.screenshot:
                    screenshot = fresh_obs.screenshot
                    logger.info(
                        "evaluate_dense: using fresh screenshot (%d bytes)",
                        len(screenshot),
                    )
            except Exception as e:
                logger.warning(
                    "evaluate_dense: failed to take fresh screenshot, "
                    "falling back to cached: %s", e,
                )
                if self._last_obs and self._last_obs.screenshot:
                    screenshot = self._last_obs.screenshot

            server_url = getattr(
                getattr(self._adapter, "config", None), "server_url", ""
            ) or ""

            passed, total = self._task_config.evaluate_milestones(
                screenshot, server_url
            )
            if total > 0:
                milestone_score = passed / total

                # Also try binary evaluation if available
                try:
                    binary_score = self.evaluate()
                except Exception:
                    binary_score = 0.0

                # Use the higher of milestone score and binary score
                # This way, full task completion (1.0) always beats partial (0.6)
                score = max(milestone_score, binary_score)

                # Backfill reward on last trajectory step
                if self._trajectory:
                    self._trajectory[-1].reward = score
                    self._trajectory[-1].info["milestone_score"] = milestone_score
                    self._trajectory[-1].info["binary_score"] = binary_score
                    self._trajectory[-1].info["milestones_passed"] = passed
                    self._trajectory[-1].info["milestones_total"] = total

                logger.info(
                    "Dense evaluation: milestones=%d/%d (%.2f), binary=%.2f, final=%.2f",
                    passed, total, milestone_score, binary_score, score,
                )
                return score

        # Fallback to binary evaluation
        return self.evaluate()

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

        # Evaluate and backfill reward — use dense rewards if milestones exist
        if self._task_config and self._task_config.milestones:
            score = self.evaluate_dense()
        else:
            score = self.evaluate()

        logger.info(
            "Rollout complete: %d steps, score=%.2f",
            self._step_count,
            score,
        )
        return list(self._trajectory)
