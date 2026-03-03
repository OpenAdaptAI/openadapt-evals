"""Tests for pixel_action direct path in WAALiveAdapter.

Verifies that pixel_action() builds pyautogui commands directly and sends
them via _send_command(), bypassing the element-based _translate_action path.
"""

from unittest.mock import MagicMock, patch

import pytest

from openadapt_evals.adapters.base import BenchmarkAction, BenchmarkObservation
from openadapt_evals.adapters.waa.live import WAALiveAdapter, WAALiveConfig


def _make_adapter(**config_kwargs) -> WAALiveAdapter:
    """Create a WAALiveAdapter without connecting to a server."""
    adapter = WAALiveAdapter.__new__(WAALiveAdapter)
    adapter.config = WAALiveConfig(**config_kwargs)
    adapter._current_task = None
    adapter._step_count = 0
    adapter._current_a11y = None
    adapter._current_rects = {}
    adapter._current_screenshot = None
    adapter._actions = []
    adapter._actual_screen_size = (1920, 1200)
    return adapter


class TestBuildPixelCommand:
    """Tests for _build_pixel_command -- the direct pyautogui command builder."""

    def test_click_absolute_pixels(self):
        adapter = _make_adapter()
        cmd = adapter._build_pixel_command(action_type="click", x=500, y=300)
        assert cmd == "import pyautogui; pyautogui.click(500, 300)"

    def test_double_click(self):
        adapter = _make_adapter()
        cmd = adapter._build_pixel_command(action_type="double_click", x=100, y=200)
        assert cmd == "import pyautogui; pyautogui.doubleClick(100, 200)"

    def test_right_click(self):
        adapter = _make_adapter()
        cmd = adapter._build_pixel_command(action_type="right_click", x=800, y=600)
        assert cmd == "import pyautogui; pyautogui.rightClick(800, 600)"

    def test_type_action_clicks_then_types(self):
        adapter = _make_adapter()
        cmd = adapter._build_pixel_command(
            action_type="type", x=100, y=200, text="hello"
        )
        assert "pyautogui.click(100, 200)" in cmd
        assert "time.sleep(0.2)" in cmd
        assert "pyautogui.write('hello'" in cmd

    def test_key_action(self):
        adapter = _make_adapter()
        cmd = adapter._build_pixel_command(action_type="key", key="enter")
        assert "pyautogui.press('enter')" in cmd

    def test_scroll_at_position(self):
        adapter = _make_adapter()
        cmd = adapter._build_pixel_command(action_type="scroll", x=500, y=400)
        assert "pyautogui.scroll(-3, x=500, y=400)" in cmd

    def test_wait_action(self):
        adapter = _make_adapter()
        cmd = adapter._build_pixel_command(action_type="wait")
        assert cmd == "import time; time.sleep(1)"

    def test_done_returns_none(self):
        adapter = _make_adapter()
        cmd = adapter._build_pixel_command(action_type="done")
        assert cmd is None

    def test_error_returns_none(self):
        adapter = _make_adapter()
        cmd = adapter._build_pixel_command(action_type="error")
        assert cmd is None

    def test_unknown_action_returns_none(self):
        adapter = _make_adapter()
        cmd = adapter._build_pixel_command(action_type="unknown_action")
        assert cmd is None

    def test_clamps_to_safe_margin(self):
        """Coordinates at screen edges should be clamped to avoid fail-safe."""
        adapter = _make_adapter()
        # Top-left corner
        cmd = adapter._build_pixel_command(action_type="click", x=0, y=0)
        assert cmd == "import pyautogui; pyautogui.click(5, 5)"

    def test_clamps_bottom_right(self):
        """Bottom-right corner should be clamped to screen_size - margin."""
        adapter = _make_adapter()
        cmd = adapter._build_pixel_command(action_type="click", x=2000, y=1300)
        # screen is 1920x1200, margin=5 => max is (1915, 1195)
        assert cmd == "import pyautogui; pyautogui.click(1915, 1195)"

    def test_none_coords_default_to_clamped_zero(self):
        adapter = _make_adapter()
        cmd = adapter._build_pixel_command(action_type="click", x=None, y=None)
        # None -> 0 -> clamped to margin (5)
        assert cmd == "import pyautogui; pyautogui.click(5, 5)"

    def test_float_coords_are_truncated(self):
        """Float pixel values (not fracs) should be cast to int."""
        adapter = _make_adapter()
        cmd = adapter._build_pixel_command(action_type="click", x=500.7, y=300.3)
        assert cmd == "import pyautogui; pyautogui.click(500, 300)"

    def test_generated_commands_are_valid_python(self):
        """All generated commands should be syntactically valid Python."""
        adapter = _make_adapter()
        cases = [
            ("click", 500, 300, None, None),
            ("double_click", 100, 200, None, None),
            ("right_click", 800, 600, None, None),
            ("type", 100, 200, "it's a test", None),
            ("key", None, None, None, "enter"),
            ("scroll", 500, 400, None, None),
            ("wait", None, None, None, None),
        ]
        for action_type, x, y, text, key in cases:
            cmd = adapter._build_pixel_command(
                action_type=action_type, x=x, y=y, text=text, key=key,
            )
            if cmd is not None:
                compile(cmd, f"<{action_type}>", "exec")


