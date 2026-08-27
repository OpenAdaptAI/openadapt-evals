from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from openadapt_evals.infrastructure.pool import (
    PoolRunResult,
    validate_terminal_pool_result,
)


def _sha(label: str) -> str:
    return "sha256:" + hashlib.sha256(label.encode()).hexdigest()


def test_terminal_receipt_schema_bytes_match_the_frozen_central_schema() -> None:
    path = (
        Path(__file__).parents[1]
        / "openadapt_evals/schemas/qualification-worker-terminal-receipt.schema.json"
    )
    assert hashlib.sha256(path.read_bytes()).hexdigest() == (
        "81779a9cf670dc4bf02276bc51a0e06879e73ca2dd816a48bcf4b84f91ea70c2"
    )


def _central_schema() -> dict[str, object]:
    path = (
        Path(__file__).parents[1]
        / "openadapt_evals/schemas/qualification-worker-terminal-receipt.schema.json"
    )
    return json.loads(path.read_text(encoding="utf-8"))


def _central_terminal_receipt() -> dict[str, object]:
    return {
        "schema_version": "openadapt.qualification-worker-terminal-receipt/v1",
        "receipt_id_sha256": _sha("receipt"),
        "worker_admission_sha256": _sha("admission"),
        "dispatch_id_sha256": _sha("dispatch"),
        "provider_identity_sha256": _sha("provider"),
        "worker_identity_sha256": _sha("worker"),
        "live_provider_observation_sha256": _sha("observation"),
        "admitted_runtime_sha256": _sha("runtime"),
        "run_id": "123",
        "run_attempt": "1",
        "start_id_sha256": _sha("start"),
        "task_id_sha256": _sha("task"),
        "task_condition_sha256": _sha("condition"),
        "capability_handle_sha256": _sha("capability"),
        "launch_attempt": {
            "attempted_at": "2026-08-27T12:00:00Z",
            "host_identity_sha256": _sha("host"),
            "executable_sha256": _sha("executable"),
            "capability_handle_sha256": _sha("capability"),
            "evidence_sha256": _sha("launch-evidence"),
            "child_created": True,
            "failure_classification": None,
        },
        "launch_attempt_sha256": _sha("launch-attempt"),
        "process": {
            "pid": 101,
            "process_group_id": 101,
            "process_start_ticks": "9001",
            "launched_at": "2026-08-27T12:00:01Z",
            "executable_sha256": _sha("executable"),
            "process_start_identity_sha256": _sha("process-start"),
        },
        "oracle_sha256": _sha("oracle"),
        "result_sha256": _sha("result"),
        "log_sha256": _sha("log"),
        "burned_identities_sha256": _sha("burned-identities"),
        "burn_ledger_revision": 7,
        "burn_receipt_sha256": _sha("burn-receipt"),
        "burned_at": "2026-08-27T12:00:00Z",
        "ledger_readback_sha256": _sha("ledger-readback"),
        "effect_started": True,
        "delivery_state": "verified",
        "terminal_state": "VERIFIED",
        "exit_code": 0,
        "uncertainty_sha256": None,
        "quarantine": {
            "active": False,
            "reason_code": None,
            "evidence_sha256": None,
        },
        "completed_at": "2026-08-27T12:01:00Z",
        "issuer": {
            "repository": "OpenAdaptAI/.github",
            "repository_id": "858454062",
            "repository_owner_id": "132681217",
            "workflow": ".github/workflows/issue-qualification-worker-terminal-receipt.yml",
            "ref": "refs/heads/main",
            "source_commit": "c" * 40,
            "environment": "qualification-worker-terminal-receipt",
        },
    }


def test_central_schema_requires_kernel_start_ticks_after_launch() -> None:
    receipt = _central_terminal_receipt()
    Draft202012Validator(_central_schema()).validate(receipt)
    process = receipt["process"]
    assert isinstance(process, dict)
    del process["process_start_ticks"]
    with pytest.raises(ValidationError, match="process_start_ticks"):
        Draft202012Validator(_central_schema()).validate(receipt)


