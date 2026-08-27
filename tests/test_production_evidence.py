from __future__ import annotations

import base64
import copy
import hashlib
import json

import pytest

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


def _decision_receipt(campaign: dict[str, dict[str, int]]) -> dict[str, object]:
    receipt: dict[str, object] = {
        "schema_version": evidence.DECISION_RECEIPT_SCHEMA,
        "decision_commitment_sha256": _digest("a"),
        "evidence_manifest_sha256": _digest("b"),
        "campaign_artifact_sha256": _digest("c"),
        "organization_id_sha256": _digest("d"),
        "workflow_id_sha256": _digest("e"),
        "workflow_version_id_sha256": _digest("f"),
        "bundle_version": "7",
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
        "signer_registry_sha256": _digest("8"),
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
        "expires_at": "2026-09-10T12:00:00Z",
        "issuer_key_id": "qualification-evidence-key-1",
        "algorithm": "ed25519",
        "signature": base64.b64encode(b"s" * 64).decode("ascii"),
    }
    return receipt


def _publication_staging() -> tuple[dict[str, object], list[dict[str, object]]]:
    expected_assets = [
        {
            "name": "openadapt_evals-0.94.1-py3-none-any.whl",
            "sha256": _digest("a"),
            "size_bytes": 200,
        },
        {
            "name": "openadapt_evals-0.94.1.tar.gz",
            "sha256": _digest("b"),
            "size_bytes": 100,
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
            "repository": "OpenAdaptAI/openadapt-evals",
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
        "repository": "OpenAdaptAI/openadapt-evals",
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
        "immutable_releases_enabled": True,
        "tag_rulesets": tag_rulesets,
        "tag_rulesets_sha256": evidence.sha256_digest(
            evidence.TAG_RULESETS_DIGEST_DOMAIN + evidence.canonical_json_bytes(tag_rulesets)
        ),
        "observed_at": "2026-08-27T11:30:00Z",
    }
    return staging, expected_assets


def _summary() -> tuple[dict[str, object], dict[str, object], list[dict[str, object]]]:
    campaign = _campaign_summary()
    receipt = _decision_receipt(campaign)
    decision = _pair("qualification-evidence-decision-receipt", object_value=receipt)
    admission = _pair("qualification-admission")
    manifest = _pair("production-acceptance-manifest")
    staging, expected_assets = _publication_staging()
    summary = evidence.build_production_acceptance_summary(
        target="flow",
        claim_scope="qualified_workflow_runtime_release",
        acceptance_policy_sha256=_digest("1"),
        lifecycle_policy_sha256=_digest("2"),
        release_identity={
            "schema_version": "openadapt.monotonic-production-release/v1",
            "channel": "production",
            "sequence": 7,
            "previous_admission_sha256": _digest("3"),
        },
        release_sha256=_digest("4"),
        artifact_inventory_sha256=_digest("5"),
        publication_staging=staging,
        expected_publication_assets=expected_assets,
        qualification_evidence_decision_receipt=receipt,
        qualification_evidence_decision_receipt_references=decision.references,
        qualification_admission_references=admission.references,
        production_acceptance_manifest_references=manifest.references,
        authority_state_sha256=_digest("6"),
        revocation_state_sha256=_digest("7"),
        signer_registry_sha256=_digest("8"),
        issued_at="2026-08-27T12:00:00Z",
        not_before="2026-08-27T12:00:00Z",
        expires_at="2026-09-03T12:00:00Z",
    )
    return summary, receipt, expected_assets


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


def test_builds_exact_content_addressed_v2_reference_pair() -> None:
    pair = _pair("production-acceptance-summary")
    regular, bundle = pair.references

    assert pair.objects[1].startswith(b'{ "mediaType"')
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
    summary, receipt, expected_assets = _summary()
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
        qualification_evidence_decision_receipt=receipt,
        expected_publication_assets=expected_assets,
    )


def test_summary_binds_durable_release_app_staging_and_two_tag_rulesets() -> None:
    summary, receipt, expected_assets = _summary()
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

    mutated = copy.deepcopy(summary)
    mutated["publication_staging"]["immutable_releases_enabled"] = False
    with pytest.raises(evidence.ProductionEvidenceError, match="immutable"):
        evidence.validate_production_acceptance_summary(
            mutated,
            qualification_evidence_decision_receipt=receipt,
            expected_publication_assets=expected_assets,
        )


def test_summary_rejects_draft_asset_or_tag_authority_drift() -> None:
    summary, receipt, expected_assets = _summary()
    changed_assets = copy.deepcopy(expected_assets)
    changed_assets[0]["size_bytes"] += 1
    with pytest.raises(evidence.ProductionEvidenceError, match="release candidate"):
        evidence.validate_production_acceptance_summary(
            summary,
            qualification_evidence_decision_receipt=receipt,
            expected_publication_assets=changed_assets,
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
            qualification_evidence_decision_receipt=receipt,
            expected_publication_assets=expected_assets,
        )


def test_summary_extracts_only_the_remote_safe_receipt_classes() -> None:
    summary, receipt, expected_assets = _summary()
    changed_receipt = copy.deepcopy(receipt)
    changed_receipt["entity_class"] = "custom customer noun"
    with pytest.raises(evidence.ProductionEvidenceError, match="remote-safe"):
        evidence.validate_production_acceptance_summary(
            summary,
            qualification_evidence_decision_receipt=changed_receipt,
            expected_publication_assets=expected_assets,
        )


def test_summary_identity_uses_the_exact_frozen_projection() -> None:
    summary, _, _ = _summary()
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
        )
    }
    assert summary["evidence_identity_sha256"] == (
        "sha256:"
        + hashlib.sha256(
            evidence.PRODUCTION_EVIDENCE_IDENTITY_DOMAIN + evidence.canonical_json_bytes(projection)
        ).hexdigest()
    )


def test_summary_rejects_private_counts_or_receipt_drift() -> None:
    summary, receipt, expected_assets = _summary()
    mutated = copy.deepcopy(summary)
    mutated["campaign_summary"]["healthy"]["task_name"] = 1
    with pytest.raises(evidence.ProductionEvidenceError, match="keys"):
        evidence.validate_production_acceptance_summary(
            mutated,
            qualification_evidence_decision_receipt=receipt,
            expected_publication_assets=expected_assets,
        )

    different_receipt = copy.deepcopy(receipt)
    different_receipt["campaign_summary"]["classes"]["healthy"]["observed_trial_count"] = 4
    with pytest.raises(evidence.ProductionEvidenceError, match="public reference"):
        evidence.validate_production_acceptance_summary(
            summary,
            qualification_evidence_decision_receipt=different_receipt,
            expected_publication_assets=expected_assets,
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
    summary, receipt, expected_assets = _summary()
    summary["campaign_summary"][qualification_class][field] = value
    with pytest.raises(evidence.ProductionEvidenceError):
        evidence.validate_production_acceptance_summary(
            summary,
            qualification_evidence_decision_receipt=receipt,
            expected_publication_assets=expected_assets,
        )
