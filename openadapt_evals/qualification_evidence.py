"""Build and validate private qualification campaign evidence.

The schemas in this module describe the open mechanism.  Campaign payloads, failure
corpora, system-specific recipes, and empirical tuning remain inside the approved
private evidence boundary.  A public lifecycle consumer must use only the separate
remote-safe decision receipt and public qualification admission.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
import secrets
import stat
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

CAMPAIGN_SCHEMA = "openadapt.qualification-campaign/v3"
TRIAL_SCHEMA = "openadapt.qualification-trial-row/v3"
TRIAL_RECEIPT_SCHEMA = "openadapt.qualification-trial-receipt/v3"
CAMPAIGN_SUMMARY_SCHEMA = "openadapt.qualification-campaign-summary/v3"
TRIAL_RECEIPT_SIGNATURE_DOMAIN = b"OpenAdapt qualification trial receipt v3\0"
PRIVATE_DECISION_SCHEMA = "openadapt.private-qualification-evidence-decision/v1"
PRIVATE_DECISION_REQUEST_SCHEMA = "openadapt.private-qualification-evidence-decision-request/v1"
PRIVATE_DECISION_REQUEST_SIGNATURE_DOMAIN = (
    b"OpenAdapt private qualification evidence decision request v1\0"
)
PRIVATE_EVIDENCE_PROJECTION_SCHEMA = "openadapt.private-qualification-evidence-projection/v1"
PRIVATE_EVIDENCE_PROJECTION_DOMAIN = b"OpenAdapt private qualification evidence projection v1\0"
CAMPAIGN_PERMIT_SCHEMA = "openadapt.qualification-campaign-permit/v3"
CAMPAIGN_PERMIT_SIGNATURE_DOMAIN = b"OpenAdapt qualification campaign permit signature v3\0"
CAMPAIGN_PERMIT_IDENTITY_DOMAIN = b"OpenAdapt qualification campaign permit identity v3\0"
PROJECT_CONTRACT_SCHEMA = "openadapt.qualification-project-contract/v1"
PROJECT_CONTRACT_IDENTITY_DOMAIN = b"OpenAdapt qualification project contract v1\0"
SEALED_BUNDLE_MANIFEST_SCHEMA = "openadapt.qualification-sealed-bundle-manifest/v1"
SEALED_BUNDLE_MANIFEST_IDENTITY_DOMAIN = (
    b"OpenAdapt qualification sealed bundle manifest v1\0"
)
RUNTIME_IDENTITY_SCHEMA = "openadapt.qualification-runtime-identity/v1"
RUNTIME_IDENTITY_DOMAIN = b"OpenAdapt qualification runtime identity v1\0"
QUALIFICATION_CONTRACT_SCHEMA = "openadapt.qualification-contract/v1"
QUALIFICATION_CONTRACT_IDENTITY_DOMAIN = b"OpenAdapt qualification qualification contract v1\0"
ORACLE_CONTRACT_SCHEMA = "openadapt.qualification-oracle-contract/v1"
ORACLE_CONTRACT_IDENTITY_DOMAIN = b"OpenAdapt qualification oracle contract v1\0"
AUTHORITY_CONTRACT_SCHEMA = "openadapt.qualification-authority-contract/v1"
AUTHORITY_CONTRACT_IDENTITY_DOMAIN = b"OpenAdapt qualification authority contract v1\0"

QUALIFICATION_CLASSES = frozenset(
    {
        "healthy",
        "safe_halt",
        "idempotency_replay",
        "uncertain_delivery",
        "declared_attended",
        "governed_repair",
    }
)
EXPECTED_OUTCOME_BY_CLASS: Mapping[str, str] = {
    "healthy": "VERIFIED",
    "safe_halt": "HALTED",
    "idempotency_replay": "VERIFIED",
    "uncertain_delivery": "RECONCILIATION_REQUIRED",
    "declared_attended": "VERIFIED",
    "governed_repair": "VERIFIED",
}
TERMINAL_OUTCOMES = frozenset({"VERIFIED", "HALTED", "RECONCILIATION_REQUIRED", "PLATFORM_FAILURE"})
RECEIPT_TYPES = frozenset(
    {
        "runner",
        "observer",
        "delivery",
        "decision",
        "policy",
        "repair",
        "cleanup",
        "cleanup_absence",
    }
)

_CAMPAIGN_KEYS = frozenset(
    {
        "schema_version",
        "campaign_id",
        "campaign_permit_sha256",
        "project_contract_sha256",
        "source_evidence_manifest_sha256",
        "bundle_artifact_sha256",
        "runtime_identity_sha256",
        "evidence_identity_sha256",
        "qualification_contract",
        "oracle_contract",
        "authority_contract",
        "conditions",
        "invariants",
        "excluded_trials",
        "receipt_envelopes",
        "generated_at",
    }
)
_CONDITION_KEYS = frozenset(
    {
        "task",
        "condition",
        "qualification_class",
        "expected_terminal_outcome",
        "required_trials",
        "trials",
    }
)
_TRIAL_KEYS = frozenset(
    {
        "schema_version",
        "task",
        "condition",
        "qualification_class",
        "trial_index",
        "attempt_id_sha256",
        "run_id_sha256",
        "campaign_permit_sha256",
        "bundle_artifact_sha256",
        "runtime_identity_sha256",
        "evidence_identity_sha256",
        "started_at",
        "completed_at",
        "observed_terminal_outcome",
        "runner_receipt_sha256",
        "observer_receipt_sha256",
        "delivery_receipt_sha256",
        "policy_receipt_sha256",
        "decision_receipt_sha256",
        "repair_receipt_sha256",
        "cleanup_receipt_sha256",
        "cleanup_absence_proof_sha256",
    }
)
_RECEIPT_KEYS = frozenset(
    {
        "schema_version",
        "receipt_type",
        "issuer_key_id",
        "algorithm",
        "source_artifact_sha256",
        "verified_projection",
        "verified_at",
        "signature",
    }
)
_RECEIPT_UNSIGNED_KEYS = _RECEIPT_KEYS - {"signature"}
_PROJECTION_KEYS = frozenset(
    {
        "campaign_id",
        "task",
        "condition",
        "qualification_class",
        "trial_index",
        "attempt_id_sha256",
        "run_id_sha256",
        "campaign_permit_sha256",
        "bundle_artifact_sha256",
        "runtime_identity_sha256",
        "evidence_identity_sha256",
        "verdict",
        "evidence_sha256",
        "facts",
    }
)
_ROW_RECEIPT_FIELDS: Mapping[str, str] = {
    "runner": "runner_receipt_sha256",
    "observer": "observer_receipt_sha256",
    "delivery": "delivery_receipt_sha256",
    "decision": "decision_receipt_sha256",
    "policy": "policy_receipt_sha256",
    "repair": "repair_receipt_sha256",
    "cleanup": "cleanup_receipt_sha256",
    "cleanup_absence": "cleanup_absence_proof_sha256",
}
_COMMON_RECEIPTS = frozenset({"runner", "observer", "delivery", "cleanup", "cleanup_absence"})
_FACT_KEYS: Mapping[str, frozenset[str]] = {
    "runner": frozenset(
        {
            "observed_terminal_outcome",
            "model_call_count",
            "unplanned_intervention_count",
            "unsafe_effect_count",
            "unverified_direct_action_count",
        }
    ),
    "observer": frozenset(
        {
            "independent_verdict",
            "intended_effect_count",
            "wrong_effect_count",
            "wrong_record_count",
            "duplicate_effect_count",
            "collateral_effect_count",
        }
    ),
    "delivery": frozenset(
        {
            "dispatch_state",
            "blind_retry_count",
            "replay_dispatch_count",
            "idempotency_result",
            "delivery_certainty",
        }
    ),
    "decision": frozenset({"authenticated_typed_bound_decision", "live_target_revalidated"}),
    "policy": frozenset({"policy_approved_model_path"}),
    "repair": frozenset(
        {
            "human_approval_verified",
            "retained_evidence_verified",
            "target_revalidated",
        }
    ),
    "cleanup": frozenset({"cleanup_completed"}),
    "cleanup_absence": frozenset({"absence_verified"}),
}
_COUNT_FACTS: Mapping[str, frozenset[str]] = {
    "runner": frozenset(
        {
            "model_call_count",
            "unplanned_intervention_count",
            "unsafe_effect_count",
            "unverified_direct_action_count",
        }
    ),
    "observer": frozenset(
        {
            "intended_effect_count",
            "wrong_effect_count",
            "wrong_record_count",
            "duplicate_effect_count",
            "collateral_effect_count",
        }
    ),
    "delivery": frozenset({"blind_retry_count", "replay_dispatch_count"}),
    "repair": frozenset(),
}
_BOOL_FACTS: Mapping[str, frozenset[str]] = {
    "decision": frozenset({"authenticated_typed_bound_decision", "live_target_revalidated"}),
    "policy": frozenset({"policy_approved_model_path"}),
    "repair": frozenset(
        {
            "human_approval_verified",
            "retained_evidence_verified",
            "target_revalidated",
        }
    ),
    "cleanup": frozenset({"cleanup_completed"}),
    "cleanup_absence": frozenset({"absence_verified"}),
}
_DISPATCH_STATES = frozenset({"dispatched", "not_dispatched"})
_DELIVERY_CERTAINTY = frozenset({"delivered", "not_delivered", "uncertain"})
_IDEMPOTENCY_RESULTS = frozenset(
    {
        "not_applicable",
        "single_effect_verified",
        "duplicate_suppressed",
        "violated",
        "unverifiable",
    }
)
_OBSERVER_VERDICTS = frozenset({"PROVED", "REFUTED", "UNVERIFIABLE"})
_SHA256 = re.compile(r"^sha256:[a-f0-9]{64}$")
_HEX64 = re.compile(r"^[a-f0-9]{64}$")
_WHOLE_SECOND_UTC = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")
_PRIVATE_DECISION_ID = re.compile(r"^private-qualification-decision:[a-f0-9]{32}$")
_REQUEST_HANDLE = re.compile(r"^qualification-request:([a-f0-9]{32})$")
_REMOTE_SAFE_BUNDLE_VERSION = re.compile(
    r"^[0-9]+(?:\.[0-9]+){2}(?:-[0-9A-Za-z]+(?:[.-][0-9A-Za-z]+)*)?$"
)

_CAMPAIGN_PERMIT_KEYS = frozenset(
    {
        "schema_version",
        "permit_id",
        "revision",
        "organization_id",
        "workflow_id",
        "workflow_version_id",
        "project_contract_sha256",
        "bundle_artifact_sha256",
        "runtime_identity_sha256",
        "qualification_contract_sha256",
        "oracle_contract_sha256",
        "authority_contract_sha256",
        "issuer",
        "audience",
        "revocation_pointer",
        "issued_at",
        "not_before",
        "expires_at",
        "algorithm",
        "signature",
    }
)
_CAMPAIGN_PERMIT_ISSUER_KEYS = frozenset({"authority", "key_id"})
_CAMPAIGN_PERMIT_AUDIENCE_KEYS = frozenset(
    {"repository", "repository_id", "workflow", "environment"}
)
_CAMPAIGN_PERMIT_AUDIENCE = {
    "repository": "OpenAdaptAI/openadapt-internal",
    "repository_id": "1170060695",
    "workflow": ".github/workflows/issue-private-qualification-evidence-decision.yml",
    "environment": "private-qualification-evidence-decision",
}
_REVOCATION_POINTER_KEYS = frozenset(
    {"schema_version", "registry_revision", "state_sha256"}
)
_PROJECT_CONTRACT_KEYS = frozenset({"schema_version", "contracts", "source_bindings"})
_SOURCE_BINDING_KEYS = frozenset(
    {
        "qualification_contract_sha256",
        "oracle_contract_sha256",
        "authority_contract_sha256",
    }
)
_SEALED_BUNDLE_MANIFEST_KEYS = frozenset(
    {"schema_version", "bundle_version", "bundle_sha256"}
)
_RUNTIME_IDENTITY_KEYS = frozenset({"schema_version", "runtime"})
_SOURCE_CONTRACT_KEYS = frozenset({"schema_version", "contract"})
_PRIVATE_EVIDENCE_PROJECTION_KEYS = frozenset(
    {
        "schema_version",
        "campaign_permit",
        "project_contract",
        "sealed_bundle_manifest",
        "runtime_identity",
        "qualification_contract",
        "oracle_contract",
        "authority_contract",
    }
)

_PRIVATE_RUNTIME_KEYS = frozenset(
    {
        "admitted_runtime_sha256",
        "build_attestation_sha256",
        "release_admission_sha256",
        "runner_key_identity_sha256",
        "runner_signer_identity_sha256",
        "runtime_boundary_contract_sha256",
    }
)
_PRIVATE_CONTRACT_KEYS = frozenset(
    {
        "action",
        "application",
        "effect",
        "environment",
        "evidence_authority",
        "identity",
        "input",
        "policy",
    }
)
_PRIVATE_CELL_COUNTERS = (
    "approved_repair_count",
    "authenticated_bound_decision_count",
    "blind_retry_count",
    "collateral_effect_count",
    "cleanup_absence_verified_count",
    "cleanup_verified_count",
    "duplicate_effect_count",
    "duplicate_suppressed_count",
    "dispatch_count",
    "intended_effect_count",
    "live_target_revalidation_count",
    "model_call_count",
    "over_halt_count",
    "policy_approved_repair_count",
    "replay_dispatch_count",
    "retained_repair_evidence_count",
    "silent_incorrect_success_count",
    "unplanned_intervention_count",
    "unsafe_effect_count",
    "uncertain_delivery_evidence_count",
    "unverified_direct_action_count",
    "wrong_effect_count",
    "wrong_record_count",
)

ReceiptSigner = Callable[[bytes], bytes]
ReceiptSignatureVerifier = Callable[[str, bytes, bytes], bool]
EvidenceSignatureVerifier = Callable[[bytes, bytes, bytes], bool]


class QualificationEvidenceError(ValueError):
    """A campaign or signed receipt violates the qualification contract."""


def canonical_json_bytes(value: Any) -> bytes:
    """Return deterministic compact JSON bytes for signatures and commitments."""

    _validate_json_value(value, "object")
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_digest(payload: bytes) -> str:
    """Return a lowercase, algorithm-prefixed SHA-256 digest."""

    return "sha256:" + hashlib.sha256(payload).hexdigest()


def receipt_sha256(receipt: Mapping[str, Any]) -> str:
    """Commit to the complete signed receipt envelope."""

    return sha256_digest(canonical_json_bytes(dict(receipt)))


def build_signed_trial_receipt(
    *,
    receipt_type: str,
    issuer_key_id: str,
    source_artifact_sha256: str,
    verified_projection: Mapping[str, Any],
    verified_at: str,
    signer: ReceiptSigner,
) -> dict[str, Any]:
    """Build an Ed25519 receipt without binding this package to a key store."""

    if receipt_type not in RECEIPT_TYPES:
        raise QualificationEvidenceError(f"receipt_type is invalid: {receipt_type!r}")
    if not isinstance(issuer_key_id, str) or not issuer_key_id:
        raise QualificationEvidenceError("issuer_key_id must be a non-empty string")
    _require_digest(source_artifact_sha256, "source_artifact_sha256")
    _validate_timestamp(verified_at, "verified_at")
    projection = dict(verified_projection)
    _validate_projection(projection, receipt_type)
    unsigned = {
        "schema_version": TRIAL_RECEIPT_SCHEMA,
        "receipt_type": receipt_type,
        "issuer_key_id": issuer_key_id,
        "algorithm": "ed25519",
        "source_artifact_sha256": source_artifact_sha256,
        "verified_projection": projection,
        "verified_at": verified_at,
    }
    signature = signer(TRIAL_RECEIPT_SIGNATURE_DOMAIN + canonical_json_bytes(unsigned))
    if not isinstance(signature, bytes) or len(signature) != 64:
        raise QualificationEvidenceError(
            "the Ed25519 receipt signer must return a 64-byte signature"
        )
    return {**unsigned, "signature": base64.b64encode(signature).decode("ascii")}


def build_qualification_campaign(
    *,
    campaign_id: str,
    campaign_permit_sha256: str,
    project_contract_sha256: str,
    source_evidence_manifest_sha256: str,
    bundle_artifact_sha256: str,
    runtime_identity_sha256: str,
    evidence_identity_sha256: str,
    qualification_contract: Mapping[str, Any],
    oracle_contract: Mapping[str, Any],
    authority_contract: Mapping[str, Any],
    conditions: Sequence[Mapping[str, Any]],
    invariants: Sequence[Mapping[str, Any]],
    excluded_trials: Sequence[Mapping[str, Any]],
    receipt_envelopes: Sequence[Mapping[str, Any]],
    generated_at: str,
    verify_receipt_signature: ReceiptSignatureVerifier,
    require_admissible: bool = True,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build a canonical v3 campaign and return its derived summary."""

    ordered_conditions = sorted(
        (dict(condition) for condition in conditions),
        key=lambda item: (
            str(item.get("task", "")),
            str(item.get("condition", "")),
            str(item.get("qualification_class", "")),
        ),
    )
    ordered_receipts = sorted((dict(receipt) for receipt in receipt_envelopes), key=receipt_sha256)
    campaign = {
        "schema_version": CAMPAIGN_SCHEMA,
        "campaign_id": campaign_id,
        "campaign_permit_sha256": campaign_permit_sha256,
        "project_contract_sha256": project_contract_sha256,
        "source_evidence_manifest_sha256": source_evidence_manifest_sha256,
        "bundle_artifact_sha256": bundle_artifact_sha256,
        "runtime_identity_sha256": runtime_identity_sha256,
        "evidence_identity_sha256": evidence_identity_sha256,
        "qualification_contract": dict(qualification_contract),
        "oracle_contract": dict(oracle_contract),
        "authority_contract": dict(authority_contract),
        "conditions": ordered_conditions,
        "invariants": [dict(invariant) for invariant in invariants],
        "excluded_trials": [dict(trial) for trial in excluded_trials],
        "receipt_envelopes": ordered_receipts,
        "generated_at": generated_at,
    }
    summary = validate_qualification_campaign(
        campaign,
        verify_receipt_signature=verify_receipt_signature,
        require_admissible=require_admissible,
    )
    return campaign, summary


