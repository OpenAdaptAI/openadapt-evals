from __future__ import annotations

import base64
import copy
import hashlib
import json

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from openadapt_evals import production_evidence as evidence


def _digest(character: str) -> str:
    return "sha256:" + character * 64


def _object(kind: str) -> dict[str, object]:
    return {
        "schema_version": evidence.REGULAR_EVIDENCE_KINDS[kind].schema_version,
        "value": kind,
    }


def _pair(
    kind: str,
    *,
    revision: int = 4,
    object_value: dict[str, object] | None = None,
) -> evidence.EvidenceObjectPair:
    return evidence.build_evidence_object_pair(
        kind=kind,
        object_value=object_value or _object(kind),
        sigstore_bundle=(b'{ "mediaType": "application/vnd.dev.sigstore.bundle.v0.3+json" }\n'),
        registry_source_commit="a" * 40,
        registry_revision=revision,
        registry_head_sha256=_digest("b"),
    )


def _campaign_summary() -> dict[str, dict[str, int]]:
    fields = evidence._CAMPAIGN_CLASS_SUMMARY_KEYS
    summary = {
        qualification_class: {field: 0 for field in fields}
        for qualification_class in evidence._CAMPAIGN_CLASSES
    }
    for counts in summary.values():
        counts["task_condition_cell_count"] = 1
        counts["minimum_trials_per_cell"] = 3
        counts["observed_trial_count"] = 3
    summary["uncertain_delivery"]["reconciliation_required_count"] = 3
    summary["declared_attended"]["authenticated_bound_decision_count"] = 3
    summary["declared_attended"]["live_target_revalidation_count"] = 3
    for field in (
        "policy_approved_repair_count",
        "approved_repair_count",
        "retained_repair_evidence_count",
        "live_target_revalidation_count",
    ):
        summary["governed_repair"][field] = 3
    return summary


_RECEIPT_PRIVATE_KEY = Ed25519PrivateKey.from_private_bytes(b"\x11" * 32)


def _receipt_public_key() -> bytes:
    return _RECEIPT_PRIVATE_KEY.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )


def _receipt_key_id() -> str:
    return "qa-ed25519-" + hashlib.sha256(_receipt_public_key()).hexdigest()[:16]


def _signer_registry() -> dict[str, object]:
    public_key = _receipt_public_key()
    spki = bytes.fromhex("302a300506032b6570032100") + public_key
    return {
        "schema_version": evidence.SIGNER_REGISTRY_SCHEMA,
        "revision": 7,
        "generated_at": "2026-08-27T10:00:00Z",
        "expires_at": "2026-09-03T10:00:00Z",
        "signers": [
            {
                "algorithm": "ed25519",
                "key_id": _receipt_key_id(),
                "public_key": base64.urlsafe_b64encode(public_key)
                .rstrip(b"=")
                .decode("ascii"),
                "public_key_spki_der_base64": base64.b64encode(spki).decode("ascii"),
                "public_key_sha256": evidence.sha256_digest(spki),
                "statement_schema_versions": [
                    evidence.DECISION_RECEIPT_SIGNING_STATEMENT_SCHEMA
                ],
                "allowed_workflows": [
                    "https://github.com/OpenAdaptAI/openadapt-internal/"
                    ".github/workflows/issue-private-qualification-evidence-decision.yml"
                ],
                "allowed_ref_prefixes": ["refs/heads/main"],
                "status": "active",
                "revoked_at": None,
                "allowed_usages": ["qualification-evidence-decision-receipt"],
            }
        ],
    }


def _signer_registry_bytes() -> bytes:
    return evidence.canonical_object_bytes(_signer_registry())


def _signer_registry_sha256() -> str:
    return evidence.signer_registry_identity(_signer_registry())


def _sign_receipt(receipt: dict[str, object]) -> dict[str, object]:
    receipt.pop("signing_statement", None)
    receipt.pop("signature", None)
    unsigned_bytes = evidence.canonical_object_bytes(receipt)
    statement = {
        "schema_version": evidence.DECISION_RECEIPT_SIGNING_STATEMENT_SCHEMA,
        "object_schema_version": evidence.DECISION_RECEIPT_SCHEMA,
        "signature_domain": evidence.DECISION_RECEIPT_SIGNATURE_DOMAIN,
        "unsigned_object_sha256": evidence.sha256_digest(unsigned_bytes),
        "unsigned_size_bytes": len(unsigned_bytes),
        "commitment_scheme": "sha256-canonical-json-lf",
    }
    receipt["signing_statement"] = statement
    receipt["signature"] = base64.b64encode(
        _RECEIPT_PRIVATE_KEY.sign(evidence.canonical_object_bytes(statement))
    ).decode("ascii")
    return receipt


