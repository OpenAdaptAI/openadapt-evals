"""Directory-based demonstration library for demo-guided execution.

Stores demonstrations as sequences of (screenshot, action, metadata) on disk.
Retrieval uses sequential step alignment with visual similarity fallback.
No embeddings or vector DBs -- just files on disk.

Usage:
    from openadapt_evals.demo_library import DemoLibrary

    library = DemoLibrary("./demos")
    library.add_demo("notepad_1", screenshots=[...], actions=[...])

    guidance = library.align_step("notepad_1", current_screenshot, step_index=2)
    print(guidance.instruction)
"""

from __future__ import annotations

import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from openadapt_evals.adapters.base import BenchmarkAction

logger = logging.getLogger(__name__)


@dataclass
class DemoStep:
    """A single step in a demonstration."""

    step_index: int
    screenshot_path: str  # relative to demo dir
    action_type: str
    action_description: str  # human-readable
    target_description: str  # what element was interacted with
    action_value: str  # text typed, key pressed, etc.
    metadata: dict[str, Any] = field(default_factory=dict)

    # Coordinates for click/drag actions (normalized 0-1)
    x: float | None = None
    y: float | None = None


@dataclass
class Demo:
    """A complete demonstration of a task."""

    task_id: str
    demo_id: str
    description: str  # what the demo accomplishes
    steps: list[DemoStep]
    created_at: str = ""  # ISO format
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.now(timezone.utc).isoformat()


@dataclass
class DemoGuidance:
    """Guidance from a demonstration for the current step.

    Returned by ``DemoLibrary.align_step()`` to tell the agent what the
    demo says to do at this point in the task.
    """

    available: bool  # whether demo guidance was found
    step_index: int  # which demo step this corresponds to
    instruction: str  # human-readable guidance text
    action_type: str  # expected action type
    action_value: str  # expected action value (text, key, etc.)
    target_description: str  # what to interact with
    screenshot_path: str | None  # path to demo screenshot for this step
    next_screenshot_path: str | None  # path to demo screenshot for next step
    confidence: float  # alignment confidence 0-1
    total_demo_steps: int  # total steps in the demo
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_prompt_text(self) -> str:
        """Format guidance as text suitable for injection into an agent prompt."""
        if not self.available:
            return ""

        lines = [
            f"DEMONSTRATION GUIDANCE (step {self.step_index + 1}/{self.total_demo_steps}):",
            f"  Expected action: {self.action_type}",
        ]
        if self.target_description:
            lines.append(f"  Target: {self.target_description}")
        if self.action_value:
            lines.append(f"  Value: {self.action_value}")
        lines.append(f"  Instruction: {self.instruction}")
        lines.append(
            "  NOTE: Adapt if the current UI state differs from the demo. "
            "This is guidance, not a rigid script."
        )
        return "\n".join(lines)


def _empty_guidance(step_index: int = 0) -> DemoGuidance:
    """Return empty guidance when no demo is available."""
    return DemoGuidance(
        available=False,
        step_index=step_index,
        instruction="",
        action_type="",
        action_value="",
        target_description="",
        screenshot_path=None,
        next_screenshot_path=None,
        confidence=0.0,
        total_demo_steps=0,
    )