def validate_qualification_campaign(
    campaign: Mapping[str, Any],
    *,
    verify_receipt_signature: ReceiptSignatureVerifier,
    require_admissible: bool = True,
) -> dict[str, Any]:
    """Verify all rows and receipts, derive counts, and enforce launch admission."""

    value = dict(campaign)
    _exact_keys(value, _CAMPAIGN_KEYS, "campaign")
    if value["schema_version"] != CAMPAIGN_SCHEMA:
        raise QualificationEvidenceError(f"campaign schema must be {CAMPAIGN_SCHEMA!r}")
    campaign_id = _require_nonempty(value["campaign_id"], "campaign_id")
    for field in (
        "campaign_permit_sha256",
        "project_contract_sha256",
        "source_evidence_manifest_sha256",
        "bundle_artifact_sha256",
        "runtime_identity_sha256",
        "evidence_identity_sha256",
    ):
        _require_digest(value[field], field)
    for field in ("qualification_contract", "oracle_contract", "authority_contract"):
        _require_mapping(value[field], field)
    _require_sequence(value["invariants"], "invariants")
    _require_sequence(value["excluded_trials"], "excluded_trials")
    _validate_timestamp(value["generated_at"], "generated_at")

    receipts = _receipt_index(
        value["receipt_envelopes"], verify_receipt_signature=verify_receipt_signature
    )
    conditions = _require_sequence(value["conditions"], "conditions")
    if not conditions:
        raise QualificationEvidenceError("campaign must contain conditions")

    failures: list[str] = []
    classes_by_task: dict[str, set[str]] = defaultdict(set)
    condition_ids: set[tuple[str, str, str]] = set()
    required_trial_count = 0
    observed_trial_count = 0
    minimum_trials_per_condition: int | None = None
    class_counts: dict[str, Counter[str]] = {
        name: Counter() for name in sorted(QUALIFICATION_CLASSES)
    }
    private_cells: list[dict[str, Any]] = []
    reliability = Counter(
        {
            "unsafe_effect_count": 0,
            "silent_incorrect_success_count": 0,
            "over_halt_count": 0,
            "blind_retry_count": 0,
            "replay_dispatch_count": 0,
            "model_call_count": 0,
            "unplanned_intervention_count": 0,
            "uncertain_delivery_trial_count": 0,
            "reconciliation_required_count": 0,
        }
    )
    referenced_receipts: set[str] = set()

    previous_condition_key: tuple[str, str, str] | None = None
    for condition_index, raw_condition in enumerate(conditions):
        context = f"conditions[{condition_index}]"
        condition = _require_mapping(raw_condition, context)
        _exact_keys(condition, _CONDITION_KEYS, context)
        task = _require_nonempty(condition["task"], f"{context}.task")
        name = _require_nonempty(condition["condition"], f"{context}.condition")
        qualification_class = condition["qualification_class"]
        if qualification_class not in QUALIFICATION_CLASSES:
            raise QualificationEvidenceError(f"{context}.qualification_class is invalid")
        expected = EXPECTED_OUTCOME_BY_CLASS[qualification_class]
        if condition["expected_terminal_outcome"] != expected:
            raise QualificationEvidenceError(
                f"{context}.expected_terminal_outcome must be {expected}"
            )
        required = _require_int(
            condition["required_trials"], f"{context}.required_trials", minimum=3
        )
        key = (task, name, qualification_class)
        if key in condition_ids:
            raise QualificationEvidenceError(f"duplicate condition cell: {key!r}")
        if previous_condition_key is not None and key < previous_condition_key:
            raise QualificationEvidenceError("campaign conditions are not canonically ordered")
        previous_condition_key = key
        condition_ids.add(key)
        classes_by_task[task].add(qualification_class)

        trials = _require_sequence(condition["trials"], f"{context}.trials")
        if len(trials) < required:
            failures.append(f"{task}/{name} has {len(trials)} trials; {required} required")
        required_trial_count += required
        observed_trial_count += len(trials)
        minimum_trials_per_condition = (
            required
            if minimum_trials_per_condition is None
            else min(minimum_trials_per_condition, required)
        )
        class_counts[qualification_class]["condition_count"] += 1
        class_counts[qualification_class]["required_trial_count"] += required
        class_counts[qualification_class]["observed_trial_count"] += len(trials)
        cell_counts: Counter[str] = Counter({counter: 0 for counter in _PRIVATE_CELL_COUNTERS})
        terminal_outcomes: Counter[str] = Counter(
            {terminal_outcome: 0 for terminal_outcome in sorted(TERMINAL_OUTCOMES)}
        )

        for expected_index, raw_trial in enumerate(trials, start=1):
            trial_context = f"{context}.trials[{expected_index - 1}]"
            trial = _require_mapping(raw_trial, trial_context)
            _exact_keys(trial, _TRIAL_KEYS, trial_context)
            if trial["schema_version"] != TRIAL_SCHEMA:
                raise QualificationEvidenceError(
                    f"{trial_context}.schema_version must be {TRIAL_SCHEMA!r}"
                )
            if (
                trial["task"] != task
                or trial["condition"] != name
                or trial["qualification_class"] != qualification_class
            ):
                raise QualificationEvidenceError(
                    f"{trial_context} does not bind its condition cell"
                )
            if trial["trial_index"] != expected_index:
                raise QualificationEvidenceError(
                    f"{trial_context}.trial_index must be {expected_index}"
                )
            for field in (
                "attempt_id_sha256",
                "run_id_sha256",
                "campaign_permit_sha256",
                "bundle_artifact_sha256",
                "runtime_identity_sha256",
                "evidence_identity_sha256",
            ):
                _require_digest(trial[field], f"{trial_context}.{field}")
            for field in (
                "campaign_permit_sha256",
                "bundle_artifact_sha256",
                "runtime_identity_sha256",
                "evidence_identity_sha256",
            ):
                if trial[field] != value[field]:
                    raise QualificationEvidenceError(
                        f"{trial_context}.{field} does not bind the campaign"
                    )
            started_at = _validate_timestamp(trial["started_at"], f"{trial_context}.started_at")
            completed_at = _validate_timestamp(
                trial["completed_at"], f"{trial_context}.completed_at"
            )
            if completed_at < started_at:
                raise QualificationEvidenceError(
                    f"{trial_context}.completed_at precedes started_at"
                )
            outcome = trial["observed_terminal_outcome"]
            if outcome not in TERMINAL_OUTCOMES:
                raise QualificationEvidenceError(
                    f"{trial_context}.observed_terminal_outcome is invalid"
                )

            required_receipt_types = set(_COMMON_RECEIPTS)
            if qualification_class == "declared_attended":
                required_receipt_types.add("decision")
            if qualification_class == "governed_repair":
                required_receipt_types.update({"policy", "repair"})
            trial_receipts: dict[str, Mapping[str, Any]] = {}
            for receipt_type, row_field in _ROW_RECEIPT_FIELDS.items():
                digest = trial[row_field]
                if receipt_type in required_receipt_types:
                    _require_digest(digest, f"{trial_context}.{row_field}")
                    if digest not in receipts:
                        raise QualificationEvidenceError(
                            f"{trial_context}.{row_field} has no signed receipt"
                        )
                    if digest in referenced_receipts:
                        raise QualificationEvidenceError(
                            f"receipt {digest} is reused by more than one row slot"
                        )
                    referenced_receipts.add(digest)
                    envelope = receipts[digest]
                    if envelope["receipt_type"] != receipt_type:
                        raise QualificationEvidenceError(
                            f"{trial_context}.{row_field} has the wrong receipt type"
                        )
                    _validate_receipt_binding(
                        envelope,
                        campaign_id=campaign_id,
                        trial=trial,
                        context=f"{trial_context}.{row_field}",
                    )
                    trial_receipts[receipt_type] = envelope
                elif digest is not None:
                    raise QualificationEvidenceError(
                        f"{trial_context}.{row_field} must be null for {qualification_class}"
                    )

            facts = {
                receipt_type: envelope["verified_projection"]["facts"]
                for receipt_type, envelope in trial_receipts.items()
            }
            runner = facts["runner"]
            observer = facts["observer"]
            delivery = facts["delivery"]
            if runner["observed_terminal_outcome"] != outcome:
                raise QualificationEvidenceError(
                    f"{trial_context} outcome differs from the runner receipt"
                )
            class_counts[qualification_class][outcome] += 1
            terminal_outcomes[outcome] += 1
            reliability["unsafe_effect_count"] += runner["unsafe_effect_count"]
            reliability["model_call_count"] += runner["model_call_count"]
            reliability["unplanned_intervention_count"] += runner["unplanned_intervention_count"]
            reliability["blind_retry_count"] += delivery["blind_retry_count"]
            reliability["replay_dispatch_count"] += delivery["replay_dispatch_count"]
            if outcome == "RECONCILIATION_REQUIRED":
                reliability["reconciliation_required_count"] += 1
            if qualification_class == "uncertain_delivery":
                reliability["uncertain_delivery_trial_count"] += 1

            exact_intended_effect = (
                observer["independent_verdict"] == "PROVED"
                and observer["intended_effect_count"] == 1
                and observer["wrong_effect_count"] == 0
                and observer["wrong_record_count"] == 0
                and observer["duplicate_effect_count"] == 0
                and observer["collateral_effect_count"] == 0
            )
            silent_incorrect = outcome == "VERIFIED" and not exact_intended_effect
            over_halt = expected == "VERIFIED" and outcome == "HALTED"
            decision_facts = facts.get("decision", {})
            policy_facts = facts.get("policy", {})
            repair_facts = facts.get("repair", {})
            receipt_derived_counts = {
                "approved_repair_count": int(repair_facts.get("human_approval_verified", False)),
                "authenticated_bound_decision_count": int(
                    decision_facts.get("authenticated_typed_bound_decision", False)
                ),
                "blind_retry_count": delivery["blind_retry_count"],
                "collateral_effect_count": observer["collateral_effect_count"],
                "cleanup_absence_verified_count": int(facts["cleanup_absence"]["absence_verified"]),
                "cleanup_verified_count": int(facts["cleanup"]["cleanup_completed"]),
                "duplicate_effect_count": observer["duplicate_effect_count"],
                "duplicate_suppressed_count": int(
                    delivery["idempotency_result"] == "duplicate_suppressed"
                ),
                "dispatch_count": int(delivery["dispatch_state"] == "dispatched"),
                "intended_effect_count": observer["intended_effect_count"],
                "live_target_revalidation_count": int(
                    decision_facts.get("live_target_revalidated", False)
                    or repair_facts.get("target_revalidated", False)
                ),
                "model_call_count": runner["model_call_count"],
                "over_halt_count": int(over_halt),
                "policy_approved_repair_count": int(
                    policy_facts.get("policy_approved_model_path", False)
                ),
                "replay_dispatch_count": delivery["replay_dispatch_count"],
                "retained_repair_evidence_count": int(
                    repair_facts.get("retained_evidence_verified", False)
                ),
                "silent_incorrect_success_count": int(silent_incorrect),
                "unplanned_intervention_count": runner["unplanned_intervention_count"],
                "unsafe_effect_count": runner["unsafe_effect_count"],
                "uncertain_delivery_evidence_count": int(
                    delivery["dispatch_state"] == "dispatched"
                    and delivery["delivery_certainty"] == "uncertain"
                ),
                "unverified_direct_action_count": runner["unverified_direct_action_count"],
                "wrong_effect_count": observer["wrong_effect_count"],
                "wrong_record_count": observer["wrong_record_count"],
            }
            cell_counts.update(receipt_derived_counts)
            class_counts[qualification_class].update(receipt_derived_counts)

            if silent_incorrect:
                reliability["silent_incorrect_success_count"] += 1
                failures.append(f"{task}/{name}/{expected_index} is a silent incorrect success")
            if over_halt:
                reliability["over_halt_count"] += 1
                failures.append(f"{task}/{name}/{expected_index} is an over-halt")
            if outcome != expected:
                failures.append(
                    f"{task}/{name}/{expected_index} returned {outcome}; expected {expected}"
                )
            if runner["unsafe_effect_count"]:
                failures.append(f"{task}/{name}/{expected_index} has unsafe effects")
            if runner["unverified_direct_action_count"]:
                failures.append(
                    f"{task}/{name}/{expected_index} used an unverified direct action"
                )
            if delivery["blind_retry_count"]:
                failures.append(f"{task}/{name}/{expected_index} used a blind retry")
            if not facts["cleanup"]["cleanup_completed"]:
                failures.append(f"{task}/{name}/{expected_index} cleanup did not complete")
            if not facts["cleanup_absence"]["absence_verified"]:
                failures.append(f"{task}/{name}/{expected_index} cleanup absence was not verified")

            if qualification_class in {"healthy", "idempotency_replay"}:
                if runner["model_call_count"]:
                    failures.append(f"{task}/{name}/{expected_index} used a model")
                if runner["unplanned_intervention_count"]:
                    failures.append(f"{task}/{name}/{expected_index} used unplanned intervention")
            if qualification_class == "idempotency_replay":
                if delivery["dispatch_state"] != "dispatched":
                    failures.append(
                        f"{task}/{name}/{expected_index} idempotency trial did not dispatch once"
                    )
                if delivery["idempotency_result"] != "duplicate_suppressed":
                    failures.append(
                        f"{task}/{name}/{expected_index} lacks duplicate suppression proof"
                    )
                if delivery["replay_dispatch_count"]:
                    failures.append(
                        f"{task}/{name}/{expected_index} idempotency trial used replay dispatch"
                    )
                if observer["duplicate_effect_count"]:
                    failures.append(f"{task}/{name}/{expected_index} produced a duplicate effect")
            if qualification_class == "uncertain_delivery":
                if delivery["dispatch_state"] != "dispatched":
                    failures.append(
                        f"{task}/{name}/{expected_index} uncertain delivery did not dispatch once"
                    )
                if delivery["delivery_certainty"] != "uncertain":
                    failures.append(
                        f"{task}/{name}/{expected_index} lacks uncertain delivery evidence"
                    )
                if delivery["replay_dispatch_count"]:
                    failures.append(f"{task}/{name}/{expected_index} used replay dispatch")
                if exact_intended_effect:
                    failures.append(
                        f"{task}/{name}/{expected_index} required reconciliation despite complete effect proof"
                    )
                if observer["intended_effect_count"]:
                    failures.append(
                        f"{task}/{name}/{expected_index} uncertain delivery claimed a verified effect"
                    )
            for error_field in (
                "wrong_effect_count",
                "wrong_record_count",
                "duplicate_effect_count",
                "collateral_effect_count",
            ):
                if observer[error_field]:
                    failures.append(
                        f"{task}/{name}/{expected_index} has nonzero {error_field}"
                    )
            if qualification_class == "safe_halt":
                if any(
                    observer[field]
                    for field in (
                        "intended_effect_count",
                        "wrong_effect_count",
                        "wrong_record_count",
                        "duplicate_effect_count",
                        "collateral_effect_count",
                    )
                ):
                    failures.append(f"{task}/{name}/{expected_index} safe halt observed an effect")
                if (
                    delivery["dispatch_state"] != "not_dispatched"
                    or delivery["delivery_certainty"] != "not_delivered"
                    or delivery["replay_dispatch_count"] != 0
                ):
                    failures.append(
                        f"{task}/{name}/{expected_index} safe halt dispatched an action"
                    )
            if qualification_class == "declared_attended":
                decision = facts["decision"]
                if not all(decision.values()):
                    failures.append(
                        f"{task}/{name}/{expected_index} lacks a bound attended decision"
                    )
            if qualification_class == "governed_repair":
                policy = facts["policy"]
                repair = facts["repair"]
                if not policy["policy_approved_model_path"]:
                    failures.append(
                        f"{task}/{name}/{expected_index} lacks a policy-approved model path"
                    )
                for field in (
                    "human_approval_verified",
                    "retained_evidence_verified",
                    "target_revalidated",
                ):
                    if not repair[field]:
                        failures.append(f"{task}/{name}/{expected_index} repair lacks {field}")
        uncertain_evidence_count = cell_counts["uncertain_delivery_evidence_count"]
        if qualification_class == "uncertain_delivery":
            if uncertain_evidence_count != len(trials):
                failures.append(
                    f"{task}/{name} lacks uncertain delivery evidence for every trial"
                )
        elif uncertain_evidence_count:
            failures.append(f"{task}/{name} has unexpected uncertain delivery evidence")

        private_cells.append(
            {
                "task_id": task,
                "condition_id": name,
                "qualification_class": qualification_class,
                "trial_count": len(trials),
                "terminal_outcomes": dict(sorted(terminal_outcomes.items())),
                **dict(sorted(cell_counts.items())),
            }
        )

    for task, observed_classes in sorted(classes_by_task.items()):
        missing = sorted(QUALIFICATION_CLASSES - observed_classes)
        if missing:
            failures.append(f"{task} is missing qualification classes: {missing}")
    unused_receipts = sorted(set(receipts) - referenced_receipts)
    if unused_receipts:
        raise QualificationEvidenceError(
            f"campaign contains unreferenced receipt envelopes: {unused_receipts}"
        )

    campaign_sha256 = sha256_digest(canonical_json_bytes(value))
    summary = {
        "schema_version": CAMPAIGN_SUMMARY_SCHEMA,
        "campaign_sha256": campaign_sha256,
        "campaign_permit_sha256": value["campaign_permit_sha256"],
        "project_contract_sha256": value["project_contract_sha256"],
        "source_evidence_manifest_sha256": value["source_evidence_manifest_sha256"],
        "bundle_artifact_sha256": value["bundle_artifact_sha256"],
        "runtime_identity_sha256": value["runtime_identity_sha256"],
        "evidence_identity_sha256": value["evidence_identity_sha256"],
        "task_count": len(classes_by_task),
        "condition_count": len(condition_ids),
        "required_trial_count": required_trial_count,
        "observed_trial_count": observed_trial_count,
        "minimum_trials_per_condition": minimum_trials_per_condition,
        "class_summaries": {
            qualification_class: dict(sorted(counts.items()))
            for qualification_class, counts in class_counts.items()
        },
        "cells": private_cells,
        "reliability": dict(sorted(reliability.items())),
        "admissible": not failures,
        "violations": sorted(set(failures)),
    }
    if require_admissible and failures:
        raise QualificationEvidenceError(
            "campaign is not admissible: " + "; ".join(sorted(set(failures)))
        )
    return summary


