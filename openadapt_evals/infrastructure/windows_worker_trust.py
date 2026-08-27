"""Typed central-trust boundary for qualified Windows workers.

This module does not implement a trust root.  A configured central connector
must resolve and verify signed, current objects, then return them through the
abstract :class:`WorkerTrustAuthority` interface.  Callers cannot construct a
positive verifier result from a JSON file or a command-line argument.
"""

from __future__ import annotations

import hashlib
import json
import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Mapping

from openadapt_evals.infrastructure.windows_worker_task_contract import (
    WorkerTaskContract,
)

SHA256 = re.compile(r"^sha256:[a-f0-9]{64}$")
HEX40 = re.compile(r"^[a-f0-9]{40}$")
DECIMAL_ID = re.compile(r"^[1-9][0-9]*$")
TIMESTAMP = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")
DISPATCH_IDEMPOTENCY_KEY = re.compile(
    r"^qualification-worker-dispatch:[0-9a-f]{64}$"
)

WORKER_ADMISSION_VERIFIER_RESULT_SCHEMA = (
    "openadapt.qualification-worker-admission-verifier-result/v1"
)
WORKER_DISPATCH_SCHEMA = "openadapt.qualification-worker-dispatch/v1"
WORKER_TERMINAL_RECEIPT_SCHEMA = (
    "openadapt.qualification-worker-terminal-receipt/v1"
)
PROVIDER_OBSERVATION_SCHEMA = "openadapt.qualification-worker-provider-observation/v1"

PROVIDER_IDENTITY_DOMAIN = b"OpenAdapt qualification worker provider identity v1\0"
LIVE_PROVIDER_OBSERVATION_DOMAIN = (
    b"OpenAdapt qualification worker live provider observation v1\0"
)
WORKER_IDENTITY_DOMAIN = b"OpenAdapt qualification WorkerIdentity v1\0"
START_ID_DOMAIN = b"OpenAdapt qualification worker start v1\0"
DISPATCH_ID_DOMAIN = b"OpenAdapt qualification worker dispatch v1\0"
PROCESS_START_IDENTITY_DOMAIN = b"OpenAdapt qualification worker process start v1\0"
LAUNCH_ATTEMPT_IDENTITY_DOMAIN = (
    b"OpenAdapt qualification worker launch attempt v1\0"
)
TERMINAL_RECEIPT_IDENTITY_DOMAIN = (
    b"OpenAdapt qualification worker terminal receipt v1\0"
)
BURNED_IDENTITIES_DOMAIN = b"OpenAdapt qualification worker burned identities v1\0"
BURN_RECEIPT_DOMAIN = b"OpenAdapt qualification worker burn receipt v1\0"

_CENTRAL_REPOSITORY = "OpenAdaptAI/.github"
_CENTRAL_REPOSITORY_ID = "858454062"
_CENTRAL_OWNER_ID = "132681217"
_CENTRAL_REF = "refs/heads/main"


class WorkerTrustError(RuntimeError):
    """The central worker authority did not prove the requested operation."""


def canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _digest(domain: bytes, value: object) -> str:
    return "sha256:" + hashlib.sha256(domain + canonical_json(value)).hexdigest()


def _timestamp(value: object, label: str) -> datetime:
    if not isinstance(value, str) or TIMESTAMP.fullmatch(value) is None:
        raise WorkerTrustError(f"{label} is invalid")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise WorkerTrustError(f"{label} is invalid") from exc
    if parsed.tzinfo is None:
        raise WorkerTrustError(f"{label} must include a timezone")
    return parsed.astimezone(timezone.utc)