class DemoLibrary:
    """Directory-based demonstration library.

    Directory structure::

        library_dir/
          {task_id}/
            {demo_id}/
              demo.json          # Demo metadata + steps
              step_000.png       # Screenshot for step 0
              step_001.png       # Screenshot for step 1
              ...

    Args:
        library_dir: Root directory for storing demos.
    """

    def __init__(self, library_dir: str = "demo_library"):
        self.library_dir = Path(library_dir)
        self.library_dir.mkdir(parents=True, exist_ok=True)

    def add_demo(
        self,
        task_id: str,
        screenshots: list[Path | bytes],
        actions: list[BenchmarkAction],
        description: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Record a new demonstration for a task.

        Args:
            task_id: Task identifier.
            screenshots: List of screenshot paths or raw PNG bytes,
                one per action.
            actions: List of ``BenchmarkAction`` objects from the demo.
            description: Human-readable description of the demo.
            metadata: Optional extra metadata.

        Returns:
            The generated demo_id.
        """
        if len(screenshots) != len(actions):
            raise ValueError(
                f"screenshots ({len(screenshots)}) and actions "
                f"({len(actions)}) must have the same length"
            )

        demo_id = uuid.uuid4().hex[:12]
        demo_dir = self.library_dir / task_id / demo_id
        demo_dir.mkdir(parents=True, exist_ok=True)

        steps: list[DemoStep] = []
        for i, (screenshot, action) in enumerate(zip(screenshots, actions)):
            # Save screenshot
            screenshot_filename = f"step_{i:03d}.png"
            screenshot_path = demo_dir / screenshot_filename

            if isinstance(screenshot, (str, Path)):
                # Copy file
                import shutil
                shutil.copy2(str(screenshot), str(screenshot_path))
            elif isinstance(screenshot, bytes):
                screenshot_path.write_bytes(screenshot)
            else:
                raise TypeError(
                    f"screenshot must be Path or bytes, got {type(screenshot)}"
                )

            # Build action description
            from openadapt_evals.agents.base import action_to_string
            action_desc = action_to_string(action)

            step = DemoStep(
                step_index=i,
                screenshot_path=screenshot_filename,
                action_type=action.type,
                action_description=action_desc,
                target_description=action.target_name or "",
                action_value=action.text or action.key or action.answer or "",
                x=action.x,
                y=action.y,
                metadata={},
            )
            steps.append(step)

        demo = Demo(
            task_id=task_id,
            demo_id=demo_id,
            description=description or f"Demo for {task_id}",
            steps=steps,
            metadata=metadata or {},
        )

        # Save demo.json
        demo_json_path = demo_dir / "demo.json"
        with open(demo_json_path, "w") as f:
            json.dump(asdict(demo), f, indent=2)

        logger.info(
            "Saved demo %s for task %s (%d steps)",
            demo_id, task_id, len(steps),
        )
        return demo_id

    def get_demo(self, task_id: str) -> Demo | None:
        """Get the most recent demo for a task.

        If multiple demos exist for a task, returns the most recently
        created one (by filesystem modification time).

        Args:
            task_id: Task identifier.

        Returns:
            Demo object or None if no demo exists.
        """
        task_dir = self.library_dir / task_id
        if not task_dir.is_dir():
            return None

        # Find all demo directories, sorted by modification time (newest first)
        demo_dirs = sorted(
            [d for d in task_dir.iterdir() if d.is_dir()],
            key=lambda d: d.stat().st_mtime,
            reverse=True,
        )

        for demo_dir in demo_dirs:
            demo_json = demo_dir / "demo.json"
            if not demo_json.exists():
                continue
            try:
                with open(demo_json) as f:
                    data = json.load(f)
                steps = [DemoStep(**s) for s in data.pop("steps", [])]
                return Demo(steps=steps, **data)
            except (json.JSONDecodeError, TypeError, KeyError) as exc:
                logger.warning(
                    "Skipping invalid demo %s: %s", demo_dir.name, exc,
                )

        return None

    def list_demos(self, task_id: str) -> list[str]:
        """List all demo IDs for a task.

        Args:
            task_id: Task identifier.

        Returns:
            List of demo_id strings.
        """
        task_dir = self.library_dir / task_id
        if not task_dir.is_dir():
            return []
        return [
            d.name
            for d in task_dir.iterdir()
            if d.is_dir() and (d / "demo.json").exists()
        ]

    def list_tasks(self) -> list[str]:
        """List all task IDs that have at least one demo.

        Returns:
            List of task_id strings.
        """
        if not self.library_dir.is_dir():
            return []
        return [
            d.name
            for d in self.library_dir.iterdir()
            if d.is_dir() and any(
                (sub / "demo.json").exists()
                for sub in d.iterdir()
                if sub.is_dir()
            )
        ]

    def align_step(
        self,
        task_id: str,
        current_screenshot: bytes | None,
        step_index: int,
    ) -> DemoGuidance:
        """Get demo guidance for a specific step.

        Uses simple sequential alignment (step_index) with visual
        similarity fallback when the step_index exceeds the demo length.

        Args:
            task_id: Task identifier.
            current_screenshot: Current screenshot bytes (for visual
                similarity fallback, currently unused -- reserved for
                future perceptual hash matching).
            step_index: Current step index in the agent's execution.

        Returns:
            DemoGuidance with the demo's recommendation for this step.
        """
        demo = self.get_demo(task_id)
        if demo is None:
            return _empty_guidance(step_index)

        total_steps = len(demo.steps)
        if total_steps == 0:
            return _empty_guidance(step_index)

        # Sequential alignment: use step_index directly
        if step_index < total_steps:
            step = demo.steps[step_index]
            confidence = 1.0
        else:
            # Past the end of the demo -- return the last step as context
            # with low confidence
            step = demo.steps[-1]
            confidence = 0.2
            logger.info(
                "Step %d exceeds demo length %d for task %s, "
                "returning last step with low confidence",
                step_index, total_steps, task_id,
            )

        # Resolve screenshot paths
        demo_dir = self._demo_dir(task_id, demo.demo_id)
        screenshot_path = str(demo_dir / step.screenshot_path) if step.screenshot_path else None

        next_screenshot_path = None
        if step.step_index + 1 < total_steps:
            next_step = demo.steps[step.step_index + 1]
            next_screenshot_path = str(demo_dir / next_step.screenshot_path) if next_step.screenshot_path else None

        return DemoGuidance(
            available=True,
            step_index=step.step_index,
            instruction=step.action_description,
            action_type=step.action_type,
            action_value=step.action_value,
            target_description=step.target_description,
            screenshot_path=screenshot_path,
            next_screenshot_path=next_screenshot_path,
            confidence=confidence,
            total_demo_steps=total_steps,
        )

    def _demo_dir(self, task_id: str, demo_id: str) -> Path:
        """Get the directory for a specific demo."""
        return self.library_dir / task_id / demo_id