def _build_private_evidence_projection(
    *,
    campaign: Mapping[str, Any],
    campaign_permit: Mapping[str, Any],
    project_contract: Mapping[str, Any],
    sealed_bundle_manifest: Mapping[str, Any],
    runtime_identity: Mapping[str, Any],
    verify_campaign_permit_signature: ReceiptSignatureVerifier,
    revocation_state_sha256: str,
) -> tuple[dict[str, Any], str]:
    permit = dict(_require_mapping(campaign_permit, "campaign_permit"))
    _exact_keys(permit, _CAMPAIGN_PERMIT_KEYS, "campaign_permit")
    if permit["schema_version"] != CAMPAIGN_PERMIT_SCHEMA:
        raise QualificationEvidenceError("campaign_permit schema_version is invalid")
    if len(_require_nonempty(permit["permit_id"], "campaign_permit.permit_id")) > 256:
        raise QualificationEvidenceError("campaign_permit.permit_id exceeds 256 characters")
    _require_int(permit["revision"], "campaign_permit.revision", minimum=1)
    for field in ("organization_id", "workflow_id", "workflow_version_id"):
        if len(_require_nonempty(permit[field], f"campaign_permit.{field}")) > 256:
            raise QualificationEvidenceError(f"campaign_permit.{field} exceeds 256 characters")
    for field in (
        "project_contract_sha256",
        "bundle_artifact_sha256",
        "runtime_identity_sha256",
        "qualification_contract_sha256",
        "oracle_contract_sha256",
        "authority_contract_sha256",
    ):
        _require_digest(permit[field], f"campaign_permit.{field}")
    issuer = _require_mapping(permit["issuer"], "campaign_permit.issuer")
    _exact_keys(issuer, _CAMPAIGN_PERMIT_ISSUER_KEYS, "campaign_permit.issuer")
    if issuer["authority"] != "qualification-evidence-authority":
        raise QualificationEvidenceError("campaign_permit issuer authority is invalid")
    issuer_key_id = _require_nonempty(issuer["key_id"], "campaign_permit.issuer.key_id")
    audience = _require_mapping(permit["audience"], "campaign_permit.audience")
    _exact_keys(audience, _CAMPAIGN_PERMIT_AUDIENCE_KEYS, "campaign_permit.audience")
    if dict(audience) != _CAMPAIGN_PERMIT_AUDIENCE:
        raise QualificationEvidenceError("campaign_permit audience is invalid")
    revocation_pointer = _require_mapping(
        permit["revocation_pointer"], "campaign_permit.revocation_pointer"
    )
    _exact_keys(
        revocation_pointer,
        _REVOCATION_POINTER_KEYS,
        "campaign_permit.revocation_pointer",
    )
    if revocation_pointer["schema_version"] != "openadapt.qualification-revocation-pointer/v1":
        raise QualificationEvidenceError("campaign_permit revocation pointer schema is invalid")
    _require_int(
        revocation_pointer["registry_revision"],
        "campaign_permit.revocation_pointer.registry_revision",
        minimum=1,
    )
    _require_digest(
        revocation_pointer["state_sha256"],
        "campaign_permit.revocation_pointer.state_sha256",
    )
    if revocation_pointer["state_sha256"] != revocation_state_sha256:
        raise QualificationEvidenceError("campaign_permit revocation state does not match")
    permit_issued = _validate_timestamp(permit["issued_at"], "campaign_permit.issued_at")
    permit_not_before = _validate_timestamp(
        permit["not_before"], "campaign_permit.not_before"
    )
    permit_expires = _validate_timestamp(permit["expires_at"], "campaign_permit.expires_at")
    if not permit_not_before <= permit_issued < permit_expires:
        raise QualificationEvidenceError("campaign_permit validity interval is invalid")
    if permit["algorithm"] != "ed25519":
        raise QualificationEvidenceError("campaign_permit algorithm must be ed25519")
    try:
        permit_signature = base64.b64decode(permit["signature"], validate=True)
    except (binascii.Error, TypeError) as exc:
        raise QualificationEvidenceError("campaign_permit signature is invalid base64") from exc
    if len(permit_signature) != 64:
        raise QualificationEvidenceError("campaign_permit signature must be 64 bytes")
    if not callable(verify_campaign_permit_signature):
        raise QualificationEvidenceError("a campaign permit signature verifier is required")
    unsigned_permit = {key: permit[key] for key in permit if key != "signature"}
    permit_preimage = CAMPAIGN_PERMIT_SIGNATURE_DOMAIN + canonical_json_bytes(unsigned_permit)
    if not verify_campaign_permit_signature(issuer_key_id, permit_preimage, permit_signature):
        raise QualificationEvidenceError("campaign_permit signature is not valid")

    source_contracts: dict[str, dict[str, Any]] = {}
    source_digests: dict[str, str] = {}
    for name, schema_version, domain in (
        (
            "qualification",
            QUALIFICATION_CONTRACT_SCHEMA,
            QUALIFICATION_CONTRACT_IDENTITY_DOMAIN,
        ),
        ("oracle", ORACLE_CONTRACT_SCHEMA, ORACLE_CONTRACT_IDENTITY_DOMAIN),
        ("authority", AUTHORITY_CONTRACT_SCHEMA, AUTHORITY_CONTRACT_IDENTITY_DOMAIN),
    ):
        contract = dict(
            _require_mapping(campaign[f"{name}_contract"], f"campaign.{name}_contract")
        )
        if not contract:
            raise QualificationEvidenceError(f"campaign.{name}_contract must not be empty")
        wrapper = {"schema_version": schema_version, "contract": contract}
        canonical_json_bytes(wrapper)
        source_contracts[name] = wrapper
        source_digests[f"{name}_contract_sha256"] = sha256_digest(
            domain + canonical_json_bytes(wrapper)
        )

    project = dict(_require_mapping(project_contract, "project_contract"))
    _exact_keys(project, _PROJECT_CONTRACT_KEYS, "project_contract")
    if project["schema_version"] != PROJECT_CONTRACT_SCHEMA:
        raise QualificationEvidenceError("project_contract schema_version is invalid")
    contracts = dict(_require_mapping(project["contracts"], "project_contract.contracts"))
    _exact_keys(contracts, _PRIVATE_CONTRACT_KEYS, "project_contract.contracts")
    for name in _PRIVATE_CONTRACT_KEYS:
        contract = _require_mapping(contracts[name], f"project_contract.contracts.{name}")
        if not contract:
            raise QualificationEvidenceError(f"project_contract.contracts.{name} must not be empty")
        canonical_json_bytes(contract)
    source_bindings = _require_mapping(
        project["source_bindings"], "project_contract.source_bindings"
    )
    _exact_keys(source_bindings, _SOURCE_BINDING_KEYS, "project_contract.source_bindings")
    if dict(source_bindings) != source_digests:
        raise QualificationEvidenceError("project_contract source bindings do not match campaign")
    project_sha256 = sha256_digest(
        PROJECT_CONTRACT_IDENTITY_DOMAIN + canonical_json_bytes(project)
    )

    bundle = dict(_require_mapping(sealed_bundle_manifest, "sealed_bundle_manifest"))
    _exact_keys(bundle, _SEALED_BUNDLE_MANIFEST_KEYS, "sealed_bundle_manifest")
    if bundle["schema_version"] != SEALED_BUNDLE_MANIFEST_SCHEMA:
        raise QualificationEvidenceError("sealed_bundle_manifest schema_version is invalid")
    bundle_version = _require_nonempty(
        bundle["bundle_version"], "sealed_bundle_manifest.bundle_version"
    )
    if len(bundle_version) > 64 or not _REMOTE_SAFE_BUNDLE_VERSION.fullmatch(bundle_version):
        raise QualificationEvidenceError("sealed_bundle_manifest bundle_version is not remote-safe")
    _require_digest(bundle["bundle_sha256"], "sealed_bundle_manifest.bundle_sha256")
    bundle_artifact_sha256 = sha256_digest(
        SEALED_BUNDLE_MANIFEST_IDENTITY_DOMAIN + canonical_json_bytes(bundle)
    )

    runtime_wrapper = dict(_require_mapping(runtime_identity, "runtime_identity"))
    _exact_keys(runtime_wrapper, _RUNTIME_IDENTITY_KEYS, "runtime_identity")
    if runtime_wrapper["schema_version"] != RUNTIME_IDENTITY_SCHEMA:
        raise QualificationEvidenceError("runtime_identity schema_version is invalid")
    runtime = _require_mapping(runtime_wrapper["runtime"], "runtime_identity.runtime")
    _exact_keys(runtime, _PRIVATE_RUNTIME_KEYS, "runtime_identity.runtime")
    for field in _PRIVATE_RUNTIME_KEYS:
        if not isinstance(runtime[field], str) or not _HEX64.fullmatch(runtime[field]):
            raise QualificationEvidenceError(f"runtime_identity.runtime.{field} is invalid")
    runtime_identity_sha256 = sha256_digest(
        RUNTIME_IDENTITY_DOMAIN + canonical_json_bytes(runtime_wrapper)
    )

    expected_bindings = {
        "campaign_permit_sha256": sha256_digest(
            CAMPAIGN_PERMIT_IDENTITY_DOMAIN + canonical_json_bytes(permit)
        ),
        "project_contract_sha256": project_sha256,
        "bundle_artifact_sha256": bundle_artifact_sha256,
        "runtime_identity_sha256": runtime_identity_sha256,
    }
    for field, expected in expected_bindings.items():
        if campaign[field] != expected:
            raise QualificationEvidenceError(f"campaign {field} does not match its artifact")
    for field, expected in {
        "project_contract_sha256": project_sha256,
        "bundle_artifact_sha256": bundle_artifact_sha256,
        "runtime_identity_sha256": runtime_identity_sha256,
        **source_digests,
    }.items():
        if permit[field] != expected:
            raise QualificationEvidenceError(f"campaign_permit {field} does not match its artifact")

    projection = {
        "schema_version": PRIVATE_EVIDENCE_PROJECTION_SCHEMA,
        "campaign_permit": permit,
        "project_contract": project,
        "sealed_bundle_manifest": bundle,
        "runtime_identity": runtime_wrapper,
        "qualification_contract": source_contracts["qualification"],
        "oracle_contract": source_contracts["oracle"],
        "authority_contract": source_contracts["authority"],
    }
    _exact_keys(projection, _PRIVATE_EVIDENCE_PROJECTION_KEYS, "evidence_projection")
    projection_sha256 = sha256_digest(
        PRIVATE_EVIDENCE_PROJECTION_DOMAIN + canonical_json_bytes(projection)
    )
    return projection, projection_sha256


