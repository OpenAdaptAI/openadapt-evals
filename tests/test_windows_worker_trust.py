from __future__ import annotations

import hashlib
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import pytest

import openadapt_evals.infrastructure.windows_worker_trust as worker_trust
from openadapt_evals.infrastructure.windows_worker_dispatch import (
    QualifiedPrelaunchEvidence,
    WorkerDispatchError,
    _parse_prelaunch,
    _parse_process,
    build_terminal_evidence,
)
from openadapt_evals.infrastructure.windows_worker_task_contract import (
    WorkerTaskContract,
    derive_task_condition,
    derive_task_selector,
)
from openadapt_evals.infrastructure.windows_worker_trust import (
    BURN_RECEIPT_DOMAIN,
    BURNED_IDENTITIES_DOMAIN,
    DISPATCH_ID_DOMAIN,
    LAUNCH_ATTEMPT_IDENTITY_DOMAIN,
    PROCESS_START_IDENTITY_DOMAIN,
    START_ID_DOMAIN,
    TERMINAL_RECEIPT_IDENTITY_DOMAIN,
    ProviderObservation,
    VerifiedWorkerAdmission,
    WorkerTrustAuthority,
    WorkerTrustError,
    canonical_json,
    live_provider_observation_sha256,
    provider_identity_sha256,
    qualification_worker_identity_sha256,
    validate_authorized_dispatch,
    validate_provider_observation,
    validate_verified_worker_admission,
    validate_worker_terminal,
)

NOW = datetime(2026, 8, 27, 12, 0, 0, tzinfo=timezone.utc)
ROOT = Path(__file__).resolve().parents[1]


def _sha(label: str) -> str:
    return "sha256:" + hashlib.sha256(label.encode()).hexdigest()


def _domain_sha(domain: bytes, value: object) -> str:
    return "sha256:" + hashlib.sha256(domain + canonical_json(value)).hexdigest()


def _observation() -> ProviderObservation:
    return validate_provider_observation(
        {
            "schema_version": "openadapt.qualification-worker-provider-observation/v1",
            "provider": "azure",
            "provider_account": "account-private-opening",
            "region": "eastus",
            "resource_identity": "/subscriptions/private/resourceGroups/oa/providers/Microsoft.Compute/virtualMachines/waa-pool-00",
            "instance_identity": "instance-123",
            "network_identity": "192.0.2.10",
            "attestation_identity": "azure-instance-metadata-document",
            "attestation": "signed-private-provider-attestation",
            "observed_at": "2026-08-27T11:59:50Z",
        }
    )


def _worker_identity(observation: ProviderObservation) -> str:
    return qualification_worker_identity_sha256(
        observation=observation,
        worker_instance_sha256=_sha("worker-instance"),
        worker_image_sha256=_sha("worker-image"),
        host_identity_sha256=_sha("host"),
        admitted_runtime_sha256=_sha("runtime"),
    )


def _admission(observation: ProviderObservation) -> dict[str, object]:
    return {
        "schema_version": "openadapt.qualification-worker-admission-verifier-result/v1",
        "verdict": "accepted",
        "admission_object_sha256": _sha("admission-object"),
        "provider_identity_sha256": provider_identity_sha256(observation),
        "worker_identity_sha256": _worker_identity(observation),
        "live_provider_observation_sha256": live_provider_observation_sha256(
            observation
        ),
        "admitted_runtime_sha256": _sha("runtime"),
        "worker_image_sha256": _sha("worker-image"),
        "baseline_sha256": _sha("baseline"),
        "host_identity_sha256": _sha("host"),
        "tls_identity_sha256": _sha("tls"),
        "egress_policy_sha256": _sha("egress"),
        "campaign_permit_sha256": _sha("permit"),
        "capability_handle_sha256": _sha("capability-placeholder"),
        "authority_state_sha256": _sha("authority"),
        "revocation_state_sha256": _sha("revocation"),
        "signer_registry_sha256": _sha("signer-registry"),
        "not_before": "2026-08-27T11:58:00Z",
        "expires_at": "2026-08-27T12:05:00Z",
        "verified_at": "2026-08-27T11:59:55Z",
        "verifier": {
            "repository": "OpenAdaptAI/.github",
            "repository_id": "858454062",
            "repository_owner_id": "132681217",
            "workflow": ".github/workflows/verify-qualification-worker-admission.yml",
            "source_commit": "a" * 40,
            "runner_environment": "github-hosted",
        },
    }


