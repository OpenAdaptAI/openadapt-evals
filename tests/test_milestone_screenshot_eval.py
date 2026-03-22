"""Tests for evaluate_milestones_screenshot standalone function."""

from __future__ import annotations

from unittest.mock import patch

from openadapt_evals.task_config import (
    Milestone,
    TaskCheck,
    TaskConfig,
    evaluate_milestones_screenshot,
)


def _make_task_config(milestones):
    return TaskConfig(
        name="Test task",
        id="test-001",
        domain="desktop",
        setup=[],
        checks=[],
        combine="and",
        max_steps=15,
        milestones=milestones,
    )


class TestEvaluateMilestonesScreenshot:
    def test_no_milestones_returns_zero(self):
        task = _make_task_config([])
        assert evaluate_milestones_screenshot(task, b"fake-png") == 0.0

    def test_no_screenshot_milestones_returns_zero(self):
        """Non-screenshot milestones are skipped entirely."""
        task = _make_task_config([
            Milestone(
                name="Command check",
                check=TaskCheck(check="command", run="echo 1", expect="1"),
            ),
        ])
        assert evaluate_milestones_screenshot(task, b"fake-png") == 0.0

    @patch("openadapt_evals.vlm_evaluator.vlm_judge")
    def test_all_pass(self, mock_vlm):
        mock_vlm.return_value = (True, 0.95)
        task = _make_task_config([
            Milestone(
                name="App open",
                check=TaskCheck(check="screenshot", description="App is open"),
            ),
            Milestone(
                name="File loaded",
                check=TaskCheck(check="screenshot", description="File is loaded"),
            ),
        ])
        score = evaluate_milestones_screenshot(task, b"fake-png")
        assert score == 1.0
        assert mock_vlm.call_count == 2

    @patch("openadapt_evals.vlm_evaluator.vlm_judge")
    def test_partial_pass(self, mock_vlm):
        mock_vlm.side_effect = [(True, 0.9), (False, 0.3)]
        task = _make_task_config([
            Milestone(
                name="Step 1",
                check=TaskCheck(check="screenshot", description="Step 1 done"),
            ),
            Milestone(
                name="Step 2",
                check=TaskCheck(check="screenshot", description="Step 2 done"),
            ),
        ])
        score = evaluate_milestones_screenshot(task, b"fake-png")
        assert score == 0.5

    @patch("openadapt_evals.vlm_evaluator.vlm_judge")
    def test_skips_non_screenshot_milestones(self, mock_vlm):
        """Mixed milestones: only screenshot ones are evaluated."""
        mock_vlm.return_value = (True, 0.9)
        task = _make_task_config([
            Milestone(
                name="Command milestone",
                check=TaskCheck(check="command", run="echo 1", expect="1"),
            ),
            Milestone(
                name="Screenshot milestone",
                check=TaskCheck(check="screenshot", description="Something visible"),
            ),
        ])
        score = evaluate_milestones_screenshot(task, b"fake-png")
        assert score == 1.0  # 1/1 screenshot milestone passed
        mock_vlm.assert_called_once()

    @patch("openadapt_evals.vlm_evaluator.vlm_judge")
    def test_custom_model_passed_through(self, mock_vlm):
        mock_vlm.return_value = (True, 0.9)
        task = _make_task_config([
            Milestone(
                name="Check",
                check=TaskCheck(check="screenshot", description="Visible"),
            ),
        ])
        evaluate_milestones_screenshot(task, b"fake-png", model="gpt-4o")
        mock_vlm.assert_called_once_with(b"fake-png", "Visible", model="gpt-4o")

    @patch("openadapt_evals.vlm_evaluator.vlm_judge")
    def test_all_fail(self, mock_vlm):
        mock_vlm.return_value = (False, 0.2)
        task = _make_task_config([
            Milestone(
                name="Check",
                check=TaskCheck(check="screenshot", description="Not there"),
            ),
        ])
        score = evaluate_milestones_screenshot(task, b"fake-png")
        assert score == 0.0
