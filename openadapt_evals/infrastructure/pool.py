"""Pool management for parallel WAA benchmark evaluation.

Provides a clean Python API for creating and managing pools of VMs,
distributing benchmark tasks across workers, and collecting results.

Supports multiple cloud providers via the VMProvider protocol.

Example:
    from openadapt_evals.infrastructure.pool import PoolManager

    manager = PoolManager()
    pool = manager.create(workers=4)
    ready = manager.wait()
    result = manager.run(tasks=10)
    manager.cleanup(confirm=False)

    # With custom VM manager:
    from openadapt_evals.infrastructure.azure_vm import AzureVMManager
    vm = AzureVMManager(resource_group="my-rg")
    manager = PoolManager(vm_manager=vm)

    # Or with AWS:
    from openadapt_evals.infrastructure.aws_vm import AWSVMManager
    vm = AWSVMManager(region="us-east-1")
    manager = PoolManager(vm_manager=vm)
"""

from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from threading import Event
from typing import TYPE_CHECKING, Any, Callable, Mapping

from openadapt_evals.infrastructure.azure_vm import (
    SSH_OPTS,
    AzureVMManager,
    ssh_run,
    wait_for_ssh,
)

if TYPE_CHECKING:
    from openadapt_evals.infrastructure.vm_provider import VMProvider
from openadapt_evals.infrastructure.vm_monitor import (
    PoolWorker,
    VMPool,
    VMPoolRegistry,
)

logger = logging.getLogger(__name__)
PROXY_SECRET = re.compile(r"^[A-Za-z0-9._~-]{16,512}$")


def _proxy_start_values(policy: dict[str, Any]) -> dict[str, str | int]:
    """Return Docker-safe values for one validated egress proxy."""

    from openadapt_evals.infrastructure.windows_pool_isolation import (
        validate_egress_policy,
    )

    parsed = validate_egress_policy(policy)
    proxy = parsed["proxy"]
    addresses = [*proxy["resolved_ipv4"], *proxy["resolved_ipv6"]]
    address = addresses[0]
    if ":" in address:
        address = f"[{address}]"
    return {
        "proxy_hostname": proxy["hostname"],
        "proxy_address": address,
        "proxy_port": proxy["port"],
    }


@dataclass
class PoolRunResult:
    """Result of running benchmark tasks across a pool."""

    total_tasks: int
    completed: int
    failed: int
    elapsed_seconds: float
    worker_results: list[tuple[str, int, int, str | None]]
    """List of (worker_name, completed, failed, error_or_none)."""

    terminal_receipts: tuple[Mapping[str, Any], ...] = ()
    """One centrally issued terminal receipt for each requested task."""


def validate_terminal_pool_result(
    result: PoolRunResult,
    *,
    expected_dispatches: Mapping[str, str],
) -> PoolRunResult:
    """Require closed task counts and one central receipt per dispatch."""

    task_count = len(expected_dispatches)
    expected_workers = set(expected_dispatches)
    expected_dispatch_ids = set(expected_dispatches.values())
    if (
        result.total_tasks != task_count
        or len(expected_dispatch_ids) != task_count
        or any(
            not isinstance(worker, str)
            or not worker
            or not isinstance(dispatch, str)
            or not dispatch
            for worker, dispatch in expected_dispatches.items()
        )
    ):
        raise RuntimeError("Qualified terminal expectations are not exact and unique.")
    if len(result.worker_results) != task_count:
        raise RuntimeError("A requested task has no worker terminal result.")
    rows: dict[str, tuple[str, int, int, str | None]] = {}
    for row in result.worker_results:
        if (
            not isinstance(row, tuple)
            or len(row) != 4
            or row[0] not in expected_workers
            or row[0] in rows
            or isinstance(row[1], bool)
            or not isinstance(row[1], int)
            or isinstance(row[2], bool)
            or not isinstance(row[2], int)
            or row[1] not in {0, 1}
            or row[2] not in {0, 1}
            or row[1] + row[2] != 1
        ):
            raise RuntimeError("A worker terminal result is not one closed task result.")
        if row[1] == 1 and row[3] is not None:
            raise RuntimeError("A completed worker terminal result carries an error.")
        rows[row[0]] = row
    if set(rows) != expected_workers:
        raise RuntimeError("Worker terminal results differ from the requested workers.")

    if len(result.terminal_receipts) != task_count:
        raise RuntimeError("A requested task has no central terminal receipt.")
    receipts_by_dispatch: dict[str, Mapping[str, Any]] = {}
    receipt_ids: set[str] = set()
    for receipt in result.terminal_receipts:
        if not isinstance(receipt, Mapping):
            raise RuntimeError("A central terminal receipt is invalid.")
        dispatch_id = receipt.get("dispatch_id_sha256")
        receipt_id = receipt.get("receipt_id_sha256")
        task_id = receipt.get("task_id_sha256")
        terminal_state = receipt.get("terminal_state")
        if (
            dispatch_id not in expected_dispatch_ids
            or dispatch_id in receipts_by_dispatch
            or not isinstance(receipt_id, str)
            or receipt_id in receipt_ids
            or not isinstance(task_id, str)
            or terminal_state
            not in {
                "VERIFIED",
                "SAFE_HALT",
                "RECONCILIATION_REQUIRED",
                "QUARANTINED",
                "PRELAUNCH_QUARANTINED",
            }
        ):
            raise RuntimeError("Central terminal receipt identities are not exact and unique.")
        receipts_by_dispatch[dispatch_id] = receipt
        receipt_ids.add(receipt_id)
    if set(receipts_by_dispatch) != expected_dispatch_ids:
        raise RuntimeError("Central terminal receipts differ from the requested dispatches.")

    for worker, dispatch_id in expected_dispatches.items():
        receipt_completed = (
            receipts_by_dispatch[dispatch_id]["terminal_state"] == "VERIFIED"
        )
        row_completed = rows[worker][1] == 1
        if row_completed != receipt_completed:
            raise RuntimeError(
                "A worker task count differs from its central terminal receipt."
            )

    completed = sum(
        receipt["terminal_state"] == "VERIFIED"
        for receipt in result.terminal_receipts
    )
    failed = task_count - completed
    row_completed = sum(row[1] for row in result.worker_results)
    row_failed = sum(row[2] for row in result.worker_results)
    if (
        result.completed != completed
        or result.failed != failed
        or row_completed != completed
        or row_failed != failed
        or result.completed + result.failed != result.total_tasks
    ):
        raise RuntimeError("Qualified terminal task counts do not close.")
    return result


def _build_postlaunch_terminal_evidence(
    *,
    manager: Any,
    admission: Any,
    dispatch: Any,
    process: Any,
    interrupt_requested: Event,
    poll_seconds: float = 5.0,
) -> Mapping[str, Any]:
    """Read one process to terminal state and quarantine an interrupted run."""

    from openadapt_evals.infrastructure.windows_worker_dispatch import (
        build_terminal_evidence,
        interrupt_process,
        read_process_terminal,
    )

    interrupt_evidence: Mapping[str, Any] | None = None
    while True:
        if interrupt_requested.is_set():
            interrupt_evidence = interrupt_process(manager, process)
            terminal_readback = read_process_terminal(manager, process)
            break
        try:
            terminal_readback = read_process_terminal(manager, process)
        except KeyboardInterrupt:
            interrupt_requested.set()
            continue
        if terminal_readback["state"] != "RUNNING":
            break
        interrupt_requested.wait(poll_seconds)
    return build_terminal_evidence(
        admission=admission,
        dispatch=dispatch,
        process=process,
        terminal_readback=terminal_readback,
        interrupt_evidence=interrupt_evidence,
    )


# Docker setup script template for WAA workers.
# {home_dir} is formatted at runtime with the provider's ssh_username home path.
DOCKER_SETUP_SCRIPT = """
set -e
export DEBIAN_FRONTEND=noninteractive

# Wait for apt lock (unattended upgrades on fresh VMs)
echo "Waiting for apt lock..."
while sudo fuser /var/lib/apt/lists/lock >/dev/null 2>&1 || sudo fuser /var/lib/dpkg/lock-frontend >/dev/null 2>&1; do
    sleep 5
done
echo "Apt lock released"

sudo DEBIAN_FRONTEND=noninteractive apt-get update -qq
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq docker.io
sudo systemctl start docker
sudo systemctl enable docker
sudo usermod -aG docker $USER

# Configure Docker to use persistent storage (NOT /mnt which is ephemeral
# and gets wiped on VM deallocate, breaking pool-resume)
sudo systemctl stop docker
sudo mkdir -p {home_dir}/docker
sudo bash -c 'echo "{{\\"data-root\\": \\"{home_dir}/docker\\"}}" > /etc/docker/daemon.json'
sudo systemctl start docker

# Pull base images (use sudo since usermod hasn't taken effect yet)
sudo docker pull dockurr/windows:latest
sudo docker pull windowsarena/winarena:latest

# Build waa-auto image from Dockerfile uploaded via SCP
# (build context at /tmp/waa-build/ contains Dockerfile + supporting files)
sudo docker build -t waa-auto:latest /tmp/waa-build/
rm -rf /tmp/waa-build

# Install socat and register systemd unit for the evaluate proxy
# (replaces the fragile nohup socat background process with a supervised service
# that auto-restarts on failure and survives container/VM restarts)
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq socat

sudo tee /etc/systemd/system/socat-waa-evaluate.service > /dev/null << 'UNIT'
[Unit]
Description=socat proxy for WAA /evaluate endpoint (VM:5051 -> container:5050)
After=docker.service
Requires=docker.service

[Service]
Type=simple
ExecStart=/usr/bin/socat TCP-LISTEN:5051,fork,reuseaddr EXEC:"docker exec -i winarena socat STDIO TCP:localhost:5050"
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT

sudo systemctl daemon-reload
sudo systemctl enable socat-waa-evaluate.service
"""

