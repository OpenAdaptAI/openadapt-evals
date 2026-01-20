"""Simple VM utility - one helper function.

This module exists because we have 3+ places that need to run scripts on VMs.
If we had fewer, we wouldn't need this abstraction.

See SIMPLE_ARCHITECTURE.md for the philosophy.
"""

import json
import subprocess
from typing import Any


class VMCommandError(Exception):
    """Raised when a VM command fails."""
    pass


def run_on_vm(
    vm_name: str,
    resource_group: str,
    script: str,
    timeout: int = 180
) -> str:
    """Run a bash script on an Azure VM via run-command.

    This is the ONLY abstraction we need. Don't create more utilities
    until you have 3+ duplicates of this pattern.

    Args:
        vm_name: Azure VM name
        resource_group: Azure resource group
        script: Bash script to execute (as string)
        timeout: Timeout in seconds (default 3 minutes)

    Returns:
        Script output (stdout)

    Raises:
        VMCommandError: If command fails
        subprocess.TimeoutExpired: If timeout is exceeded

    Example:
        >>> result = run_on_vm("waa-eval-vm", "OPENADAPT-AGENTS", "docker ps")
        >>> print(result)
        CONTAINER ID   IMAGE     COMMAND   ...
    """
    result = subprocess.run(
        [
            "az", "vm", "run-command", "invoke",
            "--resource-group", resource_group,
            "--name", vm_name,
            "--command-id", "RunShellScript",
            "--scripts", script,
        ],
        capture_output=True,
        text=True,
        timeout=timeout,
    )

    if result.returncode != 0:
        raise VMCommandError(f"VM command failed: {result.stderr}")

    # Azure run-command returns JSON with output in value[0].message
    try:
        output = json.loads(result.stdout)
        message = output.get("value", [{}])[0].get("message", "")
        return message
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        # If JSON parsing fails, return raw output
        return result.stdout
