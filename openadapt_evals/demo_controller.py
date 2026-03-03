"""Demo-conditioned controller for step-by-step plan execution.

This module provides a state machine that executes a plan derived from a
demo, with step-level verification and re-planning.  The key insight is
that the recording pipeline (screenshot -> VLM generates steps -> human
executes -> VLM adapts) IS the execution pipeline with the human
replaced by automated verification.

During recording::

    screenshot -> VLM generates steps -> human executes step
    -> human checks result -> VLM adapts remaining steps -> repeat

The controller does::

    screenshot -> parse plan from demo -> agent executes step
    -> VLM verifies result -> advance or replan -> repeat

Usage::

    from openadapt_evals.demo_controller import DemoController, run_with_controller
    from openadapt_evals.agents import ClaudeComputerUseAgent

    demo_text = open("demo_multilevel.txt").read()
    agent = ClaudeComputerUseAgent(demo=demo_text)
    adapter = WAALiveAdapter(...)

    controller = DemoController(
        agent=agent,
        adapter=adapter,
        demo_text=demo_text,
    )
    result = controller.execute(task, max_steps=30)

    # Or use the convenience function:
    result = run_with_controller(agent, adapter, task, demo_text)
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from openadapt_evals.adapters.base import (
    BenchmarkAction,
    BenchmarkAdapter,
    BenchmarkObservation,
    BenchmarkResult,
    BenchmarkTask,
)
from openadapt_evals.agents.base import BenchmarkAgent
from openadapt_evals.agents.claude_computer_use_agent import _parse_multilevel_demo
from openadapt_evals.plan_verify import (
    VerificationResult,
    verify_goal_completion,
    verify_step,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class PlanStep:
    """A single step in the execution plan.

    Attributes:
        step_num: 1-indexed step number from the demo.
        think: The reasoning behind this step.
        action: The action description to execute.
        expect: The expected outcome after executing the action.
        status: Current execution status.
        attempts: Number of times this step has been attempted.
        verification_result: The last verification result for this step.
    """

    step_num: int
    think: str
    action: str
    expect: str
    status: str = "pending"  # "pending", "in_progress", "done", "failed", "skipped"
    attempts: int = 0
    verification_result: VerificationResult | None = None


@dataclass
class PlanState:
    """Full execution plan state.

    Attributes:
        goal: The high-level task goal.
        plan_summary: High-level plan steps (from the PLAN section).
        steps: Detailed trajectory steps (from the REFERENCE TRAJECTORY).
        current_step_idx: Index into ``steps`` for the current step.
        total_attempts: Total number of agent actions executed.
        replans: Number of times the remaining plan has been regenerated.
    """

    goal: str
    plan_summary: list[str]
    steps: list[PlanStep]
    current_step_idx: int = 0
    total_attempts: int = 0
    replans: int = 0


# ---------------------------------------------------------------------------
# DemoController
# ---------------------------------------------------------------------------


class DemoController:
    """Executes a demo-derived plan as a state machine.

    The controller wraps a BenchmarkAgent (typically ClaudeComputerUseAgent)
    and drives it step by step through the plan, verifying each step's
    completion before advancing.

    Args:
        agent: The underlying agent that produces actions.
        adapter: The benchmark adapter for executing actions and getting
            observations.
        demo_text: The full multi-level demo text to parse into a plan.
        max_retries: Maximum retries per step before replanning.
        max_replans: Maximum number of times the plan can be regenerated.
        verify_model: VLM model to use for step/goal verification.
        verify_provider: VLM provider for verification calls.
    """

    def __init__(
        self,
        agent: BenchmarkAgent,
        adapter: BenchmarkAdapter,
        demo_text: str,
        *,
        max_retries: int = 2,
        max_replans: int = 2,
        verify_model: str = "gpt-4.1-mini",
        verify_provider: str = "openai",
    ) -> None:
        self.agent = agent
        self.adapter = adapter
        self.demo_text = demo_text
        self.max_retries = max_retries
        self.max_replans = max_replans
        self.verify_model = verify_model
        self.verify_provider = verify_provider

        # Parse the demo into a structured plan
        self.plan_state = self._parse_demo(demo_text)

        logger.info(
            "DemoController initialized: goal=%r, %d plan steps, %d trajectory steps",
            self.plan_state.goal[:80],
            len(self.plan_state.plan_summary),
            len(self.plan_state.steps),
        )

    def _parse_demo(self, demo_text: str) -> PlanState:
        """Parse demo text into a PlanState.

        Uses ``_parse_multilevel_demo`` from the Claude computer-use agent
        module.  If the demo is not in multi-level format, creates a
        single-step plan from the raw text.

        Args:
            demo_text: The full demo text.

        Returns:
            A PlanState with parsed goal, plan summary, and trajectory steps.
        """
        parsed = _parse_multilevel_demo(demo_text)

        if parsed is None:
            logger.warning(
                "Demo is not in multi-level format; creating single-step plan"
            )
            return PlanState(
                goal=demo_text[:200],
                plan_summary=["Execute the task as described in the demo"],
                steps=[
                    PlanStep(
                        step_num=1,
                        think="Follow the demo instructions",
                        action="Execute the task as described",
                        expect="Task is completed",
                    )
                ],
            )

        steps = [
            PlanStep(
                step_num=t["step_num"],
                think=t["think"],
                action=t["action"],
                expect=t["expect"],
            )
            for t in parsed["trajectory"]
        ]

        return PlanState(
            goal=parsed["goal"],
            plan_summary=parsed["plan_steps"],
            steps=steps,
        )

    def execute(
        self,
        task: BenchmarkTask,
        max_steps: int = 30,
    ) -> BenchmarkResult:
        """Execute the plan as a state machine.

        Main loop that drives the agent through the plan step by step,
        verifying each step's completion before advancing.

        Args:
            task: The benchmark task to execute.
            max_steps: Maximum total agent actions before timeout.

        Returns:
            A BenchmarkResult with the execution outcome.
        """
        start_time = time.perf_counter()
        history: list[tuple[BenchmarkObservation, BenchmarkAction]] = []

        # Reset agent and environment
        logger.info("Resetting agent and environment for task %s", task.task_id)
        self.agent.reset()
        obs = self.adapter.reset(task)

        for step_idx in range(max_steps):
            self.plan_state.total_attempts += 1

            # Check if all steps are done
            if self._all_steps_done():
                logger.info(
                    "All %d plan steps completed, verifying goal",
                    len(self.plan_state.steps),
                )
                if self._verify_goal(obs):
                    logger.info("[SUCCESS] Goal verified after %d agent steps", step_idx)
                    result = self.adapter.evaluate(task)
                    result.steps = history
                    result.num_steps = step_idx
                    result.total_time_seconds = time.perf_counter() - start_time
                    return result
                else:
                    logger.warning(
                        "All steps done but goal not verified; "
                        "attempting replan from current state"
                    )
                    if self.plan_state.replans < self.max_replans:
                        self._replan(obs, self.plan_state.steps[-1])
                    else:
                        logger.warning(
                            "Max replans (%d) exceeded; finishing",
                            self.max_replans,
                        )
                        break

            # Get current plan step
            current = self._current_step()
            if current is None:
                logger.warning("No current step available; breaking")
                break

            if current.status == "pending":
                current.status = "in_progress"
                logger.info(
                    "Starting step %d/%d: %s",
                    current.step_num,
                    len(self.plan_state.steps),
                    current.action[:80],
                )

            # Build focused prompt and override task instruction
            step_prompt = self._build_step_prompt(current, self.plan_state)
            augmented_task = BenchmarkTask(
                task_id=task.task_id,
                instruction=step_prompt,
                domain=task.domain,
                initial_state_ref=task.initial_state_ref,
                time_limit_steps=task.time_limit_steps,
                raw_config=task.raw_config,
                evaluation_spec=task.evaluation_spec,
            )

            # Get action from agent
            try:
                action = self.agent.act(obs, augmented_task, history)
            except Exception as e:
                logger.error("Agent failed to produce action: %s", e)
                return BenchmarkResult(
                    task_id=task.task_id,
                    success=False,
                    score=0.0,
                    steps=history,
                    num_steps=step_idx,
                    error=f"Agent error: {e}",
                    total_time_seconds=time.perf_counter() - start_time,
                )

            current.attempts += 1

            # Override premature "done" if steps remain
            if action.type == "done" and not self._all_steps_done():
                remaining = sum(
                    1
                    for s in self.plan_state.steps
                    if s.status in ("pending", "in_progress")
                )
                logger.warning(
                    "Agent declared done but %d steps remain; overriding",
                    remaining,
                )
                # Skip this step and mark as done anyway to keep moving
                current.status = "done"
                self._advance()
                continue

            # Handle error actions
            if action.type == "error":
                logger.error("Agent returned error: %s", action.raw_action)
                return BenchmarkResult(
                    task_id=task.task_id,
                    success=False,
                    score=0.0,
                    steps=history,
                    num_steps=step_idx,
                    error=str(action.raw_action),
                    error_type=(
                        action.raw_action.get("error_type", "agent")
                        if isinstance(action.raw_action, dict)
                        else "agent"
                    ),
                    total_time_seconds=time.perf_counter() - start_time,
                )

            # Execute action in environment
            try:
                obs, env_done, info = self.adapter.step(action)
            except Exception as e:
                logger.error("Failed to execute action: %s", e)
                return BenchmarkResult(
                    task_id=task.task_id,
                    success=False,
                    score=0.0,
                    steps=history,
                    num_steps=step_idx,
                    error=f"Environment error: {e}",
                    total_time_seconds=time.perf_counter() - start_time,
                )

            history.append((obs, action))

            # Verify step completion
            screenshot_bytes = self._get_screenshot_bytes(obs)
            if screenshot_bytes is not None:
                vr = self._verify_step(screenshot_bytes, current.expect)
                current.verification_result = vr

                if vr.effectively_verified:
                    logger.info(
                        "Step %d %s (confidence=%.2f): %s",
                        current.step_num,
                        vr.status,
                        vr.confidence,
                        vr.explanation[:80],
                    )
                    current.status = "done"
                    self._advance()
                elif current.attempts >= self.max_retries:
                    logger.warning(
                        "Step %d failed after %d attempts (last: %s); %s",
                        current.step_num,
                        current.attempts,
                        vr.status,
                        "replanning" if self.plan_state.replans < self.max_replans else "skipping",
                    )
                    if self.plan_state.replans < self.max_replans:
                        self._replan(obs, current)
                    else:
                        current.status = "failed"
                        self._advance()
                else:
                    logger.info(
                        "Step %d not verified (attempt %d/%d, status=%s); retrying",
                        current.step_num,
                        current.attempts,
                        self.max_retries,
                        vr.status,
                    )
                    self._retry(obs)
            else:
                # No screenshot available -- cannot verify, assume step in progress
                logger.warning(
                    "No screenshot available for verification of step %d",
                    current.step_num,
                )

            # Check environment done signal
            if env_done:
                logger.info("Environment signaled done at step %d", step_idx)
                break

        # Max steps reached or loop exited
        if step_idx >= max_steps - 1:
            logger.warning("Reached maximum steps (%d)", max_steps)

        result = self.adapter.evaluate(task)
        result.steps = history
        result.num_steps = len(history)
        result.total_time_seconds = time.perf_counter() - start_time
        return result

    # ------------------------------------------------------------------
    # State machine operations
    # ------------------------------------------------------------------

    def _current_step(self) -> PlanStep | None:
        """Return the current plan step, or None if out of bounds."""
        idx = self.plan_state.current_step_idx
        if 0 <= idx < len(self.plan_state.steps):
            return self.plan_state.steps[idx]
        return None

    def _advance(self) -> None:
        """Mark current step done (if not already) and advance to next."""
        current = self._current_step()
        if current is not None and current.status not in ("done", "failed", "skipped"):
            current.status = "done"

        self.plan_state.current_step_idx += 1
        next_step = self._current_step()
        if next_step is not None:
            logger.info(
                "Advanced to step %d/%d: %s",
                next_step.step_num,
                len(self.plan_state.steps),
                next_step.action[:60],
            )
        else:
            logger.info("Advanced past last step; plan execution complete")

    def _retry(self, observation: BenchmarkObservation) -> None:
        """Prepare for retrying the current step.

        The current step stays in ``"in_progress"`` status. The attempt
        counter was already incremented in the main loop.

        Args:
            observation: Current observation for context.
        """
        current = self._current_step()
        if current is None:
            return
        logger.info(
            "Retrying step %d (attempt %d/%d)",
            current.step_num,
            current.attempts,
            self.max_retries,
        )

    def _replan(
        self,
        observation: BenchmarkObservation,
        failed_step: PlanStep,
    ) -> None:
        """Regenerate remaining plan steps based on current screen state.

        Uses a VLM to analyze the current screenshot and the remaining
        plan, then generates new steps to replace the unfinished portion
        of the plan.

        Args:
            observation: Current observation with screenshot.
            failed_step: The step that triggered replanning.
        """
        self.plan_state.replans += 1
        logger.info(
            "Replanning (replan %d/%d) after step %d failed",
            self.plan_state.replans,
            self.max_replans,
            failed_step.step_num,
        )

        # Mark the failed step
        failed_step.status = "failed"

        # Gather context for the VLM
        completed = [
            s for s in self.plan_state.steps if s.status == "done"
        ]
        remaining = [
            s
            for s in self.plan_state.steps
            if s.status in ("pending", "in_progress", "failed")
        ]

        completed_text = "\n".join(
            f"  Step {s.step_num}: {s.action} [DONE]" for s in completed
        )
        remaining_text = "\n".join(
            f"  Step {s.step_num}: {s.action} [{s.status.upper()}]"
            for s in remaining
        )

        prompt = (
            f"GOAL: {self.plan_state.goal}\n\n"
            f"COMPLETED STEPS:\n{completed_text or '(none)'}\n\n"
            f"REMAINING STEPS (need revision):\n{remaining_text}\n\n"
            f"FAILED STEP: Step {failed_step.step_num}: {failed_step.action}\n"
            f"FAILURE REASON: {failed_step.verification_result.explanation if failed_step.verification_result else 'Unknown'}\n\n"
            "Look at the current screenshot and generate revised remaining steps "
            "to complete the goal. The screen may not match what the original plan "
            "expected.\n\n"
            "Respond with steps in this format:\n"
            "Step N:\n"
            "  Think: <reasoning>\n"
            "  Action: <what to do>\n"
            "  Expect: <what should happen>\n\n"
            "Generate ONLY the remaining steps needed to complete the goal."
        )

        screenshot_bytes = self._get_screenshot_bytes(observation)
        images = [screenshot_bytes] if screenshot_bytes else None

        try:
            from openadapt_evals.vlm import vlm_call

            response = vlm_call(
                prompt,
                images=images,
                model=self.verify_model,
                provider=self.verify_provider,
                max_tokens=2048,
                temperature=0.2,
            )

            new_steps = self._parse_replan_response(response)
            if new_steps:
                # Replace remaining steps
                done_steps = [
                    s for s in self.plan_state.steps if s.status == "done"
                ]
                self.plan_state.steps = done_steps + new_steps
                self.plan_state.current_step_idx = len(done_steps)
                logger.info(
                    "Replan generated %d new steps (total: %d done + %d new)",
                    len(new_steps),
                    len(done_steps),
                    len(new_steps),
                )
            else:
                logger.warning("Replan produced no parseable steps; skipping failed step")
                self._advance()

        except Exception as e:
            logger.error("Replan VLM call failed: %s", e)
            # Fall back: skip the failed step and continue
            self._advance()

    def _parse_replan_response(self, response: str) -> list[PlanStep]:
        """Parse VLM replan response into PlanStep objects.

        Expects the same format as the demo trajectory::

            Step N:
              Think: ...
              Action: ...
              Expect: ...

        Args:
            response: Raw VLM response text.

        Returns:
            List of PlanStep objects, possibly empty if parsing fails.
        """
        import re

        steps: list[PlanStep] = []
        step_blocks = re.split(r"(?=^Step\s+\d+:)", response, flags=re.MULTILINE)

        for block in step_blocks:
            block = block.strip()
            if not block:
                continue

            step_num_match = re.match(r"Step\s+(\d+):", block)
            if not step_num_match:
                continue

            step_num = int(step_num_match.group(1))

            think_match = re.search(
                r"Think:\s*(.+?)(?=\n\s*Action:|\Z)", block, re.DOTALL
            )
            action_match = re.search(
                r"Action:\s*(.+?)(?=\n\s*Expect:|\Z)", block, re.DOTALL
            )
            expect_match = re.search(
                r"Expect:\s*(.+?)(?=\n\s*$|\nStep\s+\d+:|\Z)", block, re.DOTALL
            )

            steps.append(
                PlanStep(
                    step_num=step_num,
                    think=think_match.group(1).strip() if think_match else "",
                    action=action_match.group(1).strip() if action_match else "",
                    expect=expect_match.group(1).strip() if expect_match else "",
                )
            )

        return steps

    # ------------------------------------------------------------------
    # Prompt building
    # ------------------------------------------------------------------

    def _build_step_prompt(self, step: PlanStep, plan_state: PlanState) -> str:
        """Build a focused prompt for the current step with plan context.

        Provides the agent with a clear picture of where it is in the plan,
        what has been done, what to do next, and what remains.

        Args:
            step: The current PlanStep to execute.
            plan_state: The full plan state for context.

        Returns:
            A formatted prompt string.
        """
        total = len(plan_state.steps)
        current_num = plan_state.current_step_idx + 1

        # Completed steps summary
        done_steps = [s for s in plan_state.steps if s.status == "done"]
        pending_steps = [
            s
            for s in plan_state.steps
            if s.status in ("pending", "in_progress")
            and s.step_num != step.step_num
        ]

        lines = [
            f"GOAL: {plan_state.goal}",
            "",
            f"PLAN PROGRESS: Step {current_num}/{total}",
        ]

        # Completed
        if done_steps:
            completed_summary = ", ".join(
                f"Step {s.step_num}" for s in done_steps
            )
            lines.append(f"Completed: [{completed_summary}]")
        else:
            lines.append("Completed: (none yet)")

        # Current
        lines.append(f"Current: Step {step.step_num} - {step.action[:80]}")

        # Remaining
        remaining_after = [
            s
            for s in plan_state.steps
            if s.status == "pending"
            and s.step_num > step.step_num
        ]
        if remaining_after:
            remaining_summary = ", ".join(
                f"Step {s.step_num}" for s in remaining_after
            )
            lines.append(f"Remaining: [{remaining_summary}]")
        else:
            lines.append("Remaining: (none -- this is the last step)")

        # Current step detail
        lines.extend([
            "",
            "YOUR CURRENT TASK:",
            f"  Think: {step.think}",
            f"  Action: {step.action}",
            f"  Expect: {step.expect}",
        ])

        # Retry context
        if step.attempts > 0:
            lines.extend([
                "",
                f"NOTE: This is attempt {step.attempts + 1} for this step.",
            ])
            if step.verification_result is not None:
                lines.append(
                    f"Previous attempt result: {step.verification_result.status} "
                    f"({step.verification_result.explanation[:100]})"
                )
            lines.append("Try a different approach if your previous action did not work.")

        lines.extend([
            "",
            "Execute this step. Focus on the current step only.",
            "Do NOT skip ahead or declare the task done until instructed.",
        ])

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Verification delegates
    # ------------------------------------------------------------------

    def _verify_step(
        self,
        screenshot_bytes: bytes,
        expect_text: str,
    ) -> VerificationResult:
        """Verify a single step's expected outcome.

        Delegates to :func:`plan_verify.verify_step`.

        Args:
            screenshot_bytes: PNG bytes of the current screen.
            expect_text: The expected outcome description.

        Returns:
            A VerificationResult.
        """
        return verify_step(
            screenshot_bytes,
            expect_text,
            model=self.verify_model,
            provider=self.verify_provider,
        )

    def _verify_goal(self, observation: BenchmarkObservation) -> bool:
        """Verify whether the overall goal has been achieved.

        Delegates to :func:`plan_verify.verify_goal_completion`.

        Args:
            observation: Current observation with screenshot.

        Returns:
            True if the goal is verified complete.
        """
        screenshot_bytes = self._get_screenshot_bytes(observation)
        if screenshot_bytes is None:
            logger.warning("No screenshot for goal verification; assuming not done")
            return False

        result = verify_goal_completion(
            screenshot_bytes,
            self.plan_state.goal,
            model=self.verify_model,
            provider=self.verify_provider,
        )
        return result.effectively_verified

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _all_steps_done(self) -> bool:
        """Check whether all plan steps are in a terminal state."""
        return all(
            s.status in ("done", "failed", "skipped")
            for s in self.plan_state.steps
        )

    @staticmethod
    def _get_screenshot_bytes(obs: BenchmarkObservation) -> bytes | None:
        """Extract screenshot bytes from an observation.

        Args:
            obs: The current observation.

        Returns:
            Raw PNG bytes, or None if no screenshot is available.
        """
        if obs.screenshot is not None:
            return obs.screenshot
        if obs.screenshot_path:
            try:
                from pathlib import Path

                return Path(obs.screenshot_path).read_bytes()
            except (FileNotFoundError, OSError):
                pass
        return None


# ---------------------------------------------------------------------------
# Convenience function
# ---------------------------------------------------------------------------


def run_with_controller(
    agent: BenchmarkAgent,
    adapter: BenchmarkAdapter,
    task: BenchmarkTask,
    demo_text: str,
    *,
    max_steps: int = 30,
    max_retries: int = 2,
    max_replans: int = 2,
    verify_model: str = "gpt-4.1-mini",
    verify_provider: str = "openai",
) -> BenchmarkResult:
    """Run a task using the demo-conditioned controller.

    Convenience function that creates a :class:`DemoController` and calls
    :meth:`DemoController.execute`.

    Args:
        agent: The agent to drive (e.g., ClaudeComputerUseAgent).
        adapter: The benchmark adapter (e.g., WAALiveAdapter).
        task: The benchmark task to execute.
        demo_text: The multi-level demo text.
        max_steps: Maximum total agent actions.
        max_retries: Maximum retries per step.
        max_replans: Maximum replans of the remaining plan.
        verify_model: VLM model for verification.
        verify_provider: VLM provider for verification.

    Returns:
        A BenchmarkResult with the execution outcome.
    """
    controller = DemoController(
        agent=agent,
        adapter=adapter,
        demo_text=demo_text,
        max_retries=max_retries,
        max_replans=max_replans,
        verify_model=verify_model,
        verify_provider=verify_provider,
    )
    return controller.execute(task, max_steps=max_steps)
