from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from threading import Event
from unittest.mock import patch

import pytest

from openadapt_evals.infrastructure.pool import (
    PoolRunResult,
    _build_postlaunch_terminal_evidence,
    _build_qualified_terminal_evidence,
    validate_terminal_pool_result,
)
from openadapt_evals.infrastructure.windows_worker_dispatch import (
    QualifiedPrelaunchEvidence,
)
from openadapt_evals.infrastructure.windows_worker_trust import (
    AuthorizedWorkerDispatch,
    VerifiedWorkerTerminal,
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


def test_postlaunch_terminal_uses_one_canonical_evidence_build() -> None:
    terminal_readback = {"state": "TERMINAL", "oracle_success": True}
    built = {"schema_version": "openadapt.qualification-worker-terminal-evidence/v1"}
    with (
        patch(
            "openadapt_evals.infrastructure.windows_worker_dispatch.read_process_terminal",
            return_value=terminal_readback,
        ),
        patch(
            "openadapt_evals.infrastructure.windows_worker_dispatch.interrupt_process"
        ) as interrupt,
        patch(
            "openadapt_evals.infrastructure.windows_worker_dispatch.build_terminal_evidence",
            return_value=built,
        ) as build,
    ):
        result = _build_postlaunch_terminal_evidence(
            manager="manager",
            admission="admission",
            dispatch="dispatch",
            process="process",
            interrupt_requested=Event(),
            poll_seconds=0,
        )

    assert result is built
    interrupt.assert_not_called()
    build.assert_called_once_with(
        admission="admission",
        dispatch="dispatch",
        process="process",
        terminal_readback=terminal_readback,
        interrupt_evidence=None,
    )


def test_shared_interrupt_proves_termination_before_terminal_build() -> None:
    interrupt_requested = Event()
    interrupt_requested.set()
    interrupt_evidence = {"state": "INTERRUPTED_PROVEN"}
    terminal_readback = {"state": "UNCERTAIN"}
    built = {"schema_version": "openadapt.qualification-worker-terminal-evidence/v1"}
    with (
        patch(
            "openadapt_evals.infrastructure.windows_worker_dispatch.interrupt_process",
            return_value=interrupt_evidence,
        ) as interrupt,
        patch(
            "openadapt_evals.infrastructure.windows_worker_dispatch.read_process_terminal",
            return_value=terminal_readback,
        ) as read,
        patch(
            "openadapt_evals.infrastructure.windows_worker_dispatch.build_terminal_evidence",
            return_value=built,
        ) as build,
    ):
        result = _build_postlaunch_terminal_evidence(
            manager="manager",
            admission="admission",
            dispatch="dispatch",
            process="process",
            interrupt_requested=interrupt_requested,
            poll_seconds=0,
        )

    assert result is built
    interrupt.assert_called_once_with("manager", "process")
    read.assert_called_once_with("manager", "process")
    build.assert_called_once_with(
        admission="admission",
        dispatch="dispatch",
        process="process",
        terminal_readback=terminal_readback,
        interrupt_evidence=interrupt_evidence,
    )


def test_uncertain_interrupt_retains_running_readback_for_quarantine() -> None:
    interrupt_requested = Event()
    interrupt_requested.set()
    interrupt_evidence = {"state": "INTERRUPT_UNCERTAIN"}
    terminal_readback = {"state": "RUNNING"}
    with (
        patch(
            "openadapt_evals.infrastructure.windows_worker_dispatch.interrupt_process",
            return_value=interrupt_evidence,
        ),
        patch(
            "openadapt_evals.infrastructure.windows_worker_dispatch.read_process_terminal",
            return_value=terminal_readback,
        ),
        patch(
            "openadapt_evals.infrastructure.windows_worker_dispatch.build_terminal_evidence",
            return_value={"terminal_state": "QUARANTINED"},
        ) as build,
    ):
        _build_postlaunch_terminal_evidence(
            manager="manager",
            admission="admission",
            dispatch="dispatch",
            process="process",
            interrupt_requested=interrupt_requested,
            poll_seconds=0,
        )

    build.assert_called_once_with(
        admission="admission",
        dispatch="dispatch",
        process="process",
        terminal_readback=terminal_readback,
        interrupt_evidence=interrupt_evidence,
    )


def test_worker_interrupt_enters_the_same_termination_proof_path() -> None:
    interrupt_requested = Event()
    interrupt_evidence = {"state": "INTERRUPTED_PROVEN"}
    terminal_readback = {"state": "UNCERTAIN"}
    with (
        patch(
            "openadapt_evals.infrastructure.windows_worker_dispatch.interrupt_process",
            return_value=interrupt_evidence,
        ) as interrupt,
        patch(
            "openadapt_evals.infrastructure.windows_worker_dispatch.read_process_terminal",
            side_effect=[KeyboardInterrupt, terminal_readback],
        ) as read,
        patch(
            "openadapt_evals.infrastructure.windows_worker_dispatch.build_terminal_evidence",
            return_value={"terminal_state": "QUARANTINED"},
        ) as build,
    ):
        _build_postlaunch_terminal_evidence(
            manager="manager",
            admission="admission",
            dispatch="dispatch",
            process="process",
            interrupt_requested=interrupt_requested,
            poll_seconds=0,
        )

    assert interrupt_requested.is_set()
    assert read.call_count == 2
    interrupt.assert_called_once_with("manager", "process")
    build.assert_called_once()


@dataclass(frozen=True)
class _MinimalProcess:
    dispatch_id_sha256: str
    process_start_identity_sha256: str


def test_monitor_failure_retains_canonical_uncertainty_and_attempts_interrupt() -> None:
    process = _MinimalProcess(_sha("dispatch"), _sha("process"))
    interrupt = {
        "state": "INTERRUPTED_PROVEN",
        "process": {
            "dispatch_id_sha256": process.dispatch_id_sha256,
            "process_start_identity_sha256": process.process_start_identity_sha256,
        },
        "log_sha256": _sha("interrupt-log"),
    }
    with (
        patch(
            "openadapt_evals.infrastructure.windows_worker_dispatch.read_process_terminal",
            side_effect=RuntimeError("ssh lost"),
        ),
        patch(
            "openadapt_evals.infrastructure.windows_worker_dispatch.interrupt_process",
            return_value=interrupt,
        ) as stop,
        patch(
            "openadapt_evals.infrastructure.windows_worker_dispatch.build_terminal_evidence",
            return_value={"terminal_state": "QUARANTINED"},
        ) as build,
    ):
        result = _build_postlaunch_terminal_evidence(
            manager="manager",
            admission="admission",
            dispatch="dispatch",
            process=process,
            interrupt_requested=Event(),
            poll_seconds=0,
        )

    assert result == {"terminal_state": "QUARANTINED"}
    stop.assert_called_once_with("manager", process)
    readback = build.call_args.kwargs["terminal_readback"]
    assert readback["state"] == "UNCERTAIN"
    assert readback["log_sha256"].startswith("sha256:")


def test_monitor_and_interrupt_failure_stays_quarantined_and_uncertain() -> None:
    process = _MinimalProcess(_sha("dispatch"), _sha("process"))
    with (
        patch(
            "openadapt_evals.infrastructure.windows_worker_dispatch.read_process_terminal",
            side_effect=RuntimeError("ssh lost"),
        ),
        patch(
            "openadapt_evals.infrastructure.windows_worker_dispatch.interrupt_process",
            side_effect=RuntimeError("stop unconfirmed"),
        ),
        patch(
            "openadapt_evals.infrastructure.windows_worker_dispatch.build_terminal_evidence",
            return_value={"terminal_state": "QUARANTINED"},
        ) as build,
    ):
        _build_postlaunch_terminal_evidence(
            manager="manager",
            admission="admission",
            dispatch="dispatch",
            process=process,
            interrupt_requested=Event(),
            poll_seconds=0,
        )

    interrupt_evidence = build.call_args.kwargs["interrupt_evidence"]
    assert interrupt_evidence["state"] == "INTERRUPT_UNCERTAIN"
    assert interrupt_evidence["process_group_absent"] is False


def test_prelaunch_quarantine_uses_the_canonical_evidence_builder() -> None:
    outcome = QualifiedPrelaunchEvidence(terminal_evidence={"process": None})
    built = {"terminal_state": "PRELAUNCH_QUARANTINED"}
    with (
        patch(
            "openadapt_evals.infrastructure.windows_worker_dispatch.build_terminal_evidence",
            return_value=built,
        ) as build,
        patch(
            "openadapt_evals.infrastructure.pool._build_postlaunch_terminal_evidence"
        ) as postlaunch,
    ):
        result = _build_qualified_terminal_evidence(
            manager="manager",
            admission="admission",
            dispatch="dispatch",
            launch_outcome=outcome,
            interrupt_requested=Event(),
        )

    assert result is built
    postlaunch.assert_not_called()
    build.assert_called_once_with(
        admission="admission",
        dispatch="dispatch",
        process=outcome,
    )


def _receipt(worker: str, state: str = "VERIFIED") -> VerifiedWorkerTerminal:
    return VerifiedWorkerTerminal._from_authority({
        "receipt_id_sha256": _sha(f"receipt:{worker}"),
        "dispatch_id_sha256": _sha(f"dispatch:{worker}"),
        "task_id_sha256": _sha(f"task:{worker}"),
        "terminal_state": state,
    })


def _dispatch(worker: str) -> AuthorizedWorkerDispatch:
    return AuthorizedWorkerDispatch._from_authority(
        {"dispatch_id_sha256": _sha(f"dispatch:{worker}")},
        b"test-only-capability" * 2,
    )


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
        dispatch_ids_by_worker={
            "worker-1": _sha("dispatch:worker-1"),
            "worker-2": _sha("dispatch:worker-2"),
        },
        authorized_dispatches_by_worker={
            "worker-1": _dispatch("worker-1"),
            "worker-2": _dispatch("worker-2"),
        },
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


def test_external_result_retains_exact_worker_dispatch_correlation() -> None:
    result = _result()
    result.dispatch_ids_by_worker = {
        "worker-1": _sha("dispatch:worker-1"),
        "worker-2": _sha("different-dispatch"),
    }
    with pytest.raises(RuntimeError, match="expectations are not exact"):
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


def test_duplicate_dispatch_receipt_is_refused() -> None:
    result = _result()
    duplicate = dict(result.terminal_receipts[1].object)
    duplicate["dispatch_id_sha256"] = result.terminal_receipts[0].object[
        "dispatch_id_sha256"
    ]
    result.terminal_receipts = (
        result.terminal_receipts[0],
        VerifiedWorkerTerminal._from_authority(duplicate),
    )
    with pytest.raises(RuntimeError, match="not exact and unique"):
        _validate(result)


def test_duplicate_central_receipt_identity_is_refused() -> None:
    result = _result()
    second = dict(result.terminal_receipts[1].object)
    second["receipt_id_sha256"] = result.terminal_receipts[0].object[
        "receipt_id_sha256"
    ]
    result.terminal_receipts = (
        result.terminal_receipts[0],
        VerifiedWorkerTerminal._from_authority(second),
    )
    with pytest.raises(RuntimeError, match="not exact and unique"):
        _validate(result)


def test_repeated_task_identity_is_valid_for_independent_trials() -> None:
    result = _result()
    second = dict(result.terminal_receipts[1].object)
    second["task_id_sha256"] = result.terminal_receipts[0].object["task_id_sha256"]
    result.terminal_receipts = (
        result.terminal_receipts[0],
        VerifiedWorkerTerminal._from_authority(second),
    )
    assert _validate(result) is result


def test_plain_mapping_cannot_fabricate_a_verified_terminal() -> None:
    result = _result()
    result.terminal_receipts = (
        result.terminal_receipts[0],
        result.terminal_receipts[1].object,
    )
    with pytest.raises(RuntimeError, match="opaque verified result"):
        _validate(result)


def test_plain_mapping_cannot_fabricate_an_authorized_dispatch() -> None:
    result = _result()
    result.authorized_dispatches_by_worker = {
        **result.authorized_dispatches_by_worker,
        "worker-2": {"dispatch_id_sha256": _sha("dispatch:worker-2")},
    }
    with pytest.raises(RuntimeError, match="opaque central result"):
        _validate(result)
