#!/usr/bin/env python3
"""Systematic model comparison framework for WAA tasks.

Phase 1: API models only. Runs each model on each task under identical
conditions, producing structured comparison output.

Usage:
    # Basic comparison (VM/tunnels already running):
    python scripts/compare_models.py --config example_comparisons/api_models.yaml

    # With full VM lifecycle management:
    python scripts/compare_models.py \
        --config example_comparisons/api_models.yaml \
        --manage-vm --setup-tunnels

    # Override server URL:
    python scripts/compare_models.py \
        --config example_comparisons/api_models.yaml \
        --server-url http://localhost:5002

    # Resume an interrupted comparison:
    python scripts/compare_models.py \
        --config example_comparisons/api_models.yaml --resume

Prerequisites:
    - WAA VM running with SSH tunnel (port 5001 -> VM port 5000), OR
    - Use --manage-vm --setup-tunnels for automatic lifecycle
    - API keys set (OPENAI_API_KEY, ANTHROPIC_API_KEY as needed)
"""

from __future__ import annotations

import argparse
import html
import json
import logging
import signal
import sys
import time
import traceback
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("compare_models")

_shutdown_requested = False


def _signal_handler(signum, frame):
    global _shutdown_requested
    if _shutdown_requested:
        logger.warning("Second interrupt received, forcing exit")
        sys.exit(1)
    _shutdown_requested = True
    logger.warning("Shutdown requested, finishing current run...")


signal.signal(signal.SIGINT, _signal_handler)
signal.signal(signal.SIGTERM, _signal_handler)


# ---------------------------------------------------------------------------
# Config loading
# ---------------------------------------------------------------------------


@dataclass
class ModelConfig:
    """A single model to compare."""

    name: str
    provider: str  # "openai", "anthropic"
    type: str = "unified"  # "unified" (Phase 1), "split" (Phase 2+)
    # Phase 2 fields (local models via vLLM):
    model_id: str | None = None
    serve_via: str | None = None
    vllm_args: dict[str, Any] = field(default_factory=dict)


@dataclass
class ComparisonConfig:
    """Full comparison specification loaded from YAML."""

    name: str
    description: str
    tasks: list[str]
    models: list[ModelConfig]
    server_url: str
    max_steps: int
    runs_per_config: int
    save_screenshots: bool
    output_dir: str


def load_config(path: str) -> ComparisonConfig:
    """Load a comparison config from a YAML file.

    Args:
        path: Path to the YAML config file.

    Returns:
        Parsed ComparisonConfig.
    """
    with open(path) as f:
        raw = yaml.safe_load(f)

    models = []
    for m in raw.get("models", []):
        models.append(
            ModelConfig(
                name=m["name"],
                provider=m.get("provider", "openai"),
                type=m.get("type", "unified"),
                model_id=m.get("model_id"),
                serve_via=m.get("serve_via"),
                vllm_args=m.get("vllm_args", {}),
            )
        )

    return ComparisonConfig(
        name=raw.get("name", "Unnamed Comparison"),
        description=raw.get("description", ""),
        tasks=raw.get("tasks", []),
        models=models,
        server_url=raw.get("server_url", "http://localhost:5001"),
        max_steps=raw.get("max_steps", 15),
        runs_per_config=raw.get("runs_per_config", 1),
        save_screenshots=raw.get("save_screenshots", True),
        output_dir=raw.get("output_dir", "comparison_results/"),
    )


# ---------------------------------------------------------------------------
# Infrastructure helpers (reused from run_correction_flywheel.py)
# ---------------------------------------------------------------------------


def _manage_vm_lifecycle(
    vm_name: str,
    resource_group: str,
) -> str | None:
    """Start the VM and return its public IP.

    Returns:
        Public IP string, or None on failure.
    """
    # Import the flywheel infra helpers (avoid import at top level so the
    # script works without Azure CLI when --manage-vm is not used).
    from scripts.run_correction_flywheel import (
        get_vm_ip,
        start_vm,
        wait_for_ssh,
    )

    if not start_vm(vm_name, resource_group):
        return None

    ip = get_vm_ip(vm_name, resource_group)
    if not ip:
        logger.error("Could not get IP for VM %s", vm_name)
        return None

    if not wait_for_ssh(ip):
        return None

    return ip