def _decision_receipt(campaign: dict[str, dict[str, int]]) -> dict[str, object]:
    receipt: dict[str, object] = {
        "schema_version": evidence.DECISION_RECEIPT_SCHEMA,
        "decision_commitment_sha256": _digest("a"),
        "decision_identity_sha256": _digest("d"),
        "decision_revision": 1,
        "evidence_manifest_sha256": _digest("b"),
        "campaign_artifact_sha256": _digest("c"),
        "organization_id_sha256": _digest("d"),
        "workflow_id_sha256": _digest("e"),
        "workflow_version_id_sha256": _digest("f"),
        "bundle_version": "7.0.0",
        "bundle_sha256": _digest("0"),
        "admitted_runtime_sha256": _digest("1"),
        "action_contract_sha256": _digest("2"),
        "application_contract_sha256": _digest("3"),
        "effect_contract_sha256": _digest("4"),
        "environment_contract_sha256": _digest("5"),
        "evidence_authority_contract_sha256": _digest("6"),
        "identity_contract_sha256": _digest("7"),
        "input_contract_sha256": _digest("8"),
        "policy_contract_sha256": _digest("9"),
        "campaign_permit_sha256": _digest("a"),
        "signer_registry_sha256": _signer_registry_sha256(),
        "revocation_state_sha256": _digest("7"),
        "entity_class": "record",
        "campaign_summary": {
            "schema_version": evidence.DECISION_CAMPAIGN_SUMMARY_SCHEMA,
            "minimum_trials_per_task_condition": 3,
            "task_count": 1,
            "classes": campaign,
        },
        "verdict": "ADMIT",
        "issued_at": "2026-08-27T11:00:00Z",
        "not_before": "2026-08-27T11:00:00Z",
        "expires_at": "2026-09-03T11:00:00Z",
        "issuer_key_id": _receipt_key_id(),
        "algorithm": "ed25519",
        "issuer": {
            "repository": "OpenAdaptAI/openadapt-internal",
            "repository_id": "1170060695",
            "repository_owner_id": "132681217",
            "workflow": ".github/workflows/issue-private-qualification-evidence-decision.yml",
            "ref": "refs/heads/main",
            "source_commit": "c" * 40,
            "environment": "private-qualification-evidence-decision",
        },
    }
    return _sign_receipt(receipt)


def _qualification_admission(
    receipt: dict[str, object],
    decision_references: tuple[dict[str, object], dict[str, object]],
) -> dict[str, object]:
    receipt_summary = receipt["campaign_summary"]
    assert isinstance(receipt_summary, dict)
    admission: dict[str, object] = {
        "schema_version": evidence.QUALIFICATION_ADMISSION_SCHEMA,
        "admission_id_sha256": _digest("0"),
        "organization_id_sha256": receipt["organization_id_sha256"],
        "workflow_id_sha256": receipt["workflow_id_sha256"],
        "workflow_version_id_sha256": receipt["workflow_version_id_sha256"],
        "bundle_version": receipt["bundle_version"],
        "bundle_sha256": receipt["bundle_sha256"],
        "admitted_runtime_sha256": receipt["admitted_runtime_sha256"],
        "application_contract_sha256": receipt["application_contract_sha256"],
        "environment_contract_sha256": receipt["environment_contract_sha256"],
        "input_contract_sha256": receipt["input_contract_sha256"],
        "action_contract_sha256": receipt["action_contract_sha256"],
        "identity_contract_sha256": receipt["identity_contract_sha256"],
        "effect_contract_sha256": receipt["effect_contract_sha256"],
        "policy_contract_sha256": receipt["policy_contract_sha256"],
        "evidence_authority_sha256": receipt[
            "evidence_authority_contract_sha256"
        ],
        "campaign_artifact_sha256": receipt["campaign_artifact_sha256"],
        "campaign_permit_sha256": receipt["campaign_permit_sha256"],
        "decision_receipt_reference": decision_references[0],
        "decision_receipt_bundle_reference": decision_references[1],
        "signer_registry_sha256": receipt["signer_registry_sha256"],
        "revocation_state_sha256": receipt["revocation_state_sha256"],
        "entity_class": receipt["entity_class"],
        "campaign_summary": receipt_summary["classes"],
        "local_identity_opening": {
            "schema_version": "openadapt.qualification-local-identity-opening/v1",
            "algorithm": "hmac-sha256",
            "required": True,
            "customer_controlled_secret_required": True,
            "exact_contract_match_required": True,
            "revalidation_before_actuation": True,
            "maximum_age_seconds": 60,
        },
        "verdict": "accepted",
        "issued_at": "2026-08-27T11:30:00Z",
        "not_before": "2026-08-27T11:30:00Z",
        "expires_at": "2026-09-03T11:30:00Z",
        "issuer": {
            "repository": "OpenAdaptAI/.github",
            "repository_id": "858454062",
            "repository_owner_id": "132681217",
            "workflow": ".github/workflows/issue-qualification-admission.yml",
            "ref": "refs/heads/main",
            "source_commit": "d" * 40,
            "environment": "qualification-admission",
        },
    }
    unsigned = dict(admission)
    unsigned.pop("admission_id_sha256")
    admission["admission_id_sha256"] = evidence.sha256_digest(
        evidence.QUALIFICATION_ADMISSION_ID_DOMAIN
        + evidence.canonical_json_bytes(unsigned)
    )
    return admission


