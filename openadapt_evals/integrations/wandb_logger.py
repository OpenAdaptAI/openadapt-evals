"""Weights & Biases integration for OpenAdapt Evals.

This module provides logging of benchmark evaluation results to wandb,
enabling experiment tracking, visualization, and model comparison.

Example:
    from openadapt_evals import WAAMockAdapter, SmartMockAgent, evaluate_agent_on_benchmark
    from openadapt_evals.integrations import WandbLogger

    adapter = WAAMockAdapter()
    agent = SmartMockAgent()

    # Initialize wandb logger
    logger = WandbLogger(
        project="openadapt-evals",
        config={"model_id": "my-model-v1", "benchmark": "waa"},
    )

    # Run evaluation
    results = evaluate_agent_on_benchmark(agent, adapter)

    # Log results to wandb
    logger.log_results(results)
    logger.finish()

Environment Variables:
    WANDB_API_KEY: Your wandb API key (required)
    WANDB_PROJECT: Default project name (optional)
    WANDB_ENTITY: Team/organization name (optional)
    WANDB_MODE: online, offline, or disabled (optional)
"""

from __future__ import annotations

import json
import logging
import os
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from openadapt_evals.adapters import BenchmarkResult, BenchmarkTask

logger = logging.getLogger(__name__)

# Try to import wandb, fail gracefully if not installed
try:
    import wandb
    from wandb import Table

    WANDB_AVAILABLE = True
except ImportError:
    WANDB_AVAILABLE = False
    wandb = None
    Table = None