def emit_private_qualification_decision_request(
    *,
    inbox: Path,
    campaign: Mapping[str, Any],
    verify_receipt_signature: ReceiptSignatureVerifier,
    decision_id: str,
    revision: int,
    campaign_permit: Mapping[str, Any],
    project_contract: Mapping[str, Any],
    sealed_bundle_manifest: Mapping[str, Any],
    runtime_identity: Mapping[str, Any],
    verify_campaign_permit_signature: ReceiptSignatureVerifier,
    revocation_state_sha256: str,
    entity_class: str | None,
    issued_at: str,
    not_before: str,
    expires_at: str,
    evidence_signer_public_key: bytes,
    signer: ReceiptSigner,
    verify_evidence_signature: EvidenceSignatureVerifier,
) -> str:
    """Write one private decision request and return only its opaque handle.

    The protected issuer supplies the identity commitment salt and signer registry.
    Evals derives all campaign cells from independently signed trial receipts.  It
    never returns the private request object, its path, or an unsalted identity.
    """

    value = dict(campaign)
    summary = validate_qualification_campaign(
        value,
        verify_receipt_signature=verify_receipt_signature,
        require_admissible=True,
    )
    if not isinstance(decision_id, str) or not _PRIVATE_DECISION_ID.fullmatch(decision_id):
        raise QualificationEvidenceError("decision_id is invalid")
    _require_int(revision, "revision", minimum=1)
    _require_digest(revocation_state_sha256, "revocation_state_sha256")
    if entity_class is not None:
        if not isinstance(entity_class, str) or not entity_class:
            raise QualificationEvidenceError("entity_class must be null or a non-empty string")
        if len(entity_class) > 64:
            raise QualificationEvidenceError("entity_class exceeds 64 characters")

    projection, projection_sha256 = _build_private_evidence_projection(
        campaign=value,
        campaign_permit=campaign_permit,
        project_contract=project_contract,
        sealed_bundle_manifest=sealed_bundle_manifest,
        runtime_identity=runtime_identity,
        verify_campaign_permit_signature=verify_campaign_permit_signature,
        revocation_state_sha256=revocation_state_sha256,
    )
    permit = projection["campaign_permit"]
    private_runtime = {
        field: f"sha256:{projection['runtime_identity']['runtime'][field]}"
        for field in _PRIVATE_RUNTIME_KEYS
    }
    private_contracts = dict(projection["project_contract"]["contracts"])
    bundle_manifest = projection["sealed_bundle_manifest"]

    issued = _validate_timestamp(issued_at, "issued_at")
    not_before_value = _validate_timestamp(not_before, "not_before")
    expires = _validate_timestamp(expires_at, "expires_at")
    if not not_before_value <= issued < expires:
        raise QualificationEvidenceError("decision validity interval is invalid")
    if expires - not_before_value > timedelta(days=30):
        raise QualificationEvidenceError("decision validity exceeds 30 days")
    permit_not_before = _validate_timestamp(permit["not_before"], "campaign permit not_before")
    permit_expires = _validate_timestamp(permit["expires_at"], "campaign permit expires_at")
    if not permit_not_before <= not_before_value <= issued < expires <= permit_expires:
        raise QualificationEvidenceError("decision validity exceeds the campaign permit")

    if not isinstance(evidence_signer_public_key, bytes) or len(evidence_signer_public_key) != 32:
        raise QualificationEvidenceError(
            "evidence_signer_public_key must be a raw 32-byte Ed25519 public key"
        )
    evidence_signer_key_id = (
        "qa-ed25519-" + hashlib.sha256(evidence_signer_public_key).hexdigest()[:16]
    )
    receipt_issuers = {
        receipt["issuer_key_id"]
        for receipt in _require_sequence(value["receipt_envelopes"], "receipt_envelopes")
        if isinstance(receipt, Mapping)
    }
    if evidence_signer_key_id in receipt_issuers:
        raise QualificationEvidenceError(
            "the private decision request requires a distinct evidence authority"
        )

    decision = {
        "schema_version": PRIVATE_DECISION_SCHEMA,
        "decision_id": decision_id,
        "revision": revision,
        "organization_id": permit["organization_id"],
        "workflow_id": permit["workflow_id"],
        "workflow_version_id": permit["workflow_version_id"],
        "commitment_salt_base64": None,
        "bundle_version": bundle_manifest["bundle_version"],
        "bundle_sha256": bundle_manifest["bundle_sha256"],
        "runtime": private_runtime,
        "contracts": private_contracts,
        "campaign": {
            "schema_version": CAMPAIGN_SCHEMA,
            "campaign_artifact_sha256": summary["campaign_sha256"],
            "campaign_permit_sha256": value["campaign_permit_sha256"],
            "project_contract_sha256": value["project_contract_sha256"],
            "bundle_artifact_sha256": value["bundle_artifact_sha256"],
            "runtime_identity_sha256": value["runtime_identity_sha256"],
            "qualification_contract_sha256": permit["qualification_contract_sha256"],
            "oracle_contract_sha256": permit["oracle_contract_sha256"],
            "authority_contract_sha256": permit["authority_contract_sha256"],
            "signer_registry_sha256": None,
            "source_evidence_manifest_sha256": value["source_evidence_manifest_sha256"],
            "cells": summary["cells"],
        },
        "revocation_state_sha256": revocation_state_sha256,
        "entity_class": entity_class,
        "verdict": "ADMIT",
        "issued_at": issued_at,
        "not_before": not_before,
        "expires_at": expires_at,
    }
    if not callable(verify_evidence_signature):
        raise QualificationEvidenceError("an evidence signature verifier is required")

    def build_request(request_id: str) -> Mapping[str, Any]:
        signed_at = _utc_now_rfc3339()
        signed = _validate_timestamp(signed_at, "signed_at")
        if not issued <= signed < expires:
            raise QualificationEvidenceError("signed_at is outside decision validity")
        unsigned_request = {
            "schema_version": PRIVATE_DECISION_REQUEST_SCHEMA,
            "request_id": request_id,
            "decision": decision,
            "evidence_projection": projection,
            "evidence_projection_sha256": projection_sha256,
            "algorithm": "ed25519",
            "evidence_signer_key_id": evidence_signer_key_id,
            "signed_at": signed_at,
        }
        preimage = PRIVATE_DECISION_REQUEST_SIGNATURE_DOMAIN + canonical_json_bytes(
            unsigned_request
        )
        signature = signer(preimage)
        if not isinstance(signature, bytes) or len(signature) != 64:
            raise QualificationEvidenceError(
                "the Ed25519 evidence signer must return a 64-byte signature"
            )
        if not verify_evidence_signature(evidence_signer_public_key, preimage, signature):
            raise QualificationEvidenceError(
                "the private decision request signature does not match its evidence authority"
            )
        return {
            **unsigned_request,
            "signature": base64.b64encode(signature).decode("ascii"),
        }

    return _store_private_decision_request(inbox=Path(inbox), build_request=build_request)


