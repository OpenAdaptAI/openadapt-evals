"""Health checking for Azure ML compute instances and jobs.

IMPORTANT: This module is mostly stubbed out.

The actual health checking that WORKS is in cli.py's vm-setup command (lines 499-664).
That uses inline bash health checks executed via `az vm run-command invoke`.

This module was designed but never fully implemented. The working approach is simpler:
just run bash commands on the VM and check exit codes.

If you need health checks:
1. Add them to the vm-setup bash script in cli.py
2. Don't create abstractions until you have 3+ duplicates

See SIMPLE_ARCHITECTURE.md for the working pattern.
"""

from __future__ import annotations

import logging
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
    """Result of a health check operation."""
    healthy: bool
    message: str
    details: dict | None = None


def check_container_health(container_name: str = "winarena") -> HealthCheckResult:
    """Stub - use vm-setup bash script instead.

    The actual health check is in cli.py cmd_vm_setup():
    - Checks if container is running
    - Waits for VNC port
    - Tests WAA server /probe endpoint

    See lines 499-664 in cli.py for working implementation.
    """
    return HealthCheckResult(
        healthy=False,
        message="STUB: Use vm-setup command for actual health checks",
        details={"note": "See cli.py cmd_vm_setup() for working implementation"}
    )


def check_job_stuck(ml_client: AzureMLClient, job_name: str, timeout_minutes: int = 10) -> HealthCheckResult:
    """Stub - Azure ML has built-in timeouts.

    Configure timeout in azure.py AzureConfig.job_timeout instead.
    """
    return HealthCheckResult(
        healthy=False,
        message="STUB: Use Azure ML job timeout configuration instead",
        details={"note": "Set job_timeout in AzureConfig"}
    )
