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


def test_repo_manifest_names_exactly_one_current_evidence_set() -> None:
    manifest = MODULE.load_manifest(MANIFEST)

    entry = MODULE.current_entry(manifest)

    assert entry["status"] == "current"
    assert (ROOT / entry["path"]).is_dir()


def test_repo_manifest_keeps_the_flow_1_26_oracle_migration_gate() -> None:
    manifest = MODULE.load_manifest(MANIFEST)

    assert MODULE.check_contract_policy(manifest) == []


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


def test_flow_1_26_evidence_requires_the_version_bound_oracle_schema(
    tmp_path: Path,
) -> None:
    directory = tmp_path / "docs" / "eval_results" / "set"
    directory.mkdir(parents=True)
    (directory / "results.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "source": {
                    "flow": {
                        "version": "1.26.0",
                        "artifact": {"sha256": "a" * 64},
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    entry = {
        "path": "docs/eval_results/set",
        "flow_version": "1.26.0",
        "wheel_sha256": "a" * 64,
    }

    problems = MODULE.check_entry_matches_artifact(
        entry,
        tmp_path,
        {
            "effective_flow_version": "1.26.0",
            "minimum_results_schema": 2,
        },
    )

    assert any("version-bound oracle contract" in problem for problem in problems)