def _publication_staging() -> tuple[dict[str, object], list[dict[str, object]]]:
    expected_assets = [
        {
            "name": "openadapt_flow-0.94.1-py3-none-any.whl",
            "kind": "wheel",
            "sha256": _digest("a"),
            "size_bytes": 200,
            "media_type": "application/zip",
            "publish_destinations": ["github-release", "pypi"],
        },
        {
            "name": "openadapt_flow-0.94.1.tar.gz",
            "kind": "sdist",
            "sha256": _digest("b"),
            "size_bytes": 100,
            "media_type": "application/gzip",
            "publish_destinations": ["github-release", "pypi"],
        },
    ]
    assets = [
        {
            **asset,
            "asset_id": str(index),
            "uploader_id": "321543906",
            "uploader_login": "openadapt-release[bot]",
        }
        for index, asset in enumerate(expected_assets, start=11)
    ]

    def ruleset(
        role: str, ruleset_id: str, rules: list[str], *, creation_bypass: bool
    ) -> dict[str, object]:
        return {
            "schema_version": evidence.TAG_RULESET_SCHEMA,
            "role": role,
            "repository": "OpenAdaptAI/openadapt-flow",
            "repository_id": "123456",
            "ruleset_id": ruleset_id,
            "name": f"release tag {role}",
            "target": "tag",
            "enforcement": "active",
            "bypass_actors": (
                [
                    {
                        "actor_id": "4730708",
                        "actor_type": "Integration",
                        "bypass_mode": "always",
                    }
                ]
                if creation_bypass
                else []
            ),
            "conditions": {"ref_name": {"include": ["refs/tags/v*"], "exclude": []}},
            "rules": [{"type": rule} for rule in rules],
        }

    tag_rulesets = [
        ruleset("creation_authority", "71", ["creation"], creation_bypass=True),
        ruleset(
            "immutability",
            "72",
            ["deletion", "non_fast_forward", "update"],
            creation_bypass=False,
        ),
    ]
    staging = {
        "schema_version": evidence.PUBLICATION_STAGING_SCHEMA,
        "repository": "OpenAdaptAI/openadapt-flow",
        "repository_id": "123456",
        "draft_release_id": "456789",
        "tag": "v0.94.1",
        "target_commitish": "c" * 40,
        "draft": True,
        "prerelease": False,
        "release_app_id": "4730708",
        "release_app_installation_id": "156835568",
        "release_app_bot_user_id": "321543906",
        "release_author_login": "openadapt-release[bot]",
        "assets": assets,
        "immutable_releases": {
            "enabled": True,
            "enforced_by_owner": False,
        },
        "immutable_releases_sha256": evidence.sha256_digest(
            evidence.IMMUTABLE_RELEASES_DIGEST_DOMAIN
            + evidence.canonical_json_bytes(
                {"enabled": True, "enforced_by_owner": False}
            )
        ),
        "tag_ref_state": {
            "ref": "refs/tags/v0.94.1",
            "exists": False,
        },
        "tag_ref_state_sha256": evidence.sha256_digest(
            evidence.TAG_REF_STATE_DIGEST_DOMAIN
            + evidence.canonical_json_bytes(
                {"ref": "refs/tags/v0.94.1", "exists": False}
            )
        ),
        "tag_rulesets": tag_rulesets,
        "tag_rulesets_sha256": evidence.sha256_digest(
            evidence.TAG_RULESETS_DIGEST_DOMAIN + evidence.canonical_json_bytes(tag_rulesets)
        ),
        "observed_at": "2026-08-27T11:30:00Z",
    }
    return staging, expected_assets


def _release_candidate(
    artifacts: list[dict[str, object]],
) -> tuple[dict[str, object], dict[str, object]]:
    release_artifacts = sorted(
        copy.deepcopy(artifacts),
        key=lambda artifact: (artifact["kind"], artifact["name"], artifact["sha256"]),
    )
    release = {
        "schema_version": evidence.RELEASE_CANDIDATE_SCHEMA,
        "kind": "package",
        "source_repository": "OpenAdaptAI/openadapt-flow",
        "source_repository_id": "123456",
        "source_commit": "c" * 40,
        "version": "0.94.1",
        "tag": "v0.94.1",
        "deployment_id": None,
        "deployment_sha256": None,
        "artifacts": release_artifacts,
    }
    inventory = {
        "schema_version": evidence.ARTIFACT_INVENTORY_SCHEMA,
        "target": "flow",
        "claim_scope": "production_flow",
        "artifacts": copy.deepcopy(release_artifacts),
    }
    return release, inventory


def _lifecycle_policy_bytes() -> bytes:
    repositories = {
        "agent": "OpenAdaptAI/openadapt-agent",
        "capture": "OpenAdaptAI/openadapt-capture",
        "cloud": "OpenAdaptAI/openadapt-cloud",
        "desktop": "OpenAdaptAI/openadapt-desktop",
        "docs": "OpenAdaptAI/openadapt-ops",
        "flow": "OpenAdaptAI/openadapt-flow",
        "openadapt": "OpenAdaptAI/OpenAdapt",
    }
    release_kinds = {
        "cloud": "deployment",
        "docs": "deployment",
    }
    package_projects = {
        "agent": "openadapt-agent",
        "capture": "openadapt-capture",
        "desktop": "openadapt-desktop",
        "flow": "openadapt-flow",
        "openadapt": "openadapt",
    }
    required_kinds = {
        "agent": ["sdist", "wheel"],
        "capture": ["sdist", "wheel"],
        "cloud": ["deployment-manifest"],
        "desktop": ["sdist", "wheel"],
        "docs": ["site-archive"],
        "flow": ["sdist", "wheel"],
        "openadapt": ["sdist", "wheel"],
    }
    targets = []
    for index, target in enumerate(sorted(repositories), start=1):
        targets.append(
            {
                "id": target,
                "display_name": target.title(),
                "source_repository": repositories[target],
                "source_repository_id": (
                    "123456" if target == "flow" else str(900000 + index)
                ),
                "release_kind": release_kinds.get(target, "package"),
                "claim_scope": f"production_{target}",
                "required_artifact_kinds": required_kinds[target],
                "package_index_project": package_projects.get(target),
            }
        )
    policy = {
        "$schema": "schemas/production-lifecycle-policy.schema.json",
        "schema_version": evidence.PRODUCTION_LIFECYCLE_POLICY_SCHEMA,
        "revision": 2,
        "maximum_release_admission_days": 30,
        "maximum_workflow_admission_days": 7,
        "object_reference_schema_version": evidence.OBJECT_REFERENCE_SCHEMA,
        "release_admission_schema_version": "openadapt.qualification-release/v1",
        "workflow_admission_schema_version": evidence.QUALIFICATION_ADMISSION_SCHEMA,
        "lifecycle_checkpoint_schema_version": (
            "openadapt.production-lifecycle-checkpoint/v1"
        ),
        "lifecycle_feed_schema_version": "openadapt.production-lifecycle-feed/v1",
        "lifecycle_feed_ref": "refs/heads/production-lifecycle-feed",
        "targets": targets,
    }
    return (json.dumps(policy, indent=2) + "\n").encode("utf-8")