# Install one host-owned, fail-closed nftables boundary for the dedicated
# Windows guest. This runs for fresh and golden-image workers. The service
# restores the last checked policy before Docker can start after a reboot.
WINDOWS_EGRESS_BOOTSTRAP_SCRIPT = r"""
set -euo pipefail
export DEBIAN_FRONTEND=noninteractive
sudo DEBIAN_FRONTEND=noninteractive apt-get update -qq
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq conntrack nftables
sudo install -d -m 0700 /etc/openadapt
sudo tee /etc/openadapt/windows-egress.nft > /dev/null <<'NFT'
delete table inet oa_windows
add table inet oa_windows
add chain inet oa_windows input { type filter hook input priority -50; policy accept; }
add chain inet oa_windows forward { type filter hook forward priority -50; policy drop; }
add rule inet oa_windows input iifname "docker0" ct state established,related accept
add rule inet oa_windows input iifname "docker0" counter drop
add rule inet oa_windows forward iifname "docker0" counter drop
NFT
sudo chmod 0600 /etc/openadapt/windows-egress.nft
sudo tee /usr/local/sbin/openadapt-windows-egress-restore > /dev/null <<'SCRIPT'
#!/bin/sh
set -eu
nft list table inet oa_windows > /dev/null 2>&1 || nft add table inet oa_windows
nft -c -f /etc/openadapt/windows-egress.nft
nft -f /etc/openadapt/windows-egress.nft
conntrack -F >/dev/null
conntrack -F >/dev/null
install -d -m 0700 /var/lib/openadapt/windows-run-gates
find /var/lib/openadapt/windows-run-gates -mindepth 1 -maxdepth 1 -exec rm -rf -- {} +
SCRIPT
sudo chmod 0755 /usr/local/sbin/openadapt-windows-egress-restore
sudo tee /etc/systemd/system/openadapt-windows-egress.service > /dev/null <<'UNIT'
[Unit]
Description=OpenAdapt fail-closed Windows guest egress boundary
DefaultDependencies=no
After=local-fs.target
Before=network-pre.target docker.service
Wants=network-pre.target

[Service]
Type=oneshot
ExecStart=/usr/local/sbin/openadapt-windows-egress-restore
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable openadapt-windows-egress.service
sudo systemctl restart openadapt-windows-egress.service
"""

# WAA container start script template.
# The exact admitted egress proxy is also formatted at runtime. Direct guest
# egress is denied by nftables.
WAA_START_SCRIPT_TEMPLATE = """
# Check if container already running
if docker ps --format '{{{{.Names}}}}' | grep -q '^winarena$'; then
    # Container is up — ensure the socat proxy systemd service is running.
    # The service auto-restarts on failure, but we explicitly restart it here
    # in case the container was restarted externally.
    sudo systemctl restart socat-waa-evaluate.service 2>/dev/null || true
    echo "ALREADY_RUNNING"
    exit 0
fi

# Container not running, start it
docker rm -f winarena 2>/dev/null || true
sudo mkdir -p {home_dir}/waa-storage
sudo chown {ssh_username}:{ssh_username} {home_dir}/waa-storage
docker run -d --name winarena \\
  --device=/dev/kvm \\
  --cap-add NET_ADMIN \\
  --stop-timeout 120 \\
  -p 5000:5000 \\
  -p 5050:5050 \\
  -p 8006:8006 \\
  -p 7200:7200 \\
  -v {home_dir}/waa-storage:/storage \\
  -e VERSION=11e \\
  -e RAM_SIZE=8G \\
  -e CPU_CORES=4 \\
  -e DISK_SIZE=64G \\
  -e ARGUMENTS="-qmp tcp:0.0.0.0:7200,server,nowait" \\
  --add-host {proxy_hostname}={proxy_address} \\
  -e HTTPS_PROXY=https://{proxy_hostname}:{proxy_port} \\
  -e HTTP_PROXY=https://{proxy_hostname}:{proxy_port} \\
  -e NO_PROXY=localhost,127.0.0.1,172.30.0.2 \\
  {admitted_image} \\
  /entry.sh --prepare-image false --start-client false

# Start the socat proxy via systemd (installed during Docker setup).
# The systemd service auto-restarts on failure and survives reboots.
# Docker port forwarding for 5050 is broken by QEMU's --cap-add NET_ADMIN
# tap networking, so we proxy VM:5051 -> docker exec -> container:5050.
sudo systemctl restart socat-waa-evaluate.service
echo "STARTED"
"""


