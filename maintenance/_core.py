"""Core logic for the *tidy* git-history scrubbing tool.

Pipeline: Scan -> Plan -> Clean -> Verify -> Ticket

The module operates on a local git repository and optionally interacts with
GitHub (via ``gh`` CLI) for fork enumeration, branch-protection toggling,
and post-clean verification.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from ._config import ensure_patterns_file_gitignored, load_patterns
from ._github import (
    count_forks,
    disable_force_push_protection,
    generate_ticket_text,
    list_forks,
    restore_branch_protection,
    verify_all_commits_scrubbed,
)
from ._utils import confirm, log, run_cmd, run_git


# ===================================================================
# Data classes
# ===================================================================


@dataclass
class Match:
    """One pattern hit inside a commit message."""

    sha: str
    subject: str
    line: str
    pattern: str
    line_number: int


@dataclass
class BlobMatch:
    """One pattern hit inside tracked file content."""

    path: str
    line_number: int
    line: str
    pattern: str


@dataclass
class Plan:
    """Full impact report produced by :func:`build_plan`."""

    matches: List[Match]
    affected_commits: int
    downstream_commits: int
    affected_tags: List[str]
    affected_branches: List[str]
    forks: int
    replacement: str
    blob_matches: List[BlobMatch] = field(default_factory=list)


# ===================================================================
# Internal helpers
# ===================================================================


def _extract_repo_from_url(remote_url: str) -> str:
    """Extract ``owner/repo`` from an SSH or HTTPS GitHub URL.

    Handles:
    - ``git@github.com:owner/repo.git``
    - ``https://github.com/owner/repo.git``
    - ``https://github.com/owner/repo``
    """
    # SSH form
    m = re.match(r"git@github\.com:(.+?)(?:\.git)?$", remote_url.strip())
    if m:
        return m.group(1)
    # HTTPS form
    m = re.match(r"https?://github\.com/(.+?)(?:\.git)?$", remote_url.strip())
    if m:
        return m.group(1)
    raise ValueError(f"Cannot parse GitHub repo from remote URL: {remote_url!r}")


def _get_remote_url(cwd: Optional[str] = None) -> str:
    """Return the ``origin`` remote URL."""
    result = run_git("remote", "get-url", "origin", cwd=cwd)
    return result.stdout.strip()


def _short_sha(sha: str) -> str:
    """Return the first 12 characters of *sha*."""
    return sha[:12]


# ===================================================================
# Scanning
# ===================================================================


def scan_commit_messages(
    patterns: List[str],
    refs: str = "--all",
    cwd: Optional[str] = None,
) -> List[Match]:
    """Scan commit messages for *patterns* using ``git log``.

    Returns a list of :class:`Match` objects, one per pattern hit.
    """
    separator = "---END---"
    result = run_git(
        "log",
        refs,
        f"--format=%H%n%s%n%B%n{separator}",
        cwd=cwd,
        check=True,
    )

    matches: List[Match] = []
    raw = result.stdout

    # Split into per-commit blocks
    blocks = raw.split(separator)
    for block in blocks:
        lines = block.strip().splitlines()
        if not lines:
            continue

        sha = lines[0].strip()
        if not sha or len(sha) < 7:
            continue

        subject = lines[1].strip() if len(lines) > 1 else ""
        # The full message is lines[2:] (the body after subject)
        # But since %B already includes the subject, we scan all lines after sha
        message_lines = lines[1:]

        for line_number, line in enumerate(message_lines, start=1):
            for pattern in patterns:
                if pattern.lower() in line.lower():
                    matches.append(
                        Match(
                            sha=sha,
                            subject=subject,
                            line=line,
                            pattern=pattern,
                            line_number=line_number,
                        )
                    )

    return matches


def scan_file_contents(
    patterns: List[str],
    ref: str = "HEAD",
    cwd: Optional[str] = None,
) -> List[BlobMatch]:
    """Scan tracked file contents at *ref* for *patterns* using ``git grep``.

    Returns a list of :class:`BlobMatch` objects.
    """
    blob_matches: List[BlobMatch] = []

    for pattern in patterns:
        result = run_git(
            "grep",
            "-n",
            "--fixed-strings",
            "-i",
            pattern,
            ref,
            cwd=cwd,
            check=False,  # exit 1 means "no match"
        )
        if result.returncode not in (0, 1):
            log(f"git grep failed for pattern '{pattern}': {result.stderr}", level="WARN")
            continue

        for raw_line in result.stdout.splitlines():
            # Format: ref:path:lineno:content
            # or path:lineno:content when ref is empty
            parts = raw_line.split(":", 3)
            if len(parts) < 4:
                continue
            # parts[0] = ref, parts[1] = path, parts[2] = lineno, parts[3] = content
            path = parts[1]
            try:
                lineno = int(parts[2])
            except ValueError:
                continue
            content = parts[3]
            blob_matches.append(
                BlobMatch(
                    path=path,
                    line_number=lineno,
                    line=content,
                    pattern=pattern,
                )
            )

    return blob_matches


# ===================================================================
# Planning
# ===================================================================


def build_plan(
    matches: List[Match],
    replacement: str,
    blob_matches: Optional[List[BlobMatch]] = None,
    cwd: Optional[str] = None,
) -> Plan:
    """Compute the full impact report for the matched patterns.

    Counts affected/downstream commits, tags, branches, and forks.
    """
    if blob_matches is None:
        blob_matches = []

    # Unique affected SHAs
    affected_shas = sorted(set(m.sha for m in matches))
    affected_commits = len(affected_shas)

    # Downstream commits — commits that descend from any affected commit
    downstream_shas: set[str] = set()
    for sha in affected_shas:
        result = run_git(
            "rev-list",
            f"{sha}..HEAD",
            cwd=cwd,
            check=False,
        )
        if result.returncode == 0:
            for line in result.stdout.strip().splitlines():
                if line.strip():
                    downstream_shas.add(line.strip())
    downstream_commits = len(downstream_shas - set(affected_shas))

    # Affected tags
    affected_tags: List[str] = []
    for sha in affected_shas:
        result = run_git("tag", "--contains", sha, cwd=cwd, check=False)
        if result.returncode == 0:
            for tag in result.stdout.strip().splitlines():
                tag = tag.strip()
                if tag and tag not in affected_tags:
                    affected_tags.append(tag)

    # Affected branches
    affected_branches: List[str] = []
    for sha in affected_shas:
        result = run_git("branch", "--contains", sha, cwd=cwd, check=False)
        if result.returncode == 0:
            for branch_line in result.stdout.strip().splitlines():
                branch = branch_line.strip().lstrip("* ")
                if branch and branch not in affected_branches:
                    affected_branches.append(branch)

    # Forks
    forks = 0
    try:
        remote_url = _get_remote_url(cwd=cwd)
        repo = _extract_repo_from_url(remote_url)
        forks = count_forks(repo)
    except Exception:
        pass  # Not fatal — we just can't count forks

    return Plan(
        matches=matches,
        affected_commits=affected_commits,
        downstream_commits=downstream_commits,
        affected_tags=affected_tags,
        affected_branches=affected_branches,
        forks=forks,
        replacement=replacement,
        blob_matches=blob_matches,
    )


# ===================================================================
# Filter-repo callback generators
# ===================================================================


def _build_message_callback(patterns: List[str], replacement: str) -> str:
    """Generate Python code for ``git filter-repo --message-callback``.

    For multi-word patterns, generates cross-line variants (the pattern
    split at word boundaries with ``\\n``) to handle cases where the pattern
    spans two lines in commit messages.
    """
    # Build all search/replace pairs including cross-line variants
    lines: List[str] = []
    lines.append("import re")
    lines.append(f"replacement = {replacement!r}.encode('utf-8')")
    lines.append("msg = message")

    for pattern in patterns:
        # Direct replacement (case-insensitive)
        lines.append(
            f"msg = re.sub({pattern!r}.encode('utf-8'), replacement, msg, flags=re.IGNORECASE)"
        )

        # Cross-line variants: for multi-word patterns, the pattern may be
        # split across two lines.  Generate variants where each inter-word
        # boundary is replaced with \\n (plus optional surrounding whitespace).
        words = pattern.split()
        if len(words) > 1:
            for i in range(1, len(words)):
                left = " ".join(words[:i])
                right = " ".join(words[i:])
                # Pattern: left + whitespace + newline + optional whitespace + right
                cross_pat = re.escape(left) + r"\s*\n\s*" + re.escape(right)
                lines.append(
                    f"msg = re.sub({cross_pat!r}.encode('utf-8'), replacement, msg, flags=re.IGNORECASE)"
                )

    lines.append("return msg")
    return "\n".join(lines)


def _build_blob_callback(patterns: List[str], replacement: str) -> str:
    """Generate Python code for ``git filter-repo --blob-callback`` to
    replace patterns in file contents."""
    lines: List[str] = []
    lines.append("import re")
    lines.append(f"replacement = {replacement!r}.encode('utf-8')")

    for pattern in patterns:
        lines.append(
            f"blob.data = re.sub({pattern!r}.encode('utf-8'), replacement, blob.data, flags=re.IGNORECASE)"
        )

    return "\n".join(lines)


# ===================================================================
# Subcommands
# ===================================================================


def cmd_scan(args) -> None:
    """``scan`` subcommand — load patterns, scan commits + file contents,
    print results."""
    patterns_path = args.patterns
    ensure_patterns_file_gitignored(patterns_path)
    patterns = load_patterns(patterns_path)

    if not patterns:
        log("No patterns found in the patterns file", level="WARN")
        return

    log(f"Scanning with {len(patterns)} pattern(s) ...")

    cwd = getattr(args, "repo", None) or None

    # Scan commit messages
    commit_matches = scan_commit_messages(patterns, cwd=cwd)

    # Scan file contents
    blob_matches = scan_file_contents(patterns, cwd=cwd)

    output_json = getattr(args, "json", False)

    if output_json:
        result = {
            "commit_matches": [
                {
                    "sha": m.sha,
                    "subject": m.subject,
                    "line": m.line,
                    "pattern": m.pattern,
                    "line_number": m.line_number,
                }
                for m in commit_matches
            ],
            "blob_matches": [
                {
                    "path": b.path,
                    "line_number": b.line_number,
                    "line": b.line,
                    "pattern": b.pattern,
                }
                for b in blob_matches
            ],
        }
        print(json.dumps(result, indent=2))
        return

    # Text output
    if not commit_matches and not blob_matches:
        log("No matches found", level="OK")
        return

    if commit_matches:
        print(f"\n{'='*60}")
        print(f"COMMIT MESSAGE MATCHES ({len(commit_matches)})")
        print(f"{'='*60}")
        seen_shas: set[str] = set()
        for m in commit_matches:
            if m.sha not in seen_shas:
                seen_shas.add(m.sha)
                print(f"\n  {_short_sha(m.sha)}  {m.subject}")
            print(f"    L{m.line_number}: [{m.pattern}] {m.line.strip()}")

    if blob_matches:
        print(f"\n{'='*60}")
        print(f"FILE CONTENT MATCHES ({len(blob_matches)})")
        print(f"{'='*60}")
        seen_paths: set[str] = set()
        for b in blob_matches:
            if b.path not in seen_paths:
                seen_paths.add(b.path)
                print(f"\n  {b.path}")
            print(f"    L{b.line_number}: [{b.pattern}] {b.line.strip()}")

    # Summary
    unique_commits = len(set(m.sha for m in commit_matches))
    unique_files = len(set(b.path for b in blob_matches))
    print(f"\n{'='*60}")
    print(f"SUMMARY: {len(commit_matches)} commit-message hit(s) in "
          f"{unique_commits} commit(s), "
          f"{len(blob_matches)} file-content hit(s) in {unique_files} file(s)")
    print(f"{'='*60}\n")


def cmd_plan(args) -> None:
    """``plan`` subcommand — scan + build impact report, print summary with
    before/after preview."""
    patterns_path = args.patterns
    ensure_patterns_file_gitignored(patterns_path)
    patterns = load_patterns(patterns_path)

    if not patterns:
        log("No patterns found in the patterns file", level="WARN")
        return

    replacement = args.replacement
    cwd = getattr(args, "repo", None) or None

    log(f"Scanning with {len(patterns)} pattern(s) ...")
    commit_matches = scan_commit_messages(patterns, cwd=cwd)
    blob_matches = scan_file_contents(patterns, cwd=cwd)

    if not commit_matches and not blob_matches:
        log("No matches found — nothing to plan", level="OK")
        return

    log("Building impact plan ...")
    plan = build_plan(commit_matches, replacement, blob_matches=blob_matches, cwd=cwd)

    # Print the plan
    print(f"\n{'='*60}")
    print("IMPACT PLAN")
    print(f"{'='*60}")
    print(f"  Replacement text : {plan.replacement!r}")
    print(f"  Affected commits : {plan.affected_commits}")
    print(f"  Downstream commits (will be rewritten): {plan.downstream_commits}")
    print(f"  Affected tags    : {len(plan.affected_tags)}")
    if plan.affected_tags:
        for tag in plan.affected_tags:
            print(f"    - {tag}")
    print(f"  Affected branches: {len(plan.affected_branches)}")
    if plan.affected_branches:
        for branch in plan.affected_branches:
            print(f"    - {branch}")
    print(f"  Known forks      : {plan.forks}")
    print(f"  File-content hits: {len(plan.blob_matches)}")

    # Before/after preview
    if commit_matches:
        print(f"\n  {'─'*50}")
        print("  BEFORE / AFTER PREVIEW (commit messages)")
        print(f"  {'─'*50}")
        seen: set[str] = set()
        for m in commit_matches[:10]:  # Show first 10
            if m.sha in seen:
                continue
            seen.add(m.sha)
            before = m.line.strip()
            after = before
            for pat in patterns:
                # Case-insensitive replacement for preview
                compiled = re.compile(re.escape(pat), re.IGNORECASE)
                after = compiled.sub(replacement, after)
            print(f"\n  {_short_sha(m.sha)}")
            print(f"    BEFORE: {before}")
            print(f"    AFTER : {after}")

        remaining = len(set(m.sha for m in commit_matches)) - len(seen)
        if remaining > 0:
            print(f"\n  ... and {remaining} more commit(s)")

    if blob_matches:
        print(f"\n  {'─'*50}")
        print("  BEFORE / AFTER PREVIEW (file contents)")
        print(f"  {'─'*50}")
        shown = 0
        for b in blob_matches:
            if shown >= 10:
                break
            before = b.line.strip()
            after = before
            for pat in patterns:
                compiled = re.compile(re.escape(pat), re.IGNORECASE)
                after = compiled.sub(replacement, after)
            print(f"\n  {b.path}:{b.line_number}")
            print(f"    BEFORE: {before}")
            print(f"    AFTER : {after}")
            shown += 1

        remaining_blobs = len(blob_matches) - shown
        if remaining_blobs > 0:
            print(f"\n  ... and {remaining_blobs} more file hit(s)")

    print(f"\n{'='*60}\n")


def cmd_clean(args) -> None:
    """``clean`` subcommand — 7-step pipeline:

    1. Backup via ``git bundle create``
    2. Create work clone via ``git clone --mirror``
    3. Run ``git filter-repo`` with message-callback and blob-callback
    4. Read commit-map
    5. Confirm with user
    6. Toggle branch protection, force push, restore protection
    7. Print old SHAs for GitHub Support ticket
    """
    patterns_path = args.patterns
    ensure_patterns_file_gitignored(patterns_path)
    patterns = load_patterns(patterns_path)

    if not patterns:
        log("No patterns found in the patterns file", level="WARN")
        return

    replacement = args.replacement
    cwd = getattr(args, "repo", None) or os.getcwd()
    cwd = os.path.abspath(cwd)

    # Get remote URL before we do anything
    remote_url = _get_remote_url(cwd=cwd)
    repo = _extract_repo_from_url(remote_url)

    # Step 0: Quick scan to confirm there is work to do
    log("Step 0/7: Quick scan ...")
    commit_matches = scan_commit_messages(patterns, cwd=cwd)
    blob_matches = scan_file_contents(patterns, cwd=cwd)

    if not commit_matches and not blob_matches:
        log("No matches found — nothing to clean", level="OK")
        return

    log(f"Found {len(commit_matches)} commit-message hit(s) and "
        f"{len(blob_matches)} file-content hit(s)")

    plan = build_plan(commit_matches, replacement, blob_matches=blob_matches, cwd=cwd)

    # ── Step 1: Backup ──────────────────────────────────────────────
    log("Step 1/7: Creating backup bundle ...")
    backup_path = os.path.join(cwd, f".git-backup-{os.getpid()}.bundle")
    run_git("bundle", "create", backup_path, "--all", cwd=cwd)
    log(f"Backup saved to {backup_path}", level="OK")

    # ── Step 2: Mirror clone ────────────────────────────────────────
    log("Step 2/7: Creating mirror work-clone ...")
    work_dir = tempfile.mkdtemp(prefix="tidy-mirror-")
    work_clone = os.path.join(work_dir, "repo.git")
    run_git("clone", "--mirror", cwd, work_clone)
    log(f"Mirror clone at {work_clone}", level="OK")

    # ── Step 3: Run git filter-repo ─────────────────────────────────
    log("Step 3/7: Running git filter-repo ...")

    # Check that git-filter-repo is installed
    fr_check = run_cmd(["git", "filter-repo", "--version"], check=False)
    if fr_check.returncode != 0:
        log(
            "git-filter-repo is not installed.  Install it with:\n"
            "    pip install git-filter-repo\n"
            "or see https://github.com/newren/git-filter-repo",
            level="ERROR",
        )
        shutil.rmtree(work_dir, ignore_errors=True)
        sys.exit(1)

    # Write callbacks to temp files
    msg_cb = _build_message_callback(patterns, replacement)
    blob_cb = _build_blob_callback(patterns, replacement)

    msg_cb_path = os.path.join(work_dir, "message_callback.py")
    blob_cb_path = os.path.join(work_dir, "blob_callback.py")

    with open(msg_cb_path, "w") as f:
        f.write(msg_cb)
    with open(blob_cb_path, "w") as f:
        f.write(blob_cb)

    filter_cmd = [
        "git",
        "filter-repo",
        "--message-callback",
        msg_cb,
        "--blob-callback",
        blob_cb,
        "--force",
    ]

    result = run_cmd(filter_cmd, cwd=work_clone, check=False)
    if result.returncode != 0:
        log(f"git filter-repo failed:\n{result.stderr}", level="ERROR")
        shutil.rmtree(work_dir, ignore_errors=True)
        sys.exit(1)

    log("filter-repo completed", level="OK")

    # ── Step 4: Read commit-map ─────────────────────────────────────
    log("Step 4/7: Reading commit map ...")
    commit_map: Dict[str, str] = {}
    map_path = os.path.join(work_clone, "filter-repo", "commit-map")
    if os.path.exists(map_path):
        with open(map_path, "r") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("old"):
                    continue
                parts = line.split()
                if len(parts) >= 2:
                    commit_map[parts[0]] = parts[1]
        log(f"Read {len(commit_map)} commit mapping(s)", level="OK")
    else:
        log("No commit-map found (filter-repo may not have rewritten any commits)", level="WARN")

    # ── Step 5: Confirm ─────────────────────────────────────────────
    log("Step 5/7: Confirmation ...")
    print(f"\nAbout to force-push rewritten history to: {repo}")
    print(f"  Commits rewritten : {len(commit_map)}")
    print(f"  Affected branches : {', '.join(plan.affected_branches) or 'all'}")
    print(f"  Affected tags     : {', '.join(plan.affected_tags) or 'none'}")
    print(f"  Known forks       : {plan.forks}")
    if plan.forks > 0:
        print("  WARNING: Forks will NOT be updated automatically.")
        print("  You will need to contact fork owners or file a GitHub Support ticket.")
    print()

    if not getattr(args, "yes", False):
        if not confirm("Proceed with force push?"):
            log("Aborted by user", level="WARN")
            shutil.rmtree(work_dir, ignore_errors=True)
            return

    # ── Step 6: Force push ──────────────────────────────────────────
    log("Step 6/7: Force pushing ...")

    # After filter-repo, remotes are stripped — re-add origin
    run_git("remote", "add", "origin", remote_url, cwd=work_clone, check=False)

    # Toggle branch protection for each affected branch
    saved_protections = []
    for branch in plan.affected_branches:
        try:
            original = disable_force_push_protection(repo, branch)
            if original is not None:
                saved_protections.append(original)
        except Exception as e:
            log(f"Could not disable protection on '{branch}': {e}", level="WARN")

    try:
        # Force push all branches
        push_result = run_git(
            "push", "--force", "--all", "origin",
            cwd=work_clone,
            check=False,
        )
        if push_result.returncode != 0:
            log(f"Force push (branches) failed:\n{push_result.stderr}", level="ERROR")
        else:
            log("Branches force-pushed", level="OK")

        # Force push all tags
        tag_result = run_git(
            "push", "--force", "--tags", "origin",
            cwd=work_clone,
            check=False,
        )
        if tag_result.returncode != 0:
            log(f"Force push (tags) failed:\n{tag_result.stderr}", level="ERROR")
        else:
            log("Tags force-pushed", level="OK")
    finally:
        # Always restore branch protection
        for prot in saved_protections:
            try:
                restore_branch_protection(repo, prot)
            except Exception as e:
                log(f"Could not restore protection on '{prot.branch}': {e}", level="ERROR")

    # ── Step 7: Print old SHAs ──────────────────────────────────────
    log("Step 7/7: Summary ...")

    old_shas = list(commit_map.keys())
    if old_shas:
        print(f"\nOld (now-invalid) SHAs ({len(old_shas)}):")
        for old_sha in old_shas:
            new_sha = commit_map.get(old_sha, "???")
            print(f"  {old_sha} -> {new_sha}")
        print()
        print("Save these old SHAs — you'll need them for the GitHub Support ticket.")
        print("Run `tidy ticket` to generate the ticket text.")
    else:
        print("\nNo commits were rewritten.")

    # Clean up work dir
    shutil.rmtree(work_dir, ignore_errors=True)

    # Update the local repo to match the rewritten remote
    log("Fetching rewritten history into local repo ...")
    run_git("fetch", "origin", cwd=cwd, check=False)

    log("Clean complete!", level="OK")


def cmd_verify(args) -> None:
    """``verify`` subcommand — re-scan local repo and optionally verify via
    the GitHub API."""
    patterns_path = args.patterns
    ensure_patterns_file_gitignored(patterns_path)
    patterns = load_patterns(patterns_path)

    if not patterns:
        log("No patterns found in the patterns file", level="WARN")
        return

    cwd = getattr(args, "repo", None) or None

    # Local scan
    log("Verifying local repository ...")
    commit_matches = scan_commit_messages(patterns, cwd=cwd)
    blob_matches = scan_file_contents(patterns, cwd=cwd)

    if commit_matches:
        log(
            f"FAIL: {len(commit_matches)} commit-message match(es) still present locally",
            level="ERROR",
        )
        for m in commit_matches[:5]:
            print(f"  {_short_sha(m.sha)} L{m.line_number}: [{m.pattern}] {m.line.strip()}")
        if len(commit_matches) > 5:
            print(f"  ... and {len(commit_matches) - 5} more")
    else:
        log("Local commit messages: clean", level="OK")

    if blob_matches:
        log(
            f"FAIL: {len(blob_matches)} file-content match(es) still present locally",
            level="ERROR",
        )
        for b in blob_matches[:5]:
            print(f"  {b.path}:{b.line_number}: [{b.pattern}] {b.line.strip()}")
        if len(blob_matches) > 5:
            print(f"  ... and {len(blob_matches) - 5} more")
    else:
        log("Local file contents: clean", level="OK")

    # Remote verification via GitHub API
    if getattr(args, "remote", False):
        log("Verifying via GitHub API ...")
        try:
            remote_url = _get_remote_url(cwd=cwd)
            repo = _extract_repo_from_url(remote_url)
        except Exception as e:
            log(f"Could not determine remote repo: {e}", level="ERROR")
            return

        # Check each branch
        branches = getattr(args, "branches", None)
        if not branches:
            # Default to common branches
            result = run_git("branch", "-r", "--list", "origin/*", cwd=cwd, check=False)
            if result.returncode == 0:
                branches = []
                for line in result.stdout.strip().splitlines():
                    branch = line.strip().replace("origin/", "", 1)
                    if branch and "->" not in branch:
                        branches.append(branch)
            else:
                branches = ["main"]

        total_checked = 0
        total_failures = 0
        for branch in branches:
            checked, failures = verify_all_commits_scrubbed(
                repo, branch, patterns, limit=getattr(args, "limit", 100)
            )
            total_checked += checked
            total_failures += failures
            if failures:
                log(f"Branch '{branch}': {failures} failure(s) in {checked} commit(s)", level="ERROR")
            else:
                log(f"Branch '{branch}': {checked} commit(s) clean", level="OK")

        print(f"\nRemote verification: {total_checked} commit(s) checked, "
              f"{total_failures} failure(s)")

    # Final summary
    local_clean = not commit_matches and not blob_matches
    if local_clean:
        log("Verification PASSED", level="OK")
    else:
        log("Verification FAILED — patterns still present", level="ERROR")
        sys.exit(1)


def cmd_ticket(args) -> None:
    """``ticket`` subcommand — generate ready-to-submit GitHub Support ticket
    text."""
    cwd = getattr(args, "repo", None) or None

    try:
        remote_url = _get_remote_url(cwd=cwd)
        repo = _extract_repo_from_url(remote_url)
    except Exception as e:
        log(f"Could not determine remote repo: {e}", level="ERROR")
        sys.exit(1)

    # Get old SHAs from args or from commit-map file
    old_shas: List[str] = []
    if hasattr(args, "shas") and args.shas:
        old_shas = args.shas
    elif hasattr(args, "commit_map") and args.commit_map:
        # Read from a commit-map file
        map_path = args.commit_map
        if os.path.exists(map_path):
            with open(map_path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("old"):
                        continue
                    parts = line.split()
                    if parts:
                        old_shas.append(parts[0])
        else:
            log(f"Commit map not found: {map_path}", level="ERROR")
            sys.exit(1)
    else:
        log(
            "Provide old SHAs via --shas or a commit-map file via --commit-map",
            level="ERROR",
        )
        sys.exit(1)

    # Get affected branches
    branches: List[str] = []
    if hasattr(args, "branches") and args.branches:
        branches = args.branches
    else:
        result = run_git("branch", "-r", "--list", "origin/*", cwd=cwd, check=False)
        if result.returncode == 0:
            for line in result.stdout.strip().splitlines():
                branch = line.strip().replace("origin/", "", 1)
                if branch and "->" not in branch:
                    branches.append(branch)

    ticket = generate_ticket_text(repo, old_shas, branches)

    output = getattr(args, "output", None)
    if output:
        with open(output, "w") as f:
            f.write(ticket)
        log(f"Ticket text written to {output}", level="OK")
    else:
        print(ticket)
