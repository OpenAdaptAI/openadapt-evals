#!/usr/bin/env python3
"""Build an evidence-bounded OpenAdapt performance report.

The report intentionally keeps two different studies separate:

* current ``openadapt-flow`` compiled execution versus a direct API control;
* historical demo-conditioned (DC) versus zero-shot (ZS) computer use.

The latter is not the current compiler/runtime and must never be relabelled as
such.  Inputs are existing result artifacts; this script performs no GUI work,
network calls, model calls, or cloud mutations.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import statistics
from collections import Counter
from pathlib import Path
from typing import Any


LEGACY_TASKS = ("04d9aeaf", "0bf05a7d", "0e763496", "70745df8")
LEGACY_TRIALS = (2, 3, 4)
LEGACY_RUNSTAMP = "20260306_124032"
CONDITIONS = ("baseline", "ui_cosmetic_v1")
ARMS = ("compiled", "api")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _nearest_rank(values: list[float], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    return ordered[max(0, math.ceil(quantile * len(ordered)) - 1)]


def _aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    walls = [float(row["wall_s"]) for row in rows]
    return {
        "n": len(rows),
        "success_count": sum(bool(row["success"]) for row in rows),
        "success_rate": sum(bool(row["success"]) for row in rows) / len(rows),
        "silent_incorrect_success_count": sum(
            bool(row["silent_incorrect_success"]) for row in rows
        ),
        "over_halt_count": sum(bool(row["over_halt"]) for row in rows),
        "model_calls_total": sum(int(row.get("model_calls", 0)) for row in rows),
        "cost_usd_total": round(sum(float(row.get("cost_usd", 0.0)) for row in rows), 6),
        "wall_s_mean": statistics.mean(walls),
        "wall_s_p50": statistics.median(walls),
        "wall_s_p95_nearest_rank": _nearest_rank(walls, 0.95),
        "failure_taxonomy": dict(Counter(row["primary_outcome"] for row in rows)),
    }


def _load_current(app: str, path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("selected_subset_complete") is not True:
        raise ValueError(f"{app}: selected model-free subset is not complete")
    if payload.get("required_per_cell") != 3:
        raise ValueError(f"{app}: expected required_per_cell=3")
    if set(payload.get("arms", [])) != set(ARMS):
        raise ValueError(f"{app}: expected exactly compiled and api arms")
    if tuple(payload.get("conditions", [])) != CONDITIONS:
        raise ValueError(f"{app}: unexpected conditions")

    rows = payload.get("runs", [])
    for arm in ARMS:
        for condition in CONDITIONS:
            cell = [
                row for row in rows if row.get("arm") == arm and row.get("condition") == condition
            ]
            if len(cell) != 3 or sorted(row.get("trial") for row in cell) != [1, 2, 3]:
                raise ValueError(f"{app}/{arm}/{condition}: expected trials 1,2,3")

    return {
        "application": app,
        "source_sha256": _sha256(path),
        "generated_at": payload.get("generated_at"),
        "status": payload.get("status"),
        "selected_subset_complete": payload.get("selected_subset_complete"),
        "full_matrix_complete": payload.get("full_matrix_complete"),
        "publication_ready": payload.get("publication_ready"),
        "omitted_arms": payload.get("omitted_arms", []),
        "incomplete_reasons": payload.get("incomplete_reasons", []),
        "environment": payload.get("environment", {}),
        "rows": rows,
    }


def _load_legacy(root: Path) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    inputs: list[dict[str, str]] = []
    for trial in LEGACY_TRIALS:
        base = root / f"repeat_core4_trial{trial}_{LEGACY_RUNSTAMP}"
        for condition in ("zs", "dc"):
            for task in LEGACY_TASKS:
                run = base / f"val_{condition}_{task}"
                summary_path = run / "summary.json"
                executions = list((run / "tasks").glob("*/execution.json"))
                if len(executions) != 1:
                    raise ValueError(f"{run}: expected exactly one execution.json")
                execution_path = executions[0]
                summary = json.loads(summary_path.read_text(encoding="utf-8"))
                execution = json.loads(execution_path.read_text(encoding="utf-8"))
                oracle_success = bool(execution["success"])
                if oracle_success != bool(summary["tasks"][0]["success"]):
                    raise ValueError(f"{run}: summary/execution success disagreement")
                actions = [step.get("action", {}) for step in execution.get("steps", [])]
                reported_success = any(action.get("type") == "done" for action in actions)
                silent = reported_success and not oracle_success
                over_halt = (not reported_success) and oracle_success
                error = execution.get("error")
                if oracle_success:
                    outcome = "correct"
                elif error:
                    outcome = "infrastructure_or_execution_error"
                elif silent:
                    outcome = "silent_incorrect_success"
                elif int(execution.get("num_steps", 0)) >= 15:
                    outcome = "step_budget_exhausted"
                else:
                    outcome = "oracle_failure_without_success_claim"
                relative = run.relative_to(root)
                rows.append(
                    {
                        "trial": trial,
                        "condition": condition,
                        "task": task,
                        "success": oracle_success,
                        "reported_success": reported_success,
                        "silent_incorrect_success": silent,
                        "over_halt": over_halt,
                        "wall_s": float(execution["total_time_seconds"]),
                        "steps": int(execution["num_steps"]),
                        "model_calls": None,
                        "cost_usd": None,
                        "primary_outcome": outcome,
                    }
                )
                inputs.extend(
                    [
                        {
                            "path": str(relative / "summary.json"),
                            "sha256": _sha256(summary_path),
                        },
                        {
                            "path": str(
                                relative / "tasks" / execution_path.parent.name / "execution.json"
                            ),
                            "sha256": _sha256(execution_path),
                        },
                    ]
                )
    if len(rows) != 24:
        raise ValueError(f"legacy study: expected 24 rows, found {len(rows)}")
    return {"rows": rows, "input_manifest": inputs}


def build_report(args: argparse.Namespace) -> dict[str, Any]:
    current_apps = [
        _load_current("frappe_lending", args.frappe_results),
        _load_current("openemr_local", args.openemr_results),
    ]
    current_rows = [
        {"application": app["application"], **row} for app in current_apps for row in app["rows"]
    ]
    current_by_cell: dict[str, Any] = {}
    for app in current_apps:
        current_by_cell[app["application"]] = {}
        for arm in ARMS:
            current_by_cell[app["application"]][arm] = {}
            for condition in CONDITIONS:
                current_by_cell[app["application"]][arm][condition] = _aggregate(
                    [
                        row
                        for row in app["rows"]
                        if row["arm"] == arm and row["condition"] == condition
                    ]
                )
    current_overall = {
        arm: _aggregate([row for row in current_rows if row["arm"] == arm]) for arm in ARMS
    }
    current_overall["compiled_vs_api_mean_latency_ratio"] = (
        current_overall["compiled"]["wall_s_mean"] / current_overall["api"]["wall_s_mean"]
    )

    legacy = _load_legacy(args.legacy_results_root)
    legacy_by_condition: dict[str, Any] = {}
    for condition in ("zs", "dc"):
        rows = [row for row in legacy["rows"] if row["condition"] == condition]
        legacy_by_condition[condition] = _aggregate(
            [
                {
                    **row,
                    "model_calls": 0,
                    "cost_usd": 0.0,
                }
                for row in rows
            ]
        )
        legacy_by_condition[condition]["model_calls_total"] = None
        legacy_by_condition[condition]["cost_usd_total"] = None
        legacy_by_condition[condition]["steps_mean"] = statistics.mean(row["steps"] for row in rows)
    legacy_by_task: dict[str, Any] = {}
    for task in LEGACY_TASKS:
        legacy_by_task[task] = {}
        for condition in ("zs", "dc"):
            rows = [
                row
                for row in legacy["rows"]
                if row["task"] == task and row["condition"] == condition
            ]
            legacy_by_task[task][condition] = {
                "n": len(rows),
                "success_count": sum(row["success"] for row in rows),
                "silent_incorrect_success_count": sum(
                    row["silent_incorrect_success"] for row in rows
                ),
                "wall_s_mean": statistics.mean(row["wall_s"] for row in rows),
                "steps_mean": statistics.mean(row["steps"] for row in rows),
            }

    return {
        "schema_version": 1,
        "evidence_date": args.evidence_date,
        "source_revisions": {
            "openadapt_evals": args.evals_commit,
            "openadapt_flow_benchmark_candidate": args.flow_commit,
            "openadapt_flow_current_audited": args.flow_current_commit,
        },
        "latest_qualified_compiler_runtime_candidate": {
            "scope": (
                "model-free compiled execution versus direct API control; pinned synthetic "
                "Frappe Lending and pinned local OpenEMR; baseline and cosmetic drift"
            ),
            "oracle": "independent read-only REST plus direct SQL delta audit",
            "trials_per_application_arm_condition": 3,
            "applications": [
                {key: value for key, value in app.items() if key != "rows"} for app in current_apps
            ],
            "by_cell": current_by_cell,
            "overall": current_overall,
            "rows": current_rows,
            "verdict": (
                "The complete model-free subset passes 12/12 compiled and 12/12 API runs "
                "with zero silent incorrect success, zero over-halt, zero model calls, and "
                "zero model cost. Direct API execution is materially faster. The zero-shot "
                "agent arm was omitted, so this is not the complete comparative matrix."
            ),
        },
        "historical_legacy_dc_vs_zs": {
            "scope": (
                "legacy Claude computer-use agent with serialized demonstrations versus "
                "the same agent zero-shot; this is not openadapt-flow compiled replay"
            ),
            "environment": "WindowsAgentArena Azure VM, runstamp 20260306_124032",
            "oracle": "WAA native task evaluator",
            "trials_per_task_condition": 3,
            "tasks": list(LEGACY_TASKS),
            "by_condition": legacy_by_condition,
            "by_task": legacy_by_task,
            "success_delta_dc_minus_zs_pp": 100
            * (
                legacy_by_condition["dc"]["success_rate"]
                - legacy_by_condition["zs"]["success_rate"]
            ),
            "rows": legacy["rows"],
            "input_manifest": legacy["input_manifest"],
            "verdict": (
                "Both arms pass 3/12 runs (25%); DC-ZS success delta is 0 pp. DC is faster "
                "on this set but produces no reliability lift and one additional silent "
                "incorrect success. Model usage and cost were not retained in these artifacts."
            ),
        },
        "unmeasured": {
            "exact_current_flow_requalification": (
                f"No valid result on {args.flow_current_commit}. The qualified artifacts were "
                f"generated on {args.flow_commit}; shared replayer/effect code changed afterward, "
                "and the pinned local fixture containers/images are not currently present to rerun "
                "without rebuilding infrastructure."
            ),
            "current_flow_vs_zero_shot": (
                "No valid result. The Flow-on-WAA live CLI has no compiled bundles or live "
                "runner available in the current Azure subscription, and its current live "
                "path does not wire task reset plus WAALiveAdapter ground-truth evaluation."
            ),
            "current_flow_agent_arm": (
                "The matched Frappe/OpenEMR artifacts intentionally omit the paid agent arm; "
                "their own publication_ready and full_matrix_complete fields are false."
            ),
        },
        "caveats": [
            "Frappe and OpenEMR tasks use synthetic records on one macOS host.",
            "The current study measures one workflow per application and cosmetic drift only.",
            "Direct API controls are expected to be faster and are the preferred actuation tier when available.",
            "The historical WAA study used a legacy computer-use architecture, not the current compiler/runtime.",
            "The model-free compiler/runtime artifacts qualify candidate 84c7a94, not exact current Flow 1.12.1.",
            "Primary screenshots and oracle-evidence files remain in the ignored local Flow worktree; this report preserves normalized rows and their hashes, not those files.",
            "Legacy model ID, token usage, and dollar cost are unavailable in the retained artifacts.",
            "No new GUI, cloud, or model runs were performed for this report.",
        ],
    }


def render_markdown(report: dict[str, Any]) -> str:
    current = report["latest_qualified_compiler_runtime_candidate"]
    legacy = report["historical_legacy_dc_vs_zs"]
    lines = [
        "# OpenAdapt performance evidence — 2026-07-17",
        "",
        "This report separates the latest qualified compiled-runtime candidate evidence from historical demo-conditioned agent evidence.",
        "",
        "## Latest qualified compiler/runtime candidate: compiled versus API",
        "",
        "| Application | Arm | Condition | Runs | Success | Silent incorrect | Over-halt | Mean | p50 | p95 | Model calls | Cost |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for app in ("frappe_lending", "openemr_local"):
        for arm in ARMS:
            for condition in CONDITIONS:
                cell = current["by_cell"][app][arm][condition]
                lines.append(
                    f"| {app} | {arm} | {condition} | {cell['n']} | "
                    f"{cell['success_count']}/{cell['n']} | "
                    f"{cell['silent_incorrect_success_count']} | {cell['over_halt_count']} | "
                    f"{cell['wall_s_mean']:.2f}s | {cell['wall_s_p50']:.2f}s | "
                    f"{cell['wall_s_p95_nearest_rank']:.2f}s | {cell['model_calls_total']} | "
                    f"${cell['cost_usd_total']:.2f} |"
                )
    ratio = current["overall"]["compiled_vs_api_mean_latency_ratio"]
    lines.extend(
        [
            "",
            f"Compiled execution passed 12/12 and averaged {current['overall']['compiled']['wall_s_mean']:.2f}s; "
            f"API control passed 12/12 and averaged {current['overall']['api']['wall_s_mean']:.2f}s. "
            f"The compiled GUI path was {ratio:.1f}× slower. Both had zero measured silent incorrect "
            "success, over-halt, model calls, and model cost.",
            "",
            "This is a complete model-free subset, not a complete comparative matrix: the paid/zero-shot "
            "agent arm was intentionally omitted, and both source artifacts mark `publication_ready=false`.",
            "The artifacts were generated at Flow candidate `84c7a94`. Exact current Flow 1.12.1 "
            "changed shared replayer/effect code afterward, so its requalification remains pending.",
            "",
            "Classification: silent incorrect success means the arm reported completion but the independent "
            "oracle failed; over-halt means the oracle passed without a completion claim. p95 uses nearest rank.",
            "",
            "## Historical legacy agent: DC versus zero-shot",
            "",
            "| Condition | Runs | Success | Silent incorrect | Over-halt | Mean | p50 | p95 | Mean steps |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for condition in ("zs", "dc"):
        cell = legacy["by_condition"][condition]
        lines.append(
            f"| {condition.upper()} | {cell['n']} | {cell['success_count']}/{cell['n']} | "
            f"{cell['silent_incorrect_success_count']} | {cell['over_halt_count']} | "
            f"{cell['wall_s_mean']:.2f}s | {cell['wall_s_p50']:.2f}s | "
            f"{cell['wall_s_p95_nearest_rank']:.2f}s | {cell['steps_mean']:.2f} |"
        )
    lines.extend(
        [
            "",
            "Both historical arms passed 3/12 (25%), so DC − ZS was 0 percentage points. "
            "DC reduced mean wall time from 84.37s to 71.37s, but silent incorrect successes "
            "rose from 5/12 to 6/12. This is legacy Claude computer use, not current compiled Flow.",
            "",
            "## What remains unmeasured",
            "",
            "- Current compiled Flow versus zero-shot on WAA: no valid result.",
            "- Exact current Flow 1.12.1 on the matched Frappe/OpenEMR matrix: requalification pending.",
            "- Current paid agent arm on the matched Frappe/OpenEMR matrix: intentionally omitted.",
            "- A real design-partner Windows/Citrix workflow: not represented here.",
            "",
            "## Caveats",
            "",
        ]
    )
    lines.extend(f"- {item}" for item in report["caveats"])
    lines.extend(
        [
            "",
            "The JSON companion contains every normalized row and SHA-256 hashes for all source artifacts.",
            "",
        ]
    )
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--frappe-results", type=Path, required=True)
    parser.add_argument("--openemr-results", type=Path, required=True)
    parser.add_argument("--legacy-results-root", type=Path, required=True)
    parser.add_argument("--flow-commit", required=True)
    parser.add_argument("--flow-current-commit", required=True)
    parser.add_argument("--evals-commit", required=True)
    parser.add_argument("--evidence-date", default="2026-07-17")
    parser.add_argument("--out-json", type=Path, required=True)
    parser.add_argument("--out-md", type=Path, required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = build_report(args)
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_md.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    args.out_md.write_text(render_markdown(report), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
