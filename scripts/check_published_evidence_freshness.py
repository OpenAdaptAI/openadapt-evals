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

Checks 1, 2 and 5 are offline and always run.  Checks 3 and 4 need PyPI: pass
``--current-version``/``--current-wheel-sha256`` to supply the release
out-of-band, or ``--offline`` to skip them.  A network failure is reported and
skipped rather than failing the build -- it is not evidence of drift.  Actual
drift always exits non-zero.
"""

from __future__ import annotations

import argparse
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
    print(
        f"Published evidence {entry['path']} is bound to the current "
        f"{package} release {entry['flow_version']}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
