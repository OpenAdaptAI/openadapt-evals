"""Utility helpers for the maintenance CLI."""

from __future__ import annotations

import subprocess
import sys
from typing import Optional


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

_PREFIXES = {
    "INFO": "[*]",
    "WARN": "[!]",
    "ERROR": "[✗]",
    "OK": "[✓]",
}


def log(msg: str, *, level: str = "INFO") -> None:
    """Print a prefixed message to stderr."""
    prefix = _PREFIXES.get(level.upper(), "[*]")
    print(f"{prefix} {msg}", file=sys.stderr)


# ---------------------------------------------------------------------------
# Interactive helpers
# ---------------------------------------------------------------------------


def confirm(prompt: str) -> bool:
    """Prompt the user with a y/n question.  Returns True for 'y'."""
    try:
        answer = input(f"{prompt} [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        print(file=sys.stderr)
        return False
    return answer in ("y", "yes")


# ---------------------------------------------------------------------------
# Subprocess helpers
# ---------------------------------------------------------------------------


def run_cmd(
    cmd: list[str],
    cwd: Optional[str] = None,
    check: bool = True,
) -> subprocess.CompletedProcess:
    """Run *cmd* and return the CompletedProcess.

    stdout/stderr are captured as strings.  If *check* is True a non-zero
    exit code raises ``subprocess.CalledProcessError``.
    """
    return subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=True,
        text=True,
        check=check,
    )


def run_git(
    *args: str,
    cwd: Optional[str] = None,
    check: bool = True,
) -> subprocess.CompletedProcess:
    """Thin wrapper: ``run_cmd(["git", *args], ...)``."""
    return run_cmd(["git", *args], cwd=cwd, check=check)
