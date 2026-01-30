"""Azure deployment automation for WAA benchmark.

This module provides Azure VM orchestration for running Windows Agent Arena
at scale across multiple parallel VMs.

Requirements:
    - azure-ai-ml
    - azure-identity
    - Azure subscription with ML workspace

Example:
    from openadapt_evals.benchmarks.azure import AzureWAAOrchestrator, AzureConfig

    config = AzureConfig(
        subscription_id="your-subscription-id",
        resource_group="agents",
        workspace_name="agents_ml",
    )
    orchestrator = AzureWAAOrchestrator(config, waa_repo_path="/path/to/WAA")

    # Run evaluation on 40 parallel VMs
    results = orchestrator.run_evaluation(
        agent=my_agent,
        num_workers=40,
        task_ids=None,  # All tasks
    )
"""

from __future__ import annotations

import json
import logging
import os
import re
import signal
import subprocess
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)

from openadapt_evals.agents import BenchmarkAgent
from openadapt_evals.adapters import BenchmarkResult, BenchmarkTask

logger = logging.getLogger(__name__)


# VM Tier Configuration for Cost Optimization
VM_TIERS = {
    "simple": "Standard_D2_v3",   # 2 vCPUs, 8 GB RAM - Notepad, File Explorer, basic apps
    "medium": "Standard_D4_v3",   # 4 vCPUs, 16 GB RAM - Chrome, Office, email
    "complex": "Standard_D8_v3",  # 8 vCPUs, 32 GB RAM - Coding, multi-app workflows
}

# Hourly costs for VM tiers (East US pricing, regular instances)
VM_TIER_COSTS = {
    "simple": 0.096,   # $0.096/hour
    "medium": 0.192,   # $0.192/hour
    "complex": 0.384,  # $0.384/hour
}

# Spot instance hourly costs (approximately 70-80% discount)
VM_TIER_SPOT_COSTS = {
    "simple": 0.024,   # ~$0.024/hour (75% discount)
    "medium": 0.048,   # ~$0.048/hour (75% discount)
    "complex": 0.096,  # ~$0.096/hour (75% discount)
}


def classify_task_complexity(task: BenchmarkTask) -> str:
    """Classify task complexity to select appropriate VM tier.

    Classification priority: complex > medium > simple > default(medium)

    Args:
        task: The benchmark task to classify.

    Returns:
        VM tier name: "simple", "medium", or "complex"
    """
    task_id = task.task_id.lower()
    instruction = task.instruction.lower()
    domain = (task.domain or "").lower()

    # Complex tasks: Coding, debugging, multi-app workflows, data analysis
    complex_indicators = [
        "code", "debug", "compile", "ide", "visual studio",
        "git", "terminal", "powershell", "cmd",
        "excel formula", "pivot table", "macro",
        "multiple applications", "switch between",
        "data analysis", "chart", "graph",
        "multitasking",
    ]

    # Medium tasks: Browser, Office apps, email
    medium_indicators = [
        "browser", "chrome", "edge", "firefox",
        "word", "excel", "powerpoint", "office",
        "email", "outlook", "calendar",
        "pdf", "acrobat",
    ]

    # Simple tasks: Notepad, File Explorer, basic Windows operations
    # Note: Check these AFTER medium to avoid "open" matching browser tasks
    simple_indicators = [
        "notepad", "file explorer", "file_explorer", "calculator", "paint",
    ]

    # Simple domains take precedence for direct domain matching
    simple_domains = {"notepad", "calculator", "paint", "file_explorer"}

    # Check for complex indicators first
    for indicator in complex_indicators:
        if indicator in task_id or indicator in instruction or indicator in domain:
            return "complex"

    # Check for medium indicators (browsers, office apps are more complex than notepad)
    for indicator in medium_indicators:
        if indicator in task_id or indicator in instruction or indicator in domain:
            return "medium"

    # Check for simple domains (direct match)
    if domain in simple_domains:
        return "simple"

    # Check for simple indicators in task_id or instruction
    for indicator in simple_indicators:
        if indicator in task_id or indicator in instruction:
            return "simple"

    # Default to medium for unknown tasks
    return "medium"


@dataclass
class AzureJobLogParser:
    """Parses Azure ML job logs to extract task progress.

    Looks for patterns like:
    - "Task 1/10: {task_id}"
    - "Step {step_idx}: {action_type}"
    - "Task {task_id}: SUCCESS/FAIL"
    - Error messages
    """

    # Regex patterns for log parsing
    TASK_START_PATTERN = re.compile(r"Task (\d+)/(\d+):\s+(\S+)")
    STEP_PATTERN = re.compile(r"Step (\d+):\s+(\w+)")
    TASK_RESULT_PATTERN = re.compile(r"Task (\S+):\s+(SUCCESS|FAIL)")
    ERROR_PATTERN = re.compile(r"ERROR|Error|error|Exception|Traceback")

    def __init__(self):
        self.current_task: str | None = None
        self.current_task_idx: int = 0
        self.total_tasks: int = 0
        self.current_step: int = 0
        self.errors: list[str] = []

    def parse_line(self, line: str) -> dict[str, Any] | None:
        """Parse a log line and return extracted information.

        Args:
            line: Log line to parse.

        Returns:
            Dict with parsed data or None if no match.
        """
        # Check for task start
        match = self.TASK_START_PATTERN.search(line)
        if match:
            self.current_task_idx = int(match.group(1))
            self.total_tasks = int(match.group(2))
            self.current_task = match.group(3)
            self.current_step = 0
            return {
                "type": "task_start",
                "task_idx": self.current_task_idx,
                "total_tasks": self.total_tasks,
                "task_id": self.current_task,
            }

        # Check for step
        match = self.STEP_PATTERN.search(line)
        if match:
            self.current_step = int(match.group(1))
            action_type = match.group(2)
            return {
                "type": "step",
                "step_idx": self.current_step,
                "action_type": action_type,
                "task_id": self.current_task,
            }

        # Check for task result
        match = self.TASK_RESULT_PATTERN.search(line)
        if match:
            task_id = match.group(1)
            result = match.group(2)
            return {
                "type": "task_result",
                "task_id": task_id,
                "success": result == "SUCCESS",
            }

        # Check for errors
        if self.ERROR_PATTERN.search(line):
            self.errors.append(line)
            return {
                "type": "error",
                "message": line,
            }

        return None