def _dispatch(
    admission: dict[str, object],
    capability: bytes,
) -> dict[str, object]:
    admission["capability_handle_sha256"] = "sha256:" + hashlib.sha256(
        capability
    ).hexdigest()
    start = {
        "worker_admission_sha256": admission["admission_object_sha256"],
        "worker_identity_sha256": admission["worker_identity_sha256"],
        "run_id": "123",
        "run_attempt": "1",
        "task_id_sha256": _sha("task"),
        "task_condition_sha256": _sha("condition"),
        "capability_handle_sha256": admission["capability_handle_sha256"],
    }
    value = {
        "schema_version": "openadapt.qualification-worker-dispatch/v1",
        "worker_admission_sha256": admission["admission_object_sha256"],
        "provider_identity_sha256": admission["provider_identity_sha256"],
        "worker_identity_sha256": admission["worker_identity_sha256"],
        "live_provider_observation_sha256": admission[
            "live_provider_observation_sha256"
        ],
        "admitted_runtime_sha256": admission["admitted_runtime_sha256"],
        "run_id": "123",
        "run_attempt": "1",
        "start_id_sha256": _domain_sha(START_ID_DOMAIN, start),
        "task_id_sha256": start["task_id_sha256"],
        "task_condition_sha256": start["task_condition_sha256"],
        "campaign_artifact_sha256": _sha("campaign"),
        "process_lease_sha256": _sha("process-lease"),
        "capability_handle_sha256": start["capability_handle_sha256"],
        "idempotency_key": "qualification-worker-dispatch:" + "b" * 64,
        "issued_at": "2026-08-27T11:59:58Z",
        "not_before": "2026-08-27T11:59:57Z",
        "expires_at": "2026-08-27T12:01:00Z",
        "issuer": {
            "repository": "OpenAdaptAI/.github",
            "repository_id": "858454062",
            "repository_owner_id": "132681217",
            "workflow": ".github/workflows/issue-qualification-worker-dispatch.yml",
            "ref": "refs/heads/main",
            "source_commit": "b" * 40,
            "environment": "qualification-worker-dispatch",
        },
    }
    value["dispatch_id_sha256"] = _domain_sha(DISPATCH_ID_DOMAIN, value)
    return value


def _task_contract() -> WorkerTaskContract:
    selector = derive_task_selector(
        campaign_artifact_sha256=_sha("campaign"),
        task_source_sha256=_sha("task-source"),
        task_ordinal=1,
    )
    condition = derive_task_condition(
        task_id_sha256=selector.task_id_sha256,
        condition_source_sha256=_sha("condition-source"),
        condition_ordinal=1,
    )
    return WorkerTaskContract(selector=selector, condition=condition)


def _bind_dispatch_task(
    dispatch: dict[str, object],
    contract: WorkerTaskContract,
) -> None:
    dispatch["campaign_artifact_sha256"] = contract.selector.campaign_artifact_sha256
    dispatch["task_id_sha256"] = contract.selector.task_id_sha256
    dispatch["task_condition_sha256"] = contract.condition.task_condition_sha256
    start = {
        "worker_admission_sha256": dispatch["worker_admission_sha256"],
        "worker_identity_sha256": dispatch["worker_identity_sha256"],
        "run_id": dispatch["run_id"],
        "run_attempt": dispatch["run_attempt"],
        "task_id_sha256": dispatch["task_id_sha256"],
        "task_condition_sha256": dispatch["task_condition_sha256"],
        "capability_handle_sha256": dispatch["capability_handle_sha256"],
    }
    dispatch["start_id_sha256"] = _domain_sha(START_ID_DOMAIN, start)
    dispatch["dispatch_id_sha256"] = _domain_sha(
        DISPATCH_ID_DOMAIN,
        {key: value for key, value in dispatch.items() if key != "dispatch_id_sha256"},
    )