@dataclass
class PoolManager:
    """Manages a pool of VMs for parallel WAA benchmark evaluation.

    Provides the full pool lifecycle: create, wait, run, cleanup.
    Works with any VMProvider (Azure, AWS, etc.).

    Args:
        vm_manager: VMProvider instance (AzureVMManager or AWSVMManager).
        registry: VMPoolRegistry for persisting pool state.
        log_fn: Optional logging function with signature log_fn(step, message).
    """

    vm_manager: VMProvider = field(default_factory=AzureVMManager)
    registry: VMPoolRegistry = field(default_factory=VMPoolRegistry)
    log_fn: Any = None
    worker_trust_authority: Any = None
    external_task_session_authority: Any = None

    def _log(self, step: str, message: str, end: str = "\n") -> None:
        """Log a message using the configured log function or print."""
        if self.log_fn:
            self.log_fn(step, message, end=end)
        else:
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"[{timestamp}] [{step}] {message}", end=end, flush=True)

    @property
    def _ssh_username(self) -> str:
        """SSH username from the VM provider."""
        return self.vm_manager.ssh_username

    @property
    def _home_dir(self) -> str:
        """Home directory path for the VM provider's SSH user."""
        return f"/home/{self._ssh_username}"

    def create(
        self,
        workers: int = 3,
        auto_shutdown_hours: int = 4,
        use_acr: bool = False,
        image_id: str | None = None,
    ) -> VMPool:
        """Create a pool of VMs for parallel WAA evaluation.

        Creates VMs in parallel, installs Docker, and registers the pool.

        Args:
            workers: Number of worker VMs to create.
            auto_shutdown_hours: Hours until auto-shutdown (safety net).
            use_acr: If True, pull waa-auto from ACR instead of building.
            image_id: Azure Managed Image ID. If provided, skip Docker setup
                (image already has Docker + images pre-baked).

        Returns:
            Created VMPool.

        Raises:
            RuntimeError: If no VMs could be created.
        """
        if use_acr:
            raise RuntimeError(
                "One-step ACR provisioning has no admitted SSH identity. Create the "
                "worker with the local-build or golden-image path, then use the admitted "
                "ACR provisioning operation."
            )
        self._log("POOL", f"Creating pool with {workers} workers...")

        # Check for existing pool
        if self.registry.get_pool() is not None:
            raise RuntimeError("Pool already exists. Delete it first with: delete-pool")

        # Find available size/region
        self._log("POOL", "Finding available region and VM size...")
        vm_size, region, cost = self.vm_manager.find_available_size_and_region()
        self._log("POOL", f"Using {vm_size} (${cost:.2f}/hr) in {region}")

        if auto_shutdown_hours > 0:
            self._log("POOL", f"VMs will auto-shutdown in {auto_shutdown_hours} hours")

        # Create VMs in parallel
        self._log("POOL", f"Creating {workers} VMs in parallel...")
        workers_created: list[tuple[str, str]] = []

        def create_worker(worker_idx: int) -> tuple[str, str | None, str | None]:
            name = f"waa-pool-{worker_idx:02d}"

            # Check if VM already exists
            existing_ip = self.vm_manager.get_vm_ip(name)
            if existing_ip:
                return (name, existing_ip, None)

            try:
                vm_info = self.vm_manager.create_vm(
                    name=name,
                    region=region,
                    size=vm_size,
                    image_id=image_id,
                )
                ip = vm_info.get("publicIpAddress", "")
                return (name, ip, None)
            except RuntimeError as e:
                return (name, None, str(e))

        with ThreadPoolExecutor(max_workers=min(workers, 5)) as executor:
            futures = {executor.submit(create_worker, i): i for i in range(workers)}
            for future in as_completed(futures):
                name, ip, error = future.result()
                if error:
                    self._log("POOL", f"  {name}: FAILED - {error}")
                else:
                    self._log("POOL", f"  {name}: {ip}")
                    workers_created.append((name, ip))

        if not workers_created:
            raise RuntimeError("No VMs created successfully")

        self._log("POOL", f"\nCreated {len(workers_created)}/{workers} VMs")

        # Wait for SSH
        username = self._ssh_username
        self._log("POOL", "Waiting for SSH access...")
        workers_ready: list[tuple[str, str]] = []
        for name, ip in workers_created:
            if wait_for_ssh(ip, timeout=120, username=username):
                self._log("POOL", f"  {name}: SSH ready")
                workers_ready.append((name, ip))
                # Set auto-shutdown now that SSH is available
                if auto_shutdown_hours > 0:
                    self.vm_manager.set_auto_shutdown(name, auto_shutdown_hours)
            else:
                self._log("POOL", f"  {name}: SSH timeout")

        if not workers_ready:
            raise RuntimeError("No VMs have SSH access")

        # Install Docker on all VMs (skip if using golden image)
        if image_id:
            self._log("POOL", "Skipping Docker setup (using golden image)")
            workers_docker_ok = workers_ready
        else:
            self._log("POOL", "Installing Docker on all VMs...")
            home_dir = self._home_dir

            # Determine which setup script to use
            docker_script = DOCKER_SETUP_SCRIPT.format(home_dir=home_dir)
            def setup_docker(
                name_ip: tuple[str, str],
            ) -> tuple[str, bool, str]:
                name, ip = name_ip
                if not use_acr:
                    # Upload Docker build context (Dockerfile + supporting files)
                    waa_deploy_dir = Path(__file__).parent.parent / "waa_deploy"
                    subprocess.run(
                        ["ssh", *SSH_OPTS, f"{username}@{ip}", "mkdir -p /tmp/waa-build"],
                        capture_output=True,
                    )
                    required_files = [
                        "Dockerfile",
                        "evaluate_server.py",
                        "start_with_evaluate.sh",
                        "start_waa_server.bat",
                        "api_agent.py",
                    ]
                    for fname in required_files:
                        src = waa_deploy_dir / fname
                        if not src.exists():
                            return (name, False, f"Missing build file: {fname}")
                        scp_result = subprocess.run(
                            ["scp", *SSH_OPTS, str(src), f"{username}@{ip}:/tmp/waa-build/"],
                            capture_output=True,
                            text=True,
                        )
                        if scp_result.returncode != 0:
                            return (name, False, f"SCP failed for {fname}: {scp_result.stderr[:100]}")
                result = ssh_run(ip, docker_script, stream=False, step="DOCKER", username=username)
                error = result.stderr[:200] if result.stderr else ""
                return (name, result.returncode == 0, error)

            with ThreadPoolExecutor(max_workers=min(len(workers_ready), 5)) as executor:
                futures = {executor.submit(setup_docker, w): w[0] for w in workers_ready}
                workers_docker_ok: list[tuple[str, str]] = []
                for future in as_completed(futures):
                    name, success, error = future.result()
                    status = "Docker ready" if success else f"Docker FAILED: {error[:100]}"
                    self._log("POOL", f"  {name}: {status}")
                    if success:
                        workers_docker_ok.append((name, dict(workers_ready)[name]))

            if not workers_docker_ok:
                raise RuntimeError("Docker setup failed on all VMs")

        # Install and activate the host-owned egress boundary before a guest
        # can start. Do this for golden images too. A stale image policy cannot
        # become the new pool's initial policy because bootstrap writes the
        # fail-closed rule first.
        self._log("POOL", "Installing Windows guest egress boundaries...")

        def setup_egress_boundary(
            name_ip: tuple[str, str],
        ) -> tuple[str, bool, str]:
            name, ip = name_ip
            result = ssh_run(
                ip,
                WINDOWS_EGRESS_BOOTSTRAP_SCRIPT,
                stream=False,
                step="EGRESS",
                username=username,
            )
            error = result.stderr[:200] if result.stderr else ""
            return (name, result.returncode == 0, error)

        isolated_workers: list[tuple[str, str]] = []
        with ThreadPoolExecutor(max_workers=min(len(workers_docker_ok), 5)) as executor:
            futures = {
                executor.submit(setup_egress_boundary, worker): worker[0]
                for worker in workers_docker_ok
            }
            for future in as_completed(futures):
                name, success, error = future.result()
                status = (
                    "egress boundary ready"
                    if success
                    else f"egress FAILED: {error[:100]}"
                )
                self._log("POOL", f"  {name}: {status}")
                if success:
                    isolated_workers.append((name, dict(workers_docker_ok)[name]))

        if not isolated_workers:
            raise RuntimeError("Windows guest egress setup failed on all VMs")
        workers_docker_ok = isolated_workers

        # Register pool
        pool = self.registry.create_pool(
            workers=workers_docker_ok,
            resource_group=self.vm_manager.resource_scope,
            location=region,
            vm_size=vm_size,
        )
        pool.ssh_username = self._ssh_username
        self.registry.save()

        # Set auto-pause timer
        if auto_shutdown_hours > 0:
            from datetime import timedelta
            auto_pause_at = (datetime.now() + timedelta(hours=auto_shutdown_hours)).isoformat()
            pool.auto_pause_at = auto_pause_at
            pool.auto_pause_hours = auto_shutdown_hours
            self.registry.save()

        self._log("POOL", "=" * 60)
        self._log("POOL", f"Pool created: {pool.pool_id}")
        self._log("POOL", f"  Workers: {len(workers_docker_ok)}")
        self._log("POOL", f"  Region: {region}")
        self._log("POOL", f"  Size: {vm_size} (${cost:.2f}/hr)")
        self._log(
            "POOL",
            f"  Est. hourly cost: ${cost * len(workers_docker_ok):.2f}/hr",
        )
        if auto_shutdown_hours > 0:
            self._log("POOL", f"  Auto-shutdown: in {auto_shutdown_hours} hours")
        self._log("POOL", "")
        self._log("POOL", "Next steps:")
        self._log("POOL", "  1. Qualify each worker: pool-reset, pool-egress, pool-start")
        self._log("POOL", "  2. Wait for WAA ready: pool-wait")
        self._log("POOL", "  3. Run benchmark:      pool-run --tasks 154")
        self._log("POOL", "  4. Delete pool:        delete-pool")
        self._log("POOL", "=" * 60)

        return pool

    def wait(
        self,
        timeout_minutes: int = 30,
        start_containers: bool = False,
        qualification_dir: Path | None = None,
    ) -> list[PoolWorker]:
        """Wait for all pool workers to have WAA ready.

        This method does not start a guest. A caller must use the qualified
        reset, egress, and start sequence first.

        Args:
            timeout_minutes: Maximum minutes to wait for WAA readiness.
            start_containers: Legacy argument. A true value is refused.
            qualification_dir: Exact worker identity and egress policy directory.

        Returns:
            List of ready PoolWorker instances.

        Raises:
            RuntimeError: If no pool exists.
        """
        pool = self.registry.get_pool()
        if pool is None:
            raise RuntimeError("No active pool. Create one with: pool-create --workers N")

        self._log("POOL-WAIT", f"Pool: {pool.pool_id} ({len(pool.workers)} workers)")

        # Start WAA containers
        if start_containers:
            raise RuntimeError(
                "Ungated guest startup is disabled. Use pool-reset, pool-egress, "
                "and pool-start, then run pool-wait."
            )
        if qualification_dir is None:
            raise RuntimeError("Pool readiness requires the qualification directory.")

        # Wait for WAA readiness
        self._log(
            "POOL-WAIT",
            f"Waiting for WAA server on all workers (timeout: {timeout_minutes}m)...",
        )
        start_time = time.time()
        timeout_seconds = timeout_minutes * 60

        workers_pending = {w.name: w for w in pool.workers}
        workers_ready: list[PoolWorker] = []

        while workers_pending and (time.time() - start_time) < timeout_seconds:
            for name, worker in list(workers_pending.items()):
                try:
                    manager, _policy, _admission = self._qualified_isolation_manager(
                        worker,
                        qualification_dir,
                    )
                    ready, eval_ok = manager.probe_services(
                        run_id=worker.qualified_run_id,
                        policy_sha256=worker.qualified_egress_policy_sha256,
                        container_state_sha256=worker.qualified_container_state_sha256,
                        expires_at=worker.qualified_dispatch_expires_at,
                        live_nft_sha256=worker.qualified_live_nft_sha256,
                    )

                    if ready:
                        eval_status = ", evaluate: ok" if eval_ok else ", evaluate: not ready"
                        self._log("POOL-WAIT", f"  {name}: READY{eval_status}")
                        workers_ready.append(worker)
                        del workers_pending[name]
                        status = (
                            "qualified-ready"
                            if worker.status == "qualified-starting"
                            else "ready"
                        )
                        self.registry.update_worker(name, waa_ready=True, status=status)
                except Exception as exc:
                    logger.debug("Qualified readiness check failed for %s: %s", name, exc)

            if workers_pending:
                elapsed = int(time.time() - start_time)
                pending_names = ", ".join(workers_pending.keys())
                print(
                    f"\r  [{elapsed}s] Waiting for: {pending_names}...",
                    end="",
                    flush=True,
                )
                time.sleep(10)

        print()  # New line after progress

        if workers_pending:
            self._log(
                "POOL-WAIT",
                f"TIMEOUT: {len(workers_pending)} workers not ready",
            )
            for name in workers_pending:
                self._log(
                    "POOL-WAIT",
                    f"  {name}: not ready (check with: ssh {self._ssh_username}@{workers_pending[name].ip})",
                )

        self._log("POOL-WAIT", "=" * 60)
        self._log(
            "POOL-WAIT",
            f"Workers ready: {len(workers_ready)}/{len(pool.workers)}",
        )

        if workers_ready:
            self._log("POOL-WAIT", "")
            self._log("POOL-WAIT", "Ready to run benchmark:")
            self._log("POOL-WAIT", "  pool-run --tasks 154")

        return workers_ready

    def run(
        self,
        tasks: int = 10,
        agent: str = "navi",
        model: str = "gpt-4o-mini",
        api_key: str | None = None,
        proxy_authorization: str | None = None,
        agent_factory: Callable[[], Any] | None = None,
        qualification_dir: Path | None = None,
        task_ids: list[str] | None = None,
    ) -> PoolRunResult:
        """Run benchmark tasks distributed across pool workers.

        When agent_factory is None, runs WAA's built-in agent inside the
        Docker container via docker exec. When agent_factory is provided,
        the agent runs externally and communicates via the WAA Flask API.

        Args:
            tasks: Number of tasks to run.
            agent: Agent name for WAA's run.py (default: "navi").
            model: Model name for the agent.
            api_key: API key for the agent. Auto-loaded from config if None.
            proxy_authorization: Proxy password. Auto-loaded from the process
                environment and sent only on standard input.
            agent_factory: Optional callable that returns a BenchmarkAgent.
                When provided, overrides agent/model and runs externally.
            qualification_dir: Exact worker identity and egress policy directory.
            task_ids: Exact task identities. Required for an external agent.

        Returns:
            PoolRunResult with task counts and timing.

        Raises:
            RuntimeError: If no pool or no ready workers.
        """
        pool = self.registry.get_pool()
        if pool is None:
            raise RuntimeError("No active pool. Create one with: pool-create --workers N")

        # Load API key from config if not provided
        if not api_key:
            try:
                from openadapt_evals.config import settings

                api_key = settings.openai_api_key
            except Exception:
                pass

        if not api_key and agent_factory is None:
            raise RuntimeError(
                "No API key provided. Use api_key param or set OPENAI_API_KEY in .env"
            )
        if proxy_authorization is None:
            proxy_authorization = os.environ.get("OPENADAPT_EGRESS_PROXY_AUTHORIZATION")

        # A responsive legacy guest is not enough. Only a guest that crossed the
        # exact reset, egress, and one-use start gate can receive work.
        ready_workers = [
            worker
            for worker in pool.workers
            if worker.waa_ready
            and worker.status == "qualified-ready"
            and worker.qualified_run_id
            and worker.qualified_worker_admission_sha256
            and worker.qualified_provider_identity_sha256
            and worker.qualified_live_provider_observation_sha256
            and worker.qualified_worker_identity_sha256
            and worker.qualified_local_worker_identity_sha256
            and worker.qualified_egress_policy_sha256
            and worker.qualified_live_nft_sha256
            and worker.qualified_start_proof_sha256
            and worker.qualified_container_state_sha256
            and worker.qualified_dispatch_expires_at
        ]
        if not ready_workers:
            raise RuntimeError(
                "No qualified workers are ready. Complete reset, egress, start, and wait first."
            )
        if qualification_dir is None:
            raise RuntimeError("Pool dispatch requires the qualification directory.")
        if tasks != len(ready_workers):
            raise RuntimeError(
                "A qualified start proof can dispatch exactly one task. "
                "The task count must equal the qualified worker count."
            )
        if task_ids is not None and (
            len(task_ids) != tasks
            or len(set(task_ids)) != len(task_ids)
            or any(not isinstance(task_id, str) or not task_id for task_id in task_ids)
        ):
            raise RuntimeError("Exact task identities must be nonempty, unique, and complete.")
        if agent_factory is not None and task_ids is None:
            raise RuntimeError("An external agent requires exact task identities.")

        qualified_boundaries = {
            worker.name: self._qualified_isolation_manager(worker, qualification_dir)
            for worker in ready_workers
        }
        qualified_managers = {
            name: boundary[0] for name, boundary in qualified_boundaries.items()
        }
        qualified_admissions = {
            name: boundary[2] for name, boundary in qualified_boundaries.items()
        }
        qualified_policies = {
            name: boundary[1] for name, boundary in qualified_boundaries.items()
        }
        if agent_factory is None:
            if not isinstance(proxy_authorization, str) or PROXY_SECRET.fullmatch(
                proxy_authorization
            ) is None:
                raise RuntimeError(
                    "The authenticated egress proxy password is absent or invalid. "
                    "Set OPENADAPT_EGRESS_PROXY_AUTHORIZATION."
                )
            from openadapt_evals.infrastructure.windows_pool_isolation import (
                egress_proxy_authorization_sha256,
            )

            for worker in ready_workers:
                authorization_sha256 = egress_proxy_authorization_sha256(
                    qualified_policies[worker.name],
                    proxy_authorization,
                )
                expected = qualified_policies[worker.name]["proxy"]["authorization_sha256"]
                if authorization_sha256 != expected:
                    raise RuntimeError(
                        f"Worker {worker.name} proxy authorization differs from its policy."
                    )

        self._log("POOL-RUN", "=" * 60)
        self._log(
            "POOL-RUN",
            f"Running WAA benchmark across {len(ready_workers)} workers",
        )
        self._log("POOL-RUN", f"  Tasks: {tasks}")
        if agent_factory:
            self._log("POOL-RUN", "  Agent: custom (external)")
        else:
            self._log("POOL-RUN", f"  Agent: {agent}")
            self._log("POOL-RUN", f"  Model: {model}")
        self._log("POOL-RUN", "=" * 60)

        # Update registry
        pool.total_tasks = tasks
        self.registry.save()

        # Create experiment name
        exp_name = datetime.now().strftime("pool_%Y%m%d_%H%M%S")
        num_workers = len(ready_workers)
        interrupt_requested = Event()

        if agent_factory is not None:
            assert task_ids is not None
            if self.external_task_session_authority is None:
                raise RuntimeError(
                    "The protected external task session authority is not configured."
                )
            result = self.external_task_session_authority.run_qualified_tasks(
                workers=ready_workers,
                task_ids=task_ids,
                agent_factory=agent_factory,
                experiment=exp_name,
                managers=qualified_managers,
                admissions=qualified_admissions,
                policies=qualified_policies,
                proxy_authorization=proxy_authorization,
                worker_trust_authority=self.worker_trust_authority,
            )
            if not isinstance(result, PoolRunResult):
                raise RuntimeError("The external task authority returned an invalid result.")
            accounted = result.completed + result.failed
            names = [item[0] for item in result.worker_results]
            expected_names = [worker.name for worker in ready_workers]
            if (
                result.total_tasks != tasks
                or accounted != tasks
                or len(result.worker_results) != tasks
                or sorted(names) != sorted(expected_names)
            ):
                raise RuntimeError(
                    "The external task authority did not return one terminal receipt per task."
                )
            return result

        def run_on_worker(
            worker: PoolWorker,
            worker_idx: int,
            total_workers: int,
        ) -> tuple[
            tuple[str, int, int, str | None],
            Mapping[str, Any],
            str,
        ]:
            from openadapt_evals.infrastructure.windows_worker_dispatch import (
                launch_authorized_process,
            )

            manager = qualified_managers[worker.name]
            admission = qualified_admissions[worker.name]
            policy = qualified_policies[worker.name]
            qualified_live_nft_sha256 = worker.qualified_live_nft_sha256

            def qualified_command(remote_command, **kwargs):
                return manager.run_qualified_command(
                    remote_command,
                    run_id=worker.qualified_run_id,
                    policy_sha256=worker.qualified_egress_policy_sha256,
                    container_state_sha256=worker.qualified_container_state_sha256,
                    expires_at=worker.qualified_dispatch_expires_at,
                    live_nft_sha256=qualified_live_nft_sha256,
                    **kwargs,
                )

            # Read task metadata before the capability is consumed.  The only
            # guest operation here is a read.  The exact subset bytes are
            # written only inside the atomic dispatch transaction.
            metadata_result = qualified_command(
                [
                    "docker",
                    "exec",
                    "winarena",
                    "cat",
                    "/client/evaluation_examples_windows/test_all.json",
                ]
            )
            try:
                metadata = json.loads(metadata_result.stdout)
            except json.JSONDecodeError as exc:
                raise RuntimeError("Qualified task metadata is invalid.") from exc
            if not isinstance(metadata, dict) or not metadata:
                raise RuntimeError("Qualified task metadata is invalid.")
            pairs = [
                (domain, task_id)
                for domain, task_list in metadata.items()
                if isinstance(domain, str) and isinstance(task_list, list)
                for task_id in task_list
                if isinstance(task_id, str)
            ]
            requested_task = task_ids[worker_idx] if task_ids is not None else "-"
            if requested_task == "-":
                if worker_idx >= len(pairs):
                    raise RuntimeError("Qualified task index is outside the admitted metadata.")
                domain, exact_task = pairs[worker_idx]
            else:
                matches = [pair for pair in pairs if pair[1] == requested_task]
                if len(matches) != 1:
                    raise RuntimeError("Requested task identity is not unique.")
                domain, exact_task = matches[0]
            exact_task_id = f"{domain}:{exact_task}"
            subset = (
                json.dumps(
                    {domain: [exact_task]},
                    sort_keys=True,
                    separators=(",", ":"),
                    ensure_ascii=False,
                ).encode("utf-8")
                + b"\n"
            )
            authorized = self.worker_trust_authority.authorize_dispatch(
                admission=admission,
                run_id=worker.qualified_run_id,
                task_selector={"domain": domain, "task_id": exact_task},
            )
            if api_key is None:
                raise RuntimeError("The protected API credential is absent.")
            process = launch_authorized_process(
                manager,
                admission=admission,
                dispatch=authorized,
                policy_sha256=worker.qualified_egress_policy_sha256,
                container_state_sha256=worker.qualified_container_state_sha256,
                live_nft_sha256=worker.qualified_live_nft_sha256,
                policy=policy,
                proxy_authorization=proxy_authorization,
                agent=agent,
                model=model,
                experiment=f"{exp_name}_{worker.name}",
                subset=subset,
                api_key=api_key,
            )
            self.registry.update_worker(
                worker.name,
                status="qualified-dispatched",
                waa_ready=False,
                current_task=exact_task_id,
                qualified_task_binding_sha256=authorized.object["dispatch_id_sha256"],
            )
            terminal_evidence = _build_postlaunch_terminal_evidence(
                manager=manager,
                admission=admission,
                dispatch=authorized,
                process=process,
                interrupt_requested=interrupt_requested,
            )
            terminal = self.worker_trust_authority.issue_terminal(
                admission=admission,
                dispatch=authorized,
                terminal_evidence=terminal_evidence,
            )
            terminal_state = terminal.object["terminal_state"]
            if terminal_state == "VERIFIED":
                worker_result = (worker.name, 1, 0, None)
            else:
                worker_result = (
                    worker.name,
                    0,
                    1,
                    f"central terminal state {terminal_state}",
                )
            return (
                worker_result,
                terminal.object,
                authorized.object["dispatch_id_sha256"],
            )

        self._log("POOL-RUN", "")
        self._log("POOL-RUN", "Starting benchmark on all workers...")
        start_time = time.time()

        results: list[tuple[str, int, int, str | None]] = []
        terminal_receipts: list[Mapping[str, Any]] = []
        expected_dispatches: dict[str, str] = {}
        with ThreadPoolExecutor(max_workers=num_workers) as executor:
            futures = {}
            for worker_idx, worker in enumerate(ready_workers):
                future = executor.submit(run_on_worker, worker, worker_idx, num_workers)
                futures[future] = worker.name

            pending = set(futures)
            while pending:
                try:
                    future = next(as_completed(pending))
                    worker_result, terminal_receipt, dispatch_id = future.result()
                except KeyboardInterrupt:
                    interrupt_requested.set()
                    self._log(
                        "POOL-RUN",
                        "Operator interrupt received; quarantining active worker processes.",
                    )
                    continue
                pending.remove(future)
                name, completed, failed, error = worker_result
                if error:
                    self._log("POOL-RUN", f"  {name}: FAILED - {error}")
                else:
                    self._log("POOL-RUN", f"  {name}: completed {completed} tasks")
                results.append(worker_result)
                terminal_receipts.append(terminal_receipt)
                expected_dispatches[name] = dispatch_id
                self.registry.update_pool_progress(completed=completed, failed=failed)

        elapsed = time.time() - start_time
        total_completed = sum(r[1] for r in results)
        total_failed = sum(r[2] for r in results)

        self._log("POOL-RUN", "")
        self._log("POOL-RUN", "=" * 60)
        self._log("POOL-RUN", "BENCHMARK COMPLETE")
        self._log("POOL-RUN", f"  Time: {elapsed / 60:.1f} minutes")
        self._log("POOL-RUN", f"  Completed: {total_completed}/{tasks}")
        self._log("POOL-RUN", f"  Failed: {total_failed}")
        self._log("POOL-RUN", "=" * 60)

        result = PoolRunResult(
            total_tasks=tasks,
            completed=total_completed,
            failed=total_failed,
            elapsed_seconds=elapsed,
            worker_results=results,
            terminal_receipts=tuple(terminal_receipts),
        )
        return validate_terminal_pool_result(
            result,
            expected_dispatches=expected_dispatches,
        )

    def _run_external_agent(
        self,
        workers: list[PoolWorker],
        tasks: int,
        agent_factory: Callable[[], Any],
        exp_name: str,
        task_ids: list[str],
        qualified_managers: dict[str, Any],
    ) -> PoolRunResult:
        """Run an external agent against pool workers via Flask API.

        Sets up SSH tunnels to each worker, creates per-worker adapters
        and agents, then runs the benchmark evaluation loop locally.
        Each worker gets a unique local port for its SSH tunnel.

        Args:
            workers: Ready pool workers.
            tasks: Number of tasks to run (used if task_ids is None).
            agent_factory: Callable that returns a BenchmarkAgent.
            exp_name: Experiment name for result tracking.
            task_ids: One exact task identity for each qualified worker.
            qualified_managers: Pinned identity managers for those workers.

        Returns:
            PoolRunResult.
        """
        raise RuntimeError(
            "Generic SSH tunnels are not a qualified task session. "
            "Use the protected external task session authority."
        )
        from openadapt_evals.adapters.waa.live import WAALiveAdapter, WAALiveConfig
        from openadapt_evals.benchmarks.runner import (
            EvaluationConfig,
            evaluate_agent_on_benchmark,
        )
        from openadapt_evals.infrastructure.ssh_tunnel import (
            SSHTunnelManager,
            TunnelConfig,
        )

        num_workers = len(workers)
        _username = self._ssh_username

        # Base ports for per-worker tunnels (each worker gets unique local ports)
        base_waa_port = 15001
        base_eval_port = 15050

        self._log("POOL-RUN", f"Setting up SSH tunnels for {num_workers} workers...")

        # Set up SSH tunnels per worker
        tunnel_managers: list[SSHTunnelManager] = []
        worker_ports: list[tuple[int, int]] = []  # (waa_port, eval_port)
        tunneled_workers: list[PoolWorker] = []

        for i, worker in enumerate(workers):
            waa_port = base_waa_port + i
            eval_port = base_eval_port + i
            qualified_managers[worker.name].verify_started(
                run_id=worker.qualified_run_id,
                policy_sha256=worker.qualified_egress_policy_sha256,
                container_state_sha256=worker.qualified_container_state_sha256,
                expires_at=worker.qualified_dispatch_expires_at,
                live_nft_sha256=worker.qualified_live_nft_sha256,
            )

            tunnel_mgr = SSHTunnelManager(
                ssh_key_path=qualified_managers[worker.name].ssh_key_path,
                tunnels=[
                    TunnelConfig(
                        name=f"waa-{worker.name}",
                        local_port=waa_port,
                        remote_port=5000,
                    ),
                    TunnelConfig(
                        name=f"eval-{worker.name}",
                        local_port=eval_port,
                        remote_port=5051,
                    ),
                ],
                host_key_alias=qualified_managers[worker.name].identity.instance_id,
                host_public_key=qualified_managers[worker.name].identity.ssh_host_public_key,
            )
            statuses = tunnel_mgr.start_tunnels_for_vm(
                vm_ip=worker.ip,
                ssh_user=_username,
            )

            all_ok = all(s.active for s in statuses.values())
            if all_ok:
                self._log(
                    "POOL-RUN",
                    f"  {worker.name}: tunnels up "
                    f"(waa=:{waa_port}, eval=:{eval_port})",
                )
                tunnel_managers.append(tunnel_mgr)
                worker_ports.append((waa_port, eval_port))
                tunneled_workers.append(worker)
            else:
                failed = [n for n, s in statuses.items() if not s.active]
                self._log(
                    "POOL-RUN",
                    f"  {worker.name}: tunnel FAILED ({', '.join(failed)})",
                )

        if not tunnel_managers:
            return PoolRunResult(
                total_tasks=tasks,
                completed=0,
                failed=tasks,
                elapsed_seconds=0.0,
                worker_results=[
                    (w.name, 0, 0, "SSH tunnel setup failed") for w in workers
                ],
            )

        active_workers = list(zip(tunneled_workers, worker_ports, strict=True))

        # Distribute task_ids round-robin across workers
        task_by_worker = dict(zip((worker.name for worker in workers), task_ids, strict=True))
        per_worker_tasks = [[task_by_worker[worker.name]] for worker, _ in active_workers]

        # Run evaluation on each worker in parallel
        start_time = time.time()
        results: list[tuple[str, int, int, str | None]] = []

        def run_on_worker(
            worker_info: tuple[tuple[PoolWorker, tuple[int, int]], list[str]],
        ) -> tuple[str, int, int, str | None]:
            (worker, (waa_port, eval_port)), w_task_ids = worker_info

            try:
                adapter = WAALiveAdapter(
                    WAALiveConfig(
                        server_url=f"http://localhost:{waa_port}",
                        evaluate_url=f"http://localhost:{eval_port}",
                    )
                )

                agent = agent_factory()

                config = EvaluationConfig(
                    max_steps=15,
                    save_execution_traces=True,
                    output_dir=f"benchmark_results/{exp_name}",
                    run_name=f"{exp_name}_{worker.name}",
                )

                eval_results = evaluate_agent_on_benchmark(
                    agent=agent,
                    adapter=adapter,
                    task_ids=w_task_ids,
                    config=config,
                )
                qualified_managers[worker.name].verify_started(
                    run_id=worker.qualified_run_id,
                    policy_sha256=worker.qualified_egress_policy_sha256,
                    container_state_sha256=worker.qualified_container_state_sha256,
                    expires_at=worker.qualified_dispatch_expires_at,
                    live_nft_sha256=worker.qualified_live_nft_sha256,
                )

                completed = sum(1 for r in eval_results if r.success)
                failed = len(eval_results) - completed
                return (worker.name, completed, failed, None)

            except Exception as e:
                logger.error(f"Worker {worker.name} failed: {e}")
                return (worker.name, 0, 1, str(e))

        with ThreadPoolExecutor(max_workers=len(active_workers)) as executor:
            worker_inputs = list(zip(active_workers, per_worker_tasks))
            futures = {
                executor.submit(run_on_worker, wi): wi[0][0].name
                for wi in worker_inputs
            }
            for future in as_completed(futures):
                name = futures[future]
                try:
                    result = future.result()
                    results.append(result)
                    if result[3]:
                        self._log("POOL-RUN", f"  {name}: ERROR - {result[3]}")
                    else:
                        self._log(
                            "POOL-RUN",
                            f"  {name}: {result[1]} passed, {result[2]} failed",
                        )
                    self.registry.update_pool_progress(
                        completed=result[1], failed=result[2]
                    )
                except Exception as e:
                    results.append((name, 0, 1, str(e)))
                    self._log("POOL-RUN", f"  {name}: EXCEPTION - {e}")

        # Tear down tunnels
        for mgr in tunnel_managers:
            try:
                mgr.stop_all_tunnels()
            except Exception:
                pass

        elapsed = time.time() - start_time
        total_completed = sum(r[1] for r in results)
        total_failed = sum(r[2] for r in results)

        self._log("POOL-RUN", "")
        self._log("POOL-RUN", "=" * 60)
        self._log("POOL-RUN", "EXTERNAL AGENT BENCHMARK COMPLETE")
        self._log("POOL-RUN", f"  Time: {elapsed / 60:.1f} minutes")
        self._log("POOL-RUN", f"  Completed: {total_completed}")
        self._log("POOL-RUN", f"  Failed: {total_failed}")
        self._log("POOL-RUN", "=" * 60)

        return PoolRunResult(
            total_tasks=len(task_ids),
            completed=total_completed,
            failed=total_failed,
            elapsed_seconds=elapsed,
            worker_results=results,
        )

    def status(self) -> VMPool | None:
        """Get current pool status.

        Returns:
            VMPool if a pool exists, None otherwise.
        """
        return self.registry.get_pool()

    def _isolation_manager(self, worker_name: str, identity_path: Path):
        """Return the host isolation manager for one exact active worker."""

        from openadapt_evals.infrastructure.windows_pool_isolation import (
            WindowsPoolIsolationManager,
            load_worker_identity,
        )

        pool = self.registry.get_pool()
        if pool is None:
            raise RuntimeError("No active pool. Create one with: pool-create --workers N")
        if pool.status == "paused":
            raise RuntimeError("Pool is paused. Resume it before worker isolation.")
        matches = [worker for worker in pool.workers if worker.name == worker_name]
        if len(matches) != 1:
            raise RuntimeError(f"Pool worker not found: {worker_name}")
        worker = matches[0]
        current_ip = self.vm_manager.get_vm_ip(worker.name)
        if current_ip:
            worker.ip = current_ip
            self.registry.update_worker(worker.name, ip=current_ip)
        if not worker.ip:
            raise RuntimeError(f"Pool worker has no reachable IP: {worker_name}")
        return WindowsPoolIsolationManager(
            ssh_host=worker.ip,
            ssh_user=self._ssh_username,
            worker=worker.name,
            identity=load_worker_identity(identity_path),
            storage_dir=f"{self._home_dir}/waa-storage",
            baseline_dir=f"{self._home_dir}/openadapt-windows-baseline",
            ssh_key_path=getattr(self.vm_manager, "ssh_private_key_path", None),
        )

    def _verify_worker_admission(self, manager, policy):
        """Resolve a fresh central admission from live provider evidence."""

        from openadapt_evals.infrastructure.windows_pool_isolation import (
            egress_policy_sha256,
            worker_identity_sha256,
        )
        from openadapt_evals.infrastructure.windows_worker_trust import (
            qualification_worker_identity_sha256,
            validate_provider_observation,
        )

        if self.worker_trust_authority is None:
            raise RuntimeError(
                "The protected central worker trust connector is not configured."
            )
        observe = getattr(self.vm_manager, "observe_worker", None)
        if not callable(observe):
            raise RuntimeError("The VM provider has no live worker identity resolver.")
        observation = validate_provider_observation(observe(manager.worker))
        if observation.provider != manager.identity.provider:
            raise RuntimeError("The live worker provider differs from the admitted identity.")
        if observation.network_identity != manager.ssh_host:
            raise RuntimeError("The live provider network identity differs from the SSH target.")
        if observation.resource_identity != manager.identity.resource_id:
            raise RuntimeError("The live provider resource identity differs.")
        if observation.instance_identity != manager.identity.instance_id:
            raise RuntimeError("The live provider instance generation differs.")
        local_worker_identity_sha256 = worker_identity_sha256(manager.identity)
        central_worker_identity_sha256 = qualification_worker_identity_sha256(
            observation=observation,
            worker_instance_sha256=local_worker_identity_sha256,
            worker_image_sha256=manager.identity.admitted_image_sha256,
            host_identity_sha256=manager.identity.host_bindings_sha256,
            admitted_runtime_sha256=manager.identity.admitted_runtime_sha256,
        )
        admission = self.worker_trust_authority.verify_worker(
            observation=observation,
            worker_identity_sha256=central_worker_identity_sha256,
            admitted_runtime_sha256=manager.identity.admitted_runtime_sha256,
            worker_image_sha256=manager.identity.admitted_image_sha256,
            baseline_sha256=manager.identity.baseline_manifest_sha256,
            host_identity_sha256=manager.identity.host_bindings_sha256,
            tls_identity_sha256=manager.identity.tls_bindings_sha256,
            egress_policy_sha256=egress_policy_sha256(policy),
        )
        return admission, observation

    def _qualified_isolation_manager(
        self,
        worker: PoolWorker,
        qualification_dir: Path,
    ):
        """Resolve and revalidate one exact qualified worker boundary."""

        from openadapt_evals.infrastructure.windows_pool_isolation import (
            egress_policy_sha256,
            load_egress_policy,
            worker_identity_sha256,
        )

        if qualification_dir.is_symlink() or not qualification_dir.is_dir():
            raise RuntimeError("Qualification directory is not a regular directory.")
        required = (
            worker.status in {"qualified-starting", "qualified-ready"}
            and worker.qualified_run_id
            and worker.qualified_worker_admission_sha256
            and worker.qualified_provider_identity_sha256
            and worker.qualified_live_provider_observation_sha256
            and worker.qualified_worker_identity_sha256
            and worker.qualified_local_worker_identity_sha256
            and worker.qualified_egress_policy_sha256
            and worker.qualified_live_nft_sha256
            and worker.qualified_start_proof_sha256
            and worker.qualified_container_state_sha256
            and worker.qualified_dispatch_expires_at
        )
        if not required:
            raise RuntimeError(f"Worker {worker.name} has no complete qualification state.")
        manager = self._isolation_manager(
            worker.name,
            qualification_dir / f"{worker.name}.identity.json",
        )
        policy = load_egress_policy(
            qualification_dir / f"{worker.name}.egress.json"
        )
        if (
            worker_identity_sha256(manager.identity)
            != worker.qualified_local_worker_identity_sha256
        ):
            raise RuntimeError(f"Worker {worker.name} identity differs from the start proof.")
        if policy["run_id"] != worker.qualified_run_id:
            raise RuntimeError(f"Worker {worker.name} run identity differs from the policy.")
        if egress_policy_sha256(policy) != worker.qualified_egress_policy_sha256:
            raise RuntimeError(f"Worker {worker.name} egress policy differs from the start proof.")
        admission, _observation = self._verify_worker_admission(manager, policy)
        expected_admission = {
            "admission_object_sha256": worker.qualified_worker_admission_sha256,
            "provider_identity_sha256": worker.qualified_provider_identity_sha256,
            "live_provider_observation_sha256": (
                worker.qualified_live_provider_observation_sha256
            ),
            "worker_identity_sha256": worker.qualified_worker_identity_sha256,
        }
        if any(
            admission.object[key] != expected_value
            for key, expected_value in expected_admission.items()
        ):
            raise RuntimeError(f"Worker {worker.name} central admission differs.")
        manager.verify_proxy_tls(policy)
        manager.verify_started(
            run_id=worker.qualified_run_id,
            policy_sha256=worker.qualified_egress_policy_sha256,
            container_state_sha256=worker.qualified_container_state_sha256,
            expires_at=worker.qualified_dispatch_expires_at,
            live_nft_sha256=worker.qualified_live_nft_sha256,
        )
        return manager, policy, admission

    def provision_worker_from_acr(
        self,
        worker_name: str,
        *,
        identity_path: Path,
        login_server: str,
        username: str,
        image_ref: str,
        password: str,
    ) -> None:
        """Pull one exact ACR image through an admitted pinned SSH boundary."""

        server_pattern = re.compile(
            r"^[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?(?::[1-9][0-9]{0,4})?$"
        )
        if server_pattern.fullmatch(login_server) is None:
            raise RuntimeError("The ACR login server is invalid.")
        _, separator, port = login_server.rpartition(":")
        if separator and (not port.isdigit() or not 1 <= int(port) <= 65535):
            raise RuntimeError("The ACR login server port is invalid.")
        if re.fullmatch(r"[A-Za-z0-9._@-]{1,128}", username) is None:
            raise RuntimeError("The ACR username is invalid.")
        prefix = login_server + "/"
        if not image_ref.startswith(prefix) or "@sha256:" not in image_ref:
            raise RuntimeError("The ACR image reference is not an exact digest reference.")
        repository, digest = image_ref[len(prefix) :].rsplit("@sha256:", 1)
        repository_segment = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
        if (
            not repository
            or any(repository_segment.fullmatch(part) is None for part in repository.split("/"))
            or re.fullmatch(r"[a-f0-9]{64}", digest) is None
        ):
            raise RuntimeError("The ACR image reference is not an exact digest reference.")
        if not password or len(password) > 4096 or "\n" in password or "\x00" in password:
            raise RuntimeError("The ACR password is invalid.")

        manager = self._isolation_manager(worker_name, identity_path)
        program = r"""
import subprocess
import sys

login_server, username, image_ref, expected_image = sys.argv[1:]
password = sys.stdin.buffer.readline()
if not password.endswith(b'\n') or sys.stdin.buffer.read(1):
    raise SystemExit('ACR password framing is invalid')
password = password[:-1]
if not password or b'\x00' in password:
    raise SystemExit('ACR password is invalid')
subprocess.run(
    ['docker', 'login', login_server, '--username', username, '--password-stdin'],
    input=password,
    check=True,
)
try:
    subprocess.run(['docker', 'pull', image_ref], check=True)
    actual = subprocess.run(
        ['docker', 'image', 'inspect', image_ref, '--format', '{{.Id}}'],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    if actual != expected_image:
        raise SystemExit('pulled ACR image differs from the worker admission')
finally:
    subprocess.run(['docker', 'logout', login_server], check=False)
""".strip()
        manager.run_command(
            [
                "sudo",
                "python3",
                "-c",
                program,
                login_server,
                username,
                image_ref,
                manager.identity.admitted_image_sha256,
            ],
            input_bytes=(password + "\n").encode("utf-8"),
            timeout_seconds=15 * 60,
        )

    def reset_worker(
        self,
        worker_name: str,
        *,
        run_id: str,
        identity_path: Path,
    ):
        """Restore one worker from an exact verified baseline."""

        manager = self._isolation_manager(worker_name, identity_path)
        proof = manager.reset(run_id=run_id)
        self.registry.update_worker(
            worker_name,
            status="reset",
            waa_ready=False,
            qualified_run_id=None,
            qualified_worker_admission_sha256=None,
            qualified_provider_identity_sha256=None,
            qualified_live_provider_observation_sha256=None,
            qualified_worker_identity_sha256=None,
            qualified_local_worker_identity_sha256=None,
            qualified_egress_policy_sha256=None,
            qualified_live_nft_sha256=None,
            qualified_start_proof_sha256=None,
            qualified_container_state_sha256=None,
            qualified_dispatch_expires_at=None,
            qualified_task_binding_sha256=None,
        )
        return proof

    def apply_worker_egress(
        self,
        worker_name: str,
        policy_path: Path,
        *,
        identity_path: Path,
        reset_proof_path: Path,
    ):
        """Apply one exact host-enforced egress policy to a worker."""

        from openadapt_evals.infrastructure.windows_pool_isolation import (
            load_egress_policy,
            load_reset_proof,
        )

        manager = self._isolation_manager(worker_name, identity_path)
        return manager.apply_egress(
            load_egress_policy(policy_path),
            reset_proof=load_reset_proof(reset_proof_path),
        )

    def start_worker(
        self,
        worker_name: str,
        *,
        identity_path: Path,
        policy_path: Path,
        reset_proof_path: Path,
        egress_proof_path: Path,
    ):
        """Start one guest only through a fresh, one-use run gate."""

        from openadapt_evals.infrastructure.windows_pool_isolation import (
            load_egress_policy,
            load_egress_proof,
            load_reset_proof,
            start_proof_sha256,
        )

        manager = self._isolation_manager(worker_name, identity_path)
        policy = load_egress_policy(policy_path)
        admission, _observation = self._verify_worker_admission(manager, policy)
        start_script = WAA_START_SCRIPT_TEMPLATE.format(
            home_dir=self._home_dir,
            ssh_username=self._ssh_username,
            admitted_image=manager.identity.admitted_image_sha256,
            **_proxy_start_values(policy),
        )
        proof = manager.start(
            policy=policy,
            reset_proof=load_reset_proof(reset_proof_path),
            egress_proof=load_egress_proof(egress_proof_path),
            start_script=start_script,
            worker_admission=admission.object,
        )
        self.registry.update_worker(
            worker_name,
            status="qualified-starting",
            waa_ready=False,
            qualified_run_id=proof.run_id,
            qualified_worker_admission_sha256=proof.worker_admission_sha256,
            qualified_provider_identity_sha256=proof.provider_identity_sha256,
            qualified_live_provider_observation_sha256=(
                proof.live_provider_observation_sha256
            ),
            qualified_worker_identity_sha256=proof.worker_identity_sha256,
            qualified_local_worker_identity_sha256=(
                proof.local_worker_identity_sha256
            ),
            qualified_egress_policy_sha256=proof.egress_policy_sha256,
            qualified_live_nft_sha256=proof.live_nft_sha256,
            qualified_start_proof_sha256=start_proof_sha256(proof),
            qualified_container_state_sha256=proof.container_state_sha256,
            qualified_dispatch_expires_at=proof.expires_at,
            qualified_task_binding_sha256=None,
        )
        return proof

    def qualify_worker(
        self,
        worker_name: str,
        *,
        identity_path: Path,
        policy_path: Path,
    ):
        """Reset, apply egress, and start one worker as one local operation."""

        from openadapt_evals.infrastructure.windows_pool_isolation import (
            load_egress_policy,
            start_proof_sha256,
        )

        manager = self._isolation_manager(worker_name, identity_path)
        policy = load_egress_policy(policy_path)
        admission, _observation = self._verify_worker_admission(manager, policy)
        reset_proof = manager.reset(run_id=policy["run_id"])
        self.registry.update_worker(
            worker_name,
            status="reset",
            waa_ready=False,
            qualified_run_id=None,
            qualified_worker_admission_sha256=None,
            qualified_provider_identity_sha256=None,
            qualified_live_provider_observation_sha256=None,
            qualified_worker_identity_sha256=None,
            qualified_local_worker_identity_sha256=None,
            qualified_egress_policy_sha256=None,
            qualified_live_nft_sha256=None,
            qualified_start_proof_sha256=None,
            qualified_container_state_sha256=None,
            qualified_dispatch_expires_at=None,
            qualified_task_binding_sha256=None,
        )
        egress_proof = manager.apply_egress(policy, reset_proof=reset_proof)
        start_script = WAA_START_SCRIPT_TEMPLATE.format(
            home_dir=self._home_dir,
            ssh_username=self._ssh_username,
            admitted_image=manager.identity.admitted_image_sha256,
            **_proxy_start_values(policy),
        )
        start_proof = manager.start(
            policy=policy,
            reset_proof=reset_proof,
            egress_proof=egress_proof,
            start_script=start_script,
            worker_admission=admission.object,
        )
        self.registry.update_worker(
            worker_name,
            status="qualified-starting",
            waa_ready=False,
            qualified_run_id=start_proof.run_id,
            qualified_worker_admission_sha256=start_proof.worker_admission_sha256,
            qualified_provider_identity_sha256=start_proof.provider_identity_sha256,
            qualified_live_provider_observation_sha256=(
                start_proof.live_provider_observation_sha256
            ),
            qualified_worker_identity_sha256=start_proof.worker_identity_sha256,
            qualified_local_worker_identity_sha256=(
                start_proof.local_worker_identity_sha256
            ),
            qualified_egress_policy_sha256=start_proof.egress_policy_sha256,
            qualified_live_nft_sha256=start_proof.live_nft_sha256,
            qualified_start_proof_sha256=start_proof_sha256(start_proof),
            qualified_container_state_sha256=start_proof.container_state_sha256,
            qualified_dispatch_expires_at=start_proof.expires_at,
            qualified_task_binding_sha256=None,
        )
        return reset_proof, egress_proof, start_proof

    def pause(self) -> bool:
        """Deallocate all pool VMs. Stops compute billing, keeps disks.

        The pool state is saved to the registry so it can be resumed later
        with resume(). Disk and IP costs (~$0.25/day) continue while paused.

        Returns:
            True if all VMs were deallocated successfully.

        Raises:
            RuntimeError: If no pool exists or pool is already paused.
        """
        pool = self.registry.get_pool()
        if pool is None:
            raise RuntimeError("No active pool. Create one with: pool-create --workers N")

        if pool.status == "paused":
            raise RuntimeError(
                "Pool is already paused. Resume with: pool-resume"
            )

        self._log("POOL-PAUSE", f"Pausing pool {pool.pool_id} ({len(pool.workers)} workers)...")
        self._log("POOL-PAUSE", "Deallocating VMs (compute billing will stop)...")

        all_ok = True
        for worker in pool.workers:
            self._log("POOL-PAUSE", f"  {worker.name}: deallocating...")
            success = self.vm_manager.deallocate_vm(worker.name)
            if success:
                self._log("POOL-PAUSE", f"  {worker.name}: deallocated")
                self.registry.update_worker(
                    worker.name,
                    status="deallocated",
                    waa_ready=False,
                    qualified_run_id=None,
                    qualified_worker_admission_sha256=None,
                    qualified_provider_identity_sha256=None,
                    qualified_live_provider_observation_sha256=None,
                    qualified_worker_identity_sha256=None,
                    qualified_local_worker_identity_sha256=None,
                    qualified_egress_policy_sha256=None,
                    qualified_live_nft_sha256=None,
                    qualified_start_proof_sha256=None,
                    qualified_task_binding_sha256=None,
                )
            else:
                self._log("POOL-PAUSE", f"  {worker.name}: FAILED to deallocate")
                all_ok = False

        # Update pool status
        paused_since = datetime.now().isoformat()
        self.registry.update_pool_status(status="paused", paused_since=paused_since)

        self._log("POOL-PAUSE", "=" * 60)
        self._log("POOL-PAUSE", "Pool paused. Compute billing stopped.")
        self._log("POOL-PAUSE", "  Idle cost: ~$0.25/day (disk + IP)")
        self._log("POOL-PAUSE", "  Resume with: oa-vm pool-resume")
        self._log("POOL-PAUSE", "  Delete with: oa-vm pool-cleanup -y")
        self._log("POOL-PAUSE", "=" * 60)

        return all_ok

    def resume(self, timeout_minutes: int = 10) -> list[PoolWorker]:
        """Start deallocated pool VMs and wait for WAA ready.

        Starts all VM hosts and waits for SSH access. It leaves every guest
        stopped. A caller must qualify each guest again before use.

        Args:
            timeout_minutes: Maximum minutes to wait for WAA readiness.

        Returns:
            List of ready PoolWorker instances.

        Raises:
            RuntimeError: If no pool exists or pool is not paused.
        """
        pool = self.registry.get_pool()
        if pool is None:
            raise RuntimeError("No active pool. Create one with: pool-create --workers N")

        if pool.status != "paused":
            raise RuntimeError(
                f"Pool is not paused (status: {pool.status}). "
                "Use pool-pause first, or pool-wait if already running."
            )

        self._log("POOL-RESUME", f"Resuming pool {pool.pool_id} ({len(pool.workers)} workers)...")

        # Start all VMs
        self._log("POOL-RESUME", "Starting VMs...")
        for worker in pool.workers:
            self._log("POOL-RESUME", f"  {worker.name}: starting...")
            success = self.vm_manager.start_vm(worker.name)
            if success:
                self._log("POOL-RESUME", f"  {worker.name}: started")
                self.registry.update_worker(worker.name, status="starting")
            else:
                self._log("POOL-RESUME", f"  {worker.name}: FAILED to start")

        # Wait for SSH on all workers
        self._log("POOL-RESUME", "Waiting for SSH access...")
        workers_ssh_ok: list[PoolWorker] = []
        for worker in pool.workers:
            # Re-fetch IP (may have changed after deallocate/start cycle)
            new_ip = self.vm_manager.get_vm_ip(worker.name)
            if new_ip and new_ip != worker.ip:
                self._log(
                    "POOL-RESUME",
                    f"  {worker.name}: IP changed {worker.ip} -> {new_ip}",
                )
                self.registry.update_worker(worker.name, ip=new_ip)
                worker.ip = new_ip

            if not worker.ip:
                self._log("POOL-RESUME", f"  {worker.name}: no IP address, skipping")
                continue

            if wait_for_ssh(worker.ip, timeout=120, username=self._ssh_username):
                self._log("POOL-RESUME", f"  {worker.name}: SSH ready")
                workers_ssh_ok.append(worker)
            else:
                self._log("POOL-RESUME", f"  {worker.name}: SSH timeout")

        if not workers_ssh_ok:
            self._log("POOL-RESUME", "ERROR: No VMs have SSH access after start")
            return []

        # Update pool status back to active
        self.registry.update_pool_status(status="active", paused_since=None)
        for worker in workers_ssh_ok:
            self.registry.update_worker(
                worker.name,
                status="ready",
                waa_ready=False,
                qualified_run_id=None,
                qualified_worker_admission_sha256=None,
                qualified_provider_identity_sha256=None,
                qualified_live_provider_observation_sha256=None,
                qualified_worker_identity_sha256=None,
                qualified_local_worker_identity_sha256=None,
                qualified_egress_policy_sha256=None,
                qualified_live_nft_sha256=None,
                qualified_start_proof_sha256=None,
                qualified_task_binding_sha256=None,
            )

        self._log("POOL-RESUME", "=" * 60)
        self._log(
            "POOL-RESUME",
            f"Pool hosts resumed: {len(workers_ssh_ok)}/{len(pool.workers)}; guests remain stopped",
        )
        self._log("POOL-RESUME", "  Qualify each guest with pool-reset, pool-egress, pool-start")
        self._log("POOL-RESUME", "=" * 60)

        return workers_ssh_ok

    def cleanup(
        self,
        confirm: bool = True,
    ) -> bool:
        """Clean up orphaned pool resources.

        Delegates resource discovery and deletion to the VM provider,
        making this method cloud-agnostic.

        Args:
            confirm: If True, prompt for confirmation before deleting.

        Returns:
            True if cleanup succeeded.
        """
        prefix = "waa-pool"
        self._log("POOL-CLEANUP", "Searching for orphaned pool resources...")

        resources = self.vm_manager.list_pool_resources(prefix)
        total = sum(len(v) for v in resources.values())

        if total == 0:
            self._log("POOL-CLEANUP", "No orphaned resources found.")
            return True

        self._log("POOL-CLEANUP", f"Found {total} orphaned resources:")
        for rtype, names in resources.items():
            if names:
                self._log("POOL-CLEANUP", f"  {rtype}: {len(names)}")

        if confirm:
            user_input = input("\nDelete these resources? [y/N]: ")
            if user_input.lower() != "y":
                self._log("POOL-CLEANUP", "Aborted.")
                return False

        self._log("POOL-CLEANUP", "Deleting resources...")
        for rtype, names in resources.items():
            for name in names:
                self._log("POOL-CLEANUP", f"  Deleting {rtype}: {name}")

        success = self.vm_manager.cleanup_pool_resources(prefix, resources)

        # Only delete registry if cloud resources were successfully cleaned up
        if success:
            self.registry.delete_pool()
            self._log("POOL-CLEANUP", "Cleanup complete.")
        else:
            self._log(
                "POOL-CLEANUP",
                "Some resources failed to delete. Registry preserved for retry.",
            )
        return success
