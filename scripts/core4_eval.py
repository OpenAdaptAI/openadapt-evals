#!/usr/bin/env python3
"""Deterministic wrapper for running/inspecting core4 WAA trials.

Examples:
  # Run Trial 2 and 3 with a single deterministic runstamp
  uv run python scripts/core4_eval.py run --trials 2,3 --vm-ip 172.173.66.131

  # Resume only remaining conditions in Trial 1 (start index 6)
  uv run python scripts/core4_eval.py run --trials 1 --runstamp 20260305_154420 --start-from 6 --vm-ip 172.173.66.131

  # Summarize scores for all trials with this runstamp
  uv run python scripts/core4_eval.py status --runstamp 20260305_154420
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path


CORE4_TASKS = (
    "04d9aeaf-7bed-4024-bedb-e10e6f00eb7f-WOS,"
    "0bf05a7d-b28b-44d2-955a-50b41e24012a-WOS,"
    "0e763496-b6bb-4508-a427-fad0b6c3e195-WOS,"
    "70745df8-f2f5-42bd-8074-fbc10334fcc5-2-WOS"
)


def parse_trials(value: str) -> list[int]:
    trials: list[int] = []
    for part in value.split(","):
        part = part.strip()
        if not part:
            continue
        t = int(part)
        if t <= 0:
            raise ValueError(f"Invalid trial number: {t}")
        trials.append(t)
    if not trials:
        raise ValueError("No trial numbers provided")
    return trials


def _run_cmd(cmd: list[str], cwd: Path, dry_run: bool = False) -> int:
    print("$ " + " ".join(cmd))
    if dry_run:
        return 0
    result = subprocess.run(cmd, cwd=str(cwd))
    return result.returncode


def cmd_run(args: argparse.Namespace) -> int:
    repo_root = Path(__file__).resolve().parent.parent
    run_dc = Path(__file__).resolve().parent / "run_dc_eval.py"
    runstamp = args.runstamp or datetime.now().strftime("%Y%m%d_%H%M%S")
    trials = parse_trials(args.trials)

    print(f"runstamp={runstamp}")
    print(f"trials={trials}")
    print(f"tasks={args.tasks}")

    all_ok = True
    for t in trials:
        out = Path(args.output_root) / f"repeat_core4_trial{t}_{runstamp}"
        cmd = [
            sys.executable,
            str(run_dc),
            "--tasks",
            args.tasks,
            "--demo-dir",
            args.demo_dir,
            "--max-steps",
            str(args.max_steps),
            "--output",
            str(out),
            "--server",
            args.server,
            "--agent",
            args.agent,
            "--vm-user",
            args.vm_user,
        ]
        if args.evaluate_url:
            cmd.extend(["--evaluate-url", args.evaluate_url])
        if args.vm_ip:
            cmd.extend(["--vm-ip", args.vm_ip])
        if args.start_from > 0:
            cmd.extend(["--start-from", str(args.start_from)])
        if args.zs_only:
            cmd.append("--zs-only")
        if args.dc_only:
            cmd.append("--dc-only")
        if args.controller:
            cmd.extend(
                [
                    "--controller",
                    "--max-retries",
                    str(args.max_retries),
                    "--max-replans",
                    str(args.max_replans),
                ]
            )
        if args.done_gate:
            cmd.extend(
                [
                    "--done-gate",
                    "--done-gate-max-overrides",
                    str(args.done_gate_max_overrides),
                    "--done-gate-threshold",
                    str(args.done_gate_threshold),
                ]
            )

        print(f"\n=== Trial {t} -> {out} ===")
        rc = _run_cmd(cmd, cwd=repo_root, dry_run=args.dry_run)
        print(f"=== Trial {t} rc={rc} ===")
        if rc != 0:
            all_ok = False
            if not args.continue_on_fail:
                return rc

    return 0 if all_ok else 1


def _safe_read_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def cmd_status(args: argparse.Namespace) -> int:
    repo_root = Path(__file__).resolve().parent.parent
    base = repo_root / args.output_root
    trials = parse_trials(args.trials)
    found_any = False

    for t in trials:
        trial_dir = base / f"repeat_core4_trial{t}_{args.runstamp}"
        if not trial_dir.exists():
            print(f"\n=== Trial {t} ({trial_dir.name}) ===")
            print("missing")
            continue

        found_any = True
        print(f"\n=== Trial {t} ({trial_dir.name}) ===")
        run_dirs = sorted([p for p in trial_dir.iterdir() if p.is_dir() and p.name.startswith("val_")])
        if not run_dirs:
            print("no val_* runs yet")
            continue

        for run_dir in run_dirs:
            summary = _safe_read_json(run_dir / "summary.json")
            if not summary:
                print(f"{run_dir.name:30s} pending")
                continue
            avg_score = summary.get("avg_score", "n/a")
            avg_steps = summary.get("avg_steps", "n/a")
            success_rate = summary.get("success_rate", "n/a")
            print(
                f"{run_dir.name:30s} "
                f"score={avg_score} success_rate={success_rate} steps={avg_steps}"
            )

    return 0 if found_any else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Core4 trial wrapper")
    sub = parser.add_subparsers(dest="cmd", required=True)

    run = sub.add_parser("run", help="Run one or more core4 trials")
    run.add_argument("--trials", default="1,2,3", help="Comma-separated trial numbers")
    run.add_argument("--runstamp", default=None, help="Reuse existing runstamp (YYYYMMDD_HHMMSS)")
    run.add_argument("--tasks", default=CORE4_TASKS, help="Task IDs CSV")
    run.add_argument("--demo-dir", default="annotated_demos")
    run.add_argument("--max-steps", type=int, default=15)
    run.add_argument("--output-root", default="benchmark_results")
    run.add_argument("--server", default="http://localhost:5001")
    run.add_argument("--evaluate-url", default=None,
                     help="Evaluate server URL (default: same as --server)")
    run.add_argument("--agent", default="api-claude-cu")
    run.add_argument("--vm-ip", default=None)
    run.add_argument("--vm-user", default="azureuser")
    run.add_argument("--start-from", type=int, default=0)
    run.add_argument("--zs-only", action="store_true")
    run.add_argument("--dc-only", action="store_true")
    run.add_argument("--controller", action="store_true")
    run.add_argument("--max-retries", type=int, default=2)
    run.add_argument("--max-replans", type=int, default=2)
    run.add_argument("--done-gate", action="store_true")
    run.add_argument("--done-gate-max-overrides", type=int, default=3)
    run.add_argument("--done-gate-threshold", type=float, default=1.0)
    run.add_argument("--continue-on-fail", action="store_true")
    run.add_argument("--dry-run", action="store_true")
    run.set_defaults(func=cmd_run)

    status = sub.add_parser("status", help="Summarize trial run artifacts")
    status.add_argument("--runstamp", required=True, help="Runstamp to inspect")
    status.add_argument("--trials", default="1,2,3", help="Comma-separated trial numbers")
    status.add_argument("--output-root", default="benchmark_results")
    status.set_defaults(func=cmd_status)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
