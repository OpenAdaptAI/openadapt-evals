from __future__ import annotations

import copy
import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify_release_staging.py"
SPEC = importlib.util.spec_from_file_location("verify_release_staging", SCRIPT)
assert SPEC and SPEC.loader
staging = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(staging)

VERSION = "0.94.1"
TAG = f"v{VERSION}"
SOURCE_COMMIT = "c" * 40
SETTINGS = {"enabled": True, "enforced_by_owner": False}


def _raw_rulesets() -> list[dict[str, object]]:
    return [
        {
            "id": 71,
            "name": "release tag creation authority",
            "target": "tag",
            "enforcement": "active",
            "bypass_actors": [
                {
                    "actor_id": 4730708,
                    "actor_type": "Integration",
                    "bypass_mode": "always",
                }
            ],
            "conditions": {"ref_name": {"include": ["refs/tags/v*"], "exclude": []}},
            "rules": [{"type": "creation"}],
        },
        {
            "id": 72,
            "name": "release tag immutability",
            "target": "tag",
            "enforcement": "active",
            "bypass_actors": [],
            "conditions": {"ref_name": {"include": ["v*"], "exclude": []}},
            "rules": [
                {"type": "update"},
                {"type": "deletion"},
                {"type": "non_fast_forward"},
            ],
        },
    ]


def _rulesets() -> list[dict[str, object]]:
    return staging.normalize_tag_rulesets(_raw_rulesets(), tag=TAG)


def _write_dist(root: Path) -> Path:
    directory = root / "dist"
    directory.mkdir()
    (directory / f"openadapt_evals-{VERSION}-py3-none-any.whl").write_bytes(b"wheel")
    (directory / f"openadapt_evals-{VERSION}.tar.gz").write_bytes(b"sdist")
    return directory


def _manifest(directory: Path) -> dict[str, object]:
    return staging.build_manifest(
        directory=directory,
        version=VERSION,
        tag=TAG,
        source_commit=SOURCE_COMMIT,
        immutable_releases=SETTINGS,
        tag_rulesets=_rulesets(),
    )


def _release(directory: Path, *, published: bool = False) -> dict[str, object]:
    manifest = _manifest(directory)
    assets = []
    for asset_id, artifact in enumerate(manifest["artifacts"], start=41):
        assets.append(
            {
                "id": asset_id,
                "name": artifact["name"],
                "state": "uploaded",
                "size": artifact["size_bytes"],
                "digest": artifact["sha256"],
                "content_type": artifact["media_type"],
                "uploader": {
                    "login": "openadapt-release[bot]",
                    "id": 321543906,
                },
            }
        )
    return {
        "id": 991,
        "tag_name": TAG,
        "target_commitish": SOURCE_COMMIT,
        "name": TAG,
        "body": staging.render_body(manifest),
        "draft": not published,
        "prerelease": False,
        "immutable": published,
        "author": {"login": "openadapt-release[bot]", "id": 321543906},
        "assets": assets,
    }


def _validate(release: object, directory: Path, *, published: bool = False) -> None:
    staging.validate_release(
        release,
        directory=directory,
        version=VERSION,
        tag=TAG,
        source_commit=SOURCE_COMMIT,
        immutable_releases=SETTINGS,
        tag_rulesets=_rulesets(),
        published=published,
    )