class _DispatchAuthority(WorkerTrustAuthority):
    def __init__(self, dispatch: dict[str, object], capability: bytes) -> None:
        self.dispatch = dispatch
        self.capability = capability
        self.bindings: dict[str, object] | None = None

    def _verify_worker(self, **bindings):
        raise AssertionError("not used")

    def _authorize_dispatch(self, **bindings):
        self.bindings = bindings
        return self.dispatch, self.capability

    def _issue_terminal(self, **bindings):
        raise AssertionError("not used")


def _terminal(
    admission: dict[str, object],
    dispatch: dict[str, object],
) -> tuple[dict[str, object], dict[str, object]]:
    process_projection = {
        "provider_identity_sha256": dispatch["provider_identity_sha256"],
        "worker_identity_sha256": dispatch["worker_identity_sha256"],
        "live_provider_observation_sha256": dispatch[
            "live_provider_observation_sha256"
        ],
        "admitted_runtime_sha256": dispatch["admitted_runtime_sha256"],
        "run_id": "123",
        "run_attempt": "1",
        "start_id_sha256": dispatch["start_id_sha256"],
        "dispatch_id_sha256": dispatch["dispatch_id_sha256"],
        "pid": 101,
        "process_group_id": 101,
        "process_start_ticks": "9001",
        "launched_at": "2026-08-27T12:00:00Z",
        "executable_sha256": _sha("bash-executable"),
    }
    process = {
        "pid": 101,
        "process_group_id": 101,
        "process_start_ticks": "9001",
        "launched_at": "2026-08-27T12:00:00Z",
        "executable_sha256": _sha("bash-executable"),
        "process_start_identity_sha256": _domain_sha(
            PROCESS_START_IDENTITY_DOMAIN,
            process_projection,
        ),
    }
    burned = {
        "worker_identity_sha256": dispatch["worker_identity_sha256"],
        "run_id": "123",
        "run_attempt": "1",
        "start_id_sha256": dispatch["start_id_sha256"],
        "dispatch_id_sha256": dispatch["dispatch_id_sha256"],
        "task_id_sha256": dispatch["task_id_sha256"],
        "capability_handle_sha256": dispatch["capability_handle_sha256"],
        "burn_ledger_revision": 7,
        "burned_at": "2026-08-27T11:59:59Z",
    }
    burned_sha256 = _domain_sha(BURNED_IDENTITIES_DOMAIN, burned)
    burn_receipt = {
        "burned_identities_sha256": burned_sha256,
        "burn_ledger_revision": 7,
        "burned_at": "2026-08-27T11:59:59Z",
        "ledger_readback_sha256": _sha("ledger-readback"),
    }
    launch_attempt = {
        "attempted_at": "2026-08-27T11:59:59Z",
        "host_identity_sha256": admission["host_identity_sha256"],
        "executable_sha256": _sha("bash-executable"),
        "capability_handle_sha256": dispatch["capability_handle_sha256"],
        "evidence_sha256": _sha("launch-evidence"),
        "child_created": True,
        "failure_classification": None,
    }
    launch_projection = {
        "worker_admission_sha256": admission["admission_object_sha256"],
        "dispatch_id_sha256": dispatch["dispatch_id_sha256"],
        "provider_identity_sha256": dispatch["provider_identity_sha256"],
        "worker_identity_sha256": dispatch["worker_identity_sha256"],
        "live_provider_observation_sha256": dispatch[
            "live_provider_observation_sha256"
        ],
        "admitted_runtime_sha256": dispatch["admitted_runtime_sha256"],
        "run_id": "123",
        "run_attempt": "1",
        "start_id_sha256": dispatch["start_id_sha256"],
        "capability_handle_sha256": dispatch["capability_handle_sha256"],
        "launch_attempt": launch_attempt,
    }
    receipt = {
        "schema_version": "openadapt.qualification-worker-terminal-receipt/v1",
        "receipt_id_sha256": _sha("receipt"),
        "worker_admission_sha256": admission["admission_object_sha256"],
        "dispatch_id_sha256": dispatch["dispatch_id_sha256"],
        "provider_identity_sha256": dispatch["provider_identity_sha256"],
        "worker_identity_sha256": dispatch["worker_identity_sha256"],
        "live_provider_observation_sha256": dispatch[
            "live_provider_observation_sha256"
        ],
        "admitted_runtime_sha256": dispatch["admitted_runtime_sha256"],
        "run_id": "123",
        "run_attempt": "1",
        "start_id_sha256": dispatch["start_id_sha256"],
        "task_id_sha256": dispatch["task_id_sha256"],
        "task_condition_sha256": dispatch["task_condition_sha256"],
        "capability_handle_sha256": dispatch["capability_handle_sha256"],
        "launch_attempt": launch_attempt,
        "launch_attempt_sha256": _domain_sha(
            LAUNCH_ATTEMPT_IDENTITY_DOMAIN,
            launch_projection,
        ),
        "process": process,
        "oracle_sha256": _sha("oracle"),
        "result_sha256": _sha("result"),
        "log_sha256": _sha("log"),
        "burned_identities_sha256": burned_sha256,
        "burn_ledger_revision": 7,
        "burn_receipt_sha256": _domain_sha(BURN_RECEIPT_DOMAIN, burn_receipt),
        "burned_at": "2026-08-27T11:59:59Z",
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
        "completed_at": "2026-08-27T12:00:30Z",
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
    receipt["receipt_id_sha256"] = _domain_sha(
        TERMINAL_RECEIPT_IDENTITY_DOMAIN,
        {key: value for key, value in receipt.items() if key != "receipt_id_sha256"},
    )
    local_process = {
        **process,
        "schema_version": "openadapt.qualification-worker-process-evidence/v1",
        "worker_admission_sha256": admission["admission_object_sha256"],
        "provider_identity_sha256": dispatch["provider_identity_sha256"],
        "worker_identity_sha256": dispatch["worker_identity_sha256"],
        "live_provider_observation_sha256": dispatch[
            "live_provider_observation_sha256"
        ],
        "admitted_runtime_sha256": dispatch["admitted_runtime_sha256"],
        "run_id": "123",
        "run_attempt": "1",
        "start_id_sha256": dispatch["start_id_sha256"],
        "dispatch_id_sha256": dispatch["dispatch_id_sha256"],
        "task_id_sha256": dispatch["task_id_sha256"],
        "task_condition_sha256": dispatch["task_condition_sha256"],
        "capability_handle_sha256": dispatch["capability_handle_sha256"],
        "process_lease_sha256": dispatch["process_lease_sha256"],
        "process_start_ticks": "9001",
        "launch_attempt": receipt["launch_attempt"],
        "launch_attempt_sha256": receipt["launch_attempt_sha256"],
        "subset_sha256": _sha("subset"),
        "oracle_sha256": _sha("oracle"),
        "container_state_sha256": _sha("container"),
        "burn_ledger_revision": 7,
        "burned_at": "2026-08-27T11:59:59Z",
        "ledger_readback_sha256": _sha("ledger-readback"),
    }
    evidence = {
        "process": local_process,
        "launch_attempt": receipt["launch_attempt"],
        "terminal_readback": {
            "state": "TERMINAL",
            "exit_code": 0,
            "oracle_sha256": _sha("oracle"),
            "result_sha256": _sha("result"),
            "oracle_success": True,
            "log_sha256": _sha("log"),
        },
    }
    return receipt, evidence


def test_central_worker_admission_dispatch_and_terminal_contracts() -> None:
    observation = _observation()
    admission = _admission(observation)
    validated_admission = validate_verified_worker_admission(
        admission,
        observation=observation,
        worker_identity_sha256=_worker_identity(observation),
        admitted_runtime_sha256=_sha("runtime"),
        worker_image_sha256=_sha("worker-image"),
        baseline_sha256=_sha("baseline"),
        host_identity_sha256=_sha("host"),
        tls_identity_sha256=_sha("tls"),
        egress_policy_sha256=_sha("egress"),
        now=NOW,
    )
    capability = b"c" * 32
    dispatch = _dispatch(admission, capability)
    validated_dispatch = validate_authorized_dispatch(
        dispatch,
        capability=capability,
        admission=validated_admission,
        run_id="123",
        now=NOW,
    )
    receipt, evidence = _terminal(admission, dispatch)
    assert (
        validate_worker_terminal(
            receipt,
            dispatch=validated_dispatch,
            admission=validated_admission,
            terminal_evidence=evidence,
        )["terminal_state"]
        == "VERIFIED"
    )


def test_worker_admission_and_dispatch_schemas_are_exact_central_copies() -> None:
    expected = {
        "qualification-worker-admission.schema.json": (
            "852dc3cb93f0c74ec79c135e46001e0c8637b33efc147d1e21ad1f1946b63327"
        ),
        "qualification-worker-admission-verifier-result.schema.json": (
            "6e1f938a565250ecaed5b3e84cf939a4150737d78f5476659d349a68f5fd6886"
        ),
        "qualification-worker-dispatch.schema.json": (
            "1ff432becdfc836b23b4b60959584881f75960d7803e15724b64da90400acb8e"
        ),
    }
    for name, digest in expected.items():
        schema = (ROOT / "openadapt_evals" / "schemas" / name).read_bytes()
        assert hashlib.sha256(schema).hexdigest() == digest


def test_authority_sends_and_requires_the_exact_task_contract(monkeypatch) -> None:
    class _FixedDateTime:
        @classmethod
        def now(cls, tz=None):
            return NOW

        @classmethod
        def fromisoformat(cls, value):
            return datetime.fromisoformat(value)

    monkeypatch.setattr(worker_trust, "datetime", _FixedDateTime)
    observation = _observation()
    admission = _admission(observation)
    capability = b"c" * 32
    dispatch = _dispatch(admission, capability)
    contract = _task_contract()
    _bind_dispatch_task(dispatch, contract)
    authority = _DispatchAuthority(dispatch, capability)

    authorized = authority.authorize_dispatch(
        admission=VerifiedWorkerAdmission._from_authority(admission),
        run_id="123",
        task_contract=contract,
    )

    assert authorized.object["task_id_sha256"] == contract.selector.task_id_sha256
    assert authority.bindings is not None
    assert authority.bindings["task_selector"] == contract.selector.as_mapping()
    assert authority.bindings["task_condition"] == contract.condition.as_mapping()


def test_authority_refuses_a_central_dispatch_for_a_different_task(monkeypatch) -> None:
    class _FixedDateTime:
        @classmethod
        def now(cls, tz=None):
            return NOW

        @classmethod
        def fromisoformat(cls, value):
            return datetime.fromisoformat(value)

    monkeypatch.setattr(worker_trust, "datetime", _FixedDateTime)
    observation = _observation()
    admission = _admission(observation)
    capability = b"c" * 32
    dispatch = _dispatch(admission, capability)
    expected = _task_contract()
    different_selector = derive_task_selector(
        campaign_artifact_sha256=_sha("campaign"),
        task_source_sha256=_sha("different-task-source"),
        task_ordinal=1,
    )
    different_condition = derive_task_condition(
        task_id_sha256=different_selector.task_id_sha256,
        condition_source_sha256=_sha("condition-source"),
        condition_ordinal=1,
    )
    _bind_dispatch_task(
        dispatch,
        WorkerTaskContract(
            selector=different_selector,
            condition=different_condition,
        ),
    )
    authority = _DispatchAuthority(dispatch, capability)

    with pytest.raises(WorkerTrustError, match="task contract differs"):
        authority.authorize_dispatch(
            admission=VerifiedWorkerAdmission._from_authority(admission),
            run_id="123",
            task_contract=expected,
        )


def _prelaunch_evidence(
    admission: dict[str, object],
    dispatch: dict[str, object],
) -> dict[str, object]:
    receipt, _ = _terminal(admission, dispatch)
    launch_attempt = {
        **receipt["launch_attempt"],
        "child_created": False,
        "failure_classification": "PROCESS_START_REFUSED",
    }
    launch_projection = {
        "worker_admission_sha256": admission["admission_object_sha256"],
        "dispatch_id_sha256": dispatch["dispatch_id_sha256"],
        "provider_identity_sha256": dispatch["provider_identity_sha256"],
        "worker_identity_sha256": dispatch["worker_identity_sha256"],
        "live_provider_observation_sha256": dispatch[
            "live_provider_observation_sha256"
        ],
        "admitted_runtime_sha256": dispatch["admitted_runtime_sha256"],
        "run_id": dispatch["run_id"],
        "run_attempt": "1",
        "start_id_sha256": dispatch["start_id_sha256"],
        "capability_handle_sha256": dispatch["capability_handle_sha256"],
        "launch_attempt": launch_attempt,
    }
    value = {
        key: item
        for key, item in receipt.items()
        if key not in {"receipt_id_sha256", "issuer"}
    }
    value.update(
        schema_version="openadapt.qualification-worker-terminal-evidence/v1",
        launch_attempt=launch_attempt,
        launch_attempt_sha256=_domain_sha(
            LAUNCH_ATTEMPT_IDENTITY_DOMAIN,
            launch_projection,
        ),
        process=None,
        effect_started=False,
        delivery_state="not_started",
        terminal_state="PRELAUNCH_QUARANTINED",
        exit_code=None,
        uncertainty_sha256=None,
        quarantine={
            "active": True,
            "reason_code": "PROCESS_START_REFUSED",
            "evidence_sha256": launch_attempt["evidence_sha256"],
        },
        terminal_readback={
            "state": "PRELAUNCH_QUARANTINED",
            "classification": "PROCESS_START_REFUSED",
        },
        interrupt_evidence=None,
    )
    return value


def test_bounded_prelaunch_evidence_requires_no_child_and_exact_burn() -> None:
    observation = _observation()
    admission = _admission(observation)
    capability = b"c" * 32
    dispatch = _dispatch(admission, capability)
    opaque_admission = VerifiedWorkerAdmission._from_authority(admission)
    from openadapt_evals.infrastructure.windows_worker_trust import (
        AuthorizedWorkerDispatch,
    )

    opaque_dispatch = AuthorizedWorkerDispatch._from_authority(dispatch, capability)
    value = _prelaunch_evidence(admission, dispatch)
    parsed = _parse_prelaunch(
        value,
        admission=opaque_admission,
        dispatch=opaque_dispatch,
    )
    assert isinstance(parsed, QualifiedPrelaunchEvidence)
    assert build_terminal_evidence(
        admission=opaque_admission,
        dispatch=opaque_dispatch,
        process=parsed,
    ) == value

    changed = deepcopy(value)
    changed["launch_attempt"]["child_created"] = True
    with pytest.raises(WorkerDispatchError, match="launch attempt differs"):
        _parse_prelaunch(
            changed,
            admission=opaque_admission,
            dispatch=opaque_dispatch,
        )


def test_uncertain_interrupt_can_quarantine_a_still_running_process() -> None:
    observation = _observation()
    admission = _admission(observation)
    capability = b"c" * 32
    dispatch = _dispatch(admission, capability)
    receipt, evidence = _terminal(admission, dispatch)
    process = _parse_process(evidence["process"])
    opaque_admission = VerifiedWorkerAdmission._from_authority(admission)
    from openadapt_evals.infrastructure.windows_worker_trust import (
        AuthorizedWorkerDispatch,
    )

    opaque_dispatch = AuthorizedWorkerDispatch._from_authority(dispatch, capability)
    interrupted = {
        "state": "INTERRUPT_UNCERTAIN",
        "leader_identity_matched": True,
        "process_group_absent": False,
        "remaining_member_count": 1,
        "log_sha256": _sha("running-log"),
        "log_size_bytes": 12,
        "process": evidence["process"],
    }
    terminal = build_terminal_evidence(
        admission=opaque_admission,
        dispatch=opaque_dispatch,
        process=process,
        terminal_readback={"state": "RUNNING"},
        interrupt_evidence=interrupted,
        completed_at=NOW,
    )
    assert terminal["terminal_state"] == "QUARANTINED"
    assert terminal["delivery_state"] == "uncertain"
    assert terminal["quarantine"]["active"] is True


@pytest.mark.parametrize(
    ("mutation", "match"),
    [
        (lambda item: item.update(extra=True), "closed"),
        (
            lambda item: item.update(worker_identity_sha256=_sha("other-worker")),
            "binding differs",
        ),
        (
            lambda item: item.update(verified_at="2026-08-27T11:59:55.1Z"),
            "verified_at is invalid",
        ),
    ],
)
def test_worker_admission_rejects_shape_identity_and_timestamp_mutation(
    mutation,
    match: str,
) -> None:
    observation = _observation()
    admission = _admission(observation)
    mutation(admission)
    with pytest.raises(WorkerTrustError, match=match):
        validate_verified_worker_admission(
            admission,
            observation=observation,
            worker_identity_sha256=_worker_identity(observation),
            admitted_runtime_sha256=_sha("runtime"),
            worker_image_sha256=_sha("worker-image"),
            baseline_sha256=_sha("baseline"),
            host_identity_sha256=_sha("host"),
            tls_identity_sha256=_sha("tls"),
            egress_policy_sha256=_sha("egress"),
            now=NOW,
        )


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("run_id", "run-123", "run id"),
        ("idempotency_key", "dispatch:abc", "idempotency"),
        ("dispatch_id_sha256", "sha256:" + "A" * 64, "dispatch_id_sha256"),
    ],
)
def test_dispatch_rejects_noncanonical_identity_fields(
    field: str,
    value: object,
    match: str,
) -> None:
    observation = _observation()
    admission = _admission(observation)
    capability = b"c" * 32
    dispatch = _dispatch(admission, capability)
    dispatch[field] = value
    with pytest.raises(WorkerTrustError, match=match):
        validate_authorized_dispatch(
            dispatch,
            capability=capability,
            admission=admission,
            run_id="123",
            now=NOW,
        )


