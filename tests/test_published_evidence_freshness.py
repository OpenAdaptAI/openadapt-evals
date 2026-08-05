from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "check_published_evidence_freshness.py"
MANIFEST = ROOT / "docs" / "eval_results" / "PUBLISHED_EVIDENCE.json"
SPEC = importlib.util.spec_from_file_location("published_evidence_freshness", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_repo_manifest_is_internally_consistent() -> None:
    """The committed manifest must agree with the artifacts it describes.

    This is the offline half of the drift guard and needs no network, so it
    runs on every pull request.
    """

    assert MODULE.main(["--offline"]) == 0


def test_repo_manifest_keeps_old_evidence_stale_and_names_the_exact_rerun() -> None:
    manifest = MODULE.load_manifest(MANIFEST)
    current = MODULE.current_entry(manifest)
    old = next(item for item in manifest["evidence"] if item["flow_version"] == "1.28.0")
    assert current["flow_version"] == "1.30.0"
    assert old["status"] == "superseded"
    assert old["superseded_by"] == current["path"]
    assert "not relabeled" in old["stale_reason"]


def test_drift_is_detected_when_a_newer_release_is_published() -> None:
    manifest = MODULE.load_manifest(MANIFEST)
    entry = MODULE.current_entry(manifest)

    problems = MODULE.check_against_release(entry, "99.0.0", None)

    assert problems
    assert "99.0.0" in problems[0]


def test_no_drift_when_the_pinned_release_is_current() -> None:
    manifest = MODULE.load_manifest(MANIFEST)
    entry = MODULE.current_entry(manifest)

    problems = MODULE.check_against_release(entry, entry["flow_version"], entry["wheel_sha256"])

    assert problems == []


def test_a_republished_wheel_digest_is_drift() -> None:
    manifest = MODULE.load_manifest(MANIFEST)
    entry = MODULE.current_entry(manifest)

    problems = MODULE.check_against_release(entry, entry["flow_version"], "0" * 64)

    assert problems
    assert "digest" in problems[0]


def test_two_current_evidence_sets_are_refused() -> None:
    manifest = {
        "evidence": [
            {"path": "a", "status": "current"},
            {"path": "b", "status": "current"},
        ]
    }

    with pytest.raises(MODULE.DriftError, match="exactly one"):
        MODULE.current_entry(manifest)


def test_superseded_entry_must_name_an_existing_replacement() -> None:
    dangling = {
        "evidence": [
            {"path": "a", "status": "superseded", "superseded_by": "missing"},
            {"path": "b", "status": "current"},
        ]
    }

    problems = MODULE.check_superseded_links(dangling)

    assert problems and "not in the manifest" in problems[0]

    orphan = {"evidence": [{"path": "a", "status": "superseded"}]}
    assert "no superseded_by" in MODULE.check_superseded_links(orphan)[0]


def test_manifest_that_disagrees_with_its_artifact_is_drift(tmp_path: Path) -> None:
    directory = tmp_path / "docs" / "eval_results" / "set"
    directory.mkdir(parents=True)
    (directory / "results.json").write_text(
        json.dumps({"source": {"flow": {"version": "1.24.0", "artifact": {"sha256": "a" * 64}}}}),
        encoding="utf-8",
    )
    entry = {
        "path": "docs/eval_results/set",
        "flow_version": "1.16.1",
        "wheel_sha256": "a" * 64,
    }

    problems = MODULE.check_entry_matches_artifact(entry, tmp_path)

    assert problems and "results.json recorded" in problems[0]


def test_stale_evidence_names_the_runtime_facts_that_were_not_retained() -> None:
    manifest = MODULE.load_manifest(MANIFEST)
    entry = next(item for item in manifest["evidence"] if item["flow_version"] == "1.28.0")

    problems = MODULE.check_evidence_manifest(entry, ROOT)

    assert any("openadapt_types_version" in problem for problem in problems)
    assert any("browser_revision" in problem for problem in problems)
    assert any("dependency snapshot" in problem for problem in problems)


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True), encoding="utf-8")


