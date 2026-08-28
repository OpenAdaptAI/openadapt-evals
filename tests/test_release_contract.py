from __future__ import annotations

import importlib.util
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "verify_release_lock.py"
SPEC = importlib.util.spec_from_file_location("verify_release_lock", SCRIPT)
assert SPEC and SPEC.loader
release_lock = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(release_lock)


def _write_release_files(root: Path, project_version: str, lock_version: str) -> None:
    (root / "pyproject.toml").write_text(
        f'[project]\nname = "example-package"\nversion = "{project_version}"\n',
        encoding="utf-8",
    )
    (root / "uv.lock").write_text(
        '[[package]]\nname = "dependency"\nversion = "8.1.8"\n'
        'source = { registry = "https://pypi.org/simple" }\n\n'
        '[[package]]\nname = "example-package"\n'
        f'version = "{lock_version}"\nsource = {{ editable = "." }}\n',
        encoding="utf-8",
    )


def test_real_release_metadata_is_consistent() -> None:
    project_version, lock_version = release_lock.release_versions()
    assert project_version == lock_version
    release_lock.verify_release_lock()


def test_release_lock_rejects_version_drift(tmp_path: Path) -> None:
    _write_release_files(tmp_path, "0.90.0", "0.89.0")
    try:
        release_lock.verify_release_lock(tmp_path)
    except ValueError as exc:
        assert "pyproject.toml=0.90.0, uv.lock=0.89.0" in str(exc)
    else:
        raise AssertionError("version drift was accepted")


def test_sync_changes_only_editable_root_and_is_idempotent(tmp_path: Path) -> None:
    _write_release_files(tmp_path, "0.90.0", "0.89.0")
    before = (tmp_path / "uv.lock").read_text(encoding="utf-8")
    assert release_lock.synchronize_release_lock(tmp_path) is True
    after = (tmp_path / "uv.lock").read_text(encoding="utf-8")
    assert after == before.replace(
        'name = "example-package"\nversion = "0.89.0"',
        'name = "example-package"\nversion = "0.90.0"',
    )
    assert release_lock.synchronize_release_lock(tmp_path) is False
    assert (tmp_path / "uv.lock").read_text(encoding="utf-8") == after


