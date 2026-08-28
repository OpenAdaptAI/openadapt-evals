#!/usr/bin/env python3
"""Build and verify the durable GitHub draft used for one Evals release."""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import re
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

REPOSITORY = "OpenAdaptAI/openadapt-evals"
SCHEMA = "openadapt.evals-release-draft/v1"
BODY_HEADER = "<!-- openadapt.evals-release-draft/v1"
BODY_FOOTER = "-->"
IMMUTABLE_RELEASES_DIGEST_DOMAIN = b"OpenAdapt production immutable releases response v1\0"
TAG_REF_STATE_DIGEST_DOMAIN = b"OpenAdapt production release tag ref state v1\0"
TAG_RULESETS_DIGEST_DOMAIN = b"OpenAdapt production release tag rulesets v1\0"
TAG_RULESET_SCHEMA = "openadapt.production-release-tag-ruleset/v1"
RELEASE_APP_LOGIN = "openadapt-release[bot]"
RELEASE_APP_ID = 4730708
RELEASE_APP_BOT_USER_ID = 321543906
REPOSITORY_ID = "1135998197"
MAX_ARTIFACT_BYTES = 256 * 1024 * 1024
STABLE_VERSION = re.compile(r"^(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$")
HEX40 = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^sha256:[0-9a-f]{64}$")
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,199}$")
MANIFEST_KEYS = frozenset(
    {
        "schema_version",
        "repository",
        "version",
        "tag",
        "source_commit",
        "tag_ref_state",
        "tag_ref_state_sha256",
        "immutable_releases",
        "immutable_releases_sha256",
        "tag_rulesets",
        "tag_rulesets_sha256",
        "artifacts",
    }
)
SETTINGS_KEYS = frozenset({"enabled", "enforced_by_owner"})
NORMALIZED_RULESET_KEYS = frozenset(
    {
        "schema_version",
        "role",
        "repository",
        "repository_id",
        "ruleset_id",
        "name",
        "target",
        "enforcement",
        "bypass_actors",
        "conditions",
        "rules",
    }
)


class StagingError(RuntimeError):
    """The staged release differs from the reviewed release candidate."""


def _object_without_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise StagingError(f"JSON object contains a duplicate key: {key}")
        value[key] = item
    return value


def _decode_json(body: bytes | str, context: str) -> object:
    try:
        return json.loads(body, object_pairs_hook=_object_without_duplicate_keys)
    except StagingError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StagingError(f"{context} is not valid JSON") from exc


def canonical_json_bytes(value: object) -> bytes:
    """Return the one JSON byte representation used by release digests."""

    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_hex(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_digest(value: bytes) -> str:
    return "sha256:" + sha256_hex(value)


def _read_object(path: Path, context: str) -> dict[str, Any]:
    try:
        value = _decode_json(path.read_bytes(), context)
    except OSError as exc:
        raise StagingError(f"{context} cannot be read: {path}") from exc
    if not isinstance(value, dict):
        raise StagingError(f"{context} must be a JSON object")
    return value


def _read_array(path: Path, context: str) -> list[Any]:
    try:
        value = _decode_json(path.read_bytes(), context)
    except OSError as exc:
        raise StagingError(f"{context} cannot be read: {path}") from exc
    if not isinstance(value, list):
        raise StagingError(f"{context} must be a JSON array")
    return value


def validate_immutable_releases(value: object) -> dict[str, bool]:
    """Accept only the documented repository immutable-release response."""

    if not isinstance(value, Mapping) or set(value) != SETTINGS_KEYS:
        raise StagingError(
            "immutable releases response must contain only enabled and enforced_by_owner"
        )
    if value["enabled"] is not True or not isinstance(value["enforced_by_owner"], bool):
        raise StagingError(
            "immutable releases must be enabled and enforced_by_owner must be a boolean"
        )
    return {
        "enabled": True,
        "enforced_by_owner": value["enforced_by_owner"],
    }


def immutable_releases_digest(settings: Mapping[str, bool]) -> str:
    return sha256_digest(IMMUTABLE_RELEASES_DIGEST_DOMAIN + canonical_json_bytes(dict(settings)))


def tag_ref_state(tag: str) -> dict[str, object]:
    return {"ref": f"refs/tags/{tag}", "exists": False}


def tag_ref_state_digest(value: Mapping[str, object]) -> str:
    return sha256_digest(TAG_REF_STATE_DIGEST_DOMAIN + canonical_json_bytes(dict(value)))


def _string_list(value: object, context: str) -> list[str]:
    if (
        isinstance(value, (str, bytes))
        or not isinstance(value, Sequence)
        or any(not isinstance(item, str) or not item for item in value)
    ):
        raise StagingError(f"{context} must be an array of non-empty strings")
    normalized = sorted(set(value))
    if len(normalized) != len(value):
        raise StagingError(f"{context} contains a duplicate value")
    return normalized


def _normalized_conditions(value: object, tag: str) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) != {"ref_name"}:
        raise StagingError("tag ruleset conditions must contain only ref_name")
    ref_name = value["ref_name"]
    if not isinstance(ref_name, Mapping) or set(ref_name) != {"include", "exclude"}:
        raise StagingError("tag ruleset ref_name conditions are invalid")
    include = _string_list(ref_name["include"], "tag ruleset include patterns")
    exclude = _string_list(ref_name["exclude"], "tag ruleset exclude patterns")
    candidates = (tag, f"refs/tags/{tag}")
    if not any(
        fnmatch.fnmatchcase(candidate, pattern) for pattern in include for candidate in candidates
    ):
        raise StagingError("tag ruleset does not include the exact release tag")
    if any(
        fnmatch.fnmatchcase(candidate, pattern) for pattern in exclude for candidate in candidates
    ):
        raise StagingError("tag ruleset excludes the exact release tag")
    return {"ref_name": {"include": include, "exclude": exclude}}