@dataclass
class AzureConfig:
    """Azure configuration for WAA deployment.

    Attributes:
        subscription_id: Azure subscription ID.
        resource_group: Resource group containing ML workspace.
        workspace_name: Azure ML workspace name.
        vm_size: VM size for compute instances (must support nested virtualization).
        vm_security_type: VM security type (Standard or TrustedLaunch). Use Standard for nested virt.
        enable_nested_virtualization: Whether to enable nested virtualization (default: True).
        idle_timeout_minutes: Auto-shutdown after idle (minutes).
        docker_image: Docker image for agent container.
        storage_account: Storage account for results (auto-detected if None).
        use_managed_identity: Whether to use managed identity for auth.
        managed_identity_name: Name of managed identity (if using).
        enable_tiered_vms: Whether to auto-select VM size based on task complexity (default: False).
        use_spot_instances: Whether to use spot instances for cost savings (default: False).
        max_spot_price: Maximum hourly price for spot instances (default: 0.5).
        spot_eviction_policy: What to do when spot instance is evicted (Deallocate or Delete).
        environment: Deployment environment (production or development).
        enable_ssh: Whether to enable SSH access for VNC debugging (default: True).
        ssh_public_key_path: Path to SSH public key file (default: ~/.ssh/id_rsa.pub).
    """

    subscription_id: str
    resource_group: str
    workspace_name: str
    vm_size: str = "Standard_D4ds_v5"  # D4ds_v5 supported by Azure ML compute
    vm_security_type: str = "Standard"  # NOT TrustedLaunch (disables nested virt)
    enable_nested_virtualization: bool = True
    idle_timeout_minutes: int = 60
    # Custom WAA image with unattended installation support
    # Use public.ecr.aws image (not vanilla windowsarena/winarena) because:
    # - Modern dockurr/windows base (auto-downloads Windows 11)
    # - FirstLogonCommands patches for unattended installation
    # - Python 3.9 with transformers 4.46.2 (compatible with navi agent)
    # Build with: uv run python -m openadapt_evals.benchmarks.cli waa-image build-push
    docker_image: str = "public.ecr.aws/g3w3k7s5/waa-auto:latest"
    storage_account: str | None = None
    use_managed_identity: bool = False
    managed_identity_name: str | None = None
    # Cost optimization features
    enable_tiered_vms: bool = False  # Auto-select VM size based on task complexity
    use_spot_instances: bool = False  # Use spot instances for 70-80% cost savings
    max_spot_price: float = 0.5  # Maximum hourly price for spot instances
    spot_eviction_policy: str = "Deallocate"  # Deallocate or Delete
    environment: str = "production"  # production or development
    # SSH/VNC access for debugging parallel workers
    enable_ssh: bool = True  # Enable SSH for VNC access to workers
    ssh_public_key_path: str = "~/.ssh/id_rsa.pub"  # Path to SSH public key

    @classmethod
    def from_env(cls) -> AzureConfig:
        """Create config from environment variables.

        Required env vars:
            AZURE_SUBSCRIPTION_ID
            AZURE_ML_RESOURCE_GROUP
            AZURE_ML_WORKSPACE_NAME

        Optional env vars:
            AZURE_VM_SIZE (default: Standard_D4ds_v5)
            AZURE_VM_SECURITY_TYPE (default: Standard)
            AZURE_DOCKER_IMAGE (default: public.ecr.aws/g3w3k7s5/waa-auto:latest)
            AZURE_ENABLE_TIERED_VMS (default: false) - Auto-select VM size by task complexity
            AZURE_USE_SPOT_INSTANCES (default: false) - Use spot instances for cost savings
            AZURE_MAX_SPOT_PRICE (default: 0.5) - Maximum hourly price for spot instances
            AZURE_ENVIRONMENT (default: production) - Set to 'development' to enable spot by default

        Authentication (one of):
            - AZURE_CLIENT_ID, AZURE_CLIENT_SECRET, AZURE_TENANT_ID (service principal)
            - Azure CLI login (`az login`)
            - Managed Identity (when running on Azure)

        Raises:
            ValueError: If required settings are not configured.
        """
        subscription_id = os.getenv("AZURE_SUBSCRIPTION_ID")
        resource_group = os.getenv("AZURE_ML_RESOURCE_GROUP")
        workspace_name = os.getenv("AZURE_ML_WORKSPACE_NAME")

        # Validate required settings
        if not subscription_id:
            raise ValueError(
                "AZURE_SUBSCRIPTION_ID not set. "
                "Set it in environment or .env file."
            )
        if not resource_group:
            raise ValueError(
                "AZURE_ML_RESOURCE_GROUP not set. "
                "Set it in environment or .env file."
            )
        if not workspace_name:
            raise ValueError(
                "AZURE_ML_WORKSPACE_NAME not set. "
                "Set it in environment or .env file."
            )

        # Cost optimization settings
        environment = os.getenv("AZURE_ENVIRONMENT", "production")
        enable_tiered_vms = os.getenv("AZURE_ENABLE_TIERED_VMS", "false").lower() == "true"
        use_spot_instances = os.getenv("AZURE_USE_SPOT_INSTANCES",
                                       "true" if environment == "development" else "false").lower() == "true"

        return cls(
            subscription_id=subscription_id,
            resource_group=resource_group,
            workspace_name=workspace_name,
            vm_size=os.getenv("AZURE_VM_SIZE", "Standard_D4ds_v5"),
            vm_security_type=os.getenv("AZURE_VM_SECURITY_TYPE", "Standard"),
            docker_image=os.getenv(
                "AZURE_DOCKER_IMAGE",
                "public.ecr.aws/g3w3k7s5/waa-auto:latest"
            ),
            enable_tiered_vms=enable_tiered_vms,
            use_spot_instances=use_spot_instances,
            max_spot_price=float(os.getenv("AZURE_MAX_SPOT_PRICE", "0.5")),
            environment=environment,
        )

    @classmethod
    def from_json(cls, path: str | Path) -> AzureConfig:
        """Load config from JSON file."""
        with open(path) as f:
            data = json.load(f)
        return cls(**data)

    def to_json(self, path: str | Path) -> None:
        """Save config to JSON file."""
        with open(path, "w") as f:
            json.dump(self.__dict__, f, indent=2)


@dataclass
class WorkerState:
    """State of a single worker VM."""

    worker_id: int
    compute_name: str
    status: str = "pending"  # pending, running, completed, failed
    assigned_tasks: list[str] = field(default_factory=list)
    completed_tasks: list[str] = field(default_factory=list)
    results: list[BenchmarkResult] = field(default_factory=list)
    error: str | None = None
    start_time: float | None = None
    end_time: float | None = None
    job_name: str | None = None  # Azure ML job name for this worker
    # Cost tracking
    vm_tier: str = "medium"  # simple, medium, or complex
    vm_size: str = "Standard_D4ds_v5"  # Actual VM size used
    is_spot: bool = False  # Whether spot instance was used
    hourly_cost: float = 0.192  # Actual hourly cost
    total_cost: float = 0.0  # Total cost for this worker


@dataclass
class EvaluationRun:
    """State of an evaluation run across multiple workers."""

    run_id: str
    experiment_name: str
    num_workers: int
    total_tasks: int
    workers: list[WorkerState] = field(default_factory=list)
    status: str = "pending"  # pending, running, completed, failed
    start_time: float | None = None
    end_time: float | None = None
    total_cost: float = 0.0  # Total cost for entire evaluation

    def to_dict(self) -> dict:
        """Serialize to dict for JSON storage."""
        # Calculate total cost
        total_cost = sum(w.total_cost for w in self.workers)

        return {
            "run_id": self.run_id,
            "experiment_name": self.experiment_name,
            "num_workers": self.num_workers,
            "total_tasks": self.total_tasks,
            "status": self.status,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "total_cost": total_cost,
            "cost_per_task": total_cost / self.total_tasks if self.total_tasks > 0 else 0,
            "workers": [
                {
                    "worker_id": w.worker_id,
                    "compute_name": w.compute_name,
                    "status": w.status,
                    "assigned_tasks": w.assigned_tasks,
                    "completed_tasks": w.completed_tasks,
                    "error": w.error,
                    "vm_tier": w.vm_tier,
                    "vm_size": w.vm_size,
                    "is_spot": w.is_spot,
                    "hourly_cost": w.hourly_cost,
                    "total_cost": w.total_cost,
                }
                for w in self.workers
            ],
        }


