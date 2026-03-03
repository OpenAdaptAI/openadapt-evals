"""Configuration helpers — pattern loading and safety checks."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import List

from ._utils import log


def load_patterns(path: str) -> List[str]:
    """Read *path*, strip comments (``#``) and blank lines, return a list of
    non-empty pattern strings."""
    patterns: List[str] = []
    with open(path, "r", encoding="utf-8") as fh:
        for raw_line in fh:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            patterns.append(line)
    return patterns


def ensure_patterns_file_gitignored(patterns_path: str) -> None:
    """Hard-exit if the patterns file is NOT listed in ``.gitignore``.

    This is a safety check — the patterns file typically contains sensitive
    strings that must never be committed.
    """
    patterns_path_obj = Path(patterns_path)

    # Walk up to find the repo root (directory containing .git/)
    search = patterns_path_obj.resolve().parent
    repo_root = None
    while True:
        if (search / ".git").exists():
            repo_root = search
            break
        parent = search.parent
        if parent == search:
            break
        search = parent

    if repo_root is None:
        log("Cannot locate repo root — skipping .gitignore safety check", level="WARN")
        return

    gitignore_path = repo_root / ".gitignore"
    if not gitignore_path.exists():
        log(
            f"No .gitignore found at {gitignore_path}.  "
            f"Add '{patterns_path}' to .gitignore before continuing.",
            level="ERROR",
        )
        sys.exit(1)

    # Compute the relative path of the patterns file from the repo root
    try:
        rel = patterns_path_obj.resolve().relative_to(repo_root)
    except ValueError:
        rel = patterns_path_obj

    rel_str = str(rel)
    # Also check with leading slash and without
    variants = {rel_str, f"/{rel_str}", rel_str.lstrip("/")}

    with open(gitignore_path, "r", encoding="utf-8") as fh:
        for raw_line in fh:
            entry = raw_line.strip()
            if entry in variants:
                return  # Good — it is gitignored

    log(
        f"SAFETY: '{rel_str}' is NOT in {gitignore_path}.\n"
        f"    Add it to .gitignore to prevent accidental commit of sensitive patterns.\n"
        f"    Refusing to continue.",
        level="ERROR",
    )
    sys.exit(1)
