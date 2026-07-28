from __future__ import annotations

import copy
from types import SimpleNamespace

import pytest

from openadapt_evals.evaluation.oracle_contract import (
    OracleContractError,
    build_oracle_contract,
    canonical_sha256,
    classify_outcome,
    evaluate_expected_fields,
    validate_evidence_document,
    validate_oracle_contract,
)
from openadapt_evals.evaluation.synthetic_mockmed_oracle import (
    EXPECTED_FIELDS,
    WRONG_ACTION_RULES,
    verify_final_state,
)


def _lines(*text: str):
    return [SimpleNamespace(text=item) for item in text]


def test_mockmed_oracle_keeps_each_expected_field_separate() -> None:
    note = "Follow-up in two weeks [A00]"
    verdict = verify_final_state(
        b"png",
        note,
        ocr_fn=lambda _png: _lines(
            f"Encounter saved - {note}",
            f"Triage - {note}",
            "Jane Sample",
        ),
    )

    assert verdict.success is True
    assert [field["name"] for field in verdict.field_results] == [
        "saved_banner",
        "saved_triage_note",
        "right_patient",
        "wrong_type_absent",
    ]
    assert all(field["passed"] is True for field in verdict.field_results)


def test_wrong_patient_and_oracle_failure_never_become_success() -> None:
    note = "Follow-up in two weeks [A00]"
    wrong_patient = verify_final_state(
        b"png",
        note,
        ocr_fn=lambda _png: _lines(
            f"Encounter saved - {note}",
            f"Triage - {note}",
            "John Sample",
        ),
    )
    unavailable = verify_final_state(
        b"png",
        note,
        ocr_fn=lambda _png: (_ for _ in ()).throw(RuntimeError("offline")),
    )

    assert wrong_patient.status == "refuted"
    assert wrong_patient.wrong_action is True
    assert unavailable.status == "unavailable"
    assert unavailable.success is False


@pytest.mark.parametrize(
    ("reported", "oracle_status", "wrong_action", "expected"),
    [
        (True, "confirmed", False, "correct"),
        (True, "refuted", True, "silent_incorrect_success"),
        (False, "confirmed", False, "over_halt"),
        (False, "refuted", True, "wrong_action_after_halt_or_error"),
        (True, "unavailable", False, "oracle_indeterminate"),
    ],
)
def test_failure_taxonomy_uses_actor_and_oracle_as_separate_signals(
    reported: bool,
    oracle_status: str,
    wrong_action: bool,
    expected: str,
) -> None:
    assert (
        classify_outcome(
            actor_reported_complete=reported,
            oracle_status=oracle_status,
            wrong_action=wrong_action,
        )
        == expected
    )


def _contract(tmp_path):
    verifier = tmp_path / "verifier.py"
    runner = tmp_path / "runner.py"
    verifier.write_text("def verify():\n    return True\n", encoding="utf-8")
    runner.write_text("def run():\n    return None\n", encoding="utf-8")
    contract = build_oracle_contract(
        repo_root=tmp_path,
        verifier_file=verifier,
        runner_file=runner,
        evals_commit="a" * 40,
        arms=["compiled", "control"],
        expected_fields=EXPECTED_FIELDS,
        wrong_action_rules=WRONG_ACTION_RULES,
        observation_provider={
            "distribution": "openadapt-flow",
            "version": "1.0.0",
            "module": "observer.ocr",
            "path_in_artifact": "observer/ocr.py",
            "sha256": "b" * 64,
            "artifact_sha256": "c" * 64,
        },
        dependency_versions={
            "observer": f"observer==1.0.0;module_sha256={'d' * 64}",
            "playwright": f"playwright==1.55.0;module_sha256={'8' * 64}",
        },
    )
    return contract, verifier


def test_verifier_change_invalidates_evidence(tmp_path) -> None:
    contract, verifier = _contract(tmp_path)
    validate_oracle_contract(
        contract,
        repo_root=tmp_path,
        arms=["compiled", "control"],
    )

    verifier.write_text("def verify():\n    return False\n", encoding="utf-8")

    with pytest.raises(OracleContractError, match="verifier binding changed"):
        validate_oracle_contract(
            contract,
            repo_root=tmp_path,
            arms=["compiled", "control"],
        )


def test_retained_result_is_recomputed_from_field_evidence(tmp_path) -> None:
    contract, _verifier = _contract(tmp_path)
    document = _valid_document(contract)
    validate_evidence_document(document, repo_root=tmp_path)

    document["runs"][0]["primary_outcome"] = "silent_incorrect_success"
    with pytest.raises(OracleContractError, match="primary_outcome"):
        validate_evidence_document(document, repo_root=tmp_path)