def _normalized_bypass_actors(value: object) -> list[dict[str, object]]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise StagingError("tag ruleset bypass actors must be an array")
    actors: list[dict[str, object]] = []
    for actor in value:
        if not isinstance(actor, Mapping):
            raise StagingError("tag ruleset bypass actor is invalid")
        actor_id = actor.get("actor_id")
        actor_type = actor.get("actor_type")
        bypass_mode = actor.get("bypass_mode")
        if (
            isinstance(actor_id, bool)
            or not isinstance(actor_id, int)
            or actor_id <= 0
            or not isinstance(actor_type, str)
            or not actor_type
            or not isinstance(bypass_mode, str)
            or not bypass_mode
        ):
            raise StagingError("tag ruleset bypass actor fields are invalid")
        actors.append(
            {
                "actor_id": str(actor_id),
                "actor_type": actor_type,
                "bypass_mode": bypass_mode,
            }
        )
    return sorted(
        actors,
        key=lambda actor: (
            str(actor["actor_type"]),
            str(actor["actor_id"]),
            str(actor["bypass_mode"]),
        ),
    )


def normalize_tag_rulesets(value: object, *, tag: str) -> list[dict[str, object]]:
    """Select and normalize the two active rulesets that protect one release tag."""

    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise StagingError("repository tag ruleset details must be an array")
    candidates: dict[str, list[dict[str, object]]] = {
        "creation_authority": [],
        "immutability": [],
    }
    for raw in value:
        if not isinstance(raw, Mapping) or raw.get("target") != "tag":
            continue
        try:
            conditions = _normalized_conditions(raw.get("conditions"), tag)
        except StagingError as exc:
            if "exact release tag" in str(exc):
                continue
            raise
        raw_rules = raw.get("rules")
        if isinstance(raw_rules, (str, bytes)) or not isinstance(raw_rules, Sequence):
            raise StagingError("tag ruleset rules must be an array")
        rule_types = _string_list(
            [rule.get("type") if isinstance(rule, Mapping) else None for rule in raw_rules],
            "tag ruleset rule types",
        )
        role: str | None = None
        if rule_types == ["creation"]:
            role = "creation_authority"
        elif rule_types == ["deletion", "non_fast_forward", "update"]:
            role = "immutability"
        bypass_actors = _normalized_bypass_actors(raw.get("bypass_actors", []))
        if role is None:
            if bypass_actors:
                raise StagingError("a matching tag ruleset contains an unapproved bypass actor")
            continue
        if raw.get("enforcement") != "active":
            raise StagingError(f"the {role} tag ruleset is not active")
        expected_bypass = (
            [
                {
                    "actor_id": str(RELEASE_APP_ID),
                    "actor_type": "Integration",
                    "bypass_mode": "always",
                }
            ]
            if role == "creation_authority"
            else []
        )
        if bypass_actors != expected_bypass:
            raise StagingError(f"the {role} tag ruleset bypass actors are invalid")
        ruleset_id = raw.get("id")
        name = raw.get("name")
        if (
            isinstance(ruleset_id, bool)
            or not isinstance(ruleset_id, int)
            or ruleset_id <= 0
            or not isinstance(name, str)
            or not name
        ):
            raise StagingError(f"the {role} tag ruleset identity is invalid")
        candidates[role].append(
            {
                "schema_version": TAG_RULESET_SCHEMA,
                "role": role,
                "repository": REPOSITORY,
                "repository_id": REPOSITORY_ID,
                "ruleset_id": str(ruleset_id),
                "name": name,
                "target": "tag",
                "enforcement": "active",
                "bypass_actors": bypass_actors,
                "conditions": conditions,
                "rules": [{"type": rule_type} for rule_type in rule_types],
            }
        )
    for role, matches in candidates.items():
        if len(matches) != 1:
            raise StagingError(f"expected exactly one active {role} tag ruleset")
    return [candidates["creation_authority"][0], candidates["immutability"][0]]


