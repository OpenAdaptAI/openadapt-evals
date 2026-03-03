"""Tests for RLEnvironment wrapper.

Uses WAAMockAdapter so no VM or network connection is required.
"""

from __future__ import annotations

import pytest

from openadapt_evals.adapters import (
    BenchmarkAction,
    BenchmarkObservation,
    WAAMockAdapter,
)
from openadapt_evals.adapters.rl_env import (
    ResetConfig,
    RLEnvironment,
    RolloutStep,
)


@pytest.fixture
def mock_env() -> RLEnvironment:
    """Create an RLEnvironment backed by WAAMockAdapter."""
    adapter = WAAMockAdapter(num_tasks=5, domains=["notepad"])
    task_id = adapter.list_tasks()[0].task_id
    return RLEnvironment(adapter=adapter, default_task_id=task_id)


# ---------------------------------------------------------------------------
# reset
# ---------------------------------------------------------------------------


class TestReset:
    def test_reset_returns_observation(self, mock_env: RLEnvironment) -> None:
        """RLEnvironment.reset() returns a BenchmarkObservation with screenshot bytes."""
        obs = mock_env.reset()
        assert isinstance(obs, BenchmarkObservation)
        assert obs.screenshot is not None
        assert isinstance(obs.screenshot, bytes)
        assert len(obs.screenshot) > 0

    def test_reset_with_config(self, mock_env: RLEnvironment) -> None:
        """reset() accepts a ResetConfig and uses its task_id."""
        tasks = mock_env._adapter.list_tasks()
        other_id = tasks[-1].task_id
        obs = mock_env.reset(ResetConfig(task_id=other_id))
        assert isinstance(obs, BenchmarkObservation)


# ---------------------------------------------------------------------------
# step
# ---------------------------------------------------------------------------


class TestStep:
    def test_step_returns_rollout_step(self, mock_env: RLEnvironment) -> None:
        """step() returns a RolloutStep with reward=0.0 and done=False for normal actions."""
        mock_env.reset()
        action = BenchmarkAction(type="click", x=150.0, y=120.0)
        result = mock_env.step(action)

        assert isinstance(result, RolloutStep)
        assert isinstance(result.observation, BenchmarkObservation)
        assert result.reward == 0.0
        assert result.done is False
        assert isinstance(result.info, dict)

    def test_step_done_action(self, mock_env: RLEnvironment) -> None:
        """step() returns done=True when the action is 'done'."""
        mock_env.reset()
        result = mock_env.step(BenchmarkAction(type="done"))
        assert result.done is True


# ---------------------------------------------------------------------------
# evaluate
# ---------------------------------------------------------------------------


class TestEvaluate:
    def test_evaluate_returns_score(self, mock_env: RLEnvironment) -> None:
        """evaluate() returns a float in [0.0, 1.0]."""
        mock_env.reset()
        mock_env.step(BenchmarkAction(type="click", x=150.0, y=120.0))
        score = mock_env.evaluate()

        assert isinstance(score, float)
        assert 0.0 <= score <= 1.0


# ---------------------------------------------------------------------------
# pixel_action
# ---------------------------------------------------------------------------


class TestPixelAction:
    def test_pixel_action_absolute_coords(self, mock_env: RLEnvironment) -> None:
        """pixel_action(x=500, y=300) constructs the correct BenchmarkAction."""
        mock_env.reset()
        result = mock_env.pixel_action(x=500, y=300)

        assert isinstance(result, RolloutStep)
        assert result.action.type == "click"
        assert result.action.x == 500
        assert result.action.y == 300

    def test_pixel_action_normalized_fracs(self, mock_env: RLEnvironment) -> None:
        """pixel_action(x_frac=0.5, y_frac=0.25) converts to pixels using screen_size."""
        mock_env.reset()
        result = mock_env.pixel_action(x_frac=0.5, y_frac=0.25)

        assert isinstance(result, RolloutStep)
        assert result.action.type == "click"
        # WAAMockAdapter viewport is (1920, 1200)
        assert result.action.x == int(0.5 * 1920)
        assert result.action.y == int(0.25 * 1200)

    def test_pixel_action_type_text(self, mock_env: RLEnvironment) -> None:
        """pixel_action with action_type='type' and text sends a type action."""
        mock_env.reset()
        result = mock_env.pixel_action(action_type="type", text="hello")

        assert result.action.type == "type"
        assert result.action.text == "hello"

    def test_pixel_action_key_press(self, mock_env: RLEnvironment) -> None:
        """pixel_action with action_type='key' sends a key action."""
        mock_env.reset()
        result = mock_env.pixel_action(action_type="key", key="Enter")

        assert result.action.type == "key"
        assert result.action.key == "Enter"