def test_observation_provider_requires_exact_artifact_identity(tmp_path) -> None:
    contract, _verifier = _contract(tmp_path)
    del contract["bindings"]["observation_provider"]["path_in_artifact"]
    contract["contract_sha256"] = canonical_sha256(
        {key: value for key, value in contract.items() if key != "contract_sha256"}
    )

    with pytest.raises(OracleContractError, match="path_in_artifact"):
        validate_oracle_contract(contract, repo_root=tmp_path, arms=["compiled", "control"])


def test_dependency_binding_cannot_use_a_floating_version(tmp_path) -> None:
    contract, _verifier = _contract(tmp_path)
    contract["bindings"]["dependency_versions"] = {"observer": "latest"}
    contract["bindings"]["dependency_versions_sha256"] = canonical_sha256(
        contract["bindings"]["dependency_versions"]
    )
    contract["contract_sha256"] = canonical_sha256(
        {key: value for key, value in contract.items() if key != "contract_sha256"}
    )

    with pytest.raises(OracleContractError, match="exact distribution"):
        validate_oracle_contract(contract, repo_root=tmp_path, arms=["compiled", "control"])


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("task_success_rate", 0.0),
        ("steady_wall_s_median", 999.0),
        ("model_calls_total", 999),
        ("model_cost_usd_total", 999.0),
    ],
)
def test_public_aggregate_claims_are_recomputed(tmp_path, field: str, value: object) -> None:
    contract, _verifier = _contract(tmp_path)
    document = _valid_document(contract)
    document["aggregate"]["compiled"]["clean"][field] = value

    with pytest.raises(OracleContractError, match="aggregate does not match"):
        validate_evidence_document(document, repo_root=tmp_path)


def test_result_types_and_source_bindings_are_exact(tmp_path) -> None:
    contract, _verifier = _contract(tmp_path)
    document = _valid_document(contract)
    document["runs"][0]["wrong_action"] = 0
    with pytest.raises(OracleContractError, match="wrong_action must be a boolean"):
        validate_evidence_document(document, repo_root=tmp_path)

    document = _valid_document(contract)
    document["source"]["runner_sha256"] = "0" * 64
    with pytest.raises(OracleContractError, match="runner does not match"):
        validate_evidence_document(document, repo_root=tmp_path)


def _valid_document(contract):
    observed = {field["name"]: field["expected"] for field in EXPECTED_FIELDS}
    verdict = evaluate_expected_fields(observed, EXPECTED_FIELDS, WRONG_ACTION_RULES)
    row_template = {
        "condition": "clean",
        "reported_complete": True,
        "success": True,
        "primary_outcome": "correct",
        "silent_incorrect_success": False,
        "over_halt": False,
        "steady_wall_s": 1.0,
        "end_to_end_wall_s": 2.0,
        "api_calls": 0,
        "cost_usd": 0.0,
        "note_sha256": "e" * 64,
        "final_screenshot_sha256": "f" * 64,
        "oracle_error_type": None,
        **verdict.model_dump(exclude={"success"}),
    }
    rows = []
    for arm in ("compiled", "control"):
        for trial in (1, 2, 3):
            rows.append({**copy.deepcopy(row_template), "arm": arm, "trial": trial})
    counted = {
        "n": 3,
        "task_success_count": 3,
        "task_success_rate": 1.0,
        "reported_complete_count": 3,
        "silent_incorrect_success_count": 0,
        "wrong_action_count": 0,
        "over_halt_count": 0,
        "halt_or_error_count": 0,
        "oracle_indeterminate_count": 0,
        "failure_taxonomy": {"correct": 3},
        "steady_wall_s_median": 1.0,
        "steady_wall_s_p95_nearest_rank": 1.0,
        "end_to_end_wall_s_median": 2.0,
        "end_to_end_wall_s_p95_nearest_rank": 2.0,
        "browser_oracle_teardown_overhead_s_median": 1.0,
        "model_calls_total": 0,
        "model_cost_usd_total": 0.0,
    }
    return {
        "schema_version": 2,
        "arms": ["compiled", "control"],
        "conditions": ["clean"],
        "trials_per_arm_condition": 3,
        "oracle": {"contract": contract},
        "source": {
            "evals": {"commit": "a" * 40, "tracked_clean": True},
            "runner_sha256": contract["bindings"]["runner"]["sha256"],
            "flow": {
                "commit": "b" * 40,
                "tags": ["v1.0.0"],
                "tracked_clean": True,
                "version": "1.0.0",
                "release_tag": "v1.0.0",
                "artifact": {
                    "filename": "openadapt_flow-1.0.0-py3-none-any.whl",
                    "sha256": "c" * 64,
                    "import_mode": "locally extracted published wheel",
                },
            },
        },
        "environment": {
            "platform": "test-platform",
            "python": "3.12.0",
            "playwright": "1.55.0",
            "chromium": {"version": "Chromium 140", "executable_sha256": "9" * 64},
        },
        "runs": rows,
        "aggregate": {
            "compiled": {"clean": dict(counted)},
            "control": {"clean": dict(counted)},
        },
    }