class AzureMLClient:
    """Wrapper around Azure ML SDK for compute management.

    This provides a simplified interface for creating and managing
    Azure ML compute instances for WAA evaluation.
    """

    def __init__(self, config: AzureConfig):
        self.config = config
        self._client = None
        self._ensure_sdk_available()

    def _ensure_sdk_available(self) -> None:
        """Check that Azure SDK is available."""
        try:
            from azure.ai.ml import MLClient
            from azure.identity import (
                ClientSecretCredential,
                DefaultAzureCredential,
            )

            self._MLClient = MLClient
            self._DefaultAzureCredential = DefaultAzureCredential
            self._ClientSecretCredential = ClientSecretCredential
        except ImportError as e:
            raise ImportError(
                "Azure ML SDK not installed. Install with: "
                "pip install azure-ai-ml azure-identity"
            ) from e

    @property
    def client(self):
        """Lazy-load ML client.

        Uses service principal credentials if configured in env,
        otherwise falls back to DefaultAzureCredential (CLI login, managed identity, etc.)
        """
        if self._client is None:
            credential = self._get_credential()
            self._client = self._MLClient(
                credential=credential,
                subscription_id=self.config.subscription_id,
                resource_group_name=self.config.resource_group,
                workspace_name=self.config.workspace_name,
            )
            logger.info(f"Connected to Azure ML workspace: {self.config.workspace_name}")
        return self._client

    def _get_credential(self):
        """Get Azure credential, preferring service principal if configured."""
        client_id = os.getenv("AZURE_CLIENT_ID")
        client_secret = os.getenv("AZURE_CLIENT_SECRET")
        tenant_id = os.getenv("AZURE_TENANT_ID")

        # Use service principal if credentials are configured
        if all([client_id, client_secret, tenant_id]):
            logger.info("Using service principal authentication")
            return self._ClientSecretCredential(
                tenant_id=tenant_id,
                client_id=client_id,
                client_secret=client_secret,
            )

        # Fall back to DefaultAzureCredential (CLI login, managed identity, etc.)
        logger.info(
            "Using DefaultAzureCredential (ensure you're logged in with 'az login' "
            "or have service principal credentials in env)"
        )
        return self._DefaultAzureCredential()

    def create_compute_instance(
        self,
        name: str,
        startup_script_path: str | None = None,
        vm_size: str | None = None,
        use_spot: bool | None = None,
    ) -> str:
        """Create a compute instance with startup script.

        Args:
            name: Compute instance name.
            startup_script_path: Path to startup script in datastore (e.g., 'Users/me/startup.sh').
            vm_size: Override VM size (uses config.vm_size if None).
            use_spot: Override spot instance setting (uses config.use_spot_instances if None).

        Returns:
            Compute instance name.
        """
        from azure.ai.ml.entities import ComputeInstance, ScriptReference, SetupScripts

        # Check if already exists
        try:
            existing = self.client.compute.get(name)
            if existing:
                logger.info(f"Compute instance {name} already exists")
                return name
        except Exception:
            pass  # Doesn't exist, create it

        # Determine VM size and spot settings
        vm_size = vm_size or self.config.vm_size
        use_spot = use_spot if use_spot is not None else self.config.use_spot_instances

        # CRITICAL: Use Standard security type for nested virtualization
        # TrustedLaunch (Azure default since 2024) disables nested virtualization

        # Configure SSH settings for VNC access
        ssh_settings = None
        if self.config.enable_ssh:
            from azure.ai.ml.entities import ComputeInstanceSshSettings

            # Read SSH public key
            ssh_key_path = os.path.expanduser(self.config.ssh_public_key_path)
            if os.path.exists(ssh_key_path):
                with open(ssh_key_path) as f:
                    ssh_public_key = f.read().strip()
                ssh_settings = ComputeInstanceSshSettings(
                    ssh_public_access="Enabled",
                    admin_public_key=ssh_public_key,
                )
                logger.info(f"SSH enabled for {name} (key: {ssh_key_path})")
            else:
                logger.warning(
                    f"SSH key not found at {ssh_key_path}. "
                    f"SSH access disabled for {name}. "
                    f"Generate with: ssh-keygen -t rsa -b 4096"
                )

        # Configure startup script to stop conflicting services
        setup_scripts = None
        if startup_script_path:
            startup_script_ref = ScriptReference(
                path=startup_script_path,
                timeout_minutes=10,
            )
            setup_scripts = SetupScripts(startup_script=startup_script_ref)
            logger.info(f"Startup script configured: {startup_script_path}")

        compute = ComputeInstance(
            name=name,
            size=vm_size,
            idle_time_before_shutdown_minutes=self.config.idle_timeout_minutes,
            ssh_settings=ssh_settings,
            setup_scripts=setup_scripts,
        )

        # Configure spot instance if enabled
        if use_spot:
            # Note: Azure ML Compute Instances don't directly support spot instances
            # in the same way as VMs. For now, we log this and use regular instances.
            # Full spot support would require using Azure ML Compute Clusters instead.
            logger.warning(
                f"Spot instances requested but not supported for ComputeInstance. "
                f"Using regular instance for {name}. "
                f"Consider using Azure ML Compute Clusters for spot instance support."
            )
            # Future enhancement: Switch to AmlCompute cluster with low priority nodes
            # from azure.ai.ml.entities import AmlCompute
            # compute = AmlCompute(
            #     name=name,
            #     size=vm_size,
            #     min_instances=0,
            #     max_instances=1,
            #     tier="LowPriority",  # Spot instance equivalent
            # )

        # Note: VM security type configuration may vary by Azure ML SDK version
        # The vm_security_type parameter controls whether nested virtualization is enabled
        # For Azure ML SDK v2, this is typically set through additional_properties or
        # by ensuring we use Standard tier VMs (not TrustedLaunch)
        # The config.vm_security_type and config.enable_nested_virtualization are
        # available for future SDK updates or custom deployment templates

        # Add managed identity if configured
        if self.config.use_managed_identity and self.config.managed_identity_name:
            identity_id = (
                f"/subscriptions/{self.config.subscription_id}"
                f"/resourceGroups/{self.config.resource_group}"
                f"/providers/Microsoft.ManagedIdentity"
                f"/userAssignedIdentities/{self.config.managed_identity_name}"
            )
            compute.identity = {"type": "UserAssigned", "user_assigned_identities": [identity_id]}

        spot_indicator = " (spot)" if use_spot else ""
        print(f"      Creating VM: {name} ({vm_size}{spot_indicator})...", end="", flush=True)
        self.client.compute.begin_create_or_update(compute).result()
        print(" done")

        return name

    def delete_compute_instance(self, name: str) -> None:
        """Delete a compute instance.

        Args:
            name: Compute instance name.
        """
        try:
            logger.info(f"Deleting compute instance: {name}")
            self.client.compute.begin_delete(name).result()
            logger.info(f"Compute instance {name} deleted")
        except Exception as e:
            logger.warning(f"Failed to delete compute instance {name}: {e}")

    def list_compute_instances(self, prefix: str | None = None) -> list[dict]:
        """List compute instances.

        Args:
            prefix: Optional name prefix filter.

        Returns:
            List of dicts with compute instance info (name, state, created_on).
        """
        computes = self.client.compute.list()
        instances = []
        for c in computes:
            if c.type == "ComputeInstance":
                if prefix is None or c.name.startswith(prefix):
                    instances.append({
                        "name": c.name,
                        "state": c.state,
                        "created_on": c.created_on if hasattr(c, "created_on") else None,
                    })
        return instances

    def get_compute_status(self, name: str) -> str:
        """Get compute instance status.

        Args:
            name: Compute instance name.

        Returns:
            Status string (Running, Stopped, etc.)
        """
        compute = self.client.compute.get(name)
        return compute.state

    def get_compute_ssh_info(self, name: str) -> dict[str, Any] | None:
        """Get SSH connection info for a compute instance.

        Args:
            name: Compute instance name.

        Returns:
            Dict with ssh_host, ssh_port, ssh_user, or None if SSH not available.
            Example: {"ssh_host": "10.0.0.4", "ssh_port": 50000, "ssh_user": "azureuser"}
        """
        try:
            compute = self.client.compute.get(name)

            # Check if SSH settings exist
            if not hasattr(compute, "ssh_settings") or compute.ssh_settings is None:
                logger.warning(f"SSH not enabled for compute instance {name}")
                return None

            # Get SSH connection details from compute properties
            # Azure ML provides these in the connectivity_endpoints or ssh_settings
            ssh_info = {
                "ssh_user": "azureuser",  # Azure ML always uses azureuser
                "ssh_host": None,
                "ssh_port": 50000,  # Default SSH port for Azure ML compute
            }

            # Try to get IP from various possible locations
            if hasattr(compute, "public_ip_address") and compute.public_ip_address:
                ssh_info["ssh_host"] = compute.public_ip_address
            elif hasattr(compute, "connectivity_endpoints"):
                endpoints = compute.connectivity_endpoints
                if endpoints and hasattr(endpoints, "public_ip_address"):
                    ssh_info["ssh_host"] = endpoints.public_ip_address
                if endpoints and hasattr(endpoints, "ssh_port"):
                    ssh_info["ssh_port"] = endpoints.ssh_port

            # Alternative: Check properties dict
            if ssh_info["ssh_host"] is None and hasattr(compute, "properties"):
                props = compute.properties
                if isinstance(props, dict):
                    if "connectivityEndpoints" in props:
                        ep = props["connectivityEndpoints"]
                        ssh_info["ssh_host"] = ep.get("publicIpAddress")
                        ssh_info["ssh_port"] = ep.get("sshPort", 50000)

            if ssh_info["ssh_host"] is None:
                logger.warning(f"Could not determine SSH host for {name}")
                return None

            return ssh_info

        except Exception as e:
            logger.warning(f"Failed to get SSH info for {name}: {e}")
            return None

    def get_all_workers_ssh_info(self, worker_names: list[str]) -> dict[str, dict]:
        """Get SSH info for all workers.

        Args:
            worker_names: List of compute instance names.

        Returns:
            Dict mapping worker name to SSH info.
        """
        ssh_info = {}
        for name in worker_names:
            info = self.get_compute_ssh_info(name)
            if info:
                ssh_info[name] = info
        return ssh_info

    def submit_job(
        self,
        compute_name: str,
        command: str,
        environment_variables: dict[str, str] | None = None,
        display_name: str | None = None,
        timeout_hours: float = 4.0,
    ) -> str:
        """Submit a job to a compute instance using SDK V1 with Docker.

        This uses the Azure ML SDK V1 approach with DockerConfiguration,
        which is required to run WAA because:
        1. Docker runs the job INSIDE the container (not just using it as env)
        2. NET_ADMIN capability is needed for QEMU networking
        3. entry_setup.sh is called to start Windows VM

        Args:
            compute_name: Target compute instance.
            command: Command to run (passed to entry script).
            environment_variables: Environment variables.
            display_name: Job display name.
            timeout_hours: Maximum job duration in hours (default: 4).

        Returns:
            Job run ID.
        """
        # Use SDK V1 for DockerConfiguration support
        from azureml.core import Workspace, Experiment, Environment
        from azureml.core.runconfig import RunConfiguration, DockerConfiguration
        from azureml.core.compute import ComputeTarget
        from azureml.core import ScriptRunConfig

        # Connect to workspace using V1 SDK
        ws = Workspace(
            subscription_id=self.config.subscription_id,
            resource_group=self.config.resource_group,
            workspace_name=self.config.workspace_name,
        )

        # Create environment from Docker image
        env = Environment.from_docker_image(
            name=f"waa-env-{int(time.time())}",
            image=self.config.docker_image,
        )

        # Configure Docker with NET_ADMIN capability (required for QEMU networking)
        docker_config = DockerConfiguration(
            use_docker=True,
            shared_volumes=True,
            arguments=["--cap-add", "NET_ADMIN"],
            shm_size="16g",  # Shared memory for QEMU
        )

        # Set up run configuration
        run_config = RunConfiguration()
        run_config.target = ComputeTarget(workspace=ws, name=compute_name)
        run_config.environment = env
        run_config.docker = docker_config
        run_config.environment_variables = environment_variables or {}

        # Get the azure_files directory (contains run_entry.py)
        azure_files_dir = Path(__file__).parent / "azure_files"

        # Parse command to extract arguments for run_entry.py
        # Command format: "cd /client && python run.py --agent_name X --model Y ..."
        # We need to convert this to arguments for run_entry.py
        import shlex
        args = self._parse_command_to_args(command)

        # Create script run config
        src = ScriptRunConfig(
            source_directory=str(azure_files_dir),
            script="run_entry.py",
            arguments=args,
            run_config=run_config,
        )

        # Submit to experiment
        exp_name = display_name or f"waa-{compute_name}"
        experiment = Experiment(workspace=ws, name=exp_name)
        run = experiment.submit(config=src)

        logger.info(f"Job submitted: {run.id} (portal: {run.get_portal_url()})")
        return run.id

    def _parse_command_to_args(self, command: str) -> list[str]:
        """Parse the WAA command into arguments for run_entry.py.

        Args:
            command: WAA command string like:
                "cd /client && python run.py --agent_name navi --model gpt-4o ..."

        Returns:
            List of arguments for run_entry.py:
                [output_path, exp_name, num_workers, worker_id, agent, model, max_steps]
        """
        # Default values
        output_path = "/outputs"
        exp_name = "waa_eval"
        num_workers = "1"
        worker_id = "0"
        agent = "navi"
        model = "gpt-4o"
        max_steps = "15"

        # Parse command to extract values
        if "--worker_id" in command:
            match = re.search(r"--worker_id\s+(\d+)", command)
            if match:
                worker_id = match.group(1)

        if "--num_workers" in command:
            match = re.search(r"--num_workers\s+(\d+)", command)
            if match:
                num_workers = match.group(1)

        if "--agent_name" in command:
            match = re.search(r"--agent_name\s+(\w+)", command)
            if match:
                agent = match.group(1)

        if "--model" in command:
            match = re.search(r"--model\s+([\w\-\.]+)", command)
            if match:
                model = match.group(1)

        if "--max_steps" in command:
            match = re.search(r"--max_steps\s+(\d+)", command)
            if match:
                max_steps = match.group(1)

        if "--result_dir" in command:
            match = re.search(r"--result_dir\s+(\S+)", command)
            if match:
                output_path = match.group(1)

        return [output_path, exp_name, num_workers, worker_id, agent, model, max_steps]

    def wait_for_job(self, job_name: str, timeout_seconds: int = 3600) -> dict:
        """Wait for a job to complete.

        Args:
            job_name: Job name/ID.
            timeout_seconds: Maximum wait time.

        Returns:
            Job result dict.
        """
        start_time = time.time()
        while time.time() - start_time < timeout_seconds:
            job = self.client.jobs.get(job_name)
            if job.status in ["Completed", "Failed", "Canceled"]:
                return {
                    "status": job.status,
                    "outputs": job.outputs if hasattr(job, "outputs") else {},
                }
            time.sleep(10)

        raise TimeoutError(f"Job {job_name} did not complete within {timeout_seconds}s")

    def get_job_logs(self, job_name: str, tail: int | None = None) -> str:
        """Fetch logs for a job (non-streaming).

        Args:
            job_name: Job name/ID.
            tail: If specified, return only the last N lines.

        Returns:
            Log content as string.
        """
        try:
            # Use az ml job download to get logs
            import tempfile
            with tempfile.TemporaryDirectory() as temp_dir:
                result = subprocess.run(
                    [
                        "az",
                        "ml",
                        "job",
                        "download",
                        "--name",
                        job_name,
                        "--workspace-name",
                        self.config.workspace_name,
                        "--resource-group",
                        self.config.resource_group,
                        "--download-path",
                        temp_dir,
                        "--outputs",
                        "logs",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=60,
                )

                if result.returncode != 0:
                    logger.warning(f"Failed to download logs: {result.stderr}")
                    return ""

                # Find and read the user_logs/std_log.txt file
                log_dir = Path(temp_dir)
                log_files = list(log_dir.rglob("std_log.txt")) + list(log_dir.rglob("stdout.txt"))

                if not log_files:
                    return ""

                logs = log_files[0].read_text()

                if tail:
                    lines = logs.split("\n")
                    logs = "\n".join(lines[-tail:])

                return logs

        except Exception as e:
            logger.warning(f"Error fetching logs for {job_name}: {e}")
            return ""

    def stream_job_logs(
        self,
        job_name: str,
        on_log_line: Callable[[str], None] | None = None,
    ) -> subprocess.Popen:
        """Stream Azure ML job logs in real-time via az ml job stream.

        Args:
            job_name: Job name/ID.
            on_log_line: Optional callback for each log line.

        Returns:
            Subprocess handle (caller should call .wait() or .terminate()).
        """
        cmd = [
            "az",
            "ml",
            "job",
            "stream",
            "--name",
            job_name,
            "--workspace-name",
            self.config.workspace_name,
            "--resource-group",
            self.config.resource_group,
        ]

        logger.info(f"Starting log stream for job: {job_name}")

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,  # Line buffered
        )

        # Start background thread to read logs
        def _read_logs():
            try:
                for line in process.stdout:
                    line = line.rstrip()
                    if on_log_line:
                        on_log_line(line)
                    logger.debug(f"[Azure ML] {line}")
            except Exception as e:
                logger.error(f"Error reading job logs: {e}")

        thread = threading.Thread(target=_read_logs, daemon=True)
        thread.start()

        return process


