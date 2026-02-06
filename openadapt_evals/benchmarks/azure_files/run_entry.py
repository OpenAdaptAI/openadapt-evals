"""Entry script for WAA evaluation on Azure ML.

This script runs INSIDE the WAA Docker container and:
1. Sets up storage paths
2. Starts the Windows VM via /entry_setup.sh
3. Runs the WAA client with the specified configuration

Based on Microsoft's WindowsAgentArena/scripts/azure_files/run_entry.py
"""

import os
import subprocess
import sys
import time


def main():
    """Main entry point."""
    print("=" * 60)
    print("WAA Azure Entry Script Starting")
    print("=" * 60)

    # Parse arguments
    if len(sys.argv) < 8:
        print(f"Usage: {sys.argv[0]} <output_path> <exp_name> <num_workers> "
              "<worker_id> <agent> <model> <max_steps>")
        print(f"Got: {sys.argv}")
        sys.exit(1)

    output_path = sys.argv[1]
    exp_name = sys.argv[2]
    num_workers = sys.argv[3]
    worker_id = sys.argv[4]
    agent = sys.argv[5]
    model = sys.argv[6]
    max_steps = sys.argv[7]

    print(f"Configuration:")
    print(f"  Output path: {output_path}")
    print(f"  Experiment: {exp_name}")
    print(f"  Workers: {num_workers} (this is worker {worker_id})")
    print(f"  Agent: {agent}")
    print(f"  Model: {model}")
    print(f"  Max steps: {max_steps}")

    # Create result directory
    result_dir = os.path.join(output_path, exp_name, f"worker_{worker_id}")
    os.makedirs(result_dir, exist_ok=True)
    print(f"Result directory: {result_dir}")

    # Write start marker
    with open(os.path.join(result_dir, "started.txt"), "w") as f:
        f.write(f"Started at {time.ctime()}\n")

    # Check NET_ADMIN capability (required for QEMU networking)
    print("\nChecking NET_ADMIN capability...")
    try:
        subprocess.check_call(
            ["ip", "link", "add", "dummy0", "type", "dummy"],
            stderr=subprocess.DEVNULL
        )
        subprocess.check_call(
            ["ip", "link", "del", "dummy0"],
            stderr=subprocess.DEVNULL
        )
        print("  NET_ADMIN: ENABLED")
    except subprocess.CalledProcessError:
        print("  NET_ADMIN: DISABLED (WAA may not work correctly)")

    # Start Windows VM via entry_setup.sh
    # This script is part of the WAA Docker image and:
    # - Starts QEMU with Windows 11
    # - Waits for Windows to boot
    # - Starts the WAA server
    print("\n" + "=" * 60)
    print("Starting Windows VM (this takes 5-15 minutes)...")
    print("=" * 60)

    entry_script = "/entry_setup.sh"
    if os.path.exists(entry_script):
        result = os.system(entry_script)
        if result != 0:
            print(f"WARNING: entry_setup.sh returned {result}")
    else:
        print(f"WARNING: {entry_script} not found!")
        print("Available files in /:")
        os.system("ls -la /")

    # Run the WAA client
    print("\n" + "=" * 60)
    print("Starting WAA client...")
    print("=" * 60)

    client_cmd = (
        f"cd /client && python run.py "
        f"--agent_name {agent} "
        f"--model {model} "
        f"--worker_id {worker_id} "
        f"--num_workers {num_workers} "
        f"--max_steps {max_steps} "
        f"--result_dir {result_dir}"
    )
    print(f"Command: {client_cmd}")

    result = os.system(client_cmd)

    # Write completion marker
    with open(os.path.join(result_dir, "completed.txt"), "w") as f:
        f.write(f"Completed at {time.ctime()}\n")
        f.write(f"Exit code: {result}\n")

    print("\n" + "=" * 60)
    print(f"WAA client finished with exit code {result}")
    print("=" * 60)

    sys.exit(result)


if __name__ == "__main__":
    main()