def _issuer() -> dict[str, object]:
    return {
        "repository": "OpenAdaptAI/openadapt-evals",
        "repository_id": "1135998197",
        "repository_owner_id": "132681217",
        "workflow": ".github/workflows/issue-production-acceptance.yml",
        "ref": "refs/heads/main",
        "source_commit": "d" * 40,
        "environment": "production-acceptance",
    }


def _summary() -> tuple[
    dict[str, object],
    dict[str, object],
    dict[str, object],
    dict[str, object],
    list[dict[str, object]],
]:
    campaign = _campaign_summary()
    receipt = _decision_receipt(campaign)
    decision = _pair("qualification-evidence-decision-receipt", object_value=receipt)
    admission_object = _qualification_admission(receipt, decision.references)
    admission = _pair("qualification-admission", object_value=admission_object)
    staging, expected_assets = _publication_staging()
    release, inventory = _release_candidate(expected_assets)
    manifest_object = evidence.build_production_acceptance_manifest(
        target="flow",
        claim_scope="production_flow",
        acceptance_policy_sha256=_digest("1"),
        lifecycle_policy_bytes=_lifecycle_policy_bytes(),
        release_identity={
            "schema_version": "openadapt.monotonic-production-release/v1",
            "channel": "production",
            "sequence": 7,
            "previous_admission_sha256": _digest("3"),
        },
        release=release,
        artifact_inventory=inventory,
        publication_staging=staging,
        signer_registry_bytes=_signer_registry_bytes(),
        qualification_evidence_decision_receipt_bytes=decision.objects[0],
        qualification_evidence_decision_receipt_references=decision.references,
        qualification_admission_bytes=admission.objects[0],
        qualification_admission_references=admission.references,
        authority_state_sha256=_digest("6"),
        revocation_state_sha256=_digest("7"),
        signer_registry_sha256=_signer_registry_sha256(),
        issuer=_issuer(),
        issued_at="2026-08-27T11:45:00Z",
        not_before="2026-08-27T11:45:00Z",
        expires_at="2026-09-03T10:30:00Z",
    )
    manifest = _pair("production-acceptance-manifest", object_value=manifest_object)
    summary = evidence.build_production_acceptance_summary(
        target="flow",
        claim_scope="production_flow",
        acceptance_policy_sha256=_digest("1"),
        lifecycle_policy_sha256=manifest_object["lifecycle_policy_sha256"],
        release_identity={
            "schema_version": "openadapt.monotonic-production-release/v1",
            "channel": "production",
            "sequence": 7,
            "previous_admission_sha256": _digest("3"),
        },
        release_sha256=manifest_object["release_sha256"],
        artifact_inventory_sha256=manifest_object["artifact_inventory_sha256"],
        publication_staging=staging,
        signer_registry_bytes=_signer_registry_bytes(),
        qualification_evidence_decision_receipt_bytes=decision.objects[0],
        qualification_evidence_decision_receipt_references=decision.references,
        qualification_admission_bytes=admission.objects[0],
        qualification_admission_references=admission.references,
        production_acceptance_manifest_bytes=manifest.objects[0],
        production_acceptance_manifest_references=manifest.references,
        authority_state_sha256=_digest("6"),
        revocation_state_sha256=_digest("7"),
        signer_registry_sha256=_signer_registry_sha256(),
        issuer=_issuer(),
        issued_at="2026-08-27T12:00:00Z",
        not_before="2026-08-27T12:00:00Z",
        expires_at="2026-09-03T10:30:00Z",
    )
    return summary, receipt, admission_object, manifest_object, expected_assets


def test_approved_kind_map_is_exact() -> None:
    assert set(evidence.REGULAR_EVIDENCE_KINDS) == {
        "qualification-release",
        "production-acceptance-manifest",
        "production-acceptance-summary",
        "qualification-authority-state-receipt",
        "qualification-revocation-state-receipt",
        "production-current-default",
        "production-deployment-observation",
        "production-lifecycle-checkpoint",
        "production-cloud-deploy-authorization",
        "production-cloud-deployment-result",
        "qualification-campaign-permit-policy",
        "qualification-campaign-permit-request",
        "qualification-campaign-permit",
        "qualification-campaign-permit-receipt",
        "qualification-evidence-decision-receipt",
        "qualification-admission",
    }
    assert evidence.REGULAR_EVIDENCE_KINDS["production-acceptance-summary"] == (
        evidence.EvidenceKind(
            "openadapt.production-lifecycle-evidence-summary/v2",
            "application/vnd.openadapt.production-lifecycle-evidence-summary+json;version=2",
        )
    )
    assert evidence.REGULAR_EVIDENCE_KINDS["qualification-admission"] == (
        evidence.EvidenceKind(
            "openadapt.qualification-admission/v3",
            "application/vnd.openadapt.qualification-admission+json;version=3",
        )
    )


