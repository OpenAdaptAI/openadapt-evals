from __future__ import annotations

from benchmark.complex_visual.run_campaign import load_campaign, run_campaign


def test_campaign_has_required_visual_faults_and_control_flow() -> None:
    campaign = load_campaign()
    assert campaign["execution_boundary"] == "local_synthetic_only"
    assert campaign["pixel_only"] is True
    assert campaign["trials_per_condition"] >= 3
    assert {"branch: route by request priority", "loop: process each attachment"} <= set(
        campaign["workflow"]["control_flow"]
    )
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


def test_reference_runner_proves_effects_and_reports_safety_metrics(tmp_path) -> None:
    report = run_campaign(tmp_path)
    metrics = report["metrics"]
    assert len(report["results"]) == 27
    assert metrics["verified_outcomes"] == 12
    assert metrics["safe_halts"] == 15
    assert metrics["silent_incorrect_successes"] == 0
    assert metrics["over_halts"] == 0
    assert metrics["duplicate_effects"] == 0
    assert metrics["model_calls"] == 0
    commit = [item for item in report["results"] if item["condition"] == "commit_timeout"]
    assert all(item["outcome"] == "verified" and all(item["oracle"].values()) for item in commit)
