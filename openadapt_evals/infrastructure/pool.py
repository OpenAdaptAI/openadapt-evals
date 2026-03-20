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

import logging
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable

from openadapt_evals.infrastructure.azure_vm import (
    SSH_OPTS,
    AzureVMManager,
    ssh_run,
    wait_for_ssh,
)

if TYPE_CHECKING:
    from openadapt_evals.infrastructure.vm_provider import VMProvider
from openadapt_evals.infrastructure.vm_monitor import (
    VMConfig,
    VMMonitor,
    VMPool,
    VMPoolRegistry,
    PoolWorker,
)

logger = logging.getLogger(__name__)


@dataclass
class PoolRunResult:
    """Result of running benchmark tasks across a pool."""

    total_tasks: int
    completed: int
    failed: int
    elapsed_seconds: float
    worker_results: list[tuple[str, int, int, str | None]]
    """List of (worker_name, completed, failed, error_or_none)."""


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

# Docker setup script that pulls pre-built image from ACR instead of building.
# {home_dir} is formatted at runtime with the provider's ssh_username home path.
DOCKER_SETUP_SCRIPT_WITH_ACR = """
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

# Pull pre-built image from ACR (faster than building)
echo "Pulling pre-built image from ACR..."
sudo docker login {acr_login_server} -u {acr_username} -p '{acr_password}'
sudo docker pull {acr_login_server}/waa-auto:latest
sudo docker tag {acr_login_server}/waa-auto:latest waa-auto:latest

# Pull base images (needed for WAA container)
sudo docker pull dockurr/windows:latest

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

# WAA container start script template.
# {home_dir} and {ssh_username} are formatted at runtime.
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
  waa-auto:latest \\
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

    def _get_acr_password(self, acr_name: str) -> str | None:
        """Get ACR admin password via az CLI."""
        try:
            result = subprocess.run(
                ["az", "acr", "credential", "show", "--name", acr_name, "--query", "passwords[0].value", "-o", "tsv"],
                capture_output=True, text=True, timeout=30,
            )
            if result.returncode == 0 and result.stdout.strip():
                return result.stdout.strip()
        except Exception as e:
            logger.debug(f"Failed to get ACR password: {e}")
        return None

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
            if use_acr:
                from openadapt_evals.config import settings
                acr_password = self._get_acr_password(settings.acr_name)
                if acr_password:
                    docker_script = DOCKER_SETUP_SCRIPT_WITH_ACR.format(
                        home_dir=home_dir,
                        acr_login_server=settings.acr_login_server,
                        acr_username=settings.acr_name,
                        acr_password=acr_password,
                    )
                    self._log("POOL", f"Using ACR: {settings.acr_login_server}")
                else:
                    self._log("POOL", "WARNING: ACR password not found, falling back to local build")

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
        self._log("POOL", "  1. Wait for WAA ready: pool-wait")
        self._log("POOL", "  2. Run benchmark:      pool-run --tasks 154")
        self._log("POOL", "  3. Delete pool:        delete-pool")
        self._log("POOL", "=" * 60)

        return pool

    def wait(
        self,
        timeout_minutes: int = 30,
        start_containers: bool = True,
    ) -> list[PoolWorker]:
        """Wait for all pool workers to have WAA ready.

        Optionally starts WAA containers on each worker first.

        Args:
            timeout_minutes: Maximum minutes to wait for WAA readiness.
            start_containers: If True, start WAA containers before waiting.

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
            self._log("POOL-WAIT", "Checking WAA containers on all workers...")
            username = self._ssh_username
            waa_start_script = WAA_START_SCRIPT_TEMPLATE.format(
                home_dir=self._home_dir,
                ssh_username=username,
            )

            def start_container(
                worker: PoolWorker,
            ) -> tuple[str, bool, str]:
                result = ssh_run(
                    worker.ip, waa_start_script, stream=False, step="START",
                    username=username,
                )
                output = result.stdout.strip() if result.stdout else ""
                return (worker.name, result.returncode == 0, output)

            with ThreadPoolExecutor(max_workers=min(len(pool.workers), 5)) as executor:
                futures = {executor.submit(start_container, w): w.name for w in pool.workers}
                for future in as_completed(futures):
                    name, success, output = future.result()
                    if "ALREADY_RUNNING" in output:
                        status = "already running"
                    elif "STARTED" in output:
                        status = "container started"
                    elif success:
                        status = "ok"
                    else:
                        status = "FAILED"
                    self._log("POOL-WAIT", f"  {name}: {status}")

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
                    config = VMConfig(
                        name=name,
                        ssh_host=worker.ip,
                        internal_ip="localhost",
                    )
                    monitor = VMMonitor(config, timeout=5)
                    ready, _response = monitor.check_waa_probe()

                    if ready:
                        # Also check evaluate server (informational)
                        try:
                            eval_result = ssh_run(
                                worker.ip,
                                "curl -sf http://localhost:5051/probe",
                                stream=False,
                                step="EVAL",
                                username=self._ssh_username,
                            )
                            eval_ok = eval_result.returncode == 0
                        except Exception:
                            eval_ok = False
                        eval_status = ", evaluate: ok" if eval_ok else ", evaluate: not ready"
                        self._log("POOL-WAIT", f"  {name}: READY{eval_status}")
                        workers_ready.append(worker)
                        del workers_pending[name]
                        self.registry.update_worker(name, waa_ready=True, status="ready")
                except Exception:
                    pass

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
        agent_factory: Callable[[], Any] | None = None,
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
            agent_factory: Optional callable that returns a BenchmarkAgent.
                When provided, overrides agent/model and runs externally.

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

        # Get ready workers
        ready_workers = [w for w in pool.workers if w.waa_ready or w.status == "ready"]
        if not ready_workers:
            raise RuntimeError("No workers ready. Run wait() first.")

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

        if agent_factory is not None:
            return self._run_external_agent(ready_workers, tasks, agent_factory, exp_name)

        # Default path: run WAA's built-in agent via docker exec
        # Uses docker exec -d (detached) + tail -f for streaming.
        # Process survives SSH drops; tail -f reconnects automatically.
        stale_timeout = 15 * 60  # Kill if no log activity for 15 minutes
        _username = self._ssh_username

        def run_on_worker(
            worker: PoolWorker,
            worker_idx: int,
            total_workers: int,
        ) -> tuple[str, int, int, str | None]:
            log_file = "/tmp/benchmark.log"
            exit_file = "/tmp/benchmark.exit"

            # Create a subset test JSON if --tasks limits the count.
            # WAA's run.py uses --test_all_meta_path to decide which tasks to run.
            # Without this, it runs ALL 154 tasks regardless of our --tasks flag.
            test_meta_arg = ""
            if tasks and tasks < 154:
                subset_json = "/tmp/test_subset.json"
                py_cmd = (
                    f"import json; "
                    f"data=json.load(open('/client/evaluation_examples_windows/test_all.json')); "
                    f"pairs=[(d,t) for d in data for t in data[d]][:{tasks}]; "
                    f"s={{}}; [s.setdefault(d,[]).append(t) for d,t in pairs]; "
                    f"json.dump(s,open('{subset_json}','w'),indent=2); "
                    f"print(f'Created subset: {{len(pairs)}} tasks')"
                )
                ssh_run(
                    worker.ip,
                    f'docker exec winarena python -c "{py_cmd}"',
                    username=_username,
                )
                self._log("RUN", f"  {worker.name}: limited to {tasks} tasks")
                test_meta_arg = f"--test_all_meta_path {subset_json} "

            # Start benchmark detached inside container (returns immediately)
            run_cmd = (
                f"cd /client && python -u run.py "
                f"--agent {agent} --model {model} "
                f"--exp_name {exp_name}_{worker.name} "
                f"--worker_id {worker_idx} --num_workers {total_workers} "
                f"--emulator_ip 172.30.0.2 {test_meta_arg}"
                f"> {log_file} 2>&1; echo $? > {exit_file}"
            )
            ssh_run(
                worker.ip,
                f"docker exec -d -e OPENAI_API_KEY='{api_key}' winarena "
                f"bash -c '{run_cmd}'",
                username=_username,
            )
            self._log("RUN", f"  {worker.name}: started (detached), log: {log_file}")

            # Wait for process to start and get its PID
            time.sleep(3)
            pid_result = ssh_run(
                worker.ip,
                "docker exec winarena pgrep -f 'python.*run.py' || echo ''",
                username=_username,
            )
            pid = pid_result.stdout.strip().splitlines()[0] if pid_result.stdout.strip() else ""
            if pid:
                self._log("RUN", f"  {worker.name}: benchmark PID {pid}")
                tail_cmd = f"docker exec winarena tail -f --pid={pid} {log_file}"
            else:
                self._log("RUN", f"  {worker.name}: could not get PID, using plain tail -f")
                tail_cmd = f"docker exec winarena tail -f {log_file}"

            # Stream logs via tail -f with auto-reconnect on SSH drop
            # tail -f --pid exits when the benchmark process dies
            last_activity = time.time()
            while True:
                try:
                    result = ssh_run(
                        worker.ip,
                        tail_cmd,
                        stream=True,
                        step="RUN",
                        log_fn=self.log_fn,
                        username=_username,
                    )
                    # tail -f exited — process likely done
                    break
                except KeyboardInterrupt:
                    self._log("RUN", f"  {worker.name}: interrupted (process continues on VM)")
                    return (worker.name, 0, 1, "interrupted by user")
                except Exception as e:
                    # SSH dropped — check if benchmark is still running
                    self._log("RUN", f"  {worker.name}: SSH reconnecting ({e})")
                    time.sleep(5)
                    try:
                        check = ssh_run(
                            worker.ip,
                            "docker exec winarena pgrep -f run.py > /dev/null "
                            "&& echo RUNNING || echo DONE",
                            username=_username,
                        )
                        if "DONE" in check.stdout:
                            break
                        # Check for stale progress
                        mtime_result = ssh_run(
                            worker.ip,
                            f"docker exec winarena stat -c %Y {log_file} 2>/dev/null || echo 0",
                            username=_username,
                        )
                        now_result = ssh_run(worker.ip, "date +%s", username=_username)
                        mtime = int(mtime_result.stdout.strip()) if mtime_result.stdout.strip().isdigit() else 0
                        now = int(now_result.stdout.strip()) if now_result.stdout.strip().isdigit() else 0
                        if mtime > 0 and now - mtime > stale_timeout:
                            self._log(
                                "RUN",
                                f"  {worker.name}: no log activity for "
                                f"{stale_timeout // 60}m — killing",
                            )
                            ssh_run(
                                worker.ip,
                                "docker exec winarena bash -c "
                                "'kill -9 $(pgrep -f run.py) 2>/dev/null' || true",
                                username=_username,
                            )
                            return (
                                worker.name, 0, 1,
                                f"killed: no activity for {stale_timeout // 60} minutes",
                            )
                        last_activity = time.time()
                    except Exception:
                        # Can't even check — retry
                        continue

            # Get exit code
            try:
                exit_result = ssh_run(
                    worker.ip,
                    f"docker exec winarena cat {exit_file} 2>/dev/null || echo 1",
                    username=_username,
                )
                exit_code = int(exit_result.stdout.strip()) if exit_result.stdout.strip().isdigit() else 1
            except Exception:
                exit_code = 1

            if exit_code == 0:
                return (worker.name, 1, 0, None)
            else:
                return (worker.name, 0, 1, f"exit code {exit_code}")

        self._log("POOL-RUN", "")
        self._log("POOL-RUN", "Starting benchmark on all workers...")
        start_time = time.time()

        results: list[tuple[str, int, int, str | None]] = []
        with ThreadPoolExecutor(max_workers=num_workers) as executor:
            futures = {}
            for worker_idx, worker in enumerate(ready_workers):
                future = executor.submit(run_on_worker, worker, worker_idx, num_workers)
                futures[future] = worker.name

            for future in as_completed(futures):
                name, completed, failed, error = future.result()
                if error:
                    self._log("POOL-RUN", f"  {name}: FAILED - {error}")
                else:
                    self._log("POOL-RUN", f"  {name}: completed {completed} tasks")
                results.append((name, completed, failed, error))
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

        return PoolRunResult(
            total_tasks=tasks,
            completed=total_completed,
            failed=total_failed,
            elapsed_seconds=elapsed,
            worker_results=results,
        )

    def _run_external_agent(
        self,
        workers: list[PoolWorker],
        tasks: int,
        agent_factory: Callable[[], Any],
        exp_name: str,
        task_ids: list[str] | None = None,
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
            task_ids: Optional list of specific task IDs to run.
                Distributed round-robin across workers.

        Returns:
            PoolRunResult.
        """
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

        for i, worker in enumerate(workers):
            waa_port = base_waa_port + i
            eval_port = base_eval_port + i

            tunnel_mgr = SSHTunnelManager(
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

        active_workers = [
            (workers[i], worker_ports[i]) for i in range(len(tunnel_managers))
        ]

        # Distribute task_ids round-robin across workers
        if task_ids:
            per_worker_tasks: list[list[str]] = [[] for _ in active_workers]
            for idx, tid in enumerate(task_ids):
                per_worker_tasks[idx % len(active_workers)].append(tid)
        else:
            per_worker_tasks = [None] * len(active_workers)  # type: ignore[list-item]

        # Run evaluation on each worker in parallel
        start_time = time.time()
        results: list[tuple[str, int, int, str | None]] = []

        def run_on_worker(
            worker_info: tuple[tuple[PoolWorker, tuple[int, int]], list[str] | None],
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
            total_tasks=len(task_ids) if task_ids else tasks,
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
                self.registry.update_worker(worker.name, status="deallocated", waa_ready=False)
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

        Starts all VMs in the pool, waits for SSH access, then starts
        WAA containers and waits for readiness. This is much faster than
        creating a new pool (~5 min vs ~42 min) because Docker images
        and Windows disk state are preserved.

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
            self.registry.update_worker(worker.name, status="ready")

        # Wait for WAA readiness (starts containers, waits for probe)
        self._log("POOL-RESUME", "Starting WAA containers and waiting for readiness...")
        ready_workers = self.wait(
            timeout_minutes=timeout_minutes,
            start_containers=True,
        )

        self._log("POOL-RESUME", "=" * 60)
        self._log("POOL-RESUME", f"Pool resumed: {len(ready_workers)}/{len(pool.workers)} workers ready")
        if ready_workers:
            self._log("POOL-RESUME", "  Run benchmark: oa-vm pool-run --tasks 10")
        self._log("POOL-RESUME", "=" * 60)

        return ready_workers

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