class WandbLogger:
    """Logger for benchmark evaluation results to Weights & Biases.

    This class handles:
    - Initializing wandb runs with configuration
    - Logging per-task and aggregate metrics
    - Creating tables for detailed analysis
    - Uploading artifacts (screenshots, traces)
    - Generating summary reports

    Args:
        project: Wandb project name.
        entity: Wandb entity (team/org) name.
        config: Run configuration dictionary.
        tags: List of tags for the run.
        name: Run name (auto-generated if None).
        notes: Run notes/description.
        mode: Wandb mode ("online", "offline", "disabled").
        resume: Whether to resume an existing run.

    Raises:
        ImportError: If wandb is not installed.
        ValueError: If WANDB_API_KEY is not set.
    """

    def __init__(
        self,
        project: str = "openadapt-evals",
        entity: str | None = None,
        config: dict[str, Any] | None = None,
        tags: list[str] | None = None,
        name: str | None = None,
        notes: str | None = None,
        mode: str | None = None,
        resume: bool = False,
    ):
        if not WANDB_AVAILABLE:
            raise ImportError(
                "wandb is not installed. Install with: pip install wandb "
                "or: pip install openadapt-evals[wandb]"
            )

        # Check for API key
        api_key = os.environ.get("WANDB_API_KEY")
        if not api_key and mode != "disabled":
            logger.warning(
                "WANDB_API_KEY not set. Set it in your environment or .env file, "
                "or use mode='disabled' for testing."
            )

        self.project = project
        self.entity = entity or os.environ.get("WANDB_ENTITY")
        self.config = config or {}
        self.tags = tags or []
        self.name = name
        self.notes = notes
        self.mode = mode or os.environ.get("WANDB_MODE", "online")
        self.resume = resume

        self._run: wandb.Run | None = None
        self._tasks_logged = 0
        self._results_buffer: list[BenchmarkResult] = []

    def init(self) -> wandb.Run:
        """Initialize the wandb run.

        Returns:
            The wandb Run object.
        """
        if self._run is not None:
            return self._run

        # Generate run name if not provided
        if self.name is None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            model_id = self.config.get("model_id", "unknown")
            benchmark = self.config.get("benchmark", "eval")
            self.name = f"{benchmark}_{model_id}_{timestamp}"

        self._run = wandb.init(
            project=self.project,
            entity=self.entity,
            config=self.config,
            tags=self.tags,
            name=self.name,
            notes=self.notes,
            mode=self.mode,
            resume="allow" if self.resume else None,
        )

        logger.info(f"Initialized wandb run: {self._run.name} ({self._run.url})")
        return self._run

    def log_task_result(self, result: BenchmarkResult) -> None:
        """Log a single task result (for real-time tracking).

        Args:
            result: The benchmark result for one task.
        """
        if self._run is None:
            self.init()

        self._results_buffer.append(result)
        self._tasks_logged += 1

        # Log incremental metrics
        success_count = sum(1 for r in self._results_buffer if r.success)
        current_rate = success_count / len(self._results_buffer)

        self._run.log({
            "task/current_success_rate": current_rate,
            "task/tasks_completed": self._tasks_logged,
            "task/last_task_success": result.success,
            "task/last_task_steps": result.num_steps,
        })

    def log_results(
        self,
        results: list[BenchmarkResult],
        tasks: list[BenchmarkTask] | None = None,
    ) -> None:
        """Log all evaluation results to wandb.

        Args:
            results: List of benchmark results.
            tasks: Optional list of tasks (for domain info).
        """
        if self._run is None:
            self.init()

        if not results:
            logger.warning("No results to log")
            return

        # Build task_id -> domain mapping
        task_domains = {}
        if tasks:
            task_domains = {t.task_id: t.domain for t in tasks}
        else:
            # Try to extract domain from task_id (e.g., "notepad_1" -> "notepad")
            for r in results:
                parts = r.task_id.rsplit("_", 1)
                if len(parts) == 2:
                    task_domains[r.task_id] = parts[0]

        # Compute aggregate metrics
        metrics = self._compute_metrics(results)
        domain_metrics = self._compute_domain_metrics(results, task_domains)

        # Log aggregate metrics
        self._run.log({
            "eval/success_rate": metrics["success_rate"],
            "eval/avg_score": metrics["avg_score"],
            "eval/avg_steps": metrics["avg_steps"],
            "eval/avg_time_seconds": metrics["avg_time_seconds"],
            "eval/num_tasks": metrics["num_tasks"],
            "eval/num_success": metrics["num_success"],
        })

        # Log per-domain metrics
        for domain, dm in domain_metrics.items():
            self._run.log({
                f"eval/domain/{domain}/success_rate": dm["success_rate"],
                f"eval/domain/{domain}/avg_steps": dm["avg_steps"],
                f"eval/domain/{domain}/num_tasks": dm["num_tasks"],
            })

        # Log task results table
        self._log_task_table(results, task_domains)

        # Log error breakdown
        self._log_error_breakdown(results)

        # Log step distribution
        self._log_step_distribution(results)

        logger.info(
            f"Logged {len(results)} results to wandb: "
            f"{metrics['success_rate']:.1%} success rate"
        )

    def log_artifact(
        self,
        artifact_path: str | Path,
        name: str,
        artifact_type: str = "dataset",
        description: str | None = None,
    ) -> None:
        """Upload an artifact (screenshots, traces, etc.) to wandb.

        Args:
            artifact_path: Path to file or directory.
            name: Artifact name.
            artifact_type: Type of artifact ("dataset", "model", etc.).
            description: Optional description.
        """
        if self._run is None:
            self.init()

        artifact = wandb.Artifact(
            name=name,
            type=artifact_type,
            description=description,
        )

        path = Path(artifact_path)
        if path.is_dir():
            artifact.add_dir(str(path))
        else:
            artifact.add_file(str(path))

        self._run.log_artifact(artifact)
        logger.info(f"Uploaded artifact: {name}")

    def log_benchmark_dir(
        self,
        benchmark_dir: str | Path,
        include_screenshots: bool = True,
    ) -> None:
        """Upload benchmark results directory as artifacts.

        Args:
            benchmark_dir: Path to benchmark results directory.
            include_screenshots: Whether to include screenshot files.
        """
        if self._run is None:
            self.init()

        benchmark_dir = Path(benchmark_dir)

        # Upload summary.json
        summary_path = benchmark_dir / "summary.json"
        if summary_path.exists():
            self.log_artifact(
                summary_path,
                name=f"summary_{benchmark_dir.name}",
                artifact_type="results",
                description="Benchmark summary JSON",
            )

        # Upload execution traces
        tasks_dir = benchmark_dir / "tasks"
        if tasks_dir.exists():
            # Create artifact with execution traces
            artifact = wandb.Artifact(
                name=f"traces_{benchmark_dir.name}",
                type="execution_traces",
                description="Task execution traces",
            )

            for task_dir in tasks_dir.iterdir():
                if task_dir.is_dir():
                    execution_path = task_dir / "execution.json"
                    if execution_path.exists():
                        artifact.add_file(
                            str(execution_path),
                            name=f"{task_dir.name}/execution.json",
                        )

                    if include_screenshots:
                        screenshots_dir = task_dir / "screenshots"
                        if screenshots_dir.exists():
                            artifact.add_dir(
                                str(screenshots_dir),
                                name=f"{task_dir.name}/screenshots",
                            )

            self._run.log_artifact(artifact)
            logger.info(f"Uploaded execution traces from {benchmark_dir}")

    def finish(self, exit_code: int = 0) -> None:
        """Finish the wandb run.

        Args:
            exit_code: Exit code (0 for success).
        """
        if self._run is not None:
            self._run.finish(exit_code=exit_code)
            logger.info(f"Finished wandb run: {self._run.url}")
            self._run = None

    def _compute_metrics(self, results: list[BenchmarkResult]) -> dict[str, Any]:
        """Compute aggregate metrics from results."""
        if not results:
            return {
                "num_tasks": 0,
                "num_success": 0,
                "success_rate": 0.0,
                "avg_score": 0.0,
                "avg_steps": 0.0,
                "avg_time_seconds": 0.0,
            }

        num_tasks = len(results)
        num_success = sum(1 for r in results if r.success)

        return {
            "num_tasks": num_tasks,
            "num_success": num_success,
            "success_rate": num_success / num_tasks,
            "avg_score": sum(r.score for r in results) / num_tasks,
            "avg_steps": sum(r.num_steps for r in results) / num_tasks,
            "avg_time_seconds": sum(r.total_time_seconds for r in results) / num_tasks,
        }

    def _compute_domain_metrics(
        self,
        results: list[BenchmarkResult],
        task_domains: dict[str, str],
    ) -> dict[str, dict[str, Any]]:
        """Compute per-domain metrics."""
        domain_results: dict[str, list[BenchmarkResult]] = defaultdict(list)

        for result in results:
            domain = task_domains.get(result.task_id, "unknown")
            domain_results[domain].append(result)

        return {
            domain: self._compute_metrics(domain_res)
            for domain, domain_res in domain_results.items()
        }

    def _log_task_table(
        self,
        results: list[BenchmarkResult],
        task_domains: dict[str, str],
    ) -> None:
        """Log task results as a wandb Table."""
        columns = [
            "task_id",
            "domain",
            "success",
            "score",
            "num_steps",
            "time_seconds",
            "error",
        ]

        data = []
        for r in results:
            domain = task_domains.get(r.task_id, "unknown")
            data.append([
                r.task_id,
                domain,
                r.success,
                r.score,
                r.num_steps,
                r.total_time_seconds,
                r.error or "",
            ])

        table = Table(columns=columns, data=data)
        self._run.log({"eval/task_results": table})

    def _log_error_breakdown(self, results: list[BenchmarkResult]) -> None:
        """Log error type breakdown."""
        error_counts: dict[str, int] = defaultdict(int)
        for r in results:
            if not r.success and r.error:
                error_counts[r.error] += 1
            elif not r.success:
                error_counts["unknown"] += 1

        if error_counts:
            # Create error breakdown table
            columns = ["error_type", "count", "percentage"]
            total_errors = sum(error_counts.values())
            data = [
                [error_type, count, count / total_errors * 100]
                for error_type, count in sorted(
                    error_counts.items(), key=lambda x: -x[1]
                )
            ]

            table = Table(columns=columns, data=data)
            self._run.log({"eval/error_breakdown": table})

            # Also log as individual metrics
            for error_type, count in error_counts.items():
                self._run.log({
                    f"eval/errors/{error_type}": count,
                })

    def _log_step_distribution(self, results: list[BenchmarkResult]) -> None:
        """Log step count distribution."""
        success_steps = [r.num_steps for r in results if r.success]
        fail_steps = [r.num_steps for r in results if not r.success]

        if success_steps:
            self._run.log({
                "eval/steps/success_mean": sum(success_steps) / len(success_steps),
                "eval/steps/success_min": min(success_steps),
                "eval/steps/success_max": max(success_steps),
            })

        if fail_steps:
            self._run.log({
                "eval/steps/fail_mean": sum(fail_steps) / len(fail_steps),
                "eval/steps/fail_min": min(fail_steps),
                "eval/steps/fail_max": max(fail_steps),
            })

    def __enter__(self) -> WandbLogger:
        """Context manager entry."""
        self.init()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Context manager exit."""
        exit_code = 1 if exc_type is not None else 0
        self.finish(exit_code=exit_code)


def load_results_from_summary(summary_path: str | Path) -> list[BenchmarkResult]:
    """Load BenchmarkResults from a summary.json file.

    Args:
        summary_path: Path to summary.json file.

    Returns:
        List of BenchmarkResult objects.
    """
    with open(summary_path) as f:
        summary = json.load(f)

    results = []
    for task_data in summary.get("tasks", []):
        results.append(BenchmarkResult(
            task_id=task_data["task_id"],
            success=task_data["success"],
            score=task_data.get("score", 1.0 if task_data["success"] else 0.0),
            num_steps=task_data.get("num_steps", 0),
            total_time_seconds=task_data.get("total_time_seconds", 0.0),
            error=task_data.get("error"),
        ))

    return results