class WorkerVNCManager:
    """Manages SSH tunnels for VNC access to parallel workers.

    Provides VNC access to multiple Azure ML compute instances via SSH tunnels.
    Each worker gets a unique local port (8006, 8007, 8008, ...) mapped to its
    VNC port (8006) via SSH.

    Example:
        manager = WorkerVNCManager(ml_client)
        manager.start_tunnels(["worker0", "worker1", "worker2"])
        # Access VNC at localhost:8006, localhost:8007, localhost:8008

        # Get status
        print(manager.get_status())

        # Cleanup
        manager.stop_all_tunnels()
    """

    VNC_REMOTE_PORT = 8006  # noVNC port inside Windows container
    VNC_BASE_LOCAL_PORT = 8006  # Local ports start at 8006

    def __init__(self, ml_client: AzureMLClient):
        """Initialize VNC manager.

        Args:
            ml_client: AzureMLClient instance for getting SSH info.
        """
        self.ml_client = ml_client
        self.tunnels: dict[str, subprocess.Popen] = {}  # worker_name -> tunnel process
        self.local_ports: dict[str, int] = {}  # worker_name -> local port

    def start_tunnel(self, worker_name: str, local_port: int | None = None) -> int | None:
        """Start SSH tunnel for a single worker.

        Args:
            worker_name: Compute instance name.
            local_port: Local port to use (auto-assigned if None).

        Returns:
            Local port number, or None if tunnel failed.
        """
        # Get SSH connection info
        ssh_info = self.ml_client.get_compute_ssh_info(worker_name)
        if not ssh_info:
            logger.error(f"Cannot start tunnel for {worker_name}: no SSH info")
            return None

        # Assign local port
        if local_port is None:
            # Find next available port
            used_ports = set(self.local_ports.values())
            local_port = self.VNC_BASE_LOCAL_PORT
            while local_port in used_ports:
                local_port += 1

        # Build SSH tunnel command
        ssh_cmd = [
            "ssh",
            "-N",  # Don't execute remote command
            "-L", f"{local_port}:localhost:{self.VNC_REMOTE_PORT}",
            "-p", str(ssh_info["ssh_port"]),
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            "-o", "ServerAliveInterval=60",
            f"{ssh_info['ssh_user']}@{ssh_info['ssh_host']}",
        ]

        try:
            # Start tunnel process
            process = subprocess.Popen(
                ssh_cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
            )

            # Give it a moment to establish
            time.sleep(1)

            # Check if it's still running
            if process.poll() is not None:
                stderr = process.stderr.read().decode() if process.stderr else ""
                logger.error(f"Tunnel failed for {worker_name}: {stderr}")
                return None

            self.tunnels[worker_name] = process
            self.local_ports[worker_name] = local_port
            logger.info(f"VNC tunnel started: localhost:{local_port} -> {worker_name}:8006")
            return local_port

        except Exception as e:
            logger.error(f"Failed to start tunnel for {worker_name}: {e}")
            return None

    def start_tunnels(self, worker_names: list[str]) -> dict[str, int]:
        """Start SSH tunnels for multiple workers.

        Args:
            worker_names: List of compute instance names.

        Returns:
            Dict mapping worker name to local port.
        """
        results = {}
        for i, worker_name in enumerate(worker_names):
            local_port = self.VNC_BASE_LOCAL_PORT + i
            port = self.start_tunnel(worker_name, local_port)
            if port:
                results[worker_name] = port
        return results

    def stop_tunnel(self, worker_name: str) -> None:
        """Stop SSH tunnel for a worker.

        Args:
            worker_name: Compute instance name.
        """
        if worker_name in self.tunnels:
            process = self.tunnels[worker_name]
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
            del self.tunnels[worker_name]
            del self.local_ports[worker_name]
            logger.info(f"Tunnel stopped for {worker_name}")

    def stop_all_tunnels(self) -> None:
        """Stop all SSH tunnels."""
        for worker_name in list(self.tunnels.keys()):
            self.stop_tunnel(worker_name)

    def get_status(self) -> dict[str, dict]:
        """Get status of all tunnels.

        Returns:
            Dict mapping worker name to status info.
        """
        status = {}
        for worker_name, process in self.tunnels.items():
            is_running = process.poll() is None
            status[worker_name] = {
                "local_port": self.local_ports.get(worker_name),
                "vnc_url": f"http://localhost:{self.local_ports.get(worker_name)}",
                "running": is_running,
                "pid": process.pid,
            }
        return status

    def print_vnc_urls(self) -> None:
        """Print VNC URLs for all active tunnels."""
        status = self.get_status()
        if not status:
            print("No active VNC tunnels")
            return

        print("\n=== VNC Access URLs ===")
        for worker_name, info in sorted(status.items()):
            if info["running"]:
                print(f"  {worker_name}: {info['vnc_url']}")
            else:
                print(f"  {worker_name}: (tunnel down)")
        print()


