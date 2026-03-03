"""Tests for the demo-conditioned controller.

Tests the DemoController state machine logic with mocked agent, adapter,
and verifier to avoid real API calls.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from openadapt_evals.adapters.base import (
    BenchmarkAction,
    BenchmarkObservation,
    BenchmarkResult,
    BenchmarkTask,
)
from openadapt_evals.demo_controller import (
    DemoController,
    PlanState,
    PlanStep,
    run_with_controller,
)
from openadapt_evals.plan_verify import VerificationResult


# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------

SAMPLE_DEMO = """\
GOAL: Create a new spreadsheet with headers Year, CA changes, FA changes, OA changes

PLAN:
1. Create a new sheet
2. Add header row
3. Enter year data

REFERENCE TRAJECTORY (for disambiguation -- adapt actions to your actual screen):

Step 1:
  Think: I need to create a new sheet.
  Action: Right-click on Sheet1 tab and select Insert Sheet.
  Expect: A new blank sheet named Sheet2 should appear.

Step 2:
  Think: I need to add headers.
  Action: Click cell A1 and type Year, then Tab and type CA changes.
  Expect: Headers Year and CA changes should appear in A1 and B1.

Step 3:
  Think: I need to add more headers.
  Action: Press Tab and type FA changes, then Tab and type OA changes.
  Expect: All four headers should be visible in row 1.