def test_seven_target_release_claim_scopes_are_exact() -> None:
    assert evidence._PRODUCT_CLAIM_SCOPE_BY_TARGET == {
        "agent": "production_agent",
        "capture": "production_capture",
        "cloud": "production_cloud",
        "desktop": "production_desktop",
        "docs": "production_docs",
        "flow": "production_flow",
        "openadapt": "production_openadapt",
    }


def test_builds_exact_content_addressed_v2_reference_pair() -> None:
    pair = _pair("production-acceptance-summary")
    regular, bundle = pair.references

    assert pair.objects[1].startswith(b'{ "mediaType"')
    assert pair.objects[0].endswith(b"\n")
    assert not pair.objects[0].endswith(b"\n\n")
    assert set(regular) == evidence.REFERENCE_KEYS
    assert "url" not in regular
    assert regular["schema_version"] == evidence.OBJECT_REFERENCE_SCHEMA
    assert regular["repository"] == "OpenAdaptAI/.github"
    assert regular["repository_id"] == "858454062"
    assert regular["repository_owner_id"] == "132681217"
    assert regular["object_schema_version"] == (
        "openadapt.production-lifecycle-evidence-summary/v2"
    )
    assert regular["object_media_type"] == (
        "application/vnd.openadapt.production-lifecycle-evidence-summary+json;version=2"
    )
    assert regular["subject_sha256"] is None
    assert regular["size_bytes"] == len(pair.objects[0])
    assert regular["object_sha256"] == evidence.sha256_digest(pair.objects[0])
    regular_hex = str(regular["object_sha256"]).removeprefix("sha256:")
    assert regular["object_path"] == (
        f"production-evidence/objects/sha256/{regular_hex[:2]}/"
        f"{regular_hex}.production-acceptance-summary.json"
    )
    assert bundle["kind"] == "production-acceptance-summary-sigstore-bundle"
    assert bundle["object_schema_version"] == evidence.SIGSTORE_BUNDLE_MEDIA_TYPE
    assert bundle["object_media_type"] == evidence.SIGSTORE_BUNDLE_MEDIA_TYPE
    assert bundle["subject_sha256"] == regular["object_sha256"]
    evidence.validate_reference_pair(
        pair.references, expected_regular_kind="production-acceptance-summary"
    )


def test_registered_regular_object_requires_exact_canonical_bytes_plus_lf() -> None:
    pair = _pair("qualification-admission")
    raw = pair.objects[0]
    reference = pair.references[0]
    assert evidence._parse_registered_regular_object(
        raw,
        reference=reference,
        expected_kind="qualification-admission",
    ) == json.loads(raw)

    def rebind(changed_raw: bytes) -> dict[str, object]:
        changed = copy.deepcopy(reference)
        changed["size_bytes"] = len(changed_raw)
        changed["object_sha256"] = evidence.sha256_digest(changed_raw)
        digest_hex = changed["object_sha256"].removeprefix("sha256:")
        changed["object_path"] = (
            f"production-evidence/objects/sha256/{digest_hex[:2]}/{digest_hex}."
            "qualification-admission.json"
        )
        changed["registry_entry_sha256"] = evidence._registry_entry_sha256(changed)
        return changed

    without_lf = raw[:-1]
    with pytest.raises(evidence.ProductionEvidenceError, match="exactly one LF"):
        evidence._parse_registered_regular_object(
            without_lf,
            reference=rebind(without_lf),
            expected_kind="qualification-admission",
        )

    extra_lf = raw + b"\n"
    with pytest.raises(evidence.ProductionEvidenceError, match="exactly one LF"):
        evidence._parse_registered_regular_object(
            extra_lf,
            reference=rebind(extra_lf),
            expected_kind="qualification-admission",
        )

    noncanonical = b'{ "schema_version": "openadapt.qualification-admission/v3" }\n'
    with pytest.raises(evidence.ProductionEvidenceError, match="not canonical"):
        evidence._parse_registered_regular_object(
            noncanonical,
            reference=rebind(noncanonical),
            expected_kind="qualification-admission",
        )


def test_reference_digests_use_frozen_domains_and_projections() -> None:
    pair = _pair("qualification-admission")
    regular, bundle = pair.references
    regular_object = json.loads(pair.objects[0])
    expected_regular_identity = evidence.sha256_digest(
        evidence.REGULAR_SEMANTIC_IDENTITY_DOMAIN
        + evidence.canonical_json_bytes(
            {
                "kind": "qualification-admission",
                "object_schema_version": "openadapt.qualification-admission/v3",
                "object": regular_object,
            }
        )
    )
    assert regular["semantic_identity_sha256"] == expected_regular_identity
    expected_bundle_identity = evidence.sha256_digest(
        evidence.BUNDLE_SEMANTIC_IDENTITY_DOMAIN
        + evidence.canonical_json_bytes(
            {
                "kind": "qualification-admission-sigstore-bundle",
                "object_sha256": bundle["object_sha256"],
                "subject_sha256": regular["object_sha256"],
            }
        )
    )
    assert bundle["semantic_identity_sha256"] == expected_bundle_identity
    for reference in pair.references:
        entry = {field: reference[field] for field in evidence.REGISTRY_ENTRY_KEYS}
        assert reference["registry_entry_sha256"] == evidence.sha256_digest(
            evidence.REGISTRY_ENTRY_DIGEST_DOMAIN + evidence.canonical_json_bytes(entry)
        )