def test_terminal_rejects_false_oracle_as_verified() -> None:
    observation = _observation()
    admission = _admission(observation)
    capability = b"c" * 32
    dispatch = _dispatch(admission, capability)
    receipt, evidence = _terminal(admission, dispatch)
    evidence["terminal_readback"]["oracle_success"] = False
    with pytest.raises(WorkerTrustError, match="oracle success"):
        validate_worker_terminal(
            receipt,
            dispatch=dispatch,
            admission=admission,
            terminal_evidence=evidence,
        )


def test_terminal_rejects_process_and_burn_identity_mutation() -> None:
    observation = _observation()
    admission = _admission(observation)
    capability = b"c" * 32
    dispatch = _dispatch(admission, capability)
    receipt, evidence = _terminal(admission, dispatch)
    receipt["process"]["pid"] = 102
    with pytest.raises(WorkerTrustError, match="process identity"):
        validate_worker_terminal(
            receipt,
            dispatch=dispatch,
            admission=admission,
            terminal_evidence=evidence,
        )
    receipt, evidence = _terminal(admission, dispatch)
    receipt["burn_ledger_revision"] = 8
    with pytest.raises(WorkerTrustError, match="burned identities"):
        validate_worker_terminal(
            receipt,
            dispatch=dispatch,
            admission=admission,
            terminal_evidence=evidence,
        )