"""

SIMPLE_DEMO = "Just click the button and type hello."


def _make_task(task_id: str = "test-task-001") -> BenchmarkTask:
    return BenchmarkTask(
        task_id=task_id,
        instruction="Create a spreadsheet with asset changes",
        domain="desktop",
    )


def _make_obs(screenshot: bytes | None = b"fake-png-bytes") -> BenchmarkObservation:
    return BenchmarkObservation(screenshot=screenshot)


def _make_verified() -> VerificationResult:
    return VerificationResult(
        status="verified",
        confidence=0.9,
        explanation="Step completed successfully",
        raw_response='{"status":"verified","confidence":0.9,"explanation":"ok"}',
    )


def _make_not_verified() -> VerificationResult:
    return VerificationResult(
        status="not_verified",
        confidence=0.8,
        explanation="Expected outcome not visible",
        raw_response='{"status":"not_verified","confidence":0.8,"explanation":"not visible"}',
    )


def _make_unclear() -> VerificationResult:
    return VerificationResult(
        status="unclear",
        confidence=0.3,
        explanation="Cannot determine",
        raw_response='{"status":"unclear","confidence":0.3,"explanation":"cannot tell"}',
    )


def _make_goal_verified() -> VerificationResult:
    return VerificationResult(
        status="verified",
        confidence=0.95,
        explanation="Goal achieved",
        raw_response='{"status":"verified","confidence":0.95,"explanation":"done"}',
    )


def _make_goal_not_verified() -> VerificationResult:
    return VerificationResult(
        status="not_verified",
        confidence=0.7,
        explanation="Goal not yet achieved",
        raw_response='{"status":"not_verified","confidence":0.7,"explanation":"not done"}',
    )


def _make_click_action() -> BenchmarkAction:
    return BenchmarkAction(type="click", x=0.5, y=0.5, raw_action={"test": True})


def _make_done_action() -> BenchmarkAction:
    return BenchmarkAction(type="done", raw_action={"reason": "completed"})


def _make_error_action() -> BenchmarkAction:
    return BenchmarkAction(
        type="error",
        raw_action={"reason": "api_failed", "error_type": "infrastructure"},
    )


# ---------------------------------------------------------------------------
# Test PlanStep and PlanState creation
# ---------------------------------------------------------------------------


class TestPlanStep:
    def test_default_values(self):
        step = PlanStep(
            step_num=1,
            think="Think about it",
            action="Do the thing",
            expect="Thing is done",
        )
        assert step.step_num == 1
        assert step.think == "Think about it"
        assert step.action == "Do the thing"
        assert step.expect == "Thing is done"
        assert step.status == "pending"
        assert step.attempts == 0
        assert step.verification_result is None

    def test_custom_status(self):
        step = PlanStep(
            step_num=5,
            think="t",
            action="a",
            expect="e",
            status="done",
            attempts=3,
        )
        assert step.status == "done"
        assert step.attempts == 3

    def test_with_verification_result(self):
        vr = _make_verified()
        step = PlanStep(
            step_num=1,
            think="t",
            action="a",
            expect="e",
            verification_result=vr,
        )
        assert step.verification_result is not None
        assert step.verification_result.status == "verified"


class TestPlanState:
    def test_default_values(self):
        state = PlanState(
            goal="Do something",
            plan_summary=["Step 1", "Step 2"],
            steps=[
                PlanStep(step_num=1, think="t1", action="a1", expect="e1"),
                PlanStep(step_num=2, think="t2", action="a2", expect="e2"),
            ],
        )
        assert state.goal == "Do something"
        assert len(state.plan_summary) == 2
        assert len(state.steps) == 2
        assert state.current_step_idx == 0
        assert state.total_attempts == 0
        assert state.replans == 0

    def test_custom_values(self):
        state = PlanState(
            goal="g",
            plan_summary=[],
            steps=[],
            current_step_idx=5,
            total_attempts=10,
            replans=2,
        )
        assert state.current_step_idx == 5
        assert state.total_attempts == 10
        assert state.replans == 2


# ---------------------------------------------------------------------------
# Test DemoController initialization
# ---------------------------------------------------------------------------


class TestDemoControllerInit:
    def test_init_with_multilevel_demo(self):
        agent = MagicMock()
        adapter = MagicMock()

        controller = DemoController(
            agent=agent,
            adapter=adapter,
            demo_text=SAMPLE_DEMO,
        )

        assert controller.plan_state.goal.startswith("Create a new spreadsheet")
        assert len(controller.plan_state.plan_summary) == 3
        assert len(controller.plan_state.steps) == 3
        assert controller.plan_state.steps[0].step_num == 1
        assert controller.plan_state.steps[1].step_num == 2
        assert controller.plan_state.steps[2].step_num == 3
        assert "Right-click" in controller.plan_state.steps[0].action
        assert controller.max_retries == 2
        assert controller.max_replans == 2
        assert controller.verify_model == "gpt-4.1-mini"

    def test_init_with_simple_demo(self):
        agent = MagicMock()
        adapter = MagicMock()

        controller = DemoController(
            agent=agent,
            adapter=adapter,
            demo_text=SIMPLE_DEMO,
        )

        # Falls back to single-step plan
        assert len(controller.plan_state.steps) == 1
        assert controller.plan_state.steps[0].action == "Execute the task as described"

    def test_init_custom_params(self):
        agent = MagicMock()
        adapter = MagicMock()

        controller = DemoController(
            agent=agent,
            adapter=adapter,
            demo_text=SAMPLE_DEMO,
            max_retries=5,
            max_replans=3,
            verify_model="gpt-4o",
            verify_provider="anthropic",
        )

        assert controller.max_retries == 5
        assert controller.max_replans == 3
        assert controller.verify_model == "gpt-4o"
        assert controller.verify_provider == "anthropic"


# ---------------------------------------------------------------------------
# Test _build_step_prompt
# ---------------------------------------------------------------------------


class TestBuildStepPrompt:
    def test_first_step_prompt(self):
        agent = MagicMock()
        adapter = MagicMock()
        controller = DemoController(
            agent=agent, adapter=adapter, demo_text=SAMPLE_DEMO
        )

        step = controller.plan_state.steps[0]
        prompt = controller._build_step_prompt(step, controller.plan_state)

        assert "GOAL:" in prompt
        assert "PLAN PROGRESS: Step 1/3" in prompt
        assert "Completed: (none yet)" in prompt
        assert "Current: Step 1" in prompt
        assert "YOUR CURRENT TASK:" in prompt
        assert "Think:" in prompt
        assert "Action:" in prompt
        assert "Expect:" in prompt
        assert "Remaining: [Step 2, Step 3]" in prompt

    def test_middle_step_prompt_with_completed(self):
        agent = MagicMock()
        adapter = MagicMock()
        controller = DemoController(
            agent=agent, adapter=adapter, demo_text=SAMPLE_DEMO
        )

        # Mark first step as done
        controller.plan_state.steps[0].status = "done"
        controller.plan_state.current_step_idx = 1

        step = controller.plan_state.steps[1]
        prompt = controller._build_step_prompt(step, controller.plan_state)

        assert "PLAN PROGRESS: Step 2/3" in prompt
        assert "Completed: [Step 1]" in prompt
        assert "Current: Step 2" in prompt
        assert "Remaining: [Step 3]" in prompt

    def test_last_step_prompt(self):
        agent = MagicMock()
        adapter = MagicMock()
        controller = DemoController(
            agent=agent, adapter=adapter, demo_text=SAMPLE_DEMO
        )

        controller.plan_state.steps[0].status = "done"
        controller.plan_state.steps[1].status = "done"
        controller.plan_state.current_step_idx = 2

        step = controller.plan_state.steps[2]
        prompt = controller._build_step_prompt(step, controller.plan_state)

        assert "PLAN PROGRESS: Step 3/3" in prompt
        assert "Completed: [Step 1, Step 2]" in prompt
        assert "this is the last step" in prompt.lower()

    def test_retry_context_in_prompt(self):
        agent = MagicMock()
        adapter = MagicMock()
        controller = DemoController(
            agent=agent, adapter=adapter, demo_text=SAMPLE_DEMO
        )

        step = controller.plan_state.steps[0]
        step.attempts = 1
        step.verification_result = _make_not_verified()

        prompt = controller._build_step_prompt(step, controller.plan_state)

        assert "attempt 2" in prompt.lower()
        assert "Previous attempt result: not_verified" in prompt
        assert "different approach" in prompt.lower()


# ---------------------------------------------------------------------------
# Test _advance state transitions
# ---------------------------------------------------------------------------


class TestAdvance:
    def test_advance_from_first_step(self):
        agent = MagicMock()
        adapter = MagicMock()
        controller = DemoController(
            agent=agent, adapter=adapter, demo_text=SAMPLE_DEMO
        )

        controller.plan_state.steps[0].status = "in_progress"
        controller._advance()

        assert controller.plan_state.steps[0].status == "done"
        assert controller.plan_state.current_step_idx == 1

    def test_advance_from_middle_step(self):
        agent = MagicMock()
        adapter = MagicMock()
        controller = DemoController(
            agent=agent, adapter=adapter, demo_text=SAMPLE_DEMO
        )

        controller.plan_state.steps[0].status = "done"
        controller.plan_state.current_step_idx = 1
        controller.plan_state.steps[1].status = "in_progress"
        controller._advance()

        assert controller.plan_state.steps[1].status == "done"
        assert controller.plan_state.current_step_idx == 2

    def test_advance_past_last_step(self):
        agent = MagicMock()
        adapter = MagicMock()
        controller = DemoController(
            agent=agent, adapter=adapter, demo_text=SAMPLE_DEMO
        )

        controller.plan_state.current_step_idx = 2
        controller.plan_state.steps[2].status = "in_progress"
        controller._advance()

        assert controller.plan_state.current_step_idx == 3
        assert controller._current_step() is None

    def test_advance_does_not_overwrite_failed(self):
        agent = MagicMock()
        adapter = MagicMock()
        controller = DemoController(
            agent=agent, adapter=adapter, demo_text=SAMPLE_DEMO
        )

        controller.plan_state.steps[0].status = "failed"
        controller._advance()

        # Failed status is preserved (it's a terminal state)
        assert controller.plan_state.steps[0].status == "failed"
        assert controller.plan_state.current_step_idx == 1


# ---------------------------------------------------------------------------
# Test _all_steps_done
# ---------------------------------------------------------------------------


class TestAllStepsDone:
    def test_no_steps_done(self):
        agent = MagicMock()
        adapter = MagicMock()
        controller = DemoController(
            agent=agent, adapter=adapter, demo_text=SAMPLE_DEMO
        )
        assert not controller._all_steps_done()

    def test_all_steps_done(self):
        agent = MagicMock()
        adapter = MagicMock()
        controller = DemoController(
            agent=agent, adapter=adapter, demo_text=SAMPLE_DEMO
        )
        for s in controller.plan_state.steps:
            s.status = "done"
        assert controller._all_steps_done()

    def test_mixed_terminal_states(self):
        agent = MagicMock()
        adapter = MagicMock()
        controller = DemoController(
            agent=agent, adapter=adapter, demo_text=SAMPLE_DEMO
        )
        controller.plan_state.steps[0].status = "done"
        controller.plan_state.steps[1].status = "failed"
        controller.plan_state.steps[2].status = "skipped"
        assert controller._all_steps_done()

    def test_one_pending_not_done(self):
        agent = MagicMock()
        adapter = MagicMock()
        controller = DemoController(
            agent=agent, adapter=adapter, demo_text=SAMPLE_DEMO
        )
        controller.plan_state.steps[0].status = "done"
        controller.plan_state.steps[1].status = "done"
        controller.plan_state.steps[2].status = "pending"
        assert not controller._all_steps_done()


# ---------------------------------------------------------------------------
# Test full execute loop with mocked dependencies
# ---------------------------------------------------------------------------


class TestExecuteLoop:
    """Integration tests for the full execute() state machine."""

    def _make_controller(
        self,
        agent_actions: list[BenchmarkAction] | None = None,
        verify_results: list[VerificationResult] | None = None,
        goal_result: VerificationResult | None = None,
        eval_result: BenchmarkResult | None = None,
    ) -> tuple[DemoController, MagicMock, MagicMock]:
        """Create a DemoController with mocked dependencies.

        Args:
            agent_actions: Actions the agent will return in sequence.
            verify_results: Step verification results in sequence.
            goal_result: Goal verification result.
            eval_result: Result from adapter.evaluate().

        Returns:
            Tuple of (controller, mock_agent, mock_adapter).
        """
        mock_agent = MagicMock()
        mock_adapter = MagicMock()

        # Default agent: always returns click actions
        if agent_actions is None:
            agent_actions = [_make_click_action()] * 20
        mock_agent.act.side_effect = agent_actions

        # Default adapter: returns observation with screenshot
        mock_adapter.reset.return_value = _make_obs()
        mock_adapter.step.return_value = (_make_obs(), False, {})

        # Default eval result
        if eval_result is None:
            eval_result = BenchmarkResult(
                task_id="test-task-001", success=True, score=1.0
            )
        mock_adapter.evaluate.return_value = eval_result

        controller = DemoController(
            agent=mock_agent,
            adapter=mock_adapter,
            demo_text=SAMPLE_DEMO,
        )

        # Mock verification
        if verify_results is None:
            verify_results = [_make_verified()] * 10

        if goal_result is None:
            goal_result = _make_goal_verified()

        return controller, mock_agent, mock_adapter, verify_results, goal_result

    @patch("openadapt_evals.demo_controller.verify_goal_completion")
    @patch("openadapt_evals.demo_controller.verify_step")
    def test_all_steps_verify_success(self, mock_verify_step, mock_verify_goal):
        """All steps verify on first try -> success."""
        controller, mock_agent, mock_adapter, _, _ = self._make_controller()

        mock_verify_step.return_value = _make_verified()
        mock_verify_goal.return_value = _make_goal_verified()

        task = _make_task()
        result = controller.execute(task, max_steps=30)

        # Agent reset was called
        mock_agent.reset.assert_called_once()
        mock_adapter.reset.assert_called_once_with(task)

        # All 3 steps should be done
        for step in controller.plan_state.steps:
            assert step.status == "done"

        # verify_step called 3 times (once per step)
        assert mock_verify_step.call_count == 3

        # Goal verified
        mock_verify_goal.assert_called_once()

        # Result should come from adapter.evaluate()
        assert result.success is True
        assert result.score == 1.0

    @patch("openadapt_evals.demo_controller.verify_goal_completion")
    @patch("openadapt_evals.demo_controller.verify_step")
    def test_step_fails_then_retries_then_verifies(
        self, mock_verify_step, mock_verify_goal
    ):
        """Step fails, retries once, then verifies -> advance."""
        controller, mock_agent, mock_adapter, _, _ = self._make_controller()

        # Step 1: fail, then verify on retry
        # Step 2: verify immediately
        # Step 3: verify immediately
        verify_sequence = [
            _make_not_verified(),  # Step 1, attempt 1
            _make_verified(),      # Step 1, attempt 2 (retry)
            _make_verified(),      # Step 2
            _make_verified(),      # Step 3
        ]
        mock_verify_step.side_effect = verify_sequence
        mock_verify_goal.return_value = _make_goal_verified()

        task = _make_task()
        result = controller.execute(task, max_steps=30)

        assert result.success is True
        assert controller.plan_state.steps[0].status == "done"
        assert controller.plan_state.steps[0].attempts == 2
        assert mock_verify_step.call_count == 4

    @patch("openadapt_evals.demo_controller.verify_goal_completion")
    @patch("openadapt_evals.demo_controller.verify_step")
    def test_step_fails_max_retries_triggers_replan(
        self, mock_verify_step, mock_verify_goal
    ):
        """Step fails max_retries times -> replan is triggered."""
        controller, mock_agent, mock_adapter, _, _ = self._make_controller()
        controller.max_retries = 2

        # Step 1: fail twice (max_retries), then replan generates a single new step
        verify_sequence = [
            _make_not_verified(),  # Step 1, attempt 1
            _make_not_verified(),  # Step 1, attempt 2 -> triggers replan
            _make_verified(),      # New step from replan
            _make_verified(),      # Step 2 (original)
            _make_verified(),      # Step 3 (original)
        ]
        mock_verify_step.side_effect = verify_sequence
        mock_verify_goal.return_value = _make_goal_verified()

        # Mock the VLM replan call
        replan_response = (
            "Step 1:\n"
            "  Think: Alternative approach.\n"
            "  Action: Try clicking elsewhere.\n"
            "  Expect: Sheet should appear.\n"
        )

        with patch("openadapt_evals.demo_controller.DemoController._replan") as mock_replan:
            # Instead of actually replanning, just skip the failed step
            def fake_replan(obs, failed_step):
                failed_step.status = "failed"
                controller.plan_state.replans += 1
                controller._advance()

            mock_replan.side_effect = fake_replan

            task = _make_task()
            result = controller.execute(task, max_steps=30)

        assert controller.plan_state.replans == 1
        assert controller.plan_state.steps[0].status == "failed"

    @patch("openadapt_evals.demo_controller.verify_goal_completion")
    @patch("openadapt_evals.demo_controller.verify_step")
    def test_agent_says_done_but_steps_remain_override(
        self, mock_verify_step, mock_verify_goal
    ):
        """Agent declares done but steps remain -> override and continue."""
        mock_agent = MagicMock()
        mock_adapter = MagicMock()

        # Agent says done on first call, then gives click actions
        mock_agent.act.side_effect = [
            _make_done_action(),   # Step 1: agent says done prematurely
            _make_click_action(),  # Step 2: normal
            _make_click_action(),  # Step 3: normal
        ]
        mock_adapter.reset.return_value = _make_obs()
        mock_adapter.step.return_value = (_make_obs(), False, {})
        mock_adapter.evaluate.return_value = BenchmarkResult(
            task_id="test-task-001", success=True, score=1.0
        )

        controller = DemoController(
            agent=mock_agent,
            adapter=mock_adapter,
            demo_text=SAMPLE_DEMO,
        )

        # Step 1 is overridden (done), steps 2 and 3 verify
        mock_verify_step.side_effect = [
            _make_verified(),  # Step 2
            _make_verified(),  # Step 3
        ]
        mock_verify_goal.return_value = _make_goal_verified()

        task = _make_task()
        result = controller.execute(task, max_steps=30)

        # Step 1 was force-marked done (override)
        assert controller.plan_state.steps[0].status == "done"
        # Other steps verified normally
        assert controller.plan_state.steps[1].status == "done"
        assert controller.plan_state.steps[2].status == "done"

        # adapter.step was NOT called for the done override (no action executed)
        # It was called for steps 2 and 3
        assert mock_adapter.step.call_count == 2

    @patch("openadapt_evals.demo_controller.verify_goal_completion")
    @patch("openadapt_evals.demo_controller.verify_step")
    def test_agent_error_returns_failure(self, mock_verify_step, mock_verify_goal):
        """Agent returns error action -> immediate failure."""
        mock_agent = MagicMock()
        mock_adapter = MagicMock()

        mock_agent.act.return_value = _make_error_action()
        mock_adapter.reset.return_value = _make_obs()
        mock_adapter.evaluate.return_value = BenchmarkResult(
            task_id="test-task-001", success=False, score=0.0
        )

        controller = DemoController(
            agent=mock_agent,
            adapter=mock_adapter,
            demo_text=SAMPLE_DEMO,
        )

        task = _make_task()
        result = controller.execute(task, max_steps=30)

        assert result.success is False
        assert result.error_type == "infrastructure"

    @patch("openadapt_evals.demo_controller.verify_goal_completion")
    @patch("openadapt_evals.demo_controller.verify_step")
    def test_max_steps_reached(self, mock_verify_step, mock_verify_goal):
        """Execution reaches max_steps -> returns adapter.evaluate() result."""
        controller, mock_agent, mock_adapter, _, _ = self._make_controller()

        # Verification always says unclear, so we never advance
        mock_verify_step.return_value = _make_unclear()

        task = _make_task()
        result = controller.execute(task, max_steps=3)

        # Should have attempted exactly 3 steps
        assert controller.plan_state.total_attempts == 3

    @patch("openadapt_evals.demo_controller.verify_goal_completion")
    @patch("openadapt_evals.demo_controller.verify_step")
    def test_env_done_signal(self, mock_verify_step, mock_verify_goal):
        """Environment signals done -> exit loop early."""
        mock_agent = MagicMock()
        mock_adapter = MagicMock()

        mock_agent.act.return_value = _make_click_action()
        mock_adapter.reset.return_value = _make_obs()
        # Second step: env says done
        mock_adapter.step.side_effect = [
            (_make_obs(), False, {}),
            (_make_obs(), True, {}),   # env done
        ]
        mock_adapter.evaluate.return_value = BenchmarkResult(
            task_id="test-task-001", success=True, score=0.8
        )

        controller = DemoController(
            agent=mock_agent,
            adapter=mock_adapter,
            demo_text=SAMPLE_DEMO,
        )

        mock_verify_step.side_effect = [
            _make_verified(),   # Step 1 verifies
            _make_verified(),   # Step 2 verifies, but env also says done
        ]

        task = _make_task()
        result = controller.execute(task, max_steps=30)

        # Exited due to env done, not all steps completed
        assert result.score == 0.8

    @patch("openadapt_evals.demo_controller.verify_goal_completion")
    @patch("openadapt_evals.demo_controller.verify_step")
    def test_no_screenshot_skips_verification(
        self, mock_verify_step, mock_verify_goal
    ):
        """No screenshot in observation -> skip verification, continue."""
        mock_agent = MagicMock()
        mock_adapter = MagicMock()

        mock_agent.act.return_value = _make_click_action()
        mock_adapter.reset.return_value = _make_obs(screenshot=None)
        mock_adapter.step.return_value = (_make_obs(screenshot=None), False, {})
        mock_adapter.evaluate.return_value = BenchmarkResult(
            task_id="test-task-001", success=False, score=0.0
        )

        controller = DemoController(
            agent=mock_agent,
            adapter=mock_adapter,
            demo_text=SAMPLE_DEMO,
        )

        task = _make_task()
        # With no screenshots, verification is skipped but loop continues
        result = controller.execute(task, max_steps=5)

        # verify_step should not have been called (no screenshots)
        mock_verify_step.assert_not_called()


# ---------------------------------------------------------------------------
# Test _parse_replan_response
# ---------------------------------------------------------------------------


class TestParseReplanResponse:
    def test_parse_valid_response(self):
        agent = MagicMock()
        adapter = MagicMock()
        controller = DemoController(
            agent=agent, adapter=adapter, demo_text=SAMPLE_DEMO
        )

        response = """\