def test_release_configuration_is_fail_closed() -> None:
    metadata = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    test_workflow = (ROOT / ".github/workflows/test.yml").read_text(encoding="utf-8")
    assert "major_on_zero = false" in metadata
    assert "allow_zero_version = true" in metadata
    assert (
        "python -m pip install uv==0.11.29 && "
        "python scripts/verify_release_lock.py --write && "
        "git add uv.lock && uv build"
    ) in metadata
    assert (
        metadata.index("python -m pip install uv==0.11.29")
        < metadata.index("python scripts/verify_release_lock.py --write")
        < metadata.index("git add uv.lock")
        < metadata.index("uv build")
    )
    assert "environment: release-identity" in workflow
    assert "environment: pypi" in workflow
    assert "actions/create-github-app-token@" in workflow
    assert workflow.count("app-id: 4730708") == 2
    assert "secrets.OPENADAPT_RELEASE_APP_PRIVATE_KEY" in workflow
    assert workflow.count("permission-administration: read") == 2
    assert "permission-contents: write" in workflow
    assert "permission-pull-requests: write" not in workflow
    publish_job = workflow.split("  publish-staged-release:", 1)[1]
    assert "environment: pypi" in publish_job
    assert "permissions:\n      contents: read\n      id-token: write" in publish_job
    assert "test \"$APP_SLUG\" = 'openadapt-release'" in publish_job
    assert "test \"$APP_INSTALLATION_ID\" = '156835568'" in publish_job
    assert "GH_TOKEN: ${{ steps.release-app.outputs.token }}" in publish_job
    assert "GH_TOKEN: ${{ github.token }}" not in publish_job
    assert re.search(r"(?m)^  workflow_dispatch:\s*$", workflow)
    assert re.search(r"(?m)^      version:\s*$", workflow)
    assert re.search(r"(?m)^      source_commit:\s*$", workflow)
    assert re.search(r"(?m)^  push:\s*$", workflow)
    assert re.search(r"(?m)^    tags:\s*$", workflow)
    assert not re.search(r"(?m)^    branches:\s*$", workflow)
    assert "github.event_name == 'workflow_dispatch'" in workflow
    assert "group: release-openadapt-evals" in workflow
    assert "github.actor == 'openadapt-release[bot]'" in workflow
    assert "reject-lifecycle-app:" in workflow
    assert "github.actor != 'openadapt-lifecycle[bot]'" in workflow
    assert "github.triggering_actor != 'openadapt-lifecycle[bot]'" in workflow
    assert "test \"$GITHUB_REF\" = 'refs/heads/main'" in workflow
    assert 'test "$GITHUB_SHA" = "$REQUESTED_SOURCE_COMMIT"' in workflow
    assert "refs/remotes/origin/main" in workflow
    assert 'git tag -a "$RELEASE_TAG" "$SOURCE_COMMIT"' in workflow
    assert "refs/tags/${RELEASE_TAG}:refs/tags/${RELEASE_TAG}" in workflow
    app_pushes = [
        line.strip() for line in workflow.splitlines() if line.strip().startswith("git push")
    ]
    assert app_pushes == ['git push origin "refs/tags/${RELEASE_TAG}:refs/tags/${RELEASE_TAG}"']
    assert "refs/heads/main:refs/heads/main" not in workflow
    assert "gh pr create" not in workflow
    assert "automation/release" not in workflow
    assert "python-semantic-release" not in workflow
    assert workflow.count("uv build") == 1
    assert workflow.count("python scripts/check_source_boundary.py --require-dist") == 3
    stage_job = workflow.split("  stage-release-and-create-tag:", 1)[1].split(
        "  publish-staged-release:", 1
    )[0]
    assert "Build the exact protected-main source once" in stage_job
    assert "Recover a complete exact draft without rebuilding" in stage_job
    assert "if: steps.recovery.outputs.complete != 'true'" in stage_job
    assert "Create or recover the exact App-owned draft" in stage_job
    assert "repos/${GITHUB_REPOSITORY}/immutable-releases" in stage_job
    assert "Capture the exact pre-draft release protections" in stage_job
    assert workflow.count("rulesets?includes_parents=true&per_page=100") == 3
    assert workflow.count("verify_release_staging.py normalize-settings") == 3
    assert workflow.count("verify_release_staging.py normalize-rulesets") == 3
    assert workflow.count('--tag-rulesets "$RUNNER_TEMP/') == 9
    assert stage_job.count('--tag-rulesets "$RUNNER_TEMP/') == 6
    assert publish_job.count('--tag-rulesets "$RUNNER_TEMP/') == 3
    assert 'select(.target == "tag")' in workflow
    assert "immutable-releases-post.json" in stage_job
    assert "tag-rulesets-post.json" in stage_job
    assert (
        'cmp "$RUNNER_TEMP/immutable-releases.json" \\\n'
        '            "$RUNNER_TEMP/immutable-releases-post.json"'
    ) in stage_job
    assert (
        'cmp "$RUNNER_TEMP/tag-rulesets.json" \\\n            "$RUNNER_TEMP/tag-rulesets-post.json"'
    ) in stage_job
    assert "X-GitHub-Api-Version: 2026-03-10" in stage_job
    assert "verify_release_staging.py prepare" in stage_job
    assert "verify_release_staging.py inspect" in stage_job
    assert stage_job.count("verify_release_staging.py verify") == 3
    assert "--allow-missing-assets" in stage_job
    assert "https://uploads.github.com/repos/${GITHUB_REPOSITORY}" in stage_job
    assert '--header "Content-Type: ${media_type}"' in stage_job
    assert stage_job.count("git ls-remote --exit-code --tags origin") >= 3
    assert stage_job.count('case "$tag_status" in') >= 3
    assert stage_job.count('2) test ! -s "$RUNNER_TEMP/') >= 3
    assert ">/dev/null 2>&1" not in stage_job
    assert "The release tag appeared before draft creation" in stage_job
    assert "The release tag appeared before final draft verification" in stage_job
    recovery = stage_job.index("Recover a complete exact draft without rebuilding")
    build = stage_job.index("Build the exact protected-main source once")
    boundary = stage_job.index("Verify the new public distribution boundary")
    draft = stage_job.index("Create or recover the exact App-owned draft")
    uploaded_assets = stage_job.index("https://uploads.github.com")
    post_draft_proof = stage_job.index("immutable-releases-post.raw.json")
    tag = stage_job.index('git tag -a "$RELEASE_TAG" "$SOURCE_COMMIT"')
    assert recovery < build < boundary < draft < uploaded_assets < post_draft_proof < tag
    assert "uv build" not in publish_job
    assert "Build the exact tag" not in publish_job
    assert "Recover and verify the durable draft assets" in publish_job
    assert "verify_release_staging.py inspect" in publish_job
    assert publish_job.count("verify_release_staging.py verify") == 2
    assert publish_job.count("--published") >= 2
    assert "gh api --method POST" not in publish_job
    assert "Publish only the existing verified draft" in publish_job
    assert "gh api --method PATCH" in publish_job
    assert "printf '{\"draft\":false}\\n'" in publish_job
    assert "gh release create" not in workflow
    assert "pypa/gh-action-pypi-publish@" in workflow
    assert "id-token: write" in workflow
    assert "skip-existing: true" in workflow
    preflight = publish_job.index("Refuse conflicting immutable PyPI files")
    publish = publish_job.index("pypa/gh-action-pypi-publish@")
    postflight = publish_job.index("Verify immutable PyPI publication bytes")
    assert preflight < publish < postflight
    preflight_body = publish_job[preflight:publish]
    postflight_body = publish_job[postflight:]
    assert "python scripts/verify_pypi_release.py" in preflight_body
    assert "--allow-matching-subset" in preflight_body
    assert "python scripts/verify_pypi_release.py" in postflight_body
    assert "--allow-matching-subset" not in postflight_body
    assert "Verify immutable PyPI publication bytes" in publish_job
    assert "--directory dist" in publish_job
    assert '--version "$version"' in publish_job
    assert "--wait-seconds 300" in publish_job
    assert "first_release_heading=$(grep -Em1" in workflow
    assert "ADMIN_TOKEN" not in workflow
    assert "PYPI_API_TOKEN" not in workflow
    assert "secrets.GITHUB_TOKEN" not in workflow
    assert 'version: "0.11.29"' in test_workflow
    assert "uv sync --locked --extra dev --no-sources" in test_workflow


