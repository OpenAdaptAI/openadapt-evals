#!/usr/bin/env python3
"""Deterministic CLI wrapper for the recurring 4-task WAA eval lane.

This script avoids ad-hoc copy/paste command chains by generating a stable
"command pack" and/or executing repeated trials programmatically.
"""

from __future__ import annotations

import argparse
import shlex
import subprocess
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
RUN_DC_EVAL = REPO_ROOT / "scripts" / "run_dc_eval.py"
DEFAULT_TASKS = "04d9aeaf,0bf05a7d,0e763496,70745df8"


@dataclass(frozen=True)
class TrialConfig:
    trial_num: int
    run_stamp: str
    output_root: Path
    lane_name: str

    def run_dir_name(self) -> str:
        return f"{self.lane_name}_trial{self.trial_num}_{self.run_stamp}"

    def output_arg(self) -> str:
        return str(self.output_root / self.run_dir_name())


def _bool_flag(enabled: bool, flag: str) -> list[str]:
    return [flag] if enabled else []


def _build_eval_cmd(args: argparse.Namespace, trial: TrialConfig) -> list[str]:
    cmd = [
        sys.executable,
        str(RUN_DC_EVAL),
        "--agent",
        args.agent,
        "--tasks",
        args.tasks,
        "--demo-dir",
        str(args.demo_dir),
        "--max-steps",
        str(args.max_steps),
        "--output",
        trial.output_arg(),
        "--server",
        args.server,
        "--vm-user",
        args.vm_user,
        "--transport-error-threshold",
        str(args.transport_error_threshold),
    ]
    if args.evaluate_url:
        cmd.extend(["--evaluate-url", args.evaluate_url])
    if args.vm_ip:
        cmd.extend(["--vm-ip", args.vm_ip])
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
    cmd.extend(_bool_flag(args.clean_desktop, "--clean-desktop"))
    cmd.extend(_bool_flag(args.force_tray_icons, "--force-tray-icons"))
    if args.waa_image_version:
        cmd.extend(["--waa-image-version", args.waa_image_version])
    return cmd


def _build_trials(args: argparse.Namespace) -> list[TrialConfig]:
    return [
        TrialConfig(
            trial_num=i,
            run_stamp=args.run_stamp,
            output_root=args.output_root,
            lane_name=args.lane_name,
        )
        for i in range(args.start_trial, args.start_trial + args.trials)
    ]


def _render_pack(args: argparse.Namespace, trials: list[TrialConfig]) -> str:
    lines = [
        "#!/usr/bin/env bash",
        "set -euo pipefail",
        "",
        f"cd {shlex.quote(str(REPO_ROOT))}",
        "",
        f'echo "Running {len(trials)} trial(s) for lane: {args.lane_name}"',
        "",
    ]
    for trial in trials:
        cmd = _build_eval_cmd(args, trial)
        lines.append(f'echo "\\n=== Trial {trial.trial_num} / stamp {args.run_stamp} ==="')
        lines.append(shlex.join(cmd))
    lines.append("")
    return "\n".join(lines)


def cmd_pack(args: argparse.Namespace) -> int:
    trials = _build_trials(args)
    args.output_root.mkdir(parents=True, exist_ok=True)
    pack_text = _render_pack(args, trials)
    pack_path = args.output_root / f"{args.lane_name}_resume_pack_{args.run_stamp}.sh"
    pack_path.write_text(pack_text, encoding="utf-8")
    print(pack_text)
    print(f"\nPack written: {pack_path}")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    trials = _build_trials(args)
    args.output_root.mkdir(parents=True, exist_ok=True)
    failures: list[tuple[int, int]] = []

    print(f"Repo root: {REPO_ROOT}")
    print(f"Trials: {len(trials)}")
    print(f"Tasks: {args.tasks}")
    print(f"Demo dir: {args.demo_dir}")
    print(f"Output root: {args.output_root}")

    for trial in trials:
        cmd = _build_eval_cmd(args, trial)
        print(f"\n=== Trial {trial.trial_num} ===")
        print(shlex.join(cmd))
        if args.dry_run:
            continue

        result = subprocess.run(cmd)
        if result.returncode != 0:
            failures.append((trial.trial_num, result.returncode))
            if args.fail_fast:
                break

    if failures:
        print("\nFailures:")
        for trial_num, rc in failures:
            print(f"  trial {trial_num}: rc={rc}")
        return 1

    print("\nAll requested trials completed.")
    return 0


def _common_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--tasks", default=DEFAULT_TASKS, help="Comma-separated task IDs/prefixes")
    parser.add_argument(
        "--demo-dir",
        type=Path,
        default=REPO_ROOT / "annotated_demos_core4",
        help="Directory containing demo files",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=REPO_ROOT / "benchmark_results",
        help="Root directory for per-trial outputs",
    )
    parser.add_argument("--lane-name", default="repeat_core4", help="Logical lane name")
    parser.add_argument(
        "--run-stamp",
        default=datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S"),
        help="Stable run stamp used in output/pack names",
    )
    parser.add_argument("--trials", type=int, default=1, help="Number of sequential trials to run")
    parser.add_argument("--start-trial", type=int, default=1, help="First trial index")
    parser.add_argument("--agent", default="api-openai", help="Agent passed to run_dc_eval")
    parser.add_argument("--max-steps", type=int, default=15, help="Max steps per task")
    parser.add_argument("--server", default="http://localhost:5001", help="WAA server URL")
    parser.add_argument("--evaluate-url", default=None, help="Evaluate server URL (default: same as --server)")
    parser.add_argument("--vm-ip", default=None, help="VM IP (optional)")
    parser.add_argument("--vm-user", default="azureuser", help="VM SSH user")
    parser.add_argument(
        "--transport-error-threshold",
        type=int,
        default=8,
        help="Hard-recovery threshold passed through to run_dc_eval",
    )
    parser.add_argument("--controller", action="store_true", help="Enable controller mode")
    parser.add_argument("--max-retries", type=int, default=2, help="Controller retries")
    parser.add_argument("--max-replans", type=int, default=2, help="Controller replans")
    parser.add_argument("--clean-desktop", action="store_true", help="Enable clean desktop parity mode")
    parser.add_argument("--force-tray-icons", action="store_true", help="Force tray icon setup")
    parser.add_argument("--waa-image-version", default=None, help="Pinned WAA image version metadata")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    pack = sub.add_parser("pack", help="Generate a deterministic post-eval resume pack")
    _common_args(pack)
    pack.set_defaults(func=cmd_pack)

    run = sub.add_parser("run", help="Run repeated trials programmatically")
    _common_args(run)
    run.add_argument("--dry-run", action="store_true", help="Print commands only")
    run.add_argument("--fail-fast", action="store_true", help="Stop at first failed trial")
    run.set_defaults(func=cmd_run)

    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