def test_rejects_bundle_before_regular_or_wrong_subject() -> None:
    pair = _pair("qualification-campaign-permit")
    with pytest.raises(evidence.ProductionEvidenceError):
        evidence.validate_reference_pair(tuple(reversed(pair.references)))

    regular, bundle = copy.deepcopy(pair.references)
    bundle["subject_sha256"] = _digest("f")
    bundle["registry_entry_sha256"] = evidence._registry_entry_sha256(bundle)
    with pytest.raises(evidence.ProductionEvidenceError, match="subject"):
        evidence.validate_reference_pair((regular, bundle))


def test_signer_registry_pointer_has_only_frozen_fields() -> None:
    registry = {
        "schema_version": "openadapt.qualification-signer-registry/v2",
        "revision": 9,
    }
    pointer = evidence.build_signer_registry_pointer(
        object_path="production-evidence/authority/signer-registry.json",
        object_sha256=_digest("a"),
        registry_identity_sha256=evidence.signer_registry_identity(registry),
        registry_revision=9,
    )
    assert pointer == {
        "schema_version": "openadapt.qualification-signer-registry-pointer/v1",
        "object_path": "production-evidence/authority/signer-registry.json",
        "object_sha256": _digest("a"),
        "registry_identity_sha256": evidence.signer_registry_identity(registry),
        "registry_revision": 9,
    }


def test_builds_remote_safe_summary_from_three_prior_reference_pairs() -> None:
    summary, receipt, admission, manifest, _ = _summary()
    assert set(summary) == evidence._SUMMARY_KEYS
    assert summary["schema_version"] == ("openadapt.production-lifecycle-evidence-summary/v2")
    assert summary["verdict"] == "accepted"
    assert set(summary["campaign_summary"]) == evidence._CAMPAIGN_CLASSES
    rendered = json.dumps(summary["campaign_summary"], sort_keys=True)
    for private_field in (
        "task_name",
        "condition_name",
        "application",
        "environment",
        "live_identity",
    ):
        assert private_field not in rendered
    evidence.validate_production_acceptance_summary(
        summary,
        qualification_evidence_decision_receipt_bytes=evidence.canonical_object_bytes(receipt),
        qualification_admission_bytes=evidence.canonical_object_bytes(admission),
        production_acceptance_manifest_bytes=evidence.canonical_object_bytes(manifest),
        signer_registry_bytes=_signer_registry_bytes(),
    )

    assert set(manifest) == evidence._MANIFEST_KEYS
    assert manifest["schema_version"] == evidence.PRODUCTION_ACCEPTANCE_MANIFEST_SCHEMA
    assert "source_evidence" not in manifest
    assert "retention" not in manifest


def test_manifest_uses_the_frozen_release_and_inventory_digest_domains() -> None:
    summary, _, _, manifest, _ = _summary()
    assert manifest["release_sha256"] == evidence.sha256_digest(
        evidence.RELEASE_CANDIDATE_DIGEST_DOMAIN
        + evidence.canonical_json_bytes(
            {
                "target": manifest["target"],
                "claim_scope": manifest["claim_scope"],
                "release": manifest["release"],
            }
        )
    )
    assert manifest["artifact_inventory_sha256"] == evidence.sha256_digest(
        evidence.ARTIFACT_INVENTORY_DIGEST_DOMAIN
        + evidence.canonical_json_bytes(
            {
                "target": manifest["target"],
                "claim_scope": manifest["claim_scope"],
                "artifacts": manifest["artifact_inventory"]["artifacts"],
            }
        )
    )
    assert manifest["release"]["artifacts"] == manifest["artifact_inventory"][
        "artifacts"
    ]
    assert summary["release_sha256"] == manifest["release_sha256"]
    assert summary["artifact_inventory_sha256"] == manifest[
        "artifact_inventory_sha256"
    ]
    assert manifest["lifecycle_policy_sha256"] == evidence.sha256_digest(
        _lifecycle_policy_bytes()
    )


def test_lifecycle_policy_bytes_bind_the_selected_release_candidate() -> None:
    _, artifacts = _publication_staging()
    release, _ = _release_candidate(artifacts)
    digest = evidence._validate_production_lifecycle_policy(
        _lifecycle_policy_bytes(),
        target="flow",
        claim_scope="production_flow",
        release=release,
        artifacts=release["artifacts"],
    )
    assert digest == evidence.sha256_digest(_lifecycle_policy_bytes())

    wrong_repository = copy.deepcopy(release)
    wrong_repository["source_repository"] = "OpenAdaptAI/openadapt-evals"
    with pytest.raises(evidence.ProductionEvidenceError, match="source_repository"):
        evidence._validate_production_lifecycle_policy(
            _lifecycle_policy_bytes(),
            target="flow",
            claim_scope="production_flow",
            release=wrong_repository,
            artifacts=wrong_repository["artifacts"],
        )


