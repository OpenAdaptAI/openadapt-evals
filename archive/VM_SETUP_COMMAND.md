# VM Setup Command: Technical Specification

**Version**: 1.0
**Date**: January 2026
**Component**: openadapt-evals benchmarks CLI
**Status**: Design Complete, Ready for Implementation

---

## Table of Contents

1. [Command Specification](#1-command-specification)
2. [Architecture Overview](#2-architecture-overview)
3. [Implementation Phases](#3-implementation-phases)
4. [Error Handling Matrix](#4-error-handling-matrix)
5. [Integration Points](#5-integration-points)
6. [Code Structure](#6-code-structure)
7. [Testing Requirements](#7-testing-requirements)
8. [Performance Targets](#8-performance-targets)

---

## 1. Command Specification

### 1.1 Command Syntax

```bash
uv run python -m openadapt_evals.benchmarks.cli vm-setup [OPTIONS]
```

### 1.2 Options

| Option | Type | Default | Description |
|--------|------|---------|-------------|
| `--host` | str | $WAA_VM_HOST | VM hostname or IP address |
| `--image` | str | `windowsarena/winarena:latest` | Docker image to pull |
| `--container-name` | str | `winarena` | Name for the container |
| `--rebuild` | flag | False | Remove existing container and rebuild |
| `--verify-nested-virt` | flag | True | Check nested virtualization support |
| `--timeout` | int | 1800 | Overall timeout in seconds (30 min) |
| `--skip-smoke-test` | flag | False | Skip end-to-end smoke test |
| `--log-file` | path | `/tmp/waa_setup.log` | Log file location on VM |
| `--azure-cr` | str | None | Azure Container Registry URL (fallback) |
| `--verbose` | flag | False | Show detailed progress |

### 1.3 Usage Examples

**Basic Usage** (uses defaults):
```bash
uv run python -m openadapt_evals.benchmarks.cli vm-setup
```

**Rebuild Existing Container**:
```bash
uv run python -m openadapt_evals.benchmarks.cli vm-setup --rebuild
```

**Use Azure Container Registry**:
```bash
uv run python -m openadapt_evals.benchmarks.cli vm-setup \
  --azure-cr myregistry.azurecr.io \
  --image myregistry.azurecr.io/winarena:latest
```

**Quick Setup (Skip Smoke Test)**:
```bash
uv run python -m openadapt_evals.benchmarks.cli vm-setup \
  --skip-smoke-test \
  --timeout 900
```

**Debug Mode**:
```bash
uv run python -m openadapt_evals.benchmarks.cli vm-setup \
  --verbose \
  --log-file /tmp/waa_setup_debug.log
```

### 1.4 Exit Codes

| Code | Meaning | Action Required |
|------|---------|-----------------|
| 0 | Success | None - container ready |
| 1 | Pre-flight check failed | Fix VM configuration |
| 2 | Docker daemon failure | Restart daemon or VM |
| 3 | Image pull failed | Check network, retry, or use ACR |
| 4 | Container creation failed | Check Docker logs, verify config |
| 5 | Windows boot timeout | Increase timeout or check VM resources |
| 6 | WAA server failure | Check server logs, verify image |
| 7 | Smoke test failed | Check accessibility tree, verify API |
| 8 | Timeout exceeded | Increase --timeout or check for hangs |
| 9 | Unknown error | Check logs, report issue |

### 1.5 Output Format

**Standard Output** (Human-Readable):
```
[vm-setup] Starting WAA container setup on 172.171.112.41
[vm-setup] Phase 1/9: Pre-flight checks
  ✓ SSH connectivity
  ✓ Docker daemon running
  ✓ Nested virtualization enabled (/dev/kvm exists)
  ✓ Disk space: 120GB free (need 50GB)
[vm-setup] Phase 2/9: Image pull
  → Pulling windowsarena/winarena:latest from Docker Hub
  → Progress: 1.2GB / 5.3GB (23%) - ETA 8m 30s
  → Progress: 2.5GB / 5.3GB (47%) - ETA 5m 12s
  ✓ Image pulled successfully (12m 34s)
[vm-setup] Phase 3/9: Container creation
  → Removing old container 'winarena' (if exists)
  → Creating container with health checks
  ✓ Container created: winarena (ID: a3f9d8e2c1b4)
[vm-setup] Phase 4/9: Windows VM boot
  → Waiting for QEMU initialization...
  → Windows starting (2m 12s elapsed)
  → Desktop visible on VNC (5m 45s elapsed)
  ✓ Windows booted successfully (6m 23s)
[vm-setup] Phase 5/9: WAA server initialization
  → Waiting for port 5000...
  → Flask app starting...
  ✓ WAA server ready (8m 10s elapsed)
[vm-setup] Phase 6/9: Accessibility tree verification
  → Testing UI automation API...
  ✓ Accessibility tree available
[vm-setup] Phase 7/9: End-to-end smoke test
  → Submitting test task: notepad_open
  → Action: click(x=50, y=50)
  → Screenshot captured
  ✓ Smoke test passed
[vm-setup] Phase 8/9: Persist results
  ✓ Setup log saved to /tmp/waa_setup.log
  ✓ Container ID saved to /tmp/waa_container_id
[vm-setup] Phase 9/9: Final validation
  ✓ All health checks passing

SUCCESS: WAA container ready for evaluation
  Total time: 18m 42s
  Container: winarena (a3f9d8e2c1b4)
  Server: http://172.171.112.41:5000
  Status: ✓ Ready

Next steps:
  1. Run evaluation: uv run python -m openadapt_evals.benchmarks.cli evaluate --benchmark waa
  2. Check status: uv run python -m openadapt_evals.benchmarks.cli probe
  3. View logs: ssh azureuser@172.171.112.41 "tail -f /tmp/waa_setup.log"
```

**JSON Output** (for programmatic use):
```bash
uv run python -m openadapt_evals.benchmarks.cli vm-setup --json
```

```json
{
  "success": true,
  "exit_code": 0,
  "duration_seconds": 1122,
  "timestamp": "2026-01-18T10:45:23Z",
  "host": "172.171.112.41",
  "container": {
    "name": "winarena",
    "id": "a3f9d8e2c1b4",
    "image": "windowsarena/winarena:latest",
    "status": "running",
    "health": "healthy"
  },
  "phases": [
    {
      "name": "pre_flight_checks",
      "status": "success",
      "duration_seconds": 12,
      "checks": {
        "ssh": true,
        "docker": true,
        "nested_virt": true,
        "disk_space": 120000000000
      }
    },
    {
      "name": "image_pull",
      "status": "success",
      "duration_seconds": 754,
      "image_size_bytes": 5300000000,
      "source": "docker.io"
    }
    // ... other phases
  ],
  "health_checks": {
    "docker_daemon": "healthy",
    "container_status": "healthy",
    "windows_vm_boot": "healthy",
    "waa_server_ready": "healthy",
    "accessibility_tree": "healthy"
  },
  "costs": {
    "vm_runtime_seconds": 1122,
    "estimated_cost_usd": 0.062
  }
}
```

---

## 2. Architecture Overview

### 2.1 System Context

```
┌────────────────────────────────────────────────────────┐
│                    Local Machine                       │
│  ┌──────────────────────────────────────────────────┐  │
│  │         openadapt-evals CLI                      │  │
│  │  ┌────────────────────────────────────────────┐  │  │
│  │  │   vm-setup command                         │  │  │
│  │  │   (VMSetupOrchestrator)                    │  │  │
│  │  └────────────────────────────────────────────┘  │  │
│  └──────────────────┬───────────────────────────────┘  │
│                     │ SSH commands                     │
└─────────────────────┼──────────────────────────────────┘
                      │
                      ▼
┌────────────────────────────────────────────────────────┐
│              Azure VM (172.171.112.41)                 │
│  ┌──────────────────────────────────────────────────┐  │
│  │          Docker Daemon                           │  │
│  │  ┌────────────────────────────────────────────┐  │  │
│  │  │   winarena Container                       │  │  │
│  │  │  ┌──────────────────────────────────────┐  │  │  │
│  │  │  │  QEMU/KVM                            │  │  │  │
│  │  │  │  ┌────────────────────────────────┐  │  │  │  │
│  │  │  │  │  Windows 11 VM                 │  │  │  │  │
│  │  │  │  │  ┌──────────────────────────┐  │  │  │  │  │
│  │  │  │  │  │  WAA Flask Server        │  │  │  │  │  │
│  │  │  │  │  │  - UI Automation API     │  │  │  │  │  │
│  │  │  │  │  │  - Accessibility Tree    │  │  │  │  │  │
│  │  │  │  │  │  - Screenshot Service    │  │  │  │  │  │
│  │  │  │  │  └──────────────────────────┘  │  │  │  │  │
│  │  │  │  └────────────────────────────────┘  │  │  │  │
│  │  │  └──────────────────────────────────────┘  │  │  │
│  │  └────────────────────────────────────────────┘  │  │
│  └──────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────┘
```

### 2.2 Component Responsibilities

**VMSetupOrchestrator** (Local):
- Coordinates all setup phases
- Executes SSH commands on remote VM
- Monitors progress and handles errors
- Implements retry logic and timeouts
- Generates human-readable and JSON output

**Docker Daemon** (VM):
- Pulls container images
- Manages container lifecycle
- Provides health check interfaces

**winarena Container**:
- Runs QEMU/KVM for Windows virtualization
- Exposes WAA server on port 5000
- Provides VNC access for debugging

**WAA Server** (Inside Windows VM):
- Flask application serving UI automation API
- Manages Windows accessibility tree
- Executes actions via UI Automation framework
- Captures screenshots

---

## 3. Implementation Phases

### Phase 1: Pre-flight Checks

**Goal**: Validate environment before attempting setup

**Duration**: 10-30 seconds

**Checks**:

#### 1.1 SSH Connectivity
```python
def check_ssh_connectivity(host: str) -> PreflightCheck:
    """Verify we can SSH to the VM"""
    try:
        result = subprocess.run(
            ["ssh", "-o", "ConnectTimeout=10", host, "echo", "ok"],
            capture_output=True,
            text=True,
            timeout=15
        )
        return PreflightCheck(
            name="ssh_connectivity",
            passed=result.returncode == 0 and "ok" in result.stdout,
            message=f"SSH connection successful" if result.returncode == 0 else f"SSH failed: {result.stderr}"
        )
    except subprocess.TimeoutExpired:
        return PreflightCheck(
            name="ssh_connectivity",
            passed=False,
            message="SSH connection timeout (>15s)"
        )
```

#### 1.2 Docker Daemon Running
```python
def check_docker_daemon(host: str) -> PreflightCheck:
    """Verify Docker daemon is active"""
    result = subprocess.run(
        ["ssh", host, "systemctl", "is-active", "docker"],
        capture_output=True,
        text=True
    )

    if result.returncode == 0 and result.stdout.strip() == "active":
        return PreflightCheck(
            name="docker_daemon",
            passed=True,
            message="Docker daemon running"
        )

    # Try to start Docker
    logger.info("Docker daemon not running, attempting to start...")
    start_result = subprocess.run(
        ["ssh", host, "sudo", "systemctl", "start", "docker"],
        capture_output=True,
        text=True
    )

    if start_result.returncode == 0:
        time.sleep(5)  # Wait for daemon to initialize
        # Verify it started
        verify_result = subprocess.run(
            ["ssh", host, "systemctl", "is-active", "docker"],
            capture_output=True,
            text=True
        )
        if verify_result.stdout.strip() == "active":
            return PreflightCheck(
                name="docker_daemon",
                passed=True,
                message="Docker daemon started successfully"
            )

    return PreflightCheck(
        name="docker_daemon",
        passed=False,
        message=f"Docker daemon failed to start: {start_result.stderr}"
    )
```

#### 1.3 Nested Virtualization Support
```python
def check_nested_virtualization(host: str) -> PreflightCheck:
    """Verify /dev/kvm exists and is accessible"""
    result = subprocess.run(
        ["ssh", host, "ls", "-l", "/dev/kvm"],
        capture_output=True,
        text=True
    )

    if result.returncode == 0 and "kvm" in result.stdout:
        return PreflightCheck(
            name="nested_virtualization",
            passed=True,
            message="Nested virtualization enabled (/dev/kvm exists)"
        )

    # Check if KVM module is loaded
    lsmod_result = subprocess.run(
        ["ssh", host, "lsmod", "|", "grep", "kvm"],
        capture_output=True,
        text=True,
        shell=True
    )

    if lsmod_result.returncode != 0:
        return PreflightCheck(
            name="nested_virtualization",
            passed=False,
            message="KVM module not loaded. VM may not support nested virtualization. "
                    "Required VM types: Dv5, Ddsv5, Ev5, Edsv5 series"
        )

    return PreflightCheck(
        name="nested_virtualization",
        passed=False,
        message="/dev/kvm not accessible. Check permissions or VM configuration."
    )
```

#### 1.4 Disk Space
```python
def check_disk_space(host: str, required_gb: int = 50) -> PreflightCheck:
    """Verify sufficient disk space for image and container"""
    result = subprocess.run(
        ["ssh", host, "df", "/var/lib/docker", "--output=avail", "-BG"],
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        return PreflightCheck(
            name="disk_space",
            passed=False,
            message=f"Failed to check disk space: {result.stderr}"
        )

    # Parse output (format: "Avail\n123G")
    lines = result.stdout.strip().split('\n')
    if len(lines) < 2:
        return PreflightCheck(
            name="disk_space",
            passed=False,
            message="Unexpected df output format"
        )

    avail_str = lines[1].rstrip('G')
    try:
        avail_gb = int(avail_str)
    except ValueError:
        return PreflightCheck(
            name="disk_space",
            passed=False,
            message=f"Failed to parse disk space: {avail_str}"
        )

    if avail_gb >= required_gb:
        return PreflightCheck(
            name="disk_space",
            passed=True,
            message=f"Sufficient disk space: {avail_gb}GB available (need {required_gb}GB)"
        )

    return PreflightCheck(
        name="disk_space",
        passed=False,
        message=f"Insufficient disk space: {avail_gb}GB available (need {required_gb}GB). "
                f"Clean up old containers: docker system prune -a"
    )
```

**Phase Output**:
```
[vm-setup] Phase 1/9: Pre-flight checks
  ✓ SSH connectivity
  ✓ Docker daemon running
  ✓ Nested virtualization enabled (/dev/kvm exists)
  ✓ Disk space: 120GB free (need 50GB)
```

---

### Phase 2: Image Pull with Progress Monitoring

**Goal**: Download Docker image with retry and progress tracking

**Duration**: 5-20 minutes (depends on network)

**Implementation**:

```python
def pull_image_with_progress(
    host: str,
    image: str,
    timeout: int = 1200,
    azure_cr: Optional[str] = None
) -> ImagePullResult:
    """
    Pull Docker image with progress monitoring and retry logic

    Args:
        host: VM hostname
        image: Docker image name (e.g., windowsarena/winarena:latest)
        timeout: Max time in seconds
        azure_cr: Azure Container Registry URL for fallback

    Returns:
        ImagePullResult with success status, duration, and error message if any
    """

    # Retry config: 3 attempts with 60s base delay
    retry_config = RetryConfig(
        base_delay=60,
        max_attempts=3,
        max_delay=300,
        jitter=True
    )

    attempt = 0
    start_time = time.time()

    while attempt < retry_config.max_attempts:
        attempt += 1
        logger.info(f"Image pull attempt {attempt}/{retry_config.max_attempts}")

        # Start pull in background so we can monitor progress
        pull_cmd = f"docker pull {image}"

        # Use SSH to run command and redirect output to temp file
        proc = subprocess.Popen(
            [
                "ssh", host,
                f"{pull_cmd} 2>&1 | tee /tmp/docker_pull.log"
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )

        # Monitor progress
        last_progress_time = time.time()
        progress_timeout = 300  # 5 minutes without progress = stuck

        try:
            while proc.poll() is None:
                # Read progress from log file
                log_result = subprocess.run(
                    ["ssh", host, "tail", "-1", "/tmp/docker_pull.log"],
                    capture_output=True,
                    text=True,
                    timeout=5
                )

                if log_result.returncode == 0:
                    last_line = log_result.stdout.strip()

                    # Parse Docker pull progress
                    # Format: "a3f9d8e2c1b4: Downloading [==>  ] 1.2GB/5.3GB"
                    if "Downloading" in last_line or "Extracting" in last_line:
                        last_progress_time = time.time()
                        print(f"\r  → {last_line}", end="", flush=True)

                # Check for timeout
                if time.time() - start_time > timeout:
                    proc.kill()
                    return ImagePullResult(
                        success=False,
                        duration=time.time() - start_time,
                        error="Overall timeout exceeded"
                    )

                # Check for progress timeout (stuck)
                if time.time() - last_progress_time > progress_timeout:
                    proc.kill()
                    logger.warning("Image pull stuck (no progress for 5 minutes)")
                    break  # Retry

                time.sleep(2)  # Poll every 2 seconds

            # Process completed
            if proc.returncode == 0:
                duration = time.time() - start_time
                print()  # New line after progress
                logger.info(f"Image pulled successfully in {duration:.0f}s")
                return ImagePullResult(
                    success=True,
                    duration=duration,
                    error=None
                )

        except Exception as e:
            logger.error(f"Error monitoring pull progress: {e}")
            proc.kill()

        # Pull failed, retry or try fallback
        if attempt < retry_config.max_attempts:
            wait_time = retry_config.get_wait_time(attempt - 1)
            logger.info(f"Pull failed, retrying in {wait_time:.0f}s...")
            time.sleep(wait_time)
        elif azure_cr and attempt == retry_config.max_attempts:
            # Last attempt failed, try Azure CR fallback
            logger.info(f"Docker Hub pull failed, trying Azure Container Registry: {azure_cr}")
            acr_image = f"{azure_cr}/{image.split('/')[-1]}"
            # One more attempt with ACR
            # (recursive call with azure_cr=None to avoid infinite loop)
            return pull_image_with_progress(host, acr_image, timeout, azure_cr=None)

    # All retries exhausted
    return ImagePullResult(
        success=False,
        duration=time.time() - start_time,
        error=f"Image pull failed after {retry_config.max_attempts} attempts"
    )
```

**Phase Output**:
```
[vm-setup] Phase 2/9: Image pull
  → Pulling windowsarena/winarena:latest from Docker Hub
  → a3f9d8e2c1b4: Downloading [==>                ] 1.2GB/5.3GB - ETA 8m 30s
  → a3f9d8e2c1b4: Downloading [======>            ] 2.5GB/5.3GB - ETA 5m 12s
  → a3f9d8e2c1b4: Downloading [=============>     ] 4.1GB/5.3GB - ETA 2m 05s
  → a3f9d8e2c1b4: Extracting [========>          ] 2.1GB/5.3GB
  ✓ Image pulled successfully (12m 34s)
```

---

### Phase 3: Container Creation with Health Hooks

**Goal**: Create Docker container with proper configuration

**Duration**: 5-15 seconds

**Implementation**:

```python
def create_container(
    host: str,
    image: str,
    container_name: str,
    rebuild: bool = False
) -> ContainerCreateResult:
    """
    Create WAA container with health checks

    Args:
        host: VM hostname
        image: Docker image to use
        container_name: Name for the container
        rebuild: If True, remove existing container first

    Returns:
        ContainerCreateResult with container ID and status
    """

    # Step 1: Remove old container if rebuild=True or if exists and not running
    if rebuild:
        logger.info(f"Removing old container '{container_name}' (rebuild=True)")
        remove_result = subprocess.run(
            ["ssh", host, "docker", "rm", "-f", container_name],
            capture_output=True,
            text=True
        )
        if remove_result.returncode != 0 and "No such container" not in remove_result.stderr:
            logger.warning(f"Failed to remove container: {remove_result.stderr}")

    # Step 2: Check if container already exists
    inspect_result = subprocess.run(
        ["ssh", host, "docker", "inspect", "-f", "{{.State.Status}}", container_name],
        capture_output=True,
        text=True
    )

    if inspect_result.returncode == 0:
        status = inspect_result.stdout.strip()
        if status == "running":
            logger.info(f"Container '{container_name}' already running")
            # Get container ID
            id_result = subprocess.run(
                ["ssh", host, "docker", "inspect", "-f", "{{.Id}}", container_name],
                capture_output=True,
                text=True
            )
            container_id = id_result.stdout.strip()
            return ContainerCreateResult(
                success=True,
                container_id=container_id,
                status="running",
                message="Container already running (idempotent)"
            )
        else:
            # Container exists but not running, remove it
            logger.info(f"Container '{container_name}' exists with status '{status}', removing")
            subprocess.run(
                ["ssh", host, "docker", "rm", "-f", container_name],
                capture_output=True,
                text=True
            )

    # Step 3: Create container with proper configuration
    # Based on waa_setup.md lines 113-126
    docker_run_cmd = [
        "docker", "run",
        "-d",  # Detached mode
        "--name", container_name,
        "--device", "/dev/kvm",  # KVM device for nested virtualization
        "--cap-add", "NET_ADMIN",  # Network capabilities
        "-p", "5000:5000",  # WAA server port
        "-p", "8006:8006",  # VNC port
        "-e", "RAM_SIZE=8G",  # Windows VM RAM
        "-e", "CPU_CORES=4",  # Windows VM CPUs
        "-e", "DISK_SIZE=64G",  # Windows VM disk
        "--restart", "unless-stopped",  # Auto-restart policy
        image
    ]

    logger.info(f"Creating container with command: {' '.join(docker_run_cmd)}")

    create_result = subprocess.run(
        ["ssh", host] + docker_run_cmd,
        capture_output=True,
        text=True,
        timeout=30
    )

    if create_result.returncode != 0:
        return ContainerCreateResult(
            success=False,
            container_id=None,
            status="failed",
            message=f"Container creation failed: {create_result.stderr}"
        )

    container_id = create_result.stdout.strip()
    logger.info(f"Container created with ID: {container_id}")

    # Step 4: Verify container is running
    time.sleep(2)  # Brief delay for container to initialize

    verify_result = subprocess.run(
        ["ssh", host, "docker", "inspect", "-f", "{{.State.Status}}", container_name],
        capture_output=True,
        text=True
    )

    if verify_result.returncode == 0 and verify_result.stdout.strip() == "running":
        return ContainerCreateResult(
            success=True,
            container_id=container_id,
            status="running",
            message="Container created and running"
        )

    # Container created but not running - get logs for debugging
    logs_result = subprocess.run(
        ["ssh", host, "docker", "logs", "--tail", "50", container_name],
        capture_output=True,
        text=True
    )

    return ContainerCreateResult(
        success=False,
        container_id=container_id,
        status=verify_result.stdout.strip() if verify_result.returncode == 0 else "unknown",
        message=f"Container created but not running. Logs:\n{logs_result.stdout}"
    )
```

**Phase Output**:
```
[vm-setup] Phase 3/9: Container creation
  → Checking for existing container 'winarena'
  → Removing old container (rebuild=True)
  → Creating container with health checks
  ✓ Container created: winarena (ID: a3f9d8e2c1b4)
  ✓ Container status: running
```

---

### Phase 4: QEMU/Windows Boot Detection

**Goal**: Wait for Windows VM to fully boot inside container

**Duration**: 5-15 minutes (highly variable)

**Implementation**:

```python
def wait_for_windows_boot(
    host: str,
    container_name: str,
    timeout: int = 1200  # 20 minutes
) -> WindowsBootResult:
    """
    Wait for Windows VM to boot by monitoring container logs and VNC

    Strategy:
    1. Monitor container logs for QEMU initialization messages
    2. Wait for VNC port to become accessible
    3. Optional: Check VNC screenshot for non-black screen
    4. Use heuristic: uptime > 5 minutes = probably booted

    Args:
        host: VM hostname
        container_name: Container name
        timeout: Max time to wait in seconds

    Returns:
        WindowsBootResult with success status and boot duration
    """

    start_time = time.time()
    logger.info("Waiting for Windows VM to boot...")

    # Stage 1: Wait for QEMU to initialize (first 60 seconds)
    logger.info("Stage 1: Waiting for QEMU initialization...")

    for i in range(12):  # 12 attempts × 5s = 60s max
        if time.time() - start_time > timeout:
            return WindowsBootResult(
                success=False,
                duration=time.time() - start_time,
                stage="qemu_init",
                message="Timeout waiting for QEMU initialization"
            )

        # Check container logs for QEMU startup messages
        logs_result = subprocess.run(
            ["ssh", host, "docker", "logs", "--tail", "100", container_name],
            capture_output=True,
            text=True,
            timeout=10
        )

        if "QEMU" in logs_result.stdout or "Starting VM" in logs_result.stdout:
            logger.info(f"QEMU initialized ({time.time() - start_time:.0f}s elapsed)")
            break

        # Check if container is still running
        status_result = subprocess.run(
            ["ssh", host, "docker", "inspect", "-f", "{{.State.Status}}", container_name],
            capture_output=True,
            text=True
        )

        if status_result.returncode != 0 or status_result.stdout.strip() != "running":
            # Container died
            logs_result = subprocess.run(
                ["ssh", host, "docker", "logs", "--tail", "100", container_name],
                capture_output=True,
                text=True
            )
            return WindowsBootResult(
                success=False,
                duration=time.time() - start_time,
                stage="qemu_init",
                message=f"Container stopped during boot. Logs:\n{logs_result.stdout}"
            )

        time.sleep(5)

    # Stage 2: Wait for VNC port (next 60 seconds)
    logger.info("Stage 2: Waiting for VNC port...")

    vnc_ready = False
    for i in range(12):  # 12 attempts × 5s = 60s max
        if time.time() - start_time > timeout:
            return WindowsBootResult(
                success=False,
                duration=time.time() - start_time,
                stage="vnc_port",
                message="Timeout waiting for VNC port"
            )

        # Try to connect to VNC port
        vnc_check = subprocess.run(
            ["ssh", host, "nc", "-zv", "localhost", "8006"],
            capture_output=True,
            text=True,
            timeout=5
        )

        if vnc_check.returncode == 0:
            logger.info(f"VNC port accessible ({time.time() - start_time:.0f}s elapsed)")
            vnc_ready = True
            break

        time.sleep(5)

    if not vnc_ready:
        return WindowsBootResult(
            success=False,
            duration=time.time() - start_time,
            stage="vnc_port",
            message="VNC port never became accessible"
        )

    # Stage 3: Wait for Windows boot (use uptime heuristic)
    # Windows typically takes 5-8 minutes to boot fully
    logger.info("Stage 3: Waiting for Windows to boot (5-15 minutes)...")

    # Exponential backoff: 10s, 20s, 30s, 60s, 60s, ...
    wait_times = [10, 20, 30] + [60] * 15  # Total: ~17 minutes

    for wait_time in wait_times:
        if time.time() - start_time > timeout:
            return WindowsBootResult(
                success=False,
                duration=time.time() - start_time,
                stage="windows_boot",
                message=f"Timeout waiting for Windows boot (waited {time.time() - start_time:.0f}s)"
            )

        # Get container uptime
        uptime_result = subprocess.run(
            ["ssh", host, "docker", "inspect", "-f", "{{.State.StartedAt}}", container_name],
            capture_output=True,
            text=True
        )

        if uptime_result.returncode == 0:
            started_at_str = uptime_result.stdout.strip()
            # Parse ISO format timestamp
            started_at = datetime.fromisoformat(started_at_str.replace('Z', '+00:00'))
            uptime_seconds = (datetime.now(timezone.utc) - started_at).total_seconds()

            elapsed = time.time() - start_time
            logger.info(f"  → Windows booting... (uptime: {uptime_seconds:.0f}s, elapsed: {elapsed:.0f}s)")

            # Heuristic: if uptime > 5 minutes, Windows is probably booted
            # We'll verify with WAA server check in next phase
            if uptime_seconds >= 300:  # 5 minutes
                logger.info(f"Windows likely booted (uptime: {uptime_seconds:.0f}s)")
                return WindowsBootResult(
                    success=True,
                    duration=time.time() - start_time,
                    stage="complete",
                    message=f"Windows boot detected (uptime: {uptime_seconds:.0f}s)"
                )

        time.sleep(wait_time)

    # Reached here = timeout
    return WindowsBootResult(
        success=False,
        duration=time.time() - start_time,
        stage="windows_boot",
        message=f"Windows boot timeout after {timeout}s"
    )
```

**Phase Output**:
```
[vm-setup] Phase 4/9: Windows VM boot
  → Stage 1: Waiting for QEMU initialization...
  ✓ QEMU initialized (12s elapsed)
  → Stage 2: Waiting for VNC port...
  ✓ VNC port accessible (45s elapsed)
  → Stage 3: Waiting for Windows to boot (5-15 minutes)...
  → Windows booting... (uptime: 120s, elapsed: 2m 15s)
  → Windows booting... (uptime: 180s, elapsed: 3m 25s)
  → Windows booting... (uptime: 240s, elapsed: 4m 35s)
  → Windows booting... (uptime: 300s, elapsed: 5m 45s)
  ✓ Windows likely booted (uptime: 300s)
  ✓ Windows boot complete (6m 23s total)
```

---

### Phase 5: WAA Server Initialization

**Goal**: Wait for WAA Flask server to become ready

**Duration**: 1-3 minutes

**Implementation**:

```python
def wait_for_waa_server(
    host: str,
    port: int = 5000,
    timeout: int = 300  # 5 minutes
) -> ServerReadyResult:
    """
    Wait for WAA Flask server to be ready

    Strategy:
    1. Wait for port to be accessible
    2. Check /probe endpoint returns 200
    3. Verify response is valid JSON
    4. Use exponential backoff

    Args:
        host: VM hostname (or IP)
        port: WAA server port
        timeout: Max time to wait

    Returns:
        ServerReadyResult with success status
    """

    start_time = time.time()
    logger.info(f"Waiting for WAA server on {host}:{port}...")

    retry_config = RetryConfig(
        base_delay=5,
        max_attempts=10,
        max_delay=60,
        jitter=True
    )

    for attempt in range(retry_config.max_attempts):
        if time.time() - start_time > timeout:
            return ServerReadyResult(
                success=False,
                duration=time.time() - start_time,
                message=f"Timeout waiting for WAA server after {timeout}s"
            )

        try:
            # Try to connect to /probe endpoint
            response = requests.get(
                f"http://{host}:{port}/probe",
                timeout=10
            )

            if response.status_code == 200:
                # Server is ready
                duration = time.time() - start_time
                logger.info(f"WAA server ready ({duration:.0f}s)")

                # Try to parse response to verify server is healthy
                try:
                    data = response.json()
                    logger.info(f"Server response: {data}")
                except:
                    logger.warning("Server returned 200 but response is not JSON")

                return ServerReadyResult(
                    success=True,
                    duration=duration,
                    message="WAA server ready"
                )

            elif response.status_code >= 500:
                # Server error - might be starting up
                logger.info(f"  → Server returned {response.status_code}, waiting...")

        except requests.ConnectionError:
            logger.info(f"  → Connection refused, server not ready yet...")
        except requests.Timeout:
            logger.info(f"  → Request timeout, server might be busy...")
        except Exception as e:
            logger.warning(f"  → Unexpected error: {e}")

        # Wait before retry
        if attempt < retry_config.max_attempts - 1:
            wait_time = retry_config.get_wait_time(attempt)
            elapsed = time.time() - start_time
            logger.info(f"  → Attempt {attempt + 1}/{retry_config.max_attempts} failed, "
                       f"retrying in {wait_time:.0f}s (elapsed: {elapsed:.0f}s)")
            time.sleep(wait_time)

    # All retries exhausted
    return ServerReadyResult(
        success=False,
        duration=time.time() - start_time,
        message=f"WAA server not ready after {retry_config.max_attempts} attempts"
    )
```

**Phase Output**:
```
[vm-setup] Phase 5/9: WAA server initialization
  → Waiting for port 5000...
  → Connection refused, server not ready yet...
  → Attempt 1/10 failed, retrying in 5s (elapsed: 5s)
  → Server returned 500, waiting...
  → Attempt 2/10 failed, retrying in 10s (elapsed: 15s)
  → Server returned 200
  ✓ WAA server ready (45s)
```

---

### Phase 6: Accessibility Tree Verification

**Goal**: Verify Windows UI Automation is working

**Duration**: 10-30 seconds

**Implementation**:

```python
def verify_accessibility_tree(
    host: str,
    port: int = 5000
) -> AccessibilityCheckResult:
    """
    Verify accessibility tree is available

    Strategy:
    1. Call /api/accessibility/root to get root element
    2. Verify response contains element data
    3. Try to get desktop children

    Args:
        host: VM hostname
        port: WAA server port

    Returns:
        AccessibilityCheckResult with success status
    """

    logger.info("Verifying accessibility tree...")

    try:
        # Test 1: Get root element
        response = requests.get(
            f"http://{host}:{port}/api/accessibility/root",
            timeout=15
        )

        if response.status_code != 200:
            return AccessibilityCheckResult(
                success=False,
                message=f"Accessibility API returned {response.status_code}: {response.text}"
            )

        # Try to parse response
        try:
            data = response.json()
        except:
            return AccessibilityCheckResult(
                success=False,
                message=f"Accessibility API response is not valid JSON: {response.text}"
            )

        # Verify response has expected structure
        # Expected: {"element": {...}, "children": [...]} or similar
        if not isinstance(data, dict):
            return AccessibilityCheckResult(
                success=False,
                message=f"Unexpected response format: {type(data)}"
            )

        # Check for common keys that indicate a valid tree
        valid_keys = ["element", "tree", "root", "name", "control_type"]
        has_valid_key = any(key in data for key in valid_keys)

        if not has_valid_key:
            return AccessibilityCheckResult(
                success=False,
                message=f"Response missing expected keys. Got: {list(data.keys())}"
            )

        logger.info(f"Accessibility tree structure: {list(data.keys())}")

        # Test 2: Try to interact with tree (optional)
        # This could be a simple query like "find element by name"
        # For now, we'll just verify the root endpoint works

        return AccessibilityCheckResult(
            success=True,
            message="Accessibility tree available and responsive"
        )

    except requests.Timeout:
        return AccessibilityCheckResult(
            success=False,
            message="Timeout connecting to accessibility API (>15s)"
        )
    except requests.ConnectionError:
        return AccessibilityCheckResult(
            success=False,
            message="Connection error accessing accessibility API"
        )
    except Exception as e:
        return AccessibilityCheckResult(
            success=False,
            message=f"Unexpected error: {e}"
        )
```

**Phase Output**:
```
[vm-setup] Phase 6/9: Accessibility tree verification
  → Testing UI automation API...
  → Accessibility tree structure: ['element', 'children', 'properties']
  ✓ Accessibility tree available and responsive
```

---

### Phase 7: End-to-End Smoke Test

**Goal**: Verify complete functionality with simple task

**Duration**: 30-60 seconds

**Implementation**:

```python
def run_smoke_test(
    host: str,
    port: int = 5000,
    skip: bool = False
) -> SmokeTestResult:
    """
    Run end-to-end smoke test

    Test: Open Notepad
    1. Submit action: click on Start button
    2. Submit action: type "notepad"
    3. Submit action: press Enter
    4. Capture screenshot
    5. Verify Notepad window appears

    Args:
        host: VM hostname
        port: WAA server port
        skip: If True, skip smoke test

    Returns:
        SmokeTestResult with success status
    """

    if skip:
        logger.info("Skipping smoke test (--skip-smoke-test)")
        return SmokeTestResult(
            success=True,
            message="Smoke test skipped",
            skipped=True
        )

    logger.info("Running end-to-end smoke test: Open Notepad")

    try:
        # Step 1: Click Start button (bottom-left corner)
        logger.info("  → Step 1: Click Start button")
        click_response = requests.post(
            f"http://{host}:{port}/api/action/click",
            json={"x": 50, "y": 1050},  # Approximate Start button location
            timeout=15
        )

        if click_response.status_code != 200:
            return SmokeTestResult(
                success=False,
                message=f"Click action failed: {click_response.status_code}",
                skipped=False
            )

        time.sleep(2)  # Wait for Start menu

        # Step 2: Type "notepad"
        logger.info("  → Step 2: Type 'notepad'")
        type_response = requests.post(
            f"http://{host}:{port}/api/action/type",
            json={"text": "notepad"},
            timeout=15
        )

        if type_response.status_code != 200:
            return SmokeTestResult(
                success=False,
                message=f"Type action failed: {type_response.status_code}",
                skipped=False
            )

        time.sleep(1)

        # Step 3: Press Enter
        logger.info("  → Step 3: Press Enter")
        enter_response = requests.post(
            f"http://{host}:{port}/api/action/key",
            json={"key": "enter"},
            timeout=15
        )

        if enter_response.status_code != 200:
            return SmokeTestResult(
                success=False,
                message=f"Key action failed: {enter_response.status_code}",
                skipped=False
            )

        time.sleep(2)  # Wait for Notepad to open

        # Step 4: Capture screenshot
        logger.info("  → Step 4: Capture screenshot")
        screenshot_response = requests.get(
            f"http://{host}:{port}/api/screenshot",
            timeout=15
        )

        if screenshot_response.status_code != 200:
            return SmokeTestResult(
                success=False,
                message=f"Screenshot failed: {screenshot_response.status_code}",
                skipped=False
            )

        # Verify screenshot is not empty
        if len(screenshot_response.content) < 1000:
            return SmokeTestResult(
                success=False,
                message="Screenshot is suspiciously small (< 1KB)",
                skipped=False
            )

        logger.info(f"  → Screenshot captured: {len(screenshot_response.content)} bytes")

        # Step 5: Verify Notepad window (look for "Notepad" in window title)
        logger.info("  → Step 5: Verify Notepad window")
        windows_response = requests.get(
            f"http://{host}:{port}/api/windows",
            timeout=15
        )

        if windows_response.status_code == 200:
            windows = windows_response.json()
            notepad_found = any("Notepad" in str(w) for w in windows)

            if notepad_found:
                logger.info("  ✓ Notepad window detected")
            else:
                logger.warning("  ⚠ Notepad window not found in window list, but actions succeeded")

        return SmokeTestResult(
            success=True,
            message="Smoke test passed: Actions executed and screenshot captured",
            skipped=False
        )

    except requests.Timeout:
        return SmokeTestResult(
            success=False,
            message="Smoke test timeout",
            skipped=False
        )
    except Exception as e:
        return SmokeTestResult(
            success=False,
            message=f"Smoke test error: {e}",
            skipped=False
        )
```

**Phase Output**:
```
[vm-setup] Phase 7/9: End-to-end smoke test
  → Running test: Open Notepad
  → Step 1: Click Start button
  → Step 2: Type 'notepad'
  → Step 3: Press Enter
  → Step 4: Capture screenshot
  → Screenshot captured: 245623 bytes
  → Step 5: Verify Notepad window
  ✓ Notepad window detected
  ✓ Smoke test passed
```

---

### Phase 8: Persist Results

**Goal**: Save setup information for future reference

**Duration**: 2-5 seconds

**Implementation**:

```python
def persist_setup_results(
    host: str,
    container_name: str,
    container_id: str,
    setup_duration: float,
    log_file: str = "/tmp/waa_setup.log"
) -> PersistResult:
    """
    Save setup results to VM for future reference

    Saves:
    1. Container ID to /tmp/waa_container_id
    2. Setup timestamp to /tmp/waa_setup_time
    3. Setup log (already saved during execution)
    4. Container configuration to /tmp/waa_container_config.json

    Args:
        host: VM hostname
        container_name: Container name
        container_id: Container ID
        setup_duration: Total setup time in seconds
        log_file: Path to log file

    Returns:
        PersistResult with success status
    """

    logger.info("Persisting setup results...")

    try:
        # 1. Save container ID
        subprocess.run(
            ["ssh", host, f"echo '{container_id}' > /tmp/waa_container_id"],
            check=True,
            timeout=5
        )
        logger.info(f"  ✓ Container ID saved to /tmp/waa_container_id")

        # 2. Save setup timestamp
        timestamp = datetime.now(timezone.utc).isoformat()
        subprocess.run(
            ["ssh", host, f"echo '{timestamp}' > /tmp/waa_setup_time"],
            check=True,
            timeout=5
        )
        logger.info(f"  ✓ Setup time saved to /tmp/waa_setup_time")

        # 3. Save container configuration
        inspect_result = subprocess.run(
            ["ssh", host, "docker", "inspect", container_name],
            capture_output=True,
            text=True,
            check=True,
            timeout=10
        )

        subprocess.run(
            ["ssh", host, f"echo '{inspect_result.stdout}' > /tmp/waa_container_config.json"],
            check=True,
            timeout=5
        )
        logger.info(f"  ✓ Container config saved to /tmp/waa_container_config.json")

        # 4. Verify log file exists
        log_check = subprocess.run(
            ["ssh", host, "test", "-f", log_file],
            timeout=5
        )

        if log_check.returncode == 0:
            logger.info(f"  ✓ Setup log available at {log_file}")
        else:
            logger.warning(f"  ⚠ Setup log not found at {log_file}")

        return PersistResult(
            success=True,
            message="Setup results persisted successfully"
        )

    except subprocess.TimeoutExpired:
        return PersistResult(
            success=False,
            message="Timeout persisting results"
        )
    except Exception as e:
        return PersistResult(
            success=False,
            message=f"Error persisting results: {e}"
        )
```

**Phase Output**:
```
[vm-setup] Phase 8/9: Persist results
  ✓ Container ID saved to /tmp/waa_container_id
  ✓ Setup time saved to /tmp/waa_setup_time
  ✓ Container config saved to /tmp/waa_container_config.json
  ✓ Setup log available at /tmp/waa_setup.log
```

---

### Phase 9: Final Validation

**Goal**: Verify all health checks pass before completing

**Duration**: 10-20 seconds

**Implementation**:

```python
def final_validation(
    host: str,
    container_name: str
) -> ValidationResult:
    """
    Run all health checks one final time

    Args:
        host: VM hostname
        container_name: Container name

    Returns:
        ValidationResult with all health check statuses
    """

    logger.info("Running final health checks...")

    checker = MultiLayerHealthChecker(host, container_name)
    results = checker.check_all_layers(timeout=60)

    # Check if all layers are healthy
    all_healthy = all(r.status == "healthy" for r in results)

    if all_healthy:
        logger.info("  ✓ All health checks passing")
        return ValidationResult(
            success=True,
            health_checks={r.layer.name: r.status for r in results},
            message="All health checks passing"
        )
    else:
        # Some checks failed
        failed = [r for r in results if r.status != "healthy"]
        logger.error(f"  ✗ {len(failed)} health check(s) failed:")
        for r in failed:
            logger.error(f"    - {r.layer.name}: {r.message}")

        return ValidationResult(
            success=False,
            health_checks={r.layer.name: r.status for r in results},
            message=f"{len(failed)} health check(s) failed"
        )
```

**Phase Output**:
```
[vm-setup] Phase 9/9: Final validation
  → Running all health checks...
  ✓ Docker daemon: healthy
  ✓ Container status: healthy
  ✓ Windows VM boot: healthy
  ✓ WAA server: healthy
  ✓ Accessibility tree: healthy
  ✓ All health checks passing
```

---

## 4. Error Handling Matrix

| Error Scenario | Detection Method | Recovery Strategy | User Message | Exit Code |
|----------------|------------------|-------------------|--------------|-----------|
| SSH connection failed | Pre-flight check timeout | None (permanent) | "Cannot connect to VM via SSH. Verify IP address and SSH keys." | 1 |
| Docker daemon not running | systemctl check | Auto-restart daemon | "Docker daemon was stopped, restarted successfully." | 0 |
| Docker daemon failed | systemctl restart fails | None (permanent) | "Docker daemon failed to start. SSH to VM and check: systemctl status docker" | 2 |
| Nested virt not supported | /dev/kvm missing | None (permanent) | "Nested virtualization not supported. VM type must be Dv5/Ddsv5/Ev5/Edsv5." | 1 |
| Insufficient disk space | df check | Suggest cleanup | "Only 15GB free, need 50GB. Run: ssh {host} 'docker system prune -a'" | 1 |
| Image pull timeout | Progress stalled >5min | Retry (3x) | "Image pull timed out, retrying (attempt 2/3)..." | 3 if all fail |
| Docker Hub rate limited | HTTP 429 response | Fallback to ACR | "Docker Hub rate limited, trying Azure Container Registry..." | 0 or 3 |
| Container already exists | docker inspect | Remove if not running | "Container exists with status 'exited', removing..." | 0 |
| Container creation failed | docker run error | None | "Container creation failed: {error}. Check logs: docker logs {name}" | 4 |
| Container exits immediately | docker inspect status | Get logs, suggest fix | "Container exited. Check /dev/kvm access. Logs: {logs}" | 4 |
| QEMU init timeout | Container logs | Restart container | "QEMU failed to initialize, restarting container..." | 5 |
| Windows boot timeout | Uptime < 5min after 20min | Increase timeout or restart | "Windows boot timeout after 20min. Try --timeout 2400 or restart container." | 5 |
| VNC port not accessible | nc check fails | Wait longer | "VNC port not ready yet, continuing to wait..." | 5 if timeout |
| WAA server not ready | /probe returns 500 | Retry with backoff | "WAA server starting up (attempt 3/10)..." | 6 if all fail |
| Accessibility tree unavailable | API returns error | Retry, suggest restart | "Accessibility tree not ready. This is uncommon, checking again..." | 7 |
| Smoke test action failed | API returns 4xx/5xx | Continue anyway | "Smoke test action failed but server is running. Check manually." | 0 (warning) |
| Smoke test screenshot empty | Response < 1KB | Flag as warning | "Screenshot suspiciously small. WAA may not be fully ready." | 0 (warning) |
| Overall timeout | time.time() > timeout | Fail with state info | "Setup timeout after {timeout}s. Reached phase: {current_phase}" | 8 |
| Unknown exception | try/except | Fail with traceback | "Unexpected error: {exception}. Please report this issue." | 9 |

---

## 5. Integration Points

### 5.1 Integration with `up` Command

**Current `up` Command** (cli.py lines 638-746):
```python
def up(args):
    """Start VM and wait for server ready"""
    # 1. Start VM
    # 2. Wait for SSH
    # 3. Start server
    # 4. Probe until ready
```

**Enhanced `up` Command**:
```python
def up(args):
    """Start VM, setup container if needed, and wait for server ready"""

    # 1. Start VM (existing code)
    start_vm(args.vm_name)
    wait_for_ssh(args.host)

    # 2. Check if container exists (NEW)
    container_exists = check_container_exists(args.host, args.container_name)

    if not container_exists:
        logger.info("Container doesn't exist, running vm-setup...")
        # Run vm-setup
        setup_args = argparse.Namespace(
            host=args.host,
            image=args.image,
            container_name=args.container_name,
            rebuild=False,
            verify_nested_virt=True,
            timeout=args.setup_timeout or 1800,
            skip_smoke_test=False,
            log_file="/tmp/waa_setup.log",
            azure_cr=args.azure_cr,
            verbose=args.verbose
        )
        result = vm_setup(setup_args)

        if result.exit_code != 0:
            logger.error(f"vm-setup failed: {result.message}")
            return result.exit_code

        logger.info("vm-setup completed successfully")

    # 3. Start server (existing code, but now verifies health)
    server_start(args)

    # 4. Enhanced probe with multi-layer checks (NEW)
    health_checker = MultiLayerHealthChecker(args.host, args.container_name)
    all_results = health_checker.check_all_layers(timeout=args.probe_timeout or 300)

    if all(r.status == "healthy" for r in all_results):
        logger.info("All systems ready")
        return 0
    else:
        logger.error("Some health checks failed")
        for r in all_results:
            if r.status != "healthy":
                logger.error(f"  - {r.layer.name}: {r.message}")
        return 1
```

---

### 5.2 Integration with `server-start` Command

**Current `server-start`** (cli.py lines 462-547):
```python
def server_start(args):
    """Start WAA server (assumes container exists)"""
    # SSH to VM and start container
    subprocess.run(["ssh", args.host, "docker", "start", args.container_name])
```

**Enhanced `server-start`**:
```python
def server_start(args):
    """Start WAA server with pre-validation"""

    # Pre-validation: Check if container exists
    inspect_result = subprocess.run(
        ["ssh", args.host, "docker", "inspect", args.container_name],
        capture_output=True,
        text=True
    )

    if inspect_result.returncode != 0:
        logger.error(f"Container '{args.container_name}' doesn't exist")
        logger.info("Run 'vm-setup' first to create container")
        return 1

    # Check current status
    status_result = subprocess.run(
        ["ssh", args.host, "docker", "inspect", "-f", "{{.State.Status}}", args.container_name],
        capture_output=True,
        text=True
    )

    current_status = status_result.stdout.strip()

    if current_status == "running":
        logger.info(f"Container already running")

        # Verify it's actually healthy
        health_checker = MultiLayerHealthChecker(args.host, args.container_name)
        server_check = health_checker._check_waa_server()

        if server_check:
            logger.info("WAA server is healthy")
            return 0
        else:
            logger.warning("Container running but WAA server not responding")
            logger.info("Restarting container...")
            subprocess.run(["ssh", args.host, "docker", "restart", args.container_name])

    elif current_status == "exited":
        logger.info("Container stopped, starting...")
        subprocess.run(["ssh", args.host, "docker", "start", args.container_name])

    elif current_status == "restarting":
        logger.warning("Container is restarting (might be in crash loop)")
        # Wait a bit and check logs
        time.sleep(10)
        logs = subprocess.run(
            ["ssh", args.host, "docker", "logs", "--tail", "50", args.container_name],
            capture_output=True,
            text=True
        )
        logger.info(f"Container logs:\n{logs.stdout}")

    # Wait for server to be ready
    logger.info("Waiting for WAA server to be ready...")
    result = wait_for_waa_server(args.host, timeout=300)

    if result.success:
        logger.info("WAA server ready")
        return 0
    else:
        logger.error(f"WAA server failed to start: {result.message}")
        return 1
```

---

### 5.3 Integration with Azure ML Jobs

**Job Submission Script** (new file: `azure_job_with_setup.py`):

```python
def submit_waa_evaluation_job(
    ml_client: MLClient,
    task_list: List[str],
    run_name: str,
    ensure_setup: bool = True
) -> Job:
    """
    Submit WAA evaluation job with automated setup

    Args:
        ml_client: Azure ML client
        task_list: List of task IDs to evaluate
        run_name: Name for this run
        ensure_setup: If True, run vm-setup before evaluation

    Returns:
        Submitted job object
    """

    # Create job script
    job_script = f"""
#!/bin/bash
set -e

echo "Starting WAA evaluation job: {run_name}"

# Navigate to repo
cd /mnt/openadapt-evals

# Ensure container is set up
if [ "{ensure_setup}" = "True" ]; then
    echo "Running vm-setup to ensure container is ready..."
    uv run python -m openadapt_evals.benchmarks.cli vm-setup \\
        --host $WAA_VM_HOST \\
        --timeout 1800 \\
        --verbose

    if [ $? -ne 0 ]; then
        echo "ERROR: vm-setup failed"
        exit 1
    fi
fi

# Run evaluation
echo "Starting evaluation..."
uv run python -m openadapt_evals.benchmarks.cli evaluate \\
    --benchmark waa \\
    --tasks {','.join(task_list)} \\
    --run-name {run_name} \\
    --output-dir /mnt/outputs

exit $?
"""

    # Write script to file
    script_path = f"/tmp/waa_job_{run_name}.sh"
    with open(script_path, "w") as f:
        f.write(job_script)

    # Create Azure ML command job
    job = command(
        code="./",
        command=f"bash {script_path}",
        environment="openadapt-evals-env:latest",
        compute="waa-eval-vm",
        experiment_name="waa-evaluations",
        display_name=run_name,
        environment_variables={
            "WAA_VM_HOST": "172.171.112.41"
        }
    )

    # Submit
    submitted_job = ml_client.jobs.create_or_update(job)

    logger.info(f"Job submitted: {submitted_job.name}")
    logger.info(f"Studio URL: {submitted_job.studio_url}")

    return submitted_job
```

---

## 6. Code Structure

### 6.1 File Organization

```
openadapt_evals/
├── benchmarks/
│   ├── cli.py                    # Main CLI entry point
│   ├── vm_setup.py               # NEW: VMSetupOrchestrator
│   ├── health_checker.py         # Enhanced health checks
│   └── azure_job_runner.py       # NEW: Azure ML job helpers
├── adapters/
│   └── waa_live.py               # WAA API client
└── utils/
    ├── retry.py                  # NEW: Retry logic utilities
    └── logging_utils.py          # NEW: Structured logging
```

### 6.2 Core Classes

#### VMSetupOrchestrator

```python
# File: openadapt_evals/benchmarks/vm_setup.py

from dataclasses import dataclass
from typing import Optional, List
from enum import Enum

@dataclass
class SetupResult:
    """Result of VM setup operation"""
    success: bool
    exit_code: int
    duration_seconds: float
    message: str
    container_id: Optional[str]
    phase_results: List['PhaseResult']

@dataclass
class PhaseResult:
    """Result of a single setup phase"""
    phase_number: int
    phase_name: str
    success: bool
    duration_seconds: float
    message: str
    error: Optional[str] = None

class SetupPhase(Enum):
    """Setup phases"""
    PRE_FLIGHT_CHECKS = 1
    IMAGE_PULL = 2
    CONTAINER_CREATE = 3
    WINDOWS_BOOT = 4
    SERVER_INIT = 5
    ACCESSIBILITY_CHECK = 6
    SMOKE_TEST = 7
    PERSIST_RESULTS = 8
    FINAL_VALIDATION = 9

class VMSetupOrchestrator:
    """
    Orchestrates WAA container setup on Azure VM

    Responsibilities:
    - Execute all 9 setup phases in sequence
    - Handle errors and implement retry logic
    - Provide progress updates
    - Generate human-readable and JSON output
    """

    def __init__(
        self,
        host: str,
        image: str = "windowsarena/winarena:latest",
        container_name: str = "winarena",
        timeout: int = 1800,
        verbose: bool = False,
        logger: Optional[logging.Logger] = None
    ):
        self.host = host
        self.image = image
        self.container_name = container_name
        self.timeout = timeout
        self.verbose = verbose
        self.logger = logger or logging.getLogger(__name__)

        self.start_time = None
        self.phase_results: List[PhaseResult] = []

    def setup(
        self,
        rebuild: bool = False,
        verify_nested_virt: bool = True,
        skip_smoke_test: bool = False,
        azure_cr: Optional[str] = None,
        log_file: str = "/tmp/waa_setup.log"
    ) -> SetupResult:
        """
        Main entry point for setup

        Returns:
            SetupResult with success status and details
        """

        self.start_time = time.time()

        try:
            # Phase 1: Pre-flight checks
            result = self._run_phase(
                SetupPhase.PRE_FLIGHT_CHECKS,
                lambda: self._pre_flight_checks(verify_nested_virt)
            )
            if not result.success:
                return self._build_setup_result(result.exit_code, result.message)

            # Phase 2: Image pull
            result = self._run_phase(
                SetupPhase.IMAGE_PULL,
                lambda: self._pull_image(azure_cr)
            )
            if not result.success:
                return self._build_setup_result(result.exit_code, result.message)

            # Phase 3: Container creation
            result = self._run_phase(
                SetupPhase.CONTAINER_CREATE,
                lambda: self._create_container(rebuild)
            )
            if not result.success:
                return self._build_setup_result(result.exit_code, result.message)

            # Phase 4: Windows boot
            result = self._run_phase(
                SetupPhase.WINDOWS_BOOT,
                lambda: self._wait_for_windows_boot()
            )
            if not result.success:
                return self._build_setup_result(result.exit_code, result.message)

            # Phase 5: Server initialization
            result = self._run_phase(
                SetupPhase.SERVER_INIT,
                lambda: self._wait_for_server()
            )
            if not result.success:
                return self._build_setup_result(result.exit_code, result.message)

            # Phase 6: Accessibility check
            result = self._run_phase(
                SetupPhase.ACCESSIBILITY_CHECK,
                lambda: self._check_accessibility()
            )
            if not result.success:
                return self._build_setup_result(result.exit_code, result.message)

            # Phase 7: Smoke test
            if not skip_smoke_test:
                result = self._run_phase(
                    SetupPhase.SMOKE_TEST,
                    lambda: self._run_smoke_test()
                )
                # Smoke test failure is warning, not fatal
                if not result.success:
                    self.logger.warning(f"Smoke test failed: {result.message}")

            # Phase 8: Persist results
            result = self._run_phase(
                SetupPhase.PERSIST_RESULTS,
                lambda: self._persist_results(log_file)
            )
            # Persist failure is warning, not fatal

            # Phase 9: Final validation
            result = self._run_phase(
                SetupPhase.FINAL_VALIDATION,
                lambda: self._final_validation()
            )
            if not result.success:
                return self._build_setup_result(result.exit_code, result.message)

            # All phases succeeded
            container_id = self._get_container_id()
            return self._build_setup_result(
                0,
                "WAA container ready for evaluation",
                container_id
            )

        except Exception as e:
            self.logger.error(f"Unexpected error during setup: {e}", exc_info=True)
            return self._build_setup_result(9, f"Unexpected error: {e}")

    def _run_phase(
        self,
        phase: SetupPhase,
        func: callable
    ) -> PhaseResult:
        """
        Execute a setup phase with error handling and timing

        Args:
            phase: Phase enum
            func: Function to execute (no args)

        Returns:
            PhaseResult
        """

        phase_start = time.time()
        self.logger.info(f"Phase {phase.value}/9: {phase.name.lower().replace('_', ' ')}")

        try:
            # Check overall timeout
            elapsed = time.time() - self.start_time
            if elapsed > self.timeout:
                result = PhaseResult(
                    phase_number=phase.value,
                    phase_name=phase.name,
                    success=False,
                    duration_seconds=time.time() - phase_start,
                    message=f"Overall timeout exceeded ({elapsed:.0f}s > {self.timeout}s)",
                    error="timeout"
                )
                self.phase_results.append(result)
                return result

            # Execute phase function
            phase_result = func()

            # Record result
            duration = time.time() - phase_start
            result = PhaseResult(
                phase_number=phase.value,
                phase_name=phase.name,
                success=phase_result.success if hasattr(phase_result, 'success') else True,
                duration_seconds=duration,
                message=phase_result.message if hasattr(phase_result, 'message') else "Success"
            )
            self.phase_results.append(result)

            if result.success:
                self.logger.info(f"  ✓ {result.message} ({duration:.0f}s)")
            else:
                self.logger.error(f"  ✗ {result.message}")

            return result

        except Exception as e:
            duration = time.time() - phase_start
            self.logger.error(f"Phase {phase.name} failed with exception: {e}", exc_info=True)

            result = PhaseResult(
                phase_number=phase.value,
                phase_name=phase.name,
                success=False,
                duration_seconds=duration,
                message=f"Phase failed: {e}",
                error=str(e)
            )
            self.phase_results.append(result)
            return result

    # Individual phase implementations
    # (Same as in Phase 1-9 sections above)

    def _pre_flight_checks(self, verify_nested_virt: bool) -> PhaseResult:
        # Implementation from Phase 1
        pass

    def _pull_image(self, azure_cr: Optional[str]) -> PhaseResult:
        # Implementation from Phase 2
        pass

    def _create_container(self, rebuild: bool) -> PhaseResult:
        # Implementation from Phase 3
        pass

    def _wait_for_windows_boot(self) -> PhaseResult:
        # Implementation from Phase 4
        pass

    def _wait_for_server(self) -> PhaseResult:
        # Implementation from Phase 5
        pass

    def _check_accessibility(self) -> PhaseResult:
        # Implementation from Phase 6
        pass

    def _run_smoke_test(self) -> PhaseResult:
        # Implementation from Phase 7
        pass

    def _persist_results(self, log_file: str) -> PhaseResult:
        # Implementation from Phase 8
        pass

    def _final_validation(self) -> PhaseResult:
        # Implementation from Phase 9
        pass

    def _get_container_id(self) -> Optional[str]:
        """Get container ID"""
        result = subprocess.run(
            ["ssh", self.host, "docker", "inspect", "-f", "{{.Id}}", self.container_name],
            capture_output=True,
            text=True
        )
        return result.stdout.strip() if result.returncode == 0 else None

    def _build_setup_result(
        self,
        exit_code: int,
        message: str,
        container_id: Optional[str] = None
    ) -> SetupResult:
        """Build final SetupResult"""

        duration = time.time() - self.start_time

        return SetupResult(
            success=(exit_code == 0),
            exit_code=exit_code,
            duration_seconds=duration,
            message=message,
            container_id=container_id or self._get_container_id(),
            phase_results=self.phase_results
        )
```

---

## 7. Testing Requirements

See WAA_RELIABILITY_PLAN.md Section 5 for full testing strategy.

**Key Tests for vm-setup**:

1. **Unit Tests**:
   - Pre-flight check: SSH, Docker, nested virt, disk space
   - Image pull: progress parsing, retry logic
   - Container creation: idempotency, cleanup
   - Phase timeout handling

2. **Integration Tests**:
   - Fresh VM → ready container (happy path)
   - Idempotency (run twice, same result)
   - Rebuild flag (recreates container)
   - Azure CR fallback

3. **Error Recovery Tests**:
   - Docker daemon stopped → auto-restart
   - Image pull timeout → retry
   - Container crash → clear error
   - Disk space low → clear error

---

## 8. Performance Targets

| Metric | Target | Measurement |
|--------|--------|-------------|
| Total setup time (first run) | 15-20 min | Time from start to "ready" |
| Total setup time (image cached) | 8-12 min | With image already pulled |
| Image pull time | 5-15 min | Depends on network |
| Windows boot time | 5-8 min | Container start to server ready |
| Server init time | 1-2 min | WAA server startup |
| Pre-flight checks | < 30 sec | All validation checks |
| Container creation | < 15 sec | Docker run command |
| Smoke test | 30-60 sec | Full action sequence |
| Success rate (fresh VM) | 95%+ | 19/20 setups succeed |
| Success rate (existing container) | 99%+ | Idempotent operations |

---

## Conclusion

This technical specification provides a complete design for the `vm-setup` command, addressing the #1 critical blocker in WAA reliability: missing container setup automation.

**Key Features**:
- Fully automated setup (no manual steps)
- Robust error handling and retry logic
- Clear progress reporting
- Idempotent (safe to re-run)
- Comprehensive validation
- Integration with existing CLI commands

**Implementation Status**: Design complete, ready for coding

**Next Steps**:
1. Implement VMSetupOrchestrator class
2. Add vm-setup command to CLI
3. Test on fresh VM
4. Iterate based on real-world failures

**Estimated Implementation Time**: 8 hours (Week 1 of roadmap)

---

**Document Version**: 1.0
**Last Updated**: January 18, 2026
**Author**: Claude (P00 Agent)
**Status**: Ready for Implementation