def _closed_mapping(value: object, keys: set[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping) or set(value) != keys:
        raise WorkerTrustError(f"{label} is not a closed object")
    return value


def _require_digest(value: object, label: str) -> str:
    if not isinstance(value, str) or SHA256.fullmatch(value) is None:
        raise WorkerTrustError(f"{label} is invalid")
    return value


def _validate_issuer(value: object, *, workflow: str, environment: str) -> None:
    issuer = _closed_mapping(
        value,
        {
            "repository",
            "repository_id",
            "repository_owner_id",
            "workflow",
            "ref",
            "source_commit",
            "environment",
        },
        "worker authority issuer",
    )
    expected = {
        "repository": _CENTRAL_REPOSITORY,
        "repository_id": _CENTRAL_REPOSITORY_ID,
        "repository_owner_id": _CENTRAL_OWNER_ID,
        "workflow": workflow,
        "ref": _CENTRAL_REF,
        "environment": environment,
    }
    if any(issuer[key] != expected_value for key, expected_value in expected.items()):
        raise WorkerTrustError("worker authority issuer differs")
    if not isinstance(issuer["source_commit"], str) or HEX40.fullmatch(
        issuer["source_commit"]
    ) is None:
        raise WorkerTrustError("worker authority source commit is invalid")


@dataclass(frozen=True)
class ProviderObservation:
    """Private live provider opening supplied to the central verifier."""

    schema_version: str
    provider: str
    provider_account: str
    region: str
    resource_identity: str
    instance_identity: str
    network_identity: str
    attestation_identity: str
    attestation: str
    observed_at: str


def validate_provider_observation(value: object) -> ProviderObservation:
    keys = set(ProviderObservation.__dataclass_fields__)
    mapping = _closed_mapping(value, keys, "live provider observation")
    try:
        observation = ProviderObservation(**mapping)
    except TypeError as exc:  # pragma: no cover - closed keys prove construction
        raise WorkerTrustError("live provider observation is invalid") from exc
    if observation.schema_version != PROVIDER_OBSERVATION_SCHEMA:
        raise WorkerTrustError("live provider observation schema is invalid")
    if observation.provider not in {"azure", "aws", "customer-controlled"}:
        raise WorkerTrustError("live provider is invalid")
    for field in (
        "provider_account",
        "region",
        "resource_identity",
        "instance_identity",
        "network_identity",
        "attestation_identity",
        "attestation",
    ):
        item = getattr(observation, field)
        if not isinstance(item, str) or not item or len(item) > 4096 or "\x00" in item:
            raise WorkerTrustError(f"live provider {field} is invalid")
    _timestamp(observation.observed_at, "live provider observed_at")
    return observation


def provider_identity_projection(observation: ProviderObservation) -> Mapping[str, str]:
    return {
        "provider": observation.provider,
        "provider_account_sha256": "sha256:"
        + hashlib.sha256(observation.provider_account.encode("utf-8")).hexdigest(),
        "region": observation.region,
        "resource_identity_sha256": "sha256:"
        + hashlib.sha256(observation.resource_identity.encode("utf-8")).hexdigest(),
        "attestation_identity_sha256": "sha256:"
        + hashlib.sha256(observation.attestation_identity.encode("utf-8")).hexdigest(),
    }


def provider_identity_sha256(observation: ProviderObservation) -> str:
    return _digest(PROVIDER_IDENTITY_DOMAIN, provider_identity_projection(observation))


def live_provider_observation_projection(
    observation: ProviderObservation,
) -> Mapping[str, str]:
    return {
        "provider_identity_sha256": provider_identity_sha256(observation),
        "instance_identity_sha256": "sha256:"
        + hashlib.sha256(observation.instance_identity.encode("utf-8")).hexdigest(),
        "network_identity_sha256": "sha256:"
        + hashlib.sha256(observation.network_identity.encode("utf-8")).hexdigest(),
        "attestation_sha256": "sha256:"
        + hashlib.sha256(observation.attestation.encode("utf-8")).hexdigest(),
        "observed_at": observation.observed_at,
    }


def live_provider_observation_sha256(observation: ProviderObservation) -> str:
    return _digest(
        LIVE_PROVIDER_OBSERVATION_DOMAIN,
        live_provider_observation_projection(observation),
    )


def qualification_worker_identity_sha256(
    *,
    observation: ProviderObservation,
    worker_instance_sha256: str,
    worker_image_sha256: str,
    host_identity_sha256: str,
    admitted_runtime_sha256: str,
) -> str:
    """Derive the central worker identity from verified private openings."""

    projection = {
        "provider_identity_sha256": provider_identity_sha256(observation),
        "worker_instance_sha256": _require_digest(
            worker_instance_sha256,
            "worker instance identity",
        ),
        "worker_image_sha256": _require_digest(
            worker_image_sha256,
            "worker image identity",
        ),
        "host_identity_sha256": _require_digest(
            host_identity_sha256,
            "worker host identity",
        ),
        "admitted_runtime_sha256": _require_digest(
            admitted_runtime_sha256,
            "worker admitted runtime",
        ),
    }
    return _digest(WORKER_IDENTITY_DOMAIN, projection)


@dataclass(frozen=True, init=False)
class VerifiedWorkerAdmission:
    """Opaque positive result returned only by a configured central connector."""

    object: Mapping[str, Any]

    @classmethod
    def _from_authority(cls, value: Mapping[str, Any]) -> VerifiedWorkerAdmission:
        instance = object.__new__(cls)
        object.__setattr__(instance, "object", dict(value))
        return instance


@dataclass(frozen=True, init=False)
class AuthorizedWorkerDispatch:
    """Opaque one-use dispatch plus its non-serializable capability secret."""

    object: Mapping[str, Any]
    capability: bytes

    @classmethod
    def _from_authority(
        cls,
        value: Mapping[str, Any],
        capability: bytes,
    ) -> AuthorizedWorkerDispatch:
        instance = object.__new__(cls)
        object.__setattr__(instance, "object", dict(value))
        object.__setattr__(instance, "capability", bytes(capability))
        return instance


@dataclass(frozen=True, init=False)
class VerifiedWorkerTerminal:
    """Opaque terminal receipt returned by the protected central issuer."""

    object: Mapping[str, Any]

    @classmethod
    def _from_authority(cls, value: Mapping[str, Any]) -> VerifiedWorkerTerminal:
        instance = object.__new__(cls)
        object.__setattr__(instance, "object", dict(value))
        return instance


_ADMISSION_KEYS = {
    "schema_version",
    "verdict",
    "admission_object_sha256",
    "provider_identity_sha256",
    "worker_identity_sha256",
    "live_provider_observation_sha256",
    "admitted_runtime_sha256",
    "worker_image_sha256",
    "baseline_sha256",
    "host_identity_sha256",
    "tls_identity_sha256",
    "egress_policy_sha256",
    "campaign_permit_sha256",
    "capability_handle_sha256",
    "authority_state_sha256",
    "revocation_state_sha256",
    "signer_registry_sha256",
    "not_before",
    "expires_at",
    "verified_at",
    "verifier",
}

_DISPATCH_KEYS = {
    "schema_version",
    "dispatch_id_sha256",
    "worker_admission_sha256",
    "provider_identity_sha256",
    "worker_identity_sha256",
    "live_provider_observation_sha256",
    "admitted_runtime_sha256",
    "run_id",
    "run_attempt",
    "start_id_sha256",
    "task_id_sha256",
    "task_condition_sha256",
    "campaign_artifact_sha256",
    "process_lease_sha256",
    "capability_handle_sha256",
    "idempotency_key",
    "issued_at",
    "not_before",
    "expires_at",
    "issuer",
}

_TERMINAL_KEYS = {
    "schema_version",
    "receipt_id_sha256",
    "worker_admission_sha256",
    "dispatch_id_sha256",
    "provider_identity_sha256",
    "worker_identity_sha256",
    "live_provider_observation_sha256",
    "admitted_runtime_sha256",
    "run_id",
    "run_attempt",
    "start_id_sha256",
    "task_id_sha256",
    "task_condition_sha256",
    "capability_handle_sha256",
    "launch_attempt",
    "launch_attempt_sha256",
    "process",
    "oracle_sha256",
    "result_sha256",
    "log_sha256",
    "burned_identities_sha256",
    "burn_ledger_revision",
    "burned_at",
    "ledger_readback_sha256",
    "burn_receipt_sha256",
    "effect_started",
    "delivery_state",
    "terminal_state",
    "exit_code",
    "uncertainty_sha256",
    "quarantine",
    "completed_at",
    "issuer",
}


def _validate_verifier(value: object) -> None:
    verifier = _closed_mapping(
        value,
        {
            "repository",
            "repository_id",
            "repository_owner_id",
            "workflow",
            "source_commit",
            "runner_environment",
        },
        "worker admission verifier",
    )
    expected = {
        "repository": _CENTRAL_REPOSITORY,
        "repository_id": _CENTRAL_REPOSITORY_ID,
        "repository_owner_id": _CENTRAL_OWNER_ID,
        "workflow": ".github/workflows/verify-qualification-worker-admission.yml",
        "runner_environment": "github-hosted",
    }
    if any(verifier[key] != expected_value for key, expected_value in expected.items()):
        raise WorkerTrustError("worker admission verifier differs")
    if not isinstance(verifier["source_commit"], str) or HEX40.fullmatch(
        verifier["source_commit"]
    ) is None:
        raise WorkerTrustError("worker admission verifier source commit is invalid")


def validate_verified_worker_admission(
    value: object,
    *,
    observation: ProviderObservation,
    worker_identity_sha256: str,
    admitted_runtime_sha256: str,
    worker_image_sha256: str,
    baseline_sha256: str,
    host_identity_sha256: str,
    tls_identity_sha256: str,
    egress_policy_sha256: str,
    now: datetime | None = None,
) -> Mapping[str, Any]:
    result = _closed_mapping(value, _ADMISSION_KEYS, "worker admission verifier result")
    if result["schema_version"] != WORKER_ADMISSION_VERIFIER_RESULT_SCHEMA:
        raise WorkerTrustError("worker admission verifier result schema is invalid")
    if result["verdict"] != "accepted":
        raise WorkerTrustError("worker admission was not accepted")
    for key in _ADMISSION_KEYS - {
        "schema_version",
        "verdict",
        "not_before",
        "expires_at",
        "verified_at",
        "verifier",
    }:
        _require_digest(result[key], f"worker admission {key}")
    expected = {
        "provider_identity_sha256": provider_identity_sha256(observation),
        "live_provider_observation_sha256": live_provider_observation_sha256(observation),
        "worker_identity_sha256": worker_identity_sha256,
        "admitted_runtime_sha256": admitted_runtime_sha256,
        "worker_image_sha256": worker_image_sha256,
        "baseline_sha256": baseline_sha256,
        "host_identity_sha256": host_identity_sha256,
        "tls_identity_sha256": tls_identity_sha256,
        "egress_policy_sha256": egress_policy_sha256,
    }
    if any(result[key] != expected_value for key, expected_value in expected.items()):
        raise WorkerTrustError("worker admission binding differs")
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    not_before = _timestamp(result["not_before"], "worker admission not_before")
    expires = _timestamp(result["expires_at"], "worker admission expires_at")
    verified = _timestamp(result["verified_at"], "worker admission verified_at")
    if not not_before <= verified <= current < expires:
        raise WorkerTrustError("worker admission is not current")
    _validate_verifier(result["verifier"])
    return result


def validate_authorized_dispatch(
    value: object,
    *,
    capability: bytes,
    admission: Mapping[str, Any],
    run_id: str,
    now: datetime | None = None,
) -> Mapping[str, Any]:
    dispatch = _closed_mapping(value, _DISPATCH_KEYS, "worker dispatch")
    if dispatch["schema_version"] != WORKER_DISPATCH_SCHEMA:
        raise WorkerTrustError("worker dispatch schema is invalid")
    if not isinstance(dispatch["run_id"], str) or DECIMAL_ID.fullmatch(
        dispatch["run_id"]
    ) is None:
        raise WorkerTrustError("worker dispatch run id is invalid")
    if not isinstance(
        dispatch["idempotency_key"], str
    ) or DISPATCH_IDEMPOTENCY_KEY.fullmatch(dispatch["idempotency_key"]) is None:
        raise WorkerTrustError("worker dispatch idempotency key is invalid")
    for key in _DISPATCH_KEYS - {
        "schema_version",
        "run_id",
        "run_attempt",
        "idempotency_key",
        "issued_at",
        "not_before",
        "expires_at",
        "issuer",
    }:
        _require_digest(dispatch[key], f"worker dispatch {key}")
    if not capability or len(capability) < 32:
        raise WorkerTrustError("worker dispatch capability is invalid")
    capability_digest = "sha256:" + hashlib.sha256(capability).hexdigest()
    if capability_digest != dispatch["capability_handle_sha256"]:
        raise WorkerTrustError("worker dispatch capability differs")
    if dispatch["capability_handle_sha256"] != admission["capability_handle_sha256"]:
        raise WorkerTrustError("worker dispatch capability is not admitted")
    expected = {
        "worker_admission_sha256": admission["admission_object_sha256"],
        "provider_identity_sha256": admission["provider_identity_sha256"],
        "worker_identity_sha256": admission["worker_identity_sha256"],
        "live_provider_observation_sha256": admission[
            "live_provider_observation_sha256"
        ],
        "admitted_runtime_sha256": admission["admitted_runtime_sha256"],
        "run_id": run_id,
        "run_attempt": "1",
    }
    if any(dispatch[key] != expected_value for key, expected_value in expected.items()):
        raise WorkerTrustError("worker dispatch binding differs")
    start_projection = {
        "worker_admission_sha256": dispatch["worker_admission_sha256"],
        "worker_identity_sha256": dispatch["worker_identity_sha256"],
        "run_id": dispatch["run_id"],
        "run_attempt": dispatch["run_attempt"],
        "task_id_sha256": dispatch["task_id_sha256"],
        "task_condition_sha256": dispatch["task_condition_sha256"],
        "capability_handle_sha256": dispatch["capability_handle_sha256"],
    }
    if _digest(START_ID_DOMAIN, start_projection) != dispatch["start_id_sha256"]:
        raise WorkerTrustError("worker dispatch start identity differs")
    projection = dict(dispatch)
    supplied_dispatch_id = projection.pop("dispatch_id_sha256")
    if _digest(DISPATCH_ID_DOMAIN, projection) != supplied_dispatch_id:
        raise WorkerTrustError("worker dispatch identity differs")
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    issued = _timestamp(dispatch["issued_at"], "worker dispatch issued_at")
    not_before = _timestamp(dispatch["not_before"], "worker dispatch not_before")
    expires = _timestamp(dispatch["expires_at"], "worker dispatch expires_at")
    if not not_before <= issued <= current < expires:
        raise WorkerTrustError("worker dispatch is not current")
    _validate_issuer(
        dispatch["issuer"],
        workflow=".github/workflows/issue-qualification-worker-dispatch.yml",
        environment="qualification-worker-dispatch",
    )
    return dispatch


def validate_worker_terminal(
    value: object,
    *,
    dispatch: Mapping[str, Any],
    admission: Mapping[str, Any],
    terminal_evidence: Mapping[str, Any] | None = None,
) -> Mapping[str, Any]:
    receipt = _closed_mapping(value, _TERMINAL_KEYS, "worker terminal receipt")
    if receipt["schema_version"] != WORKER_TERMINAL_RECEIPT_SCHEMA:
        raise WorkerTrustError("worker terminal receipt schema is invalid")
    launch_attempt = _closed_mapping(
        receipt["launch_attempt"],
        {
            "attempted_at",
            "host_identity_sha256",
            "executable_sha256",
            "capability_handle_sha256",
            "evidence_sha256",
            "child_created",
            "failure_classification",
        },
        "worker terminal launch attempt",
    )
    _timestamp(launch_attempt["attempted_at"], "worker launch attempted_at")
    for key in (
        "host_identity_sha256",
        "executable_sha256",
        "capability_handle_sha256",
        "evidence_sha256",
    ):
        _require_digest(launch_attempt[key], f"worker launch {key}")
    if launch_attempt["host_identity_sha256"] != admission["host_identity_sha256"]:
        raise WorkerTrustError("worker launch host identity differs")
    if launch_attempt["capability_handle_sha256"] != dispatch[
        "capability_handle_sha256"
    ]:
        raise WorkerTrustError("worker launch capability differs")
    if type(launch_attempt["child_created"]) is not bool:
        raise WorkerTrustError("worker launch child_created is invalid")
    if launch_attempt["failure_classification"] not in {
        None,
        "PROCESS_START_REFUSED",
        "PROCESS_START_FAILED",
    }:
        raise WorkerTrustError("worker launch failure classification is invalid")
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
        "run_attempt": dispatch["run_attempt"],
        "start_id_sha256": dispatch["start_id_sha256"],
        "capability_handle_sha256": dispatch["capability_handle_sha256"],
        "launch_attempt": launch_attempt,
    }
    if _digest(LAUNCH_ATTEMPT_IDENTITY_DOMAIN, launch_projection) != receipt[
        "launch_attempt_sha256"
    ]:
        raise WorkerTrustError("worker launch attempt identity differs")
    process: Mapping[str, Any] | None
    if receipt["process"] is None:
        process = None
    else:
        process = _closed_mapping(
            receipt["process"],
            {
                "pid",
                "process_group_id",
                "process_start_ticks",
                "process_start_identity_sha256",
                "launched_at",
                "executable_sha256",
            },
            "worker terminal process",
        )
        for key in ("pid", "process_group_id"):
            if (
                not isinstance(process[key], int)
                or isinstance(process[key], bool)
                or process[key] < 1
            ):
                raise WorkerTrustError(f"worker terminal {key} is invalid")
        if (
            not isinstance(process["process_start_ticks"], str)
            or DECIMAL_ID.fullmatch(process["process_start_ticks"]) is None
        ):
            raise WorkerTrustError("worker terminal process start ticks are invalid")
        _timestamp(process["launched_at"], "worker terminal process launched_at")
        _require_digest(
            process["process_start_identity_sha256"],
            "process start identity",
        )
        _require_digest(process["executable_sha256"], "process executable")
        if process["executable_sha256"] != launch_attempt["executable_sha256"]:
            raise WorkerTrustError("worker launch executable differs")
        if launch_attempt["failure_classification"] is not None:
            raise WorkerTrustError("started process has a launch failure")
        process_projection = {
            "provider_identity_sha256": dispatch["provider_identity_sha256"],
            "worker_identity_sha256": dispatch["worker_identity_sha256"],
            "live_provider_observation_sha256": dispatch[
                "live_provider_observation_sha256"
            ],
            "admitted_runtime_sha256": dispatch["admitted_runtime_sha256"],
            "run_id": dispatch["run_id"],
            "run_attempt": dispatch["run_attempt"],
            "start_id_sha256": dispatch["start_id_sha256"],
            "dispatch_id_sha256": dispatch["dispatch_id_sha256"],
            "pid": process["pid"],
            "process_group_id": process["process_group_id"],
            "process_start_ticks": process["process_start_ticks"],
            "launched_at": process["launched_at"],
            "executable_sha256": process["executable_sha256"],
        }
        if _digest(PROCESS_START_IDENTITY_DOMAIN, process_projection) != process[
            "process_start_identity_sha256"
        ]:
            raise WorkerTrustError("worker terminal process identity differs")
    for key in _TERMINAL_KEYS - {
        "schema_version",
        "run_id",
        "run_attempt",
        "launch_attempt",
        "process",
        "burn_ledger_revision",
        "burned_at",
        "effect_started",
        "delivery_state",
        "terminal_state",
        "exit_code",
        "uncertainty_sha256",
        "quarantine",
        "completed_at",
        "issuer",
    }:
        _require_digest(receipt[key], f"worker terminal {key}")
    expected = {
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
        "task_id_sha256": dispatch["task_id_sha256"],
        "task_condition_sha256": dispatch["task_condition_sha256"],
        "capability_handle_sha256": dispatch["capability_handle_sha256"],
    }
    if any(receipt[key] != expected_value for key, expected_value in expected.items()):
        raise WorkerTrustError("worker terminal binding differs")
    if not isinstance(receipt["run_id"], str) or DECIMAL_ID.fullmatch(
        receipt["run_id"]
    ) is None:
        raise WorkerTrustError("worker terminal run id is invalid")
    if (
        not isinstance(receipt["burn_ledger_revision"], int)
        or receipt["burn_ledger_revision"] <= 0
    ):
        raise WorkerTrustError("worker terminal burn ledger revision is invalid")
    attempted_at = _timestamp(
        launch_attempt["attempted_at"],
        "worker terminal attempted_at",
    )
    burned_at = _timestamp(receipt["burned_at"], "worker terminal burned_at")
    completed_at = _timestamp(receipt["completed_at"], "worker terminal completed_at")
    if attempted_at > burned_at:
        raise WorkerTrustError("worker terminal burned before its launch attempt")
    if process is not None and completed_at < _timestamp(
        process["launched_at"], "worker terminal launched_at"
    ):
        raise WorkerTrustError("worker terminal completed before process launch")
    if completed_at < burned_at:
        raise WorkerTrustError("worker terminal completed before dispatch burn")
    if type(receipt["effect_started"]) is not bool:
        raise WorkerTrustError("worker terminal effect_started is invalid")
    quarantine = _closed_mapping(
        receipt["quarantine"],
        {"active", "reason_code", "evidence_sha256"},
        "worker terminal quarantine",
    )
    if type(quarantine["active"]) is not bool:
        raise WorkerTrustError("worker terminal quarantine active is invalid")
    if quarantine["reason_code"] is not None and (
        not isinstance(quarantine["reason_code"], str)
        or re.fullmatch(r"^[A-Z][A-Z0-9_]{2,63}$", quarantine["reason_code"]) is None
    ):
        raise WorkerTrustError("worker terminal quarantine reason is invalid")
    if quarantine["evidence_sha256"] is not None:
        _require_digest(quarantine["evidence_sha256"], "worker terminal quarantine evidence")
    if quarantine["active"]:
        if quarantine["reason_code"] is None or quarantine["evidence_sha256"] is None:
            raise WorkerTrustError("active quarantine has incomplete evidence")
    elif quarantine["reason_code"] is not None or quarantine["evidence_sha256"] is not None:
        raise WorkerTrustError("inactive quarantine has evidence")
    if receipt["delivery_state"] not in {"not_started", "verified", "uncertain"}:
        raise WorkerTrustError("worker terminal delivery state is invalid")
    if receipt["terminal_state"] not in {
        "VERIFIED",
        "SAFE_HALT",
        "RECONCILIATION_REQUIRED",
        "QUARANTINED",
        "PRELAUNCH_QUARANTINED",
    }:
        raise WorkerTrustError("worker terminal state is invalid")
    if receipt["exit_code"] is not None and (
        not isinstance(receipt["exit_code"], int) or isinstance(receipt["exit_code"], bool)
    ):
        raise WorkerTrustError("worker terminal exit code is invalid")
    uncertain = receipt["delivery_state"] == "uncertain"
    if uncertain:
        if receipt["effect_started"] is not True:
            raise WorkerTrustError("uncertain delivery did not start an effect")
        _require_digest(receipt["uncertainty_sha256"], "worker terminal uncertainty")
        if receipt["terminal_state"] not in {"RECONCILIATION_REQUIRED", "QUARANTINED"}:
            raise WorkerTrustError("uncertain delivery has an invalid terminal state")
        if quarantine["active"] is not True:
            raise WorkerTrustError("uncertain delivery is not quarantined")
    elif receipt["uncertainty_sha256"] is not None:
        raise WorkerTrustError("certain delivery has uncertainty evidence")
    if receipt["terminal_state"] == "VERIFIED" and receipt["delivery_state"] != "verified":
        raise WorkerTrustError("verified terminal receipt has unverified delivery")
    if receipt["terminal_state"] == "VERIFIED" and (
        receipt["exit_code"] != 0 or quarantine["active"]
    ):
        raise WorkerTrustError("verified terminal receipt lacks clean process proof")
    if receipt["terminal_state"] == "SAFE_HALT" and (
        receipt["effect_started"] is not False
        or receipt["delivery_state"] != "not_started"
    ):
        raise WorkerTrustError("safe halt terminal receipt started an effect")
    if receipt["terminal_state"] == "QUARANTINED" and quarantine["active"] is not True:
        raise WorkerTrustError("quarantined terminal receipt lacks quarantine evidence")
    if process is None:
        if (
            receipt["terminal_state"] != "PRELAUNCH_QUARANTINED"
            or receipt["effect_started"] is not False
            or receipt["delivery_state"] != "not_started"
            or receipt["exit_code"] is not None
            or receipt["uncertainty_sha256"] is not None
            or quarantine["active"] is not True
            or launch_attempt["child_created"] is not False
            or launch_attempt["failure_classification"] is None
        ):
            raise WorkerTrustError("prelaunch terminal receipt is invalid")
    else:
        if launch_attempt["child_created"] is not True:
            raise WorkerTrustError("postlaunch terminal receipt has no child proof")
        if receipt["terminal_state"] == "PRELAUNCH_QUARANTINED":
            raise WorkerTrustError("prelaunch terminal receipt has a process")
    burned_projection = {
        "worker_identity_sha256": dispatch["worker_identity_sha256"],
        "run_id": dispatch["run_id"],
        "run_attempt": dispatch["run_attempt"],
        "start_id_sha256": dispatch["start_id_sha256"],
        "dispatch_id_sha256": dispatch["dispatch_id_sha256"],
        "task_id_sha256": dispatch["task_id_sha256"],
        "capability_handle_sha256": dispatch["capability_handle_sha256"],
        "burn_ledger_revision": receipt["burn_ledger_revision"],
        "burned_at": receipt["burned_at"],
    }
    if _digest(BURNED_IDENTITIES_DOMAIN, burned_projection) != receipt[
        "burned_identities_sha256"
    ]:
        raise WorkerTrustError("worker terminal burned identities differ")
    burn_receipt_projection = {
        "burned_identities_sha256": receipt["burned_identities_sha256"],
        "burn_ledger_revision": receipt["burn_ledger_revision"],
        "burned_at": receipt["burned_at"],
        "ledger_readback_sha256": receipt["ledger_readback_sha256"],
    }
    if _digest(BURN_RECEIPT_DOMAIN, burn_receipt_projection) != receipt[
        "burn_receipt_sha256"
    ]:
        raise WorkerTrustError("worker terminal burn receipt differs")
    terminal_projection = dict(receipt)
    supplied_receipt_id = terminal_projection.pop("receipt_id_sha256")
    if _digest(TERMINAL_RECEIPT_IDENTITY_DOMAIN, terminal_projection) != supplied_receipt_id:
        raise WorkerTrustError("worker terminal receipt identity differs")
    if terminal_evidence is not None:
        evidence_process = terminal_evidence.get("process")
        terminal_readback = terminal_evidence.get("terminal_readback")
        if (
            (evidence_process is not None and not isinstance(evidence_process, Mapping))
            or not isinstance(terminal_readback, Mapping)
        ):
            raise WorkerTrustError("worker terminal local evidence is incomplete")
        evidence_launch = terminal_evidence.get("launch_attempt")
        if evidence_launch != launch_attempt:
            raise WorkerTrustError("worker terminal local launch attempt differs")
        evidence_process_projection = (
            None
            if evidence_process is None
            else {
                "pid": evidence_process.get("pid"),
                "process_group_id": evidence_process.get("process_group_id"),
                "process_start_ticks": evidence_process.get("process_start_ticks"),
                "launched_at": evidence_process.get("launched_at"),
                "executable_sha256": evidence_process.get("executable_sha256"),
                "process_start_identity_sha256": evidence_process.get(
                    "process_start_identity_sha256"
                ),
            }
        )
        if evidence_process_projection != process:
            raise WorkerTrustError("worker terminal local process differs")
        burn_evidence = evidence_process if evidence_process is not None else terminal_evidence
        local_burn = {
            "burn_ledger_revision": burn_evidence.get("burn_ledger_revision"),
            "burned_at": burn_evidence.get("burned_at"),
            "ledger_readback_sha256": burn_evidence.get("ledger_readback_sha256"),
        }
        if any(receipt[key] != expected_value for key, expected_value in local_burn.items()):
            raise WorkerTrustError("worker terminal local burn evidence differs")
        if terminal_readback.get("state") == "TERMINAL":
            local_artifacts = {
                "oracle_sha256": terminal_readback.get("oracle_sha256"),
                "result_sha256": terminal_readback.get("result_sha256"),
                "log_sha256": terminal_readback.get("log_sha256"),
                "exit_code": terminal_readback.get("exit_code"),
            }
            if any(
                receipt[key] != expected_value
                for key, expected_value in local_artifacts.items()
            ):
                raise WorkerTrustError("worker terminal local artifact evidence differs")
            if (
                receipt["terminal_state"] == "VERIFIED"
                and terminal_readback.get("oracle_success") is not True
            ):
                raise WorkerTrustError("verified terminal receipt lacks oracle success")
    _validate_issuer(
        receipt["issuer"],
        workflow=".github/workflows/issue-qualification-worker-terminal-receipt.yml",
        environment="qualification-worker-terminal-receipt",
    )
    return receipt