def test_summary_binds_durable_release_app_staging_and_two_tag_rulesets() -> None:
    summary, receipt, admission, manifest, expected_assets = _summary()
    staging = summary["publication_staging"]
    assert staging["draft"] is True
    assert staging["prerelease"] is False
    assert staging["release_app_id"] == "4730708"
    assert staging["release_app_installation_id"] == "156835568"
    assert staging["release_app_bot_user_id"] == "321543906"
    assert [ruleset["role"] for ruleset in staging["tag_rulesets"]] == [
        "creation_authority",
        "immutability",
    ]
    assert summary["publication_staging_sha256"] == evidence.sha256_digest(
        evidence.PUBLICATION_STAGING_DIGEST_DOMAIN + evidence.canonical_json_bytes(staging)
    )

    owner_enforced = copy.deepcopy(staging)
    owner_enforced["immutable_releases"]["enforced_by_owner"] = True
    owner_enforced["immutable_releases_sha256"] = evidence.sha256_digest(
        evidence.IMMUTABLE_RELEASES_DIGEST_DOMAIN
        + evidence.canonical_json_bytes(owner_enforced["immutable_releases"])
    )
    assert evidence._validate_publication_staging(
        owner_enforced, expected_assets=expected_assets
    ) == evidence.sha256_digest(
        evidence.PUBLICATION_STAGING_DIGEST_DOMAIN
        + evidence.canonical_json_bytes(owner_enforced)
    )

    unknown_setting = copy.deepcopy(staging)
    unknown_setting["immutable_releases"]["source"] = "owner"
    with pytest.raises(evidence.ProductionEvidenceError, match="immutable"):
        evidence._validate_publication_staging(
            unknown_setting, expected_assets=expected_assets
        )

    existing_tag = copy.deepcopy(staging)
    existing_tag["tag_ref_state"]["exists"] = True
    existing_tag["tag_ref_state_sha256"] = evidence.sha256_digest(
        evidence.TAG_REF_STATE_DIGEST_DOMAIN
        + evidence.canonical_json_bytes(existing_tag["tag_ref_state"])
    )
    with pytest.raises(evidence.ProductionEvidenceError, match="tag_ref_state"):
        evidence._validate_publication_staging(
            existing_tag, expected_assets=expected_assets
        )

    mutated = copy.deepcopy(summary)
    mutated["publication_staging"]["immutable_releases"]["enabled"] = False
    with pytest.raises(evidence.ProductionEvidenceError, match="immutable"):
        evidence.validate_production_acceptance_summary(
            mutated,
            qualification_evidence_decision_receipt_bytes=evidence.canonical_object_bytes(receipt),
            qualification_admission_bytes=evidence.canonical_object_bytes(admission),
            production_acceptance_manifest_bytes=evidence.canonical_object_bytes(manifest),
            signer_registry_bytes=_signer_registry_bytes(),
        )


def test_summary_rejects_draft_asset_or_tag_authority_drift() -> None:
    summary, receipt, admission, manifest, _ = _summary()
    changed_manifest = copy.deepcopy(manifest)
    changed_manifest["artifact_inventory"]["artifacts"][0]["size_bytes"] += 1
    with pytest.raises(evidence.ProductionEvidenceError, match="release candidate"):
        evidence.validate_production_acceptance_manifest(
            changed_manifest,
            qualification_evidence_decision_receipt_bytes=evidence.canonical_object_bytes(receipt),
            qualification_admission_bytes=evidence.canonical_object_bytes(admission),
            signer_registry_bytes=_signer_registry_bytes(),
        )

    changed_rules = copy.deepcopy(summary)
    changed_rules["publication_staging"]["tag_rulesets"][1]["bypass_actors"] = [
        {
            "actor_id": "4730708",
            "actor_type": "Integration",
            "bypass_mode": "always",
        }
    ]
    with pytest.raises(evidence.ProductionEvidenceError, match="bypass"):
        evidence.validate_production_acceptance_summary(
            changed_rules,
            qualification_evidence_decision_receipt_bytes=evidence.canonical_object_bytes(receipt),
            qualification_admission_bytes=evidence.canonical_object_bytes(admission),
            production_acceptance_manifest_bytes=evidence.canonical_object_bytes(manifest),
            signer_registry_bytes=_signer_registry_bytes(),
        )


def test_summary_extracts_only_the_remote_safe_receipt_classes() -> None:
    summary, receipt, admission, manifest, _ = _summary()
    changed_receipt = copy.deepcopy(receipt)
    changed_receipt["entity_class"] = "custom customer noun"
    with pytest.raises(evidence.ProductionEvidenceError, match="remote-safe"):
        evidence._validate_decision_receipt(
            changed_receipt,
            reference=summary["qualification_evidence_decision_receipt_reference"],
            expected_signer_registry_sha256=summary["signer_registry_sha256"],
            expected_revocation_state_sha256=summary["revocation_state_sha256"],
            signer_registry_bytes=_signer_registry_bytes(),
        )
    with pytest.raises(evidence.ProductionEvidenceError, match="public reference"):
        evidence.validate_production_acceptance_summary(
            summary,
            qualification_evidence_decision_receipt_bytes=evidence.canonical_object_bytes(changed_receipt),
            qualification_admission_bytes=evidence.canonical_object_bytes(admission),
            production_acceptance_manifest_bytes=evidence.canonical_object_bytes(manifest),
            signer_registry_bytes=_signer_registry_bytes(),
        )


def test_summary_validates_the_public_admission_and_shared_commitments() -> None:
    summary, receipt, admission, manifest, _ = _summary()
    assert admission["schema_version"] == evidence.QUALIFICATION_ADMISSION_SCHEMA
    assert admission["decision_receipt_reference"] == (
        summary["qualification_evidence_decision_receipt_reference"]
    )
    assert admission["campaign_summary"] == summary["campaign_summary"]

    changed_admission = copy.deepcopy(admission)
    changed_admission["admitted_runtime_sha256"] = _digest("f")
    with pytest.raises(evidence.ProductionEvidenceError, match="admitted_runtime"):
        evidence._validate_qualification_admission(
            changed_admission,
            reference=summary["qualification_admission_reference"],
            decision_receipt=receipt,
            decision_references=(
                summary["qualification_evidence_decision_receipt_reference"],
                summary["qualification_evidence_decision_receipt_bundle_reference"],
            ),
        )
    with pytest.raises(evidence.ProductionEvidenceError, match="public reference"):
        evidence.validate_production_acceptance_summary(
            summary,
            qualification_evidence_decision_receipt_bytes=evidence.canonical_object_bytes(receipt),
            qualification_admission_bytes=evidence.canonical_object_bytes(changed_admission),
            production_acceptance_manifest_bytes=evidence.canonical_object_bytes(manifest),
            signer_registry_bytes=_signer_registry_bytes(),
        )