class TestPixelActionBypassesTranslateAction:
    """Tests that pixel_action() bypasses _translate_action entirely."""

    @patch.object(WAALiveAdapter, "_get_observation")
    @patch.object(WAALiveAdapter, "_send_command")
    def test_pixel_action_does_not_call_translate_action(
        self, mock_send, mock_obs
    ):
        """pixel_action should never call _translate_action."""
        mock_obs.return_value = BenchmarkObservation(viewport=(1920, 1200))
        adapter = _make_adapter()

        with patch.object(adapter, "_translate_action") as mock_translate:
            adapter.pixel_action(x=500, y=300, action_type="click")
            mock_translate.assert_not_called()

    @patch.object(WAALiveAdapter, "_get_observation")
    @patch.object(WAALiveAdapter, "_send_command")
    def test_pixel_action_calls_send_command_directly(
        self, mock_send, mock_obs
    ):
        """pixel_action should call _send_command with the direct command."""
        mock_obs.return_value = BenchmarkObservation(viewport=(1920, 1200))
        adapter = _make_adapter()

        adapter.pixel_action(x=500, y=300, action_type="click")
        mock_send.assert_called_once_with(
            "import pyautogui; pyautogui.click(500, 300)"
        )

    @patch.object(WAALiveAdapter, "_get_observation")
    @patch.object(WAALiveAdapter, "_send_command")
    def test_pixel_action_returns_pixel_direct_flag(
        self, mock_send, mock_obs
    ):
        """info dict should contain pixel_direct=True."""
        mock_obs.return_value = BenchmarkObservation(viewport=(1920, 1200))
        adapter = _make_adapter()

        _, _, info = adapter.pixel_action(x=500, y=300, action_type="click")
        assert info["pixel_direct"] is True

    @patch.object(WAALiveAdapter, "_get_observation")
    @patch.object(WAALiveAdapter, "_send_command")
    def test_pixel_action_increments_step_count(
        self, mock_send, mock_obs
    ):
        """pixel_action should increment _step_count."""
        mock_obs.return_value = BenchmarkObservation(viewport=(1920, 1200))
        adapter = _make_adapter()
        assert adapter._step_count == 0

        adapter.pixel_action(x=500, y=300)
        assert adapter._step_count == 1

        adapter.pixel_action(x=600, y=400)
        assert adapter._step_count == 2

    @patch.object(WAALiveAdapter, "_get_observation")
    @patch.object(WAALiveAdapter, "_send_command")
    def test_pixel_action_records_action_history(
        self, mock_send, mock_obs
    ):
        """pixel_action should append to _actions list."""
        mock_obs.return_value = BenchmarkObservation(viewport=(1920, 1200))
        adapter = _make_adapter()

        adapter.pixel_action(x=500, y=300, action_type="click")
        assert len(adapter._actions) == 1
        assert adapter._actions[0].type == "click"
        assert adapter._actions[0].x == 500
        assert adapter._actions[0].y == 300

    @patch.object(WAALiveAdapter, "_get_observation")
    @patch.object(WAALiveAdapter, "_send_command")
    def test_pixel_action_done_returns_true(self, mock_send, mock_obs):
        """pixel_action with action_type='done' should return done=True."""
        mock_obs.return_value = BenchmarkObservation(viewport=(1920, 1200))
        adapter = _make_adapter()

        _, done, _ = adapter.pixel_action(action_type="done")
        assert done is True
        # _send_command should NOT be called for done actions
        mock_send.assert_not_called()


