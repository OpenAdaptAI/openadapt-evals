from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from openadapt_evals import production_evidence as evidence

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_production_evidence.py"
SPEC = importlib.util.spec_from_file_location("build_production_evidence", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _digest(character: str) -> str:
    return "sha256:" + character * 64


def test_pair_command_writes_exact_content_addressed_paths(tmp_path: Path) -> None:
    regular = tmp_path / "admission.json"
    raw_bundle = tmp_path / "admission.sigstore.json"
    output_root = tmp_path / "registry"
    references_output = tmp_path / "references.json"
    regular.write_text(
        json.dumps(
            {
                "schema_version": "openadapt.qualification-admission/v3",
                "verdict": "ADMIT",
            }
        ),
        encoding="utf-8",
    )
    bundle_bytes = b'{ "mediaType": "application/vnd.dev.sigstore.bundle.v0.3+json" }\n'
    raw_bundle.write_bytes(bundle_bytes)

    regular_reference, bundle_reference = MODULE.build_pair(
        kind="qualification-admission",
        object_path=regular,
        sigstore_bundle_path=raw_bundle,
        registry_source_commit="a" * 40,
        registry_revision=12,
        registry_head_sha256=_digest("b"),
        output_root=output_root,
        references_output=references_output,
    )

    assert (output_root / regular_reference["object_path"]).read_bytes() == (
        evidence.canonical_json_bytes(json.loads(regular.read_text(encoding="utf-8")))
    )
    assert (output_root / bundle_reference["object_path"]).read_bytes() == bundle_bytes
    assert json.loads(references_output.read_text(encoding="utf-8")) == [
        regular_reference,
        bundle_reference,
    ]
    evidence.validate_reference_pair(
        (regular_reference, bundle_reference),
        expected_regular_kind="qualification-admission",
    )


def test_pair_command_refuses_to_replace_different_evidence(tmp_path: Path) -> None:
    path = tmp_path / "evidence.json"
    path.write_bytes(b"old")
    with pytest.raises(evidence.ProductionEvidenceError, match="refusing to replace"):
        MODULE._write_atomic(path, b"new")


def test_json_reader_rejects_duplicate_keys_and_floats(tmp_path: Path) -> None:
    duplicate = tmp_path / "duplicate.json"
    duplicate.write_text('{"schema_version":"one","schema_version":"two"}', encoding="utf-8")
    with pytest.raises(evidence.ProductionEvidenceError, match="duplicate key"):
        MODULE._read_json_object(duplicate, "test object")

    floating = tmp_path / "float.json"
    floating.write_text('{"size":1.5}', encoding="utf-8")
    with pytest.raises(evidence.ProductionEvidenceError, match="floating-point"):
        MODULE._read_json_object(floating, "test object")
