from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
LEGACY_REFUSAL = WORKFLOWS / "import-production-acceptance.yml"


def test_no_evals_workflow_can_accept_a_private_payload() -> None:
    """Keep the legacy importer unreachable until the public cutover removes it."""

    forbidden_public_inputs = {
        "private_export_contract:",
        "--private-export-contract",
        "--campaign /",
        "--qualification-admission /",
    }
    for workflow in WORKFLOWS.glob("*.yml"):
        if workflow == LEGACY_REFUSAL:
            continue
        text = workflow.read_text(encoding="utf-8")
        for token in forbidden_public_inputs:
            assert token not in text, f"{workflow.name} accepts private input via {token!r}"

    legacy = LEGACY_REFUSAL.read_text(encoding="utf-8")
    assert "Staging private evidence is not implemented, and the import gate is closed." in legacy
    assert "if python scripts/import_production_acceptance.py" in legacy
    assert "--certificate /nonexistent/certificate.json" in legacy
    assert "--campaign /nonexistent/campaign.json" in legacy
    assert "--qualification-admission /nonexistent/admission.json" in legacy
    assert "--attestation-bundle /nonexistent/bundle.jsonl" in legacy
    assert "the importer produced a result while the gate is closed" in legacy
    assert 'test ! -e "${RUNNER_TEMP}/derived.json"' in legacy
    assert "actions/upload-artifact" not in legacy