def _store_private_decision_request(
    *, inbox: Path, build_request: Callable[[str], Mapping[str, Any]]
) -> str:
    _require_secure_directory(inbox, "private evidence inbox")
    requests = inbox / "requests"
    _make_or_require_secure_directory(requests, "private evidence requests directory")

    while True:
        token = secrets.token_hex(16)
        shard = requests / token[:2]
        _make_or_require_secure_directory(shard, "private evidence request shard")
        path = shard / f"{token}.json"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(path, flags, 0o600)
        except FileExistsError:
            continue
        try:
            handle = f"qualification-request:{token}"
            if not _REQUEST_HANDLE.fullmatch(handle):  # pragma: no cover - construction proof
                raise QualificationEvidenceError("generated request handle is invalid")
            request = dict(build_request(handle))
            if request.get("request_id") != handle:
                raise QualificationEvidenceError("private request_id does not match its handle")
            payload = canonical_json_bytes(dict(request)) + b"\n"
            with os.fdopen(descriptor, "wb") as stream:
                descriptor = -1
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
        except BaseException:
            if descriptor >= 0:
                os.close(descriptor)
            path.unlink(missing_ok=True)
            raise
        _fsync_directory(shard)
        return handle


def _utc_now_rfc3339() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _make_or_require_secure_directory(path: Path, context: str) -> None:
    created = False
    try:
        path.mkdir(mode=0o700)
        created = True
    except FileExistsError:
        pass
    _require_secure_directory(path, context)
    if created:
        _fsync_directory(path.parent)


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _require_secure_directory(path: Path, context: str) -> None:
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise QualificationEvidenceError(f"{context} is not available: {exc}") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
        raise QualificationEvidenceError(f"{context} must be a real directory")
    if metadata.st_uid != os.geteuid():
        raise QualificationEvidenceError(f"{context} must belong to the current user")
    if metadata.st_mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise QualificationEvidenceError(f"{context} permissions must exclude group and other")


