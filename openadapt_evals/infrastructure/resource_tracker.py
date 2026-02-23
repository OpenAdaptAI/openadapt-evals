#!/usr/bin/env python3
"""
Resource Tracker - Track deployed Azure resources to prevent losing track of running VMs.

This module provides:
1. Functions to check Azure resource status
2. Functions to update a persistent RESOURCES.md file
3. A CLI entry point for use as a Claude Code hook

Usage as hook:
    python -m openadapt_evals.infrastructure.resource_tracker

The hook outputs JSON to stdout which Claude Code injects into context.
"""

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

# Constants
RESOURCE_GROUP = "openadapt-agents"
VM_NAME = "waa-eval-vm"
RESOURCES_FILE = Path(__file__).parent.parent.parent / "RESOURCES.md"

# VM hourly rates
VM_HOURLY_RATES = {
    "Standard_D4ds_v4": 0.19,
    "Standard_D8ds_v5": 0.38,
    "Standard_D8s_v5": 0.36,
    "Standard_D8ds_v4": 0.38,
    "Standard_D8as_v5": 0.34,
}

# Paused pool cost: OS disk (~$0.15/day) + static IP (~$0.10/day) per VM
PAUSED_POOL_COST_PER_VM_PER_DAY = 0.25


def get_paused_pool() -> dict | None:
    """Check if there is a paused VM pool in the registry.

    Returns:
        Dict with pool info if a paused pool exists, None otherwise.
    """
    try:
        from openadapt_evals.infrastructure.vm_monitor import VMPoolRegistry

        registry = VMPoolRegistry()
        pool = registry.get_pool()
        if pool is not None and pool.status == "paused":
            paused_days = 0.0
            if pool.paused_since:
                paused_dt = datetime.fromisoformat(pool.paused_since)
                paused_days = (datetime.now() - paused_dt).total_seconds() / 86400

            return {
                "pool_id": pool.pool_id,
                "num_workers": len(pool.workers),
                "paused_since": pool.paused_since,
                "paused_days": paused_days,
                "daily_cost": PAUSED_POOL_COST_PER_VM_PER_DAY * len(pool.workers),
                "accumulated_cost": PAUSED_POOL_COST_PER_VM_PER_DAY * len(pool.workers) * paused_days,
            }
    except Exception:
        pass
    return None