class WorkerTrustAuthority(ABC):
    """Protected connector for central worker admission and one-use authority."""

    def verify_worker(
        self,
        *,
        observation: ProviderObservation,
        worker_identity_sha256: str,
        admitted_runtime_sha256: str,
        worker_image_sha256: str,
        baseline_sha256: str,
        host_identity_sha256: str,
        tls_identity_sha256: str,
        egress_policy_sha256: str,
    ) -> VerifiedWorkerAdmission:
        raw = self._verify_worker(
            observation=observation,
            worker_identity_sha256=worker_identity_sha256,
            admitted_runtime_sha256=admitted_runtime_sha256,
            worker_image_sha256=worker_image_sha256,
            baseline_sha256=baseline_sha256,
            host_identity_sha256=host_identity_sha256,
            tls_identity_sha256=tls_identity_sha256,
            egress_policy_sha256=egress_policy_sha256,
        )
        validated = validate_verified_worker_admission(
            raw,
            observation=observation,
            worker_identity_sha256=worker_identity_sha256,
            admitted_runtime_sha256=admitted_runtime_sha256,
            worker_image_sha256=worker_image_sha256,
            baseline_sha256=baseline_sha256,
            host_identity_sha256=host_identity_sha256,
            tls_identity_sha256=tls_identity_sha256,
            egress_policy_sha256=egress_policy_sha256,
        )
        return VerifiedWorkerAdmission._from_authority(validated)

    def authorize_dispatch(
        self,
        *,
        admission: VerifiedWorkerAdmission,
        run_id: str,
        task_contract: WorkerTaskContract,
    ) -> AuthorizedWorkerDispatch:
        raw, capability = self._authorize_dispatch(
            admission=admission.object,
            run_id=run_id,
            task_selector=task_contract.selector.as_mapping(),
            task_condition=task_contract.condition.as_mapping(),
        )
        validated = validate_authorized_dispatch(
            raw,
            capability=capability,
            admission=admission.object,
            run_id=run_id,
        )
        expected_task_bindings = {
            "campaign_artifact_sha256": (
                task_contract.selector.campaign_artifact_sha256
            ),
            "task_id_sha256": task_contract.selector.task_id_sha256,
            "task_condition_sha256": (
                task_contract.condition.task_condition_sha256
            ),
        }
        if any(
            validated[key] != expected
            for key, expected in expected_task_bindings.items()
        ):
            raise WorkerTrustError("worker dispatch task contract differs")
        return AuthorizedWorkerDispatch._from_authority(validated, capability)

    def issue_terminal(
        self,
        *,
        admission: VerifiedWorkerAdmission,
        dispatch: AuthorizedWorkerDispatch,
        terminal_evidence: Mapping[str, Any],
    ) -> VerifiedWorkerTerminal:
        raw = self._issue_terminal(
            admission=admission.object,
            dispatch=dispatch.object,
            terminal_evidence=terminal_evidence,
        )
        validated = validate_worker_terminal(
            raw,
            dispatch=dispatch.object,
            admission=admission.object,
            terminal_evidence=terminal_evidence,
        )
        return VerifiedWorkerTerminal._from_authority(validated)

    @abstractmethod
    def _verify_worker(self, **bindings: Any) -> Mapping[str, Any]:
        """Resolve the exact signed current admission through central trust v2."""

    @abstractmethod
    def _authorize_dispatch(
        self,
        **bindings: Any,
    ) -> tuple[Mapping[str, Any], bytes]:
        """Atomically consume a capability and return the exact central dispatch."""

    @abstractmethod
    def _issue_terminal(self, **bindings: Any) -> Mapping[str, Any]:
        """Issue a central terminal receipt from independently verified evidence."""
