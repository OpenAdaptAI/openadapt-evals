# maintenance/tidy — Git History Scrubbing Tool

A CLI tool for scanning, planning, executing, verifying, and reporting
git-history rewrites to remove sensitive patterns from commit messages and
file contents.

## Prerequisites

- Python 3.10+
- `git-filter-repo` (install via `pip install git-filter-repo`)
- `gh` CLI (for GitHub API operations: fork enumeration, branch protection, verification)

## Setup

1. Create a patterns file at `maintenance/patterns` with one sensitive
   string per line.  Lines starting with `#` are comments.

   See `maintenance/patterns.example` for the format.

2. Ensure `maintenance/patterns` is listed in `.gitignore` (the tool
   enforces this as a safety check).

## Subcommands

### scan

Scan commit messages and tracked file contents for pattern matches.

```
python -m maintenance scan --patterns maintenance/patterns [--repo /path/to/repo] [--json]
```

- `--patterns` (required): path to the patterns file.
- `--repo`: path to the git repository (defaults to current directory).
- `--json`: output results as JSON instead of human-readable text.

### plan

Scan + build an impact report showing affected commits, downstream commits,
tags, branches, forks, and a before/after preview of what the replacement
will look like.

```
python -m maintenance plan --patterns maintenance/patterns --replacement "[REDACTED]" [--repo /path/to/repo]
```

- `--replacement` (default `[REDACTED]`): the text that replaces each
  matched pattern.

### clean

Execute the full scrub pipeline:

1. **Backup** — creates a git bundle of the entire repo.
2. **Mirror clone** — works on a temporary `--mirror` clone.
3. **filter-repo** — runs `git filter-repo` with both `--message-callback`
   (commit messages) and `--blob-callback` (file contents).
4. **Commit map** — reads the old-SHA to new-SHA mapping.
5. **Confirm** — prompts the user before force-pushing (skip with `--yes`).
6. **Force push** — disables branch protection, force-pushes all branches
   and tags, then restores protection (in a `try/finally`).
7. **Summary** — prints old SHAs needed for a GitHub Support ticket.

```
python -m maintenance clean --patterns maintenance/patterns --replacement "[REDACTED]" [--repo /path/to/repo] [--yes]
```

- `--yes` / `-y`: skip the confirmation prompt.

**Important notes:**

- After `filter-repo`, remotes are stripped.  The tool re-adds `origin`
  before pushing.
- Uses `git push --force --all` then `git push --force --tags` (not
  `--mirror`).
- Branch protection is disabled then restored in a `try/finally` to avoid
  leaving the repo unprotected on error.

### verify

Re-scan the local repository to confirm patterns are gone.  Optionally
verify via the GitHub API.

```
python -m maintenance verify --patterns maintenance/patterns [--remote] [--branches main develop] [--limit 200]
```

- `--remote`: also check commits via the GitHub API.
- `--branches`: which remote branches to check (default: all).
- `--limit`: max commits per branch to check via API (default: 100).

### ticket

Generate a ready-to-submit GitHub Support ticket requesting cache/ghost
commit purge.

```
python -m maintenance ticket --commit-map /path/to/filter-repo/commit-map [--output ticket.txt]
python -m maintenance ticket --shas abc123 def456 [--branches main] [--output ticket.txt]
```

- `--shas`: provide old SHAs directly on the command line.
- `--commit-map`: path to the `commit-map` file produced by `git filter-repo`.
- `--branches`: affected branch names (default: auto-detect).
- `--output` / `-o`: write to file instead of stdout.

## Typical Workflow

```bash
# 1. Scan for matches
python -m maintenance scan --patterns maintenance/patterns

# 2. Review the impact plan
python -m maintenance plan --patterns maintenance/patterns --replacement "[REDACTED]"

# 3. Execute the clean (creates backup, rewrites, force-pushes)
python -m maintenance clean --patterns maintenance/patterns --replacement "[REDACTED]"

# 4. Verify locally and remotely
python -m maintenance verify --patterns maintenance/patterns --remote

# 5. Generate GitHub Support ticket for cache purge
python -m maintenance ticket --commit-map /tmp/tidy-mirror-*/repo.git/filter-repo/commit-map -o ticket.txt
```
