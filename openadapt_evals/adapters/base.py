"""Base classes for benchmark adapters.

This module provides the core abstractions for integrating GUI agent benchmarks
into the evaluation framework. It supports both interactive environments (WAA, OSWorld)
and static trajectory datasets (Mind2Web).

Example:
    from openadapt_evals.adapters import BenchmarkAdapter, WAAAdapter

    adapter = WAAAdapter(waa_repo_path="/path/to/WAA")
    tasks = adapter.list_tasks()
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Iterator

# Canonical Benchmark* task/observation/action types now live in the shared
# schema package (openadapt-types) so openadapt-ml and openadapt-evals do not
# import each other. Re-exported here for backward compatibility with existing
# imports, e.g. ``from openadapt_evals.adapters.base import BenchmarkAction``.
from openadapt_types import (
    BenchmarkAction,
    BenchmarkObservation,
    BenchmarkTask,
)

if TYPE_CHECKING:
    pass


class EvaluationUnavailableError(RuntimeError):
    """A task could not be scored, as distinct from having scored badly.

    Adapters signal this condition on a :class:`BenchmarkResult` via
    ``error_type in {"infrastructure", "evaluation"}``. Any API that flattens a
    result down to a bare float must raise this instead of returning ``0.0``:
    an unreachable VM reported as a legitimate 0% is the single worst defect an
    evaluation harness can have, because the number looks measured.
    """

    def __init__(self, message: str, error_type: str = "infrastructure") -> None:
        super().__init__(message)
        self.error_type = error_type


@dataclass
class BenchmarkResult:
    """Result of a single task evaluation.

    Attributes:
        task_id: ID of the evaluated task.
        success: Whether the task was completed successfully.
        score: Score between 0.0 and 1.0.
        steps: List of (observation, action) pairs from the trajectory.
        num_steps: Number of steps taken.
        error: Error message if task failed due to error.
        reason: Explanation of success/failure.
        total_time_seconds: Total time taken for the task.
    """

    task_id: str
    success: bool
    score: float  # 0.0 to 1.0

    # Trajectory
    steps: list[tuple[BenchmarkObservation, BenchmarkAction]] = field(
        default_factory=list
    )
    num_steps: int = 0

    # Diagnostics
    error: str | None = None
    reason: str | None = None  # Why success/fail
    error_type: str | None = None  # "infrastructure", "agent", "evaluation", or None

    # Timing
    total_time_seconds: float = 0.0


@dataclass
class UIElement:
    """Normalized UI element for cross-platform use.

    Provides a common representation for UI elements across platforms
    (Windows UIA, macOS AXTree, web DOM).

    Attributes:
        node_id: Unique identifier for the element.
        role: Element role (button, textfield, link, etc.).
        name: Accessible name/label.
        bbox: Bounding box (normalized [0,1] or pixels).
        text: Text content.
        value: Current value (for inputs).
        children: Child elements.
        attributes: Additional platform-specific attributes.
    """

    node_id: str
    role: str  # "button", "textfield", "link", etc.
    name: str | None = None  # Accessible name/label
    bbox: tuple[float, float, float, float] | None = None  # (x1, y1, x2, y2)
    text: str | None = None  # Text content
    value: str | None = None  # Current value (for inputs)
    children: list[UIElement] | None = None
    attributes: dict[str, Any] | None = None  # Platform-specific


class BenchmarkAdapter(ABC):
    """Abstract interface for benchmark integration.

    Subclasses implement this interface to integrate specific benchmarks
    (WAA, OSWorld, WebArena, etc.) with the evaluation framework.

    Two types of adapters:
    - Interactive: Run environment, step through tasks (WAA, OSWorld)
    - Static: Load trajectories for offline training/eval (Mind2Web)
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Benchmark name (e.g., 'waa', 'osworld', 'webarena')."""
        pass

    @property
    @abstractmethod
    def benchmark_type(self) -> str:
        """Benchmark type: 'interactive' or 'static'."""
        pass

    @property
    def supports_parallel(self) -> bool:
        """Whether the adapter supports parallel task execution."""
        return False

    @abstractmethod
    def list_tasks(self, domain: str | None = None) -> list[BenchmarkTask]:
        """List available tasks, optionally filtered by domain.

        Args:
            domain: Optional domain filter (e.g., "browser", "office").

        Returns:
            List of BenchmarkTask objects.
        """
        pass

    @abstractmethod
    def load_task(self, task_id: str) -> BenchmarkTask:
        """Load a specific task by ID.

        Args:
            task_id: Task identifier.

        Returns:
            BenchmarkTask object.

        Raises:
            KeyError: If task_id not found.
        """
        pass

    @abstractmethod
    def reset(self, task: BenchmarkTask) -> BenchmarkObservation:
        """Reset environment to task's initial state.

        Args:
            task: Task to initialize.

        Returns:
            Initial observation.
        """
        pass

    @abstractmethod
    def step(
        self, action: BenchmarkAction
    ) -> tuple[BenchmarkObservation, bool, dict[str, Any]]:
        """Execute action and return new observation.

        Args:
            action: Action to execute.

        Returns:
            Tuple of (observation, done, info).
        """
        pass

    @abstractmethod
    def evaluate(self, task: BenchmarkTask) -> BenchmarkResult:
        """Run benchmark's native evaluation on current state.

        Args:
            task: Task to evaluate.

        Returns:
            BenchmarkResult with success/score.
        """
        pass

    def close(self) -> None:
        """Clean up resources (VMs, browser, etc.)."""
        pass

    def __enter__(self) -> BenchmarkAdapter:
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit."""
        self.close()


class StaticDatasetAdapter(BenchmarkAdapter):
    """Base for static trajectory datasets (Mind2Web, demos).

    Static adapters load pre-recorded trajectories for offline training
    or evaluation, rather than running an interactive environment.
    """

    @property
    def benchmark_type(self) -> str:
        """Static datasets are not interactive."""
        return "static"

    @abstractmethod
    def load_trajectories(
        self, split: str = "test"
    ) -> Iterator[tuple[BenchmarkTask, list[tuple[BenchmarkObservation, BenchmarkAction]]]]:
        """Iterate over expert trajectories.

        Args:
            split: Dataset split ("train", "val", "test").

        Yields:
            Tuples of (task, trajectory) where trajectory is a list of
            (observation, action) pairs.
        """
        pass

    def reset(self, task: BenchmarkTask) -> BenchmarkObservation:
        """Not supported for static datasets."""
        raise NotImplementedError(
            "Static datasets don't support interactive reset. "
            "Use load_trajectories() instead."
        )

    def step(
        self, action: BenchmarkAction
    ) -> tuple[BenchmarkObservation, bool, dict[str, Any]]:
        """Not supported for static datasets."""
        raise NotImplementedError(
            "Static datasets don't support interactive stepping. "
            "Use load_trajectories() instead."
        )

    def evaluate(self, task: BenchmarkTask) -> BenchmarkResult:
        """Not supported for static datasets."""
        raise NotImplementedError(
            "Static datasets don't support execution-based evaluation. "
            "Use offline metrics instead."
        )
