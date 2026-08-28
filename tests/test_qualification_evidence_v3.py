from __future__ import annotations

import base64
import copy
import hashlib
import hmac
import json
from pathlib import Path
from typing import Any

import pytest

from openadapt_evals import qualification_evidence as evidence

SECRET = b"test-only-receipt-key"
CLASSES = (
    "declared_attended",
    "governed_repair",
    "healthy",
    "idempotency_replay",
    "safe_halt",
    "uncertain_delivery",
)


@pytest.fixture(autouse=True)
def _fixed_private_request_time(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        evidence,
        "_utc_now_rfc3339",
        lambda: "2026-08-27T12:01:00Z",
    )


def _digest(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode()).hexdigest()


def _sign(preimage: bytes) -> bytes:
    digest = hmac.new(SECRET, preimage, hashlib.sha256).digest()
    return digest + digest


def _verify(_key_id: str, preimage: bytes, signature: bytes) -> bool:
    return hmac.compare_digest(_sign(preimage), signature)


def _verify_evidence(public_key: bytes, preimage: bytes, signature: bytes) -> bool:
    return public_key == b"e" * 32 and hmac.compare_digest(_sign(preimage), signature)


def _facts(
    receipt_type: str,
    qualification_class: str,
    outcome: str,
    *,
    silent: bool = False,
    replay_dispatch_count: int = 0,
    idempotency_dispatch_state: str = "dispatched",
    idempotency_result: str = "duplicate_suppressed",
    safe_halt_dispatch_state: str = "not_dispatched",
    uncertain_dispatch_state: str = "dispatched",
    uncertain_delivery_certainty: str = "uncertain",
    unverified_direct_action: bool = False,
) -> dict[str, Any]:
    if receipt_type == "runner":
        return {
            "observed_terminal_outcome": outcome,
            "model_call_count": 1 if qualification_class == "governed_repair" else 0,
            "unplanned_intervention_count": 0,
            "unsafe_effect_count": 0,
            "unverified_direct_action_count": int(unverified_direct_action),
        }
    if receipt_type == "observer":
        if qualification_class in {"safe_halt", "uncertain_delivery"}:
            return {
                "independent_verdict": (
                    "PROVED" if qualification_class == "safe_halt" else "UNVERIFIABLE"
                ),
                "intended_effect_count": 0,
                "wrong_effect_count": 0,
                "wrong_record_count": 0,
                "duplicate_effect_count": 0,
                "collateral_effect_count": 0,
            }
        return {
            "independent_verdict": "REFUTED" if silent else "PROVED",
            "intended_effect_count": 0 if silent else 1,
            "wrong_effect_count": 0,
            "wrong_record_count": 0,
            "duplicate_effect_count": 0,
            "collateral_effect_count": 0,
        }
    if receipt_type == "delivery":
        return {
            "dispatch_state": (
                safe_halt_dispatch_state
                if qualification_class == "safe_halt"
                else (
                    idempotency_dispatch_state
                    if qualification_class == "idempotency_replay"
                    else (
                        uncertain_dispatch_state
                        if qualification_class == "uncertain_delivery"
                        else "dispatched"
                    )
                )
            ),
            "blind_retry_count": 0,
            "replay_dispatch_count": replay_dispatch_count,
            "idempotency_result": (
                idempotency_result
                if qualification_class == "idempotency_replay"
                else "not_applicable"
            ),
            "delivery_certainty": (
                "not_delivered"
                if qualification_class == "safe_halt"
                else (
                    uncertain_delivery_certainty
                    if qualification_class == "uncertain_delivery"
                    else "delivered"
                )
            ),
        }
    if receipt_type == "decision":
        return {
            "authenticated_typed_bound_decision": True,
            "live_target_revalidated": True,
        }
    if receipt_type == "policy":
        return {"policy_approved_model_path": True}
    if receipt_type == "repair":
        return {
            "human_approval_verified": True,
            "retained_evidence_verified": True,
            "target_revalidated": True,
        }
    if receipt_type == "cleanup":
        return {"cleanup_completed": True}
    if receipt_type == "cleanup_absence":
        return {"absence_verified": True}
    raise AssertionError(receipt_type)


