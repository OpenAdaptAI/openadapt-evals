"""Build content-addressed references for public production evidence.

The public evidence registry stores immutable JSON objects in ``OpenAdaptAI/.github``.
This module does not publish those objects.  It builds the canonical bytes, semantic
identities, registry-entry commitments, and exact v2 references that a publisher can
write after it has obtained the current registry metadata.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from fnmatch import fnmatchcase
from pathlib import PurePosixPath
from typing import Any, Mapping, Sequence

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

OBJECT_REFERENCE_SCHEMA = "openadapt.production-evidence-object-reference/v2"
EVIDENCE_REPOSITORY = "OpenAdaptAI/.github"
EVIDENCE_REPOSITORY_ID = "858454062"
EVIDENCE_REPOSITORY_OWNER_ID = "132681217"
SIGSTORE_BUNDLE_MEDIA_TYPE = "application/vnd.dev.sigstore.bundle.v0.3+json"
OBJECT_PATH_PREFIX = "production-evidence/objects/sha256"

REGISTRY_ENTRY_DIGEST_DOMAIN = b"OpenAdapt production evidence registry entry v1\0"
REGULAR_SEMANTIC_IDENTITY_DOMAIN = b"OpenAdapt production evidence semantic identity v1\0"
BUNDLE_SEMANTIC_IDENTITY_DOMAIN = b"OpenAdapt production evidence Sigstore bundle identity v1\0"

SIGNER_REGISTRY_POINTER_SCHEMA = "openadapt.qualification-signer-registry-pointer/v1"
SIGNER_REGISTRY_IDENTITY_DOMAIN = b"OpenAdapt qualification signer registry v2\0"
PRODUCTION_ACCEPTANCE_SUMMARY_SCHEMA = "openadapt.production-lifecycle-evidence-summary/v2"
PRODUCTION_EVIDENCE_IDENTITY_DOMAIN = b"OpenAdapt production acceptance evidence identity v2\0"
PRODUCTION_ACCEPTANCE_MANIFEST_SCHEMA = "openadapt.production-acceptance/v2"
RELEASE_CANDIDATE_SCHEMA = "openadapt.production-release-candidate/v1"
RELEASE_CANDIDATE_DIGEST_DOMAIN = b"OpenAdapt production release candidate v1\0"
ARTIFACT_INVENTORY_SCHEMA = "openadapt.production-release-artifact-inventory/v1"
ARTIFACT_INVENTORY_DIGEST_DOMAIN = b"OpenAdapt production release artifact inventory v1\0"
PRODUCTION_LIFECYCLE_POLICY_SCHEMA = "openadapt.production-lifecycle-policy/v2"
PUBLICATION_STAGING_SCHEMA = "openadapt.production-release-staging-evidence/v1"
PUBLICATION_STAGING_DIGEST_DOMAIN = b"OpenAdapt production release staging evidence v1\0"
IMMUTABLE_RELEASES_DIGEST_DOMAIN = b"OpenAdapt production immutable releases response v1\0"
TAG_RULESET_SCHEMA = "openadapt.production-release-tag-ruleset/v1"
TAG_RULESETS_DIGEST_DOMAIN = b"OpenAdapt production release tag rulesets v1\0"
TAG_REF_STATE_DIGEST_DOMAIN = b"OpenAdapt production release tag ref state v1\0"
DECISION_RECEIPT_SCHEMA = "openadapt.qualification-evidence-decision-receipt/v1"
DECISION_CAMPAIGN_SUMMARY_SCHEMA = "openadapt.qualification-evidence-decision-campaign-summary/v1"
QUALIFICATION_ADMISSION_SCHEMA = "openadapt.qualification-admission/v3"
QUALIFICATION_ADMISSION_ID_DOMAIN = b"OpenAdapt qualification admission v3\0"
DECISION_RECEIPT_SERIES_IDENTITY_DOMAIN = (
    b"OpenAdapt qualification decision receipt series identity v1\0"
)
DECISION_RECEIPT_SIGNING_STATEMENT_SCHEMA = (
    "openadapt.qualification-evidence-signing-statement/v1"
)
DECISION_RECEIPT_SIGNATURE_DOMAIN = "OpenAdapt qualification evidence decision receipt v1\0"
SIGNER_REGISTRY_SCHEMA = "openadapt.qualification-signer-registry/v2"

_SHA256 = re.compile(r"^sha256:[a-f0-9]{64}$")
_HEX40 = re.compile(r"^[a-f0-9]{40}$")
_KIND = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_DECISION_KEY_ID = re.compile(r"^qa-ed25519-[a-f0-9]{16}$")
_BUNDLE_VERSION = re.compile(
    r"^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)"
    r"(?:-(?:(?:0|[1-9][0-9]*)|(?:[A-Za-z-][0-9A-Za-z-]*))"
    r"(?:\.(?:(?:0|[1-9][0-9]*)|(?:[A-Za-z-][0-9A-Za-z-]*)))*)?$"
)


@dataclass(frozen=True)
class EvidenceKind:
    """The approved schema and media type for one regular evidence object."""

    schema_version: str
    media_type: str


@dataclass(frozen=True)
class EvidenceObjectPair:
    """One regular object followed by its raw Sigstore bundle."""

    objects: tuple[bytes, bytes]
    references: tuple[dict[str, Any], dict[str, Any]]


REGULAR_EVIDENCE_KINDS: Mapping[str, EvidenceKind] = {
    "qualification-release": EvidenceKind(
        "openadapt.qualification-release/v1",
        "application/vnd.openadapt.qualification-release+json;version=1",
    ),
    "production-acceptance-manifest": EvidenceKind(
        "openadapt.production-acceptance/v2",
        "application/vnd.openadapt.production-acceptance+json;version=2",
    ),
    "production-acceptance-summary": EvidenceKind(
        "openadapt.production-lifecycle-evidence-summary/v2",
        "application/vnd.openadapt.production-lifecycle-evidence-summary+json;version=2",
    ),
    "qualification-authority-state-receipt": EvidenceKind(
        "openadapt.qualification-authority-state-receipt/v2",
        "application/vnd.openadapt.qualification-authority-state-receipt+json;version=2",
    ),
    "qualification-revocation-state-receipt": EvidenceKind(
        "openadapt.qualification-revocation-state-receipt/v1",
        "application/vnd.openadapt.qualification-revocation-state-receipt+json;version=1",
    ),
    "production-current-default": EvidenceKind(
        "openadapt.production-current-default/v1",
        "application/vnd.openadapt.production-current-default+json;version=1",
    ),
    "production-deployment-observation": EvidenceKind(
        "openadapt.production-deployment-observation/v1",
        "application/vnd.openadapt.production-deployment-observation+json;version=1",
    ),
    "production-lifecycle-checkpoint": EvidenceKind(
        "openadapt.production-lifecycle-checkpoint/v1",
        "application/vnd.openadapt.production-lifecycle-checkpoint+json;version=1",
    ),
    "production-cloud-deploy-authorization": EvidenceKind(
        "openadapt.production-cloud-deploy-authorization/v1",
        "application/vnd.openadapt.production-cloud-deploy-authorization+json;version=1",
    ),
    "production-cloud-deployment-result": EvidenceKind(
        "openadapt.production-cloud-deployment-result/v1",
        "application/vnd.openadapt.production-cloud-deployment-result+json;version=1",
    ),
    "qualification-campaign-permit-policy": EvidenceKind(
        "openadapt.qualification-campaign-permit-policy/v3",
        "application/vnd.openadapt.qualification-campaign-permit-policy+json;version=3",
    ),
    "qualification-campaign-permit-request": EvidenceKind(
        "openadapt.qualification-campaign-permit-request/v3",
        "application/vnd.openadapt.qualification-campaign-permit-request+json;version=3",
    ),
    "qualification-campaign-permit": EvidenceKind(
        "openadapt.qualification-campaign-permit/v3",
        "application/vnd.openadapt.qualification-campaign-permit+json;version=3",
    ),
    "qualification-campaign-permit-receipt": EvidenceKind(
        "openadapt.qualification-campaign-permit-receipt/v3",
        "application/vnd.openadapt.qualification-campaign-permit-receipt+json;version=3",
    ),
    "qualification-evidence-decision-receipt": EvidenceKind(
        "openadapt.qualification-evidence-decision-receipt/v1",
        "application/vnd.openadapt.qualification-evidence-decision-receipt+json;version=1",
    ),
    "qualification-admission": EvidenceKind(
        "openadapt.qualification-admission/v3",
        "application/vnd.openadapt.qualification-admission+json;version=3",
    ),
}

REFERENCE_KEYS = frozenset(
    {
        "schema_version",
        "repository",
        "repository_id",
        "repository_owner_id",
        "registry_source_commit",
        "registry_revision",
        "registry_head_sha256",
        "registry_entry_sha256",
        "kind",
        "object_schema_version",
        "object_path",
        "object_sha256",
        "size_bytes",
        "object_media_type",
        "semantic_identity_sha256",
        "subject_sha256",
    }
)

REGISTRY_ENTRY_KEYS: Sequence[str] = (
    "kind",
    "object_media_type",
    "object_path",
    "object_schema_version",
    "object_sha256",
    "semantic_identity_sha256",
    "size_bytes",
    "subject_sha256",
)

_SUMMARY_KEYS = frozenset(
    {
        "schema_version",
        "target",
        "verdict",
        "claim_scope",
        "acceptance_policy_sha256",
        "lifecycle_policy_sha256",
        "release_identity",
        "release_sha256",
        "artifact_inventory_sha256",
        "publication_staging",
        "publication_staging_sha256",
        "evidence_identity_sha256",
        "qualification_evidence_decision_receipt_reference",
        "qualification_evidence_decision_receipt_bundle_reference",
        "qualification_admission_reference",
        "qualification_admission_bundle_reference",
        "production_acceptance_manifest_reference",
        "production_acceptance_manifest_bundle_reference",
        "campaign_summary",
        "authority_state_sha256",
        "revocation_state_sha256",
        "signer_registry_sha256",
        "issuer",
        "issued_at",
        "not_before",
        "expires_at",
    }
)
_MANIFEST_KEYS = frozenset(
    {
        "schema_version",
        "target",
        "verdict",
        "claim_scope",
        "acceptance_policy_sha256",
        "lifecycle_policy_sha256",
        "release_identity",
        "release",
        "release_sha256",
        "artifact_inventory",
        "artifact_inventory_sha256",
        "publication_staging",
        "publication_staging_sha256",
        "qualification_evidence_decision_receipt_reference",
        "qualification_evidence_decision_receipt_bundle_reference",
        "qualification_admission_reference",
        "qualification_admission_bundle_reference",
        "campaign_summary",
        "authority_state_sha256",
        "revocation_state_sha256",
        "signer_registry_sha256",
        "issuer",
        "issued_at",
        "not_before",
        "expires_at",
    }
)
_RELEASE_IDENTITY_KEYS = frozenset(
    {"schema_version", "channel", "sequence", "previous_admission_sha256"}
)
_RELEASE_CANDIDATE_KEYS = frozenset(
    {
        "schema_version",
        "kind",
        "source_repository",
        "source_repository_id",
        "source_commit",
        "version",
        "tag",
        "deployment_id",
        "deployment_sha256",
        "artifacts",
    }
)
_ARTIFACT_INVENTORY_KEYS = frozenset(
    {"schema_version", "target", "claim_scope", "artifacts"}
)
_CAMPAIGN_CLASSES = frozenset(
    {
        "healthy",
        "safe_halt",
        "idempotency_replay",
        "uncertain_delivery",
        "declared_attended",
        "governed_repair",
    }
)
_CAMPAIGN_CLASS_SUMMARY_KEYS = frozenset(
    {
        "task_condition_cell_count",
        "minimum_trials_per_cell",
        "observed_trial_count",
        "silent_incorrect_success_count",
        "over_halt_count",
        "unsafe_effect_count",
        "blind_retry_count",
        "replay_dispatch_count",
        "model_call_count",
        "unplanned_intervention_count",
        "reconciliation_required_count",
        "authenticated_bound_decision_count",
        "live_target_revalidation_count",
        "policy_approved_repair_count",
        "approved_repair_count",
        "retained_repair_evidence_count",
        "unverified_direct_action_count",
    }
)
_WHOLE_SECOND_UTC = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")
_DECIMAL_ID = re.compile(r"^[1-9][0-9]*$")
_ARTIFACT_KIND = re.compile(r"^[a-z][a-z0-9-]*$")
_MEDIA_TYPE = re.compile(r"^[^/]+/[^/]+$")
_PRODUCT_TARGETS = frozenset(
    {"agent", "capture", "cloud", "desktop", "docs", "flow", "openadapt"}
)
_PRODUCT_CLAIM_SCOPE_BY_TARGET: Mapping[str, str] = {
    target: f"production_{target}" for target in _PRODUCT_TARGETS
}
_POLICY_KEYS = frozenset(
    {
        "$schema",
        "schema_version",
        "revision",
        "maximum_release_admission_days",
        "maximum_workflow_admission_days",
        "object_reference_schema_version",
        "release_admission_schema_version",
        "workflow_admission_schema_version",
        "lifecycle_checkpoint_schema_version",
        "lifecycle_feed_schema_version",
        "lifecycle_feed_ref",
        "targets",
    }
)
_POLICY_TARGET_KEYS = frozenset(
    {
        "id",
        "display_name",
        "source_repository",
        "source_repository_id",
        "release_kind",
        "claim_scope",
        "required_artifact_kinds",
        "package_index_project",
    }
)
_PACKAGE_PROJECT = re.compile(r"^[a-z][a-z0-9-]*$")
_PUBLICATION_STAGING_KEYS = frozenset(
    {
        "schema_version",
        "repository",
        "repository_id",
        "draft_release_id",
        "tag",
        "target_commitish",
        "draft",
        "prerelease",
        "release_app_id",
        "release_app_installation_id",
        "release_app_bot_user_id",
        "release_author_login",
        "assets",
        "immutable_releases",
        "immutable_releases_sha256",
        "tag_ref_state",
        "tag_ref_state_sha256",
        "tag_rulesets",
        "tag_rulesets_sha256",
        "observed_at",
    }
)
_ASSET_KEYS = frozenset(
    {
        "asset_id",
        "name",
        "kind",
        "sha256",
        "size_bytes",
        "media_type",
        "publish_destinations",
        "uploader_id",
        "uploader_login",
    }
)
_EXPECTED_ASSET_KEYS = frozenset(
    {"name", "kind", "sha256", "size_bytes", "media_type", "publish_destinations"}
)
_IMMUTABLE_RELEASES_KEYS = frozenset({"enabled", "enforced_by_owner"})
_TAG_REF_STATE_KEYS = frozenset({"ref", "exists"})
_TAG_RULESET_KEYS = frozenset(
    {
        "schema_version",
        "role",
        "repository",
        "repository_id",
        "ruleset_id",
        "name",
        "target",
        "enforcement",
        "bypass_actors",
        "conditions",
        "rules",
    }
)
_BYPASS_ACTOR_KEYS = frozenset({"actor_id", "actor_type", "bypass_mode"})
_CONDITION_KEYS = frozenset({"ref_name"})
_REF_NAME_KEYS = frozenset({"include", "exclude"})
_RULE_KEYS = frozenset({"type"})
_DECISION_RECEIPT_KEYS = frozenset(
    {
        "schema_version",
        "decision_commitment_sha256",
        "decision_identity_sha256",
        "decision_revision",
        "evidence_manifest_sha256",
        "campaign_artifact_sha256",
        "organization_id_sha256",
        "workflow_id_sha256",
        "workflow_version_id_sha256",
        "bundle_version",
        "bundle_sha256",
        "admitted_runtime_sha256",
        "action_contract_sha256",
        "application_contract_sha256",
        "effect_contract_sha256",
        "environment_contract_sha256",
        "evidence_authority_contract_sha256",
        "identity_contract_sha256",
        "input_contract_sha256",
        "policy_contract_sha256",
        "campaign_permit_sha256",
        "signer_registry_sha256",
        "revocation_state_sha256",
        "entity_class",
        "campaign_summary",
        "verdict",
        "issued_at",
        "not_before",
        "expires_at",
        "issuer_key_id",
        "algorithm",
        "issuer",
        "signing_statement",
        "signature",
    }
)
_DECISION_RECEIPT_ISSUER_KEYS = frozenset(
    {
        "repository",
        "repository_id",
        "repository_owner_id",
        "workflow",
        "ref",
        "source_commit",
        "environment",
    }
)
_DECISION_SIGNING_STATEMENT_KEYS = frozenset(
    {
        "schema_version",
        "object_schema_version",
        "signature_domain",
        "unsigned_object_sha256",
        "unsigned_size_bytes",
        "commitment_scheme",
    }
)
_SIGNER_REGISTRY_KEYS = frozenset(
    {"schema_version", "revision", "generated_at", "expires_at", "signers"}
)
_SIGNER_KEYS = frozenset(
    {
        "algorithm",
        "key_id",
        "public_key",
        "public_key_spki_der_base64",
        "public_key_sha256",
        "statement_schema_versions",
        "allowed_workflows",
        "allowed_ref_prefixes",
        "status",
        "revoked_at",
        "allowed_usages",
    }
)
_DECISION_CAMPAIGN_SUMMARY_KEYS = frozenset(
    {"schema_version", "minimum_trials_per_task_condition", "task_count", "classes"}
)
_QUALIFICATION_ADMISSION_KEYS = frozenset(
    {
        "schema_version",
        "admission_id_sha256",
        "organization_id_sha256",
        "workflow_id_sha256",
        "workflow_version_id_sha256",
        "bundle_version",
        "bundle_sha256",
        "admitted_runtime_sha256",
        "application_contract_sha256",
        "environment_contract_sha256",
        "input_contract_sha256",
        "action_contract_sha256",
        "identity_contract_sha256",
        "effect_contract_sha256",
        "policy_contract_sha256",
        "evidence_authority_sha256",
        "campaign_artifact_sha256",
        "campaign_permit_sha256",
        "decision_receipt_reference",
        "decision_receipt_bundle_reference",
        "signer_registry_sha256",
        "revocation_state_sha256",
        "entity_class",
        "campaign_summary",
        "local_identity_opening",
        "verdict",
        "issued_at",
        "not_before",
        "expires_at",
        "issuer",
    }
)
_LOCAL_IDENTITY_OPENING_KEYS = frozenset(
    {
        "schema_version",
        "algorithm",
        "required",
        "customer_controlled_secret_required",
        "exact_contract_match_required",
        "revalidation_before_actuation",
        "maximum_age_seconds",
    }
)
_ADMISSION_ISSUER_KEYS = frozenset(
    {
        "repository",
        "repository_id",
        "repository_owner_id",
        "workflow",
        "ref",
        "source_commit",
        "environment",
    }
)
_PRODUCTION_ACCEPTANCE_ISSUER_KEYS = frozenset(
    {
        "repository",
        "repository_id",
        "repository_owner_id",
        "workflow",
        "ref",
        "source_commit",
        "environment",
    }
)


class ProductionEvidenceError(ValueError):
    """A public evidence object or reference violates the frozen contract."""


def canonical_json_bytes(value: Any) -> bytes:
    """Return the canonical compact JSON encoding used by evidence digests."""

    _validate_json_value(value, "object")
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def canonical_object_bytes(value: Mapping[str, Any]) -> bytes:
    """Return the exact bytes used for a registered regular object."""

    return canonical_json_bytes(dict(value)) + b"\n"


def _detached_json_object(value: Mapping[str, Any], context: str) -> dict[str, Any]:
    detached = json.loads(canonical_json_bytes(dict(value)))
    if not isinstance(detached, dict):  # pragma: no cover - protected by the input type
        raise ProductionEvidenceError(f"{context} must be an object")
    return detached


def sha256_digest(payload: bytes) -> str:
    """Return a lowercase, algorithm-prefixed SHA-256 digest."""

    return "sha256:" + hashlib.sha256(payload).hexdigest()


def signer_registry_identity(registry: Mapping[str, Any]) -> str:
    """Commit to a signer registry with the approved v2 identity domain."""

    return sha256_digest(SIGNER_REGISTRY_IDENTITY_DOMAIN + canonical_json_bytes(dict(registry)))


def build_signer_registry_pointer(
    *,
    object_path: str,
    object_sha256: str,
    registry_identity_sha256: str,
    registry_revision: int,
) -> dict[str, Any]:
    """Build the exact public signer-registry pointer projection."""

    _validate_object_path(object_path)
    _require_digest(object_sha256, "object_sha256")
    _require_digest(registry_identity_sha256, "registry_identity_sha256")
    _require_positive_int(registry_revision, "registry_revision")
    return {
        "schema_version": SIGNER_REGISTRY_POINTER_SCHEMA,
        "object_path": object_path,
        "object_sha256": object_sha256,
        "registry_identity_sha256": registry_identity_sha256,
        "registry_revision": registry_revision,
    }


def decision_receipt_semantic_identity(value: Mapping[str, Any]) -> str:
    """Derive the stable identity for one private-decision receipt series item."""

    decision_identity = value.get("decision_identity_sha256")
    decision_revision = value.get("decision_revision")
    _require_digest(decision_identity, "decision_identity_sha256")
    _require_positive_int(decision_revision, "decision_revision")
    return sha256_digest(
        DECISION_RECEIPT_SERIES_IDENTITY_DOMAIN
        + canonical_json_bytes(
            {
                "decision_identity_sha256": decision_identity,
                "decision_revision": decision_revision,
            }
        )
    )


def build_evidence_object_pair(
    *,
    kind: str,
    object_value: Mapping[str, Any],
    sigstore_bundle: bytes,
    registry_source_commit: str,
    registry_revision: int,
    registry_head_sha256: str,
) -> EvidenceObjectPair:
    """Build one regular reference and its immediately following bundle reference."""

    profile = REGULAR_EVIDENCE_KINDS.get(kind)
    if profile is None:
        raise ProductionEvidenceError(f"evidence kind is not approved: {kind!r}")
    if object_value.get("schema_version") != profile.schema_version:
        raise ProductionEvidenceError(f"{kind} schema_version must be {profile.schema_version!r}")

    regular_bytes = canonical_object_bytes(object_value)
    bundle_bytes = _validate_raw_json_object(sigstore_bundle, "sigstore_bundle")
    regular_sha256 = sha256_digest(regular_bytes)
    if kind == "qualification-evidence-decision-receipt":
        regular_identity = decision_receipt_semantic_identity(object_value)
    else:
        regular_identity = sha256_digest(
            REGULAR_SEMANTIC_IDENTITY_DOMAIN
            + canonical_json_bytes(
                {
                    "kind": kind,
                    "object_schema_version": profile.schema_version,
                    "object": dict(object_value),
                }
            )
        )
    regular = _build_reference(
        kind=kind,
        object_schema_version=profile.schema_version,
        object_media_type=profile.media_type,
        object_bytes=regular_bytes,
        object_sha256=regular_sha256,
        semantic_identity_sha256=regular_identity,
        subject_sha256=None,
        registry_source_commit=registry_source_commit,
        registry_revision=registry_revision,
        registry_head_sha256=registry_head_sha256,
    )

    bundle_kind = f"{kind}-sigstore-bundle"
    bundle_sha256 = sha256_digest(bundle_bytes)
    bundle_identity = sha256_digest(
        BUNDLE_SEMANTIC_IDENTITY_DOMAIN
        + canonical_json_bytes(
            {
                "kind": bundle_kind,
                "object_sha256": bundle_sha256,
                "subject_sha256": regular_sha256,
            }
        )
    )
    bundle = _build_reference(
        kind=bundle_kind,
        object_schema_version=SIGSTORE_BUNDLE_MEDIA_TYPE,
        object_media_type=SIGSTORE_BUNDLE_MEDIA_TYPE,
        object_bytes=bundle_bytes,
        object_sha256=bundle_sha256,
        semantic_identity_sha256=bundle_identity,
        subject_sha256=regular_sha256,
        registry_source_commit=registry_source_commit,
        registry_revision=registry_revision,
        registry_head_sha256=registry_head_sha256,
    )
    return EvidenceObjectPair(
        objects=(regular_bytes, bundle_bytes),
        references=(regular, bundle),
    )


def build_production_acceptance_manifest(
    *,
    target: str,
    claim_scope: str,
    acceptance_policy_sha256: str,
    lifecycle_policy_bytes: bytes,
    release_identity: Mapping[str, Any],
    release: Mapping[str, Any],
    artifact_inventory: Mapping[str, Any],
    publication_staging: Mapping[str, Any],
    signer_registry_bytes: bytes,
    qualification_evidence_decision_receipt_bytes: bytes,
    qualification_evidence_decision_receipt_references: Sequence[Mapping[str, Any]],
    qualification_admission_bytes: bytes,
    qualification_admission_references: Sequence[Mapping[str, Any]],
    authority_state_sha256: str,
    revocation_state_sha256: str,
    signer_registry_sha256: str,
    issuer: Mapping[str, Any],
    issued_at: str,
    not_before: str,
    expires_at: str,
) -> dict[str, Any]:
    """Build the public-only v2 manifest from prior public trust objects."""

    decision_pair = _validated_pair(
        qualification_evidence_decision_receipt_references,
        "qualification-evidence-decision-receipt",
    )
    admission_pair = _validated_pair(
        qualification_admission_references, "qualification-admission"
    )
    receipt = _parse_registered_regular_object(
        qualification_evidence_decision_receipt_bytes,
        reference=decision_pair[0],
        expected_kind="qualification-evidence-decision-receipt",
    )
    campaign = _validate_decision_receipt(
        receipt,
        reference=decision_pair[0],
        expected_signer_registry_sha256=signer_registry_sha256,
        expected_revocation_state_sha256=revocation_state_sha256,
        signer_registry_bytes=signer_registry_bytes,
    )
    admission = _parse_registered_regular_object(
        qualification_admission_bytes,
        reference=admission_pair[0],
        expected_kind="qualification-admission",
    )
    _validate_qualification_admission(
        admission,
        reference=admission_pair[0],
        decision_receipt=receipt,
        decision_references=decision_pair,
    )
    release_value = _detached_json_object(release, "production release candidate")
    release_artifacts, release_sha256 = _validate_release_candidate(
        release_value,
        target=target,
        claim_scope=claim_scope,
    )
    lifecycle_policy_sha256 = _validate_production_lifecycle_policy(
        lifecycle_policy_bytes,
        target=target,
        claim_scope=claim_scope,
        release=release_value,
        artifacts=release_artifacts,
    )
    inventory = _detached_json_object(
        artifact_inventory, "production artifact inventory"
    )
    artifact_inventory_sha256 = _validate_artifact_inventory(
        inventory,
        target=target,
        claim_scope=claim_scope,
        expected_artifacts=release_artifacts,
    )
    staging = _detached_json_object(publication_staging, "publication staging")
    publication_staging_sha256 = _validate_publication_staging(
        staging,
        expected_assets=release_artifacts,
    )
    manifest: dict[str, Any] = {
        "schema_version": PRODUCTION_ACCEPTANCE_MANIFEST_SCHEMA,
        "target": target,
        "verdict": "accepted",
        "claim_scope": claim_scope,
        "acceptance_policy_sha256": acceptance_policy_sha256,
        "lifecycle_policy_sha256": lifecycle_policy_sha256,
        "release_identity": _detached_json_object(
            release_identity, "production release identity"
        ),
        "release": release_value,
        "release_sha256": release_sha256,
        "artifact_inventory": inventory,
        "artifact_inventory_sha256": artifact_inventory_sha256,
        "publication_staging": staging,
        "publication_staging_sha256": publication_staging_sha256,
        "qualification_evidence_decision_receipt_reference": decision_pair[0],
        "qualification_evidence_decision_receipt_bundle_reference": decision_pair[1],
        "qualification_admission_reference": admission_pair[0],
        "qualification_admission_bundle_reference": admission_pair[1],
        "campaign_summary": campaign,
        "authority_state_sha256": authority_state_sha256,
        "revocation_state_sha256": revocation_state_sha256,
        "signer_registry_sha256": signer_registry_sha256,
        "issuer": _detached_json_object(issuer, "production acceptance issuer"),
        "issued_at": issued_at,
        "not_before": not_before,
        "expires_at": expires_at,
    }
    validate_production_acceptance_manifest(
        manifest,
        qualification_evidence_decision_receipt_bytes=(
            qualification_evidence_decision_receipt_bytes
        ),
        qualification_admission_bytes=qualification_admission_bytes,
        signer_registry_bytes=signer_registry_bytes,
    )
    return manifest


def validate_production_acceptance_manifest(
    manifest: Mapping[str, Any],
    *,
    qualification_evidence_decision_receipt_bytes: bytes,
    qualification_admission_bytes: bytes,
    signer_registry_bytes: bytes,
) -> tuple[datetime, datetime, datetime]:
    """Validate one public-only manifest and return its validity interval."""

    value = dict(manifest)
    if set(value) != _MANIFEST_KEYS:
        missing = sorted(_MANIFEST_KEYS - set(value))
        extra = sorted(set(value) - _MANIFEST_KEYS)
        raise ProductionEvidenceError(
            f"production acceptance manifest keys differ: missing={missing}, extra={extra}"
        )
    if value["schema_version"] != PRODUCTION_ACCEPTANCE_MANIFEST_SCHEMA:
        raise ProductionEvidenceError("production acceptance manifest schema_version is invalid")
    for field in ("target", "claim_scope"):
        if not isinstance(value[field], str) or not value[field]:
            raise ProductionEvidenceError(
                f"production acceptance manifest {field} is invalid"
            )
    if value["target"] not in _PRODUCT_TARGETS:
        raise ProductionEvidenceError("production acceptance manifest target is invalid")
    if value["claim_scope"] != _PRODUCT_CLAIM_SCOPE_BY_TARGET[value["target"]]:
        raise ProductionEvidenceError(
            "production acceptance manifest claim_scope differs from its target"
        )
    if value["verdict"] != "accepted":
        raise ProductionEvidenceError("production acceptance manifest verdict must be accepted")
    for field in (
        "acceptance_policy_sha256",
        "lifecycle_policy_sha256",
        "release_sha256",
        "artifact_inventory_sha256",
        "publication_staging_sha256",
        "authority_state_sha256",
        "revocation_state_sha256",
        "signer_registry_sha256",
    ):
        _require_digest(value[field], f"production acceptance manifest {field}")
    _validate_release_identity(value["release_identity"])
    _validate_production_acceptance_issuer(value["issuer"])
    release_artifacts, release_sha256 = _validate_release_candidate(
        value["release"],
        target=value["target"],
        claim_scope=value["claim_scope"],
    )
    if value["release_sha256"] != release_sha256:
        raise ProductionEvidenceError("production acceptance manifest release_sha256 is invalid")
    inventory_sha256 = _validate_artifact_inventory(
        value["artifact_inventory"],
        target=value["target"],
        claim_scope=value["claim_scope"],
        expected_artifacts=release_artifacts,
    )
    if value["artifact_inventory_sha256"] != inventory_sha256:
        raise ProductionEvidenceError(
            "production acceptance manifest artifact_inventory_sha256 is invalid"
        )
    staging_sha256 = _validate_publication_staging(
        value["publication_staging"],
        expected_assets=release_artifacts,
    )
    if value["publication_staging_sha256"] != staging_sha256:
        raise ProductionEvidenceError(
            "production acceptance manifest publication_staging_sha256 is invalid"
        )
    release = value["release"]
    staging = value["publication_staging"]
    for release_field, staging_field in (
        ("source_repository", "repository"),
        ("source_repository_id", "repository_id"),
        ("source_commit", "target_commitish"),
    ):
        if release[release_field] != staging[staging_field]:
            raise ProductionEvidenceError(
                f"publication staging {staging_field} differs from the release candidate"
            )
    if release["tag"] is not None and release["tag"] != staging["tag"]:
        raise ProductionEvidenceError(
            "publication staging tag differs from the release candidate"
        )

    decision_pair = _validated_pair(
        (
            value["qualification_evidence_decision_receipt_reference"],
            value["qualification_evidence_decision_receipt_bundle_reference"],
        ),
        "qualification-evidence-decision-receipt",
    )
    admission_pair = _validated_pair(
        (
            value["qualification_admission_reference"],
            value["qualification_admission_bundle_reference"],
        ),
        "qualification-admission",
    )
    receipt = _parse_registered_regular_object(
        qualification_evidence_decision_receipt_bytes,
        reference=decision_pair[0],
        expected_kind="qualification-evidence-decision-receipt",
    )
    admission = _parse_registered_regular_object(
        qualification_admission_bytes,
        reference=admission_pair[0],
        expected_kind="qualification-admission",
    )
    receipt_summary = _validate_decision_receipt(
        receipt,
        reference=decision_pair[0],
        expected_signer_registry_sha256=value["signer_registry_sha256"],
        expected_revocation_state_sha256=value["revocation_state_sha256"],
        signer_registry_bytes=signer_registry_bytes,
    )
    admission_validity = _validate_qualification_admission(
        admission,
        reference=admission_pair[0],
        decision_receipt=receipt,
        decision_references=decision_pair,
    )
    _validate_campaign_summary(value["campaign_summary"])
    if value["campaign_summary"] != receipt_summary:
        raise ProductionEvidenceError(
            "production acceptance manifest campaign_summary differs from public trust objects"
        )

    issued = _validate_timestamp(
        value["issued_at"], "production acceptance manifest issued_at"
    )
    not_before = _validate_timestamp(
        value["not_before"], "production acceptance manifest not_before"
    )
    expires = _validate_timestamp(
        value["expires_at"], "production acceptance manifest expires_at"
    )
    if not (not_before <= issued < expires):
        raise ProductionEvidenceError("production acceptance manifest validity is invalid")
    staging_observed = _validate_timestamp(
        value["publication_staging"]["observed_at"],
        "publication staging observed_at",
    )
    if staging_observed > issued:
        raise ProductionEvidenceError(
            "publication staging was observed after manifest issuance"
        )
    receipt_not_before = _validate_timestamp(
        receipt["not_before"],
        "decision receipt not_before",
    )
    receipt_issued = _validate_timestamp(
        receipt["issued_at"],
        "decision receipt issued_at",
    )
    receipt_expires = _validate_timestamp(
        receipt["expires_at"],
        "decision receipt expires_at",
    )
    if not (
        receipt_not_before <= receipt_issued <= issued
        and not_before >= receipt_not_before
        and expires <= receipt_expires
    ):
        raise ProductionEvidenceError(
            "production acceptance manifest validity exceeds the public decision receipt"
        )
    admission_not_before, admission_issued, admission_expires = admission_validity
    if not (
        admission_not_before <= admission_issued <= issued
        and not_before >= admission_not_before
        and expires <= admission_expires
    ):
        raise ProductionEvidenceError(
            "production acceptance manifest validity exceeds the public admission"
        )
    return not_before, issued, expires


def _validate_production_acceptance_manifest_reference(
    manifest_bytes: bytes,
    *,
    reference: Mapping[str, Any],
    qualification_evidence_decision_receipt_bytes: bytes,
    qualification_admission_bytes: bytes,
    signer_registry_bytes: bytes,
) -> tuple[dict[str, Any], tuple[datetime, datetime, datetime]]:
    manifest = _parse_registered_regular_object(
        manifest_bytes,
        reference=reference,
        expected_kind="production-acceptance-manifest",
    )
    validity = validate_production_acceptance_manifest(
        manifest,
        qualification_evidence_decision_receipt_bytes=(
            qualification_evidence_decision_receipt_bytes
        ),
        qualification_admission_bytes=qualification_admission_bytes,
        signer_registry_bytes=signer_registry_bytes,
    )
    return manifest, validity


def build_production_acceptance_summary(
    *,
    target: str,
    claim_scope: str,
    acceptance_policy_sha256: str,
    lifecycle_policy_sha256: str,
    release_identity: Mapping[str, Any],
    release_sha256: str,
    artifact_inventory_sha256: str,
    publication_staging: Mapping[str, Any],
    signer_registry_bytes: bytes,
    qualification_evidence_decision_receipt_bytes: bytes,
    qualification_evidence_decision_receipt_references: Sequence[Mapping[str, Any]],
    qualification_admission_bytes: bytes,
    qualification_admission_references: Sequence[Mapping[str, Any]],
    production_acceptance_manifest_bytes: bytes,
    production_acceptance_manifest_references: Sequence[Mapping[str, Any]],
    authority_state_sha256: str,
    revocation_state_sha256: str,
    signer_registry_sha256: str,
    issuer: Mapping[str, Any],
    issued_at: str,
    not_before: str,
    expires_at: str,
) -> dict[str, Any]:
    """Build the remote-safe v2 summary after all three input pairs exist."""

    decision_pair = _validated_pair(
        qualification_evidence_decision_receipt_references,
        "qualification-evidence-decision-receipt",
    )
    admission_pair = _validated_pair(qualification_admission_references, "qualification-admission")
    manifest_pair = _validated_pair(
        production_acceptance_manifest_references, "production-acceptance-manifest"
    )
    release = dict(release_identity)
    receipt = _parse_registered_regular_object(
        qualification_evidence_decision_receipt_bytes,
        reference=decision_pair[0],
        expected_kind="qualification-evidence-decision-receipt",
    )
    campaign = _validate_decision_receipt(
        receipt,
        reference=decision_pair[0],
        expected_signer_registry_sha256=signer_registry_sha256,
        expected_revocation_state_sha256=revocation_state_sha256,
        signer_registry_bytes=signer_registry_bytes,
    )
    admission = _parse_registered_regular_object(
        qualification_admission_bytes,
        reference=admission_pair[0],
        expected_kind="qualification-admission",
    )
    _validate_qualification_admission(
        admission,
        reference=admission_pair[0],
        decision_receipt=receipt,
        decision_references=decision_pair,
    )
    manifest, _ = _validate_production_acceptance_manifest_reference(
        production_acceptance_manifest_bytes,
        reference=manifest_pair[0],
        qualification_evidence_decision_receipt_bytes=(
            qualification_evidence_decision_receipt_bytes
        ),
        qualification_admission_bytes=qualification_admission_bytes,
        signer_registry_bytes=signer_registry_bytes,
    )
    staging = _detached_json_object(publication_staging, "publication staging")
    staging_sha256 = _validate_publication_staging(
        staging,
        expected_assets=manifest["artifact_inventory"]["artifacts"],
    )
    summary: dict[str, Any] = {
        "schema_version": PRODUCTION_ACCEPTANCE_SUMMARY_SCHEMA,
        "target": target,
        "verdict": "accepted",
        "claim_scope": claim_scope,
        "acceptance_policy_sha256": acceptance_policy_sha256,
        "lifecycle_policy_sha256": lifecycle_policy_sha256,
        "release_identity": release,
        "release_sha256": release_sha256,
        "artifact_inventory_sha256": artifact_inventory_sha256,
        "publication_staging": staging,
        "publication_staging_sha256": staging_sha256,
        "evidence_identity_sha256": "sha256:" + "0" * 64,
        "qualification_evidence_decision_receipt_reference": decision_pair[0],
        "qualification_evidence_decision_receipt_bundle_reference": decision_pair[1],
        "qualification_admission_reference": admission_pair[0],
        "qualification_admission_bundle_reference": admission_pair[1],
        "production_acceptance_manifest_reference": manifest_pair[0],
        "production_acceptance_manifest_bundle_reference": manifest_pair[1],
        "campaign_summary": campaign,
        "authority_state_sha256": authority_state_sha256,
        "revocation_state_sha256": revocation_state_sha256,
        "signer_registry_sha256": signer_registry_sha256,
        "issuer": _detached_json_object(issuer, "production acceptance issuer"),
        "issued_at": issued_at,
        "not_before": not_before,
        "expires_at": expires_at,
    }
    summary["evidence_identity_sha256"] = _production_evidence_identity(summary)
    validate_production_acceptance_summary(
        summary,
        qualification_evidence_decision_receipt_bytes=(
            qualification_evidence_decision_receipt_bytes
        ),
        qualification_admission_bytes=qualification_admission_bytes,
        production_acceptance_manifest_bytes=production_acceptance_manifest_bytes,
        signer_registry_bytes=signer_registry_bytes,
    )
    return summary


def validate_production_acceptance_summary(
    summary: Mapping[str, Any],
    *,
    qualification_evidence_decision_receipt_bytes: bytes,
    qualification_admission_bytes: bytes,
    production_acceptance_manifest_bytes: bytes,
    signer_registry_bytes: bytes,
) -> None:
    """Validate a v2 summary without reading any private campaign payload."""

    value = dict(summary)
    if set(value) != _SUMMARY_KEYS:
        missing = sorted(_SUMMARY_KEYS - set(value))
        extra = sorted(set(value) - _SUMMARY_KEYS)
        raise ProductionEvidenceError(
            f"production summary keys differ: missing={missing}, extra={extra}"
        )
    if value["schema_version"] != PRODUCTION_ACCEPTANCE_SUMMARY_SCHEMA:
        raise ProductionEvidenceError("production summary schema_version is invalid")
    for field in ("target", "claim_scope"):
        if not isinstance(value[field], str) or not value[field]:
            raise ProductionEvidenceError(f"production summary {field} is invalid")
    if value["verdict"] != "accepted":
        raise ProductionEvidenceError("production summary verdict must be accepted")
    for field in (
        "acceptance_policy_sha256",
        "lifecycle_policy_sha256",
        "release_sha256",
        "artifact_inventory_sha256",
        "publication_staging_sha256",
        "evidence_identity_sha256",
        "authority_state_sha256",
        "revocation_state_sha256",
        "signer_registry_sha256",
    ):
        _require_digest(value[field], field)
    _validate_release_identity(value["release_identity"])
    _validate_production_acceptance_issuer(value["issuer"])
    _validate_summary_reference_fields(value)
    manifest, manifest_validity = _validate_production_acceptance_manifest_reference(
        production_acceptance_manifest_bytes,
        reference=value["production_acceptance_manifest_reference"],
        qualification_evidence_decision_receipt_bytes=(
            qualification_evidence_decision_receipt_bytes
        ),
        qualification_admission_bytes=qualification_admission_bytes,
        signer_registry_bytes=signer_registry_bytes,
    )
    staging_sha256 = _validate_publication_staging(
        value["publication_staging"],
        expected_assets=manifest["artifact_inventory"]["artifacts"],
    )
    if value["publication_staging_sha256"] != staging_sha256:
        raise ProductionEvidenceError("publication_staging_sha256 is invalid")
    receipt_summary = _validate_decision_receipt(
        _parse_registered_regular_object(
            qualification_evidence_decision_receipt_bytes,
            reference=value["qualification_evidence_decision_receipt_reference"],
            expected_kind="qualification-evidence-decision-receipt",
        ),
        reference=value["qualification_evidence_decision_receipt_reference"],
        expected_signer_registry_sha256=value["signer_registry_sha256"],
        expected_revocation_state_sha256=value["revocation_state_sha256"],
        signer_registry_bytes=signer_registry_bytes,
    )
    receipt = _parse_registered_regular_object(
        qualification_evidence_decision_receipt_bytes,
        reference=value["qualification_evidence_decision_receipt_reference"],
        expected_kind="qualification-evidence-decision-receipt",
    )
    admission = _parse_registered_regular_object(
        qualification_admission_bytes,
        reference=value["qualification_admission_reference"],
        expected_kind="qualification-admission",
    )
    admission_validity = _validate_qualification_admission(
        admission,
        reference=value["qualification_admission_reference"],
        decision_receipt=receipt,
        decision_references=(
            value["qualification_evidence_decision_receipt_reference"],
            value["qualification_evidence_decision_receipt_bundle_reference"],
        ),
    )
    _validate_campaign_summary(value["campaign_summary"])
    if value["campaign_summary"] != receipt_summary:
        raise ProductionEvidenceError("campaign_summary differs from the public decision receipt")
    for field in (
        "target",
        "claim_scope",
        "acceptance_policy_sha256",
        "lifecycle_policy_sha256",
        "release_identity",
        "release_sha256",
        "artifact_inventory_sha256",
        "publication_staging",
        "publication_staging_sha256",
        "qualification_evidence_decision_receipt_reference",
        "qualification_evidence_decision_receipt_bundle_reference",
        "qualification_admission_reference",
        "qualification_admission_bundle_reference",
        "campaign_summary",
        "authority_state_sha256",
        "revocation_state_sha256",
        "signer_registry_sha256",
        "issuer",
    ):
        if value[field] != manifest[field]:
            raise ProductionEvidenceError(
                f"production summary {field} differs from its public manifest"
            )
    issued = _validate_timestamp(value["issued_at"], "issued_at")
    not_before = _validate_timestamp(value["not_before"], "not_before")
    expires = _validate_timestamp(value["expires_at"], "expires_at")
    if not (not_before <= issued < expires):
        raise ProductionEvidenceError(
            "production summary validity must satisfy not_before <= issued_at < expires_at"
        )
    receipt_issued = _validate_timestamp(
        receipt["issued_at"],
        "decision receipt issued_at",
    )
    receipt_not_before = _validate_timestamp(
        receipt["not_before"],
        "decision receipt not_before",
    )
    receipt_expires = _validate_timestamp(
        receipt["expires_at"],
        "decision receipt expires_at",
    )
    if not (
        receipt_not_before <= receipt_issued <= issued
        and not_before >= receipt_not_before
        and expires <= receipt_expires
    ):
        raise ProductionEvidenceError(
            "production summary validity exceeds the public decision receipt"
        )
    admission_not_before, admission_issued, admission_expires = admission_validity
    if not (
        admission_not_before <= admission_issued <= issued
        and not_before >= admission_not_before
        and expires <= admission_expires
    ):
        raise ProductionEvidenceError(
            "production summary validity exceeds the public qualification admission"
        )
    manifest_not_before, manifest_issued, manifest_expires = manifest_validity
    if not (
        manifest_not_before <= manifest_issued <= issued
        and not_before >= manifest_not_before
        and expires <= manifest_expires
    ):
        raise ProductionEvidenceError(
            "production summary validity exceeds the public acceptance manifest"
        )
    if value["evidence_identity_sha256"] != _production_evidence_identity(value):
        raise ProductionEvidenceError("evidence_identity_sha256 is invalid")


def validate_reference_pair(
    references: Sequence[Mapping[str, Any]],
    *,
    expected_regular_kind: str | None = None,
) -> None:
    """Reject a reference pair that changes kind, order, digest, or subject binding."""

    if len(references) != 2:
        raise ProductionEvidenceError(
            "an evidence pair must contain one regular object and one bundle"
        )
    regular = dict(references[0])
    bundle = dict(references[1])
    validate_object_reference(regular)
    validate_object_reference(bundle)
    kind = regular["kind"]
    if expected_regular_kind is not None and kind != expected_regular_kind:
        raise ProductionEvidenceError(f"regular evidence kind must be {expected_regular_kind!r}")
    if bundle["kind"] != f"{kind}-sigstore-bundle":
        raise ProductionEvidenceError("the Sigstore bundle must immediately follow its subject")
    if regular["subject_sha256"] is not None:
        raise ProductionEvidenceError("a regular evidence object subject must be null")
    if bundle["subject_sha256"] != regular["object_sha256"]:
        raise ProductionEvidenceError("the Sigstore bundle subject does not bind its object")
    for field in (
        "registry_source_commit",
        "registry_revision",
        "registry_head_sha256",
    ):
        if bundle[field] != regular[field]:
            raise ProductionEvidenceError(f"the evidence pair does not share {field}")


def validate_object_reference(reference: Mapping[str, Any]) -> None:
    """Validate the complete 16-key v2 public object-reference contract."""

    value = dict(reference)
    if set(value) != REFERENCE_KEYS:
        missing = sorted(REFERENCE_KEYS - set(value))
        extra = sorted(set(value) - REFERENCE_KEYS)
        raise ProductionEvidenceError(
            f"object reference keys differ: missing={missing}, extra={extra}"
        )
    expected_constants = {
        "schema_version": OBJECT_REFERENCE_SCHEMA,
        "repository": EVIDENCE_REPOSITORY,
        "repository_id": EVIDENCE_REPOSITORY_ID,
        "repository_owner_id": EVIDENCE_REPOSITORY_OWNER_ID,
    }
    for field, expected in expected_constants.items():
        if value[field] != expected:
            raise ProductionEvidenceError(f"object reference {field} is invalid")
    if not isinstance(value["registry_source_commit"], str) or not _HEX40.fullmatch(
        value["registry_source_commit"]
    ):
        raise ProductionEvidenceError("registry_source_commit must be 40 lowercase hex")
    _require_positive_int(value["registry_revision"], "registry_revision")
    for field in (
        "registry_head_sha256",
        "registry_entry_sha256",
        "object_sha256",
        "semantic_identity_sha256",
    ):
        _require_digest(value[field], field)
    _require_positive_int(value["size_bytes"], "size_bytes")
    _validate_object_path(value["object_path"])

    kind = value["kind"]
    if not isinstance(kind, str) or not _KIND.fullmatch(kind):
        raise ProductionEvidenceError("kind is invalid")
    if kind.endswith("-sigstore-bundle"):
        regular_kind = kind.removesuffix("-sigstore-bundle")
        if regular_kind not in REGULAR_EVIDENCE_KINDS:
            raise ProductionEvidenceError("bundle kind has no approved regular kind")
        if (
            value["object_schema_version"] != SIGSTORE_BUNDLE_MEDIA_TYPE
            or value["object_media_type"] != SIGSTORE_BUNDLE_MEDIA_TYPE
        ):
            raise ProductionEvidenceError("raw Sigstore bundle schema or media type is invalid")
        _require_digest(value["subject_sha256"], "subject_sha256")
    else:
        profile = REGULAR_EVIDENCE_KINDS.get(kind)
        if profile is None:
            raise ProductionEvidenceError(f"evidence kind is not approved: {kind!r}")
        if value["object_schema_version"] != profile.schema_version:
            raise ProductionEvidenceError("regular object schema version is invalid")
        if value["object_media_type"] != profile.media_type:
            raise ProductionEvidenceError("regular object media type is invalid")
        if value["subject_sha256"] is not None:
            raise ProductionEvidenceError("a regular object subject must be null")

    raw_digest = value["object_sha256"].removeprefix("sha256:")
    expected_path = f"{OBJECT_PATH_PREFIX}/{raw_digest[:2]}/{raw_digest}.{kind}.json"
    if value["object_path"] != expected_path:
        raise ProductionEvidenceError("object_path is not content-addressed by object_sha256")
    expected_entry = _registry_entry_sha256(value)
    if value["registry_entry_sha256"] != expected_entry:
        raise ProductionEvidenceError("registry_entry_sha256 is invalid")


def _build_reference(
    *,
    kind: str,
    object_schema_version: str,
    object_media_type: str,
    object_bytes: bytes,
    object_sha256: str,
    semantic_identity_sha256: str,
    subject_sha256: str | None,
    registry_source_commit: str,
    registry_revision: int,
    registry_head_sha256: str,
) -> dict[str, Any]:
    if not _HEX40.fullmatch(registry_source_commit):
        raise ProductionEvidenceError("registry_source_commit must be 40 lowercase hex")
    _require_positive_int(registry_revision, "registry_revision")
    _require_digest(registry_head_sha256, "registry_head_sha256")
    _require_digest(object_sha256, "object_sha256")
    _require_digest(semantic_identity_sha256, "semantic_identity_sha256")
    if subject_sha256 is not None:
        _require_digest(subject_sha256, "subject_sha256")
    raw_digest = object_sha256.removeprefix("sha256:")
    reference: dict[str, Any] = {
        "schema_version": OBJECT_REFERENCE_SCHEMA,
        "repository": EVIDENCE_REPOSITORY,
        "repository_id": EVIDENCE_REPOSITORY_ID,
        "repository_owner_id": EVIDENCE_REPOSITORY_OWNER_ID,
        "registry_source_commit": registry_source_commit,
        "registry_revision": registry_revision,
        "registry_head_sha256": registry_head_sha256,
        "registry_entry_sha256": "sha256:" + "0" * 64,
        "kind": kind,
        "object_schema_version": object_schema_version,
        "object_path": (f"{OBJECT_PATH_PREFIX}/{raw_digest[:2]}/{raw_digest}.{kind}.json"),
        "object_sha256": object_sha256,
        "size_bytes": len(object_bytes),
        "object_media_type": object_media_type,
        "semantic_identity_sha256": semantic_identity_sha256,
        "subject_sha256": subject_sha256,
    }
    reference["registry_entry_sha256"] = _registry_entry_sha256(reference)
    validate_object_reference(reference)
    return reference


def _registry_entry_sha256(reference: Mapping[str, Any]) -> str:
    projection = {field: reference[field] for field in REGISTRY_ENTRY_KEYS}
    return sha256_digest(REGISTRY_ENTRY_DIGEST_DOMAIN + canonical_json_bytes(projection))


def _validated_pair(
    references: Sequence[Mapping[str, Any]], expected_kind: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    validate_reference_pair(references, expected_regular_kind=expected_kind)
    return dict(references[0]), dict(references[1])


def _validate_summary_reference_fields(value: Mapping[str, Any]) -> None:
    fields = (
        (
            "qualification_evidence_decision_receipt_reference",
            "qualification_evidence_decision_receipt_bundle_reference",
            "qualification-evidence-decision-receipt",
        ),
        (
            "qualification_admission_reference",
            "qualification_admission_bundle_reference",
            "qualification-admission",
        ),
        (
            "production_acceptance_manifest_reference",
            "production_acceptance_manifest_bundle_reference",
            "production-acceptance-manifest",
        ),
    )
    for regular_field, bundle_field, kind in fields:
        regular = value[regular_field]
        bundle = value[bundle_field]
        if not isinstance(regular, Mapping) or not isinstance(bundle, Mapping):
            raise ProductionEvidenceError(f"{kind} references must be objects")
        validate_reference_pair((regular, bundle), expected_regular_kind=kind)


def _validate_release_identity(value: Any) -> None:
    if not isinstance(value, Mapping) or set(value) != _RELEASE_IDENTITY_KEYS:
        raise ProductionEvidenceError("release_identity keys are invalid")
    if value["schema_version"] != "openadapt.monotonic-production-release/v1":
        raise ProductionEvidenceError("release_identity schema_version is invalid")
    if value["channel"] != "production":
        raise ProductionEvidenceError("release_identity channel must be production")
    sequence = _require_positive_int(value["sequence"], "release_identity.sequence")
    previous = value["previous_admission_sha256"]
    if sequence == 1:
        if previous is not None:
            raise ProductionEvidenceError(
                "the first release identity previous admission must be null"
            )
    else:
        _require_digest(previous, "release_identity.previous_admission_sha256")


def _validate_production_acceptance_issuer(value: Any) -> None:
    if (
        not isinstance(value, Mapping)
        or set(value) != _PRODUCTION_ACCEPTANCE_ISSUER_KEYS
    ):
        raise ProductionEvidenceError("production acceptance issuer keys are invalid")
    expected = {
        "repository": "OpenAdaptAI/openadapt-evals",
        "repository_id": "1135998197",
        "repository_owner_id": "132681217",
        "workflow": ".github/workflows/issue-production-acceptance.yml",
        "ref": "refs/heads/main",
        "environment": "production-acceptance",
    }
    for field, expected_value in expected.items():
        if value[field] != expected_value:
            raise ProductionEvidenceError(
                f"production acceptance issuer {field} is invalid"
            )
    if not isinstance(value["source_commit"], str) or not _HEX40.fullmatch(
        value["source_commit"]
    ):
        raise ProductionEvidenceError(
            "production acceptance issuer source_commit is invalid"
        )


def _parse_canonical_object_bytes(raw: Any, context: str) -> dict[str, Any]:
    if not isinstance(raw, bytes) or not raw or not raw.endswith(b"\n"):
        raise ProductionEvidenceError(f"{context} must be canonical JSON plus one LF")

    def reject_duplicate_pairs(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
        parsed: dict[str, Any] = {}
        for key, item in pairs:
            if key in parsed:
                raise ProductionEvidenceError(f"{context} contains duplicate key {key!r}")
            parsed[key] = item
        return parsed

    try:
        value = json.loads(
            raw[:-1].decode("utf-8"),
            object_pairs_hook=reject_duplicate_pairs,
            parse_float=lambda item: (_ for _ in ()).throw(
                ProductionEvidenceError(f"{context} contains float {item}")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProductionEvidenceError(f"{context} is not one UTF-8 JSON object") from exc
    if not isinstance(value, dict) or canonical_object_bytes(value) != raw:
        raise ProductionEvidenceError(f"{context} must be canonical JSON plus one LF")
    return value


def _canonical_base64(value: Any, *, size: int, context: str) -> bytes:
    if not isinstance(value, str) or not value:
        raise ProductionEvidenceError(f"{context} is invalid")
    try:
        decoded = base64.b64decode(value, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ProductionEvidenceError(f"{context} is invalid") from exc
    if len(decoded) != size or base64.b64encode(decoded).decode("ascii") != value:
        raise ProductionEvidenceError(f"{context} is not canonical padded base64")
    return decoded


def _canonical_base64url_unpadded(value: Any, *, size: int, context: str) -> bytes:
    if (
        not isinstance(value, str)
        or not value
        or "=" in value
        or re.fullmatch(r"[A-Za-z0-9_-]+", value) is None
    ):
        raise ProductionEvidenceError(f"{context} is invalid")
    try:
        decoded = base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))
    except (binascii.Error, ValueError) as exc:
        raise ProductionEvidenceError(f"{context} is invalid") from exc
    canonical = base64.urlsafe_b64encode(decoded).rstrip(b"=").decode("ascii")
    if len(decoded) != size or canonical != value:
        raise ProductionEvidenceError(f"{context} is not canonical unpadded base64url")
    return decoded


def _validate_decision_receipt_issuer(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping) or set(value) != _DECISION_RECEIPT_ISSUER_KEYS:
        raise ProductionEvidenceError("decision receipt issuer keys are invalid")
    expected = {
        "repository": "OpenAdaptAI/openadapt-internal",
        "repository_id": "1170060695",
        "repository_owner_id": "132681217",
        "workflow": ".github/workflows/issue-private-qualification-evidence-decision.yml",
        "ref": "refs/heads/main",
        "environment": "private-qualification-evidence-decision",
    }
    for field, expected_value in expected.items():
        if value[field] != expected_value:
            raise ProductionEvidenceError(f"decision receipt issuer {field} is invalid")
    if not isinstance(value["source_commit"], str) or _HEX40.fullmatch(
        value["source_commit"]
    ) is None:
        raise ProductionEvidenceError("decision receipt issuer source_commit is invalid")
    return dict(value)


def _validate_signer_registry_for_receipt(
    raw: bytes,
    *,
    expected_identity_sha256: str,
    receipt: Mapping[str, Any],
    issued_at: datetime,
) -> bytes:
    registry = _parse_canonical_object_bytes(raw, "qualification signer registry")
    if set(registry) != _SIGNER_REGISTRY_KEYS:
        raise ProductionEvidenceError("qualification signer registry keys are invalid")
    if registry["schema_version"] != SIGNER_REGISTRY_SCHEMA:
        raise ProductionEvidenceError("qualification signer registry schema is invalid")
    _require_positive_int(registry["revision"], "qualification signer registry revision")
    generated = _validate_timestamp(
        registry["generated_at"], "qualification signer registry generated_at"
    )
    expires = _validate_timestamp(
        registry["expires_at"], "qualification signer registry expires_at"
    )
    if not generated <= issued_at < expires or expires > generated + timedelta(days=7):
        raise ProductionEvidenceError("qualification signer registry is not active")
    observed_identity = signer_registry_identity(registry)
    if observed_identity != expected_identity_sha256:
        raise ProductionEvidenceError("qualification signer registry identity differs")
    signers = registry["signers"]
    if not isinstance(signers, list) or not 1 <= len(signers) <= 128:
        raise ProductionEvidenceError("qualification signer registry signers are invalid")
    previous_key_id = ""
    selected: tuple[dict[str, Any], bytes] | None = None
    for index, signer_value in enumerate(signers):
        if not isinstance(signer_value, Mapping) or set(signer_value) != _SIGNER_KEYS:
            raise ProductionEvidenceError("qualification signer registry signer keys are invalid")
        signer = dict(signer_value)
        if signer["algorithm"] != "ed25519":
            raise ProductionEvidenceError("qualification signer algorithm is invalid")
        raw_public_key = _canonical_base64url_unpadded(
            signer["public_key"],
            size=32,
            context=f"qualification signer {index} public key",
        )
        spki = bytes.fromhex("302a300506032b6570032100") + raw_public_key
        if signer["public_key_spki_der_base64"] != base64.b64encode(spki).decode("ascii"):
            raise ProductionEvidenceError("qualification signer SPKI is invalid")
        if signer["public_key_sha256"] != sha256_digest(spki):
            raise ProductionEvidenceError("qualification signer fingerprint is invalid")
        expected_key_id = f"qa-ed25519-{hashlib.sha256(raw_public_key).hexdigest()[:16]}"
        if signer["key_id"] != expected_key_id or expected_key_id <= previous_key_id:
            raise ProductionEvidenceError("qualification signer key identity or order is invalid")
        previous_key_id = expected_key_id
        for field in (
            "statement_schema_versions",
            "allowed_workflows",
            "allowed_ref_prefixes",
            "allowed_usages",
        ):
            items = signer[field]
            if (
                not isinstance(items, list)
                or not items
                or items != sorted(set(items))
                or any(not isinstance(item, str) or not item for item in items)
            ):
                raise ProductionEvidenceError(f"qualification signer {field} is invalid")
        if signer["statement_schema_versions"] != [
            DECISION_RECEIPT_SIGNING_STATEMENT_SCHEMA
        ]:
            raise ProductionEvidenceError("qualification signer statement schema is invalid")
        if signer["status"] == "active":
            if signer["revoked_at"] is not None:
                raise ProductionEvidenceError("active qualification signer is revoked")
        elif signer["status"] == "revoked":
            revoked = _validate_timestamp(
                signer["revoked_at"], f"qualification signer {index} revoked_at"
            )
            if not generated <= revoked < expires:
                raise ProductionEvidenceError("qualification signer revocation time is invalid")
        else:
            raise ProductionEvidenceError("qualification signer status is invalid")
        if signer["key_id"] == receipt["issuer_key_id"]:
            selected = signer, raw_public_key
    if selected is None:
        raise ProductionEvidenceError("decision receipt signer is absent from the registry")
    signer, raw_public_key = selected
    issuer = receipt["issuer"]
    workflow = f"https://github.com/{issuer['repository']}/{issuer['workflow']}"
    if (
        signer["status"] != "active"
        or signer["revoked_at"] is not None
        or "qualification-evidence-decision-receipt" not in signer["allowed_usages"]
        or workflow not in signer["allowed_workflows"]
        or not any(issuer["ref"].startswith(prefix) for prefix in signer["allowed_ref_prefixes"])
    ):
        raise ProductionEvidenceError("decision receipt signer is not authorized")
    return raw_public_key


def _validate_decision_receipt(
    value: Mapping[str, Any],
    *,
    reference: Mapping[str, Any],
    expected_signer_registry_sha256: str,
    expected_revocation_state_sha256: str,
    signer_registry_bytes: bytes,
) -> dict[str, Any]:
    receipt = dict(value)
    if set(receipt) != _DECISION_RECEIPT_KEYS:
        missing = sorted(_DECISION_RECEIPT_KEYS - set(receipt))
        extra = sorted(set(receipt) - _DECISION_RECEIPT_KEYS)
        raise ProductionEvidenceError(
            f"decision receipt keys differ: missing={missing}, extra={extra}"
        )
    if receipt["schema_version"] != DECISION_RECEIPT_SCHEMA:
        raise ProductionEvidenceError("decision receipt schema_version is invalid")
    for field in _DECISION_RECEIPT_KEYS:
        if field.endswith("_sha256"):
            _require_digest(receipt[field], f"decision receipt {field}")
    _require_positive_int(receipt["decision_revision"], "decision receipt decision_revision")
    if receipt["signer_registry_sha256"] != expected_signer_registry_sha256:
        raise ProductionEvidenceError("decision receipt signer registry differs")
    if receipt["revocation_state_sha256"] != expected_revocation_state_sha256:
        raise ProductionEvidenceError("decision receipt revocation state differs")
    if (
        not isinstance(receipt["bundle_version"], str)
        or len(receipt["bundle_version"]) > 64
        or _BUNDLE_VERSION.fullmatch(receipt["bundle_version"]) is None
    ):
        raise ProductionEvidenceError("decision receipt bundle_version is invalid")
    if receipt["entity_class"] not in {
        "insurance claim",
        "item",
        "loan application",
        "patient record",
        "record",
    }:
        raise ProductionEvidenceError("decision receipt entity_class is not remote-safe")
    if receipt["verdict"] != "ADMIT":
        raise ProductionEvidenceError("decision receipt verdict must be ADMIT")
    if receipt["algorithm"] != "ed25519":
        raise ProductionEvidenceError("decision receipt algorithm must be ed25519")
    if not isinstance(receipt["issuer_key_id"], str) or _DECISION_KEY_ID.fullmatch(
        receipt["issuer_key_id"]
    ) is None:
        raise ProductionEvidenceError("decision receipt issuer_key_id is invalid")
    issuer = _validate_decision_receipt_issuer(receipt["issuer"])
    signature = _canonical_base64(
        receipt["signature"], size=64, context="decision receipt signature"
    )
    issued = _validate_timestamp(receipt["issued_at"], "decision receipt issued_at")
    not_before = _validate_timestamp(receipt["not_before"], "decision receipt not_before")
    expires = _validate_timestamp(receipt["expires_at"], "decision receipt expires_at")
    if (
        not not_before <= issued < expires
        or expires - not_before > timedelta(days=7)
    ):
        raise ProductionEvidenceError("decision receipt validity is invalid")
    public_key = _validate_signer_registry_for_receipt(
        signer_registry_bytes,
        expected_identity_sha256=expected_signer_registry_sha256,
        receipt={**receipt, "issuer": issuer},
        issued_at=issued,
    )
    statement = receipt["signing_statement"]
    if not isinstance(statement, Mapping) or set(statement) != (
        _DECISION_SIGNING_STATEMENT_KEYS
    ):
        raise ProductionEvidenceError("decision receipt signing_statement keys are invalid")
    unsigned = dict(receipt)
    unsigned.pop("signing_statement")
    unsigned.pop("signature")
    unsigned_bytes = canonical_object_bytes(unsigned)
    expected_statement = {
        "schema_version": DECISION_RECEIPT_SIGNING_STATEMENT_SCHEMA,
        "object_schema_version": DECISION_RECEIPT_SCHEMA,
        "signature_domain": DECISION_RECEIPT_SIGNATURE_DOMAIN,
        "unsigned_object_sha256": sha256_digest(unsigned_bytes),
        "unsigned_size_bytes": len(unsigned_bytes),
        "commitment_scheme": "sha256-canonical-json-lf",
    }
    if statement != expected_statement:
        raise ProductionEvidenceError("decision receipt signing_statement differs")
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(
            signature,
            canonical_object_bytes(statement),
        )
    except (InvalidSignature, ValueError) as exc:
        raise ProductionEvidenceError("decision receipt signature verification failed") from exc
    if not isinstance(reference, Mapping):
        raise ProductionEvidenceError("decision receipt reference must be an object")
    validate_object_reference(reference)
    if reference["kind"] != "qualification-evidence-decision-receipt":
        raise ProductionEvidenceError("decision receipt reference kind is invalid")
    if reference["semantic_identity_sha256"] != decision_receipt_semantic_identity(receipt):
        raise ProductionEvidenceError("decision receipt semantic identity is invalid")

    campaign_summary = receipt["campaign_summary"]
    if not isinstance(campaign_summary, Mapping) or set(campaign_summary) != (
        _DECISION_CAMPAIGN_SUMMARY_KEYS
    ):
        raise ProductionEvidenceError("decision receipt campaign_summary keys are invalid")
    if campaign_summary["schema_version"] != DECISION_CAMPAIGN_SUMMARY_SCHEMA:
        raise ProductionEvidenceError("decision receipt campaign_summary schema_version is invalid")
    minimum = _require_positive_int(
        campaign_summary["minimum_trials_per_task_condition"],
        "decision receipt minimum_trials_per_task_condition",
    )
    task_count = _require_positive_int(
        campaign_summary["task_count"], "decision receipt task_count"
    )
    if minimum < 3:
        raise ProductionEvidenceError("decision receipt requires fewer than three trials")
    classes = campaign_summary["classes"]
    _validate_campaign_summary(classes)
    if minimum != min(counts["minimum_trials_per_cell"] for counts in classes.values()):
        raise ProductionEvidenceError("decision receipt minimum trial count differs")
    if any(counts["task_condition_cell_count"] < task_count for counts in classes.values()):
        raise ProductionEvidenceError("decision receipt omits a task/class cell")
    return {qualification_class: dict(counts) for qualification_class, counts in classes.items()}


def _validate_qualification_admission(
    value: Mapping[str, Any],
    *,
    reference: Mapping[str, Any],
    decision_receipt: Mapping[str, Any],
    decision_references: Sequence[Mapping[str, Any]],
) -> tuple[datetime, datetime, datetime]:
    admission = dict(value)
    if set(admission) != _QUALIFICATION_ADMISSION_KEYS:
        missing = sorted(_QUALIFICATION_ADMISSION_KEYS - set(admission))
        extra = sorted(set(admission) - _QUALIFICATION_ADMISSION_KEYS)
        raise ProductionEvidenceError(
            f"qualification admission keys differ: missing={missing}, extra={extra}"
        )
    if admission["schema_version"] != QUALIFICATION_ADMISSION_SCHEMA:
        raise ProductionEvidenceError("qualification admission schema_version is invalid")
    for field in _QUALIFICATION_ADMISSION_KEYS:
        if field.endswith("_sha256"):
            _require_digest(admission[field], f"qualification admission {field}")
    if not isinstance(admission["bundle_version"], str) or not admission["bundle_version"]:
        raise ProductionEvidenceError("qualification admission bundle_version is invalid")
    if admission["verdict"] != "accepted":
        raise ProductionEvidenceError("qualification admission verdict must be accepted")
    if admission["entity_class"] not in {
        "insurance claim",
        "item",
        "loan application",
        "patient record",
        "record",
    }:
        raise ProductionEvidenceError("qualification admission entity_class is not remote-safe")

    validate_reference_pair(
        decision_references,
        expected_regular_kind="qualification-evidence-decision-receipt",
    )
    if admission["decision_receipt_reference"] != decision_references[0]:
        raise ProductionEvidenceError("qualification admission decision receipt differs")
    if admission["decision_receipt_bundle_reference"] != decision_references[1]:
        raise ProductionEvidenceError("qualification admission decision bundle differs")

    shared_fields = {
        "organization_id_sha256": "organization_id_sha256",
        "workflow_id_sha256": "workflow_id_sha256",
        "workflow_version_id_sha256": "workflow_version_id_sha256",
        "bundle_version": "bundle_version",
        "bundle_sha256": "bundle_sha256",
        "admitted_runtime_sha256": "admitted_runtime_sha256",
        "application_contract_sha256": "application_contract_sha256",
        "environment_contract_sha256": "environment_contract_sha256",
        "input_contract_sha256": "input_contract_sha256",
        "action_contract_sha256": "action_contract_sha256",
        "identity_contract_sha256": "identity_contract_sha256",
        "effect_contract_sha256": "effect_contract_sha256",
        "policy_contract_sha256": "policy_contract_sha256",
        "evidence_authority_sha256": "evidence_authority_contract_sha256",
        "campaign_artifact_sha256": "campaign_artifact_sha256",
        "campaign_permit_sha256": "campaign_permit_sha256",
        "signer_registry_sha256": "signer_registry_sha256",
        "revocation_state_sha256": "revocation_state_sha256",
        "entity_class": "entity_class",
    }
    for admission_field, receipt_field in shared_fields.items():
        if admission[admission_field] != decision_receipt[receipt_field]:
            raise ProductionEvidenceError(
                f"qualification admission {admission_field} differs from the decision receipt"
            )
    receipt_campaign = decision_receipt["campaign_summary"]
    if (
        not isinstance(receipt_campaign, Mapping)
        or admission["campaign_summary"] != receipt_campaign.get("classes")
    ):
        raise ProductionEvidenceError(
            "qualification admission campaign_summary differs from the decision receipt"
        )
    _validate_campaign_summary(admission["campaign_summary"])

    expected_opening = {
        "schema_version": "openadapt.qualification-local-identity-opening/v1",
        "algorithm": "hmac-sha256",
        "required": True,
        "customer_controlled_secret_required": True,
        "exact_contract_match_required": True,
        "revalidation_before_actuation": True,
        "maximum_age_seconds": 60,
    }
    if (
        not isinstance(admission["local_identity_opening"], Mapping)
        or set(admission["local_identity_opening"]) != _LOCAL_IDENTITY_OPENING_KEYS
        or admission["local_identity_opening"] != expected_opening
    ):
        raise ProductionEvidenceError(
            "qualification admission local_identity_opening is invalid"
        )
    issuer = admission["issuer"]
    expected_issuer = {
        "repository": "OpenAdaptAI/.github",
        "repository_id": "858454062",
        "repository_owner_id": "132681217",
        "workflow": ".github/workflows/issue-qualification-admission.yml",
        "ref": "refs/heads/main",
        "environment": "qualification-admission",
    }
    if not isinstance(issuer, Mapping) or set(issuer) != _ADMISSION_ISSUER_KEYS:
        raise ProductionEvidenceError("qualification admission issuer keys are invalid")
    for field, expected in expected_issuer.items():
        if issuer[field] != expected:
            raise ProductionEvidenceError(
                f"qualification admission issuer {field} is invalid"
            )
    if not isinstance(issuer["source_commit"], str) or not _HEX40.fullmatch(
        issuer["source_commit"]
    ):
        raise ProductionEvidenceError(
            "qualification admission issuer source_commit is invalid"
        )

    not_before = _validate_timestamp(
        admission["not_before"], "qualification admission not_before"
    )
    issued = _validate_timestamp(
        admission["issued_at"], "qualification admission issued_at"
    )
    expires = _validate_timestamp(
        admission["expires_at"], "qualification admission expires_at"
    )
    if not (not_before <= issued < expires):
        raise ProductionEvidenceError("qualification admission validity is invalid")
    if expires - not_before > timedelta(days=7):
        raise ProductionEvidenceError("qualification admission validity exceeds seven days")

    unsigned = dict(admission)
    unsigned.pop("admission_id_sha256")
    expected_admission_id = sha256_digest(
        QUALIFICATION_ADMISSION_ID_DOMAIN + canonical_json_bytes(unsigned)
    )
    if admission["admission_id_sha256"] != expected_admission_id:
        raise ProductionEvidenceError("qualification admission ID is invalid")
    if not isinstance(reference, Mapping):
        raise ProductionEvidenceError("qualification admission reference must be an object")
    validate_object_reference(reference)
    if reference["kind"] != "qualification-admission":
        raise ProductionEvidenceError("qualification admission reference kind is invalid")
    return not_before, issued, expires


def _validate_production_lifecycle_policy(
    raw: bytes,
    *,
    target: str,
    claim_scope: str,
    release: Mapping[str, Any],
    artifacts: Sequence[Mapping[str, Any]],
) -> str:
    if not isinstance(raw, bytes) or not raw:
        raise ProductionEvidenceError("production lifecycle policy bytes are invalid")

    def reject_duplicate_pairs(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ProductionEvidenceError(
                    f"production lifecycle policy contains duplicate key: {key}"
                )
            value[key] = item
        return value

    try:
        policy = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=reject_duplicate_pairs,
            parse_float=lambda value: (_ for _ in ()).throw(
                ProductionEvidenceError(
                    f"production lifecycle policy contains a float: {value}"
                )
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProductionEvidenceError("production lifecycle policy JSON is invalid") from exc
    if not isinstance(policy, Mapping) or set(policy) != _POLICY_KEYS:
        raise ProductionEvidenceError("production lifecycle policy keys are invalid")
    expected_top = {
        "$schema": "schemas/production-lifecycle-policy.schema.json",
        "schema_version": PRODUCTION_LIFECYCLE_POLICY_SCHEMA,
        "maximum_release_admission_days": 30,
        "maximum_workflow_admission_days": 7,
        "object_reference_schema_version": OBJECT_REFERENCE_SCHEMA,
        "release_admission_schema_version": "openadapt.qualification-release/v1",
        "workflow_admission_schema_version": QUALIFICATION_ADMISSION_SCHEMA,
        "lifecycle_checkpoint_schema_version": (
            "openadapt.production-lifecycle-checkpoint/v1"
        ),
        "lifecycle_feed_schema_version": "openadapt.production-lifecycle-feed/v1",
        "lifecycle_feed_ref": "refs/heads/production-lifecycle-feed",
    }
    for field, expected in expected_top.items():
        if policy[field] != expected:
            raise ProductionEvidenceError(
                f"production lifecycle policy {field} is invalid"
            )
    _require_positive_int(policy["revision"], "production lifecycle policy revision")
    if policy["revision"] < 2:
        raise ProductionEvidenceError("production lifecycle policy revision is stale")

    raw_targets = policy["targets"]
    if (
        isinstance(raw_targets, (str, bytes))
        or not isinstance(raw_targets, Sequence)
        or len(raw_targets) != len(_PRODUCT_TARGETS)
    ):
        raise ProductionEvidenceError(
            "production lifecycle policy must contain all seven targets"
        )
    targets: dict[str, dict[str, Any]] = {}
    for index, raw_target in enumerate(raw_targets):
        if not isinstance(raw_target, Mapping) or set(raw_target) != _POLICY_TARGET_KEYS:
            raise ProductionEvidenceError(
                f"production lifecycle policy target {index} keys are invalid"
            )
        entry = dict(raw_target)
        target_id = entry["id"]
        if target_id not in _PRODUCT_TARGETS or target_id in targets:
            raise ProductionEvidenceError(
                f"production lifecycle policy target {index} id is invalid"
            )
        if (
            not isinstance(entry["display_name"], str)
            or not 1 <= len(entry["display_name"]) <= 80
        ):
            raise ProductionEvidenceError(
                f"production lifecycle policy target {target_id} display_name is invalid"
            )
        if (
            not isinstance(entry["source_repository"], str)
            or re.fullmatch(
                r"OpenAdaptAI/[A-Za-z0-9._-]+", entry["source_repository"]
            )
            is None
        ):
            raise ProductionEvidenceError(
                f"production lifecycle policy target {target_id} repository is invalid"
            )
        _require_decimal_id(
            entry["source_repository_id"],
            f"production lifecycle policy target {target_id} repository_id",
        )
        if entry["release_kind"] not in {"package", "deployment", "hybrid"}:
            raise ProductionEvidenceError(
                f"production lifecycle policy target {target_id} release_kind is invalid"
            )
        if entry["claim_scope"] != _PRODUCT_CLAIM_SCOPE_BY_TARGET[target_id]:
            raise ProductionEvidenceError(
                f"production lifecycle policy target {target_id} claim_scope is invalid"
            )
        required_kinds = entry["required_artifact_kinds"]
        if (
            not isinstance(required_kinds, list)
            or not required_kinds
            or required_kinds != sorted(set(required_kinds))
            or any(
                not isinstance(kind, str) or _ARTIFACT_KIND.fullmatch(kind) is None
                for kind in required_kinds
            )
        ):
            raise ProductionEvidenceError(
                f"production lifecycle policy target {target_id} artifact kinds are invalid"
            )
        project = entry["package_index_project"]
        if project is not None and (
            not isinstance(project, str) or _PACKAGE_PROJECT.fullmatch(project) is None
        ):
            raise ProductionEvidenceError(
                f"production lifecycle policy target {target_id} package project is invalid"
            )
        targets[target_id] = entry
    if set(targets) != _PRODUCT_TARGETS:
        raise ProductionEvidenceError(
            "production lifecycle policy does not contain the exact target set"
        )

    selected = targets.get(target)
    if selected is None:
        raise ProductionEvidenceError("production lifecycle policy target is unavailable")
    expected_bindings = {
        "claim_scope": claim_scope,
        "source_repository": release["source_repository"],
        "source_repository_id": release["source_repository_id"],
        "release_kind": release["kind"],
    }
    for field, actual in expected_bindings.items():
        if selected[field] != actual:
            raise ProductionEvidenceError(
                f"production release {field} differs from the lifecycle policy"
            )
    actual_kinds = sorted({artifact["kind"] for artifact in artifacts})
    if actual_kinds != selected["required_artifact_kinds"]:
        raise ProductionEvidenceError(
            "production release artifact kinds differ from the lifecycle policy"
        )
    project = selected["package_index_project"]
    pypi_artifacts = [
        artifact for artifact in artifacts if "pypi" in artifact["publish_destinations"]
    ]
    if project is None:
        if pypi_artifacts:
            raise ProductionEvidenceError(
                "a deployment-only target cannot publish an artifact to PyPI"
            )
    else:
        if not pypi_artifacts:
            raise ProductionEvidenceError(
                "the lifecycle package project has no PyPI artifact"
            )
        normalized_project = project.replace("-", "_")
        for artifact in pypi_artifacts:
            if not (
                artifact["name"].startswith(f"{normalized_project}-")
                or artifact["name"].startswith(f"{project}-")
            ):
                raise ProductionEvidenceError(
                    "a PyPI artifact differs from the lifecycle package project"
                )
    return sha256_digest(raw)


def _validate_release_candidate(
    value: Any,
    *,
    target: str,
    claim_scope: str,
) -> tuple[list[dict[str, Any]], str]:
    if not isinstance(value, Mapping) or set(value) != _RELEASE_CANDIDATE_KEYS:
        raise ProductionEvidenceError("production release candidate keys are invalid")
    release = dict(value)
    if release["schema_version"] != RELEASE_CANDIDATE_SCHEMA:
        raise ProductionEvidenceError("production release candidate schema is invalid")
    if release["kind"] not in {"package", "deployment", "hybrid"}:
        raise ProductionEvidenceError("production release candidate kind is invalid")
    if (
        not isinstance(release["source_repository"], str)
        or re.fullmatch(r"OpenAdaptAI/[A-Za-z0-9._-]+", release["source_repository"])
        is None
    ):
        raise ProductionEvidenceError("production release source_repository is invalid")
    _require_decimal_id(
        release["source_repository_id"], "production release source_repository_id"
    )
    if (
        not isinstance(release["source_commit"], str)
        or _HEX40.fullmatch(release["source_commit"]) is None
    ):
        raise ProductionEvidenceError("production release source_commit is invalid")

    version = release["version"]
    tag = release["tag"]
    deployment_id = release["deployment_id"]
    deployment_sha256 = release["deployment_sha256"]
    if version is not None and (
        not isinstance(version, str) or not 1 <= len(version) <= 80
    ):
        raise ProductionEvidenceError("production release version is invalid")
    if tag is not None and (not isinstance(tag, str) or not 1 <= len(tag) <= 120):
        raise ProductionEvidenceError("production release tag is invalid")
    if deployment_id is not None:
        _require_decimal_id(deployment_id, "production release deployment_id")
    if deployment_sha256 is not None:
        _require_digest(deployment_sha256, "production release deployment_sha256")
    if release["kind"] == "package" and (
        version is None
        or tag is None
        or deployment_id is not None
        or deployment_sha256 is not None
    ):
        raise ProductionEvidenceError("package release identities are invalid")
    if release["kind"] == "deployment" and (
        deployment_id is None or deployment_sha256 is None
    ):
        raise ProductionEvidenceError("deployment release identities are invalid")
    if release["kind"] == "hybrid" and (
        version is None
        or tag is None
        or deployment_id is None
        or deployment_sha256 is None
    ):
        raise ProductionEvidenceError("hybrid release identities are invalid")

    artifacts = _validate_release_artifacts(
        release["artifacts"], context="production release artifacts"
    )
    digest = sha256_digest(
        RELEASE_CANDIDATE_DIGEST_DOMAIN
        + canonical_json_bytes(
            {"target": target, "claim_scope": claim_scope, "release": release}
        )
    )
    return artifacts, digest


def _validate_artifact_inventory(
    value: Any,
    *,
    target: str,
    claim_scope: str,
    expected_artifacts: Sequence[Mapping[str, Any]],
) -> str:
    if not isinstance(value, Mapping) or set(value) != _ARTIFACT_INVENTORY_KEYS:
        raise ProductionEvidenceError("production artifact inventory keys are invalid")
    inventory = dict(value)
    if inventory["schema_version"] != ARTIFACT_INVENTORY_SCHEMA:
        raise ProductionEvidenceError("production artifact inventory schema is invalid")
    if inventory["target"] != target or inventory["claim_scope"] != claim_scope:
        raise ProductionEvidenceError("production artifact inventory target or scope differs")
    artifacts = _validate_release_artifacts(
        inventory["artifacts"], context="production artifact inventory"
    )
    if artifacts != [dict(artifact) for artifact in expected_artifacts]:
        raise ProductionEvidenceError(
            "production artifact inventory differs from the release candidate"
        )
    return sha256_digest(
        ARTIFACT_INVENTORY_DIGEST_DOMAIN
        + canonical_json_bytes(
            {"target": target, "claim_scope": claim_scope, "artifacts": artifacts}
        )
    )


def _validate_release_artifacts(value: Any, *, context: str) -> list[dict[str, Any]]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence) or not value:
        raise ProductionEvidenceError(f"{context} must be a non-empty array")
    artifacts: list[dict[str, Any]] = []
    names: set[str] = set()
    for index, raw_artifact in enumerate(value):
        if not isinstance(raw_artifact, Mapping) or set(raw_artifact) != _EXPECTED_ASSET_KEYS:
            raise ProductionEvidenceError(f"{context} entry {index} keys are invalid")
        artifact = dict(raw_artifact)
        if not _valid_artifact_name(artifact["name"]):
            raise ProductionEvidenceError(f"{context} entry {index} name is invalid")
        folded_name = artifact["name"].casefold()
        if folded_name in names:
            raise ProductionEvidenceError(f"{context} contains a duplicate name")
        names.add(folded_name)
        _validate_release_asset_fields(artifact, f"{context} entry {index}")
        _require_digest(artifact["sha256"], f"{context} entry {index} sha256")
        _require_positive_int(
            artifact["size_bytes"], f"{context} entry {index} size_bytes"
        )
        artifacts.append(artifact)
    if artifacts != sorted(artifacts, key=_artifact_sort_key):
        raise ProductionEvidenceError(
            f"{context} is not sorted by kind, name, and sha256"
        )
    return artifacts


def _artifact_sort_key(artifact: Mapping[str, Any]) -> tuple[str, str, str]:
    return (artifact["kind"], artifact["name"], artifact["sha256"])


def _validate_publication_staging(
    value: Any, *, expected_assets: Sequence[Mapping[str, Any]]
) -> str:
    if not isinstance(value, Mapping) or set(value) != _PUBLICATION_STAGING_KEYS:
        raise ProductionEvidenceError("publication_staging keys are invalid")
    staging = dict(value)
    if staging["schema_version"] != PUBLICATION_STAGING_SCHEMA:
        raise ProductionEvidenceError("publication_staging schema_version is invalid")
    if (
        not isinstance(staging["repository"], str)
        or re.fullmatch(r"OpenAdaptAI/[A-Za-z0-9._-]+", staging["repository"]) is None
    ):
        raise ProductionEvidenceError("publication_staging repository is invalid")
    for field in (
        "repository_id",
        "draft_release_id",
        "release_app_id",
        "release_app_installation_id",
        "release_app_bot_user_id",
    ):
        _require_decimal_id(staging[field], f"publication_staging {field}")
    if (
        staging["release_app_id"] != "4730708"
        or staging["release_app_installation_id"] != "156835568"
        or staging["release_app_bot_user_id"] != "321543906"
        or staging["release_author_login"] != "openadapt-release[bot]"
    ):
        raise ProductionEvidenceError("publication_staging release App identity is invalid")
    if staging["draft"] is not True or staging["prerelease"] is not False:
        raise ProductionEvidenceError("publication_staging must be a non-prerelease draft")
    immutable_releases = staging["immutable_releases"]
    if (
        not isinstance(immutable_releases, Mapping)
        or set(immutable_releases) != _IMMUTABLE_RELEASES_KEYS
        or immutable_releases["enabled"] is not True
        or not isinstance(immutable_releases["enforced_by_owner"], bool)
    ):
        raise ProductionEvidenceError("immutable GitHub releases response is invalid")
    immutable_releases_sha256 = sha256_digest(
        IMMUTABLE_RELEASES_DIGEST_DOMAIN
        + canonical_json_bytes(dict(immutable_releases))
    )
    if staging["immutable_releases_sha256"] != immutable_releases_sha256:
        raise ProductionEvidenceError(
            "publication_staging immutable_releases_sha256 is invalid"
        )
    if not isinstance(staging["tag"], str) or not 1 <= len(staging["tag"]) <= 120:
        raise ProductionEvidenceError("publication_staging tag is invalid")
    tag_ref_state = staging["tag_ref_state"]
    if (
        not isinstance(tag_ref_state, Mapping)
        or set(tag_ref_state) != _TAG_REF_STATE_KEYS
        or tag_ref_state["ref"] != f"refs/tags/{staging['tag']}"
        or tag_ref_state["exists"] is not False
    ):
        raise ProductionEvidenceError("publication_staging tag_ref_state is invalid")
    tag_ref_state_sha256 = sha256_digest(
        TAG_REF_STATE_DIGEST_DOMAIN + canonical_json_bytes(dict(tag_ref_state))
    )
    if staging["tag_ref_state_sha256"] != tag_ref_state_sha256:
        raise ProductionEvidenceError(
            "publication_staging tag_ref_state_sha256 is invalid"
        )
    if (
        not isinstance(staging["target_commitish"], str)
        or _HEX40.fullmatch(staging["target_commitish"]) is None
    ):
        raise ProductionEvidenceError("publication_staging target_commitish is invalid")
    _validate_timestamp(staging["observed_at"], "publication_staging observed_at")
    _validate_publication_assets(staging["assets"], expected_assets=expected_assets)
    tag_rulesets_sha256 = _validate_tag_rulesets(
        staging["tag_rulesets"],
        repository=staging["repository"],
        repository_id=staging["repository_id"],
        tag=staging["tag"],
    )
    if staging["tag_rulesets_sha256"] != tag_rulesets_sha256:
        raise ProductionEvidenceError("publication_staging tag_rulesets_sha256 is invalid")
    return sha256_digest(PUBLICATION_STAGING_DIGEST_DOMAIN + canonical_json_bytes(staging))


def _validate_publication_assets(
    value: Any, *, expected_assets: Sequence[Mapping[str, Any]]
) -> None:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence) or not value:
        raise ProductionEvidenceError("publication_staging assets must be a non-empty array")
    normalized: list[dict[str, Any]] = []
    names: set[str] = set()
    asset_ids: set[str] = set()
    for index, raw_asset in enumerate(value):
        if not isinstance(raw_asset, Mapping) or set(raw_asset) != _ASSET_KEYS:
            raise ProductionEvidenceError(f"publication asset {index} keys are invalid")
        asset = dict(raw_asset)
        _require_decimal_id(asset["asset_id"], f"publication asset {index} asset_id")
        _require_decimal_id(asset["uploader_id"], f"publication asset {index} uploader_id")
        if (
            asset["uploader_id"] != "321543906"
            or asset["uploader_login"] != "openadapt-release[bot]"
        ):
            raise ProductionEvidenceError(f"publication asset {index} uploader is invalid")
        if not _valid_artifact_name(asset["name"]):
            raise ProductionEvidenceError(f"publication asset {index} name is invalid")
        _validate_release_asset_fields(asset, f"publication asset {index}")
        _require_digest(asset["sha256"], f"publication asset {index} sha256")
        _require_positive_int(asset["size_bytes"], f"publication asset {index} size_bytes")
        if asset["name"] in names or asset["asset_id"] in asset_ids:
            raise ProductionEvidenceError("publication assets contain a duplicate")
        names.add(asset["name"])
        asset_ids.add(asset["asset_id"])
        normalized.append(asset)
    if normalized != sorted(normalized, key=lambda item: (item["name"], item["asset_id"])):
        raise ProductionEvidenceError("publication assets are not canonically ordered")

    expected: list[dict[str, Any]] = []
    for index, raw_asset in enumerate(expected_assets):
        if not isinstance(raw_asset, Mapping) or set(raw_asset) != _EXPECTED_ASSET_KEYS:
            raise ProductionEvidenceError(f"expected publication asset {index} keys are invalid")
        asset = dict(raw_asset)
        if not _valid_artifact_name(asset["name"]):
            raise ProductionEvidenceError(f"expected publication asset {index} name is invalid")
        _validate_release_asset_fields(asset, f"expected publication asset {index}")
        _require_digest(asset["sha256"], f"expected publication asset {index} sha256")
        _require_positive_int(asset["size_bytes"], f"expected publication asset {index} size_bytes")
        expected.append(asset)
    actual_projection = [
        {
            field: asset[field]
            for field in (
                "name",
                "kind",
                "sha256",
                "size_bytes",
                "media_type",
                "publish_destinations",
            )
        }
        for asset in normalized
    ]
    if actual_projection != sorted(expected, key=lambda item: item["name"]):
        raise ProductionEvidenceError("publication assets differ from the release candidate")


def _validate_release_asset_fields(value: Mapping[str, Any], context: str) -> None:
    if not isinstance(value["kind"], str) or _ARTIFACT_KIND.fullmatch(value["kind"]) is None:
        raise ProductionEvidenceError(f"{context} kind is invalid")
    if (
        not isinstance(value["media_type"], str)
        or len(value["media_type"]) > 200
        or _MEDIA_TYPE.fullmatch(value["media_type"]) is None
    ):
        raise ProductionEvidenceError(f"{context} media_type is invalid")
    destinations = value["publish_destinations"]
    if (
        not isinstance(destinations, list)
        or not destinations
        or destinations != sorted(set(destinations))
        or any(
            destination not in {"github-release", "pypi", "deployment"}
            for destination in destinations
        )
    ):
        raise ProductionEvidenceError(f"{context} publish_destinations are invalid")


def _valid_artifact_name(value: Any) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= 255
        and "/" not in value
        and "\\" not in value
    )


def _validate_tag_rulesets(value: Any, *, repository: str, repository_id: str, tag: str) -> str:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise ProductionEvidenceError("publication tag_rulesets must be an array")
    rulesets = [dict(item) if isinstance(item, Mapping) else {} for item in value]
    if [item.get("role") for item in rulesets] != ["creation_authority", "immutability"]:
        raise ProductionEvidenceError("publication tag_rulesets roles or order are invalid")
    for index, ruleset in enumerate(rulesets):
        if set(ruleset) != _TAG_RULESET_KEYS:
            raise ProductionEvidenceError(f"publication tag ruleset {index} keys are invalid")
        if ruleset["schema_version"] != TAG_RULESET_SCHEMA:
            raise ProductionEvidenceError(f"publication tag ruleset {index} schema is invalid")
        if ruleset["repository"] != repository or ruleset["repository_id"] != repository_id:
            raise ProductionEvidenceError(f"publication tag ruleset {index} repository differs")
        _require_decimal_id(ruleset["ruleset_id"], f"tag ruleset {index} ruleset_id")
        if not isinstance(ruleset["name"], str) or not ruleset["name"]:
            raise ProductionEvidenceError(f"publication tag ruleset {index} name is invalid")
        if ruleset["target"] != "tag" or ruleset["enforcement"] != "active":
            raise ProductionEvidenceError(f"publication tag ruleset {index} is not active")
        _validate_tag_conditions(ruleset["conditions"], tag=tag, index=index)

        bypass = ruleset["bypass_actors"]
        if not isinstance(bypass, list):
            raise ProductionEvidenceError(f"publication tag ruleset {index} bypass is invalid")
        expected_bypass = (
            [
                {
                    "actor_id": "4730708",
                    "actor_type": "Integration",
                    "bypass_mode": "always",
                }
            ]
            if ruleset["role"] == "creation_authority"
            else []
        )
        if bypass != expected_bypass or any(
            not isinstance(item, Mapping) or set(item) != _BYPASS_ACTOR_KEYS for item in bypass
        ):
            raise ProductionEvidenceError(f"publication tag ruleset {index} bypass differs")

        rules = ruleset["rules"]
        expected_rule_types = (
            ["creation"]
            if ruleset["role"] == "creation_authority"
            else ["deletion", "non_fast_forward", "update"]
        )
        if not isinstance(rules, list) or rules != [
            {"type": rule_type} for rule_type in expected_rule_types
        ]:
            raise ProductionEvidenceError(f"publication tag ruleset {index} rules differ")
        if any(not isinstance(item, Mapping) or set(item) != _RULE_KEYS for item in rules):
            raise ProductionEvidenceError(f"publication tag ruleset {index} rules are invalid")
    return sha256_digest(TAG_RULESETS_DIGEST_DOMAIN + canonical_json_bytes(rulesets))


def _validate_tag_conditions(value: Any, *, tag: str, index: int) -> None:
    if not isinstance(value, Mapping) or set(value) != _CONDITION_KEYS:
        raise ProductionEvidenceError(f"publication tag ruleset {index} conditions are invalid")
    ref_name = value["ref_name"]
    if not isinstance(ref_name, Mapping) or set(ref_name) != _REF_NAME_KEYS:
        raise ProductionEvidenceError(f"publication tag ruleset {index} ref_name is invalid")
    include = ref_name["include"]
    exclude = ref_name["exclude"]
    for label, patterns in (("include", include), ("exclude", exclude)):
        if (
            not isinstance(patterns, list)
            or any(not isinstance(pattern, str) or not pattern for pattern in patterns)
            or patterns != sorted(set(patterns))
        ):
            raise ProductionEvidenceError(
                f"publication tag ruleset {index} {label} patterns are invalid"
            )
    candidates = (tag, f"refs/tags/{tag}")
    if not include or not any(
        fnmatchcase(candidate, pattern) for pattern in include for candidate in candidates
    ):
        raise ProductionEvidenceError(f"publication tag ruleset {index} does not match the tag")
    if any(fnmatchcase(candidate, pattern) for pattern in exclude for candidate in candidates):
        raise ProductionEvidenceError(f"publication tag ruleset {index} excludes the tag")


def _require_decimal_id(value: Any, field: str) -> str:
    if not isinstance(value, str) or _DECIMAL_ID.fullmatch(value) is None:
        raise ProductionEvidenceError(f"{field} must be a positive decimal string")
    return value


def _validate_campaign_summary(value: Any) -> None:
    if not isinstance(value, Mapping) or set(value) != _CAMPAIGN_CLASSES:
        raise ProductionEvidenceError(
            "campaign_summary must contain exactly the six qualification classes"
        )
    for qualification_class, raw_counts in value.items():
        if not isinstance(raw_counts, Mapping) or set(raw_counts) != _CAMPAIGN_CLASS_SUMMARY_KEYS:
            raise ProductionEvidenceError(
                f"campaign_summary.{qualification_class} keys are invalid"
            )
        for field, count in raw_counts.items():
            if isinstance(count, bool) or not isinstance(count, int) or count < 0:
                raise ProductionEvidenceError(
                    f"campaign_summary.{qualification_class}.{field} must be non-negative"
                )
        cells = raw_counts["task_condition_cell_count"]
        minimum = raw_counts["minimum_trials_per_cell"]
        observed = raw_counts["observed_trial_count"]
        if cells < 1 or minimum < 3 or observed < cells * minimum:
            raise ProductionEvidenceError(
                f"campaign_summary.{qualification_class} lacks three trials per cell"
            )
        for field in (
            "silent_incorrect_success_count",
            "over_halt_count",
            "unsafe_effect_count",
            "blind_retry_count",
        ):
            if raw_counts[field] != 0:
                raise ProductionEvidenceError(
                    f"accepted campaign has nonzero {qualification_class}.{field}"
                )
    healthy = value["healthy"]
    idempotency = value["idempotency_replay"]
    uncertain = value["uncertain_delivery"]
    attended = value["declared_attended"]
    repair = value["governed_repair"]
    for qualification_class, counts in (
        ("healthy", healthy),
        ("idempotency_replay", idempotency),
    ):
        for field in ("model_call_count", "unplanned_intervention_count"):
            if counts[field] != 0:
                raise ProductionEvidenceError(f"{qualification_class}.{field} must be zero")
    if idempotency["replay_dispatch_count"] != 0:
        raise ProductionEvidenceError("idempotency_replay.replay_dispatch_count must be zero")
    if (
        uncertain["reconciliation_required_count"] != uncertain["observed_trial_count"]
        or uncertain["blind_retry_count"] != 0
        or uncertain["replay_dispatch_count"] != 0
    ):
        raise ProductionEvidenceError(
            "each uncertain-delivery trial must require reconciliation without redispatch"
        )
    if (
        attended["authenticated_bound_decision_count"] != attended["observed_trial_count"]
        or attended["live_target_revalidation_count"] != attended["observed_trial_count"]
    ):
        raise ProductionEvidenceError(
            "each declared-attended trial must bind a decision and target revalidation"
        )
    for field in (
        "policy_approved_repair_count",
        "approved_repair_count",
        "retained_repair_evidence_count",
        "live_target_revalidation_count",
    ):
        if repair[field] != repair["observed_trial_count"]:
            raise ProductionEvidenceError(f"each governed-repair trial must provide {field}")
    if repair["unverified_direct_action_count"] != 0:
        raise ProductionEvidenceError("governed-repair trials cannot use unverified direct action")


def _production_evidence_identity(value: Mapping[str, Any]) -> str:
    projection = {
        field: value[field]
        for field in (
            "target",
            "claim_scope",
            "release_identity",
            "release_sha256",
            "artifact_inventory_sha256",
            "publication_staging_sha256",
            "qualification_evidence_decision_receipt_reference",
            "qualification_admission_reference",
            "production_acceptance_manifest_reference",
            "campaign_summary",
            "authority_state_sha256",
            "revocation_state_sha256",
            "signer_registry_sha256",
            "issuer",
        )
    }
    return sha256_digest(PRODUCTION_EVIDENCE_IDENTITY_DOMAIN + canonical_json_bytes(projection))


def _validate_timestamp(value: Any, field: str) -> datetime:
    if not isinstance(value, str) or not _WHOLE_SECOND_UTC.fullmatch(value):
        raise ProductionEvidenceError(f"{field} must be whole-second UTC")
    return datetime.fromisoformat(value.removesuffix("Z") + "+00:00").astimezone(timezone.utc)


def _validate_json_value(value: Any, context: str) -> None:
    if value is None or isinstance(value, (str, bool, int)):
        return
    if isinstance(value, float):
        raise ProductionEvidenceError(f"{context} contains a floating-point value")
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ProductionEvidenceError(f"{context} contains a non-string key")
            _validate_json_value(item, f"{context}.{key}")
        return
    if isinstance(value, (list, tuple)):
        for index, item in enumerate(value):
            _validate_json_value(item, f"{context}[{index}]")
        return
    raise ProductionEvidenceError(f"{context} contains a non-JSON value")


def _require_digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ProductionEvidenceError(f"{field} must be sha256:<64-lowercase-hex>")
    return value


def _require_positive_int(value: Any, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ProductionEvidenceError(f"{field} must be a positive integer")
    return value


def _validate_object_path(value: Any) -> str:
    if not isinstance(value, str) or not value or len(value) > 512:
        raise ProductionEvidenceError("object_path is invalid")
    if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,511}", value) is None:
        raise ProductionEvidenceError("object_path is invalid")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or str(path) != value
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise ProductionEvidenceError("object_path is invalid")
    return value


def _parse_registered_regular_object(
    raw: Any,
    *,
    reference: Mapping[str, Any],
    expected_kind: str,
) -> dict[str, Any]:
    """Verify exact registered bytes before parsing one closed regular object."""

    if not isinstance(raw, bytes) or not raw:
        raise ProductionEvidenceError(
            f"registered {expected_kind} object must be non-empty raw bytes"
        )
    validate_object_reference(reference)
    if reference["kind"] != expected_kind:
        raise ProductionEvidenceError(
            f"registered object kind must be {expected_kind!r}"
        )
    if reference["size_bytes"] != len(raw):
        raise ProductionEvidenceError(
            f"registered {expected_kind} object size differs from its public reference"
        )
    if reference["object_sha256"] != sha256_digest(raw):
        raise ProductionEvidenceError(
            f"registered {expected_kind} object digest differs from its public reference"
        )
    if not raw.endswith(b"\n") or raw.endswith(b"\n\n"):
        raise ProductionEvidenceError(
            f"registered {expected_kind} object must end with exactly one LF"
        )

    def reject_duplicate_pairs(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
        value: dict[str, Any] = {}
        for key, item in pairs:
            if key in value:
                raise ProductionEvidenceError(
                    f"registered {expected_kind} object contains duplicate key {key!r}"
                )
            value[key] = item
        return value

    try:
        parsed = json.loads(
            raw[:-1].decode("utf-8"),
            object_pairs_hook=reject_duplicate_pairs,
            parse_float=lambda value: (_ for _ in ()).throw(
                ProductionEvidenceError(
                    f"registered {expected_kind} object contains float {value}"
                )
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProductionEvidenceError(
            f"registered {expected_kind} object must contain one UTF-8 JSON object"
        ) from exc
    if not isinstance(parsed, dict):
        raise ProductionEvidenceError(
            f"registered {expected_kind} object must contain one JSON object"
        )
    if canonical_object_bytes(parsed) != raw:
        raise ProductionEvidenceError(
            f"registered {expected_kind} object is not canonical JSON plus LF"
        )
    return parsed


def _validate_raw_json_object(value: Any, context: str) -> bytes:
    if not isinstance(value, bytes) or not value:
        raise ProductionEvidenceError(f"{context} must be non-empty raw bytes")
    try:
        decoded = json.loads(value)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProductionEvidenceError(f"{context} must contain one JSON object") from exc
    if not isinstance(decoded, dict):
        raise ProductionEvidenceError(f"{context} must contain one JSON object")
    return value