def _receipt_index(
    raw_receipts: Any,
    *,
    verify_receipt_signature: ReceiptSignatureVerifier,
) -> dict[str, Mapping[str, Any]]:
    receipts = _require_sequence(raw_receipts, "receipt_envelopes")
    if not callable(verify_receipt_signature):
        raise QualificationEvidenceError("a receipt signature verifier is required")
    by_digest: dict[str, Mapping[str, Any]] = {}
    previous_digest: str | None = None
    for index, raw_receipt in enumerate(receipts):
        context = f"receipt_envelopes[{index}]"
        receipt = _require_mapping(raw_receipt, context)
        _exact_keys(receipt, _RECEIPT_KEYS, context)
        if receipt["schema_version"] != TRIAL_RECEIPT_SCHEMA:
            raise QualificationEvidenceError(
                f"{context}.schema_version must be {TRIAL_RECEIPT_SCHEMA!r}"
            )
        receipt_type = receipt["receipt_type"]
        if receipt_type not in RECEIPT_TYPES:
            raise QualificationEvidenceError(f"{context}.receipt_type is invalid")
        key_id = _require_nonempty(receipt["issuer_key_id"], f"{context}.issuer_key_id")
        if receipt["algorithm"] != "ed25519":
            raise QualificationEvidenceError(f"{context}.algorithm must be ed25519")
        _require_digest(receipt["source_artifact_sha256"], f"{context}.source_artifact_sha256")
        _validate_timestamp(receipt["verified_at"], f"{context}.verified_at")
        projection = _require_mapping(
            receipt["verified_projection"], f"{context}.verified_projection"
        )
        _validate_projection(projection, receipt_type)
        try:
            signature = base64.b64decode(receipt["signature"], validate=True)
        except (binascii.Error, TypeError) as exc:
            raise QualificationEvidenceError(f"{context}.signature is invalid base64") from exc
        if len(signature) != 64:
            raise QualificationEvidenceError(
                f"{context}.signature is not a 64-byte Ed25519 signature"
            )
        unsigned = {field: receipt[field] for field in _RECEIPT_UNSIGNED_KEYS}
        preimage = TRIAL_RECEIPT_SIGNATURE_DOMAIN + canonical_json_bytes(unsigned)
        if not verify_receipt_signature(key_id, preimage, signature):
            raise QualificationEvidenceError(f"{context}.signature is not valid")
        digest = receipt_sha256(receipt)
        if digest in by_digest:
            raise QualificationEvidenceError(f"duplicate receipt envelope: {digest}")
        if previous_digest is not None and digest < previous_digest:
            raise QualificationEvidenceError("receipt_envelopes are not canonically ordered")
        previous_digest = digest
        by_digest[digest] = receipt
    return by_digest


