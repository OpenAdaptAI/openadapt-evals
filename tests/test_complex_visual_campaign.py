from __future__ import annotations

from dataclasses import replace

from benchmark.complex_visual.observer import Observation
from benchmark.complex_visual.run_campaign import (
    RuntimeEvidence,
    classify,
    load_campaign,
    run_campaign,
)


def _runtime(status: str = "completed", *, uncertain: bool = False) -> RuntimeEvidence:
    return RuntimeEvidence(status, "", uncertain, 1, 0, 0.01)


def _complete_observation() -> Observation:
    return Observation(
        1,
        0,
        "complete",
        "pending",
        "complete",
        "pending",
        "urgent",
        "urgent",
        2,
        True,
        True,
        1,
        True,
        0,
        5,
    )


def test_campaign_has_required_visual_faults_and_control_flow() -> None:
    campaign = load_campaign()
    assert campaign["execution_boundary"] == "local_no_dom_pixel_fixture"
    assert campaign["pixel_only"] is True
    assert campaign["trials_per_condition"] >= 3
    assert {
        "branch: route by request priority",
        "loop: process each attachment",
        "loop: process each worklist row",
    } <= set(campaign["workflow"]["control_flow"])
    assert {"sqlite", "csv", "maildir", "document_sha256"} == set(
        campaign["workflow"]["independent_oracles"]
    )
    required = {
        "healthy",
        "wrong_entity",
        "ambiguity",
        "focus_theft",
        "stale_frame",
        "partial_render",
        "display_drift",
        "reconnect",
        "commit_timeout",
    }
    assert required <= {item["id"] for item in campaign["conditions"]}


def test_real_pixel_campaign_executes_all_trials_and_faults(tmp_path) -> None:
    report = run_campaign(tmp_path)
    metrics = report["metrics"]
    assert len(report["results"]) == 27
    assert metrics["verified_outcomes"] == 12
    assert metrics["safe_halts"] == 15
    assert metrics["reconciled_uncertain_deliveries"] == 3
    assert metrics["reconciliation_required"] == 0
    assert metrics["silent_incorrect_successes"] == 0
    assert metrics["over_halts"] == 0
    assert metrics["wrong_entity_writes"] == 0
    assert metrics["duplicate_effects"] == 0
    assert metrics["collateral_writes"] == 0
    assert metrics["model_calls"] == 0
    healthy = next(item for item in report["results"] if item["condition"] == "healthy")
    operations = {event["operation"] for event in healthy["interaction"]}
    windows = {event["active_window"] for event in healthy["interaction"]}
    assert {"capture", "move", "click", "type"} <= operations
    assert {"inbox", "worklist", "editor"} <= windows
    assert (
        sum(event.get("effect") == "attachment_processed" for event in healthy["interaction"]) == 2
    )
    assert sum(event.get("effect") == "row_processed" for event in healthy["interaction"]) == 2
    timeout = next(item for item in report["results"] if item["condition"] == "commit_timeout")
    uncertain_clicks = [
        event for event in timeout["interaction"] if event.get("reason") == "acknowledgement_lost"
    ]
    assert len(uncertain_clicks) == 1
    assert timeout["observation"]["target_action_count"] == 1
    by_condition = {item["condition"]: item for item in report["results"]}
    assert by_condition["wrong_entity"]["runtime"]["reason"] == "fresh_identity_mismatch"
    assert by_condition["ambiguity"]["runtime"]["reason"] == ("fresh_commit_missing_or_ambiguous")
    assert by_condition["focus_theft"]["runtime"]["reason"] == "fresh_frame_mismatch"
    assert by_condition["stale_frame"]["runtime"]["reason"] == "fresh_frame_mismatch"
    assert by_condition["partial_render"]["runtime"]["reason"] == (
        "fresh_commit_missing_or_ambiguous"
    )
    assert by_condition["display_drift"]["classification"]["outcome"] == "verified"
    assert by_condition["reconnect"]["runtime"]["reconnects"] == 1
    assert by_condition["commit_timeout"]["runtime"]["delivery_uncertain"] is True


def test_classifier_rejects_a_claimed_success_with_a_wrong_entity_write() -> None:
    observed = replace(
        _complete_observation(),
        target_action_count=0,
        wrong_entity_action_count=1,
        wrong_entity_status="complete",
    )
    result = classify(_runtime(), observed, "safe_halt")
    assert result.outcome == "incorrect_success"
    assert result.silent_incorrect_successes == 1
    assert result.wrong_entity_writes == 2


def test_classifier_detects_duplicates_and_collateral_writes() -> None:
    observed = replace(
        _complete_observation(), target_action_count=2, mail_count=2, collateral_write_count=1
    )
    result = classify(_runtime(), observed, "verified")
    assert result.outcome == "incorrect_success"
    assert result.duplicate_effects == 2
    assert result.collateral_writes == 1


def test_classifier_detects_an_over_halt() -> None:
    empty = Observation(
        0,
        0,
        "pending",
        "pending",
        "pending",
        "pending",
        "",
        "",
        0,
        False,
        False,
        0,
        0,
        False,
        0,
    )
    result = classify(_runtime("halted"), empty, "verified")
    assert result.outcome == "safe_halt"
    assert result.over_halts == 1


def test_uncertain_delivery_uses_observation_for_reconciliation() -> None:
    complete = classify(
        _runtime("delivery_uncertain", uncertain=True),
        _complete_observation(),
        "verified_or_reconciliation_required",
    )
    incomplete = classify(
        _runtime("delivery_uncertain", uncertain=True),
        replace(_complete_observation(), document_ok=False),
        "verified_or_reconciliation_required",
    )
    assert complete.outcome == "verified"
    assert complete.reconciled_uncertain_deliveries == 1
    assert incomplete.outcome == "reconciliation_required"
