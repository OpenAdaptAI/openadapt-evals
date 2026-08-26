from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOWS = ROOT / ".github" / "workflows"
LIFECYCLE_ACTOR = "openadapt-lifecycle[bot]"


def _workflow(name: str) -> str:
    return (WORKFLOWS / name).read_text(encoding="utf-8")


def test_production_lifecycle_evidence_is_app_only() -> None:
    workflow = _workflow("production-lifecycle-evidence.yml")
    assert re.search(r"(?m)^  workflow_dispatch:\s*$", workflow)
    assert not re.search(
        r"(?m)^  (pull_request|pull_request_target|push|release|schedule|repository_dispatch|workflow_call):\s*$",
        workflow,
    )
    assert "environment: production-lifecycle-evidence" in workflow
    assert "github.repository == 'OpenAdaptAI/openadapt-evals'" in workflow
    assert "github.ref == 'refs/heads/main'" in workflow
    assert "github.event_name == 'workflow_dispatch'" in workflow
    assert f"github.actor == '{LIFECYCLE_ACTOR}'" in workflow
    assert f"github.triggering_actor == '{LIFECYCLE_ACTOR}'" in workflow
    assert "github.actor_id == vars.OPENADAPT_LIFECYCLE_ACTOR_ID" in workflow
    assert "vars.OPENADAPT_LIFECYCLE_APP_ID" in workflow
    assert "vars.OPENADAPT_LIFECYCLE_INSTALLATION_ID" in workflow
    assert "secrets.OPENADAPT_LIFECYCLE_APP_PRIVATE_KEY" in workflow
    assert "permission-pull-requests: write" in workflow
    assert "contents: write" in workflow
    assert "token: ${{ github.token }}" in workflow
    assert "gh pr create" in workflow
    assert not re.search(r"git\s+push[^\n]*(?:refs/heads/)?main", workflow)
    assert "permission-contents: write" not in workflow
    assert "cancel-in-progress: false" in workflow
    assert "github.workflow" in workflow
    assert "github.event_name" in workflow


def test_manual_non_lifecycle_workflows_reject_the_lifecycle_app() -> None:
    for name, job in (
        ("complex-visual.yml", "headed-pixel-campaign"),
        ("evidence-freshness.yml", "freshness"),
    ):
        workflow = _workflow(name)
        assert "reject-lifecycle-app:" in workflow
        assert "permissions: {}" in workflow
        assert workflow.count(LIFECYCLE_ACTOR) >= 4
        assert re.search(rf"(?ms)^  {job}:\n.*?    needs: reject-lifecycle-app", workflow)
        assert "github.actor != 'openadapt-lifecycle[bot]'" in workflow
        assert "github.triggering_actor != 'openadapt-lifecycle[bot]'" in workflow
        assert "cancel-in-progress: false" in workflow
        group = re.search(r"(?m)^  group: (.+)$", workflow)
        assert group is not None
        assert "github.workflow" in group.group(1)
        assert "github.event_name" in group.group(1)


def test_legacy_docs_pat_dispatch_is_removed() -> None:
    assert not (WORKFLOWS / "notify-docs.yml").exists()
    combined = "\n".join(
        path.read_text(encoding="utf-8") for path in WORKFLOWS.glob("*.yml")
    )
    assert "DOCS_DISPATCH_TOKEN" not in combined
    assert "peter-evans/repository-dispatch" not in combined