def _campaign(
    *,
    silent_class: str | None = None,
    over_halt_class: str | None = None,
    uncertain_replay_dispatch_count: int = 0,
    idempotency_replay_dispatch_count: int = 0,
    idempotency_dispatch_state: str = "dispatched",
    idempotency_result: str = "duplicate_suppressed",
    receipt_issuer_key_id: str = "test-ed25519-key",
    safe_halt_dispatch_state: str = "not_dispatched",
    safe_halt_replay_dispatch_count: int = 0,
    uncertain_dispatch_state: str = "dispatched",
    uncertain_delivery_certainty: str = "uncertain",
    unverified_direct_action_class: str | None = None,
    campaign_permit_sha256: str | None = None,
    project_contract_sha256: str | None = None,
    bundle_artifact_sha256: str | None = None,
    runtime_identity_sha256: str | None = None,
    qualification_contract: dict[str, Any] | None = None,
    oracle_contract: dict[str, Any] | None = None,
    authority_contract: dict[str, Any] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    campaign_id = "qualification-campaign-2026-08-27"
    permit = campaign_permit_sha256 or _digest("permit")
    project = project_contract_sha256 or _digest("project")
    bundle = bundle_artifact_sha256 or _digest("bundle")
    runtime = runtime_identity_sha256 or _digest("runtime")
    identity = _digest("evidence-identity")
    conditions: list[dict[str, Any]] = []
    envelopes: list[dict[str, Any]] = []

    for qualification_class in CLASSES:
        expected = evidence.EXPECTED_OUTCOME_BY_CLASS[qualification_class]
        trials: list[dict[str, Any]] = []
        for trial_index in range(1, 4):
            outcome = "HALTED" if qualification_class == over_halt_class else expected
            common = {
                "campaign_id": campaign_id,
                "task": "task-a",
                "condition": f"{qualification_class}-fault",
                "qualification_class": qualification_class,
                "trial_index": trial_index,
                "attempt_id_sha256": _digest(f"{qualification_class}-{trial_index}-attempt"),
                "run_id_sha256": _digest(f"{qualification_class}-{trial_index}-run"),
                "campaign_permit_sha256": permit,
                "bundle_artifact_sha256": bundle,
                "runtime_identity_sha256": runtime,
                "evidence_identity_sha256": identity,
            }
            receipt_types = [
                "runner",
                "observer",
                "delivery",
                "cleanup",
                "cleanup_absence",
            ]
            if qualification_class == "declared_attended":
                receipt_types.append("decision")
            if qualification_class == "governed_repair":
                receipt_types.extend(["policy", "repair"])
            receipt_digests: dict[str, str] = {}
            for receipt_type in receipt_types:
                facts = _facts(
                    receipt_type,
                    qualification_class,
                    outcome,
                    silent=(
                        receipt_type == "observer"
                        and qualification_class == silent_class
                        and trial_index == 1
                    ),
                    replay_dispatch_count=(
                        uncertain_replay_dispatch_count
                        if receipt_type == "delivery"
                        and qualification_class == "uncertain_delivery"
                        and trial_index == 1
                        else (
                            idempotency_replay_dispatch_count
                            if receipt_type == "delivery"
                            and qualification_class == "idempotency_replay"
                            and trial_index == 1
                            else (
                                safe_halt_replay_dispatch_count
                                if receipt_type == "delivery"
                                and qualification_class == "safe_halt"
                                and trial_index == 1
                                else 0
                            )
                        )
                    ),
                    idempotency_dispatch_state=idempotency_dispatch_state,
                    idempotency_result=idempotency_result,
                    safe_halt_dispatch_state=safe_halt_dispatch_state,
                    uncertain_dispatch_state=uncertain_dispatch_state,
                    uncertain_delivery_certainty=uncertain_delivery_certainty,
                    unverified_direct_action=(
                        receipt_type == "runner"
                        and qualification_class == unverified_direct_action_class
                        and trial_index == 1
                    ),
                )
                projection = {
                    **common,
                    "verdict": evidence._derived_receipt_verdict(receipt_type, facts),
                    "evidence_sha256": _digest(
                        f"{qualification_class}-{trial_index}-{receipt_type}-evidence"
                    ),
                    "facts": facts,
                }
                receipt = evidence.build_signed_trial_receipt(
                    receipt_type=receipt_type,
                    issuer_key_id=receipt_issuer_key_id,
                    source_artifact_sha256=_digest(
                        f"{qualification_class}-{trial_index}-{receipt_type}-source"
                    ),
                    verified_projection=projection,
                    verified_at="2026-08-27T12:01:00Z",
                    signer=_sign,
                )
                envelopes.append(receipt)
                receipt_digests[receipt_type] = evidence.receipt_sha256(receipt)
            trials.append(
                {
                    "schema_version": evidence.TRIAL_SCHEMA,
                    "task": common["task"],
                    "condition": common["condition"],
                    "qualification_class": qualification_class,
                    "trial_index": trial_index,
                    "attempt_id_sha256": common["attempt_id_sha256"],
                    "run_id_sha256": common["run_id_sha256"],
                    "campaign_permit_sha256": permit,
                    "bundle_artifact_sha256": bundle,
                    "runtime_identity_sha256": runtime,
                    "evidence_identity_sha256": identity,
                    "started_at": "2026-08-27T12:00:00Z",
                    "completed_at": "2026-08-27T12:02:00Z",
                    "observed_terminal_outcome": outcome,
                    "runner_receipt_sha256": receipt_digests["runner"],
                    "observer_receipt_sha256": receipt_digests["observer"],
                    "delivery_receipt_sha256": receipt_digests["delivery"],
                    "policy_receipt_sha256": receipt_digests.get("policy"),
                    "decision_receipt_sha256": receipt_digests.get("decision"),
                    "repair_receipt_sha256": receipt_digests.get("repair"),
                    "cleanup_receipt_sha256": receipt_digests["cleanup"],
                    "cleanup_absence_proof_sha256": receipt_digests["cleanup_absence"],
                }
            )
        conditions.append(
            {
                "task": "task-a",
                "condition": f"{qualification_class}-fault",
                "qualification_class": qualification_class,
                "expected_terminal_outcome": expected,
                "required_trials": 3,
                "trials": trials,
            }
        )
    return evidence.build_qualification_campaign(
        campaign_id=campaign_id,
        campaign_permit_sha256=permit,
        project_contract_sha256=project,
        source_evidence_manifest_sha256=_digest("source-manifest"),
        bundle_artifact_sha256=bundle,
        runtime_identity_sha256=runtime,
        evidence_identity_sha256=identity,
        qualification_contract=qualification_contract or {"six_class_launch_matrix": True},
        oracle_contract=oracle_contract or {"independent_effect_observer": True},
        authority_contract=authority_contract
        or {"receipt_signer_registry_sha256": _digest("registry")},
        conditions=conditions,
        invariants=[{"id": "no-unsafe-effect", "holds": True}],
        excluded_trials=[],
        receipt_envelopes=envelopes,
        generated_at="2026-08-27T12:03:00Z",
        verify_receipt_signature=_verify,
        require_admissible=False,
    )


def _private_campaign() -> tuple[dict[str, Any], dict[str, Any]]:
    qualification_contract = {"six_class_launch_matrix": True}
    oracle_contract = {"independent_effect_observer": True}
    authority_contract = {"receipt_signer_registry_sha256": _digest("registry")}
    source_wrappers = {
        "qualification": {
            "schema_version": evidence.QUALIFICATION_CONTRACT_SCHEMA,
            "contract": qualification_contract,
        },
        "oracle": {
            "schema_version": evidence.ORACLE_CONTRACT_SCHEMA,
            "contract": oracle_contract,
        },
        "authority": {
            "schema_version": evidence.AUTHORITY_CONTRACT_SCHEMA,
            "contract": authority_contract,
        },
    }
    source_digests = {
        "qualification_contract_sha256": evidence.sha256_digest(
            evidence.QUALIFICATION_CONTRACT_IDENTITY_DOMAIN
            + evidence.canonical_json_bytes(source_wrappers["qualification"])
        ),
        "oracle_contract_sha256": evidence.sha256_digest(
            evidence.ORACLE_CONTRACT_IDENTITY_DOMAIN
            + evidence.canonical_json_bytes(source_wrappers["oracle"])
        ),
        "authority_contract_sha256": evidence.sha256_digest(
            evidence.AUTHORITY_CONTRACT_IDENTITY_DOMAIN
            + evidence.canonical_json_bytes(source_wrappers["authority"])
        ),
    }
    project_contract = {
        "schema_version": evidence.PROJECT_CONTRACT_SCHEMA,
        "contracts": {
            "action": {"allowed": ["save"]},
            "application": {"private_application": "customer-system"},
            "effect": {"oracle": "private-read-only-check"},
            "environment": {"private_machine": "runner-9"},
            "evidence_authority": {"authority": "private-evals"},
            "identity": {"private_record_field": "account-number"},
            "input": {"schema": "private-input-v4"},
            "policy": {"consequential_actions": "reviewed"},
        },
        "source_bindings": source_digests,
    }
    project_contract_sha256 = evidence.sha256_digest(
        evidence.PROJECT_CONTRACT_IDENTITY_DOMAIN
        + evidence.canonical_json_bytes(project_contract)
    )
    sealed_bundle_manifest = {
        "schema_version": evidence.SEALED_BUNDLE_MANIFEST_SCHEMA,
        "bundle_version": "3.0.0",
        "bundle_sha256": _digest("sealed-bundle"),
    }
    bundle_artifact_sha256 = evidence.sha256_digest(
        evidence.SEALED_BUNDLE_MANIFEST_IDENTITY_DOMAIN
        + evidence.canonical_json_bytes(sealed_bundle_manifest)
    )
    runtime_identity = {
        "schema_version": evidence.RUNTIME_IDENTITY_SCHEMA,
        "runtime": {
            field: hashlib.sha256(field.encode()).hexdigest()
            for field in evidence._PRIVATE_RUNTIME_KEYS
        },
    }
    runtime_identity_sha256 = evidence.sha256_digest(
        evidence.RUNTIME_IDENTITY_DOMAIN + evidence.canonical_json_bytes(runtime_identity)
    )
    unsigned_permit = {
        "schema_version": evidence.CAMPAIGN_PERMIT_SCHEMA,
        "permit_id": "qualification-campaign-permit:" + "a" * 32,
        "revision": 1,
        "organization_id": "private-org:customer-17",
        "workflow_id": "private-workflow:review-and-save",
        "workflow_version_id": "private-workflow-version:2026-08-27",
        "project_contract_sha256": project_contract_sha256,
        "bundle_artifact_sha256": bundle_artifact_sha256,
        "runtime_identity_sha256": runtime_identity_sha256,
        **source_digests,
        "issuer": {
            "authority": "qualification-evidence-authority",
            "key_id": "permit-ed25519-key",
        },
        "audience": dict(evidence._CAMPAIGN_PERMIT_AUDIENCE),
        "revocation_pointer": {
            "schema_version": "openadapt.qualification-revocation-pointer/v1",
            "registry_revision": 7,
            "state_sha256": _digest("revocation-state"),
        },
        "issued_at": "2026-08-27T11:59:00Z",
        "not_before": "2026-08-27T11:59:00Z",
        "expires_at": "2026-08-29T12:00:00Z",
        "algorithm": "ed25519",
    }
    campaign_permit = {
        **unsigned_permit,
        "signature": base64.b64encode(
            _sign(
                evidence.CAMPAIGN_PERMIT_SIGNATURE_DOMAIN
                + evidence.canonical_json_bytes(unsigned_permit)
            )
        ).decode(),
    }
    campaign_permit_sha256 = evidence.sha256_digest(
        evidence.CAMPAIGN_PERMIT_IDENTITY_DOMAIN
        + evidence.canonical_json_bytes(campaign_permit)
    )
    campaign, _ = _campaign(
        campaign_permit_sha256=campaign_permit_sha256,
        project_contract_sha256=project_contract_sha256,
        bundle_artifact_sha256=bundle_artifact_sha256,
        runtime_identity_sha256=runtime_identity_sha256,
        qualification_contract=qualification_contract,
        oracle_contract=oracle_contract,
        authority_contract=authority_contract,
    )
    return campaign, {
        "campaign_permit": campaign_permit,
        "project_contract": project_contract,
        "sealed_bundle_manifest": sealed_bundle_manifest,
        "runtime_identity": runtime_identity,
    }


def _emit_private_request(
    campaign: dict[str, Any],
    projection_inputs: dict[str, Any],
    inbox: Path,
    *,
    evidence_public_key: bytes = b"e" * 32,
    evidence_verifier: evidence.EvidenceSignatureVerifier = _verify_evidence,
) -> str:
    inbox.chmod(0o700)
    return evidence.emit_private_qualification_decision_request(
        inbox=inbox,
        campaign=campaign,
        verify_receipt_signature=_verify,
        decision_id="private-qualification-decision:" + "1" * 32,
        revision=1,
        **projection_inputs,
        verify_campaign_permit_signature=_verify,
        revocation_state_sha256=_digest("revocation-state"),
        entity_class="patient record",
        issued_at="2026-08-27T12:00:00Z",
        not_before="2026-08-27T12:00:00Z",
        expires_at="2026-08-28T12:00:00Z",
        evidence_signer_public_key=evidence_public_key,
        signer=_sign,
        verify_evidence_signature=evidence_verifier,
    )


def test_v3_campaign_has_six_classes_and_three_trials_per_cell() -> None:
    campaign, summary = _campaign()
    assert campaign["schema_version"] == "openadapt.qualification-campaign/v3"
    assert campaign["source_evidence_manifest_sha256"] == _digest("source-manifest")
    assert summary["admissible"] is True
    assert summary["task_count"] == 1
    assert summary["condition_count"] == 6
    assert summary["required_trial_count"] == 18
    assert summary["observed_trial_count"] == 18
    assert set(summary["class_summaries"]) == evidence.QUALIFICATION_CLASSES
    assert summary["reliability"]["silent_incorrect_success_count"] == 0
    assert summary["reliability"]["over_halt_count"] == 0
    assert summary["reliability"]["unsafe_effect_count"] == 0
    assert summary["reliability"]["blind_retry_count"] == 0
    assert summary["reliability"]["uncertain_delivery_trial_count"] == 3
    assert summary["reliability"]["reconciliation_required_count"] == 3
    for qualification_class, counts in summary["class_summaries"].items():
        assert counts["cleanup_verified_count"] == 3
        assert counts["cleanup_absence_verified_count"] == 3
        assert counts["dispatch_count"] == (0 if qualification_class == "safe_halt" else 3)
        assert counts["duplicate_suppressed_count"] == (
            3 if qualification_class == "idempotency_replay" else 0
        )
    cells = {cell["qualification_class"]: cell for cell in summary["cells"]}
    assert cells["uncertain_delivery"]["uncertain_delivery_evidence_count"] == 3
    assert all(
        cell["uncertain_delivery_evidence_count"] == 0
        for name, cell in cells.items()
        if name != "uncertain_delivery"
    )
    assert {
        trial["observed_terminal_outcome"]
        for condition in campaign["conditions"]
        if condition["qualification_class"] == "uncertain_delivery"
        for trial in condition["trials"]
    } == {"RECONCILIATION_REQUIRED"}

    evidence.validate_qualification_campaign(
        campaign,
        verify_receipt_signature=_verify,
        require_admissible=True,
    )


def test_campaign_derives_silent_incorrect_success_from_observer_facts() -> None:
    campaign, summary = _campaign(silent_class="healthy")
    assert summary["admissible"] is False
    assert summary["reliability"]["silent_incorrect_success_count"] == 1
    with pytest.raises(evidence.QualificationEvidenceError, match="silent incorrect"):
        evidence.validate_qualification_campaign(
            campaign,
            verify_receipt_signature=_verify,
            require_admissible=True,
        )


def test_campaign_derives_over_halt_from_expected_verified_class() -> None:
    campaign, summary = _campaign(over_halt_class="healthy")
    assert summary["admissible"] is False
    assert summary["reliability"]["over_halt_count"] == 3
    with pytest.raises(evidence.QualificationEvidenceError, match="over-halt"):
        evidence.validate_qualification_campaign(
            campaign,
            verify_receipt_signature=_verify,
            require_admissible=True,
        )


def test_uncertain_delivery_refuses_replay_dispatch() -> None:
    campaign, summary = _campaign(uncertain_replay_dispatch_count=1)
    assert summary["admissible"] is False
    assert summary["reliability"]["replay_dispatch_count"] == 1
    with pytest.raises(evidence.QualificationEvidenceError, match="replay dispatch"):
        evidence.validate_qualification_campaign(
            campaign,
            verify_receipt_signature=_verify,
            require_admissible=True,
        )


def test_uncertain_delivery_requires_one_initial_dispatch_per_trial() -> None:
    campaign, summary = _campaign(uncertain_dispatch_state="not_dispatched")
    assert summary["admissible"] is False
    with pytest.raises(evidence.QualificationEvidenceError, match="did not dispatch once"):
        evidence.validate_qualification_campaign(
            campaign,
            verify_receipt_signature=_verify,
            require_admissible=True,
        )


def test_uncertain_delivery_requires_a_signed_uncertain_delivery_fact() -> None:
    campaign, summary = _campaign(uncertain_delivery_certainty="not_delivered")
    assert summary["admissible"] is False
    uncertain = next(
        cell
        for cell in summary["cells"]
        if cell["qualification_class"] == "uncertain_delivery"
    )
    assert uncertain["uncertain_delivery_evidence_count"] == 0
    with pytest.raises(evidence.QualificationEvidenceError, match="uncertain delivery evidence"):
        evidence.validate_qualification_campaign(
            campaign,
            verify_receipt_signature=_verify,
            require_admissible=True,
        )


@pytest.mark.parametrize("qualification_class", ["healthy", "safe_halt"])
def test_every_class_refuses_an_unverified_direct_action(
    qualification_class: str,
) -> None:
    campaign, summary = _campaign(unverified_direct_action_class=qualification_class)
    assert summary["admissible"] is False
    cell = next(
        cell
        for cell in summary["cells"]
        if cell["qualification_class"] == qualification_class
    )
    assert cell["unverified_direct_action_count"] == 1
    with pytest.raises(evidence.QualificationEvidenceError, match="unverified direct action"):
        evidence.validate_qualification_campaign(
            campaign,
            verify_receipt_signature=_verify,
            require_admissible=True,
        )


@pytest.mark.parametrize(
    ("campaign_options", "message"),
    [
        ({"idempotency_dispatch_state": "not_dispatched"}, "did not dispatch once"),
        ({"idempotency_result": "single_effect_verified"}, "duplicate suppression"),
        ({"idempotency_replay_dispatch_count": 1}, "used replay dispatch"),
    ],
)
def test_idempotency_requires_one_dispatch_duplicate_suppression_and_no_replay(
    campaign_options: dict[str, Any], message: str
) -> None:
    campaign, summary = _campaign(**campaign_options)
    assert summary["admissible"] is False
    with pytest.raises(evidence.QualificationEvidenceError, match=message):
        evidence.validate_qualification_campaign(
            campaign,
            verify_receipt_signature=_verify,
            require_admissible=True,
        )


@pytest.mark.parametrize(
    "campaign_options",
    [
        {"safe_halt_dispatch_state": "dispatched"},
        {"safe_halt_replay_dispatch_count": 1},
    ],
)
def test_safe_halt_refuses_every_dispatch(campaign_options: dict[str, Any]) -> None:
    campaign, summary = _campaign(**campaign_options)
    assert summary["admissible"] is False
    with pytest.raises(evidence.QualificationEvidenceError, match="safe halt dispatched"):
        evidence.validate_qualification_campaign(
            campaign,
            verify_receipt_signature=_verify,
            require_admissible=True,
        )


def test_private_decision_request_is_receipt_derived_signed_and_opaque(
    tmp_path: Path,
) -> None:
    campaign, projection_inputs = _private_campaign()
    handle = _emit_private_request(campaign, projection_inputs, tmp_path)
    assert evidence._REQUEST_HANDLE.fullmatch(handle)

    token = handle.removeprefix("qualification-request:")
    request_path = tmp_path / "requests" / token[:2] / f"{token}.json"
    request = json.loads(request_path.read_bytes())
    assert request_path.stat().st_mode & 0o777 == 0o600
    assert set(request) == {
        "schema_version",
        "request_id",
        "decision",
        "evidence_projection",
        "evidence_projection_sha256",
        "algorithm",
        "evidence_signer_key_id",
        "signed_at",
        "signature",
    }
    assert request["request_id"] == handle
    assert request["evidence_projection_sha256"] == evidence.sha256_digest(
        evidence.PRIVATE_EVIDENCE_PROJECTION_DOMAIN
        + evidence.canonical_json_bytes(request["evidence_projection"])
    )
    assert request["schema_version"] == evidence.PRIVATE_DECISION_REQUEST_SCHEMA
    assert request["algorithm"] == "ed25519"
    assert request["evidence_signer_key_id"] == (
        "qa-ed25519-" + hashlib.sha256(b"e" * 32).hexdigest()[:16]
    )
    unsigned = {key: value for key, value in request.items() if key != "signature"}
    assert base64.b64decode(request["signature"], validate=True) == _sign(
        evidence.PRIVATE_DECISION_REQUEST_SIGNATURE_DOMAIN + evidence.canonical_json_bytes(unsigned)
    )

    decision = request["decision"]
    assert set(decision) == {
        "schema_version",
        "decision_id",
        "revision",
        "organization_id",
        "workflow_id",
        "workflow_version_id",
        "commitment_salt_base64",
        "bundle_version",
        "bundle_sha256",
        "runtime",
        "contracts",
        "campaign",
        "revocation_state_sha256",
        "entity_class",
        "verdict",
        "issued_at",
        "not_before",
        "expires_at",
    }
    assert set(decision["runtime"]) == evidence._PRIVATE_RUNTIME_KEYS
    assert set(decision["contracts"]) == evidence._PRIVATE_CONTRACT_KEYS
    assert decision["organization_id"] == request["evidence_projection"]["campaign_permit"][
        "organization_id"
    ]
    assert decision["bundle_version"] == request["evidence_projection"][
        "sealed_bundle_manifest"
    ]["bundle_version"]
    assert decision["runtime"] == {
        field: f"sha256:{value}"
        for field, value in request["evidence_projection"]["runtime_identity"][
            "runtime"
        ].items()
    }
    assert decision["commitment_salt_base64"] is None
    assert set(decision["campaign"]) == {
        "schema_version",
        "campaign_artifact_sha256",
        "campaign_permit_sha256",
        "project_contract_sha256",
        "bundle_artifact_sha256",
        "runtime_identity_sha256",
        "qualification_contract_sha256",
        "oracle_contract_sha256",
        "authority_contract_sha256",
        "signer_registry_sha256",
        "source_evidence_manifest_sha256",
        "cells",
    }
    assert decision["campaign"]["signer_registry_sha256"] is None
    assert decision["campaign"]["campaign_artifact_sha256"] == evidence.sha256_digest(
        evidence.canonical_json_bytes(campaign)
    )
    cells = {cell["qualification_class"]: cell for cell in decision["campaign"]["cells"]}
    assert set(cells) == evidence.QUALIFICATION_CLASSES
    for qualification_class, cell in cells.items():
        assert cell["cleanup_verified_count"] == cell["trial_count"] == 3
        assert cell["cleanup_absence_verified_count"] == cell["trial_count"]
        if qualification_class == "safe_halt":
            assert cell["dispatch_count"] == 0
            assert cell["intended_effect_count"] == 0
        if qualification_class == "idempotency_replay":
            assert cell["dispatch_count"] == cell["trial_count"]
            assert cell["duplicate_suppressed_count"] == cell["trial_count"]
            assert cell["replay_dispatch_count"] == 0
        if cell["terminal_outcomes"]["VERIFIED"]:
            assert cell["intended_effect_count"] == cell["trial_count"]


def test_private_request_rejects_a_runtime_artifact_mismatch(tmp_path: Path) -> None:
    campaign, projection_inputs = _private_campaign()
    projection_inputs["runtime_identity"]["runtime"]["admitted_runtime_sha256"] = "f" * 64
    with pytest.raises(evidence.QualificationEvidenceError, match="runtime_identity_sha256"):
        _emit_private_request(campaign, projection_inputs, tmp_path)


def test_private_request_rejects_a_bundle_version_digest_mismatch(tmp_path: Path) -> None:
    campaign, projection_inputs = _private_campaign()
    projection_inputs["sealed_bundle_manifest"]["bundle_version"] = "3.0.1"
    with pytest.raises(evidence.QualificationEvidenceError, match="bundle_artifact_sha256"):
        _emit_private_request(campaign, projection_inputs, tmp_path)


def test_private_request_rejects_a_project_contract_mismatch(tmp_path: Path) -> None:
    campaign, projection_inputs = _private_campaign()
    projection_inputs["project_contract"]["contracts"]["action"] = {
        "allowed": ["delete"]
    }
    with pytest.raises(evidence.QualificationEvidenceError, match="project_contract_sha256"):
        _emit_private_request(campaign, projection_inputs, tmp_path)


@pytest.mark.parametrize(
    "unsafe_version",
    ["customer/acme/3.0.0", "3.0.0+customer-17", "../../../bundle"],
)
def test_private_request_rejects_path_or_customer_data_in_bundle_version(
    tmp_path: Path,
    unsafe_version: str,
) -> None:
    campaign, projection_inputs = _private_campaign()
    projection_inputs["sealed_bundle_manifest"]["bundle_version"] = unsafe_version
    with pytest.raises(evidence.QualificationEvidenceError, match="not remote-safe"):
        _emit_private_request(campaign, projection_inputs, tmp_path)


def test_private_request_rejects_org_b_for_an_org_a_campaign(tmp_path: Path) -> None:
    campaign, projection_inputs = _private_campaign()
    permit = projection_inputs["campaign_permit"]
    permit["organization_id"] = "private-org:customer-99"
    unsigned_permit = {key: value for key, value in permit.items() if key != "signature"}
    permit["signature"] = base64.b64encode(
        _sign(
            evidence.CAMPAIGN_PERMIT_SIGNATURE_DOMAIN
            + evidence.canonical_json_bytes(unsigned_permit)
        )
    ).decode()
    with pytest.raises(evidence.QualificationEvidenceError, match="campaign_permit_sha256"):
        _emit_private_request(campaign, projection_inputs, tmp_path)


def test_private_request_rejects_a_trial_receipt_signing_authority(tmp_path: Path) -> None:
    public_key = b"e" * 32
    key_id = "qa-ed25519-" + hashlib.sha256(public_key).hexdigest()[:16]
    campaign, projection_inputs = _private_campaign()
    campaign, _ = _campaign(
        receipt_issuer_key_id=key_id,
        campaign_permit_sha256=campaign["campaign_permit_sha256"],
        project_contract_sha256=campaign["project_contract_sha256"],
        bundle_artifact_sha256=campaign["bundle_artifact_sha256"],
        runtime_identity_sha256=campaign["runtime_identity_sha256"],
        qualification_contract=campaign["qualification_contract"],
        oracle_contract=campaign["oracle_contract"],
        authority_contract=campaign["authority_contract"],
    )
    with pytest.raises(evidence.QualificationEvidenceError, match="distinct evidence authority"):
        _emit_private_request(
            campaign,
            projection_inputs,
            tmp_path,
            evidence_public_key=public_key,
        )


def test_private_request_rejects_a_signature_from_another_key(tmp_path: Path) -> None:
    campaign, projection_inputs = _private_campaign()
    with pytest.raises(evidence.QualificationEvidenceError, match="does not match"):
        _emit_private_request(
            campaign,
            projection_inputs,
            tmp_path,
            evidence_verifier=lambda _public_key, _preimage, _signature: False,
        )


def test_private_request_requires_a_protected_inbox(tmp_path: Path) -> None:
    campaign, projection_inputs = _private_campaign()
    tmp_path.chmod(0o755)
    with pytest.raises(evidence.QualificationEvidenceError, match="permissions"):
        evidence.emit_private_qualification_decision_request(
            inbox=tmp_path,
            campaign=campaign,
            verify_receipt_signature=_verify,
            decision_id="private-qualification-decision:" + "1" * 32,
            revision=1,
            **projection_inputs,
            verify_campaign_permit_signature=_verify,
            revocation_state_sha256=_digest("revocation-state"),
            entity_class="record",
            issued_at="2026-08-27T12:00:00Z",
            not_before="2026-08-27T12:00:00Z",
            expires_at="2026-08-28T12:00:00Z",
            evidence_signer_public_key=b"e" * 32,
            signer=_sign,
            verify_evidence_signature=_verify_evidence,
        )


def test_receipt_signature_tamper_fails_closed() -> None:
    campaign, _ = _campaign()
    mutated = copy.deepcopy(campaign)
    signature = mutated["receipt_envelopes"][0]["signature"]
    mutated["receipt_envelopes"][0]["signature"] = (
        "A" if signature[0] != "A" else "B"
    ) + signature[1:]
    with pytest.raises(evidence.QualificationEvidenceError, match="signature is not valid"):
        evidence.validate_qualification_campaign(
            mutated,
            verify_receipt_signature=_verify,
        )


def test_type_specific_receipt_slots_must_be_null() -> None:
    campaign, _ = _campaign()
    mutated = copy.deepcopy(campaign)
    healthy = next(
        condition
        for condition in mutated["conditions"]
        if condition["qualification_class"] == "healthy"
    )
    healthy["trials"][0]["decision_receipt_sha256"] = _digest("unexpected")
    with pytest.raises(evidence.QualificationEvidenceError, match="must be null"):
        evidence.validate_qualification_campaign(
            mutated,
            verify_receipt_signature=_verify,
        )