def _valid_bound_evidence(tmp_path: Path) -> tuple[dict[str, object], Path, dict[str, object]]:
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    verifier = tmp_path / "scripts" / "verify.py"
    verifier.parent.mkdir()
    verifier.write_text("# independent verifier\n", encoding="utf-8")
    dependency_snapshot = evidence / "dependencies.json"
    _write_json(dependency_snapshot, {"openadapt-types": "0.9.0", "playwright": "1.61.0"})
    report = evidence / "REPORT.md"
    report.write_text("# Bound report\n", encoding="utf-8")
    result = evidence / "results.json"
    result_value = {
        "task": "write one record",
        "oracle": "independent record read",
        "environment": {
            "chromium": "Chromium 140.0.7339.16",
            "platform": "test-platform",
            "playwright": "1.61.0",
            "python": "3.12.13",
        },
        "source": {
            "evals": {"commit": "b" * 40},
            "runner_sha256": MODULE._sha256(verifier),
            "flow": {
                "version": "1.30.0",
                "artifact": {"sha256": "a" * 64},
            },
        },
        "runtime": {
            "python_version": "3.12.13",
            "openadapt_types_version": "0.9.0",
            "browser_version": "140.0.7339.16",
            "browser_revision": "1194",
            "dependency_snapshot_filename": "dependencies.json",
            "dependency_snapshot_sha256": MODULE._sha256(dependency_snapshot),
        },
    }
    _write_json(result, result_value)
    contract = MODULE._task_contract(result_value)
    binding: dict[str, object] = {
        "schema_version": 2,
        "evals_commit": "b" * 40,
        "flow": {"version": "1.30.0", "wheel_sha256": "a" * 64},
        "verifiers": [{"path": "scripts/verify.py", "sha256": MODULE._sha256(verifier)}],
        "campaigns": [
            {
                "name": "main",
                "results_path": "evidence/results.json",
                "verifier_path": "scripts/verify.py",
                "environment": result_value["environment"],
                "runtime": result_value["runtime"],
            }
        ],
        "task_contracts": [
            {
                "results_path": "evidence/results.json",
                "value": contract,
                "sha256": MODULE._canonical_sha256(contract),
            }
        ],
        "artifacts": [
            {"path": "evidence/dependencies.json", "sha256": MODULE._sha256(dependency_snapshot)},
            {"path": "evidence/results.json", "sha256": MODULE._sha256(result)},
        ],
        "public_reports": [{"path": "evidence/REPORT.md", "sha256": MODULE._sha256(report)}],
    }
    manifest_path = evidence / "EVIDENCE_MANIFEST.json"
    _write_json(manifest_path, binding)
    entry: dict[str, object] = {
        "path": "evidence",
        "status": "current",
        "flow_version": "1.30.0",
        "wheel_sha256": "a" * 64,
        "evidence_manifest": "evidence/EVIDENCE_MANIFEST.json",
    }
    return entry, manifest_path, binding


def test_complete_evidence_binding_passes(tmp_path: Path) -> None:
    entry, _, _ = _valid_bound_evidence(tmp_path)

    assert MODULE.check_evidence_manifest(entry, tmp_path) == []


@pytest.mark.parametrize(
    ("mutation", "expected"),
    [
        (lambda value: value.__setitem__("verifiers", []), "verifiers must be a non-empty list"),
        (
            lambda value: value["artifacts"].append(dict(value["artifacts"][0])),
            "duplicate path",
        ),
        (lambda value: value["artifacts"].pop(), "artifacts inventory differs"),
        (lambda value: value.__setitem__("public_reports", []), "public_reports must be"),
        (
            lambda value: value["verifiers"][0].__setitem__("path", "../outside.py"),
            "unsafe path",
        ),
        (
            lambda value: value["campaigns"][0]["runtime"].__setitem__(
                "browser_revision", "not_recorded"
            ),
            "browser_revision",
        ),
        (
            lambda value: value["campaigns"][0].__setitem__("environment", {}),
            "campaign environment differs",
        ),
        (
            lambda value: value.__setitem__("evals_commit", "c" * 40),
            "campaign evals commit differs",
        ),
        (
            lambda value: value["task_contracts"].append(dict(value["task_contracts"][0])),
            "duplicate task contract",
        ),
    ],
)
def test_evidence_binding_refuses_omission_duplication_and_unsafe_paths(
    tmp_path: Path,
    mutation: object,
    expected: str,
) -> None:
    entry, manifest_path, binding = _valid_bound_evidence(tmp_path)
    mutation(binding)
    _write_json(manifest_path, binding)

    problems = MODULE.check_evidence_manifest(entry, tmp_path)

    assert any(expected in problem for problem in problems)


@pytest.mark.parametrize(
    "path",
    [
        "scripts/verify.py",
        "evidence/results.json",
        "evidence/dependencies.json",
        "evidence/REPORT.md",
    ],
)
def test_evidence_binding_refuses_any_bound_file_mutation(tmp_path: Path, path: str) -> None:
    entry, _, _ = _valid_bound_evidence(tmp_path)
    target = tmp_path / path
    target.write_bytes(target.read_bytes() + b"tampered")

    assert MODULE.check_evidence_manifest(entry, tmp_path)
