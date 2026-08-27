from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

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


def test_central_schema_binds_prelaunch_and_postlaunch_process_identity() -> None:
    schema = _central_schema()
    properties = schema["properties"]
    assert isinstance(properties, dict)
    process = properties["process"]
    assert isinstance(process, dict)
    process_object = process["oneOf"][0]
    assert "process_start_ticks" in process_object["required"]

    conditions = schema["allOf"]
    assert conditions[0]["then"]["properties"]["terminal_state"] == {
        "const": "PRELAUNCH_QUARANTINED"
    }
    assert conditions[0]["then"]["properties"]["launch_attempt"]["properties"][
        "child_created"
    ] == {"const": False}
    assert conditions[1]["then"]["properties"]["process"] == {"type": "null"}
    assert conditions[2]["then"]["properties"]["process"] == {"type": "object"}
    assert conditions[2]["then"]["properties"]["launch_attempt"]["properties"][
        "child_created"
    ] == {"const": True}


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