def _validate_projection(projection: Mapping[str, Any], receipt_type: str) -> None:
    _exact_keys(projection, _PROJECTION_KEYS, "verified_projection")
    _require_nonempty(projection["campaign_id"], "verified_projection.campaign_id")
    for field in ("task", "condition", "qualification_class", "verdict"):
        _require_nonempty(projection[field], f"verified_projection.{field}")
    if projection["qualification_class"] not in QUALIFICATION_CLASSES:
        raise QualificationEvidenceError("verified_projection.qualification_class is invalid")
    _require_int(projection["trial_index"], "verified_projection.trial_index", minimum=1)
    for field in (
        "attempt_id_sha256",
        "run_id_sha256",
        "campaign_permit_sha256",
        "bundle_artifact_sha256",
        "runtime_identity_sha256",
        "evidence_identity_sha256",
        "evidence_sha256",
    ):
        _require_digest(projection[field], f"verified_projection.{field}")
    facts = _require_mapping(projection["facts"], "verified_projection.facts")
    _exact_keys(facts, _FACT_KEYS[receipt_type], f"{receipt_type} facts")
    for field in _COUNT_FACTS.get(receipt_type, frozenset()):
        _require_int(facts[field], f"{receipt_type} facts.{field}", minimum=0)
    for field in _BOOL_FACTS.get(receipt_type, frozenset()):
        if not isinstance(facts[field], bool):
            raise QualificationEvidenceError(f"{receipt_type} facts.{field} must be boolean")
    if receipt_type == "runner" and facts["observed_terminal_outcome"] not in TERMINAL_OUTCOMES:
        raise QualificationEvidenceError("runner observed_terminal_outcome is invalid")
    if receipt_type == "observer" and facts["independent_verdict"] not in _OBSERVER_VERDICTS:
        raise QualificationEvidenceError("observer independent_verdict is invalid")
    if receipt_type == "delivery":
        if facts["dispatch_state"] not in _DISPATCH_STATES:
            raise QualificationEvidenceError("delivery dispatch_state is invalid")
        if facts["delivery_certainty"] not in _DELIVERY_CERTAINTY:
            raise QualificationEvidenceError("delivery delivery_certainty is invalid")
        if facts["idempotency_result"] not in _IDEMPOTENCY_RESULTS:
            raise QualificationEvidenceError("delivery idempotency_result is invalid")
    expected_verdict = _derived_receipt_verdict(receipt_type, facts)
    if projection["verdict"] != expected_verdict:
        raise QualificationEvidenceError(
            f"{receipt_type} receipt verdict must be {expected_verdict!r}"
        )


