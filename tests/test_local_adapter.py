"""Tests for LocalAdapter."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from openadapt_evals.adapters.base import (
    BenchmarkAction,
    BenchmarkObservation,
    BenchmarkResult,
    BenchmarkTask,
)
from openadapt_evals.adapters.local import LocalAdapter


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def adapter():
    """Create a LocalAdapter with no action delay for fast tests."""
    return LocalAdapter(action_delay=0.0)


@pytest.fixture
def sample_task():
    """A minimal task for testing."""
    return BenchmarkTask(
        task_id="local_test_1",
        instruction="Open Notepad and type hello",
        domain="desktop",
    )


# Minimal valid 1x1 PNG for mocking screenshot captures.
MINIMAL_PNG = bytes(
    [
        0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A,
        0x00, 0x00, 0x00, 0x0D, 0x49, 0x48, 0x44, 0x52,
        0x00, 0x00, 0x00, 0x01, 0x00, 0x00, 0x00, 0x01,
        0x08, 0x02, 0x00, 0x00, 0x00, 0x90, 0x77, 0x53,
        0xDE, 0x00, 0x00, 0x00, 0x0C, 0x49, 0x44, 0x41,
        0x54, 0x08, 0xD7, 0x63, 0xF8, 0xCF, 0xC0, 0x00,
        0x00, 0x00, 0x03, 0x00, 0x01, 0x00, 0x05, 0xFE,
        0xD4, 0xEF, 0x00, 0x00, 0x00, 0x00, 0x49, 0x45,
        0x4E, 0x44, 0xAE, 0x42, 0x60, 0x82,
    ]
)


def _make_mock_observe(adapter):
    """Patch adapter.observe to return a fake observation without screen capture."""

    def _fake_observe():
        return BenchmarkObservation(
            screenshot=MINIMAL_PNG,
            viewport=(1920, 1080),
        )

    adapter.observe = _fake_observe  # type: ignore[assignment]


# ---------------------------------------------------------------------------
# Properties
# ---------------------------------------------------------------------------


class TestLocalAdapterProperties:
    def test_name(self, adapter):
        assert adapter.name == "local"

    def test_benchmark_type(self, adapter):
        assert adapter.benchmark_type == "interactive"


# ---------------------------------------------------------------------------
# observe()
# ---------------------------------------------------------------------------


class TestLocalAdapterObserve:
    @patch("openadapt_evals.adapters.local.adapter.mss", create=True)
    def test_observe_returns_observation(self, adapter):
        """observe() returns a BenchmarkObservation with screenshot bytes."""
        _make_mock_observe(adapter)
        obs = adapter.observe()
        assert isinstance(obs, BenchmarkObservation)
        assert obs.screenshot is not None
        assert isinstance(obs.screenshot, bytes)
        assert len(obs.screenshot) > 0

    @patch("openadapt_evals.adapters.local.adapter.mss", create=True)
    def test_observe_has_viewport(self, adapter):
        """observe() populates the viewport tuple."""
        _make_mock_observe(adapter)
        obs = adapter.observe()
        assert obs.viewport is not None
        assert len(obs.viewport) == 2


# ---------------------------------------------------------------------------
# reset()
# ---------------------------------------------------------------------------


class TestLocalAdapterReset:
    def test_reset_returns_observation(self, adapter, sample_task):
        _make_mock_observe(adapter)
        obs = adapter.reset(sample_task)
        assert isinstance(obs, BenchmarkObservation)

    def test_reset_records_task(self, adapter, sample_task):
        _make_mock_observe(adapter)
        adapter.reset(sample_task)
        assert adapter._current_task is sample_task

    def test_reset_clears_step_count(self, adapter, sample_task):
        _make_mock_observe(adapter)
        adapter._step_count = 5
        adapter.reset(sample_task)
        assert adapter._step_count == 0


# ---------------------------------------------------------------------------
# step()
# ---------------------------------------------------------------------------


class TestLocalAdapterStep:
    def test_step_returns_tuple(self, adapter, sample_task):
        _make_mock_observe(adapter)
        adapter.reset(sample_task)

        with patch.object(adapter, "_execute_action"):
            obs, done, info = adapter.step(BenchmarkAction(type="click", x=100, y=200))
        assert isinstance(obs, BenchmarkObservation)
        assert isinstance(done, bool)
        assert isinstance(info, dict)

    def test_step_increments_count(self, adapter, sample_task):
        _make_mock_observe(adapter)
        adapter.reset(sample_task)

        with patch.object(adapter, "_execute_action"):
            adapter.step(BenchmarkAction(type="click", x=100, y=200))
        assert adapter._step_count == 1

    def test_step_done_action_sets_done_true(self, adapter, sample_task):
        _make_mock_observe(adapter)
        adapter.reset(sample_task)

        with patch.object(adapter, "_execute_action"):
            _, done, _ = adapter.step(BenchmarkAction(type="done"))
        assert done is True

    def test_step_click_dispatches(self, adapter, sample_task):
        _make_mock_observe(adapter)
        adapter.reset(sample_task)

        with patch.object(adapter, "_do_click") as mock_click:
            with patch.object(adapter, "observe", return_value=BenchmarkObservation()):
                adapter.step(BenchmarkAction(type="click", x=50, y=60))
            mock_click.assert_called_once()

    def test_step_type_dispatches(self, adapter, sample_task):
        _make_mock_observe(adapter)
        adapter.reset(sample_task)

        with patch.object(adapter, "_do_type") as mock_type:
            with patch.object(adapter, "observe", return_value=BenchmarkObservation()):
                adapter.step(BenchmarkAction(type="type", text="hello"))
            mock_type.assert_called_once()

    def test_step_key_dispatches(self, adapter, sample_task):
        _make_mock_observe(adapter)
        adapter.reset(sample_task)

        with patch.object(adapter, "_do_key") as mock_key:
            with patch.object(adapter, "observe", return_value=BenchmarkObservation()):
                adapter.step(BenchmarkAction(type="key", key="enter"))
            mock_key.assert_called_once()

    def test_step_error_action_sets_done_true(self, adapter, sample_task):
        _make_mock_observe(adapter)
        adapter.reset(sample_task)

        with patch.object(adapter, "_execute_action"):
            _, done, _ = adapter.step(BenchmarkAction(type="error"))
        assert done is True

    def test_step_handles_execution_error(self, adapter, sample_task):
        _make_mock_observe(adapter)
        adapter.reset(sample_task)

        with patch.object(adapter, "_execute_action", side_effect=RuntimeError("perm")):
            obs, done, info = adapter.step(BenchmarkAction(type="click", x=1, y=1))

        assert done is True
        assert "error" in info


# ---------------------------------------------------------------------------
# evaluate()
# ---------------------------------------------------------------------------


class TestLocalAdapterEvaluate:
    def test_evaluate_returns_result(self, adapter, sample_task):
        result = adapter.evaluate(sample_task)
        assert isinstance(result, BenchmarkResult)
        assert result.task_id == sample_task.task_id

    def test_evaluate_score_is_zero(self, adapter, sample_task):
        result = adapter.evaluate(sample_task)
        assert result.score == 0.0
        assert result.success is False


# ---------------------------------------------------------------------------
# list_tasks / load_task
# ---------------------------------------------------------------------------


class TestLocalAdapterTasks:
    def test_list_tasks_empty(self, adapter):
        assert adapter.list_tasks() == []

    def test_load_task_raises(self, adapter):
        with pytest.raises(KeyError):
            adapter.load_task("nonexistent")


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------


class TestLocalAdapterContextManager:
    def test_context_manager(self):
        with LocalAdapter() as adapter:
            assert isinstance(adapter, LocalAdapter)


# ---------------------------------------------------------------------------
# HiDPI scaling
# ---------------------------------------------------------------------------


class TestLocalAdapterScaling:
    def test_to_logical_scale_1(self, adapter):
        adapter._scale = 1.0
        assert adapter._to_logical(100, 200) == (100.0, 200.0)

    def test_to_logical_scale_2(self, adapter):
        adapter._scale = 2.0
        lx, ly = adapter._to_logical(200, 400)
        assert lx == pytest.approx(100.0)
        assert ly == pytest.approx(200.0)


# ---------------------------------------------------------------------------
# Key resolution
# ---------------------------------------------------------------------------


class TestKeyResolution:
    def test_known_key(self):
        from pynput.keyboard import Key  # type: ignore[import-untyped]

        resolved = LocalAdapter._resolve_key("enter")
        assert resolved == Key.enter

    def test_single_char(self):
        resolved = LocalAdapter._resolve_key("a")
        assert resolved == "a"

    def test_case_insensitive(self):
        from pynput.keyboard import Key  # type: ignore[import-untyped]

        assert LocalAdapter._resolve_key("ENTER") == Key.enter
        assert LocalAdapter._resolve_key("Tab") == Key.tab
