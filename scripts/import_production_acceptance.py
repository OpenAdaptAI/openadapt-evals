#!/usr/bin/env python3
"""Derive one bounded production-acceptance result from signed evidence.

The Cloud certificate proves one live authenticated transaction.  An external
qualification authority signs an admission for the full sanitized campaign.
The campaign retains every trial and a signed normalized receipt for each
runner, observer, webhook, replay, fault, cleanup, and cleanup-absence claim.
This importer verifies all signatures and binds all artifacts by canonical
SHA-256 before it derives counts from complete trial rows.

It never promotes an author-supplied maturity class, production boolean,
summary count, or trial classification.  The only successful output is scoped
to the exact qualified browser workflow and environment in the certificate.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import re
import subprocess
import sys
import tempfile
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

CERTIFICATE_SCHEMA = "openadapt.execute-live-acceptance-record/v2"
CAMPAIGN_SCHEMA = "openadapt.qualification-campaign/v2"
TRIAL_SCHEMA = "openadapt.qualification-trial-row/v2"
RESULT_SCHEMA = "openadapt.evals-derived-production-acceptance/v1"
CLAIM_SCOPE = "qualified_browser_workflow_on_bound_environment"
ADMISSION_SCHEMA = "openadapt.qualification-admission/v2"
ADMISSION_SIGNATURE_DOMAIN_TEXT = "openadapt-qualification-admission-v2\\0"
ADMISSION_SIGNATURE_DOMAIN = b"openadapt-qualification-admission-v2\0"
RECEIPT_SCHEMA = "openadapt.qualification-evidence-receipt/v2"
RECEIPT_SIGNATURE_DOMAIN_TEXT = "openadapt-qualification-evidence-receipt-v2\\0"
RECEIPT_SIGNATURE_DOMAIN = b"openadapt-qualification-evidence-receipt-v2\0"
EVIDENCE_IDENTITY_SCHEMA = "openadapt.production-acceptance-evidence-identity/v2"
EVIDENCE_IDENTITY_DOMAIN = b"OpenAdapt production acceptance evidence identity v2\0"
RUNTIME_BUILD_IDENTITY_SCHEMA = "openadapt.admitted-runtime-build/v1"
ADMISSION_POLICY_SCHEMA = "openadapt.production-acceptance-admission-policy/v1"
ADMISSION_POLICY_DOMAIN = b"OpenAdapt production acceptance admission policy v1\0"
SIGNER_REGISTRY_SCHEMA = "openadapt.qualification-signer-registry/v2"
SIGNER_REGISTRY_DOMAIN = b"OpenAdapt qualification signer registry v2\0"
ADMISSION_ISSUER_WORKFLOW = (
    "OpenAdaptAI/openadapt-internal/.github/workflows/"
    "production-qualification-admission.yml"
)
ADMISSION_REF_PREFIX = "refs/heads/main@"

CLOUD_REPOSITORY = "OpenAdaptAI/openadapt-cloud"
CLOUD_WORKFLOW = ".github/workflows/execute-live-acceptance.yml"
CLOUD_CERTIFICATE_IDENTITY = (
    "https://github.com/OpenAdaptAI/openadapt-cloud/"
    ".github/workflows/execute-live-acceptance.yml@refs/heads/main"
)
GITHUB_OIDC_ISSUER = "https://token.actions.githubusercontent.com"

_HEX_40 = re.compile(r"^[a-f0-9]{40}$")
_SHA256 = re.compile(r"^sha256:[a-f0-9]{64}$")
_SEMVER = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$")
_POSITIVE_DECIMAL = re.compile(r"^[1-9][0-9]*$")
_UNPREFIXED_SHA256 = re.compile(r"^[a-f0-9]{64}$")
_ADMISSION_REF = re.compile(r"^refs/heads/main@[a-f0-9]{40}$")
_ADMISSION_KEY_ID = re.compile(r"^qa-ed25519-[a-f0-9]{16}$")
_RECEIPT_KEY_ID = re.compile(r"^qe-ed25519-[a-f0-9]{16}$")
_WHOLE_SECOND_UTC = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$"
)

_CERTIFICATE_KEYS = {
    "schema_version",
    "verdict",
    "claim_scope",
    "product",
    "qualification",
    "transaction",
    "outcomes",
    "contracts",
    "identities",
    "retention",
}
_PRODUCT_KEYS = {"cloud", "flow", "managed_runtime"}
_CLOUD_KEYS = {"source_commit", "target_build_sha256"}
_FLOW_KEYS = {"version", "release_commit", "wheel_sha256"}
_RUNTIME_KEYS = {
    "manifest_sha256",
    "runner_build",
    "runner_artifact_sha256",
    "substrate",
    "playwright_version",
    "browser_base_image",
}
_QUALIFICATION_KEYS = {
    "qualification_admission_sha256",
    "campaign_artifact_sha256",
    "campaign_contract_sha256",
    "campaign_outcomes_sha256",
    "oracle_contract_sha256",
    "task_count",
    "condition_count",
    "required_trial_count",
    "observed_trial_count",
    "minimum_trials_per_condition",
    "admission_signer",
    "runtime_validation_id_sha256",
    "admission_id_sha256",
    "campaign_id_sha256",
    "workflow_version_id_sha256",
    "workflow_digest",
    "environment_digest",
    "evidence_identity_sha256",
}
_ADMISSION_SIGNER_KEYS = {
    "algorithm",
    "key_id",
    "issuer_workflow",
    "issuer_ref",
}
_TRANSACTION_KEYS = {
    "acceptance_envelope_sha256",
    "accepted_response_sha256",
    "duplicate_response_sha256",
    "receipt_sha256",
    "receipt_evidence_digest",
    "target_attestation_sha256",
    "observer_evidence_sha256",
    "webhook_event_sha256",
    "runner_transaction_identity_sha256",
    "runner_report_sha256",
    "runner_result_sha256",
    "runner_permit_sha256",
    "acceptance_challenge_sha256",
    "execution_id_sha256",
    "receipt_id_sha256",
    "idempotency_key_sha256",
    "request_sha256",
}
_OUTCOME_KEYS = {
    "transaction",
    "independent_effect",
    "webhook_delivery",
    "entitlement_and_metering",
}
_CONTRACT_KEYS = {
    "exact_source_attested",
    "authenticated_submission",
    "qualification_bound",
    "idempotency_verified",
    "independent_effect_verified",
    "single_delivery_verified",
    "single_permit_consumption_verified",
    "entitlement_and_metering_verified",
    "receipt_contract_verified",
    "target_attestation_signature_verified",
    "observer_evidence_signature_verified",
    "runner_transaction_identity_verified",
    "runner_signature_verified",
    "signed_webhook_verified",
    "zero_model_healthy_path",
    "quiet_period_stable",
}
_IDENTITY_KEYS = {
    "signer_fingerprint_scheme",
    "producer",
    "target_observer_signer_sha256",
    "target_attestation_signer_sha256",
    "managed_runner_signer_sha256",
    "organization_id_sha256",
    "workflow_id_sha256",
    "verifier",
}
_PRODUCER_KEYS = {
    "kind",
    "repository",
    "workflow",
    "source_ref",
    "run_id",
    "run_attempt",
}
_VERIFIER_KEYS = {
    "kind",
    "repository",
    "workflow",
    "certificate_identity",
    "oidc_issuer",
    "hosted_runner_required",
}
_RETENTION_KEYS = {
    "receipt_id",
    "ciphertext_sha256",
    "candidate_sha256",
    "private_envelope_sha256",
    "store_attestation_sha256",
    "storage_identity_sha256",
    "object_version_sha256",
    "private_locator_version_sha256",
    "kms_key_identity_sha256",
    "uploader_identity_sha256",
    "retention_mode",
    "retention_until",
    "retained_at",
    "upload_verified",
    "head_verified",
    "object_lock_verified",
    "private_locator_recorded",
    "acceptance_verified_at",
    "provenance_attestation",
}

_CAMPAIGN_KEYS = {
    "schema_version",
    "campaign_id",
    "admission_id",
    "runtime_validation_id",
    "evidence_identity_sha256",
    "qualification_contract",
    "oracle_contract",
    "authority_contract",
    "conditions",
    "invariants",
    "excluded_trials",
    "receipt_envelopes",
    "decision",
    "generated_at",
}
_CONDITION_KEYS = {
    "condition_id",
    "expected_runtime_outcome",
    "required_trials",
    "trials",
}
_TRIAL_KEYS = {
    "schema_version",
    "task",
    "condition",
    "trial_index",
    "attempt_id_sha256",
    "run_id_sha256",
    "workflow_version_id",
    "admission_id",
    "bundle_artifact_sha256",
    "runtime_validation_id",
    "evidence_identity_sha256",
    "started_at",
    "completed_at",
    "execution_outcome",
    "oracle_verdict",
    "failure_class",
    "runner_receipt_sha256",
    "observer_receipt_sha256",
    "webhook_receipt_sha256",
    "replay_report_sha256",
    "fault_receipt_sha256",
    "cleanup_receipt_sha256",
    "cleanup_absence_proof_sha256",
}
_INVARIANT_KEYS = {"id", "holds", "observations", "violations"}
_ORACLE_KEYS = {
    "schema_version",
    "runtime_outcome_source",
    "effect_outcome_source",
    "delivery_outcome_source",
    "attempt_accounting",
    "fault_evidence_source",
    "cleanup_evidence_source",
}

_RECEIPT_TYPES = (
    "runner",
    "observer",
    "webhook",
    "replay",
    "fault",
    "cleanup",
    "cleanup_absence",
)
_AUTHORITY_KEYS = {
    "algorithm",
    "key_id",
    "public_key",
    "signature_domain",
    "schema_version",
}
_RECEIPT_ENVELOPE_KEYS = {
    "schema_version",
    "receipt_type",
    "issuer_key_id",
    "algorithm",
    "source_artifact_sha256",
    "verified_projection",
    "verified_at",
    "signature",
}
_RECEIPT_SIGNED_KEYS = _RECEIPT_ENVELOPE_KEYS - {"signature"}
_RECEIPT_PROJECTION_KEYS = {
    "campaign_id",
    "task",
    "condition",
    "trial_index",
    "attempt_id_sha256",
    "run_id_sha256",
    "workflow_version_id",
    "admission_id",
    "bundle_artifact_sha256",
    "runtime_validation_id",
    "evidence_identity_sha256",
    "verdict",
    "evidence_sha256",
    "facts",
}
_RECEIPT_ROW_FIELDS = {
    "runner": "runner_receipt_sha256",
    "observer": "observer_receipt_sha256",
    "webhook": "webhook_receipt_sha256",
    "replay": "replay_report_sha256",
    "fault": "fault_receipt_sha256",
    "cleanup": "cleanup_receipt_sha256",
    "cleanup_absence": "cleanup_absence_proof_sha256",
}
_RECEIPT_VERDICTS = {
    "runner": {"verified", "halted", "failed"},
    "observer": {"satisfied", "refuted", "unverifiable"},
    "webhook": {"delivered", "duplicate", "missing"},
    "replay": {"verified", "halted", "failed"},
    "fault": {"injected", "not_injected", "unverifiable"},
    "cleanup": {"completed", "failed", "unverifiable"},
    "cleanup_absence": {"absent", "present", "unverifiable"},
}

_ADMISSION_PAYLOAD_KEYS = {
    "schema_version",
    "admission_id",
    "tenant_id",
    "workflow_id",
    "workflow_version_id",
    "bundle_version_id",
    "runtime_validation_id",
    "bundle_artifact_sha256",
    "bundle_content_digest",
    "governed_authorization_template_sha256",
    "application_contract_sha256",
    "substrate_contract_sha256",
    "environment_contract_sha256",
    "runtime_environment_sha256",
    "runtime_contract_sha256",
    "input_policy_sha256",
    "action_policy_sha256",
    "network_policy_sha256",
    "identity_contract_sha256",
    "effect_contract_sha256",
    "operator_contract_sha256",
    "evidence_identity",
    "campaign",
    "issuer",
    "issued_at",
    "not_before",
    "expires_at",
}
_ADMISSION_UUID_KEYS = {
    "admission_id",
    "tenant_id",
    "workflow_id",
    "workflow_version_id",
    "bundle_version_id",
    "runtime_validation_id",
}
_ADMISSION_DIGEST_KEYS = _ADMISSION_PAYLOAD_KEYS - {
    "schema_version",
    *_ADMISSION_UUID_KEYS,
    "campaign",
    "issuer",
    "issued_at",
    "not_before",
    "expires_at",
    "evidence_identity",
}
_ADMISSION_CAMPAIGN_KEYS = {
    "campaign_id",
    "artifact_sha256",
    "contract_sha256",
    "outcomes_sha256",
    "oracle_id",
    "oracle_contract_sha256",
    "tasks",
    "failure_taxonomy",
    "decision",
}

_EVIDENCE_IDENTITY_KEYS = {
    "schema_version",
    "runtime_build_identity",
    "managed_runner_signer_sha256",
    "tenant_id",
    "workflow_id",
    "workflow_version_id",
    "workflow_digest",
    "bundle_version_id",
    "bundle_artifact_sha256",
    "bundle_content_digest",
    "environment_digest",
    "governed_authorization_template_sha256",
    "application_contract_sha256",
    "substrate_contract_sha256",
    "environment_contract_sha256",
    "runtime_environment_sha256",
    "runtime_contract_sha256",
    "input_policy_sha256",
    "action_policy_sha256",
    "network_policy_sha256",
    "identity_contract_sha256",
    "effect_contract_sha256",
    "operator_contract_sha256",
    "runtime_validation_id",
    "admission_id",
    "campaign_id",
    "admission_policy_sha256",
    "campaign_contract_sha256",
    "oracle_contract_sha256",
    "qualification_campaign_schema",
    "qualification_trial_schema",
    "qualification_receipt_schema",
    "qualification_signer_registry_sha256",
    "qualification_signer_registry_revision",
}

_RUNTIME_BUILD_COMMON_KEYS = {
    "schema_version",
    "flow_version",
    "flow_release_commit",
    "flow_wheel_sha256",
    "runtime_manifest_sha256",
    "runner_build",
    "runner_artifact_sha256",
    "substrate",
    "managed_browser",
    "native_desktop",
    "remote_display",
}
_MANAGED_BROWSER_DETAIL_KEYS = {"playwright_version", "browser_base_image"}
_NATIVE_DESKTOP_DETAIL_KEYS = {
    "desktop_version",
    "desktop_release_commit",
    "desktop_artifact_sha256",
    "os_family",
    "runtime_boundary_sha256",
}
_REMOTE_DISPLAY_DETAIL_KEYS = {
    "desktop_version",
    "desktop_release_commit",
    "desktop_artifact_sha256",
    "runner_os_family",
    "transport",
    "runtime_boundary_sha256",
}

_SIGNER_REGISTRY_KEYS = {
    "schema_version",
    "revision",
    "generated_at",
    "expires_at",
    "signers",
}
_SIGNER_REGISTRY_ENTRY_KEYS = {
    "algorithm",
    "key_id",
    "public_key",
    "allowed_workflows",
    "allowed_ref_prefixes",
    "status",
    "revoked_at",
}

_RUNNER_FACT_KEYS = {
    "model_call_counter",
    "operator_intervention_ids_sha256",
}
_MODEL_CALL_COUNTER_KEYS = {
    "source",
    "attempted",
    "completed",
    "input_tokens",
    "output_tokens",
    "cost_microusd",
    "call_ids_sha256",
    "provider_models",
    "egress_policy_sha256",
    "report_sha256",
}
_PROVIDER_MODEL_KEYS = {"provider", "model"}
_OBSERVER_FACT_KEYS = {
    "dispatch_state",
    "verifier_method",
    "verifier_tier",
    "pre_state_evidence_sha256",
    "post_state_evidence_sha256",
    "expected_record_id_sha256",
    "expected_transaction_ref_sha256",
    "effect_inventory",
    "derived_classifications",
}
_EFFECT_KEYS = {
    "effect_id_sha256",
    "record_id_sha256",
    "transaction_ref_sha256",
}
_EFFECT_CLASSIFICATION_KEYS = {
    "intended_effect_count",
    "wrong_record_count",
    "duplicate_effect_count",
    "collateral_effect_count",
}

_RUNTIME_OUTCOMES = {
    "verified",
    "halted",
    "delivery_uncertain",
    "platform_failure",
    "operator_intervention",
}
_EXPECTED_OUTCOMES = {"verified", "halted"}
_HALT_REASONS = {
    "none",
    "wrong_identity",
    "stale_identity",
    "ambiguity",
    "missing_effect",
    "weak_effect",
}
_FAILURE_TAXONOMY = (
    "verified",
    "safe_halt",
    "silent_incorrect_success",
    "over_halt",
    "wrong_record",
    "duplicate_effect",
    "collateral_effect",
    "uncertain_delivery",
    "platform_failure",
    "operator_intervention",
    "healthy_path_model_call",
)
_PRODUCTION_FAILURES = set(_FAILURE_TAXONOMY) - {"verified", "safe_halt"}


class AcceptanceError(ValueError):
    """The supplied artifacts do not prove bounded production acceptance."""


def canonical_json(value: Any) -> str:
    """Return the cross-repository canonical JSON representation."""

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def canonical_sha256(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def evidence_identity_sha256(value: Mapping[str, Any]) -> str:
    """Return the domain-separated digest for one exact evidence identity."""

    return hashlib.sha256(
        EVIDENCE_IDENTITY_DOMAIN + canonical_json(value).encode("utf-8")
    ).hexdigest()


def qualification_signer_registry_sha256(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        SIGNER_REGISTRY_DOMAIN + canonical_json(value).encode("utf-8")
    ).hexdigest()


def admission_policy() -> dict[str, Any]:
    """Return the fixed policy whose digest the qualification authority admits."""

    return {
        "schema_version": ADMISSION_POLICY_SCHEMA,
        "qualification_admission_schema": ADMISSION_SCHEMA,
        "qualification_campaign_schema": CAMPAIGN_SCHEMA,
        "qualification_trial_schema": TRIAL_SCHEMA,
        "qualification_receipt_schema": RECEIPT_SCHEMA,
        "admission_signature_domain": ADMISSION_SIGNATURE_DOMAIN_TEXT,
        "receipt_signature_domain": RECEIPT_SIGNATURE_DOMAIN_TEXT,
        "issuer_workflow": ADMISSION_ISSUER_WORKFLOW,
        "issuer_ref_prefix": ADMISSION_REF_PREFIX,
        "maximum_lifetime_seconds": 2_592_000,
        "minimum_trials_per_condition": 3,
        "failure_taxonomy": sorted(_FAILURE_TAXONOMY),
        "external_signer_registry_required": True,
        "registry_freshness_required_at_actuation": True,
        "revocation_check_required": True,
        "distinct_admission_and_runtime_ids_required": True,
        "shared_evidence_identity_required": True,
    }


def admission_policy_sha256() -> str:
    return hashlib.sha256(
        ADMISSION_POLICY_DOMAIN + canonical_json(admission_policy()).encode("utf-8")
    ).hexdigest()


def file_sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def opaque_binding_sha256(domain: str, value: str) -> str:
    payload = f"OpenAdapt acceptance {domain} v1\0".encode("utf-8") + value.encode(
        "utf-8"
    )
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise AcceptanceError(f"{label} must be an object")
    return value


def _string_set(value: Any, label: str) -> set[str]:
    if (
        not isinstance(value, list)
        or not all(isinstance(item, str) and item for item in value)
        or len(value) != len(set(value))
    ):
        raise AcceptanceError(f"{label} must be a unique string list")
    return set(value)


def _closed(value: Any, expected: set[str], label: str) -> Mapping[str, Any]:
    mapping = _mapping(value, label)
    keys = set(mapping)
    if keys != expected:
        missing = sorted(expected - keys)
        extra = sorted(keys - expected)
        raise AcceptanceError(f"{label} keys differ: missing={missing}, extra={extra}")
    return mapping


def _nonempty(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AcceptanceError(f"{label} must be a non-empty string")
    return value


def _digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or _SHA256.fullmatch(value) is None:
        raise AcceptanceError(f"{label} must be a sha256 digest")
    return value


def _unprefixed_digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or _UNPREFIXED_SHA256.fullmatch(value) is None:
        raise AcceptanceError(f"{label} must be an unprefixed sha256 digest")
    return value


def _canonical_uuid(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise AcceptanceError(f"{label} must be a canonical UUID")
    try:
        parsed = uuid.UUID(value)
    except ValueError as exc:
        raise AcceptanceError(f"{label} must be a canonical UUID") from exc
    if str(parsed) != value:
        raise AcceptanceError(f"{label} must be a canonical UUID")
    return value


def _validate_desktop_runtime_detail(value: Mapping[str, Any], *, label: str) -> None:
    if not isinstance(value["desktop_version"], str) or _SEMVER.fullmatch(
        value["desktop_version"]
    ) is None:
        raise AcceptanceError(f"{label} desktop version is not exact")
    if not isinstance(value["desktop_release_commit"], str) or _HEX_40.fullmatch(
        value["desktop_release_commit"]
    ) is None:
        raise AcceptanceError(f"{label} desktop commit is not exact")
    for key in ("desktop_artifact_sha256", "runtime_boundary_sha256"):
        _unprefixed_digest(value[key], f"{label} {key}")


def _validate_evidence_identity(
    value: Any,
    *,
    admission_payload: Mapping[str, Any],
    campaign: Mapping[str, Any],
) -> dict[str, Any]:
    identity = dict(
        _closed(value, _EVIDENCE_IDENTITY_KEYS, "qualification evidence identity")
    )
    if identity["schema_version"] != EVIDENCE_IDENTITY_SCHEMA:
        raise AcceptanceError("qualification evidence identity schema is not supported")
    registry_revision = identity["qualification_signer_registry_revision"]
    if (
        not isinstance(registry_revision, int)
        or isinstance(registry_revision, bool)
        or registry_revision < 1
    ):
        raise AcceptanceError(
            "qualification evidence identity signer registry revision is invalid"
        )
    runtime_value = _mapping(
        identity["runtime_build_identity"],
        "qualification runtime build identity",
    )
    runtime = _closed(
        runtime_value,
        _RUNTIME_BUILD_COMMON_KEYS,
        "qualification runtime build identity",
    )
    selected = [
        name
        for name in ("managed_browser", "native_desktop", "remote_display")
        if runtime[name] is not None
    ]
    if len(selected) != 1:
        raise AcceptanceError(
            "qualification runtime build identity must select exactly one substrate detail"
        )
    selected_detail = selected[0]
    substrate = runtime["substrate"]
    if runtime["schema_version"] != RUNTIME_BUILD_IDENTITY_SCHEMA:
        raise AcceptanceError("qualification runtime build identity schema is not supported")
    if not isinstance(runtime["flow_version"], str) or _SEMVER.fullmatch(
        runtime["flow_version"]
    ) is None:
        raise AcceptanceError("qualification evidence identity Flow version is not exact")
    if not isinstance(runtime["flow_release_commit"], str) or _HEX_40.fullmatch(
        runtime["flow_release_commit"]
    ) is None:
        raise AcceptanceError("qualification evidence identity Flow commit is not exact")
    _nonempty(runtime["runner_build"], "qualification evidence identity runner build")
    for key in (
        "flow_wheel_sha256",
        "runtime_manifest_sha256",
        "runner_artifact_sha256",
    ):
        _unprefixed_digest(runtime[key], f"qualification runtime build identity {key}")
    if selected_detail == "managed_browser":
        if substrate != "web":
            raise AcceptanceError("qualification managed-browser substrate is not web")
        detail = _closed(
            runtime[selected_detail],
            _MANAGED_BROWSER_DETAIL_KEYS,
            "qualification managed-browser identity",
        )
        if not isinstance(detail["playwright_version"], str) or _SEMVER.fullmatch(
            detail["playwright_version"]
        ) is None:
            raise AcceptanceError(
                "qualification evidence identity Playwright version is not exact"
            )
        browser_image = _nonempty(
            detail["browser_base_image"],
            "qualification evidence identity browser image",
        )
        image_name, separator, image_digest = browser_image.rpartition("@sha256:")
        if (
            not image_name
            or separator != "@sha256:"
            or _UNPREFIXED_SHA256.fullmatch(image_digest) is None
        ):
            raise AcceptanceError(
                "qualification evidence identity browser image is not digest-pinned"
            )
    elif selected_detail == "native_desktop":
        detail = _closed(
            runtime[selected_detail],
            _NATIVE_DESKTOP_DETAIL_KEYS,
            "qualification native-desktop identity",
        )
        _validate_desktop_runtime_detail(detail, label="qualification native-desktop identity")
        if substrate not in {"windows", "macos", "linux"} or detail["os_family"] != substrate:
            raise AcceptanceError("qualification native-desktop substrate differs from OS")
    else:
        detail = _closed(
            runtime[selected_detail],
            _REMOTE_DISPLAY_DETAIL_KEYS,
            "qualification remote-display identity",
        )
        _validate_desktop_runtime_detail(detail, label="qualification remote-display identity")
        if substrate not in {"rdp", "citrix"} or detail["transport"] != substrate:
            raise AcceptanceError("qualification remote-display transport differs")
        if detail["runner_os_family"] not in {"windows", "linux"}:
            raise AcceptanceError("qualification remote-display runner OS is invalid")

    for key in {
        "tenant_id",
        "workflow_id",
        "workflow_version_id",
        "bundle_version_id",
        "runtime_validation_id",
        "admission_id",
        "campaign_id",
    }:
        _canonical_uuid(identity[key], f"qualification evidence identity {key}")
    for key in {
        "managed_runner_signer_sha256",
        "workflow_digest",
        "bundle_artifact_sha256",
        "bundle_content_digest",
        "environment_digest",
        "governed_authorization_template_sha256",
        "application_contract_sha256",
        "substrate_contract_sha256",
        "environment_contract_sha256",
        "runtime_environment_sha256",
        "runtime_contract_sha256",
        "input_policy_sha256",
        "action_policy_sha256",
        "network_policy_sha256",
        "identity_contract_sha256",
        "effect_contract_sha256",
        "operator_contract_sha256",
        "admission_policy_sha256",
        "campaign_contract_sha256",
        "oracle_contract_sha256",
        "qualification_signer_registry_sha256",
    }:
        _unprefixed_digest(identity[key], f"qualification evidence identity {key}")

    for key in (
        "tenant_id",
        "workflow_id",
        "workflow_version_id",
        "bundle_version_id",
        "bundle_artifact_sha256",
        "bundle_content_digest",
        "governed_authorization_template_sha256",
        "application_contract_sha256",
        "substrate_contract_sha256",
        "environment_contract_sha256",
        "runtime_environment_sha256",
        "runtime_contract_sha256",
        "input_policy_sha256",
        "action_policy_sha256",
        "network_policy_sha256",
        "identity_contract_sha256",
        "effect_contract_sha256",
        "operator_contract_sha256",
        "runtime_validation_id",
        "admission_id",
    ):
        if identity[key] != admission_payload[key]:
            raise AcceptanceError(
                f"qualification evidence identity {key} differs from admission"
            )
    if identity["campaign_id"] != campaign["campaign_id"]:
        raise AcceptanceError("qualification evidence identity campaign differs from campaign")
    if identity["admission_policy_sha256"] != admission_policy_sha256():
        raise AcceptanceError("qualification evidence identity admission policy differs")
    if identity["campaign_contract_sha256"] != canonical_sha256(
        campaign["qualification_contract"]
    ).removeprefix("sha256:"):
        raise AcceptanceError("qualification evidence identity campaign contract differs")
    if identity["oracle_contract_sha256"] != canonical_sha256(
        campaign["oracle_contract"]
    ).removeprefix("sha256:"):
        raise AcceptanceError("qualification evidence identity oracle contract differs")
    for key, expected in {
        "qualification_campaign_schema": CAMPAIGN_SCHEMA,
        "qualification_trial_schema": TRIAL_SCHEMA,
        "qualification_receipt_schema": RECEIPT_SCHEMA,
    }.items():
        if identity[key] != expected:
            raise AcceptanceError(f"qualification evidence identity {key} differs")
    return identity


def _whole_second_timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or _WHOLE_SECOND_UTC.fullmatch(value) is None:
        raise AcceptanceError(f"{label} must be a whole-second UTC timestamp")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00").astimezone(timezone.utc)
    except ValueError as exc:
        raise AcceptanceError(f"{label} is invalid") from exc


def _validate_signer_registry(
    value: Any,
) -> tuple[dict[str, Mapping[str, Any]], datetime, datetime]:
    registry = _closed(value, _SIGNER_REGISTRY_KEYS, "qualification signer registry")
    if registry["schema_version"] != SIGNER_REGISTRY_SCHEMA:
        raise AcceptanceError("qualification signer registry schema is not supported")
    revision = registry["revision"]
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise AcceptanceError("qualification signer registry revision is invalid")
    generated_at = _whole_second_timestamp(
        registry["generated_at"], "qualification signer registry generated_at"
    )
    expires_at = _whole_second_timestamp(
        registry["expires_at"], "qualification signer registry expires_at"
    )
    if expires_at <= generated_at or expires_at > generated_at + timedelta(days=7):
        raise AcceptanceError("qualification signer registry lifetime is invalid")
    entries = registry["signers"]
    if not isinstance(entries, list) or not entries:
        raise AcceptanceError("qualification signer registry signers must be non-empty")
    verified: dict[str, Mapping[str, Any]] = {}
    ordered_key_ids: list[str] = []
    for index, value in enumerate(entries):
        entry = _closed(
            value,
            _SIGNER_REGISTRY_ENTRY_KEYS,
            f"qualification signer registry entry {index}",
        )
        if entry["algorithm"] != "ed25519":
            raise AcceptanceError("qualification signer registry algorithm is not Ed25519")
        key_id = entry["key_id"]
        if not isinstance(key_id, str) or _ADMISSION_KEY_ID.fullmatch(key_id) is None:
            raise AcceptanceError("qualification signer registry key ID is invalid")
        if key_id in verified:
            raise AcceptanceError("qualification signer registry key ID is duplicate")
        public_key = _canonical_base64(
            entry["public_key"], 32, "qualification signer registry public key"
        )
        derived = "qa-ed25519-" + hashlib.sha256(public_key).hexdigest()[:16]
        if key_id != derived:
            raise AcceptanceError("qualification signer registry key differs from key ID")
        if entry["allowed_workflows"] != [ADMISSION_ISSUER_WORKFLOW]:
            raise AcceptanceError("qualification signer registry workflow trust is not exact")
        if entry["allowed_ref_prefixes"] != [ADMISSION_REF_PREFIX]:
            raise AcceptanceError("qualification signer registry ref trust is not exact")
        if entry["status"] == "active":
            if entry["revoked_at"] is not None:
                raise AcceptanceError("active qualification signer has a revocation time")
        elif entry["status"] == "revoked":
            revoked_at = _whole_second_timestamp(
                entry["revoked_at"], "qualification signer registry revoked_at"
            )
            if revoked_at > generated_at:
                raise AcceptanceError("qualification signer revocation postdates registry")
        else:
            raise AcceptanceError("qualification signer registry status is invalid")
        verified[key_id] = entry
        ordered_key_ids.append(key_id)
    if ordered_key_ids != sorted(ordered_key_ids):
        raise AcceptanceError("qualification signer registry entries are not ordered")
    return verified, generated_at, expires_at


def _canonical_base64(value: Any, length: int, label: str) -> bytes:
    if not isinstance(value, str):
        raise AcceptanceError(f"{label} must be canonical base64")
    try:
        decoded = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise AcceptanceError(f"{label} must be canonical base64") from exc
    if len(decoded) != length or base64.b64encode(decoded).decode("ascii") != value:
        raise AcceptanceError(f"{label} must be canonical base64")
    return decoded


def _verify_ed25519(public_key: bytes, signature: bytes, message: bytes) -> None:
    """Verify Ed25519 with the project library or the OpenSSL 3 CI fallback."""

    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError:
        # SubjectPublicKeyInfo prefix for a raw Ed25519 public key (RFC 8410).
        public_der = bytes.fromhex("302a300506032b6570032100") + public_key
        with tempfile.TemporaryDirectory(prefix="openadapt-admission-") as directory:
            root = Path(directory)
            public_path = root / "public.der"
            signature_path = root / "signature.bin"
            message_path = root / "message.bin"
            public_path.write_bytes(public_der)
            signature_path.write_bytes(signature)
            message_path.write_bytes(message)
            try:
                verified = subprocess.run(
                    [
                        "openssl",
                        "pkeyutl",
                        "-verify",
                        "-pubin",
                        "-inkey",
                        str(public_path),
                        "-keyform",
                        "DER",
                        "-rawin",
                        "-in",
                        str(message_path),
                        "-sigfile",
                        str(signature_path),
                    ],
                    check=False,
                    capture_output=True,
                    text=True,
                )
            except OSError as exc:
                raise AcceptanceError(
                    "qualification signature verifier is unavailable"
                ) from exc
        if verified.returncode != 0:
            raise AcceptanceError("qualification admission signature is invalid")
        return
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(signature, message)
    except (InvalidSignature, ValueError) as exc:
        raise AcceptanceError("qualification admission signature is invalid") from exc


def validate_qualification_admission(
    envelope: Mapping[str, Any],
    campaign: Mapping[str, Any],
    *,
    trusted_signers: Mapping[str, Any],
    revoked_admission_ids: set[str] | frozenset[str] = frozenset(),
    revoked_signer_key_ids: set[str] | frozenset[str] = frozenset(),
    now: datetime | None = None,
) -> dict[str, Any]:
    """Verify the external qualification authority and its exact campaign."""

    trusted_signers = _mapping(trusted_signers, "qualification signer trust registry")
    signer_entries, registry_generated_at, registry_expires_at = (
        _validate_signer_registry(trusted_signers)
    )
    if not isinstance(revoked_admission_ids, (set, frozenset)) or not all(
        isinstance(value, str) and value for value in revoked_admission_ids
    ):
        raise AcceptanceError("qualification admission revocations must be a string set")
    if not isinstance(revoked_signer_key_ids, (set, frozenset)) or not all(
        isinstance(value, str) and value for value in revoked_signer_key_ids
    ):
        raise AcceptanceError("qualification signer revocations must be a string set")
    campaign = _closed(campaign, _CAMPAIGN_KEYS, "campaign")
    envelope = _closed(envelope, {"payload", "algorithm", "signature"}, "admission")
    if envelope["algorithm"] != "ed25519":
        raise AcceptanceError("qualification admission algorithm is not ed25519")
    payload = _closed(
        envelope["payload"],
        _ADMISSION_PAYLOAD_KEYS,
        "qualification admission payload",
    )
    if payload["schema_version"] != ADMISSION_SCHEMA:
        raise AcceptanceError("qualification admission schema is not supported")
    for key in _ADMISSION_UUID_KEYS:
        _canonical_uuid(payload[key], f"qualification admission {key}")
    if payload["admission_id"] == payload["runtime_validation_id"]:
        raise AcceptanceError(
            "qualification admission ID equals the runtime-validation ID"
        )
    for key in _ADMISSION_DIGEST_KEYS:
        _unprefixed_digest(payload[key], f"qualification admission {key}")

    evidence_identity = _validate_evidence_identity(
        payload["evidence_identity"],
        admission_payload=payload,
        campaign=campaign,
    )
    if evidence_identity["qualification_signer_registry_sha256"] != (
        qualification_signer_registry_sha256(trusted_signers)
    ):
        raise AcceptanceError("qualification signer registry differs from admission")
    if evidence_identity["qualification_signer_registry_revision"] != trusted_signers[
        "revision"
    ]:
        raise AcceptanceError("qualification signer registry revision differs from admission")
    identity_digest = evidence_identity_sha256(evidence_identity)
    if campaign["admission_id"] != payload["admission_id"]:
        raise AcceptanceError("campaign admission ID differs from admission")
    if campaign["runtime_validation_id"] != payload["runtime_validation_id"]:
        raise AcceptanceError("campaign runtime-validation ID differs from admission")
    if campaign["evidence_identity_sha256"] != identity_digest:
        raise AcceptanceError("campaign evidence identity differs from admission")

    issuer = _closed(
        payload["issuer"],
        {"key_id", "workflow", "ref"},
        "qualification admission issuer",
    )
    key_id = issuer["key_id"]
    if not isinstance(key_id, str) or _ADMISSION_KEY_ID.fullmatch(key_id) is None:
        raise AcceptanceError("qualification admission signer key ID is invalid")
    if key_id in revoked_signer_key_ids:
        raise AcceptanceError("qualification admission signer is revoked")
    if issuer["workflow"] != ADMISSION_ISSUER_WORKFLOW:
        raise AcceptanceError("qualification admission issuer workflow is not approved")
    if not isinstance(issuer["ref"], str) or _ADMISSION_REF.fullmatch(issuer["ref"]) is None:
        raise AcceptanceError("qualification admission issuer ref is not approved")

    trust = signer_entries.get(key_id)
    if trust is None or trust["status"] != "active":
        raise AcceptanceError("qualification admission signer is not trusted")
    workflows = trust["allowed_workflows"]
    ref_prefixes = trust["allowed_ref_prefixes"]
    if workflows != [ADMISSION_ISSUER_WORKFLOW] and workflows != (ADMISSION_ISSUER_WORKFLOW,):
        raise AcceptanceError("qualification signer workflow trust is not exact")
    if ref_prefixes != [ADMISSION_REF_PREFIX] and ref_prefixes != (ADMISSION_REF_PREFIX,):
        raise AcceptanceError("qualification signer ref trust is not exact")
    public_key = _canonical_base64(
        trust["public_key"],
        32,
        "qualification signer public key",
    )
    derived_key_id = "qa-ed25519-" + hashlib.sha256(public_key).hexdigest()[:16]
    if key_id != derived_key_id:
        raise AcceptanceError("qualification signer key ID differs from its public key")
    signature = _canonical_base64(
        envelope["signature"],
        64,
        "qualification admission signature",
    )
    _verify_ed25519(
        public_key,
        signature,
        ADMISSION_SIGNATURE_DOMAIN + canonical_json(payload).encode("utf-8"),
    )

    issued_at = _whole_second_timestamp(
        payload["issued_at"], "qualification admission issued_at"
    )
    not_before = _whole_second_timestamp(
        payload["not_before"], "qualification admission not_before"
    )
    expires_at = _whole_second_timestamp(
        payload["expires_at"], "qualification admission expires_at"
    )
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        raise AcceptanceError("qualification import time must include a timezone")
    current = current.astimezone(timezone.utc)
    if not issued_at - timedelta(minutes=5) <= not_before <= issued_at + timedelta(minutes=5):
        raise AcceptanceError("qualification admission start is not bound to issuance")
    if expires_at <= not_before or expires_at > issued_at + timedelta(days=30):
        raise AcceptanceError("qualification admission lifetime is invalid")
    if issued_at > current + timedelta(minutes=5):
        raise AcceptanceError("qualification admission is future-issued")
    if current < not_before:
        raise AcceptanceError("qualification admission is not active")
    if current >= expires_at:
        raise AcceptanceError("qualification admission has expired")
    if not registry_generated_at <= issued_at < registry_expires_at:
        raise AcceptanceError("qualification signer registry was not active at issuance")
    if payload["admission_id"] in revoked_admission_ids:
        raise AcceptanceError("qualification admission is revoked")

    campaign_binding = _closed(
        payload["campaign"],
        _ADMISSION_CAMPAIGN_KEYS,
        "qualification admission campaign",
    )
    if campaign_binding["campaign_id"] != campaign["campaign_id"]:
        raise AcceptanceError("qualification admission campaign ID differs")
    for key in (
        "artifact_sha256",
        "contract_sha256",
        "outcomes_sha256",
        "oracle_contract_sha256",
    ):
        _unprefixed_digest(
            campaign_binding[key],
            f"qualification admission campaign {key}",
        )
    if campaign_binding["decision"] != "admitted":
        raise AcceptanceError("qualification campaign was not admitted")
    campaign_artifact_digest = canonical_sha256(campaign).removeprefix("sha256:")
    contract_digest = canonical_sha256(campaign["qualification_contract"]).removeprefix(
        "sha256:"
    )
    outcomes_projection = {
        "conditions": campaign["conditions"],
        "invariants": campaign["invariants"],
        "excluded_trials": campaign["excluded_trials"],
    }
    outcomes_digest = canonical_sha256(outcomes_projection).removeprefix("sha256:")
    oracle_digest = canonical_sha256(campaign["oracle_contract"]).removeprefix("sha256:")
    if campaign_binding["artifact_sha256"] != campaign_artifact_digest:
        raise AcceptanceError("qualification admission campaign artifact digest differs")
    if campaign_binding["contract_sha256"] != contract_digest:
        raise AcceptanceError("qualification admission campaign contract digest differs")
    if campaign_binding["outcomes_sha256"] != outcomes_digest:
        raise AcceptanceError("qualification admission campaign outcomes digest differs")
    oracle = _mapping(campaign["oracle_contract"], "campaign oracle contract")
    if campaign_binding["oracle_id"] != oracle.get("schema_version"):
        raise AcceptanceError("qualification admission campaign oracle identity differs")
    if campaign_binding["oracle_contract_sha256"] != oracle_digest:
        raise AcceptanceError("qualification admission campaign oracle digest differs")

    expected_tasks = []
    contract = _mapping(campaign["qualification_contract"], "qualification contract")
    task_id = contract.get("task_id")
    if not isinstance(task_id, str) or not task_id:
        raise AcceptanceError("qualification campaign task is missing")
    conditions = campaign["conditions"]
    if not isinstance(conditions, list) or not conditions:
        raise AcceptanceError("qualification campaign conditions must be a non-empty list")
    for index, condition_value in enumerate(conditions):
        condition = _closed(
            condition_value,
            _CONDITION_KEYS,
            f"qualification campaign condition {index}",
        )
        required_trials = condition["required_trials"]
        trials = condition["trials"]
        if (
            not isinstance(required_trials, int)
            or isinstance(required_trials, bool)
            or required_trials < 3
            or not isinstance(trials, list)
        ):
            raise AcceptanceError("qualification admission task inventory is malformed")
        expected_tasks.append(
            {
                "task": task_id,
                "condition": condition["condition_id"],
                "required_trials": required_trials,
                "observed_trials": len(trials),
            }
        )
    expected_tasks.sort(key=lambda value: (value["task"], value["condition"]))
    tasks = campaign_binding["tasks"]
    if not isinstance(tasks, list):
        raise AcceptanceError("qualification admission task inventory must be a list")
    if tasks != expected_tasks:
        raise AcceptanceError("qualification admission task inventory differs from campaign rows")
    taxonomy = campaign_binding["failure_taxonomy"]
    expected_taxonomy = sorted(_FAILURE_TAXONOMY)
    if taxonomy != expected_taxonomy:
        raise AcceptanceError("qualification admission failure taxonomy is incomplete")
    campaign_generated_at = _whole_second_timestamp(
        campaign["generated_at"],
        "qualification campaign generated_at",
    )
    if campaign_generated_at > issued_at:
        raise AcceptanceError("qualification admission predates its campaign")
    return {
        "artifact_sha256": canonical_sha256(envelope),
        "signer_key_id": key_id,
        "issuer_workflow": issuer["workflow"],
        "issuer_ref": issuer["ref"],
        "expires_at": payload["expires_at"],
        "evidence_identity_sha256": identity_digest,
    }


def _count(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise AcceptanceError(f"{label} must be a non-negative integer")
    return value


def _timestamp(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise AcceptanceError(f"{label} must be a canonical UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise AcceptanceError(f"{label} must be a canonical UTC timestamp") from exc
    if parsed.tzinfo != timezone.utc:
        raise AcceptanceError(f"{label} must be a canonical UTC timestamp")
    milliseconds = parsed.microsecond // 1000
    expected = parsed.replace(microsecond=milliseconds * 1000).isoformat(
        timespec="milliseconds"
    ).replace("+00:00", "Z")
    if value != expected:
        raise AcceptanceError(f"{label} must use canonical millisecond UTC form")
    return parsed


def _validate_certificate(
    certificate: Mapping[str, Any],
    *,
    now: datetime,
    expected_cloud_source_commit: str,
) -> dict[str, Any]:
    certificate = _closed(certificate, _CERTIFICATE_KEYS, "certificate")
    if certificate["schema_version"] != CERTIFICATE_SCHEMA:
        raise AcceptanceError("certificate schema is not supported")
    if certificate["verdict"] != "passed":
        raise AcceptanceError("certificate verdict is not passed")
    if certificate["claim_scope"] != "single_authenticated_qualified_browser_transaction":
        raise AcceptanceError("certificate claim scope is not the live browser transaction")

    product = _closed(certificate["product"], _PRODUCT_KEYS, "certificate.product")
    cloud = _closed(product["cloud"], _CLOUD_KEYS, "certificate.product.cloud")
    flow = _closed(product["flow"], _FLOW_KEYS, "certificate.product.flow")
    runtime = _closed(
        product["managed_runtime"],
        _RUNTIME_KEYS,
        "certificate.product.managed_runtime",
    )
    if not isinstance(cloud["source_commit"], str) or _HEX_40.fullmatch(
        cloud["source_commit"]
    ) is None:
        raise AcceptanceError("certificate Cloud source commit is not exact")
    if _HEX_40.fullmatch(expected_cloud_source_commit) is None:
        raise AcceptanceError("approved Cloud source commit is not exact")
    if cloud["source_commit"] != expected_cloud_source_commit:
        raise AcceptanceError("certificate Cloud source commit is not the approved commit")
    _digest(cloud["target_build_sha256"], "certificate Cloud target build")
    if not isinstance(flow["version"], str) or _SEMVER.fullmatch(flow["version"]) is None:
        raise AcceptanceError("certificate Flow version is not exact")
    if not isinstance(flow["release_commit"], str) or _HEX_40.fullmatch(
        flow["release_commit"]
    ) is None:
        raise AcceptanceError("certificate Flow release commit is not exact")
    _digest(flow["wheel_sha256"], "certificate Flow wheel")
    _digest(runtime["manifest_sha256"], "certificate managed-runtime manifest")
    _digest(runtime["runner_artifact_sha256"], "certificate runner artifact")
    _nonempty(runtime["runner_build"], "certificate runner build")
    if runtime["substrate"] != "web":
        raise AcceptanceError("certificate managed-runtime substrate is not web")
    if not isinstance(runtime["playwright_version"], str) or _SEMVER.fullmatch(
        runtime["playwright_version"]
    ) is None:
        raise AcceptanceError("certificate Playwright version is not exact")
    browser_image = _nonempty(runtime["browser_base_image"], "certificate browser image")
    image_name, separator, image_digest = browser_image.rpartition("@sha256:")
    if not image_name or separator != "@sha256:" or re.fullmatch(
        r"[a-f0-9]{64}", image_digest
    ) is None:
        raise AcceptanceError("certificate browser image is not digest-pinned")

    qualification = _closed(
        certificate["qualification"],
        _QUALIFICATION_KEYS,
        "certificate.qualification",
    )
    for key in (
        "qualification_admission_sha256",
        "campaign_artifact_sha256",
        "campaign_contract_sha256",
        "campaign_outcomes_sha256",
        "oracle_contract_sha256",
        "runtime_validation_id_sha256",
        "admission_id_sha256",
        "campaign_id_sha256",
        "workflow_version_id_sha256",
        "workflow_digest",
        "environment_digest",
        "evidence_identity_sha256",
    ):
        _digest(qualification[key], f"certificate qualification {key}")
    for key in (
        "task_count",
        "condition_count",
        "required_trial_count",
        "observed_trial_count",
        "minimum_trials_per_condition",
    ):
        value = _count(qualification[key], f"certificate qualification {key}")
        if value < 1:
            raise AcceptanceError(f"certificate qualification {key} must be positive")
    if (
        qualification["minimum_trials_per_condition"] < 3
        or qualification["condition_count"] < qualification["task_count"]
        or qualification["observed_trial_count"] < qualification["required_trial_count"]
    ):
        raise AcceptanceError("certificate qualification counts are not internally consistent")
    admission_signer = _closed(
        qualification["admission_signer"],
        _ADMISSION_SIGNER_KEYS,
        "certificate qualification admission signer",
    )
    if (
        admission_signer["algorithm"] != "ed25519"
        or not isinstance(admission_signer["key_id"], str)
        or _ADMISSION_KEY_ID.fullmatch(admission_signer["key_id"]) is None
        or admission_signer["issuer_workflow"] != ADMISSION_ISSUER_WORKFLOW
        or not isinstance(admission_signer["issuer_ref"], str)
        or _ADMISSION_REF.fullmatch(admission_signer["issuer_ref"]) is None
    ):
        raise AcceptanceError("certificate qualification admission signer is not approved")
    if qualification["runtime_validation_id_sha256"] == qualification[
        "admission_id_sha256"
    ]:
        raise AcceptanceError("runtime-validation and qualification bindings are not separated")

    transaction = _closed(
        certificate["transaction"],
        _TRANSACTION_KEYS,
        "certificate.transaction",
    )
    for key, value in transaction.items():
        _digest(value, f"certificate transaction {key}")
    if transaction["accepted_response_sha256"] != transaction["duplicate_response_sha256"]:
        raise AcceptanceError("idempotent accepted responses have different digests")

    outcomes = _closed(certificate["outcomes"], _OUTCOME_KEYS, "certificate.outcomes")
    if any(value != "verified" for value in outcomes.values()):
        raise AcceptanceError("certificate outcomes are not all verified")

    contracts = _closed(certificate["contracts"], _CONTRACT_KEYS, "certificate.contracts")
    if any(value is not True for value in contracts.values()):
        raise AcceptanceError("certificate contracts are not all verified")

    identities = _closed(certificate["identities"], _IDENTITY_KEYS, "certificate.identities")
    if identities["signer_fingerprint_scheme"] != "sha256-ed25519-public-key-raw-v1":
        raise AcceptanceError("certificate signer fingerprint scheme is not supported")
    producer = _closed(identities["producer"], _PRODUCER_KEYS, "certificate producer")
    verifier = _closed(identities["verifier"], _VERIFIER_KEYS, "certificate verifier")
    if producer != {
        "kind": "github_oidc_attested_workflow",
        "repository": CLOUD_REPOSITORY,
        "workflow": CLOUD_WORKFLOW,
        "source_ref": "refs/heads/main",
        "run_id": producer["run_id"],
        "run_attempt": producer["run_attempt"],
    }:
        raise AcceptanceError("certificate producer identity is not the reviewed Cloud workflow")
    for field in ("run_id", "run_attempt"):
        if not isinstance(producer[field], str) or _POSITIVE_DECIMAL.fullmatch(
            producer[field]
        ) is None:
            raise AcceptanceError(f"certificate producer {field} is invalid")
    if verifier != {
        "kind": "github_artifact_attestation",
        "repository": CLOUD_REPOSITORY,
        "workflow": CLOUD_WORKFLOW,
        "certificate_identity": CLOUD_CERTIFICATE_IDENTITY,
        "oidc_issuer": GITHUB_OIDC_ISSUER,
        "hosted_runner_required": True,
    }:
        raise AcceptanceError("certificate verifier identity is not the reviewed Cloud workflow")
    observer_signer = _digest(
        identities["target_observer_signer_sha256"],
        "certificate target observer signer",
    )
    attestation_signer = _digest(
        identities["target_attestation_signer_sha256"],
        "certificate target attestation signer",
    )
    runner_signer = _digest(
        identities["managed_runner_signer_sha256"],
        "certificate managed runner signer",
    )
    _digest(identities["organization_id_sha256"], "certificate organization identity")
    _digest(identities["workflow_id_sha256"], "certificate workflow identity")
    if len({observer_signer, attestation_signer, runner_signer}) != 3:
        raise AcceptanceError(
            "target attestation, observer, and runner signing identities are not separate"
        )

    retention = _closed(certificate["retention"], _RETENTION_KEYS, "certificate.retention")
    for key in (
        "ciphertext_sha256",
        "candidate_sha256",
        "private_envelope_sha256",
        "store_attestation_sha256",
        "storage_identity_sha256",
        "object_version_sha256",
        "private_locator_version_sha256",
        "kms_key_identity_sha256",
        "uploader_identity_sha256",
    ):
        _digest(retention[key], f"certificate retention {key}")
    if not isinstance(retention["receipt_id"], str) or re.fullmatch(
        r"retention:[a-f0-9]{32}", retention["receipt_id"]
    ) is None:
        raise AcceptanceError("certificate retention receipt ID is invalid")
    if retention["retention_mode"] != "COMPLIANCE":
        raise AcceptanceError("certificate retention mode is not Object Lock COMPLIANCE")
    for key in (
        "upload_verified",
        "head_verified",
        "object_lock_verified",
        "private_locator_recorded",
    ):
        if retention[key] is not True:
            raise AcceptanceError(f"certificate retention {key} is not verified")
    if retention["provenance_attestation"] != "github-artifact-attestation-v4":
        raise AcceptanceError("certificate provenance attestation version is not reviewed")
    acceptance_verified_at = _timestamp(
        retention["acceptance_verified_at"],
        "certificate retention acceptance_verified_at",
    )
    retained_at = _timestamp(retention["retained_at"], "certificate retention retained_at")
    expires_at = _timestamp(
        retention["retention_until"],
        "certificate retention retention_until",
    )
    retention_period = expires_at - retained_at
    if not timedelta(days=365) <= retention_period <= timedelta(days=3650):
        raise AcceptanceError("certificate Object Lock retention period is outside policy")
    if not acceptance_verified_at <= retained_at < expires_at:
        raise AcceptanceError("certificate retention chronology is invalid")
    if now.tzinfo is None:
        raise AcceptanceError("import time must include a timezone")
    if now.astimezone(timezone.utc) >= expires_at:
        raise AcceptanceError(
            "certificate Object Lock retention has expired"
        )

    return {
        "product": {"cloud": dict(cloud), "flow": dict(flow), "managed_runtime": dict(runtime)},
        "qualification": dict(qualification),
        "retention": dict(retention),
    }


def _case_contract(contract: Mapping[str, Any]) -> dict[str, dict[str, str]]:
    contract = _closed(
        contract,
        {
            "schema_version",
            "task_id",
            "classification",
            "target",
            "runtime",
            "effect_contract",
            "required_capabilities",
            "cases",
            "fault_case_receipts",
            "cleanup",
            "post_campaign_invariant",
        },
        "qualification contract",
    )
    if contract["schema_version"] != "openadapt.execute-acceptance-qualification/v1":
        raise AcceptanceError("qualification contract schema is not supported")
    if contract["task_id"] != "execute-acceptance":
        raise AcceptanceError("qualification task is not the reviewed Execute acceptance task")
    if contract["classification"] != "private-product-owned-synthetic":
        raise AcceptanceError("qualification contract classification is not reviewed")
    target = _closed(
        contract["target"],
        {
            "entry_url",
            "browser_only_write",
            "reference_input_selector",
            "transaction_ref_parameter",
        },
        "qualification target",
    )
    if target != {
        "entry_url": "https://app.openadapt.ai/execute-acceptance/target",
        "browser_only_write": True,
        "reference_input_selector": "input[data-testid=transaction-ref]",
        "transaction_ref_parameter": "transaction_ref",
    }:
        raise AcceptanceError("qualification target is not the reviewed synthetic target")
    runtime = _closed(contract["runtime"], {"openadapt_flow"}, "qualification runtime")
    flow_runtime = _closed(
        runtime["openadapt_flow"],
        {
            "release_identity_required",
            "release_channel",
            "healthy_path_model_call_limit",
        },
        "qualification Flow runtime",
    )
    if flow_runtime["release_identity_required"] is not True:
        raise AcceptanceError("qualification does not require a Flow release identity")
    _nonempty(flow_runtime["release_channel"], "qualification Flow release channel")
    if flow_runtime["healthy_path_model_call_limit"] != 0:
        raise AcceptanceError("qualification healthy path permits model calls")
    effect = _closed(
        contract["effect_contract"],
        {"kind", "match", "required_strength", "observer", "observer_request"},
        "qualification effect contract",
    )
    match = _closed(effect["match"], {"transaction_ref"}, "qualification effect match")
    observer_request = _closed(
        effect["observer_request"],
        {"method", "path", "records_key", "auth"},
        "qualification observer request",
    )
    if (
        effect["kind"] != "record_written"
        or match["transaction_ref"] != "$param:transaction_ref"
        or effect["required_strength"] != "independent_system_of_record"
        or effect["observer"] != "separate read-only synthetic transaction observer"
        or observer_request
        != {
            "method": "GET",
            "path": (
                "/api/internal/execute-acceptance/observer?"
                "transaction_ref={transaction_ref}"
            ),
            "records_key": "records",
            "auth": "bearer environment reference",
        }
    ):
        raise AcceptanceError("qualification effect contract is not independently verified")
    if contract["required_capabilities"] != [
        "browser_observation",
        "browser_actuation",
        "identity_verification",
        "independent_effect_verification",
    ]:
        raise AcceptanceError("qualification capability contract is not reviewed")

    fault_receipts = _closed(
        contract["fault_case_receipts"],
        {"required", "signer", "case_kinds"},
        "qualification fault-receipt contract",
    )
    if fault_receipts != {
        "required": True,
        "signer": "named trusted fault driver",
        "case_kinds": [
            "wrong_identity",
            "stale_identity",
            "ambiguity",
            "missing_effect",
            "weak_effect",
        ],
    }:
        raise AcceptanceError("qualification fault-receipt contract is not reviewed")
    cleanup = _closed(
        contract["cleanup"],
        {"required", "scope", "required_evidence", "failure_outcome"},
        "qualification cleanup contract",
    )
    if cleanup != {
        "required": True,
        "scope": "every synthetic transaction reference issued for this campaign",
        "required_evidence": [
            "signed cleanup receipt",
            "independent observer absence proof",
        ],
        "failure_outcome": "reconciliation_required",
    }:
        raise AcceptanceError("qualification cleanup contract is not reviewed")
    if contract["post_campaign_invariant"] != (
        "the observer confirms that every synthetic transaction ref used by this "
        "campaign is absent after cleanup"
    ):
        raise AcceptanceError("qualification post-campaign invariant is not reviewed")

    cases = contract["cases"]
    if not isinstance(cases, list) or not cases:
        raise AcceptanceError("qualification contract has no cases")
    reviewed_cases = {
        "healthy-01": ("representative", "verified"),
        "healthy-02": ("representative", "verified"),
        "healthy-03": ("representative", "verified"),
        "idempotency-replay": ("representative", "verified"),
        "wrong-reference": ("wrong_identity", "halted"),
        "stale-session": ("stale_identity", "halted"),
        "ambiguous-target": ("ambiguity", "halted"),
        "verifier-unavailable": ("missing_effect", "halted"),
        "weak-effect-only": ("weak_effect", "halted"),
    }
    expected: dict[str, dict[str, str]] = {}
    for index, case_value in enumerate(cases):
        case = _mapping(case_value, f"qualification contract case {index}")
        case_id = _nonempty(case.get("id"), f"qualification contract case {index} id")
        expected_keys = {"id", "kind", "expected_outcome"}
        if case_id == "idempotency-replay":
            expected_keys |= {
                "replays_case",
                "idempotency_key_parameter",
                "invariant",
            }
        case = _closed(case, expected_keys, f"qualification contract case {case_id!r}")
        outcome = case.get("expected_outcome")
        if outcome not in _EXPECTED_OUTCOMES:
            raise AcceptanceError(f"qualification contract case {case_id!r} has invalid outcome")
        if case_id in expected:
            raise AcceptanceError(f"qualification contract case is duplicate: {case_id!r}")
        kind = _nonempty(case.get("kind"), f"qualification contract case {case_id!r} kind")
        if reviewed_cases.get(case_id) != (kind, outcome):
            raise AcceptanceError(f"qualification contract case is not reviewed: {case_id!r}")
        if case_id == "idempotency-replay" and (
            case["replays_case"] != "healthy-01"
            or case["idempotency_key_parameter"] != "transaction_ref"
            or case["invariant"]
            != (
                "the exact healthy-01 canonical input and transaction_ref replay "
                "returns the same execution and creates no second effect"
            )
        ):
            raise AcceptanceError("qualification replay contract is not reviewed")
        halt_reason = "none" if outcome == "verified" else kind
        if halt_reason not in _HALT_REASONS:
            raise AcceptanceError(
                f"qualification contract case {case_id!r} has an unsupported halt reason"
            )
        expected[case_id] = {
            "outcome": outcome,
            "halt_reason": halt_reason,
            "kind": kind,
        }
    if set(expected) != set(reviewed_cases):
        raise AcceptanceError("qualification contract does not contain the nine reviewed cases")
    return expected


def _binding_pairs(certificate: Mapping[str, Any]) -> dict[str, Any]:
    product = certificate["product"]
    qualification = certificate["qualification"]
    return {
        "runtime_validation_id_sha256": qualification["runtime_validation_id_sha256"],
        "admission_id_sha256": qualification["admission_id_sha256"],
        "campaign_id_sha256": qualification["campaign_id_sha256"],
        "workflow_version_id_sha256": qualification["workflow_version_id_sha256"],
        "workflow_digest": qualification["workflow_digest"],
        "environment_digest": qualification["environment_digest"],
        "evidence_identity_sha256": qualification["evidence_identity_sha256"],
        "cloud_source_commit": product["cloud"]["source_commit"],
        "cloud_target_build_sha256": product["cloud"]["target_build_sha256"],
        "flow_version": product["flow"]["version"],
        "flow_release_commit": product["flow"]["release_commit"],
        "flow_wheel_sha256": product["flow"]["wheel_sha256"],
        "managed_runtime_manifest_sha256": product["managed_runtime"]["manifest_sha256"],
        "runner_artifact_sha256": product["managed_runtime"]["runner_artifact_sha256"],
        "runner_build": product["managed_runtime"]["runner_build"],
        "substrate": product["managed_runtime"]["substrate"],
        "playwright_version": product["managed_runtime"]["playwright_version"],
        "browser_base_image": product["managed_runtime"]["browser_base_image"],
        "campaign_contract_sha256": qualification["campaign_contract_sha256"],
        "managed_runner_signer_sha256": certificate["identities"][
            "managed_runner_signer_sha256"
        ],
        "target_attestation_signer_sha256": certificate["identities"][
            "target_attestation_signer_sha256"
        ],
        "target_observer_signer_sha256": certificate["identities"][
            "target_observer_signer_sha256"
        ],
        "target_attestation_sha256": certificate["transaction"][
            "target_attestation_sha256"
        ],
        "organization_id_sha256": certificate["identities"]["organization_id_sha256"],
        "workflow_id_sha256": certificate["identities"]["workflow_id_sha256"],
    }


def _validate_authority_contract(value: Any) -> dict[str, tuple[str, bytes]]:
    authorities = _closed(value, set(_RECEIPT_TYPES), "campaign authority contract")
    verified: dict[str, tuple[str, bytes]] = {}
    for receipt_type in _RECEIPT_TYPES:
        authority = _closed(
            authorities[receipt_type],
            _AUTHORITY_KEYS,
            f"campaign {receipt_type} authority",
        )
        if authority["algorithm"] != "ed25519":
            raise AcceptanceError(f"campaign {receipt_type} authority is not Ed25519")
        if authority["schema_version"] != RECEIPT_SCHEMA:
            raise AcceptanceError(f"campaign {receipt_type} receipt schema is not supported")
        if authority["signature_domain"] != RECEIPT_SIGNATURE_DOMAIN_TEXT:
            raise AcceptanceError(f"campaign {receipt_type} signature domain is not exact")
        key_id = authority["key_id"]
        if not isinstance(key_id, str) or _RECEIPT_KEY_ID.fullmatch(key_id) is None:
            raise AcceptanceError(f"campaign {receipt_type} key ID is invalid")
        public_key = _canonical_base64(
            authority["public_key"],
            32,
            f"campaign {receipt_type} public key",
        )
        derived = "qe-ed25519-" + hashlib.sha256(public_key).hexdigest()[:16]
        if key_id != derived:
            raise AcceptanceError(f"campaign {receipt_type} key ID differs from its key")
        verified[receipt_type] = (key_id, public_key)
    if len({key_id for key_id, _ in verified.values()}) != len(_RECEIPT_TYPES):
        raise AcceptanceError("campaign receipt authorities are not separated by type")
    return verified


def _unique_digest_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list):
        raise AcceptanceError(f"{label} must be a list")
    digests = [_unprefixed_digest(item, f"{label} item") for item in value]
    if len(digests) != len(set(digests)):
        raise AcceptanceError(f"{label} must not contain duplicates")
    return digests


def _validate_runner_facts(
    value: Any,
    *,
    source_digest: str,
    evidence_identity: Mapping[str, Any],
    label: str,
) -> dict[str, Any]:
    facts = _closed(value, _RUNNER_FACT_KEYS, f"{label} runner facts")
    counter = _closed(
        facts["model_call_counter"],
        _MODEL_CALL_COUNTER_KEYS,
        f"{label} model-call counter",
    )
    if counter["source"] != "runner_signed_flow_report_and_enforced_egress_policy":
        raise AcceptanceError(f"{label} model-call counter source is not reviewed")
    counts = {
        key: _count(counter[key], f"{label} model-call {key}")
        for key in (
            "attempted",
            "completed",
            "input_tokens",
            "output_tokens",
            "cost_microusd",
        )
    }
    call_ids = _unique_digest_list(
        counter["call_ids_sha256"], f"{label} model-call IDs"
    )
    if len(call_ids) != counts["attempted"]:
        raise AcceptanceError(f"{label} model-call IDs differ from attempted count")
    if counts["completed"] > counts["attempted"]:
        raise AcceptanceError(f"{label} completed model calls exceed attempted calls")
    provider_models = counter["provider_models"]
    if not isinstance(provider_models, list):
        raise AcceptanceError(f"{label} provider-model inventory must be a list")
    normalized_provider_models: list[tuple[str, str]] = []
    for index, entry in enumerate(provider_models):
        item = _closed(
            entry,
            _PROVIDER_MODEL_KEYS,
            f"{label} provider-model {index}",
        )
        normalized_provider_models.append(
            (
                _nonempty(item["provider"], f"{label} provider-model {index} provider"),
                _nonempty(item["model"], f"{label} provider-model {index} model"),
            )
        )
    if len(normalized_provider_models) != len(set(normalized_provider_models)):
        raise AcceptanceError(f"{label} provider-model inventory contains duplicates")
    if counts["attempted"] == 0 and normalized_provider_models:
        raise AcceptanceError(f"{label} provider-model inventory exists without a model call")
    if counter["egress_policy_sha256"] != evidence_identity["network_policy_sha256"]:
        raise AcceptanceError(f"{label} model-call egress policy differs from admission")
    if counter["report_sha256"] != source_digest:
        raise AcceptanceError(f"{label} model-call report differs from source evidence")
    operator_ids = _unique_digest_list(
        facts["operator_intervention_ids_sha256"],
        f"{label} operator intervention IDs",
    )
    return {
        "model_call_counter": {**counts, "call_ids": call_ids},
        "operator_intervention_count": len(operator_ids),
    }


def _validate_observer_facts(value: Any, *, label: str) -> dict[str, Any]:
    facts = _closed(value, _OBSERVER_FACT_KEYS, f"{label} observer facts")
    if facts["dispatch_state"] not in {"dispatched", "not_dispatched"}:
        raise AcceptanceError(f"{label} observer dispatch state is invalid")
    if facts["verifier_method"] != "read_only_system_of_record_query":
        raise AcceptanceError(f"{label} observer verifier method is not reviewed")
    if facts["verifier_tier"] != "independent_system_of_record":
        raise AcceptanceError(f"{label} observer verifier tier is not independent")
    for key in (
        "pre_state_evidence_sha256",
        "post_state_evidence_sha256",
        "expected_record_id_sha256",
        "expected_transaction_ref_sha256",
    ):
        _unprefixed_digest(facts[key], f"{label} observer {key}")
    inventory = facts["effect_inventory"]
    if not isinstance(inventory, list):
        raise AcceptanceError(f"{label} observer effect inventory must be a list")
    expected_record = facts["expected_record_id_sha256"]
    expected_transaction = facts["expected_transaction_ref_sha256"]
    effect_ids: set[str] = set()
    intended = 0
    wrong_record = 0
    collateral = 0
    for index, value in enumerate(inventory):
        effect = _closed(value, _EFFECT_KEYS, f"{label} observer effect {index}")
        for key in _EFFECT_KEYS:
            _unprefixed_digest(effect[key], f"{label} observer effect {index} {key}")
        if effect["effect_id_sha256"] in effect_ids:
            raise AcceptanceError(f"{label} observer effect inventory contains duplicates")
        effect_ids.add(effect["effect_id_sha256"])
        if effect["transaction_ref_sha256"] != expected_transaction:
            collateral += 1
        elif effect["record_id_sha256"] != expected_record:
            wrong_record += 1
        else:
            intended += 1
    if facts["dispatch_state"] == "not_dispatched" and inventory:
        raise AcceptanceError(f"{label} observer found effects for an undispatched action")
    derived = {
        "intended_effect_count": intended,
        "wrong_record_count": wrong_record,
        "duplicate_effect_count": max(0, intended - 1),
        "collateral_effect_count": collateral,
    }
    declared = _closed(
        facts["derived_classifications"],
        _EFFECT_CLASSIFICATION_KEYS,
        f"{label} observer derived classifications",
    )
    normalized_declared = {
        key: _count(declared[key], f"{label} observer {key}") for key in declared
    }
    if normalized_declared != derived:
        raise AcceptanceError(
            f"{label} observer effect classifications differ from its inventory"
        )
    return {"dispatch_state": facts["dispatch_state"], **derived}


def _validate_receipt_facts(
    value: Any,
    *,
    receipt_type: str,
    source_digest: str,
    evidence_identity: Mapping[str, Any],
    label: str,
) -> dict[str, Any]:
    if receipt_type == "runner":
        return _validate_runner_facts(
            value,
            source_digest=source_digest,
            evidence_identity=evidence_identity,
            label=label,
        )
    if receipt_type == "observer":
        return _validate_observer_facts(value, label=label)
    if value != {}:
        raise AcceptanceError(f"{label} {receipt_type} facts must be empty")
    return {}


def _verified_receipt(
    receipt_digest: Any,
    *,
    receipt_type: str,
    campaign_id: str,
    task_id: str,
    condition_id: str,
    trial: Mapping[str, Any],
    envelopes: Mapping[str, Any],
    authorities: Mapping[str, tuple[str, bytes]],
    evidence_identity: Mapping[str, Any],
    generated_at: datetime,
    label: str,
) -> tuple[str, str, dict[str, Any]]:
    digest = _unprefixed_digest(receipt_digest, f"{label} {receipt_type} receipt")
    if digest not in envelopes:
        raise AcceptanceError(f"{label} {receipt_type} receipt body is missing")
    envelope = _closed(
        envelopes[digest],
        _RECEIPT_ENVELOPE_KEYS,
        f"{label} {receipt_type} receipt envelope",
    )
    if canonical_sha256(envelope).removeprefix("sha256:") != digest:
        raise AcceptanceError(f"{label} {receipt_type} receipt digest differs from its body")
    if envelope["schema_version"] != RECEIPT_SCHEMA:
        raise AcceptanceError(f"{label} {receipt_type} receipt schema is not supported")
    if envelope["receipt_type"] != receipt_type:
        raise AcceptanceError(f"{label} receipt type differs from its row field")
    if envelope["algorithm"] != "ed25519":
        raise AcceptanceError(f"{label} {receipt_type} receipt is not Ed25519")
    key_id, public_key = authorities[receipt_type]
    if envelope["issuer_key_id"] != key_id:
        raise AcceptanceError(f"{label} {receipt_type} receipt signer is not authorized")
    source_digest = _unprefixed_digest(
        envelope["source_artifact_sha256"],
        f"{label} {receipt_type} source artifact",
    )
    projection = _closed(
        envelope["verified_projection"],
        _RECEIPT_PROJECTION_KEYS,
        f"{label} {receipt_type} verified projection",
    )
    expected_projection = {
        "campaign_id": campaign_id,
        "task": task_id,
        "condition": condition_id,
        "trial_index": trial["trial_index"],
        "attempt_id_sha256": trial["attempt_id_sha256"],
        "run_id_sha256": trial["run_id_sha256"],
        "workflow_version_id": trial["workflow_version_id"],
        "admission_id": trial["admission_id"],
        "bundle_artifact_sha256": trial["bundle_artifact_sha256"],
        "runtime_validation_id": trial["runtime_validation_id"],
        "evidence_identity_sha256": trial["evidence_identity_sha256"],
        "verdict": projection["verdict"],
        "evidence_sha256": source_digest,
        "facts": projection["facts"],
    }
    if projection != expected_projection:
        raise AcceptanceError(f"{label} {receipt_type} projection differs from its row")
    if projection["verdict"] not in _RECEIPT_VERDICTS[receipt_type]:
        raise AcceptanceError(f"{label} {receipt_type} verdict is invalid")
    verified_at = _whole_second_timestamp(
        envelope["verified_at"],
        f"{label} {receipt_type} verified_at",
    )
    completed_at = _whole_second_timestamp(trial["completed_at"], f"{label} completed_at")
    if not completed_at <= verified_at <= generated_at:
        raise AcceptanceError(f"{label} {receipt_type} verification time is outside the campaign")
    signature = _canonical_base64(
        envelope["signature"],
        64,
        f"{label} {receipt_type} signature",
    )
    signed = {key: envelope[key] for key in _RECEIPT_SIGNED_KEYS}
    _verify_ed25519(
        public_key,
        signature,
        RECEIPT_SIGNATURE_DOMAIN + canonical_json(signed).encode("utf-8"),
    )
    facts = _validate_receipt_facts(
        projection["facts"],
        receipt_type=receipt_type,
        source_digest=source_digest,
        evidence_identity=evidence_identity,
        label=label,
    )
    return projection["verdict"], source_digest, facts


def _derive_trial_classification(
    *,
    expected: str,
    verdicts: Mapping[str, str],
    receipt_facts: Mapping[str, Mapping[str, Any]],
) -> str:
    runner_facts = receipt_facts["runner"]
    observer_facts = receipt_facts["observer"]
    if runner_facts["operator_intervention_count"]:
        return "operator_intervention"
    if observer_facts["wrong_record_count"]:
        return "wrong_record"
    if observer_facts["duplicate_effect_count"]:
        return "duplicate_effect"
    if observer_facts["collateral_effect_count"]:
        return "collateral_effect"
    if expected == "verified" and runner_facts["model_call_counter"]["attempted"]:
        return "healthy_path_model_call"
    if verdicts["webhook"] != "delivered":
        return "uncertain_delivery"
    if verdicts["cleanup"] != "completed" or verdicts["cleanup_absence"] != "absent":
        return "platform_failure"
    if verdicts["runner"] == "failed" or verdicts["replay"] == "failed":
        return "platform_failure"
    if expected == "verified":
        if verdicts["runner"] == "halted":
            return "over_halt"
        if (
            verdicts["runner"] == "verified"
            and verdicts["observer"] == "satisfied"
            and verdicts["replay"] == "verified"
            and "fault" not in verdicts
            and observer_facts["dispatch_state"] == "dispatched"
            and observer_facts["intended_effect_count"] == 1
        ):
            return "verified"
        return "silent_incorrect_success"
    if (
        verdicts["runner"] == "halted"
        and verdicts["observer"] == "satisfied"
        and verdicts["replay"] == "halted"
        and verdicts.get("fault") == "injected"
        and observer_facts["dispatch_state"] == "not_dispatched"
        and observer_facts["intended_effect_count"] == 0
    ):
        return "safe_halt"
    return "silent_incorrect_success"


def _validate_campaign(
    campaign: Mapping[str, Any],
    admission_payload: Mapping[str, Any],
) -> tuple[Counter[str], dict[str, int], Counter[str]]:
    campaign = _closed(campaign, _CAMPAIGN_KEYS, "campaign")
    if campaign["schema_version"] != CAMPAIGN_SCHEMA:
        raise AcceptanceError("campaign schema is not supported")
    campaign_id = _canonical_uuid(campaign["campaign_id"], "campaign ID")
    if uuid.UUID(campaign_id).version != 4:
        raise AcceptanceError("campaign ID must be a UUIDv4")
    if campaign["decision"] != "admitted":
        raise AcceptanceError("campaign decision is not admitted")
    for key in ("admission_id", "runtime_validation_id"):
        _canonical_uuid(campaign[key], f"campaign {key}")
        if campaign[key] != admission_payload[key]:
            raise AcceptanceError(f"campaign {key} differs from admission")
    evidence_identity = _mapping(
        admission_payload["evidence_identity"],
        "qualification evidence identity",
    )
    identity_digest = evidence_identity_sha256(evidence_identity)
    if campaign["evidence_identity_sha256"] != identity_digest:
        raise AcceptanceError("campaign evidence identity differs from admission")
    generated_at = _whole_second_timestamp(campaign["generated_at"], "campaign generated_at")
    oracle = _closed(campaign["oracle_contract"], _ORACLE_KEYS, "campaign oracle contract")
    if oracle != {
        "schema_version": "openadapt.execute-acceptance-campaign-oracle/v1",
        "runtime_outcome_source": "signed_flow_run_receipt",
        "effect_outcome_source": "independent_system_of_record_observer",
        "delivery_outcome_source": "signed_managed_runner_and_webhook_evidence",
        "attempt_accounting": "signed_campaign_attempt_index",
        "fault_evidence_source": "signed_named_fault_driver_receipt",
        "cleanup_evidence_source": "signed_cleanup_receipt_and_observer_absence_proof",
    }:
        raise AcceptanceError("campaign oracle contract is not reviewed")
    if campaign["excluded_trials"] != []:
        raise AcceptanceError("campaign contains excluded or hidden trials")

    contract = _mapping(campaign["qualification_contract"], "qualification contract")
    expected_cases = _case_contract(contract)
    task_id = contract["task_id"]
    authorities = _validate_authority_contract(campaign["authority_contract"])
    runner_public_key = authorities["runner"][1]
    runner_fingerprint = hashlib.sha256(runner_public_key).hexdigest()
    if runner_fingerprint != evidence_identity["managed_runner_signer_sha256"]:
        raise AcceptanceError("campaign runner signer differs from admission")
    envelopes = _mapping(campaign["receipt_envelopes"], "campaign receipt envelopes")
    for digest in envelopes:
        _unprefixed_digest(digest, "campaign receipt envelope key")

    conditions = campaign["conditions"]
    if not isinstance(conditions, list) or not conditions:
        raise AcceptanceError("campaign conditions must be a non-empty list")
    seen_conditions: set[str] = set()
    seen_attempts: set[str] = set()
    seen_runs: set[str] = set()
    used_receipts: set[str] = set()
    seen_source_artifacts: set[str] = set()
    taxonomy: Counter[str] = Counter()
    fact_totals: Counter[str] = Counter()
    trials_per_condition: dict[str, int] = {}
    effect_invariant_observations = 0
    healthy_model_observations = 0
    for condition_index, condition_value in enumerate(conditions):
        condition = _closed(
            condition_value,
            _CONDITION_KEYS,
            f"campaign condition {condition_index}",
        )
        condition_id = _nonempty(
            condition["condition_id"],
            f"campaign condition {condition_index} id",
        )
        if condition_id in seen_conditions:
            raise AcceptanceError(f"campaign condition is duplicate: {condition_id!r}")
        seen_conditions.add(condition_id)
        if condition_id not in expected_cases:
            raise AcceptanceError(f"campaign condition is outside the contract: {condition_id!r}")
        expected = condition["expected_runtime_outcome"]
        case = expected_cases[condition_id]
        if expected != case["outcome"]:
            raise AcceptanceError(f"campaign condition outcome differs from contract: {condition_id!r}")
        trials = condition["trials"]
        required_trials = condition["required_trials"]
        if (
            not isinstance(required_trials, int)
            or isinstance(required_trials, bool)
            or required_trials < 3
            or required_trials > 10_000
        ):
            raise AcceptanceError(
                f"campaign condition has an invalid required trial count: {condition_id!r}"
            )
        if not isinstance(trials, list) or len(trials) < required_trials:
            raise AcceptanceError(
                "campaign condition has fewer than 3 retained trials or its required count: "
                f"{condition_id!r}"
            )
        trials_per_condition[condition_id] = len(trials)
        for trial_index, trial_value in enumerate(trials, start=1):
            label = f"campaign condition {condition_id!r} trial {trial_index}"
            trial = _closed(trial_value, _TRIAL_KEYS, label)
            if trial["schema_version"] != TRIAL_SCHEMA:
                raise AcceptanceError(f"{label} schema is not supported")
            if trial["task"] != task_id or trial["condition"] != condition_id:
                raise AcceptanceError(f"{label} task or condition differs from its container")
            if (
                not isinstance(trial["trial_index"], int)
                or isinstance(trial["trial_index"], bool)
                or trial["trial_index"] != trial_index
            ):
                raise AcceptanceError(f"{label} index is not one-based and contiguous")
            for key in ("attempt_id_sha256", "run_id_sha256", "bundle_artifact_sha256"):
                _unprefixed_digest(trial[key], f"{label} {key}")
            if trial["attempt_id_sha256"] in seen_attempts:
                raise AcceptanceError(f"{label} attempt ID is duplicate")
            if trial["run_id_sha256"] in seen_runs:
                raise AcceptanceError(f"{label} run ID is duplicate")
            seen_attempts.add(trial["attempt_id_sha256"])
            seen_runs.add(trial["run_id_sha256"])
            _canonical_uuid(trial["workflow_version_id"], f"{label} workflow version")
            _canonical_uuid(trial["admission_id"], f"{label} admission")
            _canonical_uuid(trial["runtime_validation_id"], f"{label} runtime validation")
            if trial["workflow_version_id"] != admission_payload["workflow_version_id"]:
                raise AcceptanceError(f"{label} workflow version differs from admission")
            if trial["runtime_validation_id"] != admission_payload["runtime_validation_id"]:
                raise AcceptanceError(f"{label} runtime validation differs from admission")
            if trial["admission_id"] != admission_payload["admission_id"]:
                raise AcceptanceError(f"{label} admission ID differs from admission")
            if trial["evidence_identity_sha256"] != identity_digest:
                raise AcceptanceError(f"{label} evidence identity differs from admission")
            if trial["bundle_artifact_sha256"] != admission_payload["bundle_artifact_sha256"]:
                raise AcceptanceError(f"{label} bundle artifact differs from admission")
            started_at = _whole_second_timestamp(trial["started_at"], f"{label} started_at")
            completed_at = _whole_second_timestamp(trial["completed_at"], f"{label} completed_at")
            if completed_at < started_at or completed_at > generated_at:
                raise AcceptanceError(f"{label} time interval is invalid")
            if trial["execution_outcome"] not in {"verified", "halted", "failed"}:
                raise AcceptanceError(f"{label} execution outcome is invalid")
            if trial["oracle_verdict"] not in {"satisfied", "refuted", "unverifiable"}:
                raise AcceptanceError(f"{label} oracle verdict is invalid")
            if trial["failure_class"] not in _FAILURE_TAXONOMY:
                raise AcceptanceError(f"{label} failure class is invalid")
            verdicts: dict[str, str] = {}
            receipt_facts: dict[str, dict[str, Any]] = {}
            for receipt_type, row_field in _RECEIPT_ROW_FIELDS.items():
                receipt_digest = trial[row_field]
                if receipt_type == "fault" and case["kind"] == "representative":
                    if receipt_digest is not None:
                        raise AcceptanceError(f"{label} has a fault receipt for a nonfault case")
                    continue
                if receipt_digest is None:
                    raise AcceptanceError(f"{label} {receipt_type} receipt is required")
                receipt_digest = _unprefixed_digest(
                    receipt_digest,
                    f"{label} {receipt_type} receipt",
                )
                if receipt_digest in used_receipts:
                    raise AcceptanceError(f"{label} reuses a receipt envelope")
                used_receipts.add(receipt_digest)
                verdict, source_digest, facts = _verified_receipt(
                    receipt_digest,
                    receipt_type=receipt_type,
                    campaign_id=campaign_id,
                    task_id=task_id,
                    condition_id=condition_id,
                    trial=trial,
                    envelopes=envelopes,
                    authorities=authorities,
                    evidence_identity=evidence_identity,
                    generated_at=generated_at,
                    label=label,
                )
                if source_digest in seen_source_artifacts:
                    raise AcceptanceError(f"{label} reuses a source evidence artifact")
                seen_source_artifacts.add(source_digest)
                verdicts[receipt_type] = verdict
                receipt_facts[receipt_type] = facts
            if verdicts["runner"] != trial["execution_outcome"]:
                raise AcceptanceError(f"{label} execution outcome differs from signed evidence")
            if verdicts["observer"] != trial["oracle_verdict"]:
                raise AcceptanceError(f"{label} oracle verdict differs from signed evidence")
            classification = _derive_trial_classification(
                expected=expected,
                verdicts=verdicts,
                receipt_facts=receipt_facts,
            )
            if trial["failure_class"] != classification:
                raise AcceptanceError(f"{label} failure class differs from signed evidence")
            taxonomy[classification] += 1
            observer_facts = receipt_facts["observer"]
            runner_facts = receipt_facts["runner"]
            fact_totals["wrong_record_count"] += observer_facts["wrong_record_count"]
            fact_totals["duplicate_effect_count"] += observer_facts[
                "duplicate_effect_count"
            ]
            fact_totals["collateral_effect_count"] += observer_facts[
                "collateral_effect_count"
            ]
            fact_totals["operator_intervention_count"] += runner_facts[
                "operator_intervention_count"
            ]
            attempted_model_calls = runner_facts["model_call_counter"]["attempted"]
            fact_totals["model_call_count"] += attempted_model_calls
            if expected == "verified":
                fact_totals["healthy_path_model_call_count"] += attempted_model_calls
            effect_invariant_observations += 1
            if expected == "verified":
                healthy_model_observations += 1
    if seen_conditions != set(expected_cases):
        missing = sorted(set(expected_cases) - seen_conditions)
        raise AcceptanceError(f"campaign does not retain every contract condition: {missing}")
    if set(envelopes) != used_receipts:
        raise AcceptanceError("campaign contains unreferenced or hidden receipt envelopes")
    failures = {name: taxonomy.get(name, 0) for name in _PRODUCTION_FAILURES}
    present = {name: count for name, count in failures.items() if count}
    if present:
        raise AcceptanceError(f"campaign contains production-acceptance failures: {present}")

    invariants = campaign["invariants"]
    if not isinstance(invariants, list) or not invariants:
        raise AcceptanceError("campaign invariants must be a non-empty list")
    derived_invariants = {
        "no_wrong_or_duplicate_effect": {
            "holds": (
                fact_totals["wrong_record_count"]
                + fact_totals["duplicate_effect_count"]
                + fact_totals["collateral_effect_count"]
                == 0
            ),
            "observations": effect_invariant_observations,
            "violations": (
                fact_totals["wrong_record_count"]
                + fact_totals["duplicate_effect_count"]
                + fact_totals["collateral_effect_count"]
            ),
        },
        "zero_model_healthy_path": {
            "holds": fact_totals["healthy_path_model_call_count"] == 0,
            "observations": healthy_model_observations,
            "violations": fact_totals["healthy_path_model_call_count"],
        },
    }
    seen_invariants: set[str] = set()
    for index, invariant_value in enumerate(invariants):
        invariant = _closed(invariant_value, _INVARIANT_KEYS, f"campaign invariant {index}")
        invariant_id = _nonempty(invariant["id"], f"campaign invariant {index} id")
        if invariant_id in seen_invariants:
            raise AcceptanceError(f"campaign invariant is duplicate: {invariant_id!r}")
        seen_invariants.add(invariant_id)
        if invariant_id not in derived_invariants:
            raise AcceptanceError(f"campaign invariant is not derived: {invariant_id!r}")
        observations = _count(invariant["observations"], f"campaign invariant {invariant_id}")
        violations = _count(invariant["violations"], f"campaign invariant {invariant_id}")
        if {
            "holds": invariant["holds"],
            "observations": observations,
            "violations": violations,
        } != derived_invariants[invariant_id]:
            raise AcceptanceError(f"campaign invariant differs from retained trials: {invariant_id!r}")
    if seen_invariants != set(derived_invariants):
        raise AcceptanceError("campaign does not contain the exact derived invariant set")
    return taxonomy, trials_per_condition, fact_totals


def verify_github_attestation(
    certificate_path: Path,
    bundle_path: Path,
    expected_cloud_source_commit: str,
    *,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, str]:
    """Verify the certificate bytes against the exact protected Cloud workflow."""

    if not certificate_path.is_file():
        raise AcceptanceError("certificate file is missing")
    if not bundle_path.is_file():
        raise AcceptanceError("certificate attestation bundle is missing")
    if _HEX_40.fullmatch(expected_cloud_source_commit) is None:
        raise AcceptanceError("approved Cloud source commit is not exact")
    try:
        certificate = json.loads(certificate_path.read_text(encoding="utf-8"))
        source_commit = certificate["product"]["cloud"]["source_commit"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise AcceptanceError("certificate Cloud source commit cannot be read") from exc
    if not isinstance(source_commit, str) or _HEX_40.fullmatch(source_commit) is None:
        raise AcceptanceError("certificate Cloud source commit is not exact")
    if source_commit != expected_cloud_source_commit:
        raise AcceptanceError("certificate Cloud source commit is not the approved commit")
    command = [
        "gh",
        "attestation",
        "verify",
        str(certificate_path),
        "--repo",
        CLOUD_REPOSITORY,
        "--bundle",
        str(bundle_path),
        "--cert-identity",
        CLOUD_CERTIFICATE_IDENTITY,
        "--cert-oidc-issuer",
        GITHUB_OIDC_ISSUER,
        "--deny-self-hosted-runners",
        "--format",
        "json",
    ]
    try:
        completed = run(command, check=False, capture_output=True, text=True)
    except OSError as exc:
        raise AcceptanceError(f"GitHub attestation verifier could not run: {exc}") from exc
    if completed.returncode != 0:
        detail = (completed.stderr or "verification failed").strip().splitlines()[-1]
        raise AcceptanceError(f"GitHub certificate attestation is invalid: {detail}")
    try:
        result = json.loads(completed.stdout)
    except json.JSONDecodeError as exc:
        raise AcceptanceError("GitHub attestation verifier returned invalid JSON") from exc
    _validate_verified_provenance(
        result,
        certificate_path=certificate_path,
        expected_cloud_source_commit=expected_cloud_source_commit,
    )
    return {
        "repository": CLOUD_REPOSITORY,
        "workflow": CLOUD_WORKFLOW,
        "certificate_identity": CLOUD_CERTIFICATE_IDENTITY,
        "source_commit": expected_cloud_source_commit,
        "bundle_sha256": file_sha256(bundle_path),
    }


def _validate_verified_provenance(
    result: Any,
    *,
    certificate_path: Path,
    expected_cloud_source_commit: str,
) -> None:
    """Check the source binding inside one already verified GitHub statement."""

    try:
        acceptance_record = json.loads(certificate_path.read_text(encoding="utf-8"))
        producer = acceptance_record["identities"]["producer"]
        issued_at = _timestamp(
            acceptance_record["retention"]["acceptance_verified_at"],
            "certificate retention acceptance_verified_at",
        )
    except (OSError, json.JSONDecodeError, KeyError, TypeError) as exc:
        raise AcceptanceError("certificate provenance bindings cannot be read") from exc
    run_id = producer.get("run_id")
    run_attempt = producer.get("run_attempt")
    if not isinstance(run_id, str) or _POSITIVE_DECIMAL.fullmatch(run_id) is None:
        raise AcceptanceError("certificate provenance run ID is invalid")
    if not isinstance(run_attempt, str) or _POSITIVE_DECIMAL.fullmatch(run_attempt) is None:
        raise AcceptanceError("certificate provenance run attempt is invalid")
    expected_invocation = (
        f"https://github.com/{CLOUD_REPOSITORY}/actions/runs/{run_id}/attempts/{run_attempt}"
    )

    if not isinstance(result, list) or len(result) != 1:
        raise AcceptanceError("GitHub attestation verifier must return one verified statement")
    item = _closed(
        result[0],
        {"attestation", "verificationResult"},
        "GitHub attestation result",
    )
    verification = _mapping(
        item["verificationResult"],
        "GitHub attestation verification result",
    )
    signature = _mapping(
        verification.get("signature"),
        "GitHub attestation signature",
    )
    certificate = _mapping(
        signature.get("certificate"),
        "GitHub attestation signing certificate",
    )
    expected_certificate_fields = {
        "subjectAlternativeName": CLOUD_CERTIFICATE_IDENTITY,
        "issuer": GITHUB_OIDC_ISSUER,
        "githubWorkflowTrigger": "workflow_dispatch",
        "githubWorkflowSHA": expected_cloud_source_commit,
        "githubWorkflowRepository": CLOUD_REPOSITORY,
        "githubWorkflowRef": "refs/heads/main",
        "buildSignerURI": CLOUD_CERTIFICATE_IDENTITY,
        "buildSignerDigest": expected_cloud_source_commit,
        "runnerEnvironment": "github-hosted",
        "sourceRepositoryURI": f"https://github.com/{CLOUD_REPOSITORY}",
        "sourceRepositoryDigest": expected_cloud_source_commit,
        "sourceRepositoryRef": "refs/heads/main",
        "sourceRepositoryOwnerURI": "https://github.com/OpenAdaptAI",
        "buildConfigURI": CLOUD_CERTIFICATE_IDENTITY,
        "buildConfigDigest": expected_cloud_source_commit,
        "buildTrigger": "workflow_dispatch",
        "runInvocationURI": expected_invocation,
        "sourceRepositoryVisibilityAtSigning": "public",
    }
    for key, expected in expected_certificate_fields.items():
        if certificate.get(key) != expected:
            raise AcceptanceError(f"GitHub signing certificate {key} is not approved")
    for key in ("sourceRepositoryIdentifier", "sourceRepositoryOwnerIdentifier"):
        value = certificate.get(key)
        if not isinstance(value, str) or _POSITIVE_DECIMAL.fullmatch(value) is None:
            raise AcceptanceError(f"GitHub signing certificate {key} is invalid")

    timestamps = verification.get("verifiedTimestamps")
    if not isinstance(timestamps, list) or not timestamps:
        raise AcceptanceError("GitHub attestation has no verified transparency timestamp")
    transparency_times: list[datetime] = []
    for index, value in enumerate(timestamps):
        timestamp = _mapping(value, f"GitHub verified timestamp {index}")
        if timestamp.get("type") != "Tlog" or timestamp.get("uri") != (
            "https://rekor.sigstore.dev"
        ):
            continue
        raw_time = timestamp.get("timestamp")
        if not isinstance(raw_time, str):
            raise AcceptanceError("GitHub transparency timestamp is invalid")
        try:
            parsed_time = datetime.fromisoformat(raw_time.replace("Z", "+00:00"))
        except ValueError as exc:
            raise AcceptanceError("GitHub transparency timestamp is invalid") from exc
        if parsed_time.tzinfo is None:
            raise AcceptanceError("GitHub transparency timestamp has no timezone")
        transparency_times.append(parsed_time.astimezone(timezone.utc))
    if len(transparency_times) != 1:
        raise AcceptanceError("GitHub attestation must have one public-log timestamp")
    if not issued_at <= transparency_times[0] <= issued_at + timedelta(minutes=15):
        raise AcceptanceError("GitHub transparency timestamp is not bound to record issuance")

    statement = _closed(
        verification.get("statement"),
        {"_type", "subject", "predicateType", "predicate"},
        "GitHub provenance statement",
    )
    if statement["_type"] != "https://in-toto.io/Statement/v1":
        raise AcceptanceError("GitHub provenance statement type is not supported")
    if statement["predicateType"] != "https://slsa.dev/provenance/v1":
        raise AcceptanceError("GitHub provenance predicate type is not supported")
    subjects = statement["subject"]
    if not isinstance(subjects, list) or not subjects:
        raise AcceptanceError("GitHub provenance has no certificate subject")
    expected_subject = {
        "name": certificate_path.name,
        "sha256": file_sha256(certificate_path).removeprefix("sha256:"),
    }
    matching_subjects = 0
    for index, value in enumerate(subjects):
        subject = _closed(value, {"name", "digest"}, f"GitHub provenance subject {index}")
        digest = _mapping(subject["digest"], f"GitHub provenance subject {index} digest")
        if digest.get("sha256") == expected_subject["sha256"]:
            if subject["name"] != expected_subject["name"] or set(digest) != {"sha256"}:
                raise AcceptanceError("GitHub provenance certificate subject is malformed")
            matching_subjects += 1
    if matching_subjects != 1:
        raise AcceptanceError(
            "GitHub provenance must contain exactly one subject for the certificate bytes"
        )

    predicate = _mapping(statement["predicate"], "GitHub provenance predicate")
    build = _mapping(predicate.get("buildDefinition"), "GitHub provenance build definition")
    if build.get("buildType") != (
        "https://actions.github.io/buildtypes/workflow/v1"
    ):
        raise AcceptanceError("GitHub provenance build type is not supported")
    external = _mapping(
        build.get("externalParameters"),
        "GitHub provenance external parameters",
    )
    workflow = _closed(
        external.get("workflow"),
        {"ref", "repository", "path"},
        "GitHub provenance source workflow",
    )
    if workflow != {
        "ref": "refs/heads/main",
        "repository": f"https://github.com/{CLOUD_REPOSITORY}",
        "path": CLOUD_WORKFLOW,
    }:
        raise AcceptanceError("GitHub provenance source workflow is not the approved main workflow")
    dependencies = build.get("resolvedDependencies")
    if not isinstance(dependencies, list) or len(dependencies) != 1:
        raise AcceptanceError("GitHub provenance must contain one resolved source dependency")
    dependency = _closed(
        dependencies[0],
        {"uri", "digest"},
        "GitHub provenance resolved source dependency",
    )
    if dependency["uri"] != (
        f"git+https://github.com/{CLOUD_REPOSITORY}@refs/heads/main"
    ):
        raise AcceptanceError("GitHub provenance resolved source ref is not approved")
    dependency_digest = _closed(
        dependency["digest"],
        {"gitCommit"},
        "GitHub provenance resolved source digest",
    )
    if dependency_digest["gitCommit"] != expected_cloud_source_commit:
        raise AcceptanceError("GitHub provenance resolved source commit is not approved")

    internal = _closed(
        build.get("internalParameters"),
        {"github"},
        "GitHub provenance internal parameters",
    )
    github = _closed(
        internal["github"],
        {
            "event_name",
            "repository_id",
            "repository_owner_id",
            "runner_environment",
        },
        "GitHub provenance runner parameters",
    )
    if github["event_name"] != "workflow_dispatch":
        raise AcceptanceError("GitHub provenance event is not the reviewed manual acceptance gate")
    if github["runner_environment"] != "github-hosted":
        raise AcceptanceError("GitHub provenance runner is not GitHub-hosted")
    for key in ("repository_id", "repository_owner_id"):
        if not isinstance(github[key], str) or _POSITIVE_DECIMAL.fullmatch(github[key]) is None:
            raise AcceptanceError(f"GitHub provenance {key} is invalid")

    run_details = _mapping(predicate.get("runDetails"), "GitHub provenance run details")
    builder = _closed(
        run_details.get("builder"),
        {"id"},
        "GitHub provenance builder",
    )
    if builder["id"] != CLOUD_CERTIFICATE_IDENTITY:
        raise AcceptanceError("GitHub provenance builder is not the reviewed Cloud workflow")
    metadata = _closed(
        run_details.get("metadata"),
        {"invocationId"},
        "GitHub provenance run metadata",
    )
    if metadata["invocationId"] != expected_invocation:
        raise AcceptanceError("GitHub provenance invocation differs from the certificate run")


def derive_production_acceptance(
    certificate: Mapping[str, Any],
    campaign: Mapping[str, Any],
    admission: Mapping[str, Any],
    *,
    attestation: Mapping[str, str],
    expected_cloud_source_commit: str,
    trusted_admission_signers: Mapping[str, Any],
    revoked_admission_ids: set[str] | frozenset[str] = frozenset(),
    revoked_admission_signer_key_ids: set[str] | frozenset[str] = frozenset(),
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return a derived result or raise when any required proof is absent."""

    now = now or datetime.now(timezone.utc)
    facts = _validate_certificate(
        certificate,
        now=now,
        expected_cloud_source_commit=expected_cloud_source_commit,
    )
    expected_attestation = {
        "repository": CLOUD_REPOSITORY,
        "workflow": CLOUD_WORKFLOW,
        "certificate_identity": CLOUD_CERTIFICATE_IDENTITY,
        "source_commit": expected_cloud_source_commit,
        "bundle_sha256": attestation.get("bundle_sha256"),
    }
    if attestation != expected_attestation:
        raise AcceptanceError("GitHub attestation identity is not the reviewed Cloud workflow")
    _digest(attestation.get("bundle_sha256"), "GitHub attestation bundle")

    admission_facts = validate_qualification_admission(
        admission,
        campaign,
        trusted_signers=trusted_admission_signers,
        revoked_admission_ids=revoked_admission_ids,
        revoked_signer_key_ids=revoked_admission_signer_key_ids,
        now=now,
    )
    admission_digest = canonical_sha256(admission)
    if admission_digest != certificate["qualification"]["qualification_admission_sha256"]:
        raise AcceptanceError("qualification admission digest differs from certificate")
    admission_payload = _mapping(admission["payload"], "qualification admission payload")
    evidence_identity = _mapping(
        admission_payload["evidence_identity"],
        "qualification evidence identity",
    )
    identity_digest = evidence_identity_sha256(evidence_identity)
    if certificate["qualification"]["evidence_identity_sha256"] != (
        "sha256:" + identity_digest
    ):
        raise AcceptanceError("certificate evidence identity differs from admission")
    runtime_identity = _mapping(
        evidence_identity["runtime_build_identity"],
        "qualification runtime build identity",
    )
    managed_browser = _mapping(
        runtime_identity["managed_browser"],
        "qualification managed-browser identity",
    )
    product = certificate["product"]
    certificate_identity_projection = {
        "flow_version": product["flow"]["version"],
        "flow_release_commit": product["flow"]["release_commit"],
        "flow_wheel_sha256": product["flow"]["wheel_sha256"].removeprefix("sha256:"),
        "runtime_manifest_sha256": product["managed_runtime"][
            "manifest_sha256"
        ].removeprefix("sha256:"),
        "runner_build": product["managed_runtime"]["runner_build"],
        "runner_artifact_sha256": product["managed_runtime"][
            "runner_artifact_sha256"
        ].removeprefix("sha256:"),
        "substrate": product["managed_runtime"]["substrate"],
        "playwright_version": product["managed_runtime"]["playwright_version"],
        "browser_base_image": product["managed_runtime"]["browser_base_image"],
        "workflow_digest": certificate["qualification"]["workflow_digest"].removeprefix(
            "sha256:"
        ),
        "environment_digest": certificate["qualification"][
            "environment_digest"
        ].removeprefix("sha256:"),
        "managed_runner_signer_sha256": certificate["identities"][
            "managed_runner_signer_sha256"
        ].removeprefix("sha256:"),
    }
    expected_identity_projection = {
        "flow_version": runtime_identity["flow_version"],
        "flow_release_commit": runtime_identity["flow_release_commit"],
        "flow_wheel_sha256": runtime_identity["flow_wheel_sha256"],
        "runtime_manifest_sha256": runtime_identity["runtime_manifest_sha256"],
        "runner_build": runtime_identity["runner_build"],
        "runner_artifact_sha256": runtime_identity["runner_artifact_sha256"],
        "substrate": runtime_identity["substrate"],
        "playwright_version": managed_browser["playwright_version"],
        "browser_base_image": managed_browser["browser_base_image"],
        "workflow_digest": evidence_identity["workflow_digest"],
        "environment_digest": evidence_identity["environment_digest"],
        "managed_runner_signer_sha256": evidence_identity[
            "managed_runner_signer_sha256"
        ],
    }
    if certificate_identity_projection != expected_identity_projection:
        raise AcceptanceError("certificate execution identity differs from admission")
    if certificate["qualification"]["admission_signer"] != {
        "algorithm": "ed25519",
        "key_id": admission_facts["signer_key_id"],
        "issuer_workflow": admission_facts["issuer_workflow"],
        "issuer_ref": admission_facts["issuer_ref"],
    }:
        raise AcceptanceError("certificate qualification signer differs from admission")
    admission_campaign = _mapping(
        admission_payload["campaign"],
        "qualification admission campaign",
    )
    opaque_bindings = {
        "runtime_validation_id_sha256": (
            "runtime validation id",
            admission_payload["runtime_validation_id"],
        ),
        "admission_id_sha256": (
            "qualification admission id",
            admission_payload["admission_id"],
        ),
        "campaign_id_sha256": (
            "qualification campaign id",
            admission_campaign["campaign_id"],
        ),
        "workflow_version_id_sha256": (
            "workflow version id",
            admission_payload["workflow_version_id"],
        ),
    }
    for certificate_key, (domain, raw_value) in opaque_bindings.items():
        expected = opaque_binding_sha256(domain, raw_value)
        if certificate["qualification"][certificate_key] != expected:
            raise AcceptanceError(
                f"certificate {certificate_key} differs from the retained admission"
            )
    for certificate_key, domain, payload_key in (
        ("organization_id_sha256", "organization id", "tenant_id"),
        ("workflow_id_sha256", "workflow id", "workflow_id"),
    ):
        expected = opaque_binding_sha256(domain, admission_payload[payload_key])
        if certificate["identities"][certificate_key] != expected:
            raise AcceptanceError(
                f"certificate {certificate_key} differs from the retained admission"
            )
    campaign_digest = canonical_sha256(campaign)
    if campaign_digest != certificate["qualification"]["campaign_artifact_sha256"]:
        raise AcceptanceError("campaign evidence digest differs from certificate")
    campaign_contract_digest = canonical_sha256(campaign["qualification_contract"])
    if campaign_contract_digest != certificate["qualification"]["campaign_contract_sha256"]:
        raise AcceptanceError("campaign qualification-contract digest differs from certificate")
    campaign_outcomes_digest = canonical_sha256(
        {
            "conditions": campaign["conditions"],
            "invariants": campaign["invariants"],
            "excluded_trials": campaign["excluded_trials"],
        }
    )
    if campaign_outcomes_digest != certificate["qualification"]["campaign_outcomes_sha256"]:
        raise AcceptanceError("campaign outcomes digest differs from certificate")
    oracle_digest = canonical_sha256(campaign["oracle_contract"])
    if oracle_digest != certificate["qualification"]["oracle_contract_sha256"]:
        raise AcceptanceError("campaign oracle digest differs from certificate")
    taxonomy, trials_per_condition, fact_totals = _validate_campaign(
        campaign, admission_payload
    )
    conditions = campaign["conditions"]
    required_trial_count = sum(condition["required_trials"] for condition in conditions)
    observed_trial_count = sum(trials_per_condition.values())
    minimum_trials_per_condition = min(trials_per_condition.values())
    expected_certificate_counts = {
        "task_count": 1,
        "condition_count": len(trials_per_condition),
        "required_trial_count": required_trial_count,
        "observed_trial_count": observed_trial_count,
        "minimum_trials_per_condition": minimum_trials_per_condition,
    }
    for key, expected in expected_certificate_counts.items():
        if certificate["qualification"][key] != expected:
            raise AcceptanceError(
                f"certificate qualification {key} differs from retained rows"
            )
    counted_taxonomy = {name: taxonomy.get(name, 0) for name in _FAILURE_TAXONOMY}
    total_trials = observed_trial_count
    return {
        "schema_version": RESULT_SCHEMA,
        "verdict": "accepted",
        "evidence_class": "qualified_browser_production_acceptance",
        "claim_scope": CLAIM_SCOPE,
        "bindings": _binding_pairs(certificate),
        "source_evidence": {
            "certificate_sha256": canonical_sha256(certificate),
            "campaign_sha256": campaign_digest,
            "qualification_admission_sha256": admission_digest,
            "qualification_authority": admission_facts,
            "attestation": dict(attestation),
            "approved_cloud_source_commit": expected_cloud_source_commit,
        },
        "trial_inventory": {
            "condition_count": len(trials_per_condition),
            "trial_count": total_trials,
            "minimum_trials_per_condition": min(trials_per_condition.values()),
            "trials_per_condition": dict(sorted(trials_per_condition.items())),
            "excluded_trial_count": 0,
        },
        "derived_outcomes": counted_taxonomy,
        "reliability": {
            "silent_incorrect_success_count": counted_taxonomy[
                "silent_incorrect_success"
            ],
            "over_halt_count": counted_taxonomy["over_halt"],
            "wrong_record_count": fact_totals["wrong_record_count"],
            "duplicate_effect_count": fact_totals["duplicate_effect_count"],
            "collateral_effect_count": fact_totals["collateral_effect_count"],
            "operator_intervention_count": fact_totals[
                "operator_intervention_count"
            ],
            "uncertain_delivery_count": counted_taxonomy["uncertain_delivery"],
            "model_call_count": fact_totals["model_call_count"],
        },
        "retention": facts["retention"],
        "claim_limit": "not_general_product_production_readiness",
    }


