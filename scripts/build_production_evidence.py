#!/usr/bin/env python3
"""Build public production summaries and content-addressed evidence pairs."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Sequence

from openadapt_evals.production_evidence import (
    ProductionEvidenceError,
    build_evidence_object_pair,
    build_production_acceptance_manifest,
    build_production_acceptance_summary,
    canonical_json_bytes,
    canonical_object_bytes,
)

_SUMMARY_INPUT_KEYS = frozenset(
    {
        "target",
        "claim_scope",
        "acceptance_policy_sha256",
        "lifecycle_policy_sha256",
        "release_identity",
        "release_sha256",
        "artifact_inventory_sha256",
        "publication_staging",
        "qualification_evidence_decision_receipt_references",
        "qualification_admission_references",
        "production_acceptance_manifest_references",
        "authority_state_sha256",
        "revocation_state_sha256",
        "signer_registry_sha256",
        "issuer",
        "issued_at",
        "not_before",
        "expires_at",
    }
)

_MANIFEST_INPUT_KEYS = frozenset(
    {
        "target",
        "claim_scope",
        "acceptance_policy_sha256",
        "release_identity",
        "release",
        "artifact_inventory",
        "publication_staging",
        "qualification_evidence_decision_receipt_references",
        "qualification_admission_references",
        "authority_state_sha256",
        "revocation_state_sha256",
        "signer_registry_sha256",
        "issuer",
        "issued_at",
        "not_before",
        "expires_at",
    }
)


def _reject_duplicate_pairs(pairs: Sequence[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ProductionEvidenceError(f"JSON contains duplicate key: {key}")
        value[key] = item
    return value


def _read_json_object(path: Path, context: str) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_pairs,
            parse_float=lambda value: (_ for _ in ()).throw(
                ProductionEvidenceError(f"{context} contains a floating-point value: {value}")
            ),
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProductionEvidenceError(f"cannot read {context}: {path}") from exc
    if not isinstance(value, dict):
        raise ProductionEvidenceError(f"{context} must be one JSON object")
    return value


def _write_atomic(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() == payload:
            return
        raise ProductionEvidenceError(f"refusing to replace different evidence: {path}")
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _read_bytes(path: Path, context: str) -> bytes:
    try:
        value = path.read_bytes()
    except OSError as exc:
        raise ProductionEvidenceError(f"cannot read {context}: {path}") from exc
    if not value:
        raise ProductionEvidenceError(f"{context} must not be empty")
    return value


def build_summary(
    input_path: Path,
    output_path: Path,
    *,
    signer_registry: Path,
    qualification_evidence_decision_receipt: Path,
    qualification_admission: Path,
    production_acceptance_manifest: Path,
) -> dict[str, Any]:
    """Build one public v2 lifecycle summary from public inputs only."""

    payload = _read_json_object(input_path, "production summary input")
    if set(payload) != _SUMMARY_INPUT_KEYS:
        missing = sorted(_SUMMARY_INPUT_KEYS - set(payload))
        extra = sorted(set(payload) - _SUMMARY_INPUT_KEYS)
        raise ProductionEvidenceError(
            f"production summary input keys differ: missing={missing}, extra={extra}"
        )
    summary = build_production_acceptance_summary(
        **payload,
        signer_registry_bytes=_read_bytes(
            signer_registry,
            "qualification signer registry",
        ),
        qualification_evidence_decision_receipt_bytes=_read_bytes(
            qualification_evidence_decision_receipt,
            "registered qualification evidence decision receipt",
        ),
        qualification_admission_bytes=_read_bytes(
            qualification_admission,
            "registered qualification admission",
        ),
        production_acceptance_manifest_bytes=_read_bytes(
            production_acceptance_manifest,
            "registered production acceptance manifest",
        ),
    )
    _write_atomic(output_path, canonical_object_bytes(summary))
    return summary


def _read_central_lifecycle_policy(
    repository: Path, source_commit: str
) -> bytes:
    if re.fullmatch(r"[0-9a-f]{40}", source_commit) is None:
        raise ProductionEvidenceError(
            "lifecycle policy source commit must be a full lowercase commit ID"
        )
    try:
        remote = subprocess.run(
            ["git", "-C", str(repository), "remote", "get-url", "origin"],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ProductionEvidenceError(
            "cannot read the central lifecycle policy repository"
        ) from exc
    allowed_remotes = {
        "git@github.com:OpenAdaptAI/.github.git",
        "https://github.com/OpenAdaptAI/.github",
        "https://github.com/OpenAdaptAI/.github.git",
    }
    if remote not in allowed_remotes:
        raise ProductionEvidenceError(
            "lifecycle policy repository is not OpenAdaptAI/.github"
        )
    try:
        subprocess.run(
            [
                "git",
                "-C",
                str(repository),
                "fetch",
                "--no-tags",
                "origin",
                "+refs/heads/main:refs/remotes/origin/main",
            ],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(repository),
                "merge-base",
                "--is-ancestor",
                source_commit,
                "refs/remotes/origin/main",
            ],
            check=True,
            capture_output=True,
        )
        return subprocess.run(
            [
                "git",
                "-C",
                str(repository),
                "show",
                f"{source_commit}:production-lifecycle-policy.json",
            ],
            check=True,
            capture_output=True,
        ).stdout
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ProductionEvidenceError(
            "cannot fetch or read the exact main-branch lifecycle policy commit"
        ) from exc


def build_manifest(
    input_path: Path,
    output_path: Path,
    *,
    lifecycle_policy_repository: Path,
    lifecycle_policy_source_commit: str,
    signer_registry: Path,
    qualification_evidence_decision_receipt: Path,
    qualification_admission: Path,
) -> dict[str, Any]:
    """Build one public-only v2 acceptance manifest."""

    payload = _read_json_object(input_path, "production acceptance manifest input")
    if set(payload) != _MANIFEST_INPUT_KEYS:
        missing = sorted(_MANIFEST_INPUT_KEYS - set(payload))
        extra = sorted(set(payload) - _MANIFEST_INPUT_KEYS)
        raise ProductionEvidenceError(
            f"production manifest input keys differ: missing={missing}, extra={extra}"
        )
    lifecycle_policy_bytes = _read_central_lifecycle_policy(
        lifecycle_policy_repository,
        lifecycle_policy_source_commit,
    )
    manifest = build_production_acceptance_manifest(
        **payload,
        lifecycle_policy_bytes=lifecycle_policy_bytes,
        signer_registry_bytes=_read_bytes(
            signer_registry,
            "qualification signer registry",
        ),
        qualification_evidence_decision_receipt_bytes=_read_bytes(
            qualification_evidence_decision_receipt,
            "registered qualification evidence decision receipt",
        ),
        qualification_admission_bytes=_read_bytes(
            qualification_admission,
            "registered qualification admission",
        ),
    )
    _write_atomic(output_path, canonical_object_bytes(manifest))
    return manifest


def build_pair(
    *,
    kind: str,
    object_path: Path,
    sigstore_bundle_path: Path,
    registry_source_commit: str,
    registry_revision: int,
    registry_head_sha256: str,
    output_root: Path,
    references_output: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Write one regular object and its bundle to their exact public paths."""

    object_value = _read_json_object(object_path, "regular production evidence object")
    object_bytes = _read_bytes(object_path, "regular production evidence object")
    if object_bytes != canonical_object_bytes(object_value):
        raise ProductionEvidenceError(
            "regular production evidence object must be canonical JSON plus one LF"
        )
    try:
        raw_bundle = sigstore_bundle_path.read_bytes()
    except OSError as exc:
        raise ProductionEvidenceError(
            f"cannot read raw Sigstore bundle: {sigstore_bundle_path}"
        ) from exc
    pair = build_evidence_object_pair(
        kind=kind,
        object_value=object_value,
        sigstore_bundle=raw_bundle,
        registry_source_commit=registry_source_commit,
        registry_revision=registry_revision,
        registry_head_sha256=registry_head_sha256,
    )
    for payload, reference in zip(pair.objects, pair.references, strict=True):
        _write_atomic(output_root / reference["object_path"], payload)
    references = [dict(reference) for reference in pair.references]
    _write_atomic(references_output, canonical_json_bytes(references))
    return pair.references


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    summary = commands.add_parser("summary", help="build a public lifecycle summary")
    summary.add_argument("--input", type=Path, required=True)
    summary.add_argument("--output", type=Path, required=True)
    summary.add_argument("--signer-registry", type=Path, required=True)
    summary.add_argument(
        "--qualification-evidence-decision-receipt", type=Path, required=True
    )
    summary.add_argument("--qualification-admission", type=Path, required=True)
    summary.add_argument(
        "--production-acceptance-manifest", type=Path, required=True
    )

    manifest = commands.add_parser(
        "manifest", help="build a public production-acceptance manifest"
    )
    manifest.add_argument("--input", type=Path, required=True)
    manifest.add_argument("--output", type=Path, required=True)
    manifest.add_argument(
        "--lifecycle-policy-repository", type=Path, required=True
    )
    manifest.add_argument("--lifecycle-policy-source-commit", required=True)
    manifest.add_argument("--signer-registry", type=Path, required=True)
    manifest.add_argument(
        "--qualification-evidence-decision-receipt", type=Path, required=True
    )
    manifest.add_argument("--qualification-admission", type=Path, required=True)

    pair = commands.add_parser("pair", help="build a content-addressed object pair")
    pair.add_argument("--kind", required=True)
    pair.add_argument("--object", type=Path, required=True)
    pair.add_argument("--sigstore-bundle", type=Path, required=True)
    pair.add_argument("--registry-source-commit", required=True)
    pair.add_argument("--registry-revision", type=int, required=True)
    pair.add_argument("--registry-head-sha256", required=True)
    pair.add_argument("--output-root", type=Path, required=True)
    pair.add_argument("--references-output", type=Path, required=True)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "summary":
            build_summary(
                args.input,
                args.output,
                signer_registry=args.signer_registry,
                qualification_evidence_decision_receipt=(
                    args.qualification_evidence_decision_receipt
                ),
                qualification_admission=args.qualification_admission,
                production_acceptance_manifest=args.production_acceptance_manifest,
            )
        elif args.command == "manifest":
            build_manifest(
                args.input,
                args.output,
                lifecycle_policy_repository=args.lifecycle_policy_repository,
                lifecycle_policy_source_commit=args.lifecycle_policy_source_commit,
                signer_registry=args.signer_registry,
                qualification_evidence_decision_receipt=(
                    args.qualification_evidence_decision_receipt
                ),
                qualification_admission=args.qualification_admission,
            )
        else:
            build_pair(
                kind=args.kind,
                object_path=args.object,
                sigstore_bundle_path=args.sigstore_bundle,
                registry_source_commit=args.registry_source_commit,
                registry_revision=args.registry_revision,
                registry_head_sha256=args.registry_head_sha256,
                output_root=args.output_root,
                references_output=args.references_output,
            )
    except ProductionEvidenceError as exc:
        raise SystemExit(f"production evidence refused: {exc}") from exc
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
