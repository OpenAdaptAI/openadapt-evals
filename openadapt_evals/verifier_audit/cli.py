"""``openadapt-evals audit-verifier``: find the wrong side effects a
benchmark's checker accepts.

Exit status: 0 when no confirmed false accept was found, 1 when at least one
was (so it can fail a CI job), 2 when the benchmark is not set up.
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path
from typing import Any, Sequence

from openadapt_evals.verifier_audit.adapters.base import SetupError
from openadapt_evals.verifier_audit.operators import OPERATORS
from openadapt_evals.verifier_audit.report import render
from openadapt_evals.verifier_audit.runner import audit, print_progress

BUILTIN = ("toy", "appworld")

EPILOG = """\
examples:
  openadapt-evals audit-verifier --benchmark toy
  openadapt-evals audit-verifier --benchmark appworld --tasks 22cc237_1
  openadapt-evals audit-verifier --benchmark appworld --split train --limit 0 --jobs 4
  openadapt-evals audit-verifier --benchmark mypkg.audit:MyAdapter --tasks t1,t2

A custom benchmark is any object with the methods of
openadapt_evals.verifier_audit.BenchmarkAdapter.
"""


def add_arguments(parser: argparse.ArgumentParser) -> argparse.ArgumentParser:
    parser.add_argument(
        "--benchmark",
        required=True,
        help="toy (built in, no download), appworld, or module:Class for your own adapter",
    )
    parser.add_argument("--tasks", help="comma-separated task ids (default: from --split)")
    parser.add_argument("--split", default=None, help="dataset split to take tasks from")
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="audit at most this many tasks from the split; 0 means all (default: 20)",
    )
    parser.add_argument(
        "--operators",
        default=",".join(OPERATORS),
        help=f"comma-separated subset of: {', '.join(OPERATORS)}",
    )
    parser.add_argument(
        "--ignore-fields",
        default="",
        help="comma-separated fields the task leaves free, as field or table.field; "
        "differences in them do not count (ids and timestamps are already ignored)",
    )
    parser.add_argument("--jobs", type=int, default=1, help="tasks to audit in parallel")
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="write the full report as JSON to this file",
    )
    parser.add_argument("--json", action="store_true", help="print the JSON report, not text")
    parser.add_argument(
        "--exit-zero",
        action="store_true",
        help="exit 0 even when a false accept is found",
    )
    group = parser.add_argument_group("AppWorld")
    group.add_argument(
        "--appworld-python",
        default=None,
        help="Python of the environment where AppWorld is installed (or APPWORLD_PYTHON)",
    )
    group.add_argument(
        "--appworld-root",
        default=None,
        help="AppWorld root holding data/ (or APPWORLD_ROOT)",
    )
    group.add_argument(
        "--keep-evidence",
        type=Path,
        default=None,
        help="also keep the worker's raw JSON (calls and records) in this directory; "
        "it contains AppWorld data, so do not publish it",
    )
    return parser


def make_adapter(args: argparse.Namespace) -> Any:
    name = args.benchmark
    if name == "toy":
        from openadapt_evals.verifier_audit.adapters.toy import ToyAdapter

        return ToyAdapter()
    if name == "appworld":
        from openadapt_evals.verifier_audit.adapters.appworld_bridge import AppWorldAdapter

        return AppWorldAdapter(
            python=args.appworld_python, root=args.appworld_root, keep_dir=args.keep_evidence
        )
    if ":" in name:
        module_name, _, attr = name.partition(":")
        try:
            factory = getattr(importlib.import_module(module_name), attr)
        except (ImportError, AttributeError) as exc:
            raise SetupError(f"cannot load adapter {name!r}: {exc}") from exc
        return factory()
    raise SetupError(
        f"unknown benchmark {name!r}: use one of {', '.join(BUILTIN)}, or module:Class"
    )


def run(args: argparse.Namespace) -> int:
    operators = [op.strip() for op in args.operators.split(",") if op.strip()]
    unknown = [op for op in operators if op not in OPERATORS]
    if unknown:
        print(f"unknown operator(s): {', '.join(unknown)}", file=sys.stderr)
        return 2
    try:
        adapter = make_adapter(args)
        if args.tasks:
            task_ids = [t.strip() for t in args.tasks.split(",") if t.strip()]
        else:
            task_ids = adapter.task_ids(args.split, args.limit or None)
    except SetupError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    if not task_ids:
        print("no tasks to audit", file=sys.stderr)
        return 2

    ignore = [f.strip() for f in args.ignore_fields.split(",") if f.strip()]
    result = audit(
        adapter,
        task_ids,
        operators,
        jobs=args.jobs,
        progress=print_progress,
        ignore_fields=ignore,
    )
    payload = result.to_dict()
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(render(result))
        if args.out is not None:
            print(f"\nFull report: {args.out}")
    if result.false_accepts and not args.exit_zero:
        return 1
    return 0


def build_parser(prog: str = "openadapt-evals audit-verifier") -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=prog,
        description="Edit correct benchmark runs one change at a time, replay them, and "
        "report which edits the benchmark's own verifier passes although the end state "
        "is wrong.",
        epilog=EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    return add_arguments(parser)


def main(argv: Sequence[str] | None = None) -> int:
    return run(build_parser("python -m openadapt_evals.verifier_audit").parse_args(argv))