def test_manifest_binds_the_exact_files_settings_and_absent_tag(tmp_path: Path) -> None:
    directory = _write_dist(tmp_path)
    manifest = _manifest(directory)

    assert manifest["tag_ref_state"] == {"ref": f"refs/tags/{TAG}", "exists": False}
    assert manifest["tag_ref_state_sha256"] == staging.tag_ref_state_digest(
        manifest["tag_ref_state"]
    )
    assert manifest["immutable_releases"] == SETTINGS
    assert manifest["immutable_releases_sha256"] == staging.immutable_releases_digest(SETTINGS)
    assert [ruleset["role"] for ruleset in manifest["tag_rulesets"]] == [
        "creation_authority",
        "immutability",
    ]
    assert manifest["tag_rulesets"][0]["bypass_actors"] == [
        {
            "actor_id": "4730708",
            "actor_type": "Integration",
            "bypass_mode": "always",
        }
    ]
    assert manifest["tag_rulesets"][1]["bypass_actors"] == []
    assert manifest["tag_rulesets_sha256"] == staging.tag_rulesets_digest(manifest["tag_rulesets"])
    assert str(manifest["tag_ref_state_sha256"]).startswith("sha256:")
    assert str(manifest["immutable_releases_sha256"]).startswith("sha256:")
    assert str(manifest["tag_rulesets_sha256"]).startswith("sha256:")
    for field in (
        "tag_ref_state_sha256",
        "immutable_releases_sha256",
        "tag_rulesets_sha256",
    ):
        bare = copy.deepcopy(manifest)
        bare[field] = str(bare[field]).removeprefix("sha256:")
        with pytest.raises(staging.StagingError, match="protection evidence"):
            staging.validate_manifest_metadata(
                bare,
                version=VERSION,
                tag=TAG,
                source_commit=SOURCE_COMMIT,
                immutable_releases=SETTINGS,
                tag_rulesets=_rulesets(),
            )

        uppercase = copy.deepcopy(manifest)
        uppercase[field] = str(uppercase[field]).upper()
        with pytest.raises(staging.StagingError, match="protection evidence"):
            staging.validate_manifest_metadata(
                uppercase,
                version=VERSION,
                tag=TAG,
                source_commit=SOURCE_COMMIT,
                immutable_releases=SETTINGS,
                tag_rulesets=_rulesets(),
            )
    assert [artifact["kind"] for artifact in manifest["artifacts"]] == [
        "wheel",
        "sdist",
    ]
    assert staging.parse_body(staging.render_body(manifest)) == manifest


@pytest.mark.parametrize(
    "settings",
    [
        {"enabled": False, "enforced_by_owner": False},
        {"enabled": True, "enforced_by_owner": 0},
        {"enabled": True},
        {"enabled": True, "enforced_by_owner": False, "extra": False},
    ],
)
def test_immutable_release_response_is_exact_and_fail_closed(settings: object) -> None:
    with pytest.raises(staging.StagingError):
        staging.validate_immutable_releases(settings)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (
            lambda value: value[0].update(bypass_actors=[]),
            "creation_authority tag ruleset bypass actors",
        ),
        (
            lambda value: value[0]["bypass_actors"].append(
                {
                    "actor_id": 1,
                    "actor_type": "OrganizationAdmin",
                    "bypass_mode": "always",
                }
            ),
            "creation_authority tag ruleset bypass actors",
        ),
        (
            lambda value: value[1]["bypass_actors"].append(
                {
                    "actor_id": 4730708,
                    "actor_type": "Integration",
                    "bypass_mode": "always",
                }
            ),
            "immutability tag ruleset bypass actors",
        ),
        (
            lambda value: value[0].update(enforcement="disabled"),
            "creation_authority tag ruleset is not active",
        ),
        (
            lambda value: value[1]["conditions"]["ref_name"].update(
                include=["refs/tags/not-this-release"]
            ),
            "exactly one active immutability",
        ),
        (
            lambda value: value.append(copy.deepcopy(value[0])),
            "exactly one active creation_authority",
        ),
    ],
)
def test_tag_ruleset_proof_is_exact_and_fail_closed(
    mutation: object,
    message: str,
) -> None:
    rulesets = _raw_rulesets()
    mutation(rulesets)
    with pytest.raises(staging.StagingError, match=message):
        staging.normalize_tag_rulesets(rulesets, tag=TAG)


def test_exact_app_owned_draft_and_published_release_are_accepted(tmp_path: Path) -> None:
    directory = _write_dist(tmp_path)
    _validate(_release(directory), directory)
    _validate(_release(directory, published=True), directory, published=True)


