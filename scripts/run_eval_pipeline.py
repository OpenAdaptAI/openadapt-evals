#!/usr/bin/env python3
"""End-to-end eval pipeline: demo generation + VM lifecycle + ZS/DC evaluation.

Orchestrates the full evaluation flow:
  Phase 1 (parallel): generate VLM demos for new recordings + start VM if deallocated
  Phase 2 (sequential): establish SSH tunnels, socat proxy, wait for WAA readiness
  Phase 3: run ZS and DC evaluations via run_dc_eval logic
  Phase 4: print results summary

Usage:
    # Run everything for all recordings that have demos
    python scripts/run_eval_pipeline.py

    # Run for specific task(s)
    python scripts/run_eval_pipeline.py --tasks 04d9aeaf

    # Dry run (show what would happen)
    python scripts/run_eval_pipeline.py --tasks 04d9aeaf --dry-run

    # Override defaults
    python scripts/run_eval_pipeline.py \\
        --recordings waa_recordings \\
        --demo-dir demo_prompts_vlm \\
        --agent api-claude-cu \\
        --max-steps 15 \\
        --vm-name waa-pool-00 \\
        --zs-only
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

# ---------------------------------------------------------------------------
# Repo root = parent of scripts/
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RECORDINGS = REPO_ROOT / "waa_recordings"
DEFAULT_DEMO_DIR = REPO_ROOT / "demo_prompts_vlm"
DEFAULT_OUTPUT = REPO_ROOT / "benchmark_results"
DEFAULT_VM_NAME = "waa-pool-00"
DEFAULT_RESOURCE_GROUP = "openadapt-agents"
DEFAULT_VM_USER = "azureuser"


# ── Phase 1a: Demo generation ─────────────────────────────────────────────


def _find_recordings_needing_demos(
    recordings_dir: Path,
    demo_dir: Path,
    task_filter: list[str] | None = None,
) -> list[tuple[Path, str]]:
    """Return (task_dir, task_id) pairs that have recordings but no demo file."""
    missing = []
    for task_dir in sorted(recordings_dir.iterdir()):
        if not task_dir.is_dir():
            continue
        # Prefer meta_refined.json, fall back to meta.json
        meta_path = task_dir / "meta_refined.json"
        if not meta_path.exists():
            meta_path = task_dir / "meta.json"
        if not meta_path.exists():
            continue

        task_id = task_dir.name

        # Apply task filter (prefix matching)
        if task_filter:
            if not any(task_id.startswith(f) for f in task_filter):
                continue

        demo_path = demo_dir / f"{task_id}.txt"
        if not demo_path.exists():
            missing.append((task_dir, task_id))

    return missing


def _generate_demos(
    recordings_dir: Path,
    demo_dir: Path,
    task_filter: list[str] | None = None,
    provider: str = "openai",
    model: str | None = None,
) -> list[str]:
    """Generate VLM demos for recordings that don't have one yet.

    Returns list of task IDs that were generated.
    """
    missing = _find_recordings_needing_demos(recordings_dir, demo_dir, task_filter)
    if not missing:
        print("[demos] All recordings already have demo files")
        return []

    demo_dir.mkdir(parents=True, exist_ok=True)
    print(f"[demos] Generating VLM demos for {len(missing)} recording(s)...")

    generated = []
    for task_dir, task_id in missing:
        print(f"[demos] {task_id[:12]}...")

        cmd = [
            sys.executable, str(REPO_ROOT / "scripts" / "convert_recording_to_demo.py"),
            "--recordings", str(recordings_dir),
            "--output", str(demo_dir),
            "--mode", "vlm",
            "--provider", provider,
            "--task", task_id[:8],
        ]
        if model:
            cmd.extend(["--model", model])

        result = subprocess.run(cmd, timeout=600)
        if result.returncode == 0:
            print(f"[demos]   -> done")
            generated.append(task_id)
        else:
            print(f"[demos]   ERROR: exit code {result.returncode}")

    return generated


# ── Phase 1b: VM lifecycle ─────────────────────────────────────────────────


def _vm_state(vm_name: str, resource_group: str) -> str:
    """Get VM power state via Azure CLI.

    Returns e.g. "VM running", "VM deallocated", or "" on error.
    """
    result = subprocess.run(
        [
            "az", "vm", "get-instance-view",
            "--name", vm_name,
            "--resource-group", resource_group,
            "--query", "instanceView.statuses[1].displayStatus",
            "-o", "tsv",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    return result.stdout.strip()


def _vm_start(vm_name: str, resource_group: str) -> bool:
    """Start a deallocated VM. Returns True on success."""
    print(f"[vm] Starting {vm_name}...")
    result = subprocess.run(
        [
            "az", "vm", "start",
            "--name", vm_name,
            "--resource-group", resource_group,
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )
    if result.returncode != 0:
        print(f"[vm] Start failed: {result.stderr.strip()}")
        return False
    print(f"[vm] {vm_name} started")
    return True


def _wait_ssh(vm_ip: str, vm_user: str, timeout: int = 180) -> bool:
    """Wait until SSH is reachable."""
    deadline = time.time() + timeout
    print(f"[vm] Waiting for SSH on {vm_ip}...")
    while time.time() < deadline:
        result = subprocess.run(
            [
                "ssh",
                "-o", "StrictHostKeyChecking=no",
                "-o", "ConnectTimeout=5",
                "-o", "BatchMode=yes",
                f"{vm_user}@{vm_ip}",
                "echo ok",
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode == 0:
            print(f"[vm] SSH ready")
            return True
        time.sleep(5)
    print(f"[vm] SSH timeout after {timeout}s")
    return False


def _ensure_vm_running(
    vm_name: str,
    resource_group: str,
) -> str | None:
    """Ensure VM is running. Returns VM IP or None on failure.

    Starts the VM if deallocated, then resolves its IP.
    """
    state = _vm_state(vm_name, resource_group)
    print(f"[vm] {vm_name}: {state or '(unknown)'}")

    if "running" in state.lower():
        return _resolve_ip(vm_name, resource_group)

    if "deallocated" in state.lower() or "stopped" in state.lower():
        if not _vm_start(vm_name, resource_group):
            return None
        return _resolve_ip(vm_name, resource_group)

    # Unknown state
    print(f"[vm] Unexpected state: {state}")
    return None


def _resolve_ip(vm_name: str, resource_group: str) -> str | None:
    """Get public IP for a VM via Azure CLI."""
    result = subprocess.run(
        [
            "az", "vm", "list-ip-addresses",
            "--name", vm_name,
            "--resource-group", resource_group,
            "--query", "[0].virtualMachine.network.publicIpAddresses[0].ipAddress",
            "-o", "tsv",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    ip = result.stdout.strip()
    if ip:
        print(f"[vm] IP: {ip}")
        return ip
    print(f"[vm] Could not resolve IP for {vm_name}")
    return None


def _ensure_container_running(vm_user: str, vm_ip: str) -> bool:
    """Ensure the WAA Docker container is running on the VM.

    After VM deallocate/start, the container may be in 'Exited' state.
    """
    result = subprocess.run(
        [
            "ssh", "-o", "StrictHostKeyChecking=no", "-o", "ConnectTimeout=10",
            f"{vm_user}@{vm_ip}",
            "docker inspect -f '{{.State.Running}}' winarena 2>/dev/null || echo missing",
        ],
        capture_output=True, text=True, timeout=30,
    )
    state = result.stdout.strip()

    if state == "true":
        print("[vm] WAA container already running")
        return True

    if state == "missing":
        print("[vm] WARNING: No winarena container found")
        return False

    # Container exists but not running — restart it
    print("[vm] WAA container not running, starting...")
    result = subprocess.run(
        [
            "ssh", "-o", "StrictHostKeyChecking=no",
            f"{vm_user}@{vm_ip}",
            "docker start winarena",
        ],
        capture_output=True, text=True, timeout=60,
    )
    if result.returncode == 0:
        print("[vm] WAA container started")
        return True

    print(f"[vm] Failed to start container: {result.stderr.strip()}")
    return False


def _deallocate_vm(vm_name: str, resource_group: str) -> bool:
    """Deallocate VM to stop billing.

    Uses raw ``az vm deallocate`` because the built-in ``oa-vm deallocate``
    hardcodes ``VM_NAME = "waa-eval-vm"`` and doesn't accept a ``--name``
    parameter, so it won't work for pool-style VMs like ``waa-pool-00``.
    """
    print(f"\n[vm] Deallocating {vm_name} (stops billing)...")
    result = subprocess.run(
        [
            "az", "vm", "deallocate",
            "--name", vm_name,
            "--resource-group", resource_group,
            "--no-wait",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        print(f"[vm] Deallocate failed: {result.stderr.strip()}")
        return False
    print(f"[vm] Deallocate initiated (async). Billing will stop shortly.")
    return True


# ── Phase 2: Connectivity ─────────────────────────────────────────────────


def _kill_tunnels() -> None:
    """Kill all SSH tunnels matching port 5001."""
    subprocess.run(
        "ps aux | grep 'ssh.*5001' | grep -v grep | awk '{print $2}' | xargs kill 2>/dev/null",
        shell=True, capture_output=True,
    )


def _start_tunnel(vm_user: str, vm_ip: str) -> bool:
    """Establish SSH tunnel for WAA ports (5001, 5050, 8006)."""
    cmd = [
        "ssh", "-f", "-N",
        "-o", "StrictHostKeyChecking=no",
        "-o", "ServerAliveInterval=15",
        "-o", "ServerAliveCountMax=3",
        "-o", "TCPKeepAlive=yes",
        "-o", "ExitOnForwardFailure=yes",
        "-L", "5001:localhost:5000",
        "-L", "5050:localhost:5051",
        "-L", "8006:localhost:8006",
        f"{vm_user}@{vm_ip}",
    ]
    result = subprocess.run(cmd, capture_output=True)
    return result.returncode == 0


def _setup_eval_proxy(vm_user: str, vm_ip: str) -> bool:
    """(Re-)establish socat proxy for the evaluate server on the VM."""
    script = (
        "if systemctl list-unit-files socat-waa-evaluate.service "
        "| grep -q socat-waa-evaluate; then "
        "  sudo systemctl restart socat-waa-evaluate.service; "
        "else "
        "  killall socat 2>/dev/null || true; sleep 1; "
        "  which socat >/dev/null 2>&1 "
        "  || sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq socat; "
        "  nohup socat TCP-LISTEN:5051,fork,reuseaddr "
        "  'EXEC:docker exec -i winarena socat - TCP\\:127.0.0.1\\:5050' "
        "  </dev/null >/dev/null 2>&1 & "
        "fi"
    )
    result = subprocess.run(
        ["ssh", "-o", "StrictHostKeyChecking=no", f"{vm_user}@{vm_ip}", script],
        capture_output=True, timeout=30,
    )
    if result.returncode != 0:
        print(f"  socat proxy setup failed: {result.stderr.decode()}")
        return False
    return True


def _probe(server: str, timeout: int = 10) -> bool:
    """HTTP probe to check if a server is alive."""
    import requests

    try:
        resp = requests.get(f"{server}/probe", timeout=timeout)
        return resp.ok
    except Exception:
        return False


def _ensure_waa_ready(
    server: str,
    vm_user: str,
    vm_ip: str,
    max_wait: int = 420,
    evaluate_url: str | None = None,
) -> bool:
    """Ensure WAA is reachable, recovering via tunnel reconnect if needed.

    Recovery sequence:
    1. Probe -> OK: return True
    2. Reconnect tunnel -> Probe -> OK: return True
    3. Wait for probe with timeout
    """
    if _probe(server) and (evaluate_url is None or _probe(evaluate_url)):
        return True

    print("  WAA unreachable, reconnecting tunnel...")
    _kill_tunnels()
    time.sleep(1)
    _setup_eval_proxy(vm_user, vm_ip)
    if _start_tunnel(vm_user, vm_ip):
        time.sleep(3)
        if _probe(server) and (evaluate_url is None or _probe(evaluate_url)):
            print("  Tunnel reconnected, WAA ready!")
            return True

    # Wait for WAA to come back
    deadline = time.time() + max_wait
    last_print = 0
    while time.time() < deadline:
        elapsed = int(time.time() - (deadline - max_wait))
        if elapsed - last_print >= 15:
            print(f"  [{elapsed}s] Waiting for WAA server...")
            last_print = elapsed
        if _probe(server, timeout=10) and (evaluate_url is None or _probe(evaluate_url, timeout=10)):
            print(f"  WAA ready after {elapsed}s!")
            return True
        time.sleep(10)

    print(f"  TIMEOUT: WAA not ready after {max_wait}s")
    return False


def _setup_connectivity(vm_ip: str, vm_user: str) -> bool:
    """Kill stale tunnels, establish fresh ones, set up socat proxy."""
    print("[conn] Killing stale SSH tunnels...")
    _kill_tunnels()
    time.sleep(1)

    print("[conn] Setting up socat proxy for evaluate server...")
    _setup_eval_proxy(vm_user, vm_ip)

    print("[conn] Establishing SSH tunnels (5001, 5050, 8006)...")
    if not _start_tunnel(vm_user, vm_ip):
        print("[conn] ERROR: Failed to establish SSH tunnels")
        return False

    time.sleep(2)
    print("[conn] Tunnels established")
    return True


def _wait_waa_ready(
    server: str = "http://localhost:5001",
    evaluate_url: str = "http://localhost:5050",
    timeout: int = 1200,
) -> bool:
    """Wait for WAA server and evaluate server to respond."""
    import requests

    deadline = time.time() + timeout
    last_print = 0
    start = time.time()

    print(f"[waa] Waiting for WAA readiness (timeout {timeout}s)...")
    while time.time() < deadline:
        elapsed = int(time.time() - start)
        if elapsed - last_print >= 15:
            print(f"[waa]   [{elapsed}s] probing...")
            last_print = elapsed

        try:
            waa_ok = requests.get(f"{server}/probe", timeout=10).ok
        except Exception:
            waa_ok = False

        try:
            eval_ok = requests.get(f"{evaluate_url}/probe", timeout=10).ok
        except Exception:
            eval_ok = False

        if waa_ok and eval_ok:
            print(f"[waa] WAA + evaluate server ready after {elapsed}s")
            return True
        if waa_ok and not eval_ok:
            # WAA is up but evaluate isn't — acceptable for ZS-only runs
            if elapsed > 60:
                print(f"[waa] WAA ready but evaluate server not responding (continuing)")
                return True

        time.sleep(10)

    print(f"[waa] TIMEOUT: not ready after {timeout}s")
    return False


# ── Phase 3: Run evaluations ──────────────────────────────────────────────


def _build_conditions(
    task_ids: list[str],
    demo_dir: Path,
    zs_only: bool = False,
    dc_only: bool = False,
) -> list[tuple[str, str, Path | None]]:
    """Build (task_id, run_name, demo_path_or_None) tuples."""
    conditions = []
    for tid in task_ids:
        sid = tid[:8]
        if not dc_only:
            conditions.append((tid, f"val_zs_{sid}", None))
        if not zs_only:
            demo_path = demo_dir / f"{tid}.txt"
            if not demo_path.exists():
                demo_path = demo_dir / f"{tid}.json"
            if demo_path.exists():
                conditions.append((tid, f"val_dc_{sid}", demo_path))
            else:
                print(f"[eval] WARNING: No demo for {tid[:12]}..., skipping DC condition")
    return conditions


def _run_eval(
    conditions: list[tuple[str, str, Path | None]],
    agent: str,
    server: str,
    evaluate_url: str,
    max_steps: int,
    output_dir: Path,
    vm_ip: str,
    vm_user: str,
) -> dict[str, dict]:
    """Run all eval conditions sequentially with health checks."""
    results = {}
    start_time = time.time()

    for i, (tid, run_name, demo_path) in enumerate(conditions):
        cond_label = "DC" if demo_path else "ZS"
        print(f"\n{'=' * 60}")
        print(f"[{i+1}/{len(conditions)}] {cond_label}: {tid[:40]}...")
        if demo_path:
            print(f"  Demo: {demo_path.name} ({demo_path.stat().st_size} bytes)")
        print(f"  Run: {run_name}")
        print(f"{'=' * 60}")

        # Health check before each run
        if not _ensure_waa_ready(server, vm_user, vm_ip, evaluate_url=evaluate_url):
            print(f"  Skipping {run_name} — WAA unreachable after recovery")
            results[run_name] = {
                "status": "SKIP",
                "returncode": -1,
                "elapsed_s": 0,
                "task_id": tid,
                "condition": cond_label,
            }
            continue

        task_start = time.time()

        cmd = [
            sys.executable, "-m", "openadapt_evals.benchmarks.cli",
            "run",
            "--agent", agent,
            "--tasks", tid,
            "--server", server,
            "--evaluate-url", evaluate_url,
            "--max-steps", str(max_steps),
            "--output", str(output_dir),
            "--run-name", run_name,
        ]
        if demo_path:
            cmd.extend(["--demo", str(demo_path.resolve())])

        result = subprocess.run(cmd)
        elapsed = time.time() - task_start

        status = "OK" if result.returncode == 0 else f"FAIL (rc={result.returncode})"
        results[run_name] = {
            "status": status,
            "returncode": result.returncode,
            "elapsed_s": elapsed,
            "task_id": tid,
            "condition": cond_label,
        }
        print(f"\n  -> {status} ({elapsed:.0f}s)")

    total_time = time.time() - start_time
    return results


# ── Phase 4: Summary ──────────────────────────────────────────────────────


def _print_summary(results: dict[str, dict], agent: str) -> None:
    ok = sum(1 for r in results.values() if r["returncode"] == 0)
    total_time = sum(r["elapsed_s"] for r in results.values())

    print(f"\n{'=' * 60}")
    print(f"PIPELINE SUMMARY ({agent})")
    print(f"{'=' * 60}")
    print(f"  Runs: {ok}/{len(results)} completed")
    print(f"  Total eval time: {total_time:.0f}s ({total_time/60:.1f}min)")
    print()

    for name, r in results.items():
        cond = r.get("condition", "?")
        print(f"  {name:30s}  {cond:2s}  {r['status']:15s}  {r['elapsed_s']:.0f}s")

    print()


# ── Main ──────────────────────────────────────────────────────────────────


def main() -> int:
    parser = argparse.ArgumentParser(
        description="End-to-end eval pipeline: demos + VM + ZS/DC evaluation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--tasks",
        help="Comma-separated task IDs or prefixes (default: all with recordings)",
    )
    parser.add_argument(
        "--recordings", default=str(DEFAULT_RECORDINGS),
        help=f"Recordings directory (default: {DEFAULT_RECORDINGS.name})",
    )
    parser.add_argument(
        "--demo-dir", default=str(DEFAULT_DEMO_DIR),
        help=f"Demo output directory (default: {DEFAULT_DEMO_DIR.name})",
    )
    parser.add_argument("--agent", default="api-claude-cu", help="Agent type")
    parser.add_argument("--max-steps", type=int, default=15)
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--server", default="http://localhost:5001")
    parser.add_argument("--evaluate-url", default="http://localhost:5050")
    parser.add_argument(
        "--vm-name", default=DEFAULT_VM_NAME, help="Azure VM name",
    )
    parser.add_argument(
        "--resource-group", default=DEFAULT_RESOURCE_GROUP,
    )
    parser.add_argument("--vm-user", default=DEFAULT_VM_USER)
    parser.add_argument("--vm-ip", default=None, help="VM IP (skip auto-detection)")
    parser.add_argument(
        "--vlm-provider", default="openai", help="VLM provider for demo generation",
    )
    parser.add_argument("--vlm-model", default=None, help="VLM model override")
    parser.add_argument("--zs-only", action="store_true", help="Zero-shot only")
    parser.add_argument("--dc-only", action="store_true", help="Demo-conditioned only")
    parser.add_argument(
        "--dry-run", action="store_true", help="Show what would happen without running",
    )
    parser.add_argument(
        "--skip-vm", action="store_true",
        help="Skip VM start (assume tunnels already up)",
    )
    parser.add_argument(
        "--vnc", action="store_true", default=True,
        help="Open VNC viewer in browser (default: True)",
    )
    parser.add_argument(
        "--no-vnc", dest="vnc", action="store_false",
        help="Do not open VNC viewer",
    )
    parser.add_argument(
        "--deallocate-after", action="store_true",
        help="Deallocate VM after eval completes (stops billing)",
    )
    args = parser.parse_args()

    recordings_dir = Path(args.recordings)
    demo_dir = Path(args.demo_dir)
    output_dir = Path(args.output)

    # Resolve task filter
    task_filter = None
    if args.tasks:
        task_filter = [t.strip() for t in args.tasks.split(",")]

    # ── Discover what we have ──────────────────────────────────────────

    # Find all recorded task IDs
    recorded_tasks = []
    for d in sorted(recordings_dir.iterdir()) if recordings_dir.exists() else []:
        if d.is_dir() and ((d / "meta.json").exists() or (d / "meta_refined.json").exists()):
            if task_filter is None or any(d.name.startswith(f) for f in task_filter):
                recorded_tasks.append(d.name)

    # Find all task IDs that already have demos
    existing_demos = set()
    if demo_dir.exists():
        for f in demo_dir.iterdir():
            if f.suffix == ".txt":
                existing_demos.add(f.stem)

    missing_demos = [t for t in recorded_tasks if t not in existing_demos]

    # Tasks eligible for eval = those with demos (or will have demos after generation)
    eval_tasks = recorded_tasks  # all recorded tasks (demos will be generated if missing)

    print(f"Pipeline Configuration")
    print(f"  Recordings: {recordings_dir} ({len(recorded_tasks)} task(s))")
    print(f"  Demo dir:   {demo_dir} ({len(existing_demos)} existing)")
    print(f"  Missing:    {len(missing_demos)} demo(s) to generate")
    print(f"  Agent:      {args.agent}")
    print(f"  VM:         {args.vm_name} ({args.resource_group})")
    print(f"  Conditions: {'ZS only' if args.zs_only else 'DC only' if args.dc_only else 'ZS + DC'}")
    print()

    if not recorded_tasks:
        print("ERROR: No recordings found. Record demos first.")
        return 1

    if args.dry_run:
        print("[dry-run] Phase 1a: Would generate demos for:")
        for t in missing_demos:
            print(f"  - {t}")
        if not missing_demos:
            print("  (none — all demos exist)")

        print(f"\n[dry-run] Phase 1b: Would check/start VM {args.vm_name}")

        conditions = _build_conditions(eval_tasks, demo_dir, args.zs_only, args.dc_only)
        # For dry-run, also count tasks that will have demos after generation
        if missing_demos and not args.zs_only:
            for t in missing_demos:
                if not any(c[0] == t and c[2] is not None for c in conditions):
                    conditions.append((t, f"val_dc_{t[:8]}", Path("(will be generated)")))

        print(f"\n[dry-run] Phase 3: Would run {len(conditions)} evaluation(s):")
        for tid, run_name, demo_path in conditions:
            cond = "DC" if demo_path else "ZS"
            print(f"  - {run_name} ({cond})")

        print("\n[dry-run] No actions taken.")
        return 0

    # ── Phase 1: Parallel setup ────────────────────────────────────────

    print(f"\n{'─' * 60}")
    print("PHASE 1: Parallel setup (demo generation + VM start)")
    print(f"{'─' * 60}\n")

    vm_ip = args.vm_ip
    phase1_errors = []

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {}

        # Thread A: Generate missing demos
        if missing_demos:
            futures["demos"] = pool.submit(
                _generate_demos,
                recordings_dir,
                demo_dir,
                task_filter,
                args.vlm_provider,
                args.vlm_model,
            )
        else:
            print("[demos] All demos already exist, skipping generation")

        # Thread B: Ensure VM is running
        if not args.skip_vm and vm_ip is None:
            futures["vm"] = pool.submit(
                _ensure_vm_running,
                args.vm_name,
                args.resource_group,
            )
        elif vm_ip:
            print(f"[vm] Using provided IP: {vm_ip}")
        else:
            print("[vm] Skipping VM start (--skip-vm)")

        # Wait for results
        for key, future in futures.items():
            try:
                result = future.result(timeout=600)
                if key == "vm":
                    if result is None:
                        phase1_errors.append("VM failed to start")
                    else:
                        vm_ip = result
                elif key == "demos":
                    if result:
                        print(f"[demos] Generated {len(result)} demo(s)")
            except Exception as e:
                phase1_errors.append(f"{key}: {e}")
                print(f"[{key}] ERROR: {e}")

    if phase1_errors and not args.skip_vm:
        print(f"\nPhase 1 errors: {phase1_errors}")
        if vm_ip is None:
            print("ERROR: Cannot proceed without VM IP")
            return 1

    # ── Phase 2: Connectivity ──────────────────────────────────────────

    if not args.skip_vm:
        print(f"\n{'─' * 60}")
        print("PHASE 2: Connectivity (SSH tunnels + WAA readiness)")
        print(f"{'─' * 60}\n")

        if not _wait_ssh(vm_ip, args.vm_user):
            print("ERROR: SSH not reachable")
            return 1

        if not _ensure_container_running(args.vm_user, vm_ip):
            print("ERROR: WAA container not running and could not be started")
            return 1

        if not _setup_connectivity(vm_ip, args.vm_user):
            print("ERROR: Failed to set up tunnels")
            return 1

        if args.vnc:
            vnc_url = f"http://localhost:8006"
            print(f"[vnc] Opening VNC viewer: {vnc_url}")
            subprocess.Popen(["open", vnc_url])

        if not _wait_waa_ready(args.server, args.evaluate_url):
            print("ERROR: WAA server not ready")
            return 1
    else:
        print("\n[conn] Skipping connectivity setup (--skip-vm)")

    # ── Phase 3: Run evaluations ───────────────────────────────────────

    print(f"\n{'─' * 60}")
    print("PHASE 3: Evaluation")
    print(f"{'─' * 60}")

    conditions = _build_conditions(eval_tasks, demo_dir, args.zs_only, args.dc_only)

    if not conditions:
        print("ERROR: No evaluation conditions to run")
        return 1

    print(f"\n  {len(conditions)} run(s) queued:")
    for tid, run_name, demo_path in conditions:
        cond = "DC" if demo_path else "ZS"
        print(f"    {run_name} ({cond})")
    print()

    results = _run_eval(
        conditions,
        agent=args.agent,
        server=args.server,
        evaluate_url=args.evaluate_url,
        max_steps=args.max_steps,
        output_dir=output_dir,
        vm_ip=vm_ip or "",
        vm_user=args.vm_user,
    )

    # ── Phase 4: Summary ──────────────────────────────────────────────

    _print_summary(results, args.agent)

    # ── Optional: Deallocate VM ───────────────────────────────────────

    if args.deallocate_after and not args.skip_vm:
        _deallocate_vm(args.vm_name, args.resource_group)

    ok = sum(1 for r in results.values() if r["returncode"] == 0)
    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
