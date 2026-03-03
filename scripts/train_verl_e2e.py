"""End-to-end verl-agent training orchestration.

Provisions a GPU VM, installs verl-agent, connects to a WAA server,
and launches GiGPO/GRPO training. Reuses existing openadapt-evals
infrastructure (AzureVMManager, AWSVMManager, SSHTunnelManager, ssh_run).

Architecture:
    LOCAL MACHINE          GPU VM (training)         CPU VM (WAA)
    +--------------+       +------------------+      +----------------+
    | This script  | SSH   | verl-agent       |      | Docker         |
    | (orchestrate)| ----> | WAADesktopEnv    | HTTP | QEMU (Win 11)  |
    |              |       | vLLM + Ray       | ---> | WAA Flask API  |
    +--------------+       +------------------+      +----------------+

The GPU VM runs verl-agent training. WAADesktopEnv connects to the WAA
server on the CPU VM via HTTP. The CPU VM can be an existing pool worker
or created fresh.

Usage:
    # Azure (provisions GPU VM + connects to existing WAA server)
    python scripts/train_verl_e2e.py \\
        --cloud azure \\
        --waa-server http://localhost:5001 \\
        --task-id <WAA_UUID>

    # AWS (provisions both GPU VM and WAA VM)
    python scripts/train_verl_e2e.py \\
        --cloud aws \\
        --task-id <WAA_UUID>

    # Dry run (show what would happen)
    python scripts/train_verl_e2e.py --dry-run --cloud azure

    # Use existing GPU VM
    python scripts/train_verl_e2e.py \\
        --gpu-ip 52.170.1.100 \\
        --waa-server http://localhost:5001 \\
        --task-id <WAA_UUID>
"""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys
import time
from pathlib import Path

logger = logging.getLogger(__name__)

SETUP_SCRIPT = Path(__file__).parent / "setup_gpu_training.sh"
GPU_VM_NAME = "verl-train-00"
AUTO_SHUTDOWN_HOURS = 6


def _get_vm_manager(cloud: str):
    """Get the appropriate VM manager for the cloud provider."""
    if cloud == "azure":
        from openadapt_evals.infrastructure.azure_vm import AzureVMManager

        return AzureVMManager()
    elif cloud == "aws":
        from openadapt_evals.infrastructure.aws_vm import AWSVMManager

        return AWSVMManager()
    else:
        raise ValueError(f"Unknown cloud: {cloud}")


def _ssh_run(ip: str, cmd: str, username: str = "ubuntu", stream: bool = True):
    """Run a command on the remote VM via SSH with streaming output."""
    from openadapt_evals.infrastructure.azure_vm import ssh_run

    return ssh_run(ip=ip, cmd=cmd, stream=stream, username=username)


def _scp_upload(ip: str, local_path: Path, remote_path: str, username: str = "ubuntu"):
    """Upload a file to the remote VM via SCP."""
    from openadapt_evals.infrastructure.azure_vm import SSH_OPTS

    cmd = ["scp", *SSH_OPTS, str(local_path), f"{username}@{ip}:{remote_path}"]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(f"SCP failed: {result.stderr}")


def provision_gpu_vm(cloud: str, dry_run: bool = False) -> tuple[str, str, str]:
    """Provision a GPU VM and return (ip, size, region).

    Returns:
        Tuple of (public_ip, vm_size, region).
    """
    vm = _get_vm_manager(cloud)
    username = vm.ssh_username

    logger.info("Finding available GPU VM size...")
    vm_size, region, cost = vm.find_available_size_and_region(gpu=True)
    logger.info("Selected: %s ($%.2f/hr) in %s", vm_size, cost, region)

    if dry_run:
        logger.info("[DRY RUN] Would create %s in %s", GPU_VM_NAME, region)
        return ("DRY_RUN_IP", vm_size, region)

    logger.info("Creating GPU VM '%s'...", GPU_VM_NAME)
    info = vm.create_vm(name=GPU_VM_NAME, region=region, size=vm_size)
    ip = info.get("publicIpAddress") or vm.get_vm_ip(GPU_VM_NAME)

    if not ip:
        raise RuntimeError(f"Failed to get IP for {GPU_VM_NAME}")

    logger.info("GPU VM created: %s (%s)", ip, vm_size)

    # Set auto-shutdown to prevent runaway costs
    vm.set_auto_shutdown(GPU_VM_NAME, hours=AUTO_SHUTDOWN_HOURS)
    logger.info("Auto-shutdown set to %d hours", AUTO_SHUTDOWN_HOURS)

    # Wait for SSH
    logger.info("Waiting for SSH...")
    for attempt in range(30):
        try:
            result = _ssh_run(ip, "echo ready", username=username, stream=False)
            if result.returncode == 0:
                break
        except Exception:
            pass
        time.sleep(10)
    else:
        raise RuntimeError(f"SSH not ready after 5 minutes: {ip}")

    return (ip, vm_size, region)