def validate_tag_rulesets(value: object, *, tag: str) -> list[dict[str, object]]:
    if isinstance(value, (str, bytes)) or not isinstance(value, Sequence):
        raise StagingError("normalized tag rulesets must be an array")
    rulesets = [dict(item) if isinstance(item, Mapping) else {} for item in value]
    if [item.get("role") for item in rulesets] != [
        "creation_authority",
        "immutability",
    ]:
        raise StagingError("normalized tag ruleset roles or order are invalid")
    raw_api: list[dict[str, object]] = []
    for item in rulesets:
        if set(item) != NORMALIZED_RULESET_KEYS:
            raise StagingError("normalized tag ruleset keys are invalid")
        if (
            item["schema_version"] != TAG_RULESET_SCHEMA
            or item["repository"] != REPOSITORY
            or item["repository_id"] != REPOSITORY_ID
            or item["target"] != "tag"
            or item["enforcement"] != "active"
            or not isinstance(item["ruleset_id"], str)
            or not item["ruleset_id"].isdigit()
            or int(item["ruleset_id"]) <= 0
            or not isinstance(item["name"], str)
            or not item["name"]
        ):
            raise StagingError("normalized tag ruleset identity is invalid")
        role = str(item["role"])
        expected_bypass = (
            [
                {
                    "actor_id": str(RELEASE_APP_ID),
                    "actor_type": "Integration",
                    "bypass_mode": "always",
                }
            ]
            if role == "creation_authority"
            else []
        )
        expected_rules = (
            [{"type": "creation"}]
            if role == "creation_authority"
            else [
                {"type": "deletion"},
                {"type": "non_fast_forward"},
                {"type": "update"},
            ]
        )
        if item["bypass_actors"] != expected_bypass:
            raise StagingError(f"the normalized {role} bypass actors are invalid")
        if item["rules"] != expected_rules:
            raise StagingError(f"the normalized {role} rules are invalid")
        if _normalized_conditions(item["conditions"], tag) != item["conditions"]:
            raise StagingError(f"the normalized {role} conditions are invalid")
        raw_api.append(
            {
                "id": int(item["ruleset_id"]),
                "name": item["name"],
                "target": item["target"],
                "enforcement": item["enforcement"],
                "bypass_actors": [
                    {
                        "actor_id": int(actor["actor_id"]),
                        "actor_type": actor["actor_type"],
                        "bypass_mode": actor["bypass_mode"],
                    }
                    for actor in item["bypass_actors"]
                ],
                "conditions": item["conditions"],
                "rules": item["rules"],
            }
        )
    if normalize_tag_rulesets(raw_api, tag=tag) != rulesets:
        raise StagingError("normalized tag rulesets differ from their closed contract")
    return rulesets


def tag_rulesets_digest(value: Sequence[Mapping[str, object]]) -> str:
    return sha256_digest(
        TAG_RULESETS_DIGEST_DOMAIN + canonical_json_bytes([dict(ruleset) for ruleset in value])
    )