def import_files(
    certificate_path: Path,
    campaign_path: Path,
    admission_path: Path,
    bundle_path: Path,
    expected_cloud_source_commit: str,
    *,
    trusted_admission_signers: Mapping[str, Any],
    revoked_admission_ids: set[str] | frozenset[str] = frozenset(),
    revoked_admission_signer_key_ids: set[str] | frozenset[str] = frozenset(),
    now: datetime | None = None,
    run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> dict[str, Any]:
    raise AcceptanceError(
        "full admission/campaign import is pending an approved private-export contract"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Derive one scoped browser-workflow production-acceptance result."
    )
    parser.add_argument("--certificate", type=Path, required=True)
    parser.add_argument("--campaign", type=Path, required=True)
    parser.add_argument("--qualification-admission", type=Path, required=True)
    parser.add_argument("--attestation-bundle", type=Path, required=True)
    parser.add_argument("--expected-cloud-source-commit", required=True)
    parser.add_argument("--trusted-admission-signers", type=Path, required=True)
    parser.add_argument("--revoked-admission-ids", type=Path)
    parser.add_argument("--revoked-admission-signer-key-ids", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        trusted_admission_signers = _mapping(
            json.loads(args.trusted_admission_signers.read_text(encoding="utf-8")),
            "qualification signer trust registry",
        )
        revoked_admission_ids = (
            _string_set(
                json.loads(args.revoked_admission_ids.read_text(encoding="utf-8")),
                "qualification admission revocations",
            )
            if args.revoked_admission_ids
            else set()
        )
        revoked_admission_signer_key_ids = (
            _string_set(
                json.loads(
                    args.revoked_admission_signer_key_ids.read_text(encoding="utf-8")
                ),
                "qualification signer revocations",
            )
            if args.revoked_admission_signer_key_ids
            else set()
        )
        result = import_files(
            args.certificate,
            args.campaign,
            args.qualification_admission,
            args.attestation_bundle,
            args.expected_cloud_source_commit,
            trusted_admission_signers=trusted_admission_signers,
            revoked_admission_ids=revoked_admission_ids,
            revoked_admission_signer_key_ids=revoked_admission_signer_key_ids,
        )
        with args.output.open("x", encoding="utf-8") as handle:
            handle.write(json.dumps(result, indent=2, sort_keys=True) + "\n")
    except (AcceptanceError, FileExistsError, OSError, json.JSONDecodeError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1
    print(f"Wrote scoped acceptance result to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