class TestPixelActionFracConversion:
    """Tests that fractional coordinates are converted to absolute pixels."""

    @patch.object(WAALiveAdapter, "_get_observation")
    @patch.object(WAALiveAdapter, "_send_command")
    def test_frac_to_pixel_conversion(self, mock_send, mock_obs):
        mock_obs.return_value = BenchmarkObservation(viewport=(1920, 1200))
        adapter = _make_adapter()

        adapter.pixel_action(x_frac=0.5, y_frac=0.5)
        # 0.5 * 1920 = 960, 0.5 * 1200 = 600
        mock_send.assert_called_once_with(
            "import pyautogui; pyautogui.click(960, 600)"
        )

    @patch.object(WAALiveAdapter, "_get_observation")
    @patch.object(WAALiveAdapter, "_send_command")
    def test_frac_overrides_absolute(self, mock_send, mock_obs):
        """x_frac/y_frac should override x/y when both are provided."""
        mock_obs.return_value = BenchmarkObservation(viewport=(1920, 1200))
        adapter = _make_adapter()

        adapter.pixel_action(x=100, y=100, x_frac=0.5, y_frac=0.5)
        # Fracs override: 0.5 * 1920 = 960, 0.5 * 1200 = 600
        mock_send.assert_called_once_with(
            "import pyautogui; pyautogui.click(960, 600)"
        )

    @patch.object(WAALiveAdapter, "_get_observation")
    @patch.object(WAALiveAdapter, "_send_command")
    def test_corner_frac_clamped(self, mock_send, mock_obs):
        """Fraction at (0.0, 0.0) should be clamped to safe margin."""
        mock_obs.return_value = BenchmarkObservation(viewport=(1920, 1200))
        adapter = _make_adapter()

        adapter.pixel_action(x_frac=0.0, y_frac=0.0)
        # 0.0 * 1920 = 0, 0.0 * 1200 = 0 -> clamped to (5, 5)
        mock_send.assert_called_once_with(
            "import pyautogui; pyautogui.click(5, 5)"
        )


class TestSendCommandRefactor:
    """Tests that step() still works correctly after _send_command extraction."""

    @patch.object(WAALiveAdapter, "_get_observation")
    @patch.object(WAALiveAdapter, "_send_command")
    def test_step_delegates_to_send_command(self, mock_send, mock_obs):
        """step() should delegate command execution to _send_command."""
        mock_obs.return_value = BenchmarkObservation(viewport=(1920, 1200))
        adapter = _make_adapter()
        adapter._current_rects = {"btn1": [400, 100, 500, 140]}

        action = BenchmarkAction(
            type="click", target_node_id="btn1"
        )
        adapter.step(action)
        mock_send.assert_called_once()
        # The command should be an element-grounded click via _translate_action
        call_arg = mock_send.call_args[0][0]
        assert "pyautogui.click(450, 120)" in call_arg

    @patch.object(WAALiveAdapter, "_get_observation")
    @patch.object(WAALiveAdapter, "_send_command")
    def test_step_done_does_not_send(self, mock_send, mock_obs):
        """step() with done action should not call _send_command."""
        mock_obs.return_value = BenchmarkObservation(viewport=(1920, 1200))
        adapter = _make_adapter()

        _, done, _ = adapter.step(BenchmarkAction(type="done"))
        assert done is True
        mock_send.assert_not_called()

    @patch.object(WAALiveAdapter, "_get_observation")
    @patch.object(WAALiveAdapter, "_send_command")
    def test_step_increments_step_count(self, mock_send, mock_obs):
        """step() should still increment step count after refactor."""
        mock_obs.return_value = BenchmarkObservation(viewport=(1920, 1200))
        adapter = _make_adapter()

        adapter.step(BenchmarkAction(type="click", x=500, y=300))
        assert adapter._step_count == 1

    @patch.object(WAALiveAdapter, "_get_observation")
    @patch.object(WAALiveAdapter, "_send_command")
    def test_step_returns_command_in_info(self, mock_send, mock_obs):
        """step() info dict should contain the command."""
        mock_obs.return_value = BenchmarkObservation(viewport=(1920, 1200))
        adapter = _make_adapter()

        _, _, info = adapter.step(BenchmarkAction(type="wait"))
        assert info["command"] == "import time; time.sleep(1)"