def test_tag_publication_allows_an_exact_failed_run_to_be_retried() -> None:
    workflow = (ROOT / ".github/workflows/release.yml").read_text(encoding="utf-8")
    authorize_job = workflow.split("  stage-release-and-create-tag:", 1)[0]
    publish_job = workflow.split("  publish-staged-release:", 1)[1]
    assert "test \"$ACTOR\" = 'openadapt-release[bot]'" in authorize_job
    assert publish_job.count("github.actor == 'openadapt-release[bot]'") == 1
    assert "github.triggering_actor == 'openadapt-release[bot]'" not in authorize_job
    assert "github.triggering_actor == 'openadapt-release[bot]'" not in publish_job
    assert "release_is_draft" in publish_job
    assert "published_flag='--published'" in publish_job
    assert "if: steps.draft.outputs.was_draft == 'true'" in publish_job
    assert "skip-existing: true" in publish_job


def test_all_third_party_actions_are_commit_pinned() -> None:
    action_pattern = re.compile(r"uses:\s*([^\s@]+)@([^\s#]+)")
    for path in (ROOT / ".github" / "workflows").glob("*.yml"):
        for action, action_ref in action_pattern.findall(path.read_text(encoding="utf-8")):
            assert re.fullmatch(r"[0-9a-f]{40}", action_ref), (
                f"{path.name}: {action}@{action_ref} is not pinned to a commit"
            )
