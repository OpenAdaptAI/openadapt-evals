from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "import_production_acceptance.py"
SPEC = importlib.util.spec_from_file_location("production_acceptance_importer", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

WORKFLOW_REF = (
    "OpenAdaptAI/openadapt-evals/.github/workflows/import-production-acceptance.yml"
    "@refs/heads/main"
)


def _contract() -> dict[str, Any]:
    return {
        "schema_version": MODULE.PRIVATE_EXPORT_CONTRACT_SCHEMA,
        "storage_identity": {
            "account": "123456789012",
            "service": "s3",
            "container": "openadapt-retained-evidence",
            "prefix": "production-acceptance/",
        },
        "kms_key_identity": {
            "provider": "aws-kms",
            "key_identity": "arn:aws:kms:us-east-1:123456789012:key/1111-2222",
        },
        "uploader_identity": {
            "provider": "github-actions",
            "principal": "OpenAdaptAI/openadapt-cloud",
        },
        "importer_workflow_ref": WORKFLOW_REF,
        "minimum_retention_days": 365,
        "maximum_retention_days": 2555,
        "approval_authority": "OpenAdapt",
        "approved_at": "2026-08-26T12:00:00.000Z",
    }


def test_a_reviewer_can_recompute_every_identity_digest() -> None:
    contract = _contract()
    facts = MODULE.validate_private_export_contract(contract)

    for domain, field, digest in (
        (MODULE.STORAGE_IDENTITY_DOMAIN, "storage_identity", "storage_identity_sha256"),
        (MODULE.KMS_KEY_IDENTITY_DOMAIN, "kms_key_identity", "kms_key_identity_sha256"),
        (MODULE.UPLOADER_IDENTITY_DOMAIN, "uploader_identity", "uploader_identity_sha256"),
    ):
        preimage = domain + MODULE.canonical_json(
            {key: contract[field][key] for key in sorted(contract[field])}
        ).encode("utf-8")
        assert facts[digest] == "sha256:" + hashlib.sha256(preimage).hexdigest()


def test_the_contract_carries_preimages_not_digests() -> None:
    contract = _contract()

    # An approval that asserted a digest would be unverifiable. Every digest the
    # importer compares against has to be derived from a visible preimage.
    assert not any(key.endswith("_sha256") for key in contract)
    facts = MODULE.validate_private_export_contract(contract)
    assert facts["storage_identity_sha256"].startswith("sha256:")


@pytest.mark.parametrize(
    "mutation,expected",
    [
        (lambda c: c.__setitem__("schema_version", "other/v1"), "schema is not supported"),
        (lambda c: c.pop("approval_authority"), "keys differ"),
        (lambda c: c.__setitem__("unreviewed", True), "keys differ"),
        (lambda c: c.__setitem__("approval_authority", ""), "approval authority"),
        (lambda c: c.__setitem__("importer_workflow_ref", "main"), "workflow ref is invalid"),
        (
            lambda c: c.__setitem__(
                "importer_workflow_ref",
                "OpenAdaptAI/openadapt-evals/.github/workflows/x.yml@refs/tags/v1",
            ),
            "workflow ref is invalid",
        ),
        (lambda c: c.__setitem__("minimum_retention_days", 30), "floor is outside policy"),
        (lambda c: c.__setitem__("maximum_retention_days", 4000), "ceiling is outside policy"),
        (lambda c: c.__setitem__("maximum_retention_days", 100), "floor is outside policy"),
        (lambda c: c["storage_identity"].__setitem__("prefix", ""), "storage identity prefix"),
        (lambda c: c["storage_identity"].pop("account"), "storage identity keys differ"),
        (lambda c: c["kms_key_identity"].__setitem__("key_identity", ""), "key identity"),
        (lambda c: c["uploader_identity"].pop("principal"), "uploader identity keys differ"),
        (lambda c: c.__setitem__("approved_at", "2026-08-26T12:00:00Z"), "canonical"),
    ],
)
def test_contract_refuses_anything_inexact(mutation: object, expected: str) -> None:
    contract = _contract()
    mutation(contract)

    with pytest.raises(MODULE.AcceptanceError, match=expected):
        MODULE.validate_private_export_contract(contract)


def test_contract_bounds_must_sit_inside_the_fixed_policy() -> None:
    policy = MODULE.production_acceptance_policy()
    facts = MODULE.validate_private_export_contract(_contract())

    assert policy["minimum_retention_days"] <= facts["minimum_retention_days"]
    assert facts["maximum_retention_days"] <= policy["maximum_retention_days"]


def test_importer_identity_must_be_the_approved_workflow_and_ref() -> None:
    facts = MODULE.validate_private_export_contract(_contract())

    MODULE.verify_importer_identity(facts, {"GITHUB_WORKFLOW_REF": WORKFLOW_REF})

    for environ, expected in (
        ({}, "importer workflow ref is absent"),
        ({"GITHUB_WORKFLOW_REF": ""}, "importer workflow ref is absent"),
        (
            {
                "GITHUB_WORKFLOW_REF": (
                    "OpenAdaptAI/openadapt-evals/.github/workflows/other.yml@refs/heads/main"
                )
            },
            "not the approved workflow",
        ),
        (
            {"GITHUB_WORKFLOW_REF": WORKFLOW_REF.replace("refs/heads/main", "refs/heads/dev")},
            "not the approved workflow",
        ),
        (
            {"GITHUB_WORKFLOW_REF": WORKFLOW_REF.replace("OpenAdaptAI", "attacker")},
            "not the approved workflow",
        ),
    ):
        with pytest.raises(MODULE.AcceptanceError, match=expected):
            MODULE.verify_importer_identity(facts, environ)


def _retention(facts: dict[str, Any]) -> dict[str, Any]:
    return {
        "storage_identity_sha256": facts["storage_identity_sha256"],
        "kms_key_identity_sha256": facts["kms_key_identity_sha256"],
        "uploader_identity_sha256": facts["uploader_identity_sha256"],
        "retained_at": "2026-08-18T12:00:00.000Z",
        "retention_until": "2028-08-18T12:00:00.000Z",
    }


def test_retention_must_match_the_approved_destination_key_and_uploader() -> None:
    facts = MODULE.validate_private_export_contract(_contract())

    MODULE.verify_retention_against_contract(_retention(facts), facts)

    for key in (
        "storage_identity_sha256",
        "kms_key_identity_sha256",
        "uploader_identity_sha256",
    ):
        retention = _retention(facts)
        retention[key] = "sha256:" + "0" * 64
        with pytest.raises(MODULE.AcceptanceError, match=f"{key} is not the approved"):
            MODULE.verify_retention_against_contract(retention, facts)

        retention = _retention(facts)
        retention.pop(key)
        with pytest.raises(MODULE.AcceptanceError, match=f"{key} is not the approved"):
            MODULE.verify_retention_against_contract(retention, facts)


def test_a_certificate_cannot_choose_its_own_destination() -> None:
    facts = MODULE.validate_private_export_contract(_contract())
    elsewhere = copy.deepcopy(_contract())
    elsewhere["storage_identity"]["container"] = "attacker-bucket"
    forged = MODULE.validate_private_export_contract(elsewhere)

    retention = _retention(facts)
    retention["storage_identity_sha256"] = forged["storage_identity_sha256"]

    with pytest.raises(MODULE.AcceptanceError, match="not the approved identity"):
        MODULE.verify_retention_against_contract(retention, facts)


@pytest.mark.parametrize(
    "retained_at,retention_until,expected",
    [
        ("2026-08-18T12:00:00.000Z", "2026-09-18T12:00:00.000Z", "outside the approved"),
        ("2026-08-18T12:00:00.000Z", "2040-08-18T12:00:00.000Z", "outside the approved"),
    ],
)
def test_retention_period_must_sit_inside_the_approved_window(
    retained_at: str,
    retention_until: str,
    expected: str,
) -> None:
    facts = MODULE.validate_private_export_contract(_contract())
    retention = _retention(facts)
    retention["retained_at"] = retained_at
    retention["retention_until"] = retention_until

    with pytest.raises(MODULE.AcceptanceError, match=expected):
        MODULE.verify_retention_against_contract(retention, facts)


def test_cli_refuses_a_contract_it_is_not_authorised_to_use(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract_path = tmp_path / "contract.json"
    contract_path.write_text(json.dumps(_contract()), encoding="utf-8")
    monkeypatch.setenv("GITHUB_WORKFLOW_REF", "attacker/repo/.github/workflows/x.yml@refs/heads/main")

    result = MODULE.main(
        [
            "--certificate",
            str(tmp_path / "certificate.json"),
            "--campaign",
            str(tmp_path / "campaign.json"),
            "--qualification-admission",
            str(tmp_path / "admission.json"),
            "--attestation-bundle",
            str(tmp_path / "bundle.jsonl"),
            "--expected-cloud-source-commit",
            "f" * 40,
            "--trusted-admission-signers",
            str(ROOT / "tests/fixtures/production_acceptance/qualification-admission-trust.json"),
            "--private-export-contract",
            str(contract_path),
            "--output",
            str(tmp_path / "derived.json"),
        ]
    )

    assert result == 1
    assert "not the approved workflow" in capsys.readouterr().err
    assert not (tmp_path / "derived.json").exists()


def test_cli_still_refuses_even_with_an_authorised_importer(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The contract mechanism is implemented. The import gate stays closed."""

    contract_path = tmp_path / "contract.json"
    contract_path.write_text(json.dumps(_contract()), encoding="utf-8")
    monkeypatch.setenv("GITHUB_WORKFLOW_REF", WORKFLOW_REF)

    result = MODULE.main(
        [
            "--certificate",
            str(tmp_path / "certificate.json"),
            "--campaign",
            str(tmp_path / "campaign.json"),
            "--qualification-admission",
            str(tmp_path / "admission.json"),
            "--attestation-bundle",
            str(tmp_path / "bundle.jsonl"),
            "--expected-cloud-source-commit",
            "f" * 40,
            "--trusted-admission-signers",
            str(ROOT / "tests/fixtures/production_acceptance/qualification-admission-trust.json"),
            "--private-export-contract",
            str(contract_path),
            "--output",
            str(tmp_path / "derived.json"),
        ]
    )

    assert result == 1
    assert "pending an approved private-export contract" in capsys.readouterr().err
    assert not (tmp_path / "derived.json").exists()