def _setup_tunnels(vm_ip: str) -> dict[str, int | None]:
    """Set up SSH tunnels to the VM. Returns tunnel PIDs."""
    from scripts.run_correction_flywheel import setup_tunnels, wait_for_waa

    pids = setup_tunnels(vm_ip)
    return pids


def _wait_for_waa(server_url: str, timeout: int = 600) -> bool:
    """Wait for WAA server to respond."""
    from scripts.run_correction_flywheel import wait_for_waa

    return wait_for_waa(server_url, timeout=timeout)


# ---------------------------------------------------------------------------
# Agent creation
# ---------------------------------------------------------------------------


def create_unified_agent(model_config: ModelConfig):
    """Create a unified agent (same model plans + grounds).

    Uses PlannerGrounderAgent with the same API model as both planner
    and grounder, which effectively makes it a unified agent.

    Args:
        model_config: Model configuration.

    Returns:
        A BenchmarkAgent instance.
    """
    from openadapt_evals.agents.planner_grounder_agent import PlannerGrounderAgent

    agent = PlannerGrounderAgent(
        planner=model_config.name,
        grounder=model_config.name,
        planner_provider=model_config.provider,
        grounder_provider=model_config.provider,
    )
    return agent


# ---------------------------------------------------------------------------
# Single run execution (reuses run_full_eval.run_single_task pattern)
# ---------------------------------------------------------------------------


def run_single_task(
    task_path: str,
    agent,
    server_url: str,
    max_steps: int,
    screenshots_dir: Path | None,
) -> dict[str, Any]:
    """Run a single task and return a result dict. Never raises.

    Args:
        task_path: Path to the task YAML config file.
        agent: BenchmarkAgent instance.
        server_url: WAA server URL.
        max_steps: Maximum steps per episode.
        screenshots_dir: Directory to save screenshots, or None.

    Returns:
        Result dict with score, steps, elapsed time, etc.
    """
    from openadapt_evals.adapters.base import BenchmarkTask
    from openadapt_evals.adapters.rl_env import RLEnvironment, ResetConfig
    from openadapt_evals.adapters.waa.live import WAALiveAdapter, WAALiveConfig
    from openadapt_evals.task_config import TaskConfig

    start_time = time.time()
    task_config = TaskConfig.from_yaml(task_path)

    result: dict[str, Any] = {
        "task_id": task_config.id,
        "task_name": task_config.name,
        "task_path": task_path,
        "started_at": datetime.now().isoformat(),
        "score": 0.0,
        "milestones_passed": 0,
        "milestones_total": 0,
        "steps": 0,
        "actions": [],
        "error": None,
    }

    try:
        adapter = WAALiveAdapter(WAALiveConfig(server_url=server_url))
        env = RLEnvironment(adapter, task_config=task_config)

        obs = env.reset(config=ResetConfig(task_id=task_config.id))

        task = BenchmarkTask(
            task_id=task_config.id,
            instruction=task_config.name,
            domain="desktop",
        )

        # Save reset screenshot
        task_screenshot_dir = None
        if screenshots_dir:
            task_screenshot_dir = screenshots_dir
            task_screenshot_dir.mkdir(parents=True, exist_ok=True)
            if obs.screenshot:
                (task_screenshot_dir / "step_00_reset.png").write_bytes(
                    obs.screenshot
                )

        actions_log = []
        for step in range(max_steps):
            if _shutdown_requested:
                result["error"] = "shutdown_requested"
                break

            action = agent.act(obs, task)
            actions_log.append(
                {
                    "step": step + 1,
                    "type": action.type,
                    "x": action.x,
                    "y": action.y,
                    "text": action.text,
                }
            )

            if action.type == "done":
                break
            if action.type == "error":
                result["error"] = str(action.raw_action)
                break

            # Execute action
            if action.x is not None and action.y is not None:
                x = float(action.x)
                y = float(action.y)
                if 0 <= x <= 1 and 0 <= y <= 1:
                    step_result = env.pixel_action(
                        x_frac=x,
                        y_frac=y,
                        action_type=action.type,
                        text=action.text,
                        key=action.key,
                    )
                else:
                    step_result = env.pixel_action(
                        x=int(x),
                        y=int(y),
                        action_type=action.type,
                        text=action.text,
                        key=action.key,
                    )
            else:
                step_result = env.step(action)

            obs = step_result.observation

            if task_screenshot_dir and obs.screenshot:
                (task_screenshot_dir / f"step_{step + 1:02d}.png").write_bytes(
                    obs.screenshot
                )

            if step_result.done:
                break

        # Evaluate
        result["steps"] = env.step_count
        result["actions"] = actions_log

        if task_config.milestones:
            score = env.evaluate_dense()
            last = env.trajectory[-1] if env.trajectory else None
            info = last.info if last else {}
            result["milestones_passed"] = info.get("milestones_passed", 0)
            result["milestones_total"] = info.get("milestones_total", 0)
        else:
            score = env.evaluate()

        result["score"] = score

    except Exception as e:
        result["error"] = str(e)
        result["traceback"] = traceback.format_exc()
        logger.error("Task %s failed: %s", task_path, e)

    result["elapsed_seconds"] = round(time.time() - start_time, 2)
    result["finished_at"] = datetime.now().isoformat()
    return result