def test_central_schema_bounds_no_process_to_prelaunch_quarantine() -> None:
    receipt = _central_terminal_receipt()
    receipt.update(
        process=None,
        effect_started=False,
        delivery_state="not_started",
        terminal_state="PRELAUNCH_QUARANTINED",
        exit_code=None,
        quarantine={
            "active": True,
            "reason_code": "PROCESS_START_FAILED",
            "evidence_sha256": _sha("prelaunch-failure"),
        },
    )
    launch_attempt = receipt["launch_attempt"]
    assert isinstance(launch_attempt, dict)
    launch_attempt.update(
        child_created=False,
        failure_classification="PROCESS_START_FAILED",
    )
    validator = Draft202012Validator(_central_schema())
    validator.validate(receipt)

    invalid = deepcopy(receipt)
    invalid["terminal_state"] = "QUARANTINED"
    with pytest.raises(ValidationError):
        validator.validate(invalid)


def test_central_schema_refuses_a_false_postlaunch_process_absence() -> None:
    receipt = _central_terminal_receipt()
    receipt["process"] = None
    with pytest.raises(ValidationError):
        Draft202012Validator(_central_schema()).validate(receipt)


def _receipt(worker: str, state: str = "VERIFIED") -> dict[str, object]:
    return {
        "receipt_id_sha256": _sha(f"receipt:{worker}"),
        "dispatch_id_sha256": _sha(f"dispatch:{worker}"),
        "task_id_sha256": _sha(f"task:{worker}"),
        "terminal_state": state,
    }


def _result(*, second_state: str = "SAFE_HALT") -> PoolRunResult:
    first = _receipt("worker-1")
    second = _receipt("worker-2", second_state)
    second_complete = int(second_state == "VERIFIED")
    return PoolRunResult(
        total_tasks=2,
        completed=1 + second_complete,
        failed=1 - second_complete,
        elapsed_seconds=5.0,
        worker_results=[
            ("worker-1", 1, 0, None),
            (
                "worker-2",
                second_complete,
                1 - second_complete,
                None if second_complete else f"central terminal state {second_state}",
            ),
        ],
        terminal_receipts=(first, second),
    )


def _validate(result: PoolRunResult) -> PoolRunResult:
    return validate_terminal_pool_result(
        result,
        expected_dispatches={
            "worker-1": _sha("dispatch:worker-1"),
            "worker-2": _sha("dispatch:worker-2"),
        },
    )


def test_terminal_pool_accounting_is_closed_by_central_receipts() -> None:
    result = _validate(_result())
    assert result.total_tasks == 2
    assert result.completed == 1
    assert result.failed == 1
    assert result.completed + result.failed == result.total_tasks


def test_external_partial_failure_needs_a_terminal_receipt() -> None:
    result = _result()
    result.terminal_receipts = result.terminal_receipts[:1]
    with pytest.raises(RuntimeError, match="no central terminal receipt"):
        _validate(result)


def test_every_requested_worker_needs_one_closed_result() -> None:
    result = _result()
    result.worker_results[1] = ("worker-2", 0, 0, "setup failed")
    with pytest.raises(RuntimeError, match="not one closed task result"):
        _validate(result)


def test_exit_zero_cannot_override_a_non_verified_terminal_receipt() -> None:
    result = _result(second_state="QUARANTINED")
    # The worker row attempts to count a process-level success.  The central
    # terminal receipt remains the outcome authority and the set must refuse.
    result.worker_results[1] = ("worker-2", 1, 0, None)
    result.completed = 2
    result.failed = 0
    with pytest.raises(RuntimeError, match="differs from its central terminal receipt"):
        _validate(result)


def test_prelaunch_quarantine_is_one_closed_failed_task() -> None:
    result = _result(second_state="PRELAUNCH_QUARANTINED")
    validated = _validate(result)
    assert validated.completed == 1
    assert validated.failed == 1


def test_duplicate_dispatch_or_task_receipt_is_refused() -> None:
    result = _result()
    duplicate = dict(result.terminal_receipts[1])
    duplicate["dispatch_id_sha256"] = result.terminal_receipts[0][
        "dispatch_id_sha256"
    ]
    result.terminal_receipts = (result.terminal_receipts[0], duplicate)
    with pytest.raises(RuntimeError, match="not exact and unique"):
        _validate(result)
