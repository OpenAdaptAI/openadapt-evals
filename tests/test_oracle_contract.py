from __future__ import annotations

import copy
from types import SimpleNamespace

import pytest

from openadapt_evals.evaluation.oracle_contract import (
    OracleContractError,
    build_oracle_contract,
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
            "distribution": "observer",
            "version": "1.0.0",
            "module": "observer.ocr",
            "sha256": "b" * 64,
        },
        dependency_versions={"observer": "1.0.0"},
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
    observed = {field["name"]: field["expected"] for field in EXPECTED_FIELDS}
    verdict = evaluate_expected_fields(observed, EXPECTED_FIELDS, WRONG_ACTION_RULES)
    row_template = {
        "arm": "compiled",
        "condition": "clean",
        "reported_complete": True,
        "success": True,
        "primary_outcome": "correct",
        "silent_incorrect_success": False,
        "over_halt": False,
        **verdict.model_dump(exclude={"success"}),
    }
    rows = []
    for arm in ("compiled", "control"):
        for trial in (1, 2, 3):
            row = copy.deepcopy(row_template)
            row.update({"arm": arm, "trial": trial})
            rows.append(row)
    counted = {
        "n": 3,
        "task_success_count": 3,
        "reported_complete_count": 3,
        "silent_incorrect_success_count": 0,
        "wrong_action_count": 0,
        "over_halt_count": 0,
        "halt_or_error_count": 0,
        "oracle_indeterminate_count": 0,
        "failure_taxonomy": {"correct": 3},
    }
    document = {
        "schema_version": 2,
        "arms": ["compiled", "control"],
        "conditions": ["clean"],
        "trials_per_arm_condition": 3,
        "oracle": {"contract": contract},
        "runs": rows,
        "aggregate": {
            "compiled": {"clean": dict(counted)},
            "control": {"clean": dict(counted)},
        },
    }
    validate_evidence_document(document, repo_root=tmp_path)

    rows[0]["primary_outcome"] = "silent_incorrect_success"
    with pytest.raises(OracleContractError, match="primary_outcome"):
        validate_evidence_document(document, repo_root=tmp_path)
