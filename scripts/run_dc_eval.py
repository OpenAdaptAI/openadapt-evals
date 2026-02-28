#!/usr/bin/env python3
"""Run demo-conditioned evaluation with auto-recovery.

Runs each task individually with its matching demo file. Includes:
- SSH tunnel health check + reconnect before each task
- WAA server health check with container restart if dead
- Retry on transient failures

Usage:
    # 3-task validation with ClaudeComputerUseAgent
    python scripts/run_dc_eval.py \
      --agent api-claude-cu \
      --tasks 0e763496,70745df8,fba2c100

    # All 12 tasks
    python scripts/run_dc_eval.py --agent api-claude-cu
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

import requests

HARDER_TASK_IDS = [
    "04d9aeaf-7bed-4024-bedb-e10e6f00eb7f-WOS",
    "0a0faba3-5580-44df-965d-f562a99b291c-WOS",
    "0bf05a7d-b28b-44d2-955a-50b41e24012a-WOS",
    "0e763496-b6bb-4508-a427-fad0b6c3e195-WOS",
    "4bcb1253-a636-4df4-8cb0-a35c04dfef31-WOS",
    "70745df8-f2f5-42bd-8074-fbc10334fcc5-2-WOS",
    "8b1ce5f2-59d2-4dcc-b0b0-666a714b9a14-WOS",
    "e2b5e914-ffe1-44d2-8e92-58f8c5d92bb2-WOS",
    "ec71221e-ac43-46f9-89b8-ee7d80f7e1c5-WOS",
    "fba2c100-79e8-42df-ae74-b592418d54f4-WOS",
    "INF-0d95d28a-9587-433b-a805-1fbe5467d598-WOS",
    "INF-5ac2891a-eacd-4954-b339-98abba077adb-WOS",
]


def short_id(task_id: str) -> str:
    return task_id[:8]


def _kill_tunnels():
    subprocess.run(
        "ps aux | grep 'ssh.*5001' | grep -v grep | awk '{print $2}' | xargs kill 2>/dev/null",
        shell=True, capture_output=True,
    )


def _start_tunnel(vm_user: str, vm_ip: str) -> bool:
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


def _probe(server: str, timeout: int = 10) -> bool:
    try:
        resp = requests.get(f"{server}/probe", timeout=timeout)
        return resp.ok
    except Exception:
        return False


def _setup_eval_proxy(vm_user: str, vm_ip: str) -> bool:
    """(Re-)establish socat proxy for the evaluate server on the VM.

    Docker port forwarding for port 5050 is broken due to QEMU's custom
    bridge networking (--cap-add NET_ADMIN).  Work around it by restarting
    the socat-waa-evaluate systemd service on the VM host.  The service is
    installed during pool creation (see DOCKER_SETUP_SCRIPT in pool.py).
    The SSH tunnel maps local 5050 -> VM 5051.

    Falls back to the legacy nohup socat approach if the systemd service
    is not installed (e.g. on older VMs provisioned before this change).
    """
    # Try systemd service first (preferred: auto-restarts on failure)
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
        "  </dev/null >/dev/null 2>&1 &; "
        "fi"
    )
    result = subprocess.run(
        ["ssh", "-o", "StrictHostKeyChecking=no", f"{vm_user}@{vm_ip}", script],
        capture_output=True, timeout=30,
    )
    if result.returncode != 0:
        print(f"  socat proxy setup failed: {result.stderr.decode()}")
        return False
    print("  socat proxy for evaluate server established (VM:5051 -> container:5050)")
    return True


def _restart_container(vm_user: str, vm_ip: str) -> bool:
    """Restart Windows via QEMU monitor reset, falling back to docker restart.

    The QEMU monitor approach (``system_reset`` on port 7100) is preferred
    because it performs a reliable hard reset without killing the container.
    Falls back to ``docker restart winarena`` if the QEMU monitor is
    unreachable (e.g. ``nc`` not installed in the container).
    """
    from openadapt_evals.infrastructure.qemu_reset import QEMUResetManager

    mgr = QEMUResetManager(vm_ip=vm_ip, ssh_user=vm_user, timeout_seconds=300)

    # Try QEMU monitor reset first (preferred)
    if mgr.is_qemu_monitor_reachable():
        print("  Resetting Windows via QEMU monitor (system_reset)...")
        if mgr.reset_windows():
            print("  QEMU reset sent, re-establishing evaluate proxy...")
            _setup_eval_proxy(vm_user, vm_ip)
            return True
        print("  QEMU reset command failed, falling back to docker restart...")
    else:
        print("  QEMU monitor unreachable, falling back to docker restart...")

    # Fallback: docker restart
    print("  Restarting WAA container (docker restart winarena)...")
    result = subprocess.run(
        ["ssh", "-o", "StrictHostKeyChecking=no", f"{vm_user}@{vm_ip}",
         "docker restart winarena"],
        capture_output=True, timeout=120,
    )
    if result.returncode != 0:
        print(f"  Container restart failed: {result.stderr.decode()}")
        return False
    print("  Container restarted, re-establishing evaluate proxy...")
    _setup_eval_proxy(vm_user, vm_ip)
    return True


def ensure_waa_ready(
    server: str,
    vm_user: str,
    vm_ip: str,
    max_wait: int = 420,
    evaluate_url: str | None = None,
) -> bool:
    """Ensure WAA is reachable, recovering via tunnel reconnect or container restart.

    Recovery sequence:
    1. Probe → OK: return True
    2. Reconnect tunnel → Probe → OK: return True
    3. Restart container → Reconnect tunnel → Wait for probe: return True/False

    If evaluate_url is provided, both the WAA server and evaluate server must respond.
    """
    # Step 1: Quick probe
    if _probe(server) and (evaluate_url is None or _probe(evaluate_url)):
        return True

    # Step 2: Reconnect tunnel + ensure socat proxy
    print("  WAA unreachable, reconnecting tunnel...")
    _kill_tunnels()
    time.sleep(1)
    _setup_eval_proxy(vm_user, vm_ip)
    if _start_tunnel(vm_user, vm_ip):
        time.sleep(3)
        if _probe(server) and (evaluate_url is None or _probe(evaluate_url)):
            print("  Tunnel reconnected, WAA ready!")
            return True

    # Step 3: Tunnel up but WAA not responding → container restart
    print("  Tunnel OK but WAA server dead, restarting container...")
    _kill_tunnels()
    if not _restart_container(vm_user, vm_ip):
        return False

    # Wait for Windows to boot + Flask server to start
    time.sleep(10)
    _kill_tunnels()
    time.sleep(1)
    if not _start_tunnel(vm_user, vm_ip):
        print("  Failed to reconnect tunnel after restart")
        return False

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


def main() -> int:
    parser = argparse.ArgumentParser(description="Run DC eval with auto-recovery")
    parser.add_argument("--agent", default="api-claude-cu", help="Agent type")
    parser.add_argument("--demo-dir", default="annotated_demos", help="Demo directory")
    parser.add_argument("--server", default="http://localhost:5001")
    parser.add_argument("--evaluate-url", default="http://localhost:5050")
    parser.add_argument("--max-steps", type=int, default=15)
    parser.add_argument("--output", default="benchmark_results")
    parser.add_argument("--tasks", help="Comma-separated task IDs or prefixes (default: all 12)")
    parser.add_argument("--start-from", type=int, default=0, help="Task index to start from")
    parser.add_argument("--vm-ip", default="172.173.66.131", help="VM IP")
    parser.add_argument("--vm-user", default="azureuser", help="VM SSH user")
    parser.add_argument("--zs-only", action="store_true", help="Run zero-shot only (no demo)")
    parser.add_argument("--dc-only", action="store_true", help="Run demo-conditioned only")
    args = parser.parse_args()

    demo_dir = Path(args.demo_dir)
    output_dir = Path(args.output)

    # Resolve task IDs (support prefix matching)
    if args.tasks:
        raw_ids = [t.strip() for t in args.tasks.split(",")]
        task_ids = []
        for raw in raw_ids:
            matches = [tid for tid in HARDER_TASK_IDS if tid.startswith(raw)]
            if len(matches) == 1:
                task_ids.append(matches[0])
            elif len(matches) > 1:
                print(f"Ambiguous prefix '{raw}': {matches}")
                return 1
            else:
                task_ids.append(raw)  # Use as-is
    else:
        task_ids = HARDER_TASK_IDS

    # Build run conditions
    conditions = []  # (task_id, run_name, demo_path_or_None)
    for tid in task_ids:
        sid = short_id(tid)
        if not args.dc_only:
            conditions.append((tid, f"val_zs_{sid}", None))
        if not args.zs_only:
            demo_path = demo_dir / f"{tid}.txt"
            if not demo_path.exists():
                demo_path = demo_dir / f"{tid}.json"
            if not demo_path.exists():
                print(f"WARNING: No demo for {tid}, skipping DC condition")
                continue
            conditions.append((tid, f"val_dc_{sid}", demo_path))

    print(f"Eval: {len(conditions)} runs ({len(task_ids)} tasks) with {args.agent}")
    print(f"VM: {args.vm_ip}")
    print()

    # Verify initial WAA health
    if not ensure_waa_ready(args.server, args.vm_user, args.vm_ip, evaluate_url=args.evaluate_url):
        print("ERROR: Cannot reach WAA server or evaluate server")
        return 1

    results = {}
    start_time = time.time()

    for i, (tid, run_name, demo_path) in enumerate(conditions):
        if i < args.start_from:
            print(f"[{i+1}/{len(conditions)}] Skipping {run_name}")
            continue

        # Health check before each run
        if not ensure_waa_ready(args.server, args.vm_user, args.vm_ip, evaluate_url=args.evaluate_url):
            print(f"  Skipping {run_name} - WAA unreachable after recovery")
            results[run_name] = {"status": "SKIP", "returncode": -1, "elapsed_s": 0}
            continue

        cond_label = "DC" if demo_path else "ZS"
        print(f"{'=' * 60}")
        print(f"[{i+1}/{len(conditions)}] {cond_label}: {tid}")
        if demo_path:
            print(f"  Demo: {demo_path.name} ({demo_path.stat().st_size} bytes)")
        print(f"  Run: {run_name}")
        print(f"{'=' * 60}")

        task_start = time.time()

        cmd = [
            sys.executable, "-m", "openadapt_evals.benchmarks.cli",
            "run",
            "--agent", args.agent,
            "--tasks", tid,
            "--server", args.server,
            "--evaluate-url", args.evaluate_url,
            "--max-steps", str(args.max_steps),
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

        print(f"\n  -> {status} ({elapsed:.0f}s)\n")

    # Summary
    total_time = time.time() - start_time
    ok = sum(1 for r in results.values() if r["returncode"] == 0)

    print(f"\n{'=' * 60}")
    print(f"EVAL SUMMARY ({args.agent})")
    print(f"{'=' * 60}")
    print(f"  Runs: {ok}/{len(results)} completed")
    print(f"  Total time: {total_time:.0f}s ({total_time/60:.1f}min)")
    print()

    for name, r in results.items():
        cond = r.get("condition", "?")
        print(f"  {name:30s}  {cond:2s}  {r['status']:15s}  {r['elapsed_s']:.0f}s")

    print(f"\n  Results in: {output_dir}/val_*/")

    return 0 if ok == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