def get_azure_vms() -> list[dict]:
    """Get all VMs in the resource group."""
    try:
        result = subprocess.run(
            ["az", "vm", "list", "-g", RESOURCE_GROUP, "--show-details", "-o", "json"],
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0 and result.stdout.strip():
            return json.loads(result.stdout)
    except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
        pass
    return []


def get_azure_ml_compute() -> list[dict]:
    """Get Azure ML compute instances from all known workspaces."""
    all_compute = []

    # Try to get workspaces from settings, fall back to known defaults
    try:
        from openadapt_evals.config import settings

        workspaces = [
            (settings.azure_ml_resource_group, settings.azure_ml_workspace_name),
        ]
    except Exception:
        workspaces = []

    # Add known workspaces
    known_workspaces = [
        (RESOURCE_GROUP, "openadapt-ml"),
        (RESOURCE_GROUP, "openadapt-ml-central"),
    ]
    for ws in known_workspaces:
        if ws not in workspaces:
            workspaces.append(ws)

    for resource_group, workspace_name in workspaces:
        try:
            result = subprocess.run(
                [
                    "az",
                    "ml",
                    "compute",
                    "list",
                    "-g",
                    resource_group,
                    "-w",
                    workspace_name,
                    "-o",
                    "json",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0 and result.stdout.strip():
                compute_list = json.loads(result.stdout)
                for ci in compute_list:
                    ci["_workspace"] = workspace_name
                all_compute.extend(compute_list)
        except (subprocess.TimeoutExpired, json.JSONDecodeError, FileNotFoundError):
            pass

    return all_compute


def check_resources() -> dict:
    """Check all Azure resources and return status dict."""
    status = {
        "timestamp": datetime.now().isoformat(),
        "vms": [],
        "compute_instances": [],
        "paused_pool": None,
        "total_running_cost_per_hour": 0.0,
        "has_running_resources": False,
        "has_paused_pool": False,
        "warnings": [],
    }

    # Check VMs
    vms = get_azure_vms()
    for vm in vms:
        name = vm.get("name", "unknown")
        power_state = vm.get("powerState", "unknown")
        vm_size = vm.get("hardwareProfile", {}).get("vmSize", "unknown")
        public_ip = vm.get("publicIps", "")

        is_running = "running" in power_state.lower() if power_state else False
        hourly_rate = VM_HOURLY_RATES.get(vm_size, 0.20)

        vm_info = {
            "name": name,
            "state": power_state,
            "size": vm_size,
            "ip": public_ip,
            "hourly_rate": hourly_rate,
            "is_running": is_running,
        }
        status["vms"].append(vm_info)

        if is_running:
            status["has_running_resources"] = True
            status["total_running_cost_per_hour"] += hourly_rate
            status["warnings"].append(
                f"VM '{name}' is RUNNING at ${hourly_rate:.2f}/hr. "
                f"Deallocate when done: uv run python -m openadapt_evals.benchmarks.cli deallocate"
            )

    # Check Azure ML compute
    compute_instances = get_azure_ml_compute()
    for ci in compute_instances:
        name = ci.get("name", "unknown")
        state = ci.get("state", "unknown")
        vm_size = ci.get("vmSize", ci.get("properties", {}).get("vmSize", "unknown"))

        is_running = state.lower() in ["running", "starting"] if state else False
        hourly_rate = VM_HOURLY_RATES.get(vm_size, 0.20)

        ci_info = {
            "name": name,
            "state": state,
            "size": vm_size,
            "hourly_rate": hourly_rate,
            "is_running": is_running,
        }
        status["compute_instances"].append(ci_info)

        if is_running:
            status["has_running_resources"] = True
            status["total_running_cost_per_hour"] += hourly_rate
            status["warnings"].append(
                f"Azure ML compute '{name}' is RUNNING at ${hourly_rate:.2f}/hr"
            )

    # Check for paused pool
    paused_pool = get_paused_pool()
    if paused_pool:
        status["paused_pool"] = paused_pool
        status["has_paused_pool"] = True
        days = paused_pool["paused_days"]
        daily_cost = paused_pool["daily_cost"]
        accumulated = paused_pool["accumulated_cost"]
        status["warnings"].append(
            f"Paused pool ({paused_pool['num_workers']} VMs) idle for "
            f"{days:.1f} days. Disk cost: ${daily_cost:.2f}/day "
            f"(${accumulated:.2f} accumulated). "
            f"Resume: oa-vm pool-resume | Delete: oa-vm pool-cleanup -y"
        )

    return status


def update_resources_file(status: dict) -> None:
    """Update RESOURCES.md with current status."""
    lines = [
        "# Active Azure Resources",
        "",
        f"**Last Updated**: {status['timestamp']}",
        "",
    ]

    if status["has_running_resources"]:
        lines.extend(
            [
                "## WARNING: Running Resources Detected!",
                "",
                f"**Estimated Cost**: ${status['total_running_cost_per_hour']:.2f}/hour",
                "",
            ]
        )

        for warning in status["warnings"]:
            lines.append(f"- {warning}")
        lines.append("")
    else:
        lines.extend(
            [
                "## No Running Resources",
                "",
                "All Azure resources are deallocated or stopped.",
                "",
            ]
        )

    # VMs section
    if status["vms"]:
        lines.extend(["## Virtual Machines", ""])
        for vm in status["vms"]:
            state_emoji = "RUNNING" if vm["is_running"] else "stopped"
            lines.append(
                f"- **{vm['name']}**: {state_emoji} ({vm['size']}) - ${vm['hourly_rate']:.2f}/hr"
            )
            if vm["ip"]:
                lines.append(f"  - IP: {vm['ip']}")
        lines.append("")

    # Compute instances section
    if status["compute_instances"]:
        lines.extend(["## Azure ML Compute Instances", ""])
        for ci in status["compute_instances"]:
            state_emoji = "RUNNING" if ci["is_running"] else "stopped"
            lines.append(
                f"- **{ci['name']}**: {state_emoji} ({ci['size']}) - ${ci['hourly_rate']:.2f}/hr"
            )
        lines.append("")

    # Paused pool section
    paused_pool = status.get("paused_pool")
    if paused_pool:
        lines.extend(["## Paused VM Pool", ""])
        lines.append(
            f"- **Pool {paused_pool['pool_id']}**: "
            f"{paused_pool['num_workers']} VMs paused for "
            f"{paused_pool['paused_days']:.1f} days"
        )
        lines.append(
            f"  - Daily cost: ${paused_pool['daily_cost']:.2f}/day "
            f"(accumulated: ${paused_pool['accumulated_cost']:.2f})"
        )
        lines.append(f"  - Resume: `oa-vm pool-resume`")
        lines.append(f"  - Delete: `oa-vm pool-cleanup -y`")
        lines.append("")

    # Commands reference
    lines.extend(
        [
            "## Quick Commands",
            "",
            "```bash",
            "# Check VM status",
            "uv run python -m openadapt_evals.benchmarks.cli status",
            "",
            "# Deallocate VM (stops billing)",
            "uv run python -m openadapt_evals.benchmarks.cli deallocate",
            "",
            "# Delete VM and all resources",
            "uv run python -m openadapt_evals.benchmarks.cli delete -y",
            "",
            "# Pause pool (stop compute, keep disks)",
            "oa-vm pool-pause",
            "",
            "# Resume paused pool (~5 min)",
            "oa-vm pool-resume",
            "",
            "# Start monitoring dashboard",
            "uv run python -m openadapt_evals.benchmarks.cli vm monitor",
            "```",
            "",
        ]
    )

    RESOURCES_FILE.write_text("\n".join(lines))


def format_for_hook(status: dict) -> str:
    """Format status for Claude Code SessionStart hook output.

    Output goes to stdout and is injected into Claude's context.
    """
    has_running = status["has_running_resources"]
    has_paused = status.get("has_paused_pool", False)

    if not has_running and not has_paused:
        return ""  # No message if nothing running or paused

    lines = [""]

    if has_running:
        lines.extend(
            [
                "=" * 60,
                "AZURE RESOURCE ALERT: Running resources detected!",
                "=" * 60,
                "",
            ]
        )

    if has_paused and not has_running:
        lines.extend(
            [
                "=" * 60,
                "AZURE RESOURCE NOTICE: Paused pool detected",
                "=" * 60,
                "",
            ]
        )

    for warning in status["warnings"]:
        lines.append(f"  {warning}")

    if has_running:
        lines.extend(
            [
                "",
                f"  Estimated compute cost: ${status['total_running_cost_per_hour']:.2f}/hour",
                "",
                "  To stop billing, run:",
                "    uv run python -m openadapt_evals.benchmarks.cli deallocate",
                "",
            ]
        )
    elif has_paused:
        paused_pool = status.get("paused_pool", {})
        lines.extend(
            [
                "",
                f"  Idle disk cost: ${paused_pool.get('daily_cost', 0.25):.2f}/day",
                "",
            ]
        )

    lines.extend(["=" * 60, ""])

    return "\n".join(lines)


def main():
    """Entry point for hook - outputs alert to stdout if resources are running."""
    status = check_resources()

    # Always update the RESOURCES.md file
    try:
        update_resources_file(status)
    except Exception:
        pass  # Don't fail the hook if file write fails

    # Output alert to stdout (injected into Claude context)
    alert = format_for_hook(status)
    if alert:
        print(alert)

    # Exit 0 = success, output is shown to user and added to context
    return 0


if __name__ == "__main__":
    sys.exit(main())