def _artifact(path: Path, version: str) -> dict[str, object]:
    if not path.is_file() or path.is_symlink() or SAFE_NAME.fullmatch(path.name) is None:
        raise StagingError(f"release artifact is not a regular safe file: {path}")
    if path.name.endswith(".whl"):
        kind = "wheel"
        media_type = "application/zip"
        if path.name != f"openadapt_evals-{version}-py3-none-any.whl":
            raise StagingError("wheel filename does not identify the requested version")
    elif path.name.endswith(".tar.gz"):
        kind = "sdist"
        media_type = "application/gzip"
        if path.name != f"openadapt_evals-{version}.tar.gz":
            raise StagingError("sdist filename does not identify the requested version")
    else:
        raise StagingError(f"unexpected release artifact: {path.name}")
    body = path.read_bytes()
    if not body:
        raise StagingError(f"release artifact is empty: {path.name}")
    if len(body) > MAX_ARTIFACT_BYTES:
        raise StagingError(f"release artifact exceeds the size limit: {path.name}")
    return {
        "name": path.name,
        "kind": kind,
        "sha256": sha256_digest(body),
        "size_bytes": len(body),
        "media_type": media_type,
        "publish_destinations": ["github-release", "pypi"],
    }


def inventory(directory: Path, version: str) -> list[dict[str, object]]:
    if not directory.is_dir() or directory.is_symlink():
        raise StagingError(f"release artifact directory is invalid: {directory}")
    artifacts = [_artifact(path, version) for path in sorted(directory.iterdir())]
    if len(artifacts) != 2 or {artifact["kind"] for artifact in artifacts} != {
        "wheel",
        "sdist",
    }:
        raise StagingError("release must contain exactly one wheel and one sdist")
    return artifacts


def build_manifest(
    *,
    directory: Path,
    version: str,
    tag: str,
    source_commit: str,
    immutable_releases: object,
    tag_rulesets: object,
) -> dict[str, object]:
    if STABLE_VERSION.fullmatch(version) is None or tag != f"v{version}":
        raise StagingError("version and tag must identify the same stable release")
    if HEX40.fullmatch(source_commit) is None:
        raise StagingError("source commit must be a full lowercase commit ID")
    settings = validate_immutable_releases(immutable_releases)
    tag_state = tag_ref_state(tag)
    normalized_rulesets = validate_tag_rulesets(tag_rulesets, tag=tag)
    return {
        "schema_version": SCHEMA,
        "repository": REPOSITORY,
        "version": version,
        "tag": tag,
        "source_commit": source_commit,
        "tag_ref_state": tag_state,
        "tag_ref_state_sha256": tag_ref_state_digest(tag_state),
        "immutable_releases": settings,
        "immutable_releases_sha256": immutable_releases_digest(settings),
        "tag_rulesets": normalized_rulesets,
        "tag_rulesets_sha256": tag_rulesets_digest(normalized_rulesets),
        "artifacts": inventory(directory, version),
    }


def validate_manifest(
    value: object,
    *,
    directory: Path,
    version: str,
    tag: str,
    source_commit: str,
    immutable_releases: object,
    tag_rulesets: object,
) -> dict[str, object]:
    manifest = validate_manifest_metadata(
        value,
        version=version,
        tag=tag,
        source_commit=source_commit,
        immutable_releases=immutable_releases,
        tag_rulesets=tag_rulesets,
    )
    if manifest["artifacts"] != inventory(directory, version):
        raise StagingError("draft artifact inventory differs from the exact files")
    return manifest


