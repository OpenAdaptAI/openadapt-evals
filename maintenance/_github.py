"""GitHub API helpers for git-history maintenance.

Covers:
- Branch protection toggling (disable/restore force-push restrictions)
- Fork enumeration
- GitHub Support ticket text generation
- Commit verification via the API
"""

from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from ._utils import log, run_cmd


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class BranchProtection:
    """Snapshot of the branch-protection settings we modify."""

    branch: str
    enforce_admins: bool = False
    allow_force_pushes: bool = False
    required_status_checks: Optional[Dict[str, Any]] = None
    required_pull_request_reviews: Optional[Dict[str, Any]] = None
    restrictions: Optional[Dict[str, Any]] = None
    raw: Optional[Dict[str, Any]] = field(default=None, repr=False)


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------


def _gh_api(
    endpoint: str,
    *,
    method: str = "GET",
    input_data: Optional[str] = None,
    accept: str = "application/vnd.github+json",
    check: bool = True,
) -> subprocess.CompletedProcess:
    """Call ``gh api`` and return the CompletedProcess."""
    cmd = [
        "gh",
        "api",
        "-H",
        f"Accept: {accept}",
        "-H",
        "X-GitHub-Api-Version: 2022-11-28",
    ]
    if method != "GET":
        cmd += ["-X", method]
    cmd.append(endpoint)
    if input_data is not None:
        cmd += ["--input", "-"]
        return subprocess.run(
            cmd,
            input=input_data,
            capture_output=True,
            text=True,
            check=check,
        )
    return run_cmd(cmd, check=check)


def _gh_api_json(
    endpoint: str,
    *,
    method: str = "GET",
    input_data: Optional[str] = None,
    check: bool = True,
) -> Any:
    """Call ``gh api`` and parse the JSON response."""
    result = _gh_api(endpoint, method=method, input_data=input_data, check=check)
    if result.returncode != 0:
        return None
    if not result.stdout.strip():
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError:
        return None


# ---------------------------------------------------------------------------
# Fork enumeration
# ---------------------------------------------------------------------------


def list_forks(repo: str) -> List[Dict[str, Any]]:
    """Return a list of fork dicts for *repo* (``owner/name``)."""
    forks: List[Dict[str, Any]] = []
    page = 1
    while True:
        data = _gh_api_json(f"/repos/{repo}/forks?per_page=100&page={page}")
        if not data:
            break
        forks.extend(data)
        if len(data) < 100:
            break
        page += 1
    return forks


def count_forks(repo: str) -> int:
    """Return the number of forks for *repo*."""
    data = _gh_api_json(f"/repos/{repo}")
    if data and "forks_count" in data:
        return data["forks_count"]
    return 0


# ---------------------------------------------------------------------------
# Branch protection
# ---------------------------------------------------------------------------


def get_branch_protection(repo: str, branch: str) -> Optional[BranchProtection]:
    """Fetch current branch-protection settings.  Returns None if the branch
    is not protected."""
    data = _gh_api_json(f"/repos/{repo}/branches/{branch}/protection", check=False)
    if data is None:
        return None
    if "message" in data and "not protected" in data.get("message", "").lower():
        return None

    enforce_admins = False
    ea = data.get("enforce_admins")
    if isinstance(ea, dict):
        enforce_admins = ea.get("enabled", False)
    elif isinstance(ea, bool):
        enforce_admins = ea

    allow_force = False
    afp = data.get("allow_force_pushes")
    if isinstance(afp, dict):
        allow_force = afp.get("enabled", False)
    elif isinstance(afp, bool):
        allow_force = afp

    return BranchProtection(
        branch=branch,
        enforce_admins=enforce_admins,
        allow_force_pushes=allow_force,
        required_status_checks=data.get("required_status_checks"),
        required_pull_request_reviews=data.get("required_pull_request_reviews"),
        restrictions=data.get("restrictions"),
        raw=data,
    )


def _build_protection_payload(prot: BranchProtection) -> Dict[str, Any]:
    """Build a JSON payload suitable for PUT /repos/{repo}/branches/{branch}/protection."""
    payload: Dict[str, Any] = {
        "enforce_admins": prot.enforce_admins,
        "allow_force_pushes": prot.allow_force_pushes,
    }

    # required_status_checks
    rsc = prot.required_status_checks
    if rsc is not None:
        payload["required_status_checks"] = {
            "strict": rsc.get("strict", False),
            "contexts": [
                c.get("context", c) if isinstance(c, dict) else c
                for c in rsc.get("contexts", rsc.get("checks", []))
            ],
        }
    else:
        payload["required_status_checks"] = None

    # required_pull_request_reviews
    rprr = prot.required_pull_request_reviews
    if rprr is not None:
        sub: Dict[str, Any] = {}
        if "required_approving_review_count" in rprr:
            sub["required_approving_review_count"] = rprr[
                "required_approving_review_count"
            ]
        if "dismiss_stale_reviews" in rprr:
            sub["dismiss_stale_reviews"] = rprr["dismiss_stale_reviews"]
        if "require_code_owner_reviews" in rprr:
            sub["require_code_owner_reviews"] = rprr["require_code_owner_reviews"]
        payload["required_pull_request_reviews"] = sub
    else:
        payload["required_pull_request_reviews"] = None

    # restrictions
    rest = prot.restrictions
    if rest is not None:
        payload["restrictions"] = {
            "users": [
                u.get("login", u) if isinstance(u, dict) else u
                for u in rest.get("users", [])
            ],
            "teams": [
                t.get("slug", t) if isinstance(t, dict) else t
                for t in rest.get("teams", [])
            ],
            "apps": [
                a.get("slug", a) if isinstance(a, dict) else a
                for a in rest.get("apps", [])
            ],
        }
    else:
        payload["restrictions"] = None

    return payload


