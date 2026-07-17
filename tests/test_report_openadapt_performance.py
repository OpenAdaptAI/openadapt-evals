from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts.report_openadapt_performance import (
    CONDITIONS,
    LEGACY_RUNSTAMP,
    LEGACY_TASKS,
    LEGACY_TRIALS,
    _load_current,
    build_report,
)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def _current_payload() -> dict:
    runs = []
    for arm in ("compiled", "api"):
        for condition in CONDITIONS:
            for trial in (1, 2, 3):
                runs.append(
                    {
                        "arm": arm,
                        "condition": condition,
                        "trial": trial,
                        "success": True,
                        "silent_incorrect_success": False,
                        "over_halt": False,
                        "wall_s": float(trial),
                        "model_calls": 0,
                        "cost_usd": 0.0,
                        "primary_outcome": "correct",
                    }
                )
    return {
        "selected_subset_complete": True,
        "required_per_cell": 3,
        "arms": ["compiled", "api"],
        "conditions": list(CONDITIONS),
        "runs": runs,
        "full_matrix_complete": False,
        "publication_ready": False,
        "omitted_arms": ["agent"],
        "incomplete_reasons": ["agent omitted"],
        "status": "model_free_subset_complete",
        "environment": {},
    }


def _legacy_tree(root: Path) -> None:
    for trial in LEGACY_TRIALS:
        for condition in ("zs", "dc"):
            for task in LEGACY_TASKS:
                run = (
                    root
                    / f"repeat_core4_trial{trial}_{LEGACY_RUNSTAMP}"
                    / f"val_{condition}_{task}"
                )
                success = task == "0e763496"
                summary = {"tasks": [{"success": success}]}
                execution = {
                    "success": success,
                    "error": None,
                    "num_steps": 3,
                    "total_time_seconds": 2.0,
                    "steps": [{"action": {"type": "done"}}],
                }
                _write_json(run / "summary.json", summary)
                _write_json(run / "tasks" / f"{task}-WOS" / "execution.json", execution)


def test_build_report_keeps_current_and_legacy_evidence_separate(tmp_path: Path) -> None:
    frappe = tmp_path / "frappe.json"
    openemr = tmp_path / "openemr.json"
    _write_json(frappe, _current_payload())
    _write_json(openemr, _current_payload())
    legacy = tmp_path / "legacy"
    _legacy_tree(legacy)

    report = build_report(
        SimpleNamespace(
            frappe_results=frappe,
            openemr_results=openemr,
            legacy_results_root=legacy,
            flow_commit="flow-sha",
            flow_current_commit="flow-current-sha",
            evals_commit="evals-sha",
            evidence_date="2026-07-17",
        )
    )

    current = report["latest_qualified_compiler_runtime_candidate"]
    historical = report["historical_legacy_dc_vs_zs"]
    assert current["overall"]["compiled"]["n"] == 12
    assert current["overall"]["compiled"]["success_count"] == 12
    assert historical["by_condition"]["zs"]["n"] == 12
    assert historical["by_condition"]["dc"]["success_count"] == 3
    assert "not openadapt-flow compiled replay" in historical["scope"]
    assert report["unmeasured"]["current_flow_vs_zero_shot"].startswith("No valid result")


def test_current_loader_rejects_incomplete_three_trial_cell(tmp_path: Path) -> None:
    payload = _current_payload()
    payload["runs"].pop()
    path = tmp_path / "incomplete.json"
    _write_json(path, payload)

    with pytest.raises(ValueError, match="expected trials 1,2,3"):
        _load_current("fixture", path)
