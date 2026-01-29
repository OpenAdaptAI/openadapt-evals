"""Health checking for Azure ML compute instances and jobs.

This module provides health monitoring utilities to detect:
- Container startup failures
- Stuck jobs with no progress
- Resource exhaustion on compute nodes

These checks help prevent jobs from running indefinitely without making progress,
which was a critical issue identified in the failed WAA evaluation (Issue #8).
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from openadapt_evals.benchmarks.azure import AzureMLClient

logger = logging.getLogger(__name__)


class ContainerStartupTimeout(Exception):
    """Raised when a container fails to start within the timeout period."""
    pass


class ContainerSetupError(Exception):
    """Raised when container setup fails (Docker pull, image issues, etc.)."""
    pass


class JobStuckError(Exception):
    """Raised when a job is stuck without making progress."""
    pass


@dataclass
class HealthCheckResult:
    """Result of a health check operation.

    Attributes:
        healthy: Whether the check passed.
        message: Human-readable status message.
        details: Additional diagnostic information.
    """
    healthy: bool
    message: str
    details: dict | None = None


class ContainerHealthChecker:
    """Monitors container startup and health for Azure ML jobs.

    This checker addresses the critical issue where jobs would get stuck
    in "Running" state without the Docker container ever starting successfully.
    """

    # Log patterns indicating successful container startup
    CONTAINER_STARTED_PATTERNS = [
        re.compile(r"Container\s+started", re.IGNORECASE),
        re.compile(r"Executing\s+task", re.IGNORECASE),
        re.compile(r"Task\s+\d+/\d+:", re.IGNORECASE),
        re.compile(r"WAA\s+client\s+initialized", re.IGNORECASE),
    ]

    # Log patterns indicating container startup failure
    CONTAINER_FAILED_PATTERNS = [
        re.compile(r"Container\s+setup\s+failed", re.IGNORECASE),
        re.compile(r"Docker\s+pull\s+failed", re.IGNORECASE),
        re.compile(r"failed\s+to\s+pull\s+image", re.IGNORECASE),
        re.compile(r"Error\s+response\s+from\s+daemon", re.IGNORECASE),
        re.compile(r"Cannot\s+connect\s+to\s+the\s+Docker\s+daemon", re.IGNORECASE),
    ]

    def __init__(self, ml_client: AzureMLClient):
        """Initialize health checker.

        Args:
            ml_client: Azure ML client for querying job status and logs.
        """
        self.ml_client = ml_client

    def wait_for_container_start(
        self,
        job_name: str,
        timeout_seconds: int = 600,
        poll_interval: int = 10,
    ) -> bool:
        """Wait for a container to start successfully.

        Polls job logs looking for evidence that the Docker container has
        started and is executing code. Returns False if timeout is exceeded
        without seeing startup indicators.

        Args:
            job_name: Azure ML job name.
            timeout_seconds: Maximum time to wait (default: 600s = 10 min).
            poll_interval: How often to check logs (default: 10s).

        Returns:
            True if container started successfully, False if timeout.

        Raises:
            ContainerSetupError: If container startup explicitly failed.
        """
        start_time = time.time()
        logger.info(
            f"Waiting for container to start (job: {job_name}, "
            f"timeout: {timeout_seconds}s)"
        )

        last_log_content = ""

        while time.time() - start_time < timeout_seconds:
            try:
                # Get current job logs
                logs = self._get_job_logs(job_name)

                # Check if we have new content
                if logs != last_log_content:
                    last_log_content = logs

                    # Check for successful startup
                    if self._has_container_started(logs):
                        elapsed = time.time() - start_time
                        logger.info(
                            f"Container started successfully for {job_name} "
                            f"(elapsed: {elapsed:.1f}s)"
                        )
                        return True

                    # Check for startup failure
                    if self._has_container_failed(logs):
                        error_msg = self._extract_error_message(logs)
                        raise ContainerSetupError(
                            f"Container startup failed for {job_name}: {error_msg}"
                        )

            except Exception as e:
                if isinstance(e, ContainerSetupError):
                    raise
                logger.warning(f"Error checking container status: {e}")

            time.sleep(poll_interval)

        # Timeout exceeded
        elapsed = time.time() - start_time
        logger.warning(
            f"Container startup timeout for {job_name} "
            f"(elapsed: {elapsed:.1f}s, no startup logs detected)"
        )
        return False

    def check_container_running(self, job_name: str) -> HealthCheckResult:
        """Check if a container is currently running and healthy.

        Args:
            job_name: Azure ML job name.

        Returns:
            HealthCheckResult with status.
        """
        try:
            job = self.ml_client.client.jobs.get(job_name)

            if job.status == "Running":
                # Get recent logs to verify activity
                logs = self._get_job_logs(job_name, last_n_lines=50)

                if self._has_container_started(logs):
                    return HealthCheckResult(
                        healthy=True,
                        message=f"Job {job_name} is running with active container",
                        details={"status": job.status},
                    )
                else:
                    return HealthCheckResult(
                        healthy=False,
                        message=f"Job {job_name} is Running but no container activity detected",
                        details={"status": job.status, "logs_preview": logs[:200]},
                    )

            elif job.status in ["Completed", "Succeeded"]:
                return HealthCheckResult(
                    healthy=True,
                    message=f"Job {job_name} completed successfully",
                    details={"status": job.status},
                )

            else:
                return HealthCheckResult(
                    healthy=False,
                    message=f"Job {job_name} in unexpected state: {job.status}",
                    details={"status": job.status},
                )

        except Exception as e:
            return HealthCheckResult(
                healthy=False,
                message=f"Failed to check container health: {e}",
                details={"error": str(e)},
            )

    def monitor_job_progress(
        self,
        job_name: str,
        no_progress_timeout_seconds: int = 600,
    ) -> HealthCheckResult:
        """Monitor a job for signs of being stuck without progress.

        A job is considered stuck if:
        - No new logs for > no_progress_timeout_seconds
        - Status is "Running" but no activity

        Args:
            job_name: Azure ML job name.
            no_progress_timeout_seconds: Time without logs = stuck (default: 10 min).

        Returns:
            HealthCheckResult indicating if job is making progress.
        """
        try:
            job = self.ml_client.client.jobs.get(job_name)

            # Only check running jobs
            if job.status != "Running":
                return HealthCheckResult(
                    healthy=True,
                    message=f"Job not running (status: {job.status})",
                    details={"status": job.status},
                )

            # Get recent logs
            logs = self._get_job_logs(job_name)

            # Check for recent activity by looking at timestamps in logs
            # If we can't find recent activity, the job may be stuck
            has_recent_activity = self._has_recent_log_activity(
                logs,
                max_age_seconds=no_progress_timeout_seconds
            )

            if has_recent_activity:
                return HealthCheckResult(
                    healthy=True,
                    message=f"Job {job_name} is making progress",
                    details={"status": job.status, "has_recent_logs": True},
                )
            else:
                return HealthCheckResult(
                    healthy=False,
                    message=f"Job {job_name} stuck: no logs for >{no_progress_timeout_seconds}s",
                    details={
                        "status": job.status,
                        "has_recent_logs": False,
                        "recommendation": "Consider canceling and retrying",
                    },
                )

        except Exception as e:
            return HealthCheckResult(
                healthy=False,
                message=f"Failed to monitor job progress: {e}",
                details={"error": str(e)},
            )

    def _get_job_logs(self, job_name: str, last_n_lines: int | None = None) -> str:
        """Get job logs from Azure ML.

        Args:
            job_name: Azure ML job name.
            last_n_lines: If specified, only return last N lines.

        Returns:
            Log content as string.
        """
        try:
            # Use the ml_client's get_job_logs method
            return self.ml_client.get_job_logs(job_name, tail=last_n_lines)
        except Exception as e:
            logger.warning(f"Failed to fetch logs for {job_name}: {e}")
            return ""

    def _has_container_started(self, logs: str) -> bool:
        """Check if logs indicate successful container startup."""
        for pattern in self.CONTAINER_STARTED_PATTERNS:
            if pattern.search(logs):
                return True
        return False

    def _has_container_failed(self, logs: str) -> bool:
        """Check if logs indicate container startup failure."""
        for pattern in self.CONTAINER_FAILED_PATTERNS:
            if pattern.search(logs):
                return True
        return False

    def _extract_error_message(self, logs: str) -> str:
        """Extract error message from logs."""
        # Look for error lines
        lines = logs.split("\n")
        error_lines = [
            line for line in lines
            if any(keyword in line.lower() for keyword in ["error", "failed", "exception"])
        ]

        if error_lines:
            # Return first few error lines
            return " | ".join(error_lines[:3])

        return "Unknown error (check logs for details)"

    def _has_recent_log_activity(self, logs: str, max_age_seconds: int) -> bool:
        """Check if logs contain recent activity.

        Args:
            logs: Log content.
            max_age_seconds: Maximum age for "recent" activity.

        Returns:
            True if recent activity found, False otherwise.
        """
        # Simplified implementation: check if we have any logs at all
        # Real implementation would parse timestamps and check age
        # TODO: Implement proper timestamp parsing

        if not logs or len(logs.strip()) == 0:
            return False

        # For now, assume any non-empty logs indicate recent activity
        # In production, this should parse actual timestamps
        return True


class StuckJobDetector:
    """Detects and handles stuck jobs that aren't making progress.

    This addresses the critical issue where jobs would run for 8+ hours
    without completing any tasks, consuming compute resources without output.
    """

    def __init__(self, ml_client: AzureMLClient):
        """Initialize stuck job detector.

        Args:
            ml_client: Azure ML client for querying and canceling jobs.
        """
        self.ml_client = ml_client
        self.container_checker = ContainerHealthChecker(ml_client)

    def check_and_handle_stuck_job(
        self,
        job_name: str,
        no_progress_timeout_seconds: int = 600,
        auto_cancel: bool = False,
    ) -> tuple[bool, str]:
        """Check if a job is stuck and optionally cancel it.

        Args:
            job_name: Azure ML job name.
            no_progress_timeout_seconds: Time without progress = stuck.
            auto_cancel: If True, automatically cancel stuck jobs.

        Returns:
            Tuple of (is_stuck, message).
        """
        # Check for progress
        result = self.container_checker.monitor_job_progress(
            job_name,
            no_progress_timeout_seconds
        )

        if result.healthy:
            return False, result.message

        # Job is stuck
        message = f"Job {job_name} is stuck: {result.message}"
        logger.warning(message)

        if auto_cancel:
            try:
                logger.info(f"Auto-canceling stuck job: {job_name}")
                self.ml_client.client.jobs.cancel(job_name)
                message += " (auto-canceled)"
            except Exception as e:
                logger.error(f"Failed to cancel stuck job {job_name}: {e}")
                message += f" (cancel failed: {e})"

        return True, message