# ---------------------------------------------------------------------------
# Comparison orchestrator
# ---------------------------------------------------------------------------


def run_comparison(
    config: ComparisonConfig,
    server_url_override: str | None = None,
    resume: bool = False,
) -> list[dict[str, Any]]:
    """Run all (model, task) combinations and collect results.

    Args:
        config: Comparison configuration.
        server_url_override: Override server URL from CLI.
        resume: Skip (model, task) pairs that already have results.

    Returns:
        List of result dicts.
    """
    server_url = server_url_override or config.server_url
    output_dir = Path(config.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    results_path = output_dir / "results.jsonl"

    # Load existing results for resume
    completed_keys: set[str] = set()
    existing_results: list[dict] = []
    if resume and results_path.exists():
        with open(results_path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    if rec.get("_meta"):
                        continue
                    key = f"{rec.get('model_name')}::{rec.get('task_path')}"
                    completed_keys.add(key)
                    existing_results.append(rec)
                except json.JSONDecodeError:
                    continue
        if completed_keys:
            logger.info(
                "Resume: %d runs already completed", len(completed_keys)
            )

    # Write metadata header
    meta = {
        "_meta": True,
        "comparison_name": config.name,
        "description": config.description,
        "started_at": datetime.now().isoformat(),
        "models": [m.name for m in config.models],
        "tasks": config.tasks,
        "max_steps": config.max_steps,
        "server_url": server_url,
    }
    with open(results_path, "a") as f:
        f.write(json.dumps(meta, default=str) + "\n")

    all_results = list(existing_results)
    total_runs = len(config.models) * len(config.tasks) * config.runs_per_config
    completed = len(completed_keys)

    logger.info(
        "Starting comparison: %d models x %d tasks x %d runs = %d total (%d remaining)",
        len(config.models),
        len(config.tasks),
        config.runs_per_config,
        total_runs,
        total_runs - completed,
    )

    for model_config in config.models:
        if _shutdown_requested:
            break

        logger.info("=" * 60)
        logger.info("MODEL: %s (%s, %s)", model_config.name, model_config.provider, model_config.type)
        logger.info("=" * 60)

        if model_config.type != "unified":
            logger.warning(
                "Skipping %s: only 'unified' type supported in Phase 1",
                model_config.name,
            )
            continue

        # Create agent for this model
        try:
            agent = create_unified_agent(model_config)
        except Exception as e:
            logger.error("Failed to create agent for %s: %s", model_config.name, e)
            for task_path in config.tasks:
                result = {
                    "model_name": model_config.name,
                    "model_type": model_config.type,
                    "model_provider": model_config.provider,
                    "task_path": task_path,
                    "score": 0.0,
                    "error": f"Agent creation failed: {e}",
                    "elapsed_seconds": 0.0,
                    "finished_at": datetime.now().isoformat(),
                }
                all_results.append(result)
                with open(results_path, "a") as f:
                    f.write(json.dumps(result, default=str) + "\n")
            continue

        for task_path in config.tasks:
            if _shutdown_requested:
                break

            for run_idx in range(config.runs_per_config):
                run_key = f"{model_config.name}::{task_path}"
                if run_key in completed_keys:
                    logger.info(
                        "Skipping %s on %s (already completed)", model_config.name, task_path
                    )
                    continue

                completed += 1
                logger.info(
                    "--- Run %d/%d: %s on %s (run %d) ---",
                    completed,
                    total_runs,
                    model_config.name,
                    task_path,
                    run_idx + 1,
                )

                # Reset agent state between tasks
                agent.reset()

                # Derive screenshot dir
                task_slug = Path(task_path).stem
                screenshots_dir = None
                if config.save_screenshots:
                    screenshots_dir = (
                        Path(config.output_dir)
                        / model_config.name
                        / task_slug
                        / "screenshots"
                    )

                # Run
                result = run_single_task(
                    task_path=task_path,
                    agent=agent,
                    server_url=server_url,
                    max_steps=config.max_steps,
                    screenshots_dir=screenshots_dir,
                )

                # Annotate with model info
                result["model_name"] = model_config.name
                result["model_type"] = model_config.type
                result["model_provider"] = model_config.provider
                result["run_index"] = run_idx

                all_results.append(result)

                # Write incrementally
                with open(results_path, "a") as f:
                    f.write(json.dumps(result, default=str) + "\n")

                # Log progress
                status = "PASS" if result.get("score", 0) > 0 else "FAIL"
                logger.info(
                    "  Result: %s (score=%.2f, steps=%d, time=%.1fs)",
                    status,
                    result.get("score", 0.0),
                    result.get("steps", 0),
                    result.get("elapsed_seconds", 0.0),
                )

    return [r for r in all_results if not r.get("_meta")]


# ---------------------------------------------------------------------------
# Summary and report generation
# ---------------------------------------------------------------------------


def build_summary(results: list[dict], config: ComparisonConfig) -> dict:
    """Build a summary JSON with score matrix.

    Args:
        results: List of result dicts from run_comparison.
        config: Comparison configuration.

    Returns:
        Summary dict with per-model, per-task scores and averages.
    """
    # Build score matrix: model_name -> task_path -> score
    matrix: dict[str, dict[str, float]] = {}
    steps_matrix: dict[str, dict[str, int]] = {}
    time_matrix: dict[str, dict[str, float]] = {}

    for r in results:
        model = r.get("model_name", "unknown")
        task = r.get("task_path", "unknown")
        if model not in matrix:
            matrix[model] = {}
            steps_matrix[model] = {}
            time_matrix[model] = {}
        matrix[model][task] = r.get("score", 0.0)
        steps_matrix[model][task] = r.get("steps", 0)
        time_matrix[model][task] = r.get("elapsed_seconds", 0.0)

    # Compute averages
    model_averages = {}
    for model, scores in matrix.items():
        vals = list(scores.values())
        model_averages[model] = {
            "avg_score": sum(vals) / len(vals) if vals else 0.0,
            "avg_steps": (
                sum(steps_matrix[model].values()) / len(vals) if vals else 0.0
            ),
            "avg_time": (
                sum(time_matrix[model].values()) / len(vals) if vals else 0.0
            ),
            "total_runs": len(vals),
        }

    return {
        "comparison_name": config.name,
        "description": config.description,
        "generated_at": datetime.now().isoformat(),
        "tasks": config.tasks,
        "models": [m.name for m in config.models],
        "score_matrix": matrix,
        "steps_matrix": steps_matrix,
        "time_matrix": time_matrix,
        "model_averages": model_averages,
    }


def print_summary_table(summary: dict) -> None:
    """Print a formatted comparison table to stdout.

    Args:
        summary: Summary dict from build_summary.
    """
    tasks = summary["tasks"]
    models = summary["models"]
    score_matrix = summary["score_matrix"]
    averages = summary["model_averages"]

    # Column widths
    task_labels = [Path(t).stem for t in tasks]
    model_col_w = max(len(m) for m in models) + 2
    task_col_w = max(max((len(t) for t in task_labels), default=6), 8)

    # Header
    print()
    print("=" * 70)
    print(f"COMPARISON: {summary['comparison_name']}")
    print(f"Tasks: {len(tasks)}  |  Models: {len(models)}")
    print("=" * 70)

    # Table header
    header = f"{'Model':<{model_col_w}}"
    for label in task_labels:
        header += f"  {label:>{task_col_w}}"
    header += f"  {'Avg':>6}  {'Steps':>5}  {'Time':>6}"
    print(header)
    print("-" * len(header))

    # Rows
    for model in models:
        row = f"{model:<{model_col_w}}"
        for task in tasks:
            score = score_matrix.get(model, {}).get(task, None)
            if score is not None:
                row += f"  {score:>{task_col_w}.2f}"
            else:
                row += f"  {'--':>{task_col_w}}"

        avg = averages.get(model, {})
        row += f"  {avg.get('avg_score', 0.0):>6.2f}"
        row += f"  {avg.get('avg_steps', 0.0):>5.1f}"
        row += f"  {avg.get('avg_time', 0.0):>5.1f}s"
        print(row)

    print("=" * 70)


def generate_html_report(
    summary: dict,
    results: list[dict],
    output_path: Path,
) -> Path:
    """Generate an HTML comparison report.

    Args:
        summary: Summary dict from build_summary.
        results: Full list of result dicts.
        output_path: Where to write the HTML file.

    Returns:
        Path to the generated HTML file.
    """
    tasks = summary["tasks"]
    models = summary["models"]
    score_matrix = summary["score_matrix"]
    averages = summary["model_averages"]
    task_labels = [Path(t).stem for t in tasks]

    # Build HTML
    rows_html = ""
    for model in models:
        cells = f"<td><strong>{html.escape(model)}</strong></td>"
        for task in tasks:
            score = score_matrix.get(model, {}).get(task, None)
            if score is not None:
                css = "pass" if score > 0 else "fail"
                cells += f'<td class="{css}">{score:.2f}</td>'
            else:
                cells += "<td>--</td>"

        avg = averages.get(model, {})
        cells += f"<td><strong>{avg.get('avg_score', 0.0):.2f}</strong></td>"
        cells += f"<td>{avg.get('avg_steps', 0.0):.1f}</td>"
        cells += f"<td>{avg.get('avg_time', 0.0):.1f}s</td>"
        rows_html += f"<tr>{cells}</tr>\n"

    task_headers = "".join(f"<th>{html.escape(t)}</th>" for t in task_labels)

    # Per-model detail sections
    details_html = ""
    for r in results:
        model = r.get("model_name", "?")
        task_name = r.get("task_name", r.get("task_path", "?"))
        score = r.get("score", 0.0)
        steps = r.get("steps", 0)
        elapsed = r.get("elapsed_seconds", 0.0)
        error = r.get("error", "")
        actions = r.get("actions", [])

        actions_list = ""
        for a in actions:
            actions_list += (
                f"<li>Step {a.get('step', '?')}: "
                f"{html.escape(str(a.get('type', '?')))} "
                f"({html.escape(str(a.get('text', '') or ''))})</li>\n"
            )

        css = "pass" if score > 0 else "fail"
        details_html += f"""
        <details>
            <summary class="{css}">
                <strong>{html.escape(model)}</strong> on
                <em>{html.escape(task_name)}</em>:
                score={score:.2f}, steps={steps}, time={elapsed:.1f}s
            </summary>
            <div class="detail-content">
                {"<p class='error'>Error: " + html.escape(error) + "</p>" if error else ""}
                <ul>{actions_list}</ul>
            </div>
        </details>"""

    report_html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>{html.escape(summary['comparison_name'])}</title>
    <style>
        body {{ font-family: -apple-system, sans-serif; max-width: 960px; margin: 2em auto; padding: 0 1em; }}
        h1 {{ border-bottom: 2px solid #333; padding-bottom: 0.5em; }}
        table {{ border-collapse: collapse; width: 100%; margin: 1em 0; }}
        th, td {{ border: 1px solid #ddd; padding: 8px 12px; text-align: center; }}
        th {{ background: #f5f5f5; }}
        .pass {{ background: #e6ffe6; }}
        .fail {{ background: #ffe6e6; }}
        details {{ margin: 0.5em 0; padding: 0.5em; border: 1px solid #eee; border-radius: 4px; }}
        summary {{ cursor: pointer; padding: 0.3em; }}
        summary.pass {{ color: #2a7a2a; }}
        summary.fail {{ color: #a33; }}
        .detail-content {{ padding: 0.5em 1em; }}
        .error {{ color: #a33; font-style: italic; }}
        .meta {{ color: #666; font-size: 0.9em; }}
    </style>
</head>
<body>
    <h1>{html.escape(summary['comparison_name'])}</h1>
    <p class="meta">{html.escape(summary.get('description', ''))}</p>
    <p class="meta">Generated: {summary['generated_at']}</p>

    <h2>Score Matrix</h2>
    <table>
        <thead>
            <tr>
                <th>Model</th>
                {task_headers}
                <th>Avg Score</th>
                <th>Avg Steps</th>
                <th>Avg Time</th>
            </tr>
        </thead>
        <tbody>
            {rows_html}
        </tbody>
    </table>

    <h2>Per-Run Details</h2>
    {details_html}
</body>
</html>"""

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report_html)
    logger.info("HTML report written to %s", output_path)
    return output_path


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Systematic model comparison for WAA tasks",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )

    parser.add_argument(
        "--config",
        required=True,
        help="Path to comparison YAML config file",
    )
    parser.add_argument(
        "--server-url",
        default=None,
        help="Override server URL from config (default: from YAML)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Skip (model, task) pairs already in results.jsonl",
    )

    # Infrastructure flags
    parser.add_argument(
        "--manage-vm",
        action="store_true",
        help="Start/stop WAA VM automatically (requires Azure CLI)",
    )
    parser.add_argument(
        "--vm-name",
        default="waa-pool-00",
        help="VM name for --manage-vm (default: waa-pool-00)",
    )
    parser.add_argument(
        "--resource-group",
        default="openadapt-agents",
        help="Azure resource group for --manage-vm",
    )
    parser.add_argument(
        "--setup-tunnels",
        action="store_true",
        help="Set up SSH tunnels to the VM",
    )
    parser.add_argument(
        "--no-deallocate",
        action="store_true",
        help="Do not deallocate the VM after comparison",
    )

    args = parser.parse_args()

    # Load config
    config = load_config(args.config)
    logger.info(
        "Loaded comparison config: %s (%d models, %d tasks)",
        config.name,
        len(config.models),
        len(config.tasks),
    )

    server_url = args.server_url or config.server_url
    vm_ip = None
    tunnel_pids: dict[str, int | None] = {}

    try:
        # Step 0: VM lifecycle (optional)
        if args.manage_vm:
            logger.info("Step 0: Starting VM %s...", args.vm_name)
            vm_ip = _manage_vm_lifecycle(args.vm_name, args.resource_group)
            if not vm_ip:
                logger.error("Failed to start VM")
                return 1

        # Step 1: SSH tunnels (optional)
        if args.setup_tunnels:
            if not vm_ip:
                from scripts.run_correction_flywheel import get_vm_ip

                vm_ip = get_vm_ip(args.vm_name, args.resource_group)
                if not vm_ip:
                    logger.error(
                        "Cannot set up tunnels: VM IP not found for %s",
                        args.vm_name,
                    )
                    return 1

            logger.info("Step 1: Setting up SSH tunnels to %s...", vm_ip)
            tunnel_pids = _setup_tunnels(vm_ip)

            # Wait for WAA
            if not _wait_for_waa(server_url):
                logger.error("WAA server not ready")
                return 1

        # Step 2: Run comparison
        logger.info("Step 2: Running comparison...")
        run_start = time.time()

        results = run_comparison(
            config,
            server_url_override=server_url,
            resume=args.resume,
        )

        total_elapsed = time.time() - run_start

        if not results:
            logger.warning("No results collected")
            return 1

        # Step 3: Generate outputs
        logger.info("Step 3: Generating outputs...")
        output_dir = Path(config.output_dir)

        summary = build_summary(results, config)

        # Save summary JSON
        summary_path = output_dir / "summary.json"
        with open(summary_path, "w") as f:
            json.dump(summary, f, indent=2, default=str)
        logger.info("Summary JSON: %s", summary_path)

        # Generate HTML report
        report_path = output_dir / "comparison_report.html"
        generate_html_report(summary, results, report_path)

        # Print table to stdout
        print_summary_table(summary)

        print(f"\nTotal time: {total_elapsed / 60:.1f} min")
        print(f"Results:    {output_dir / 'results.jsonl'}")
        print(f"Summary:    {summary_path}")
        print(f"Report:     {report_path}")

        return 0

    finally:
        # Cleanup: deallocate VM if we started it
        if args.manage_vm and not args.no_deallocate:
            from scripts.run_correction_flywheel import deallocate_vm

            logger.info("Cleanup: deallocating VM %s...", args.vm_name)
            deallocate_vm(args.vm_name, args.resource_group)


if __name__ == "__main__":
    sys.exit(main())