def set_branch_protection(
    repo: str,
    branch: str,
    protection: BranchProtection,
) -> bool:
    """Write branch-protection settings.  Returns True on success."""
    payload = _build_protection_payload(protection)
    data_str = json.dumps(payload)
    result = _gh_api(
        f"/repos/{repo}/branches/{branch}/protection",
        method="PUT",
        input_data=data_str,
        check=False,
    )
    if result.returncode != 0:
        log(f"Failed to set branch protection for {branch}: {result.stderr}", level="ERROR")
        return False
    return True


def disable_force_push_protection(
    repo: str,
    branch: str,
) -> Optional[BranchProtection]:
    """Disable force-push restrictions on *branch*.

    Returns the original ``BranchProtection`` snapshot so the caller can
    restore it later, or None if the branch was not protected.
    """
    original = get_branch_protection(repo, branch)
    if original is None:
        log(f"Branch '{branch}' has no protection — nothing to disable", level="WARN")
        return None

    log(f"Disabling force-push protection on '{branch}'")

    modified = BranchProtection(
        branch=branch,
        enforce_admins=False,
        allow_force_pushes=True,
        required_status_checks=original.required_status_checks,
        required_pull_request_reviews=original.required_pull_request_reviews,
        restrictions=original.restrictions,
        raw=original.raw,
    )
    ok = set_branch_protection(repo, branch, modified)
    if not ok:
        log("Could not disable branch protection — force push may fail", level="ERROR")
        return None
    return original


def restore_branch_protection(
    repo: str,
    original: BranchProtection,
) -> bool:
    """Restore branch protection to the *original* snapshot."""
    log(f"Restoring branch protection on '{original.branch}'")
    return set_branch_protection(repo, original.branch, original)


# ---------------------------------------------------------------------------
# Commit verification via API
# ---------------------------------------------------------------------------


def verify_commit_scrubbed(repo: str, sha: str, patterns: List[str]) -> bool:
    """Check via GitHub API that the commit message for *sha* does not
    contain any of the given *patterns*.  Returns True if clean."""
    data = _gh_api_json(f"/repos/{repo}/git/commits/{sha}", check=False)
    if data is None:
        log(f"Could not fetch commit {sha} from API", level="WARN")
        return False
    message = data.get("message", "")
    for pat in patterns:
        if pat.lower() in message.lower():
            log(f"Pattern '{pat}' still found in commit {sha[:12]}", level="ERROR")
            return False
    return True


def verify_all_commits_scrubbed(
    repo: str,
    branch: str,
    patterns: List[str],
    limit: int = 100,
) -> Tuple[int, int]:
    """Walk the last *limit* commits on *branch* via the API and check for
    pattern matches.  Returns ``(checked, failures)``."""
    commits = _gh_api_json(
        f"/repos/{repo}/commits?sha={branch}&per_page={limit}",
        check=False,
    )
    if not commits or not isinstance(commits, list):
        log(f"Could not list commits for {branch}", level="WARN")
        return (0, 0)

    checked = 0
    failures = 0
    for commit_data in commits:
        sha = commit_data.get("sha", "")
        msg = commit_data.get("commit", {}).get("message", "")
        checked += 1
        for pat in patterns:
            if pat.lower() in msg.lower():
                log(
                    f"Pattern '{pat}' found in {sha[:12]}: {msg.splitlines()[0]}",
                    level="ERROR",
                )
                failures += 1
                break
    return (checked, failures)


# ---------------------------------------------------------------------------
# Support ticket generation
# ---------------------------------------------------------------------------


_TICKET_TEMPLATE = """\
Subject: Request to clear cached commit data after history rewrite

Hi GitHub Support,

We recently performed a force-push to the repository **{repo}** to remove
sensitive information from the commit history using `git-filter-repo`.

The following old commit SHAs are now dangling and may still be accessible
via the GitHub API or cached views.  We would appreciate it if you could
clear any cached data for these commits:

Repository: {repo}
Branch(es) affected: {branches}

Old (now-invalid) SHAs:
{sha_list}

The rewrite replaced occurrences of sensitive strings with a redacted
placeholder.  We have verified that the current branch tips no longer
contain the sensitive data.

Thank you for your help.
"""


def generate_ticket_text(
    repo: str,
    old_shas: List[str],
    branches: List[str],
) -> str:
    """Return a ready-to-submit GitHub Support ticket body."""
    sha_list = "\n".join(f"  - {sha}" for sha in old_shas)
    branch_str = ", ".join(branches) if branches else "all branches"
    return _TICKET_TEMPLATE.format(
        repo=repo,
        branches=branch_str,
        sha_list=sha_list,
    )
