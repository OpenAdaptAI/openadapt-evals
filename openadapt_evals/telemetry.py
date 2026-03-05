"""openadapt-evals telemetry wrapper.

Thin adapter over openadapt-telemetry PostHog usage events.
"""

from __future__ import annotations

from typing import Any

from openadapt_telemetry.posthog import capture_usage_event

_PACKAGE_NAME = "openadapt-evals"


def _compact(properties: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in properties.items() if value is not None}


def capture_event(event: str, properties: dict[str, Any] | None = None) -> bool:
    """Capture a raw usage event."""
    return capture_usage_event(
        event=event,
        properties=_compact(properties or {}),
        package_name=_PACKAGE_NAME,
    )


def track_agent_run(
    *,
    phase: str,
    adapter: str | None = None,
    agent_class: str | None = None,
    entrypoint: str | None = None,
    mode: str | None = None,
    num_tasks: int | None = None,
    max_steps: int | None = None,
    parallel: int | None = None,
    run_name: str | None = None,
) -> bool:
    properties = {
        "phase": phase,
        "adapter": adapter,
        "agent_class": agent_class,
        "entrypoint": entrypoint,
        "mode": mode,
        "num_tasks": num_tasks,
        "max_steps": max_steps,
        "parallel": parallel,
        "run_name": run_name,
    }
    return capture_event("agent_run", properties)


def track_agent_run_completed(
    *,
    adapter: str | None = None,
    agent_class: str | None = None,
    entrypoint: str | None = None,
    mode: str | None = None,
    num_tasks: int | None = None,
    success_count: int | None = None,
    avg_steps: float | None = None,
    return_code: int | None = None,
    duration_seconds: float | None = None,
    run_name: str | None = None,
) -> bool:
    properties = {
        "adapter": adapter,
        "agent_class": agent_class,
        "entrypoint": entrypoint,
        "mode": mode,
        "num_tasks": num_tasks,
        "success_count": success_count,
        "avg_steps": avg_steps,
        "return_code": return_code,
        "duration_seconds": duration_seconds,
        "run_name": run_name,
    }
    return capture_event("agent_run_completed", properties)


def track_action_executed(
    *,
    task_id: str | None = None,
    step_index: int | None = None,
    action_type: str | None = None,
    adapter: str | None = None,
    agent_class: str | None = None,
) -> bool:
    properties = {
        "task_id": task_id,
        "step_index": step_index,
        "action_type": action_type,
        "adapter": adapter,
        "agent_class": agent_class,
    }
    return capture_event("action_executed", properties)


def track_demo_recorded(
    *,
    task_id: str | None = None,
    mode: str | None = None,
    steps: int | None = None,
    output_dir: str | None = None,
    phase: str | None = None,
) -> bool:
    properties = {
        "task_id": task_id,
        "mode": mode,
        "steps": steps,
        "output_dir": output_dir,
        "phase": phase,
    }
    return capture_event("demo_recorded", properties)