Step 4:
  Think: Need to try different approach.
  Action: Click on the plus icon.
  Expect: New sheet should be created.

Step 5:
  Think: Now add headers.
  Action: Type headers in row 1.
  Expect: Headers visible in row 1.
"""
        steps = controller._parse_replan_response(response)

        assert len(steps) == 2
        assert steps[0].step_num == 4
        assert "different approach" in steps[0].think
        assert "plus icon" in steps[0].action
        assert steps[1].step_num == 5

    def test_parse_empty_response(self):
        agent = MagicMock()
        adapter = MagicMock()
        controller = DemoController(
            agent=agent, adapter=adapter, demo_text=SAMPLE_DEMO
        )

        steps = controller._parse_replan_response("")
        assert steps == []

    def test_parse_malformed_response(self):
        agent = MagicMock()
        adapter = MagicMock()
        controller = DemoController(
            agent=agent, adapter=adapter, demo_text=SAMPLE_DEMO
        )

        steps = controller._parse_replan_response("Just do whatever seems right.")
        assert steps == []


# ---------------------------------------------------------------------------
# Test run_with_controller convenience function
# ---------------------------------------------------------------------------


class TestRunWithController:
    @patch("openadapt_evals.demo_controller.verify_goal_completion")
    @patch("openadapt_evals.demo_controller.verify_step")
    def test_run_with_controller(self, mock_verify_step, mock_verify_goal):
        """Convenience function creates controller and executes."""
        mock_agent = MagicMock()
        mock_adapter = MagicMock()

        mock_agent.act.return_value = _make_click_action()
        mock_adapter.reset.return_value = _make_obs()
        mock_adapter.step.return_value = (_make_obs(), False, {})
        mock_adapter.evaluate.return_value = BenchmarkResult(
            task_id="test-task-001", success=True, score=1.0
        )

        mock_verify_step.return_value = _make_verified()
        mock_verify_goal.return_value = _make_goal_verified()

        task = _make_task()
        result = run_with_controller(
            agent=mock_agent,
            adapter=mock_adapter,
            task=task,
            demo_text=SAMPLE_DEMO,
            max_steps=30,
            max_retries=2,
            max_replans=2,
        )

        assert result.success is True
        mock_agent.reset.assert_called_once()


# ---------------------------------------------------------------------------
# Test _get_screenshot_bytes
# ---------------------------------------------------------------------------


class TestGetScreenshotBytes:
    def test_from_screenshot_field(self):
        obs = _make_obs(screenshot=b"png-data")
        result = DemoController._get_screenshot_bytes(obs)
        assert result == b"png-data"

    def test_from_none(self):
        obs = _make_obs(screenshot=None)
        result = DemoController._get_screenshot_bytes(obs)
        assert result is None

    def test_from_screenshot_path(self, tmp_path):
        png_file = tmp_path / "test.png"
        png_file.write_bytes(b"file-png-data")

        obs = BenchmarkObservation(
            screenshot=None,
            screenshot_path=str(png_file),
        )
        result = DemoController._get_screenshot_bytes(obs)
        assert result == b"file-png-data"

    def test_from_missing_screenshot_path(self):
        obs = BenchmarkObservation(
            screenshot=None,
            screenshot_path="/nonexistent/path.png",
        )
        result = DemoController._get_screenshot_bytes(obs)
        assert result is None