def validate_manifest_metadata(
    value: object,
    *,
    version: str,
    tag: str,
    source_commit: str,
    immutable_releases: object,
    tag_rulesets: object,
) -> dict[str, object]:
    if not isinstance(value, Mapping) or set(value) != MANIFEST_KEYS:
        raise StagingError("draft manifest keys are invalid")
    if STABLE_VERSION.fullmatch(version) is None or tag != f"v{version}":
        raise StagingError("version and tag must identify the same stable release")
    if HEX40.fullmatch(source_commit) is None:
        raise StagingError("source commit must be a full lowercase commit ID")
    settings = validate_immutable_releases(immutable_releases)
    expected_tag_state = tag_ref_state(tag)
    normalized_rulesets = validate_tag_rulesets(tag_rulesets, tag=tag)
    manifest = dict(value)
    if (
        manifest["schema_version"] != SCHEMA
        or manifest["repository"] != REPOSITORY
        or manifest["version"] != version
        or manifest["tag"] != tag
        or manifest["source_commit"] != source_commit
        or manifest["tag_ref_state"] != expected_tag_state
        or manifest["tag_ref_state_sha256"] != tag_ref_state_digest(expected_tag_state)
        or manifest["immutable_releases"] != settings
        or manifest["immutable_releases_sha256"] != immutable_releases_digest(settings)
        or manifest["tag_rulesets"] != normalized_rulesets
        or manifest["tag_rulesets_sha256"] != tag_rulesets_digest(normalized_rulesets)
    ):
        raise StagingError("draft manifest identity or protection evidence differs")
    raw_artifacts = manifest["artifacts"]
    if isinstance(raw_artifacts, (str, bytes)) or not isinstance(raw_artifacts, Sequence):
        raise StagingError("draft artifact inventory is invalid")
    artifacts: list[dict[str, object]] = []
    names: set[str] = set()
    for position, raw_artifact in enumerate(raw_artifacts):
        if not isinstance(raw_artifact, Mapping) or set(raw_artifact) != {
            "name",
            "kind",
            "sha256",
            "size_bytes",
            "media_type",
            "publish_destinations",
        }:
            raise StagingError(f"draft artifact {position} keys are invalid")
        artifact = dict(raw_artifact)
        name = artifact["name"]
        if not isinstance(name, str) or SAFE_NAME.fullmatch(name) is None or name in names:
            raise StagingError(f"draft artifact {position} name is invalid or duplicated")
        names.add(name)
        if name.endswith(".whl"):
            expected_kind = "wheel"
            expected_media_type = "application/zip"
            valid_name = name == f"openadapt_evals-{version}-py3-none-any.whl"
        elif name.endswith(".tar.gz"):
            expected_kind = "sdist"
            expected_media_type = "application/gzip"
            valid_name = name == f"openadapt_evals-{version}.tar.gz"
        else:
            raise StagingError(f"draft artifact {position} file type is invalid")
        size = artifact["size_bytes"]
        if (
            not valid_name
            or artifact["kind"] != expected_kind
            or artifact["media_type"] != expected_media_type
            or artifact["publish_destinations"] != ["github-release", "pypi"]
            or not isinstance(artifact["sha256"], str)
            or SHA256.fullmatch(artifact["sha256"]) is None
            or isinstance(size, bool)
            or not isinstance(size, int)
            or size <= 0
            or size > MAX_ARTIFACT_BYTES
        ):
            raise StagingError(f"draft artifact {position} contract is invalid")
        artifacts.append(artifact)
    if len(artifacts) != 2 or {artifact["kind"] for artifact in artifacts} != {
        "wheel",
        "sdist",
    }:
        raise StagingError("draft must contain exactly one wheel and one sdist")
    if artifacts != sorted(artifacts, key=lambda artifact: str(artifact["name"])):
        raise StagingError("draft artifacts are not sorted by name")
    manifest["artifacts"] = artifacts
    return manifest


def render_body(manifest: Mapping[str, object]) -> str:
    return f"{BODY_HEADER}\n{canonical_json_bytes(dict(manifest)).decode('utf-8')}\n{BODY_FOOTER}\n"


def parse_body(body: object) -> dict[str, Any]:
    if not isinstance(body, str):
        raise StagingError("draft release body is not text")
    prefix = f"{BODY_HEADER}\n"
    suffix = f"\n{BODY_FOOTER}\n"
    if not body.startswith(prefix) or not body.endswith(suffix):
        raise StagingError("draft release body does not contain the exact staging envelope")
    encoded = body[len(prefix) : -len(suffix)]
    value = _decode_json(encoded, "draft release body staging JSON")
    if not isinstance(value, dict) or encoded.encode("utf-8") != canonical_json_bytes(value):
        raise StagingError("draft release body is not canonical JSON")
    return value


