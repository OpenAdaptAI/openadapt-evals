#!/usr/bin/env python3
"""Fail loudly when published evidence is pinned to a superseded engine release.

Public credibility rests on measured evidence, and every evidence set here is
bound to one exact ``openadapt-flow`` wheel.  When Flow ships a new release the
published numbers silently become claims about an engine nobody is running any
more -- the failure this check exists to catch.  It went unnoticed once already:
the comparison in ``docs/eval_results/current_flow_v1_16_1_local_20260718`` was
still the published result eight minor releases after it was measured.

What is checked, against ``docs/eval_results/PUBLISHED_EVIDENCE.json``:

1. Exactly one evidence set is marked ``current``.
2. Its directory exists and carries a ``results.json`` whose recorded Flow
   version and wheel digest match the manifest (the manifest cannot drift from
   the artifact it describes).
3. Its pinned version equals the newest non-yanked release on PyPI.
4. Its pinned wheel digest equals that release's published wheel digest.
5. Every ``superseded`` set names the set that replaced it.
6. Its verifier, result, replication, public-report, task/oracle, campaign,
   browser, and installed-dependency inventories are complete and exact.

Checks 1, 2, 5 and 6 are offline and always run.  Checks 3 and 4 need PyPI: pass
``--current-version``/``--current-wheel-sha256`` to supply the release
out-of-band, or ``--offline`` to skip them.  A network failure is reported and
skipped rather than failing the build -- it is not evidence of drift.  Actual
drift always exits non-zero.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = REPO_ROOT / "docs" / "eval_results" / "PUBLISHED_EVIDENCE.json"
PYPI_URL = "https://pypi.org/pypi/{package}/json"


class DriftError(Exception):
    """Published evidence no longer matches the current published release."""


def load_manifest(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def current_entry(manifest: dict[str, Any]) -> dict[str, Any]:
    """Return the single evidence set that must track the current release."""

    entries = manifest.get("evidence", [])
    current = [entry for entry in entries if entry.get("status") == "current"]
    if len(current) != 1:
        raise DriftError(
            f"expected exactly one evidence set with status 'current', found "
            f"{len(current)}: {[entry.get('path') for entry in current]}"
        )
    return current[0]


def check_superseded_links(manifest: dict[str, Any]) -> list[str]:
    """Every superseded set must name its replacement, which must exist."""

    paths = {entry.get("path") for entry in manifest.get("evidence", [])}
    problems: list[str] = []
    for entry in manifest.get("evidence", []):
        if entry.get("status") != "superseded":
            continue
        replacement = entry.get("superseded_by")
        if not replacement:
            problems.append(f"{entry.get('path')}: superseded but no superseded_by")
        elif replacement not in paths:
            problems.append(
                f"{entry.get('path')}: superseded_by {replacement!r} is not in the manifest"
            )
    return problems


def check_entry_matches_artifact(entry: dict[str, Any], repo_root: Path) -> list[str]:
    """The manifest must agree with the results.json it describes."""

    problems: list[str] = []
    directory = repo_root / entry["path"]
    if not directory.is_dir():
        return [f"{entry['path']}: evidence directory is missing"]
    results = directory / "results.json"
    if not results.is_file():
        return [f"{entry['path']}: results.json is missing"]
    document = json.loads(results.read_text(encoding="utf-8"))
    flow = document.get("source", {}).get("flow", {})
    recorded_version = flow.get("version")
    recorded_sha = flow.get("artifact", {}).get("sha256")
    if recorded_version != entry.get("flow_version"):
        problems.append(
            f"{entry['path']}: manifest pins flow_version "
            f"{entry.get('flow_version')!r} but results.json recorded "
            f"{recorded_version!r}"
        )
    if recorded_sha != entry.get("wheel_sha256"):
        problems.append(
            f"{entry['path']}: manifest pins wheel_sha256 "
            f"{entry.get('wheel_sha256')!r} but results.json recorded "
            f"{recorded_sha!r}"
        )
    return problems


def _safe_file(repo_root: Path, relative: object) -> Path | None:
    if not isinstance(relative, str):
        return None
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        return None
    candidate = repo_root / path
    return candidate if candidate.is_file() else None


def _relative_file(repo_root: Path, relative: object) -> tuple[Path | None, str | None]:
    """Return a safe file and its normalized repository-relative name."""

    path = _safe_file(repo_root, relative)
    if path is None:
        return None, None
    return path, path.relative_to(repo_root).as_posix()


def _validated_bindings(
    binding: dict[str, Any],
    key: str,
    repo_root: Path,
    *,
    require_sha256: bool = True,
) -> tuple[list[tuple[dict[str, Any], Path, str]], list[str]]:
    """Validate one non-empty, unique file-binding inventory."""

    raw = binding.get(key)
    if not isinstance(raw, list) or not raw:
        return [], [f"{key} must be a non-empty list"]
    values: list[tuple[dict[str, Any], Path, str]] = []
    problems: list[str] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            problems.append(f"{key} contains a malformed binding")
            continue
        path, normalized = _relative_file(repo_root, item.get("path"))
        if path is None or normalized is None:
            problems.append(f"{key} contains a missing or unsafe path: {item.get('path')!r}")
            continue
        if normalized in seen:
            problems.append(f"{key} contains a duplicate path: {normalized!r}")
            continue
        seen.add(normalized)
        if require_sha256 and item.get("sha256") != _sha256(path):
            problems.append(f"{key} digest changed: {normalized!r}")
            continue
        values.append((item, path, normalized))
    return values, problems


def _inventory_files(repo_root: Path, root: Path, suffix: str | None) -> set[str]:
    return {
        path.relative_to(repo_root).as_posix()
        for path in root.rglob("*")
        if path.is_file()
        and path.name != "EVIDENCE_MANIFEST.json"
        and (suffix is None or path.name.endswith(suffix))
    }


def _task_contract(document: dict[str, Any]) -> dict[str, Any]:
    """Return the claim-defining task and oracle fields from one result file."""

    keys = (
        "task",
        "oracle",
        "outcome_definitions",
        "trials_per_arm_condition",
        "arms",
        "conditions",
        "fault_modes",
        "verification_modes",
        "cells",
        "profiles",
    )
    return {key: document[key] for key in keys if key in document}


def check_evidence_manifest(entry: dict[str, Any], repo_root: Path) -> list[str]:
    """Verify the current result set is still the exact measurement set."""

    problems: list[str] = []
    manifest_path = _safe_file(repo_root, entry.get("evidence_manifest"))
    if manifest_path is None:
        return [f"{entry['path']}: evidence_manifest is missing or unsafe"]
    try:
        binding = load_manifest(manifest_path)
    except (OSError, json.JSONDecodeError) as exc:
        return [f"{entry['path']}: evidence_manifest cannot be read: {exc}"]
    prefix = f"{entry['path']}: "
    if binding.get("schema_version") != 2:
        problems.append(prefix + "evidence manifest schema_version must be 2")
    flow = binding.get("flow")
    if not isinstance(flow, dict):
        problems.append(f"{entry['path']}: evidence manifest flow binding is missing")
    else:
        for key, expected in (
            ("version", entry.get("flow_version")),
            ("wheel_sha256", entry.get("wheel_sha256")),
        ):
            if flow.get(key) != expected:
                problems.append(
                    f"{entry['path']}: evidence manifest flow {key} disagrees with PUBLISHED_EVIDENCE"
                )
    results_path = _safe_file(repo_root, f"{entry['path']}/results.json")
    if results_path is None:
        return problems + [f"{entry['path']}: results.json is missing"]
    evidence_root = repo_root / entry["path"]
    verifier_bindings, binding_problems = _validated_bindings(binding, "verifiers", repo_root)
    problems.extend(prefix + problem for problem in binding_problems)

    public_reports, binding_problems = _validated_bindings(binding, "public_reports", repo_root)
    problems.extend(prefix + problem for problem in binding_problems)
    bound_reports = {normalized for _, _, normalized in public_reports}
    actual_reports = _inventory_files(repo_root, evidence_root, ".md")
    if bound_reports != actual_reports:
        problems.append(
            prefix
            + "public_reports inventory differs from retained Markdown files: "
            + f"missing={sorted(actual_reports - bound_reports)}, extra={sorted(bound_reports - actual_reports)}"
        )

    artifacts, binding_problems = _validated_bindings(binding, "artifacts", repo_root)
    problems.extend(prefix + problem for problem in binding_problems)
    bound_artifacts = {normalized for _, _, normalized in artifacts}
    actual_artifacts = _inventory_files(repo_root, evidence_root, None) - actual_reports
    if bound_artifacts != actual_artifacts:
        problems.append(
            prefix
            + "artifacts inventory differs from retained JSON files: "
            + f"missing={sorted(actual_artifacts - bound_artifacts)}, extra={sorted(bound_artifacts - actual_artifacts)}"
        )

    campaigns = binding.get("campaigns")
    seen_results: set[str] = set()
    if not isinstance(campaigns, list) or not campaigns:
        problems.append(prefix + "campaigns must be a non-empty list")
    else:
        seen_campaigns: set[str] = set()
        verifier_paths = {normalized for _, _, normalized in verifier_bindings}
        for campaign in campaigns:
            if not isinstance(campaign, dict):
                problems.append(prefix + "campaigns contains a malformed binding")
                continue
            name = campaign.get("name")
            if not isinstance(name, str) or not name or name in seen_campaigns:
                problems.append(prefix + f"campaign name is missing or duplicate: {name!r}")
            else:
                seen_campaigns.add(name)
            result_path, normalized_result = _relative_file(repo_root, campaign.get("results_path"))
            if result_path is None or normalized_result is None:
                problems.append(
                    prefix
                    + f"campaign results path is missing or unsafe: {campaign.get('results_path')!r}"
                )
                continue
            if normalized_result in seen_results:
                problems.append(
                    prefix + f"campaign results path is duplicate: {normalized_result!r}"
                )
            seen_results.add(normalized_result)
            verifier_path = campaign.get("verifier_path")
            if verifier_path not in verifier_paths:
                problems.append(
                    prefix
                    + f"campaign verifier is not in the verifier inventory: {verifier_path!r}"
                )
            try:
                document = load_manifest(result_path)
            except (OSError, json.JSONDecodeError) as exc:
                problems.append(
                    prefix + f"campaign results cannot be read: {normalized_result!r}: {exc}"
                )
                continue
            if campaign.get("environment") != document.get("environment"):
                problems.append(prefix + f"campaign environment differs from {normalized_result!r}")
            runtime = campaign.get("runtime")
            required_runtime = {
                "python_version",
                "dependency_snapshot_filename",
                "dependency_snapshot_sha256",
                "openadapt_types_version",
            }
            if not isinstance(runtime, dict) or not required_runtime.issubset(runtime):
                problems.append(prefix + f"campaign runtime facts are incomplete: {name!r}")
            else:
                for field in required_runtime:
                    if (
                        not isinstance(runtime.get(field), str)
                        or not runtime[field]
                        or runtime[field].lower() in {"unknown", "not_recorded"}
                    ):
                        problems.append(
                            prefix + f"campaign runtime field is not exact: {name!r}.{field}"
                        )
                dependency_name = runtime.get("dependency_snapshot_filename")
                dependency_relative = (
                    Path(normalized_result).parent / dependency_name
                    if isinstance(dependency_name, str)
                    else None
                )
                dependency_path = _safe_file(
                    repo_root,
                    dependency_relative.as_posix() if dependency_relative is not None else None,
                )
                if dependency_path is None or runtime.get("dependency_snapshot_sha256") != _sha256(
                    dependency_path
                ):
                    problems.append(
                        prefix + f"campaign dependency snapshot changed or is missing: {name!r}"
                    )
                if "chromium" in document.get("environment", {}):
                    for field in ("browser_version", "browser_revision"):
                        if (
                            not isinstance(runtime.get(field), str)
                            or not runtime[field]
                            or runtime[field].lower() in {"unknown", "not_recorded"}
                        ):
                            problems.append(
                                prefix + f"browser runtime field is not exact: {name!r}.{field}"
                            )
            if runtime != document.get("runtime"):
                problems.append(prefix + f"campaign runtime differs from {normalized_result!r}")
        result_artifacts = {
            path
            for path in bound_artifacts
            if path.endswith("/results.json") or path == f"{entry['path']}/results.json"
        }
        if seen_results != result_artifacts:
            problems.append(
                prefix
                + "campaign results inventory differs from retained results: "
                + f"missing={sorted(result_artifacts - seen_results)}, extra={sorted(seen_results - result_artifacts)}"
            )
    contracts = binding.get("task_contracts")
    if not isinstance(contracts, list) or not contracts:
        problems.append(f"{entry['path']}: task_contracts are missing")
    else:
        seen_contracts: set[str] = set()
        for contract in contracts:
            if not isinstance(contract, dict):
                problems.append(f"{entry['path']}: malformed task contract")
                continue
            path = _safe_file(repo_root, contract.get("results_path"))
            if path is None:
                problems.append(f"{entry['path']}: task contract results file is missing")
                continue
            normalized = path.relative_to(repo_root).as_posix()
            if normalized in seen_contracts:
                problems.append(f"{entry['path']}: duplicate task contract: {normalized!r}")
                continue
            seen_contracts.add(normalized)
            try:
                actual = _task_contract(load_manifest(path))
            except (OSError, json.JSONDecodeError) as exc:
                problems.append(f"{entry['path']}: task contract results cannot be read: {exc}")
                continue
            if contract.get("value") != actual or contract.get("sha256") != _canonical_sha256(
                actual
            ):
                problems.append(
                    f"{entry['path']}: task or oracle contract changed: {contract.get('results_path')!r}"
                )
        if contracts and seen_contracts != seen_results:
            problems.append(
                prefix
                + "task contract inventory differs from campaign results: "
                + f"missing={sorted(seen_results - seen_contracts)}, extra={sorted(seen_contracts - seen_results)}"
            )
    return problems


def check_against_release(
    entry: dict[str, Any],
    release_version: str,
    release_wheel_sha256: Optional[str],
) -> list[str]:
    """The current evidence set must pin the current published release."""

    problems: list[str] = []
    if entry.get("flow_version") != release_version:
        problems.append(
            f"{entry['path']}: published evidence is pinned to openadapt-flow "
            f"{entry.get('flow_version')} but the current published release is "
            f"{release_version}. Re-run the comparison against "
            f"{release_version} and publish a new evidence set, or the public "
            f"numbers describe an engine nobody is running."
        )
    elif release_wheel_sha256 and entry.get("wheel_sha256") != release_wheel_sha256:
        problems.append(
            f"{entry['path']}: pinned wheel digest {entry.get('wheel_sha256')} "
            f"does not match the published {release_version} wheel digest "
            f"{release_wheel_sha256}"
        )
    return problems


def fetch_current_release(package: str, timeout: float = 20.0) -> tuple[str, Optional[str]]:
    """Return the newest non-yanked (version, wheel sha256) from PyPI."""

    with urllib.request.urlopen(PYPI_URL.format(package=package), timeout=timeout) as response:
        document = json.loads(response.read())
    version = document["info"]["version"]
    wheel_sha: Optional[str] = None
    for file_info in document.get("urls", []):
        if file_info.get("packagetype") == "bdist_wheel" and not file_info.get("yanked"):
            wheel_sha = file_info["digests"]["sha256"]
            break
    return version, wheel_sha


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Fail when published evidence drifts from the current published engine release."
    )
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--repo-root", type=Path, default=REPO_ROOT)
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Run only the offline consistency checks; do not query PyPI.",
    )
    parser.add_argument(
        "--current-version",
        help="Supply the current published release instead of querying PyPI.",
    )
    parser.add_argument(
        "--current-wheel-sha256",
        help="Supply the current published wheel digest instead of querying PyPI.",
    )
    args = parser.parse_args(argv)

    manifest = load_manifest(args.manifest)
    package = manifest.get("package", "openadapt-flow")
    problems: list[str] = []
    try:
        entry = current_entry(manifest)
    except DriftError as exc:
        print(f"DRIFT: {exc}", file=sys.stderr)
        return 1

    problems.extend(check_superseded_links(manifest))
    problems.extend(check_entry_matches_artifact(entry, args.repo_root))
    problems.extend(check_evidence_manifest(entry, args.repo_root))

    release_version = args.current_version
    release_wheel = args.current_wheel_sha256
    if release_version is None and not args.offline:
        try:
            release_version, release_wheel = fetch_current_release(package)
        except (urllib.error.URLError, TimeoutError, OSError, KeyError) as exc:
            # Unreachable PyPI is not evidence of drift; say so and continue.
            print(
                f"WARNING: could not query PyPI for {package} ({exc}); skipping "
                "the release-freshness comparison",
                file=sys.stderr,
            )
    if release_version is not None:
        problems.extend(check_against_release(entry, release_version, release_wheel))

    if problems:
        for problem in problems:
            print(f"DRIFT: {problem}", file=sys.stderr)
        return 1

    if release_version is None:
        # The release-freshness comparison did not run. Skipping it is
        # deliberate (see the module docstring) and the exit code stays 0, but
        # the message must not claim the binding was verified: in a CI log
        # where only the last line is read, that reads as a passing freshness
        # check when the check never happened.
        print(
            f"Published evidence {entry['path']} passed its OFFLINE checks. "
            f"The release-freshness comparison against the current {package} "
            f"release was SKIPPED" + (" (--offline)." if args.offline else " (PyPI unreachable).")
        )
        return 0

    print(
        f"Published evidence {entry['path']} is bound to the current "
        f"{package} release {entry['flow_version']}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