# ---------------------------------------------------------------------------
# observe
# ---------------------------------------------------------------------------


class TestObserve:
    def test_observe_without_step(self, mock_env: RLEnvironment) -> None:
        """observe() returns an observation without advancing the step count."""
        mock_env.reset()
        obs = mock_env.observe()

        assert isinstance(obs, BenchmarkObservation)
        assert obs.screenshot is not None
        # Internal step count should still be zero after observe
        assert mock_env._step_count == 0


# ---------------------------------------------------------------------------
# collect_rollout
# ---------------------------------------------------------------------------


class TestCollectRollout:
    def test_collect_rollout(self, mock_env: RLEnvironment) -> None:
        """collect_rollout with a mock agent_fn produces the expected number of steps."""
        mock_env.reset()

        call_count = 0

        def agent_fn(obs: BenchmarkObservation) -> BenchmarkAction:
            nonlocal call_count
            call_count += 1
            if call_count >= 3:
                return BenchmarkAction(type="done")
            return BenchmarkAction(type="click", x=150.0, y=120.0)

        rollout = mock_env.collect_rollout(agent_fn=agent_fn, max_steps=10)

        assert isinstance(rollout, list)
        assert len(rollout) == 3
        for step in rollout:
            assert isinstance(step, RolloutStep)
        # Last step should be done
        assert rollout[-1].done is True

    def test_collect_rollout_max_steps(self, mock_env: RLEnvironment) -> None:
        """collect_rollout respects max_steps when the agent never sends 'done'."""
        mock_env.reset()

        def always_click(obs: BenchmarkObservation) -> BenchmarkAction:
            return BenchmarkAction(type="click", x=400.0, y=400.0)

        rollout = mock_env.collect_rollout(agent_fn=always_click, max_steps=5)

        assert len(rollout) <= 5

    def test_collect_rollout_stuck_detection(self, mock_env: RLEnvironment) -> None:
        """collect_rollout terminates early when screenshots repeat (stuck detection).

        WAAMockAdapter generates screenshots based on the step count, which
        includes step-specific text (e.g., 'Step: 3').  Each mock screenshot
        is therefore unique, so stuck detection will NOT trigger.  To exercise
        the stuck-detection branch we patch the adapter to return identical
        bytes on every call.
        """
        mock_env.reset()

        # Patch the adapter to return identical observations (simulating stuck)
        _original_mock_obs = mock_env._adapter._mock_observation
        sentinel_bytes = b"identical-screenshot-bytes"

        def _stuck_observation() -> BenchmarkObservation:
            obs = _original_mock_obs()
            obs.screenshot = sentinel_bytes
            return obs

        mock_env._adapter._mock_observation = _stuck_observation

        def always_click(obs: BenchmarkObservation) -> BenchmarkAction:
            return BenchmarkAction(type="click", x=400.0, y=400.0)

        rollout = mock_env.collect_rollout(
            agent_fn=always_click,
            max_steps=15,
            stuck_window=3,
        )

        # Should terminate early because screenshots are identical
        assert len(rollout) < 15


# ---------------------------------------------------------------------------
# screen_size
# ---------------------------------------------------------------------------


class TestScreenSize:
    def test_screen_size_property(self) -> None:
        """WAAMockAdapter observations report (1920, 1200) viewport which
        RLEnvironment exposes as screen_size."""
        adapter = WAAMockAdapter(num_tasks=2, domains=["notepad"])
        task_id = adapter.list_tasks()[0].task_id
        env = RLEnvironment(adapter=adapter, default_task_id=task_id)
        env.reset()

        width, height = env.screen_size
        assert width == 1920
        assert height == 1200