def test_interrupted_draft_can_resume_only_with_an_exact_asset_subset(
    tmp_path: Path,
) -> None:
    directory = _write_dist(tmp_path)
    release = _release(directory)
    release["assets"] = release["assets"][:1]

    staging.validate_release(
        release,
        directory=directory,
        version=VERSION,
        tag=TAG,
        source_commit=SOURCE_COMMIT,
        immutable_releases=SETTINGS,
        tag_rulesets=_rulesets(),
        allow_missing_assets=True,
    )
    with pytest.raises(staging.StagingError, match="complete artifact set"):
        _validate(release, directory)


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda value: value["author"].update(id=1), "author differs"),
        (lambda value: value["assets"][0]["uploader"].update(id=1), "uploader differs"),
        (lambda value: value["assets"][0].update(digest="sha256:" + "0" * 64), "digest differs"),
        (lambda value: value["assets"][0].update(size=1), "metadata differs"),
        (
            lambda value: value["assets"][0].update(content_type="application/octet-stream"),
            "metadata differs",
        ),
        (lambda value: value.update(target_commitish="d" * 40), "identity or state differs"),
        (lambda value: value.update(prerelease=True), "identity or state differs"),
    ],
)
def test_release_identity_and_asset_drift_are_refused(
    tmp_path: Path,
    mutation: object,
    message: str,
) -> None:
    directory = _write_dist(tmp_path)
    release = _release(directory)
    mutation(release)
    with pytest.raises(staging.StagingError, match=message):
        _validate(release, directory)


def test_manifest_and_downloaded_file_drift_are_refused(tmp_path: Path) -> None:
    directory = _write_dist(tmp_path)
    release = _release(directory)
    parsed = staging.parse_body(release["body"])
    parsed["tag_ref_state"]["exists"] = True
    release["body"] = staging.render_body(parsed)
    with pytest.raises(staging.StagingError, match="protection evidence"):
        _validate(release, directory)

    release = _release(directory)
    (directory / f"openadapt_evals-{VERSION}.tar.gz").write_bytes(b"changed")
    with pytest.raises(staging.StagingError, match="exact files"):
        _validate(release, directory)


@pytest.mark.parametrize("transform", [lambda value: value[7:], str.upper])
def test_bare_or_uppercase_artifact_digests_are_refused(
    tmp_path: Path,
    transform: object,
) -> None:
    directory = _write_dist(tmp_path)
    release = _release(directory)
    manifest = staging.parse_body(release["body"])
    manifest["artifacts"][0]["sha256"] = transform(manifest["artifacts"][0]["sha256"])
    release["body"] = staging.render_body(manifest)

    with pytest.raises(staging.StagingError, match="artifact 0 contract"):
        _validate(release, directory)


@pytest.mark.parametrize("transform", [lambda value: value[7:], str.upper])
def test_bare_or_uppercase_github_asset_digests_are_refused(
    tmp_path: Path,
    transform: object,
) -> None:
    directory = _write_dist(tmp_path)
    release = _release(directory)
    release["assets"][0]["digest"] = transform(release["assets"][0]["digest"])

    with pytest.raises(staging.StagingError, match="asset digest differs"):
        _validate(release, directory)


def test_metadata_inspection_refuses_an_unsafe_asset_before_download(tmp_path: Path) -> None:
    directory = _write_dist(tmp_path)
    release = _release(directory)
    release["assets"][0]["name"] = "../escaped.whl"
    with pytest.raises(staging.StagingError, match="unexpected or duplicate asset"):
        staging.validate_release_metadata(
            release,
            version=VERSION,
            tag=TAG,
            source_commit=SOURCE_COMMIT,
            immutable_releases=SETTINGS,
            tag_rulesets=_rulesets(),
        )


def test_published_state_requires_github_immutability(tmp_path: Path) -> None:
    directory = _write_dist(tmp_path)
    release = _release(directory, published=True)
    release["immutable"] = False
    with pytest.raises(staging.StagingError, match="identity or state differs"):
        _validate(release, directory, published=True)


def test_extra_local_or_remote_files_are_refused(tmp_path: Path) -> None:
    directory = _write_dist(tmp_path)
    release = _release(directory)
    extra = copy.deepcopy(release["assets"][0])
    extra["id"] = 99
    extra["name"] = "other.whl"
    release["assets"].append(extra)
    with pytest.raises(staging.StagingError, match="unexpected or duplicate asset"):
        _validate(release, directory)

    release = _release(directory)
    (directory / "notes.txt").write_text("not a distribution", encoding="utf-8")
    with pytest.raises(staging.StagingError, match="unexpected release artifact"):
        _validate(release, directory)