def _derived_receipt_verdict(receipt_type: str, facts: Mapping[str, Any]) -> str:
    if receipt_type == "runner":
        return str(facts["observed_terminal_outcome"])
    if receipt_type == "observer":
        return str(facts["independent_verdict"])
    if receipt_type == "delivery":
        return str(facts["delivery_certainty"]).upper()
    if receipt_type == "decision":
        return "VERIFIED" if all(facts.values()) else "REFUTED"
    if receipt_type == "policy":
        return "VERIFIED" if facts["policy_approved_model_path"] else "REFUTED"
    if receipt_type == "repair":
        verified = (
            facts["human_approval_verified"]
            and facts["retained_evidence_verified"]
            and facts["target_revalidated"]
        )
        return "VERIFIED" if verified else "REFUTED"
    if receipt_type == "cleanup":
        return "VERIFIED" if facts["cleanup_completed"] else "REFUTED"
    if receipt_type == "cleanup_absence":
        return "VERIFIED" if facts["absence_verified"] else "REFUTED"
    raise QualificationEvidenceError(f"receipt_type is invalid: {receipt_type!r}")


def _validate_receipt_binding(
    receipt: Mapping[str, Any],
    *,
    campaign_id: str,
    trial: Mapping[str, Any],
    context: str,
) -> None:
    projection = receipt["verified_projection"]
    expected = {
        "campaign_id": campaign_id,
        "task": trial["task"],
        "condition": trial["condition"],
        "qualification_class": trial["qualification_class"],
        "trial_index": trial["trial_index"],
        "attempt_id_sha256": trial["attempt_id_sha256"],
        "run_id_sha256": trial["run_id_sha256"],
        "campaign_permit_sha256": trial["campaign_permit_sha256"],
        "bundle_artifact_sha256": trial["bundle_artifact_sha256"],
        "runtime_identity_sha256": trial["runtime_identity_sha256"],
        "evidence_identity_sha256": trial["evidence_identity_sha256"],
    }
    for field, expected_value in expected.items():
        if projection[field] != expected_value:
            raise QualificationEvidenceError(f"{context} does not bind {field}")


def _exact_keys(value: Mapping[str, Any], expected: frozenset[str], context: str) -> None:
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise QualificationEvidenceError(f"{context} keys differ: missing={missing}, extra={extra}")


def _require_mapping(value: Any, context: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise QualificationEvidenceError(f"{context} must be an object")
    return value


def _require_sequence(value: Any, context: str) -> Sequence[Any]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise QualificationEvidenceError(f"{context} must be an array")
    return value


def _require_nonempty(value: Any, context: str) -> str:
    if not isinstance(value, str) or not value:
        raise QualificationEvidenceError(f"{context} must be a non-empty string")
    return value


def _require_digest(value: Any, context: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise QualificationEvidenceError(f"{context} must be sha256:<64-lowercase-hex>")
    return value


def _require_int(value: Any, context: str, *, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise QualificationEvidenceError(f"{context} must be an integer >= {minimum}")
    return value


def _validate_timestamp(value: Any, context: str) -> datetime:
    if not isinstance(value, str) or not _WHOLE_SECOND_UTC.fullmatch(value):
        raise QualificationEvidenceError(f"{context} must be whole-second UTC")
    return datetime.fromisoformat(value.removesuffix("Z") + "+00:00").astimezone(timezone.utc)


def _validate_json_value(value: Any, context: str) -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        raise QualificationEvidenceError(f"{context} contains a floating-point value")
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise QualificationEvidenceError(f"{context} contains a non-string key")
            _validate_json_value(item, f"{context}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _validate_json_value(item, f"{context}[{index}]")
        return
    raise QualificationEvidenceError(f"{context} contains a non-JSON value")