def _positive_integer(value: object, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise StagingError(f"{context} must be a positive integer")
    return value


def _validate_release_assets(
    assets: object,
    *,
    expected: Sequence[Mapping[str, object]],
    allow_missing_assets: bool,
) -> list[dict[str, Any]]:
    if isinstance(assets, (str, bytes)) or not isinstance(assets, Sequence):
        raise StagingError("draft release asset inventory is invalid")
    expected_by_name = {str(artifact["name"]): artifact for artifact in expected}
    seen: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for position, raw_asset in enumerate(assets):
        if not isinstance(raw_asset, Mapping):
            raise StagingError(f"draft release asset {position} is invalid")
        asset = dict(raw_asset)
        name = asset.get("name")
        if not isinstance(name, str) or name in seen or name not in expected_by_name:
            raise StagingError(f"draft release has an unexpected or duplicate asset: {name!r}")
        seen.add(name)
        expected_asset = expected_by_name[name]
        uploader = asset.get("uploader")
        if not isinstance(uploader, Mapping):
            raise StagingError(f"draft release asset uploader is absent: {name}")
        if (
            uploader.get("login") != RELEASE_APP_LOGIN
            or uploader.get("id") != RELEASE_APP_BOT_USER_ID
        ):
            raise StagingError(f"draft release asset uploader differs: {name}")
        digest = asset.get("digest")
        if digest != expected_asset["sha256"]:
            raise StagingError(f"draft release asset digest differs: {name}")
        if (
            asset.get("state") != "uploaded"
            or asset.get("size") != expected_asset["size_bytes"]
            or asset.get("content_type") != expected_asset["media_type"]
        ):
            raise StagingError(f"draft release asset metadata differs: {name}")
        _positive_integer(asset.get("id"), f"draft release asset ID for {name}")
        normalized.append(asset)
    if not allow_missing_assets and seen != set(expected_by_name):
        raise StagingError("draft release does not contain the complete artifact set")
    return normalized


def validate_release(
    release: object,
    *,
    directory: Path,
    version: str,
    tag: str,
    source_commit: str,
    immutable_releases: object,
    tag_rulesets: object,
    allow_missing_assets: bool = False,
    published: bool = False,
) -> dict[str, object]:
    manifest = validate_release_metadata(
        release,
        version=version,
        tag=tag,
        source_commit=source_commit,
        immutable_releases=immutable_releases,
        tag_rulesets=tag_rulesets,
        allow_missing_assets=allow_missing_assets,
        published=published,
    )
    if manifest["artifacts"] != inventory(directory, version):
        raise StagingError("draft artifact inventory differs from the exact files")
    return manifest


def validate_release_metadata(
    release: object,
    *,
    version: str,
    tag: str,
    source_commit: str,
    immutable_releases: object,
    tag_rulesets: object,
    allow_missing_assets: bool = False,
    published: bool = False,
) -> dict[str, object]:
    if not isinstance(release, Mapping):
        raise StagingError("draft release response must be an object")
    value = dict(release)
    author = value.get("author")
    if not isinstance(author, Mapping):
        raise StagingError("draft release author is absent")
    if author.get("login") != RELEASE_APP_LOGIN or author.get("id") != RELEASE_APP_BOT_USER_ID:
        raise StagingError("draft release author differs from the release App")
    expected_draft = not published
    if (
        value.get("tag_name") != tag
        or value.get("target_commitish") != source_commit
        or value.get("name") != tag
        or value.get("draft") is not expected_draft
        or value.get("prerelease") is not False
        or (published and value.get("immutable") is not True)
    ):
        raise StagingError("draft release identity or state differs")
    _positive_integer(value.get("id"), "draft release ID")
    manifest = validate_manifest_metadata(
        parse_body(value.get("body")),
        version=version,
        tag=tag,
        source_commit=source_commit,
        immutable_releases=immutable_releases,
        tag_rulesets=tag_rulesets,
    )
    _validate_release_assets(
        value.get("assets"),
        expected=manifest["artifacts"],  # type: ignore[arg-type]
        allow_missing_assets=allow_missing_assets,
    )
    return manifest


def _write_json(path: Path, value: object) -> None:
    path.write_bytes(canonical_json_bytes(value) + b"\n")


def _prepare(arguments: argparse.Namespace) -> None:
    settings = _read_object(arguments.immutable_releases, "immutable releases response")
    rulesets = _read_array(arguments.tag_rulesets, "normalized release tag rulesets")
    manifest = build_manifest(
        directory=arguments.directory,
        version=arguments.version,
        tag=arguments.tag,
        source_commit=arguments.source_commit,
        immutable_releases=settings,
        tag_rulesets=rulesets,
    )
    _write_json(arguments.manifest_output, manifest)
    body = render_body(manifest)
    arguments.body_output.write_text(body, encoding="utf-8")
    request = {
        "tag_name": arguments.tag,
        "target_commitish": arguments.source_commit,
        "name": arguments.tag,
        "body": body,
        "draft": True,
        "prerelease": False,
        "generate_release_notes": False,
        "make_latest": "legacy",
    }
    _write_json(arguments.request_output, request)


def _verify(arguments: argparse.Namespace) -> None:
    settings = _read_object(arguments.immutable_releases, "immutable releases response")
    rulesets = _read_array(arguments.tag_rulesets, "normalized release tag rulesets")
    release = _read_object(arguments.release, "draft release response")
    validate_release(
        release,
        directory=arguments.directory,
        version=arguments.version,
        tag=arguments.tag,
        source_commit=arguments.source_commit,
        immutable_releases=settings,
        tag_rulesets=rulesets,
        allow_missing_assets=arguments.allow_missing_assets,
        published=arguments.published,
    )


def _inspect(arguments: argparse.Namespace) -> None:
    settings = _read_object(arguments.immutable_releases, "immutable releases response")
    rulesets = _read_array(arguments.tag_rulesets, "normalized release tag rulesets")
    release = _read_object(arguments.release, "draft release response")
    validate_release_metadata(
        release,
        version=arguments.version,
        tag=arguments.tag,
        source_commit=arguments.source_commit,
        immutable_releases=settings,
        tag_rulesets=rulesets,
        allow_missing_assets=arguments.allow_missing_assets,
        published=arguments.published,
    )


def _normalize_settings(arguments: argparse.Namespace) -> None:
    settings = _read_object(arguments.input, "immutable releases response")
    _write_json(arguments.output, validate_immutable_releases(settings))


def _normalize_rulesets(arguments: argparse.Namespace) -> None:
    raw_rulesets = _read_array(arguments.input, "repository tag ruleset details")
    _write_json(
        arguments.output,
        normalize_tag_rulesets(raw_rulesets, tag=arguments.tag),
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    settings = subparsers.add_parser("normalize-settings")
    settings.add_argument("--input", type=Path, required=True)
    settings.add_argument("--output", type=Path, required=True)
    settings.set_defaults(handler=_normalize_settings)

    rulesets = subparsers.add_parser("normalize-rulesets")
    rulesets.add_argument("--input", type=Path, required=True)
    rulesets.add_argument("--tag", required=True)
    rulesets.add_argument("--output", type=Path, required=True)
    rulesets.set_defaults(handler=_normalize_rulesets)

    for name in ("prepare", "inspect", "verify"):
        command = subparsers.add_parser(name)
        if name != "inspect":
            command.add_argument("--directory", type=Path, required=True)
        command.add_argument("--version", required=True)
        command.add_argument("--tag", required=True)
        command.add_argument("--source-commit", required=True)
        command.add_argument("--immutable-releases", type=Path, required=True)
        command.add_argument("--tag-rulesets", type=Path, required=True)
        if name == "prepare":
            command.add_argument("--manifest-output", type=Path, required=True)
            command.add_argument("--body-output", type=Path, required=True)
            command.add_argument("--request-output", type=Path, required=True)
            command.set_defaults(handler=_prepare)
        else:
            command.add_argument("--release", type=Path, required=True)
            command.add_argument("--allow-missing-assets", action="store_true")
            command.add_argument("--published", action="store_true")
            command.set_defaults(handler=_inspect if name == "inspect" else _verify)
    return parser


def main() -> int:
    arguments = _parser().parse_args()
    try:
        arguments.handler(arguments)
    except (OSError, StagingError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 1
    tag = getattr(arguments, "tag", None)
    scope = f" for {tag}" if tag is not None else ""
    print(f"Verified release staging{scope}.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
