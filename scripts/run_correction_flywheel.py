#!/usr/bin/env python3
"""End-to-end correction flywheel demonstration.

Proves the core product thesis: agent fails -> human corrects -> correction
stored -> agent retries with correction -> agent succeeds.

Four phases:
    Phase 1 (ATTEMPT):  Agent tries the task without guidance. Expected: low score.
    Phase 2 (CORRECT):  Correction captured (from demo or human). Stored.
    Phase 3 (RETRY):    Agent retries WITH demo guidance. Expected: higher score.
    Phase 4 (VERIFY):   Compare scores. Improvement = flywheel working.

Usage:
    # Mock mode (no VM, no API keys -- proves the wiring):
    python scripts/run_correction_flywheel.py \
        --task-config example_tasks/notepad-hello.yaml \
        --demo-dir ./demos \
        --mock \
        --output flywheel_results/

    # Live WAA mode:
    python scripts/run_correction_flywheel.py \
        --task-config example_tasks/notepad-hello.yaml \
        --demo-dir ./demos \
        --server-url http://localhost:5001 \
        --output flywheel_results/
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("correction_flywheel")


# ---------------------------------------------------------------------------
# Mock adapter and agent for offline testing
# ---------------------------------------------------------------------------

@dataclass
class _MockObs:
    """Minimal observation for mock mode."""
    screenshot: bytes | None = None
    screenshot_path: str | None = None
    viewport: tuple[int, int] | None = None
    accessibility_tree: dict | None = None


@dataclass
class _MockAction:
    """Minimal action for mock mode."""
    type: str = "done"
    x: float | None = None
    y: float | None = None
    text: str | None = None
    key: str | None = None
    raw_action: dict | None = None


@dataclass
class _MockStepResult:
    observation: _MockObs
    action: _MockAction
    reward: float
    done: bool
    info: dict


class MockFlywheelAdapter:
    """Simulates a WAA-like adapter without any VM or server."""

    def __init__(self):
        self._step = 0
        self._screenshot = self._make_screenshot(b"desktop-initial")

    @staticmethod
    def _make_screenshot(label: bytes) -> bytes:
        """Return synthetic PNG-like bytes (not a real image, just a marker)."""
        # 8-byte PNG header + label so we can distinguish screenshots
        return b"\x89PNG\r\n\x1a\n" + label

    def reset(self, task_id: str) -> _MockObs:
        self._step = 0
        self._screenshot = self._make_screenshot(b"desktop-initial")
        return _MockObs(screenshot=self._screenshot)

    def step(self, action: _MockAction) -> _MockStepResult:
        self._step += 1
        label = f"step-{self._step}".encode()
        self._screenshot = self._make_screenshot(label)
        return _MockStepResult(
            observation=_MockObs(screenshot=self._screenshot),
            action=action,
            reward=0.0,
            done=False,
            info={"step": self._step},
        )

    def observe(self) -> _MockObs:
        return _MockObs(screenshot=self._screenshot)


class MockAgent:
    """Agent that deterministically fails (attempt) or succeeds (retry).

    On attempt (has_demo_guidance=False): takes 3 random actions, then DONE.
    On retry  (has_demo_guidance=True):  follows the "demo", then DONE.
    """

    def __init__(self, has_demo_guidance: bool = False):
        self._has_guidance = has_demo_guidance
        self._step = 0

    def act(self, obs, task_instruction: str) -> _MockAction:
        self._step += 1
        if self._has_guidance:
            # With guidance: do the right thing
            if self._step == 1:
                return _MockAction(type="type", text="notepad", raw_action={})
            if self._step == 2:
                return _MockAction(type="key", key="enter", raw_action={})
            if self._step == 3:
                return _MockAction(type="type", text="Hello World", raw_action={})
            return _MockAction(type="done", raw_action={})
        else:
            # Without guidance: fumble around
            if self._step == 1:
                return _MockAction(type="click", x=0.5, y=0.5, raw_action={})
            if self._step == 2:
                return _MockAction(type="click", x=0.1, y=0.9, raw_action={})
            return _MockAction(type="done", raw_action={})


def _mock_evaluate(adapter: MockFlywheelAdapter, has_guidance: bool) -> float:
    """Simulate milestone scoring."""
    if has_guidance:
        return 1.0  # Guided agent succeeds
    return 0.0  # Unguided agent fails


# ---------------------------------------------------------------------------
# Live mode helpers
# ---------------------------------------------------------------------------

def _run_live_episode(
    server_url: str,
    task_config,
    demo_library=None,
    max_steps: int = 15,
    planner_model: str = "gpt-4.1-mini",
    planner_provider: str = "openai",
    grounder_model: str = "gpt-4.1-mini",
    grounder_provider: str = "openai",
    screenshot_dir: Path | None = None,
) -> tuple[float, list[bytes]]:
    """Run one episode against a live WAA server. Returns (score, screenshots)."""
    from openadapt_evals.adapters.base import BenchmarkTask
    from openadapt_evals.adapters.rl_env import RLEnvironment, ResetConfig
    from openadapt_evals.adapters.waa.live import WAALiveAdapter, WAALiveConfig
    from openadapt_evals.agents.planner_grounder_agent import PlannerGrounderAgent

    adapter = WAALiveAdapter(WAALiveConfig(server_url=server_url))
    env = RLEnvironment(adapter, task_config=task_config)

    base_agent = PlannerGrounderAgent(
        planner=planner_model,
        grounder=grounder_model,
        planner_provider=planner_provider,
        grounder_provider=grounder_provider,
    )

    # Wrap with demo guidance if library provided
    agent: object
    if demo_library is not None:
        from openadapt_evals.agents.demo_guided_agent import DemoGuidedAgent
        agent = DemoGuidedAgent(base_agent=base_agent, demo_library=demo_library)
    else:
        agent = base_agent

    task = BenchmarkTask(
        task_id=task_config.id,
        instruction=task_config.name,
        domain="desktop",
    )

    obs = env.reset(config=ResetConfig(task_id=task_config.id))
    screenshots: list[bytes] = []
    if obs.screenshot:
        screenshots.append(obs.screenshot)
        if screenshot_dir:
            (screenshot_dir / "step_00.png").write_bytes(obs.screenshot)

    for step_i in range(max_steps):
        action = agent.act(obs, task)

        if action.type == "done":
            logger.info("Agent signaled DONE at step %d", step_i + 1)
            break

        # Execute
        if action.x is not None and action.y is not None:
            x, y = float(action.x), float(action.y)
            if 0 <= x <= 1 and 0 <= y <= 1:
                step_result = env.pixel_action(
                    x_frac=x, y_frac=y,
                    action_type=action.type, text=action.text, key=action.key,
                )
            else:
                step_result = env.pixel_action(
                    x=int(x), y=int(y),
                    action_type=action.type, text=action.text, key=action.key,
                )
        else:
            step_result = env.step(action)

        obs = step_result.observation
        if obs.screenshot:
            screenshots.append(obs.screenshot)
            if screenshot_dir:
                (screenshot_dir / f"step_{step_i + 1:02d}.png").write_bytes(
                    obs.screenshot
                )
        if step_result.done:
            break

    # Score
    if task_config.milestones:
        score = env.evaluate_dense()
    else:
        score = env.evaluate()

    return score, screenshots


# ---------------------------------------------------------------------------
# Core flywheel phases
# ---------------------------------------------------------------------------

def phase1_attempt(
    mock: bool,
    server_url: str | None,
    task_config,
    output_dir: Path,
    **kwargs,
) -> tuple[float, list[bytes]]:
    """Phase 1: Agent attempts the task WITHOUT demo guidance."""
    logger.info("=" * 60)
    logger.info("PHASE 1: ATTEMPT (no demo guidance)")
    logger.info("=" * 60)

    ss_dir = output_dir / "phase1_screenshots"
    ss_dir.mkdir(parents=True, exist_ok=True)

    if mock:
        adapter = MockFlywheelAdapter()
        agent = MockAgent(has_demo_guidance=False)
        obs = adapter.reset(task_config.id)
        screenshots = [obs.screenshot] if obs.screenshot else []

        for step_i in range(10):
            action = agent.act(obs, task_config.name)
            if action.type == "done":
                break
            result = adapter.step(action)
            obs = result.observation
            if obs.screenshot:
                screenshots.append(obs.screenshot)

        score = _mock_evaluate(adapter, has_guidance=False)
    else:
        score, screenshots = _run_live_episode(
            server_url=server_url,
            task_config=task_config,
            demo_library=None,
            screenshot_dir=ss_dir,
            **kwargs,
        )

    logger.info("Phase 1 result: score=%.2f, screenshots=%d", score, len(screenshots))
    return score, screenshots


def phase2_correct(
    task_config,
    demo_dir: str,
    attempt_screenshots: list[bytes],
    output_dir: Path,
) -> str:
    """Phase 2: Capture correction (simulate from demo or create synthetic).

    For MVP: the demo IS the correction -- "this is what you should have done."
    Stores the correction in CorrectionStore for audit trail.

    Returns the demo_dir path (for Phase 3 DemoLibrary).
    """
    logger.info("=" * 60)
    logger.info("PHASE 2: CORRECT (capture/store correction)")
    logger.info("=" * 60)

    from openadapt_evals.correction_store import CorrectionEntry, CorrectionStore

    correction_dir = output_dir / "corrections"
    store = CorrectionStore(str(correction_dir))

    # Check if demo exists for this task
    demo_library_dir = Path(demo_dir)
    task_demo_dir = demo_library_dir / task_config.id

    if task_demo_dir.exists():
        logger.info("Found existing demo for task %s at %s", task_config.id, task_demo_dir)
        # Store a correction entry referencing the demo
        entry = CorrectionEntry(
            task_id=task_config.id,
            step_description=task_config.name,
            failure_screenshot_path="",
            failure_explanation="Agent failed without demo guidance",
            correction_step={
                "think": "Use the demo to guide the agent",
                "action": "Follow demonstration steps",
                "expect": "Task completed successfully",
            },
        )
        entry_id = store.save(entry)
        logger.info("Stored correction %s from existing demo", entry_id)
    else:
        # Create a synthetic demo for mock mode
        logger.info("No existing demo found. Creating synthetic demo for %s", task_config.id)
        task_demo_dir.mkdir(parents=True, exist_ok=True)

        from openadapt_evals.adapters.base import BenchmarkAction

        # Synthetic demo: the "correct" sequence for notepad-hello
        demo_steps = [
            {
                "action": asdict(BenchmarkAction(type="type", text="notepad")),
                "description": "Type 'notepad' in the search bar",
            },
            {
                "action": asdict(BenchmarkAction(type="key", key="enter")),
                "description": "Press Enter to open Notepad",
            },
            {
                "action": asdict(BenchmarkAction(type="type", text="Hello World")),
                "description": "Type 'Hello World' in Notepad",
            },
        ]

        # Write demo.json
        demo_id = "synthetic_correction"
        demo_subdir = task_demo_dir / demo_id
        demo_subdir.mkdir(parents=True, exist_ok=True)

        # Create minimal screenshot files (required by DemoLibrary)
        for i in range(len(demo_steps)):
            screenshot_path = demo_subdir / f"step_{i:03d}.png"
            # Write a minimal valid-ish marker
            screenshot_path.write_bytes(
                b"\x89PNG\r\n\x1a\n" + f"demo-step-{i}".encode()
            )

        demo_metadata = {
            "demo_id": demo_id,
            "task_id": task_config.id,
            "description": f"Correction demo: {task_config.name}",
            "created": datetime.now(timezone.utc).isoformat(),
            "steps": [
                {
                    "screenshot": f"step_{i:03d}.png",
                    "action": step["action"],
                    "description": step["description"],
                }
                for i, step in enumerate(demo_steps)
            ],
        }
        with open(demo_subdir / "demo.json", "w") as f:
            json.dump(demo_metadata, f, indent=2)

        logger.info("Created synthetic demo with %d steps at %s",
                     len(demo_steps), demo_subdir)

        # Also store in CorrectionStore
        entry = CorrectionEntry(
            task_id=task_config.id,
            step_description=task_config.name,
            failure_screenshot_path="",
            failure_explanation="Agent failed without demo guidance",
            correction_step={
                "think": "Created synthetic correction demo",
                "action": "Follow the 3-step demo: search notepad, open it, type text",
                "expect": "Notepad open with 'Hello World' typed",
            },
        )
        store.save(entry)

    # Verify corrections are stored
    all_corrections = store.load_all()
    logger.info("CorrectionStore contains %d entries", len(all_corrections))

    return demo_dir


def phase3_retry(
    mock: bool,
    server_url: str | None,
    task_config,
    demo_dir: str,
    output_dir: Path,
    **kwargs,
) -> tuple[float, list[bytes]]:
    """Phase 3: Agent retries WITH demo guidance."""
    logger.info("=" * 60)
    logger.info("PHASE 3: RETRY (with demo guidance)")
    logger.info("=" * 60)

    ss_dir = output_dir / "phase3_screenshots"
    ss_dir.mkdir(parents=True, exist_ok=True)

    if mock:
        adapter = MockFlywheelAdapter()
        agent = MockAgent(has_demo_guidance=True)
        obs = adapter.reset(task_config.id)
        screenshots = [obs.screenshot] if obs.screenshot else []

        for step_i in range(10):
            action = agent.act(obs, task_config.name)
            if action.type == "done":
                break
            result = adapter.step(action)
            obs = result.observation
            if obs.screenshot:
                screenshots.append(obs.screenshot)

        score = _mock_evaluate(adapter, has_guidance=True)
    else:
        from openadapt_evals.demo_library import DemoLibrary
        demo_library = DemoLibrary(demo_dir)
        score, screenshots = _run_live_episode(
            server_url=server_url,
            task_config=task_config,
            demo_library=demo_library,
            screenshot_dir=ss_dir,
            **kwargs,
        )

    logger.info("Phase 3 result: score=%.2f, screenshots=%d", score, len(screenshots))
    return score, screenshots


def phase4_verify(
    attempt_score: float,
    retry_score: float,
    output_dir: Path,
    task_name: str,
) -> bool:
    """Phase 4: Compare scores and generate report."""
    logger.info("=" * 60)
    logger.info("PHASE 4: VERIFY (compare results)")
    logger.info("=" * 60)

    improvement = retry_score - attempt_score
    success = retry_score > attempt_score

    # Generate report
    report = {
        "task": task_name,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "attempt_score": attempt_score,
        "retry_score": retry_score,
        "improvement": improvement,
        "flywheel_working": success,
    }

    report_path = output_dir / "flywheel_report.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)

    # Print summary
    print("\n" + "=" * 60)
    print("CORRECTION FLYWHEEL RESULTS")
    print("=" * 60)
    print(f"Task:            {task_name}")
    print(f"Attempt score:   {attempt_score:.2f}  (no guidance)")
    print(f"Retry score:     {retry_score:.2f}  (with correction/demo)")
    print(f"Improvement:     {improvement:+.2f}")
    print(f"Flywheel works:  {'YES' if success else 'NO'}")
    print(f"Report:          {report_path}")
    print("=" * 60)

    if success:
        print("\nThe correction flywheel is working.")
        print("Agent fails -> human corrects -> agent retries -> agent succeeds.")
    else:
        print("\nFlywheel did NOT show improvement. Debug needed.")

    return success


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="End-to-end correction flywheel demonstration"
    )
    parser.add_argument("--task-config", required=True,
                        help="Path to task YAML config")
    parser.add_argument("--demo-dir", default="./demos",
                        help="Directory containing (or to create) demos")
    parser.add_argument("--output", default="flywheel_results",
                        help="Output directory for results")
    parser.add_argument("--mock", action="store_true",
                        help="Use mock adapter (no VM, no API keys)")
    parser.add_argument("--server-url", default="http://localhost:5001",
                        help="WAA server URL (ignored in mock mode)")
    parser.add_argument("--max-steps", type=int, default=15)
    parser.add_argument("--planner-model", default="gpt-4.1-mini")
    parser.add_argument("--planner-provider", default="openai")
    parser.add_argument("--grounder-model", default="gpt-4.1-mini")
    parser.add_argument("--grounder-provider", default="openai")
    args = parser.parse_args()

    # Load task config
    from openadapt_evals.task_config import TaskConfig
    task_config = TaskConfig.from_yaml(args.task_config)
    logger.info("Task: %s (id=%s, %d milestones)",
                task_config.name, task_config.id, len(task_config.milestones))

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    live_kwargs = dict(
        max_steps=args.max_steps,
        planner_model=args.planner_model,
        planner_provider=args.planner_provider,
        grounder_model=args.grounder_model,
        grounder_provider=args.grounder_provider,
    )

    start = time.monotonic()

    # Phase 1: Attempt without guidance
    attempt_score, attempt_screenshots = phase1_attempt(
        mock=args.mock,
        server_url=args.server_url,
        task_config=task_config,
        output_dir=output_dir,
        **live_kwargs,
    )

    # Phase 2: Capture/store correction
    demo_dir = phase2_correct(
        task_config=task_config,
        demo_dir=args.demo_dir,
        attempt_screenshots=attempt_screenshots,
        output_dir=output_dir,
    )

    # Phase 3: Retry with guidance
    retry_score, retry_screenshots = phase3_retry(
        mock=args.mock,
        server_url=args.server_url,
        task_config=task_config,
        demo_dir=demo_dir,
        output_dir=output_dir,
        **live_kwargs,
    )

    # Phase 4: Verify improvement
    success = phase4_verify(
        attempt_score=attempt_score,
        retry_score=retry_score,
        output_dir=output_dir,
        task_name=task_config.name,
    )

    elapsed = time.monotonic() - start
    logger.info("Flywheel completed in %.1fs", elapsed)

    return 0 if success else 1


if __name__ == "__main__":
    sys.exit(main())