def test_terminal_rejects_incomplete_quarantine() -> None:
    observation = _observation()
    admission = _admission(observation)
    capability = b"c" * 32
    dispatch = _dispatch(admission, capability)
    receipt, evidence = _terminal(admission, dispatch)
    receipt["terminal_state"] = "QUARANTINED"
    receipt["delivery_state"] = "uncertain"
    receipt["uncertainty_sha256"] = _sha("uncertain")
    receipt["quarantine"] = {
        "active": True,
        "reason_code": None,
        "evidence_sha256": None,
    }
    with pytest.raises(WorkerTrustError, match="incomplete"):
        validate_worker_terminal(
            receipt,
            dispatch=dispatch,
            admission=admission,
            terminal_evidence=evidence,
        )


def test_positive_admission_wrapper_is_not_caller_constructible() -> None:
    with pytest.raises(TypeError):
        VerifiedWorkerAdmission({})


def test_provider_observation_is_closed_and_private_openings_affect_identity() -> None:
    observation = _observation()
    changed = deepcopy(observation.__dict__)
    changed["provider_account"] = "different-private-account"
    changed_observation = validate_provider_observation(changed)
    assert provider_identity_sha256(changed_observation) != provider_identity_sha256(
        observation
    )
    invalid = dict(observation.__dict__)
    invalid["extra"] = "not-allowed"
    with pytest.raises(WorkerTrustError, match="closed"):
        validate_provider_observation(invalid)