def test_summary_rejects_an_admission_valid_for_more_than_seven_days() -> None:
    summary, receipt, admission, manifest, _ = _summary()
    changed_admission = copy.deepcopy(admission)
    changed_admission["expires_at"] = "2026-09-04T11:30:00Z"
    unsigned = dict(changed_admission)
    unsigned.pop("admission_id_sha256")
    changed_admission["admission_id_sha256"] = evidence.sha256_digest(
        evidence.QUALIFICATION_ADMISSION_ID_DOMAIN
        + evidence.canonical_json_bytes(unsigned)
    )
    with pytest.raises(evidence.ProductionEvidenceError, match="seven days"):
        evidence._validate_qualification_admission(
            changed_admission,
            reference=summary["qualification_admission_reference"],
            decision_receipt=receipt,
            decision_references=(
                summary["qualification_evidence_decision_receipt_reference"],
                summary["qualification_evidence_decision_receipt_bundle_reference"],
            ),
        )
    with pytest.raises(evidence.ProductionEvidenceError, match="public reference"):
        evidence.validate_production_acceptance_summary(
            summary,
            qualification_evidence_decision_receipt_bytes=evidence.canonical_object_bytes(receipt),
            qualification_admission_bytes=evidence.canonical_object_bytes(changed_admission),
            production_acceptance_manifest_bytes=evidence.canonical_object_bytes(manifest),
            signer_registry_bytes=_signer_registry_bytes(),
        )


def test_summary_identity_uses_the_exact_frozen_projection() -> None:
    summary, _, _, _, _ = _summary()
    projection = {
        field: summary[field]
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
    assert summary["evidence_identity_sha256"] == (
        "sha256:"
        + hashlib.sha256(
            evidence.PRODUCTION_EVIDENCE_IDENTITY_DOMAIN + evidence.canonical_json_bytes(projection)
        ).hexdigest()
    )


def test_summary_rejects_private_counts_or_receipt_drift() -> None:
    summary, receipt, admission, manifest, _ = _summary()
    mutated = copy.deepcopy(summary)
    mutated["campaign_summary"]["healthy"]["task_name"] = 1
    with pytest.raises(evidence.ProductionEvidenceError, match="keys"):
        evidence.validate_production_acceptance_summary(
            mutated,
            qualification_evidence_decision_receipt_bytes=evidence.canonical_object_bytes(receipt),
            qualification_admission_bytes=evidence.canonical_object_bytes(admission),
            production_acceptance_manifest_bytes=evidence.canonical_object_bytes(manifest),
            signer_registry_bytes=_signer_registry_bytes(),
        )

    different_receipt = copy.deepcopy(receipt)
    different_receipt["campaign_summary"]["classes"]["healthy"]["observed_trial_count"] = 4
    with pytest.raises(evidence.ProductionEvidenceError, match="public reference"):
        evidence.validate_production_acceptance_summary(
            summary,
            qualification_evidence_decision_receipt_bytes=evidence.canonical_object_bytes(different_receipt),
            qualification_admission_bytes=evidence.canonical_object_bytes(admission),
            production_acceptance_manifest_bytes=evidence.canonical_object_bytes(manifest),
            signer_registry_bytes=_signer_registry_bytes(),
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("decision_identity_sha256", "sha256:" + "A" * 64, "decision_identity_sha256"),
        ("decision_revision", 0, "decision_revision"),
    ],
)
def test_decision_receipt_requires_an_opaque_series_identity_and_positive_revision(
    field: str,
    value: object,
    message: str,
) -> None:
    receipt = _decision_receipt(_campaign_summary())
    receipt[field] = value
    pair = _pair("qualification-evidence-decision-receipt", object_value=receipt)
    with pytest.raises(evidence.ProductionEvidenceError, match=message):
        evidence._validate_decision_receipt(
            receipt,
            reference=pair.references[0],
            expected_signer_registry_sha256=_signer_registry_sha256(),
            expected_revocation_state_sha256=_digest("7"),
            signer_registry_bytes=_signer_registry_bytes(),
        )


@pytest.mark.parametrize(
    "qualification_class,field,value",
    [
        ("healthy", "silent_incorrect_success_count", 1),
        ("safe_halt", "over_halt_count", 1),
        ("uncertain_delivery", "replay_dispatch_count", 1),
        ("uncertain_delivery", "reconciliation_required_count", 2),
        ("declared_attended", "authenticated_bound_decision_count", 2),
        ("governed_repair", "unverified_direct_action_count", 1),
    ],
)
def test_summary_rejects_nonqualifying_class_counts(
    qualification_class: str, field: str, value: int
) -> None:
    summary, receipt, admission, manifest, _ = _summary()
    summary["campaign_summary"][qualification_class][field] = value
    with pytest.raises(evidence.ProductionEvidenceError):
        evidence.validate_production_acceptance_summary(
            summary,
            qualification_evidence_decision_receipt_bytes=evidence.canonical_object_bytes(receipt),
            qualification_admission_bytes=evidence.canonical_object_bytes(admission),
            production_acceptance_manifest_bytes=evidence.canonical_object_bytes(manifest),
            signer_registry_bytes=_signer_registry_bytes(),
        )
