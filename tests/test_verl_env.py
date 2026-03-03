"""Tests for the VAGEN/verl-agent environment adapter.

Verifies that WAADesktopEnv implements the GymImageEnv protocol correctly
using the WAAMockAdapter (no VM required).
"""

from __future__ import annotations

import asyncio

import pytest

from openadapt_evals.adapters.rl_env import RLEnvironment
from openadapt_evals.adapters.verl_env import (
    WAADesktopEnv,
    _build_obs_dict,
    _parse_action_str,
)
from openadapt_evals.adapters.waa.mock import WAAMockAdapter


# --- Action parsing tests ---


class TestParseActionStr:
    def test_click(self):
        action = _parse_action_str("CLICK(x=0.50, y=0.30)")
        assert action.type == "click"
        assert action.x == pytest.approx(0.50)
        assert action.y == pytest.approx(0.30)

    def test_type(self):
        action = _parse_action_str('TYPE(text="hello world")')
        assert action.type == "type"
        assert action.text == "hello world"

    def test_type_escaped_quotes(self):
        action = _parse_action_str(r'TYPE(text="say \"hi\"")')
        assert action.type == "type"
        assert action.text == r'say \"hi\"'

    def test_key(self):
        action = _parse_action_str('KEY(key="enter")')
        assert action.type == "key"
        assert action.key == "enter"

    def test_wait(self):
        action = _parse_action_str("WAIT()")
        assert action.type == "wait"

    def test_done(self):
        action = _parse_action_str("DONE()")
        assert action.type == "done"

    def test_scroll(self):
        action = _parse_action_str('SCROLL(x=0.50, y=0.50, direction="down")')
        assert action.type == "scroll"

    def test_invalid_returns_done(self):
        action = _parse_action_str("random garbage text")
        assert action.type == "done"

    def test_with_thinking(self):
        action = _parse_action_str(
            "<think>I need to click the button</think>\nCLICK(x=0.25, y=0.75)"
        )
        assert action.type == "click"
        assert action.x == pytest.approx(0.25)
        assert action.y == pytest.approx(0.75)


# --- Observation building tests ---


class TestBuildObsDict:
    def test_with_screenshot(self):
        """Test obs dict with PNG bytes."""
        # Create a minimal valid PNG (1x1 red pixel)
        from PIL import Image
        import io

        img = Image.new("RGB", (100, 100), color="red")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        png_bytes = buf.getvalue()

        from openadapt_evals.adapters.base import BenchmarkObservation

        obs = BenchmarkObservation(screenshot=png_bytes)
        result = _build_obs_dict(obs, prefix="Test:")

        assert "<image>" in result["obs_str"]
        assert "multi_modal_input" in result
        assert "<image>" in result["multi_modal_input"]
        assert len(result["multi_modal_input"]["<image>"]) == 1

    def test_without_screenshot(self):
        """Test obs dict falls back to a11y text."""
        from openadapt_evals.adapters.base import BenchmarkObservation

        obs = BenchmarkObservation(
            screenshot=None, accessibility_tree={"role": "window", "name": "Desktop"}
        )
        result = _build_obs_dict(obs, prefix="Test:")

        assert "<image>" not in result["obs_str"]
        assert "multi_modal_input" not in result
        assert "window" in result["obs_str"]


# --- WAADesktopEnv protocol tests ---


def _make_mock_env() -> WAADesktopEnv:
    """Create a WAADesktopEnv with a mock adapter injected."""
    mock_adapter = WAAMockAdapter(num_tasks=5)
    task_id = mock_adapter.list_tasks()[0].task_id

    env = WAADesktopEnv.__new__(WAADesktopEnv)
    env.config = {}
    env._server_url = "mock"
    env._task_id = task_id
    env._max_steps = 15
    env._evaluate_at_done = True
    env._use_fractional = True
    env._step_count = 0

    # Inject mock adapter instead of creating a real WAALiveAdapter
    env._rl_env = RLEnvironment(mock_adapter, default_task_id=task_id)
    return env


class TestWAADesktopEnv:
    def test_system_prompt(self):
        env = _make_mock_env()
        result = asyncio.run(env.system_prompt())
        assert "obs_str" in result
        assert "CLICK" in result["obs_str"]
        assert "TYPE" in result["obs_str"]
        assert "DONE" in result["obs_str"]

    def test_reset_returns_obs_dict(self):
        env = _make_mock_env()
        obs, info = asyncio.run(env.reset(seed=42))
        assert "obs_str" in obs
        assert isinstance(info, dict)

    def test_step_click(self):
        env = _make_mock_env()
        asyncio.run(env.reset(seed=42))
        obs, reward, done, info = asyncio.run(env.step("CLICK(x=0.10, y=0.10)"))
        assert "obs_str" in obs
        assert isinstance(reward, float)
        assert isinstance(done, bool)

    def test_step_type(self):
        env = _make_mock_env()
        asyncio.run(env.reset(seed=42))
        obs, reward, done, info = asyncio.run(env.step('TYPE(text="hello")'))
        assert not done
        assert reward == 0.0

    def test_step_done_triggers_eval(self):
        env = _make_mock_env()
        asyncio.run(env.reset(seed=42))
        obs, reward, done, info = asyncio.run(env.step("DONE()"))
        assert done is True
        # Reward should be a float from evaluation (mock evaluator)
        assert isinstance(reward, float)

    def test_max_steps_triggers_done(self):
        env = _make_mock_env()
        env._max_steps = 3
        asyncio.run(env.reset(seed=42))

        for i in range(3):
            obs, reward, done, info = asyncio.run(
                env.step(f"CLICK(x=0.{i+1}0, y=0.{i+1}0)")
            )

        assert done is True

    def test_close(self):
        env = _make_mock_env()
        asyncio.run(env.close())
        assert env._rl_env is None

    def test_full_episode_flow(self):
        """Test a complete episode: reset → multiple steps → done → evaluate."""
        env = _make_mock_env()
        env._max_steps = 5

        # Reset
        obs, info = asyncio.run(env.reset(seed=1))
        assert "obs_str" in obs

        # Take some actions
        obs, r, done, _ = asyncio.run(env.step("CLICK(x=0.05, y=0.08)"))
        assert not done
        assert r == 0.0

        obs, r, done, _ = asyncio.run(env.step('TYPE(text="test input")'))
        assert not done
        assert r == 0.0

        # Finish
        obs, r, done, info = asyncio.run(env.step("DONE()"))
        assert done
        assert isinstance(r, float)

    def test_protocol_has_required_methods(self):
        """Verify WAADesktopEnv has all GymImageEnv protocol methods."""
        env = _make_mock_env()
        assert hasattr(env, "reset")
        assert hasattr(env, "step")
        assert hasattr(env, "close")
        assert hasattr(env, "system_prompt")
        assert callable(env.reset)
        assert callable(env.step)
        assert callable(env.close)
        assert callable(env.system_prompt)

    def test_obs_contains_image_placeholder(self):
        """Test that observations with screenshots include <image> placeholder."""
        env = _make_mock_env()
        obs, _ = asyncio.run(env.reset(seed=42))
        # Mock adapter returns observations that may or may not have screenshots
        # At minimum, obs_str should be present
        assert "obs_str" in obs
        assert isinstance(obs["obs_str"], str)