class AzureWAAOrchestrator:
    """Orchestrates WAA evaluation across multiple Azure VMs.

    This class manages the full lifecycle of a distributed WAA evaluation:
    1. Provisions Azure ML compute instances
    2. Distributes tasks across workers
    3. Monitors progress and collects results
    4. Cleans up resources

    Example:
        config = AzureConfig.from_env()
        orchestrator = AzureWAAOrchestrator(config, waa_repo_path="/path/to/WAA")

        results = orchestrator.run_evaluation(
            agent=my_agent,
            num_workers=40,
        )
        print(f"Success rate: {sum(r.success for r in results) / len(results):.1%}")
    """

    def __init__(
        self,
        config: AzureConfig,
        waa_repo_path: str | Path,
        experiment_name: str = "waa-eval",
    ):
        """Initialize orchestrator.

        Args:
            config: Azure configuration.
            waa_repo_path: Path to WAA repository.
            experiment_name: Name prefix for this evaluation.
        """
        self.config = config
        self.waa_repo_path = Path(waa_repo_path)
        self.experiment_name = experiment_name
        self.ml_client = AzureMLClient(config)
        self.vnc_manager = WorkerVNCManager(self.ml_client)
        self._current_run: EvaluationRun | None = None
        self._cleanup_registered = False
        self._interrupted = False

    def _setup_signal_handlers(self) -> None:
        """Setup signal handlers for graceful cleanup on interruption."""
        if self._cleanup_registered:
            return

        def signal_handler(sig, frame):
            logger.warning("\n⚠️  Interrupted! Cleaning up...")
            self._interrupted = True
            # Stop VNC tunnels first
            self.vnc_manager.stop_all_tunnels()
            if self._current_run and self._current_run.workers:
                self._cleanup_workers(self._current_run.workers)
            sys.exit(1)

        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        self._cleanup_registered = True
        logger.info("Signal handlers registered for graceful cleanup")

    def cleanup_stale_instances(self, prefix: str = "waa", dry_run: bool = False) -> int:
        """Delete compute instances from previous runs.

        This prevents quota exhaustion from stale instances that weren't
        properly cleaned up after failures or interruptions.

        Args:
            prefix: Name prefix filter (default: "waa").
            dry_run: If True, only list instances without deleting.

        Returns:
            Number of instances cleaned up (or found if dry_run=True).
        """
        logger.info(f"Scanning for stale compute instances with prefix '{prefix}'...")
        instances = self.ml_client.list_compute_instances(prefix=prefix)

        if not instances:
            logger.info("No stale instances found.")
            return 0

        logger.info(f"Found {len(instances)} stale instance(s):")
        for inst in instances:
            state = inst.get("state", "unknown")
            created = inst.get("created_on", "unknown")
            logger.info(f"  - {inst['name']}: {state} (created: {created})")

        if dry_run:
            logger.info("Dry-run mode: no instances deleted.")
            return len(instances)

        # Delete all stale instances in parallel
        logger.info(f"Deleting {len(instances)} stale instance(s)...")
        with ThreadPoolExecutor(max_workers=min(len(instances), 10)) as executor:
            futures = [
                executor.submit(self.ml_client.delete_compute_instance, inst["name"])
                for inst in instances
            ]
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    logger.warning(f"Cleanup error: {e}")

        logger.info(f"Cleanup complete: {len(instances)} instance(s) deleted.")
        return len(instances)

    def run_evaluation(
        self,
        agent: BenchmarkAgent,
        num_workers: int = 10,
        task_ids: list[str] | None = None,
        max_steps_per_task: int = 15,
        on_worker_complete: Callable[[WorkerState], None] | None = None,
        cleanup_on_complete: bool = True,
        cleanup_stale_on_start: bool = True,
        timeout_hours: float = 4.0,
        enable_vnc: bool = False,
    ) -> list[BenchmarkResult]:
        """Run evaluation across multiple Azure VMs.

        Args:
            agent: Agent to evaluate (must be serializable or API-based).
            num_workers: Number of parallel VMs.
            task_ids: Specific tasks to run (None = all 154 tasks).
            max_steps_per_task: Maximum steps per task.
            on_worker_complete: Callback when a worker finishes.
            cleanup_on_complete: Whether to delete VMs after completion.
            cleanup_stale_on_start: Whether to cleanup stale instances before starting.
            timeout_hours: Maximum job duration in hours (default: 4). Jobs are
                auto-canceled after this duration to prevent runaway costs.
            enable_vnc: Whether to start VNC tunnels for debugging (default: False).
                When enabled, VNC is accessible at localhost:8006, 8007, etc.

        Returns:
            List of BenchmarkResult for all tasks.
        """
        # Setup signal handlers for graceful cleanup on Ctrl+C
        self._setup_signal_handlers()

        # Cleanup stale instances from previous runs to prevent quota exhaustion
        if cleanup_stale_on_start:
            print("[0/5] Cleaning up stale compute instances from previous runs...")
            stale_count = self.cleanup_stale_instances(prefix="waa")
            if stale_count > 0:
                print(f"      Cleaned up {stale_count} stale instance(s).")
            else:
                print("      No stale instances found.")

        # Load tasks
        from openadapt_evals.adapters.waa import WAAAdapter

        adapter = WAAAdapter(waa_repo_path=self.waa_repo_path)
        if task_ids:
            tasks = [adapter.load_task(tid) for tid in task_ids]
        else:
            tasks = adapter.list_tasks()

        print(f"[1/5] Loaded {len(tasks)} tasks for {num_workers} worker(s)")

        # Create evaluation run
        run_id = f"{self.experiment_name}-{int(time.time())}"
        self._current_run = EvaluationRun(
            run_id=run_id,
            experiment_name=self.experiment_name,
            num_workers=num_workers,
            total_tasks=len(tasks),
            status="running",
            start_time=time.time(),
        )

        # Distribute tasks across workers
        task_batches = self._distribute_tasks(tasks, num_workers)

        # Create workers with cost tracking
        workers = []
        short_id = str(int(time.time()))[-4:]
        for i, batch in enumerate(task_batches):
            # Determine VM tier based on tasks if tiered VMs are enabled
            if self.config.enable_tiered_vms and batch:
                # Classify all tasks in batch and use highest complexity
                complexities = [classify_task_complexity(t) for t in batch]
                if "complex" in complexities:
                    vm_tier = "complex"
                elif "medium" in complexities:
                    vm_tier = "medium"
                else:
                    vm_tier = "simple"
                vm_size = VM_TIERS[vm_tier]
            else:
                # Use default VM size from config
                vm_tier = "medium"
                vm_size = self.config.vm_size

            # Determine cost
            is_spot = self.config.use_spot_instances
            if is_spot:
                hourly_cost = VM_TIER_SPOT_COSTS.get(vm_tier, 0.048)
            else:
                hourly_cost = VM_TIER_COSTS.get(vm_tier, 0.192)

            worker = WorkerState(
                worker_id=i,
                compute_name=f"waa{short_id}w{i}",
                assigned_tasks=[t.task_id for t in batch],
                vm_tier=vm_tier,
                vm_size=vm_size,
                is_spot=is_spot,
                hourly_cost=hourly_cost,
            )
            workers.append(worker)
        self._current_run.workers = workers

        try:
            # Provision VMs in parallel
            print(f"[2/5] Provisioning {num_workers} Azure VM(s)... (this takes 3-5 minutes)")
            self._provision_workers(workers)
            print(f"      VM(s) ready")

            # Start VNC tunnels if enabled (for debugging)
            if enable_vnc:
                print(f"[2.5/5] Starting VNC tunnels for debugging...")
                vnc_ports = self.start_vnc_tunnels(workers)
                if vnc_ports:
                    print(f"      VNC available at: {', '.join(f'localhost:{p}' for p in vnc_ports.values())}")
                else:
                    print(f"      Warning: VNC tunnels could not be established")

            # Submit jobs to workers
            print(f"[3/5] Submitting evaluation jobs...")
            self._submit_worker_jobs(workers, task_batches, agent, max_steps_per_task, timeout_hours)
            print(f"      Jobs submitted")

            # Wait for completion and collect results
            print(f"[4/5] Waiting for workers to complete...")
            results = self._wait_and_collect_results(workers, on_worker_complete)

            self._current_run.status = "completed"
            self._current_run.end_time = time.time()

            return results

        except KeyboardInterrupt:
            logger.warning("Evaluation interrupted by user")
            self._current_run.status = "interrupted"
            raise

        except Exception as e:
            logger.error(f"Evaluation failed: {e}")
            self._current_run.status = "failed"
            raise

        finally:
            # ALWAYS cleanup, even on error or interruption
            if cleanup_on_complete:
                print(f"[5/5] Cleaning up compute instances...")
                self._cleanup_workers(workers)
                print(f"      Cleanup complete.")

    def _distribute_tasks(
        self, tasks: list[BenchmarkTask], num_workers: int
    ) -> list[list[BenchmarkTask]]:
        """Distribute tasks evenly across workers."""
        batches: list[list[BenchmarkTask]] = [[] for _ in range(num_workers)]
        for i, task in enumerate(tasks):
            batches[i % num_workers].append(task)
        return batches

    def start_vnc_tunnels(self, workers: list[WorkerState] | None = None) -> dict[str, int]:
        """Start VNC tunnels for workers.

        This can be called during evaluation to enable VNC debugging,
        or standalone to connect to existing workers.

        Args:
            workers: List of workers to connect to. If None, uses current run's workers.

        Returns:
            Dict mapping worker name to local VNC port.
        """
        if workers is None and self._current_run:
            workers = self._current_run.workers

        if not workers:
            logger.warning("No workers to connect to")
            return {}

        # Get provisioned worker names
        worker_names = [
            w.compute_name for w in workers
            if w.status in ("provisioned", "running")
        ]

        if not worker_names:
            logger.warning("No provisioned workers found")
            return {}

        print(f"\n[VNC] Starting tunnels for {len(worker_names)} worker(s)...")
        ports = self.vnc_manager.start_tunnels(worker_names)

        if ports:
            print("\n=== VNC Access URLs ===")
            for name, port in sorted(ports.items()):
                print(f"  {name}: http://localhost:{port}")
            print("\nOpen these URLs in a browser to view Windows VMs")
            print("Tip: Arrange browser windows side-by-side for multi-worker view\n")

        return ports

    def start_vnc_for_existing_workers(self, prefix: str = "waa") -> dict[str, int]:
        """Start VNC tunnels for existing workers (standalone debugging).

        Useful for connecting to workers from a previous run or from another
        terminal while evaluation is in progress.

        Args:
            prefix: Worker name prefix to filter.

        Returns:
            Dict mapping worker name to local VNC port.
        """
        instances = self.ml_client.list_compute_instances(prefix=prefix)
        running = [i for i in instances if i.get("state") == "Running"]

        if not running:
            print(f"No running compute instances found with prefix '{prefix}'")
            return {}

        worker_names = [i["name"] for i in running]
        print(f"\nFound {len(worker_names)} running worker(s): {', '.join(worker_names)}")

        ports = self.vnc_manager.start_tunnels(worker_names)

        if ports:
            print("\n=== VNC Access URLs ===")
            for name, port in sorted(ports.items()):
                print(f"  {name}: http://localhost:{port}")
            print()

        return ports

    def _provision_workers(self, workers: list[WorkerState]) -> None:
        """Provision all worker VMs in parallel with cost-optimized sizing."""
        with ThreadPoolExecutor(max_workers=len(workers)) as executor:
            futures = {
                executor.submit(
                    self.ml_client.create_compute_instance,
                    worker.compute_name,
                    None,  # startup_script
                    worker.vm_size,  # VM size based on task complexity
                    worker.is_spot,  # Spot instance setting
                ): worker
                for worker in workers
            }

            for future in as_completed(futures):
                worker = futures[future]
                try:
                    future.result()
                    worker.status = "provisioned"
                    logger.info(
                        f"Worker {worker.worker_id} provisioned: {worker.vm_size} "
                        f"({'spot' if worker.is_spot else 'regular'}) "
                        f"${worker.hourly_cost:.3f}/hr"
                    )
                except Exception as e:
                    worker.status = "failed"
                    worker.error = str(e)
                    logger.error(f"Failed to provision worker {worker.worker_id}: {e}")

    def _submit_worker_jobs(
        self,
        workers: list[WorkerState],
        task_batches: list[list[BenchmarkTask]],
        agent: BenchmarkAgent,
        max_steps: int,
        timeout_hours: float = 4.0,
    ) -> None:
        """Submit evaluation jobs to workers.

        Args:
            workers: List of worker states.
            task_batches: Task batches for each worker.
            agent: Agent to run.
            max_steps: Maximum steps per task.
            timeout_hours: Maximum job duration in hours.
        """
        # Serialize agent config for remote workers
        agent_config = self._serialize_agent_config(agent)

        for worker, tasks in zip(workers, task_batches):
            if worker.status == "failed":
                continue

            try:
                # Build command using vanilla WAA run.py
                # Uses --worker_id and --num_workers for task distribution
                command = self._build_worker_command(
                    worker_id=worker.worker_id,
                    num_workers=len(workers),
                    max_steps=max_steps,
                    agent_config=agent_config,
                )

                # Environment variables for WAA runner
                # OPENAI_API_KEY is required by vanilla WAA
                env_vars = {
                    "WAA_WORKER_ID": str(worker.worker_id),
                    "WAA_NUM_WORKERS": str(len(workers)),
                    "WAA_MAX_STEPS": str(max_steps),
                    **agent_config.get("env_vars", {}),
                }

                # Submit job with timeout and capture job_name
                job_name = self.ml_client.submit_job(
                    compute_name=worker.compute_name,
                    command=command,
                    environment_variables=env_vars,
                    display_name=f"waa-worker-{worker.worker_id}",
                    timeout_hours=timeout_hours,
                )
                worker.job_name = job_name
                worker.status = "running"
                worker.start_time = time.time()

            except Exception as e:
                worker.status = "failed"
                worker.error = str(e)
                logger.error(f"Failed to submit job for worker {worker.worker_id}: {e}")

    def _serialize_agent_config(self, agent: BenchmarkAgent) -> dict[str, Any]:
        """Serialize agent configuration for remote execution.

        Extracts API keys and model config that can be passed via environment
        variables to remote workers running vanilla WAA.

        Args:
            agent: The agent to serialize.

        Returns:
            Dict with:
                - agent_name: WAA agent name (e.g., "navi")
                - model: Model name (e.g., "gpt-4o")
                - env_vars: Dict of environment variables to set
        """
        config: dict[str, Any] = {
            "agent_name": "navi",  # Default WAA agent
            "model": "gpt-4o",  # Default model
            "env_vars": {},
        }

        # Check if agent has provider/model info (ApiAgent pattern)
        if hasattr(agent, "provider"):
            if agent.provider == "openai":
                config["model"] = getattr(agent, "model", "gpt-4o")
                # Get API key from agent or environment
                api_key = getattr(agent, "api_key", None) or os.getenv("OPENAI_API_KEY")
                if api_key:
                    config["env_vars"]["OPENAI_API_KEY"] = api_key
            elif agent.provider == "anthropic":
                # WAA's navi agent supports Azure OpenAI, but we can use direct OpenAI
                # For Claude, we'd need custom agent code on the worker
                config["model"] = getattr(agent, "model", "claude-sonnet-4-5-20250929")
                api_key = getattr(agent, "api_key", None) or os.getenv("ANTHROPIC_API_KEY")
                if api_key:
                    config["env_vars"]["ANTHROPIC_API_KEY"] = api_key

        # Check for OpenAI API key in environment as fallback
        if "OPENAI_API_KEY" not in config["env_vars"]:
            openai_key = os.getenv("OPENAI_API_KEY")
            if openai_key:
                config["env_vars"]["OPENAI_API_KEY"] = openai_key

        return config

    def _build_worker_command(
        self,
        worker_id: int,
        num_workers: int,
        max_steps: int,
        agent_config: dict[str, Any],
    ) -> str:
        """Build the command to run on a worker VM.

        Uses vanilla WAA's run.py with --worker_id and --num_workers for
        built-in task distribution. This matches Microsoft's official
        Azure deployment pattern.

        Args:
            worker_id: This worker's ID (0-indexed).
            num_workers: Total number of workers.
            max_steps: Maximum steps per task.
            agent_config: Serialized agent configuration.

        Returns:
            Shell command string to execute in the WAA container.
        """
        agent_name = agent_config.get("agent_name", "navi")
        model = agent_config.get("model", "gpt-4o")

        # WAA Docker image has client at /client (see Dockerfile-WinArena)
        # The run.py script uses --worker_id and --num_workers for task distribution
        # Results are written to --result_dir
        return f"""
cd /client && python run.py \\
    --agent_name {agent_name} \\
    --model {model} \\
    --worker_id {worker_id} \\
    --num_workers {num_workers} \\
    --max_steps {max_steps} \\
    --result_dir /outputs
"""
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=60),
        retry=retry_if_exception_type((ConnectionError, TimeoutError)),
    )
    def _submit_job_with_retry(
        self,
        compute_name: str,
        command: str,
        environment_variables: dict[str, str],
        display_name: str,
        timeout_hours: float = 4.0,
    ) -> str:
        """Submit job with retry logic and health checking.

        This method wraps the job submission with:
        1. Automatic retry on transient failures (3 attempts)
        2. Exponential backoff between retries
        3. Container startup health check

        Args:
            compute_name: Target compute instance.
            command: Command to run.
            environment_variables: Environment variables for the job.
            display_name: Job display name.
            timeout_hours: Maximum job duration in hours.

        Returns:
            Job name/ID.

        Raises:
            ContainerStartupTimeout: If container fails to start after retries.
            Exception: If job submission fails after all retries.
        """
        from openadapt_evals.benchmarks.health_checker import (
            ContainerHealthChecker,
            ContainerStartupTimeout,
        )

        # Submit the job
        job_name = self.ml_client.submit_job(
            compute_name=compute_name,
            command=command,
            environment_variables=environment_variables,
            display_name=display_name,
            timeout_hours=timeout_hours,
        )

        # Initialize health checker
        health_checker = ContainerHealthChecker(self.ml_client)

        # Wait for container to start (5-10 minute timeout)
        logger.info(f"Waiting for container to start (job: {job_name})...")
        container_started = health_checker.wait_for_container_start(
            job_name=job_name,
            timeout_seconds=600,  # 10 minutes
        )

        if not container_started:
            # Cancel the stuck job
            logger.warning(f"Container failed to start, canceling job {job_name}")
            try:
                self.ml_client.client.jobs.cancel(job_name)
            except Exception as e:
                logger.warning(f"Failed to cancel stuck job: {e}")

            raise ContainerStartupTimeout(
                f"Container failed to start for job {job_name} within 10 minutes"
            )

        logger.info(f"Container started successfully for job {job_name}")
        return job_name

    def _wait_and_collect_results(
        self,
        workers: list[WorkerState],
        on_worker_complete: Callable[[WorkerState], None] | None,
    ) -> list[BenchmarkResult]:
        """Wait for all workers and collect results.

        Polls Azure ML job status (not compute status) to determine completion.
        Jobs can complete with status: Completed, Failed, Canceled.
        """
        all_results: list[BenchmarkResult] = []

        # Poll workers for completion
        pending_workers = [w for w in workers if w.status == "running"]

        while pending_workers:
            for worker in pending_workers[:]:
                try:
                    # Check job status (not compute status)
                    if not worker.job_name:
                        logger.warning(f"Worker {worker.worker_id} has no job_name")
                        worker.status = "failed"
                        worker.error = "No job submitted"
                        pending_workers.remove(worker)
                        continue

                    job = self.ml_client.client.jobs.get(worker.job_name)
                    job_status = job.status

                    if job_status in ["Completed", "Finished"]:
                        worker.status = "completed"
                        worker.end_time = time.time()

                        # Fetch results from job outputs
                        results = self._fetch_worker_results(worker)
                        worker.results = results
                        all_results.extend(results)

                        if on_worker_complete:
                            on_worker_complete(worker)

                        pending_workers.remove(worker)
                        logger.info(
                            f"Worker {worker.worker_id} completed: "
                            f"{len(results)} results"
                        )

                    elif job_status in ["Failed", "Canceled"]:
                        worker.status = "failed"
                        worker.error = f"Job {job_status}"
                        worker.end_time = time.time()

                        # Still try to fetch any partial results
                        results = self._fetch_worker_results(worker)
                        worker.results = results
                        all_results.extend(results)

                        pending_workers.remove(worker)
                        logger.warning(
                            f"Worker {worker.worker_id} failed ({job_status}): "
                            f"{len(results)} partial results"
                        )

                    # else: still running, continue polling

                except Exception as e:
                    logger.warning(f"Error checking worker {worker.worker_id}: {e}")

            if pending_workers:
                time.sleep(30)

        return all_results

    def _fetch_worker_results(self, worker: WorkerState) -> list[BenchmarkResult]:
        """Fetch results from a worker's output storage.

        Downloads job outputs from Azure ML and parses WAA result files.
        WAA writes results in the format: {result_dir}/{domain}/{task_id}/result.txt

        Args:
            worker: WorkerState with job_name set.

        Returns:
            List of BenchmarkResult for each task.
        """
        results = []

        if not worker.job_name:
            logger.warning(f"Worker {worker.worker_id} has no job_name, returning empty results")
            for task_id in worker.assigned_tasks:
                results.append(
                    BenchmarkResult(
                        task_id=task_id,
                        success=False,
                        score=0.0,
                        num_steps=0,
                        error_message="No job_name available",
                    )
                )
            return results

        try:
            # Download job outputs to a temp directory
            import tempfile
            with tempfile.TemporaryDirectory() as temp_dir:
                output_path = Path(temp_dir)

                # Download all outputs from the job
                self.ml_client.client.jobs.download(
                    name=worker.job_name,
                    download_path=output_path,
                    output_name="default",  # Default output location
                )

                # Parse WAA result files
                # WAA writes: {result_dir}/{action_space}/{observation_type}/{model}/{trial_id}/{domain}/{task_id}/result.txt
                # But we simplified to: /outputs/{domain}/{task_id}/result.txt
                outputs_dir = output_path / "outputs"
                if not outputs_dir.exists():
                    # Try alternative path structure
                    outputs_dir = output_path

                results = self._parse_waa_results(outputs_dir, worker.assigned_tasks)

        except Exception as e:
            logger.error(f"Failed to fetch results for worker {worker.worker_id}: {e}")
            # Return failed results for all tasks
            for task_id in worker.assigned_tasks:
                results.append(
                    BenchmarkResult(
                        task_id=task_id,
                        success=False,
                        score=0.0,
                        num_steps=0,
                        error_message=f"Failed to fetch results: {e}",
                    )
                )

        return results

    def _parse_waa_results(
        self,
        outputs_dir: Path,
        task_ids: list[str],
    ) -> list[BenchmarkResult]:
        """Parse WAA result files from downloaded outputs.

        WAA writes result.txt files containing a single float (0.0 or 1.0).

        Args:
            outputs_dir: Directory containing WAA outputs.
            task_ids: List of expected task IDs.

        Returns:
            List of BenchmarkResult for each task.
        """
        results = []

        for task_id in task_ids:
            # WAA task_id format: {domain}_{task_num} (e.g., notepad_1)
            # Result path: {domain}/{task_id}/result.txt
            parts = task_id.rsplit("_", 1)
            if len(parts) == 2:
                domain = parts[0]
            else:
                domain = task_id

            result_file = outputs_dir / domain / task_id / "result.txt"

            if result_file.exists():
                try:
                    score = float(result_file.read_text().strip())
                    results.append(
                        BenchmarkResult(
                            task_id=task_id,
                            success=score >= 1.0,
                            score=score,
                            num_steps=0,  # WAA doesn't expose step count in result.txt
                        )
                    )
                except (ValueError, OSError) as e:
                    logger.warning(f"Failed to parse result for {task_id}: {e}")
                    results.append(
                        BenchmarkResult(
                            task_id=task_id,
                            success=False,
                            score=0.0,
                            num_steps=0,
                            error_message=f"Failed to parse result: {e}",
                        )
                    )
            else:
                # Result file not found - task may have failed
                logger.warning(f"Result file not found for {task_id}: {result_file}")
                results.append(
                    BenchmarkResult(
                        task_id=task_id,
                        success=False,
                        score=0.0,
                        num_steps=0,
                        error_message="Result file not found",
                    )
                )

        return results

    def _cleanup_workers(self, workers: list[WorkerState]) -> None:
        """Delete all worker VMs and stop VNC tunnels."""
        # Stop VNC tunnels first
        if self.vnc_manager.tunnels:
            logger.info("Stopping VNC tunnels...")
            self.vnc_manager.stop_all_tunnels()

        logger.info("Cleaning up worker VMs...")
        with ThreadPoolExecutor(max_workers=len(workers)) as executor:
            futures = [
                executor.submit(self.ml_client.delete_compute_instance, w.compute_name)
                for w in workers
            ]
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    logger.warning(f"Cleanup error: {e}")

    def get_run_status(self) -> dict | None:
        """Get current run status."""
        if self._current_run is None:
            return None
        return self._current_run.to_dict()

    def cancel_run(self) -> None:
        """Cancel the current run and cleanup resources."""
        if self._current_run is None:
            return

        logger.info("Canceling evaluation run...")
        self._cleanup_workers(self._current_run.workers)
        self._current_run.status = "canceled"
        self._current_run.end_time = time.time()

    def monitor_job(
        self,
        job_name: str,
        live_tracking_file: str = "benchmark_live.json",
    ) -> None:
        """Monitor an existing Azure ML job with live tracking.

        This connects to a running job and streams its logs, updating
        the live tracking file in real-time for viewer integration.

        Args:
            job_name: Azure ML job name to monitor.
            live_tracking_file: Path to write live tracking data.
        """
        from openadapt_evals.benchmarks.live_tracker import LiveEvaluationTracker

        # Initialize live tracker
        tracker = LiveEvaluationTracker(
            output_file=live_tracking_file,
            total_tasks=0,  # Will be updated from logs
        )

        # Initialize log parser
        parser = AzureJobLogParser()

        # Create a mock task for current progress
        current_task = None

        def on_log_line(line: str):
            nonlocal current_task

            # Parse the log line
            parsed = parser.parse_line(line)

            if parsed is None:
                return

            # Handle different event types
            if parsed["type"] == "task_start":
                # Update total tasks if we learned it
                if parsed["total_tasks"] > tracker.total_tasks:
                    tracker.total_tasks = parsed["total_tasks"]

                # Start tracking this task
                from openadapt_evals.adapters import BenchmarkTask

                current_task = BenchmarkTask(
                    task_id=parsed["task_id"],
                    instruction=f"Azure ML Task {parsed['task_id']}",
                    domain="azure",
                )
                tracker.start_task(current_task)
                logger.info(
                    f"Task {parsed['task_idx']}/{parsed['total_tasks']}: {parsed['task_id']}"
                )

            elif parsed["type"] == "step" and current_task:
                # Record step
                from openadapt_evals.adapters import BenchmarkObservation, BenchmarkAction

                obs = BenchmarkObservation(screenshot=None)
                action = BenchmarkAction(type=parsed["action_type"].lower())

                tracker.record_step(
                    step_idx=parsed["step_idx"],
                    observation=obs,
                    action=action,
                    reasoning=None,
                )
                logger.info(f"  Step {parsed['step_idx']}: {parsed['action_type']}")

            elif parsed["type"] == "task_result" and current_task:
                # Finish tracking this task
                from openadapt_evals.adapters import BenchmarkResult

                result = BenchmarkResult(
                    task_id=parsed["task_id"],
                    success=parsed["success"],
                    score=1.0 if parsed["success"] else 0.0,
                    num_steps=parser.current_step,
                )
                tracker.finish_task(result)
                status = "SUCCESS" if parsed["success"] else "FAIL"
                logger.info(f"Task {parsed['task_id']}: {status}")
                current_task = None

            elif parsed["type"] == "error":
                logger.warning(f"Error in job: {parsed['message']}")

        # Start streaming logs
        logger.info(f"Monitoring Azure ML job: {job_name}")
        logger.info(f"Live tracking file: {live_tracking_file}")

        stream_process = self.ml_client.stream_job_logs(
            job_name=job_name,
            on_log_line=on_log_line,
        )

        try:
            # Wait for job to complete or user interrupt
            stream_process.wait()
            logger.info("Job monitoring complete")
            tracker.finish()
        except KeyboardInterrupt:
            logger.info("Monitoring interrupted by user")
            stream_process.terminate()
            tracker.finish()
        except Exception as e:
            logger.error(f"Error monitoring job: {e}")
            stream_process.terminate()
            tracker.finish()
            raise


