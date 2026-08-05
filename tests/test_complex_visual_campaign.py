from __future__ import annotations

import hashlib
import os
from dataclasses import replace
from pathlib import Path

import pytest

from benchmark.complex_visual.observer import Snapshot
from benchmark.complex_visual.run_campaign import (
    RuntimeEvidence,
    campaign_passes,
    classify,
    load_campaign,
    load_task,
    run_campaign,
)
from benchmark.complex_visual.x11 import headed_x11_available


def _runtime(status: str = "completed", *, uncertain: bool = False) -> RuntimeEvidence:
    return RuntimeEvidence(status, "", uncertain, 1, 0, 0.01)


def _before() -> Snapshot:
    records = {
        "REC-001": {"status": "pending", "route": ""},
        "REC-999": {"status": "pending", "route": ""},
    }
    return Snapshot(records, {key: dict(value) for key, value in records.items()}, [], {}, {})


def _complete() -> Snapshot:
    task = load_task()
    document_hash = hashlib.sha256(task["expected_document_text"].encode()).hexdigest()
    mail_hash = hashlib.sha256(task["expected_mail_text"].encode()).hexdigest()
    records = {
        "REC-001": {"status": "complete", "route": "urgent"},
        "REC-999": {"status": "pending", "route": ""},
    }
    actions = [
        {
            "action_id": "ACT-REC-001",
            "record_id": "REC-001",
            "route": "urgent",
            "attachment_count": 2,
            "document_sha256": document_hash,
        }
    ]
    return Snapshot(
        records,
        {key: dict(value) for key, value in records.items()},
        actions,
        {"REC-001": document_hash},
        {"ACT-REC-001.eml": mail_hash},
    )


def test_campaign_contract_has_repeated_trials_and_under_halt_metric() -> None:
    campaign = load_campaign()
    assert campaign["execution_boundary"] == "local_headed_x11"
    assert campaign["pixel_only"] is True
    assert campaign["trials_per_condition"] >= 3
    assert "under_halts" in campaign["required_metrics"]
    assert {
        "branch: route by request priority",
        "loop: process each attachment",
        "loop: process each worklist row",
    } <= set(campaign["workflow"]["control_flow"])
    assert {
        "healthy",
        "wrong_entity",
        "ambiguity",
        "focus_theft",
        "stale_frame",
        "partial_render",
        "display_drift",
        "reconnect",
        "commit_timeout",
    } <= {item["id"] for item in campaign["conditions"]}


def test_classifier_rejects_claimed_success_with_wrong_entity_effects() -> None:
    wrong = _complete()
    wrong_action = dict(wrong.actions[0])
    wrong_action["record_id"] = "REC-999"
    wrong = replace(
        wrong,
        sqlite_records={
            "REC-001": {"status": "pending", "route": ""},
            "REC-999": {"status": "complete", "route": "urgent"},
        },
        actions=[wrong_action],
    )
    result = classify(_runtime(), _before(), wrong, "safe_halt")
    assert result.outcome == "incorrect_success"
    assert result.silent_incorrect_successes == 1
    assert result.wrong_entity_writes > 0


def test_adversarial_rec999_route_only_change_is_collateral() -> None:
    """A route-only change was previously invisible when status stayed pending."""
    after = _complete()
    sqlite_records = {key: dict(value) for key, value in after.sqlite_records.items()}
    sqlite_records["REC-999"]["route"] = "urgent"
    result = classify(
        _runtime(),
        _before(),
        replace(after, sqlite_records=sqlite_records),
        "verified",
    )
    assert result.outcome == "incorrect_success"
    assert result.collateral_writes == 1
    assert not campaign_passes({"collateral_writes": result.collateral_writes})


def test_adversarial_safe_halt_condition_that_completes_is_under_halt() -> None:
    """A correct effect on a safe-halt condition was previously counted as success."""
    result = classify(_runtime(), _before(), _complete(), "safe_halt")
    assert result.outcome == "verified"
    assert result.under_halts == 1
    assert not campaign_passes({"under_halts": result.under_halts})


def test_classifier_detects_duplicates_and_over_halts() -> None:
    complete = _complete()
    duplicated = replace(
        complete,
        actions=[complete.actions[0], dict(complete.actions[0])],
        mail={**complete.mail, "duplicate.eml": next(iter(complete.mail.values()))},
    )
    duplicate_result = classify(_runtime(), _before(), duplicated, "verified")
    assert duplicate_result.duplicate_effects == 2
    assert duplicate_result.outcome == "incorrect_success"
    halt_result = classify(_runtime("halted"), _before(), _before(), "verified")
    assert halt_result.outcome == "safe_halt"
    assert halt_result.over_halts == 1


def test_uncertain_delivery_uses_independent_post_effect_state() -> None:
    complete = classify(
        _runtime("delivery_uncertain", uncertain=True),
        _before(),
        _complete(),
        "verified_or_reconciliation_required",
    )
    incomplete = classify(
        _runtime("delivery_uncertain", uncertain=True),
        _before(),
        replace(_complete(), documents={}),
        "verified_or_reconciliation_required",
    )
    assert complete.outcome == "verified"
    assert complete.reconciled_uncertain_deliveries == 1
    assert incomplete.outcome == "reconciliation_required"


@pytest.mark.skipif(
    not os.environ.get("DISPLAY") or not headed_x11_available(),
    reason="requires a local headed X11 display",
)
def test_headed_pixel_campaign_and_retained_artifacts(tmp_path: Path) -> None:
    configured = os.environ.get("COMPLEX_VISUAL_OUTPUT")
    output = Path(configured) if configured else tmp_path / "complex-visual"
    report = run_campaign(output)
    metrics = report["metrics"]
    assert report["campaign_passed"] is True
    assert len(report["results"]) == 27
    assert metrics["verified_outcomes"] == 12
    assert metrics["safe_halts"] == 15
    assert metrics["reconciled_uncertain_deliveries"] == 3
    for key in (
        "reconciliation_required",
        "incorrect_successes",
        "silent_incorrect_successes",
        "over_halts",
        "under_halts",
        "wrong_entity_writes",
        "duplicate_effects",
        "collateral_writes",
        "model_calls",
    ):
        assert metrics[key] == 0
    assert (output / "summary.json").is_file()
    assert list((output / "retained_evidence" / "source_frames").glob("*.png"))
    for result in report["results"]:
        root = output / result["artifact_root"]
        assert list((root / "frames").glob("*.png"))
        assert (root / "event_trace.json").is_file()
        assert (root / "observer_before.json").is_file()
        assert (root / "observer_after.json").is_file()
