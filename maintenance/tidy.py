"""CLI entry point for the *tidy* git-history scrubbing tool.

Usage::

    python -m maintenance scan   --patterns maintenance/patterns
    python -m maintenance plan   --patterns maintenance/patterns --replacement "[REDACTED]"
    python -m maintenance clean  --patterns maintenance/patterns --replacement "[REDACTED]"
    python -m maintenance verify --patterns maintenance/patterns
    python -m maintenance ticket --commit-map /path/to/commit-map

Or via the ``tidy`` console_script (if installed)::

    tidy scan --patterns maintenance/patterns
"""

from __future__ import annotations

import argparse
import sys

from ._core import cmd_clean, cmd_plan, cmd_scan, cmd_ticket, cmd_verify


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tidy",
        description="Git-history scrubbing tool — scan, plan, clean, verify, ticket.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # ── scan ────────────────────────────────────────────────────────
    p_scan = sub.add_parser(
        "scan",
        help="Scan commit messages and file contents for sensitive patterns.",
    )
    p_scan.add_argument(
        "--patterns",
        required=True,
        help="Path to the patterns file (one pattern per line).",
    )
    p_scan.add_argument(
        "--repo",
        default=None,
        help="Path to the git repository (default: current directory).",
    )
    p_scan.add_argument(
        "--json",
        action="store_true",
        default=False,
        help="Output results as JSON.",
    )

    # ── plan ────────────────────────────────────────────────────────
    p_plan = sub.add_parser(
        "plan",
        help="Scan + build impact report with before/after preview.",
    )
    p_plan.add_argument(
        "--patterns",
        required=True,
        help="Path to the patterns file.",
    )
    p_plan.add_argument(
        "--replacement",
        default="[REDACTED]",
        help="Replacement text for scrubbed patterns (default: [REDACTED]).",
    )
    p_plan.add_argument(
        "--repo",
        default=None,
        help="Path to the git repository.",
    )

    # ── clean ───────────────────────────────────────────────────────
    p_clean = sub.add_parser(
        "clean",
        help="Full scrub pipeline: backup, filter-repo, force push.",
    )
    p_clean.add_argument(
        "--patterns",
        required=True,
        help="Path to the patterns file.",
    )
    p_clean.add_argument(
        "--replacement",
        default="[REDACTED]",
        help="Replacement text for scrubbed patterns (default: [REDACTED]).",
    )
    p_clean.add_argument(
        "--repo",
        default=None,
        help="Path to the git repository.",
    )
    p_clean.add_argument(
        "--yes", "-y",
        action="store_true",
        default=False,
        help="Skip confirmation prompt.",
    )

    # ── verify ──────────────────────────────────────────────────────
    p_verify = sub.add_parser(
        "verify",
        help="Re-scan local repo and optionally verify via GitHub API.",
    )
    p_verify.add_argument(
        "--patterns",
        required=True,
        help="Path to the patterns file.",
    )
    p_verify.add_argument(
        "--repo",
        default=None,
        help="Path to the git repository.",
    )
    p_verify.add_argument(
        "--remote",
        action="store_true",
        default=False,
        help="Also verify via GitHub API.",
    )
    p_verify.add_argument(
        "--branches",
        nargs="+",
        default=None,
        help="Branches to check remotely (default: all remote branches).",
    )
    p_verify.add_argument(
        "--limit",
        type=int,
        default=100,
        help="Max commits to check per branch (default: 100).",
    )

    # ── ticket ──────────────────────────────────────────────────────
    p_ticket = sub.add_parser(
        "ticket",
        help="Generate a GitHub Support ticket for cache purge.",
    )
    p_ticket.add_argument(
        "--repo",
        default=None,
        help="Path to the git repository.",
    )
    p_ticket.add_argument(
        "--shas",
        nargs="+",
        default=None,
        help="Old (dangling) SHA(s) to include in the ticket.",
    )
    p_ticket.add_argument(
        "--commit-map",
        default=None,
        help="Path to git-filter-repo commit-map file.",
    )
    p_ticket.add_argument(
        "--branches",
        nargs="+",
        default=None,
        help="Branch names affected (default: auto-detect).",
    )
    p_ticket.add_argument(
        "--output", "-o",
        default=None,
        help="Write ticket text to file instead of stdout.",
    )

    return parser


def main(argv: list[str] | None = None) -> None:
    """Parse arguments and dispatch to the appropriate subcommand."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    dispatch = {
        "scan": cmd_scan,
        "plan": cmd_plan,
        "clean": cmd_clean,
        "verify": cmd_verify,
        "ticket": cmd_ticket,
    }

    handler = dispatch.get(args.command)
    if handler is None:
        parser.print_help()
        sys.exit(1)

    handler(args)


if __name__ == "__main__":
    main()