def estimate_cost(
    num_tasks: int = 154,
    num_workers: int = 1,
    avg_task_duration_minutes: float = 1.0,
    vm_hourly_cost: float = 0.19,  # Standard_D4_v3 in East US (free trial compatible)
) -> dict:
    """Estimate Azure costs for a WAA evaluation run.

    Args:
        num_tasks: Number of tasks to run.
        num_workers: Number of parallel VMs (default: 1 for free trial).
        avg_task_duration_minutes: Average time per task.
        vm_hourly_cost: Hourly cost per VM (D4_v3 = $0.19/hr, D8_v3 = $0.38/hr).

    Returns:
        Dict with cost estimates.
    """
    tasks_per_worker = num_tasks / num_workers
    total_minutes = tasks_per_worker * avg_task_duration_minutes
    total_hours = total_minutes / 60

    # Add overhead for provisioning/cleanup
    overhead_hours = 0.25  # ~15 minutes

    vm_hours = (total_hours + overhead_hours) * num_workers
    total_cost = vm_hours * vm_hourly_cost

    return {
        "num_tasks": num_tasks,
        "num_workers": num_workers,
        "tasks_per_worker": tasks_per_worker,
        "estimated_duration_minutes": total_minutes + (overhead_hours * 60),
        "total_vm_hours": vm_hours,
        "estimated_cost_usd": total_cost,
        "cost_per_task_usd": total_cost / num_tasks,
    }