def setup_training(ip: str, username: str = "ubuntu"):
    """Install verl-agent and dependencies on the GPU VM."""
    logger.info("Uploading setup script...")
    _scp_upload(ip, SETUP_SCRIPT, "/tmp/setup_gpu_training.sh", username=username)

    logger.info("Running setup (this may take 15-30 minutes)...")
    result = _ssh_run(
        ip,
        "bash /tmp/setup_gpu_training.sh",
        username=username,
        stream=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Setup failed with exit code {result.returncode}")

    logger.info("Setup complete!")


def launch_training(
    ip: str,
    waa_server: str,
    task_id: str,
    algorithm: str = "gigpo",
    model: str = "Qwen/Qwen2.5-VL-3B-Instruct",
    n_gpus: int = 2,
    max_turns: int = 15,
    group_size: int = 8,
    epochs: int = 100,
    username: str = "ubuntu",
):
    """Launch verl-agent training on the GPU VM.

    The training connects to the WAA server via HTTP for environment
    interaction (reset, step, evaluate).
    """
    # Build the verl-agent training command using Hydra-style overrides
    train_cmd = f"""
cd ~/verl-agent && \\
conda activate verl-agent && \\
python3 -m verl.trainer.main_ppo \\
    algorithm.adv_estimator={algorithm} \\
    actor_rollout_ref.model.path={model} \\
    actor_rollout_ref.rollout.name=vllm \\
    actor_rollout_ref.rollout.tensor_model_parallel_size={n_gpus} \\
    env.env_name=openadapt_evals.adapters.verl_env.WAADesktopEnv \\
    env.env_kwargs.server_url={waa_server} \\
    env.env_kwargs.task_id={task_id} \\
    env.env_kwargs.max_steps={max_turns} \\
    env.max_steps={max_turns} \\
    env.rollout.n={group_size} \\
    data.train_batch_size={group_size} \\
    data.max_prompt_length=2048 \\
    data.max_response_length=512 \\
    data.return_raw_chat=True \\
    trainer.n_gpus_per_node={n_gpus} \\
    trainer.nnodes=1 \\
    trainer.total_epochs={epochs} \\
    trainer.logger=['console','wandb'] \\
    trainer.project_name=openadapt-waa-rl
"""
    logger.info("Launching training with %s on %d GPU(s)...", algorithm, n_gpus)
    logger.info("Model: %s", model)
    logger.info("WAA server: %s", waa_server)
    logger.info("Task: %s", task_id)

    result = _ssh_run(ip, train_cmd, username=username, stream=True)
    return result.returncode


def cleanup_gpu_vm(cloud: str):
    """Deallocate (not delete) the GPU VM to stop billing."""
    vm = _get_vm_manager(cloud)
    logger.info("Deallocating GPU VM '%s'...", GPU_VM_NAME)
    vm.deallocate_vm(GPU_VM_NAME)
    logger.info("GPU VM deallocated (disk preserved, billing stopped)")


def main():
    parser = argparse.ArgumentParser(
        description="End-to-end verl-agent training on a GPU VM",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--cloud", choices=["azure", "aws"], default="azure",
        help="Cloud provider (default: azure)",
    )
    parser.add_argument(
        "--gpu-ip", type=str, default=None,
        help="Use an existing GPU VM instead of provisioning one",
    )
    parser.add_argument(
        "--waa-server", type=str, default="http://localhost:5001",
        help="WAA server URL accessible from GPU VM (default: http://localhost:5001)",
    )
    parser.add_argument(
        "--task-id", type=str, required=True,
        help="WAA task UUID to train on",
    )
    parser.add_argument(
        "--algorithm", choices=["gigpo", "grpo", "ppo"], default="gigpo",
        help="RL algorithm (default: gigpo)",
    )
    parser.add_argument(
        "--model", type=str, default="Qwen/Qwen2.5-VL-3B-Instruct",
        help="Model to train (default: Qwen/Qwen2.5-VL-3B-Instruct)",
    )
    parser.add_argument(
        "--n-gpus", type=int, default=2,
        help="Number of GPUs per node (default: 2)",
    )
    parser.add_argument(
        "--epochs", type=int, default=100,
        help="Training epochs (default: 100)",
    )
    parser.add_argument(
        "--setup-only", action="store_true",
        help="Only provision and setup, don't start training",
    )
    parser.add_argument(
        "--skip-setup", action="store_true",
        help="Skip setup (VM already configured)",
    )
    parser.add_argument(
        "--cleanup", action="store_true",
        help="Deallocate the GPU VM after training",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Show what would happen without doing it",
    )
    parser.add_argument(
        "-v", "--verbose", action="store_true",
        help="Verbose logging",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    username = "azureuser" if args.cloud == "azure" else "ubuntu"

    try:
        # Step 1: Provision GPU VM
        if args.gpu_ip:
            ip = args.gpu_ip
            logger.info("Using existing GPU VM: %s", ip)
        else:
            ip, vm_size, region = provision_gpu_vm(args.cloud, dry_run=args.dry_run)
            if args.dry_run:
                logger.info("[DRY RUN] Would setup and train on %s", vm_size)
                return

        # Step 2: Install dependencies
        if not args.skip_setup:
            setup_training(ip, username=username)

        if args.setup_only:
            logger.info("Setup complete. VM ready at: %s", ip)
            logger.info("SSH: ssh %s@%s", username, ip)
            return

        # Step 3: Launch training
        exit_code = launch_training(
            ip=ip,
            waa_server=args.waa_server,
            task_id=args.task_id,
            algorithm=args.algorithm,
            model=args.model,
            n_gpus=args.n_gpus,
            epochs=args.epochs,
            username=username,
        )

        if exit_code != 0:
            logger.error("Training exited with code %d", exit_code)
            sys.exit(exit_code)

        logger.info("Training complete!")

    finally:
        if args.cleanup and not args.dry_run and not args.gpu_ip:
            cleanup_gpu_vm(args.cloud)


if __name__ == "__main__":
    main()
