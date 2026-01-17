"""CLI for Windows Agent Arena benchmark evaluation.

This module provides command-line tools for running WAA evaluations:
- Mock evaluation (no Windows VM required)
- Live evaluation against a WAA server
- Azure-based parallel evaluation

Usage:
    # Run mock evaluation
    python -m openadapt_evals.benchmarks.cli mock --tasks 10

    # Run live evaluation
    python -m openadapt_evals.benchmarks.cli live --server http://vm-ip:5000

    # Check server status
    python -m openadapt_evals.benchmarks.cli probe --server http://vm-ip:5000

    # Generate benchmark viewer
    python -m openadapt_evals.benchmarks.cli view --run-name my_eval_run
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def cmd_mock(args: argparse.Namespace) -> int:
    """Run mock evaluation (no Windows VM required)."""
    from openadapt_evals.benchmarks import (
        WAAMockAdapter,
        SmartMockAgent,
        EvaluationConfig,
        evaluate_agent_on_benchmark,
        compute_metrics,
    )
    from openadapt_evals.agents import ApiAgent

    print(f"Running mock WAA evaluation with {args.tasks} tasks...")

    # Create mock adapter
    adapter = WAAMockAdapter(num_tasks=args.tasks)

    # Create agent based on --agent option
    agent_type = getattr(args, "agent", "mock") or "mock"

    # Load demo from file if provided
    demo_text = None
    if hasattr(args, "demo") and args.demo:
        demo_path = Path(args.demo)
        if demo_path.exists():
            demo_text = demo_path.read_text()
            print(f"Loaded demo from {demo_path} ({len(demo_text)} chars)")
        else:
            # Treat as direct demo text
            demo_text = args.demo

    if agent_type == "mock":
        agent = SmartMockAgent()
        print("Using SmartMockAgent (deterministic mock)")
    elif agent_type in ("api-claude", "claude", "anthropic"):
        try:
            agent = ApiAgent(provider="anthropic", demo=demo_text)
            print(f"Using ApiAgent with Claude (demo={'yes' if agent.demo else 'no'})")
        except RuntimeError as e:
            print(f"ERROR: {e}")
            return 1
    elif agent_type in ("api-openai", "openai", "gpt"):
        try:
            agent = ApiAgent(provider="openai", demo=demo_text)
            print(f"Using ApiAgent with GPT-5.1 (demo={'yes' if agent.demo else 'no'})")
        except RuntimeError as e:
            print(f"ERROR: {e}")
            return 1
    else:
        print(f"ERROR: Unknown agent type: {agent_type}")
        print("Available for mock: mock, api-claude, api-openai")
        return 1

    # Create config for trace collection
    config = None
    if args.output:
        config = EvaluationConfig(
            save_execution_traces=True,
            output_dir=args.output,
            run_name=args.run_name or "mock_eval",
        )

    # Run evaluation
    results = evaluate_agent_on_benchmark(
        agent=agent,
        adapter=adapter,
        max_steps=args.max_steps,
        config=config,
    )

    # Compute and display metrics
    metrics = compute_metrics(results)

    print("\n" + "=" * 50)
    print("Evaluation Results")
    print("=" * 50)
    print(f"Tasks:        {metrics['num_tasks']}")
    print(f"Success rate: {metrics['success_rate']:.1%}")
    print(f"Avg score:    {metrics['avg_score']:.3f}")
    print(f"Avg steps:    {metrics['avg_steps']:.1f}")

    if config:
        print(f"\nResults saved to: {config.output_dir}/{config.run_name}")

    return 0


def cmd_live(args: argparse.Namespace) -> int:
    """Run live evaluation against a WAA server."""
    from openadapt_evals.adapters import WAALiveAdapter, WAALiveConfig
    from openadapt_evals.agents import SmartMockAgent, ApiAgent, RetrievalAugmentedAgent
    from openadapt_evals.benchmarks import (
        EvaluationConfig,
        evaluate_agent_on_benchmark,
        compute_metrics,
    )

    print(f"Connecting to WAA server at {args.server}...")

    # Create live adapter
    config = WAALiveConfig(
        server_url=args.server,
        max_steps=args.max_steps,
    )
    adapter = WAALiveAdapter(config)

    # Check connection
    if not adapter.check_connection():
        print(f"ERROR: Cannot connect to WAA server at {args.server}")
        print("Ensure Windows VM is running and WAA server is started.")
        return 1

    print("Connected!")

    # Create agent based on --agent option
    agent_type = getattr(args, "agent", "mock") or "mock"

    # Load demo from file if provided
    demo_text = None
    if hasattr(args, "demo") and args.demo:
        demo_path = Path(args.demo)
        if demo_path.exists():
            demo_text = demo_path.read_text()
            print(f"Loaded demo from {demo_path} ({len(demo_text)} chars)")
        else:
            # Treat as direct demo text
            demo_text = args.demo

    # Check for demo library (for retrieval agents)
    demo_library_path = getattr(args, "demo_library", None)

    if agent_type == "mock":
        agent = SmartMockAgent()
    elif agent_type in ("api-claude", "claude", "anthropic"):
        try:
            agent = ApiAgent(provider="anthropic", demo=demo_text)
            print(f"Using ApiAgent with Claude (demo={'yes' if agent.demo else 'no'})")
        except RuntimeError as e:
            print(f"ERROR: {e}")
            return 1
    elif agent_type in ("api-openai", "openai", "gpt"):
        try:
            agent = ApiAgent(provider="openai", demo=demo_text)
            print(f"Using ApiAgent with GPT-5.1 (demo={'yes' if agent.demo else 'no'})")
        except RuntimeError as e:
            print(f"ERROR: {e}")
            return 1
    elif agent_type in ("retrieval-claude", "retrieval-anthropic"):
        if not demo_library_path:
            print("ERROR: --demo-library required for retrieval agent")
            return 1
        try:
            agent = RetrievalAugmentedAgent(
                demo_library_path=demo_library_path,
                provider="anthropic",
            )
            print(f"Using RetrievalAugmentedAgent with Claude (library={demo_library_path})")
        except Exception as e:
            print(f"ERROR: {e}")
            return 1
    elif agent_type in ("retrieval-openai", "retrieval-gpt"):
        if not demo_library_path:
            print("ERROR: --demo-library required for retrieval agent")
            return 1
        try:
            agent = RetrievalAugmentedAgent(
                demo_library_path=demo_library_path,
                provider="openai",
            )
            print(f"Using RetrievalAugmentedAgent with GPT-5.1 (library={demo_library_path})")
        except Exception as e:
            print(f"ERROR: {e}")
            return 1
    else:
        print(f"ERROR: Unknown agent type: {agent_type}")
        print("Available: mock, api-claude, api-openai, retrieval-claude, retrieval-openai")
        return 1

    # Create config for trace collection
    eval_config = None
    if args.output:
        eval_config = EvaluationConfig(
            save_execution_traces=True,
            output_dir=args.output,
            run_name=args.run_name or "live_eval",
        )

    # Load tasks
    if args.task_ids:
        task_ids = args.task_ids.split(",")
    else:
        # For live evaluation, we need explicit task IDs
        print("ERROR: --task-ids required for live evaluation")
        print("Example: --task-ids notepad_1,notepad_2,browser_1")
        return 1

    # Run evaluation
    results = evaluate_agent_on_benchmark(
        agent=agent,
        adapter=adapter,
        max_steps=args.max_steps,
        task_ids=task_ids,
        config=eval_config,
    )

    # Compute and display metrics
    metrics = compute_metrics(results)

    print("\n" + "=" * 50)
    print("Evaluation Results")
    print("=" * 50)
    print(f"Tasks:        {metrics['num_tasks']}")
    print(f"Success rate: {metrics['success_rate']:.1%}")
    print(f"Avg score:    {metrics['avg_score']:.3f}")
    print(f"Avg steps:    {metrics['avg_steps']:.1f}")

    if eval_config:
        print(f"\nResults saved to: {eval_config.output_dir}/{eval_config.run_name}")

    return 0


def cmd_probe(args: argparse.Namespace) -> int:
    """Check if WAA server is reachable."""
    import time

    try:
        import requests
    except ImportError:
        print("ERROR: requests package required. Install with: pip install requests")
        return 1

    server_url = args.server

    print(f"Probing WAA server at {server_url}...")

    max_attempts = args.wait_attempts if args.wait else 1
    attempt = 0

    while attempt < max_attempts:
        attempt += 1
        try:
            resp = requests.get(f"{server_url}/probe", timeout=5.0)
            if resp.status_code == 200:
                print(f"SUCCESS: WAA server is ready at {server_url}")
                return 0
            else:
                print(f"WARNING: Server returned status {resp.status_code}")
        except requests.ConnectionError:
            if args.wait and attempt < max_attempts:
                print(f"Attempt {attempt}/{max_attempts}: Connection refused, waiting...")
                time.sleep(args.wait_interval)
            else:
                print(f"ERROR: Cannot connect to {server_url}")
        except requests.Timeout:
            if args.wait and attempt < max_attempts:
                print(f"Attempt {attempt}/{max_attempts}: Timeout, waiting...")
                time.sleep(args.wait_interval)
            else:
                print(f"ERROR: Connection timed out")

    print("ERROR: WAA server not reachable")
    return 1


def cmd_view(args: argparse.Namespace) -> int:
    """Generate HTML viewer for benchmark results."""
    from openadapt_evals.benchmarks import generate_benchmark_viewer

    benchmark_dir = Path(args.benchmark_dir or "benchmark_results") / args.run_name

    if not benchmark_dir.exists():
        print(f"ERROR: Benchmark directory not found: {benchmark_dir}")
        return 1

    output_path = benchmark_dir / "viewer.html"

    print(f"Generating viewer from: {benchmark_dir}")

    generate_benchmark_viewer(
        benchmark_dir=benchmark_dir,
        output_path=output_path,
        embed_screenshots=args.embed_screenshots,
    )

    print(f"Viewer generated: {output_path}")

    if not args.no_open:
        import webbrowser
        webbrowser.open(f"file://{output_path.absolute()}")

    return 0


def cmd_estimate(args: argparse.Namespace) -> int:
    """Estimate Azure costs for WAA evaluation."""
    from openadapt_evals.benchmarks.azure import estimate_cost

    costs = estimate_cost(
        num_tasks=args.tasks,
        num_workers=args.workers,
        avg_task_duration_minutes=args.task_duration,
        vm_hourly_cost=args.vm_cost,
    )

    print("\n" + "=" * 50)
    print("Azure Cost Estimate")
    print("=" * 50)
    print(f"Tasks:            {costs['num_tasks']}")
    print(f"Workers:          {costs['num_workers']}")
    print(f"Tasks/worker:     {costs['tasks_per_worker']:.1f}")
    print(f"Est. duration:    {costs['estimated_duration_minutes']:.1f} minutes")
    print(f"Total VM hours:   {costs['total_vm_hours']:.2f}")
    print(f"Est. total cost:  ${costs['estimated_cost_usd']:.2f}")
    print(f"Cost per task:    ${costs['cost_per_task_usd']:.4f}")

    return 0


def cmd_vm_start(args: argparse.Namespace) -> int:
    """Start an Azure VM."""
    import subprocess

    vm_name = args.vm_name
    resource_group = args.resource_group

    print(f"Starting VM '{vm_name}' in resource group '{resource_group}'...")

    result = subprocess.run(
        ["az", "vm", "start", "--name", vm_name, "--resource-group", resource_group],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        print(f"ERROR: Failed to start VM: {result.stderr}")
        return 1

    print(f"VM '{vm_name}' started successfully.")

    # Get public IP
    result = subprocess.run(
        [
            "az", "vm", "show",
            "--name", vm_name,
            "--resource-group", resource_group,
            "--show-details",
            "--query", "publicIps",
            "-o", "tsv",
        ],
        capture_output=True,
        text=True,
    )

    if result.returncode == 0 and result.stdout.strip():
        print(f"Public IP: {result.stdout.strip()}")

    return 0


def cmd_vm_stop(args: argparse.Namespace) -> int:
    """Stop an Azure VM."""
    import subprocess

    vm_name = args.vm_name
    resource_group = args.resource_group

    print(f"Stopping VM '{vm_name}' in resource group '{resource_group}'...")

    cmd = ["az", "vm", "deallocate", "--name", vm_name, "--resource-group", resource_group]
    if args.no_wait:
        cmd.append("--no-wait")

    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        print(f"ERROR: Failed to stop VM: {result.stderr}")
        return 1

    print(f"VM '{vm_name}' stopped (deallocated).")
    return 0


def cmd_vm_status(args: argparse.Namespace) -> int:
    """Check Azure VM status."""
    import subprocess
    import json as json_module

    vm_name = args.vm_name
    resource_group = args.resource_group

    result = subprocess.run(
        [
            "az", "vm", "show",
            "--name", vm_name,
            "--resource-group", resource_group,
            "--show-details",
            "--query", "{name:name, status:powerState, publicIp:publicIps, privateIp:privateIps, size:hardwareProfile.vmSize}",
            "-o", "json",
        ],
        capture_output=True,
        text=True,
    )

    if result.returncode != 0:
        print(f"ERROR: Failed to get VM status: {result.stderr}")
        return 1

    try:
        data = json_module.loads(result.stdout)
        print(f"VM Name:    {data.get('name', 'N/A')}")
        print(f"Status:     {data.get('status', 'N/A')}")
        print(f"Public IP:  {data.get('publicIp', 'N/A')}")
        print(f"Private IP: {data.get('privateIp', 'N/A')}")
        print(f"Size:       {data.get('size', 'N/A')}")

        if args.json:
            print(f"\nJSON: {result.stdout.strip()}")

    except json_module.JSONDecodeError:
        print(result.stdout)

    return 0


def cmd_server_start(args: argparse.Namespace) -> int:
    """Start WAA server on the Azure VM via run-command.

    WAA runs inside a Docker container with Windows nested virtualization.
    This command starts the existing 'winarena' container.
    """
    import subprocess
    import time

    vm_name = args.vm_name
    resource_group = args.resource_group

    print(f"Starting WAA Docker container on VM '{vm_name}'...")

    # Script to start the WAA Docker container
    # The winarena container runs Windows 11 via QEMU with WAA server inside
    start_script = '''
# Check if container exists
CONTAINER_ID=$(docker ps -aq -f name=winarena)
if [ -z "$CONTAINER_ID" ]; then
    echo "ERROR: No 'winarena' container found. Run setup-waa first."
    exit 1
fi

# Check if already running
RUNNING=$(docker ps -q -f name=winarena)
if [ -n "$RUNNING" ]; then
    echo "Container already running"
else
    echo "Starting container..."
    docker start winarena
fi

# Wait a moment and show status
sleep 3
docker ps -f name=winarena --format "ID: {{.ID}}, Status: {{.Status}}"
echo "Container started. Windows VM booting..."
echo "WAA server will be available once Windows boots (~5-10 min first time, ~2 min after)"
'''

    result = subprocess.run(
        [
            "az", "vm", "run-command", "invoke",
            "--resource-group", resource_group,
            "--name", vm_name,
            "--command-id", "RunShellScript",
            "--scripts", start_script,
        ],
        capture_output=True,
        text=True,
        timeout=180,
    )

    if result.returncode != 0:
        print(f"ERROR: Failed to start container: {result.stderr}")
        return 1

    # Parse output
    try:
        import json as json_module
        output = json_module.loads(result.stdout)
        message = output.get("value", [{}])[0].get("message", "")
        print(message)
    except Exception:
        print(result.stdout)

    # Get public IP for convenience
    ip_result = subprocess.run(
        [
            "az", "vm", "show",
            "--name", vm_name,
            "--resource-group", resource_group,
            "--show-details",
            "--query", "publicIps",
            "-o", "tsv",
        ],
        capture_output=True,
        text=True,
    )

    if ip_result.returncode == 0 and ip_result.stdout.strip():
        public_ip = ip_result.stdout.strip()
        print(f"\nServer URL: http://{public_ip}:5000")
        print(f"Probe with: uv run python -m openadapt_evals.benchmarks.cli probe --server http://{public_ip}:5000 --wait")

    return 0


def cmd_dashboard(args: argparse.Namespace) -> int:
    """Generate and display VM usage dashboard."""
    import subprocess
    from pathlib import Path

    vm_name = args.vm_name
    resource_group = args.resource_group
    workspace_name = args.workspace_name

    # Get the project root directory
    project_root = Path(__file__).parent.parent.parent

    # Run the refresh script
    refresh_script = project_root / "refresh_vm_dashboard.py"
    output_file = project_root / "VM_USAGE_DASHBOARD.md"

    if not refresh_script.exists():
        print(f"ERROR: Dashboard script not found at {refresh_script}")
        return 1

    print("Generating VM usage dashboard...")

    result = subprocess.run(
        [
            "python",
            str(refresh_script),
            "--vm-name", vm_name,
            "--resource-group", resource_group,
            "--workspace-name", workspace_name,
            "--output", str(output_file),
        ],
        capture_output=False,
    )

    if result.returncode != 0:
        print("ERROR: Failed to generate dashboard")
        return 1

    # Display the dashboard
    if not args.no_display:
        print("\n" + "=" * 70)
        print(output_file.read_text())
        print("=" * 70)

    # Open in browser if requested
    if args.open:
        import webbrowser
        # Convert to HTML for better browser viewing
        try:
            import markdown
            html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>VM Usage Dashboard</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
               max-width: 1200px; margin: 40px auto; padding: 0 20px; }}
        h1 {{ color: #0078d4; }}
        h2 {{ color: #106ebe; border-bottom: 2px solid #0078d4; padding-bottom: 5px; }}
        table {{ border-collapse: collapse; width: 100%; margin: 20px 0; }}
        th, td {{ border: 1px solid #ddd; padding: 12px; text-align: left; }}
        th {{ background-color: #0078d4; color: white; }}
        tr:nth-child(even) {{ background-color: #f2f2f2; }}
        code {{ background-color: #f4f4f4; padding: 2px 6px; border-radius: 3px; }}
        pre {{ background-color: #f4f4f4; padding: 15px; border-radius: 5px; overflow-x: auto; }}
        .status-running {{ color: #28a745; font-weight: bold; }}
        .status-stopped {{ color: #6c757d; font-weight: bold; }}
        .status-failed {{ color: #dc3545; font-weight: bold; }}
    </style>
</head>
<body>
{markdown.markdown(output_file.read_text(), extensions=['tables', 'fenced_code'])}
</body>
</html>
"""
            html_file = output_file.with_suffix(".html")
            html_file.write_text(html_content)
            webbrowser.open(f"file://{html_file.absolute()}")
            print(f"\nOpened dashboard in browser: {html_file}")
        except ImportError:
            print("\nNote: Install 'markdown' package for HTML viewing: pip install markdown")
            webbrowser.open(f"file://{output_file.absolute()}")

    return 0


def cmd_up(args: argparse.Namespace) -> int:
    """Start VM, wait for boot, start WAA server, and probe until ready."""
    import subprocess
    import time

    vm_name = args.vm_name
    resource_group = args.resource_group

    # Step 1: Start VM
    print(f"[1/4] Starting VM '{vm_name}'...")
    result = subprocess.run(
        ["az", "vm", "start", "--name", vm_name, "--resource-group", resource_group],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"ERROR: Failed to start VM: {result.stderr}")
        return 1
    print("      VM started.")

    # Step 2: Get public IP
    print("[2/4] Getting public IP...")
    result = subprocess.run(
        [
            "az", "vm", "show",
            "--name", vm_name,
            "--resource-group", resource_group,
            "--show-details",
            "--query", "publicIps",
            "-o", "tsv",
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        print(f"ERROR: Could not get public IP")
        return 1
    public_ip = result.stdout.strip()
    server_url = f"http://{public_ip}:5000"
    print(f"      Public IP: {public_ip}")

    # Step 3: Wait for VM to boot and start WAA Docker container
    print(f"[3/4] Waiting {args.boot_wait}s for VM to boot, then starting WAA container...")
    time.sleep(args.boot_wait)

    # WAA runs inside a Docker container with Windows nested virtualization
    start_script = '''
# Check if container exists
CONTAINER_ID=$(docker ps -aq -f name=winarena)
if [ -z "$CONTAINER_ID" ]; then
    echo "ERROR: No winarena container found"
    echo "This VM may need setup. See openadapt-ml vm setup-waa command."
    exit 1
fi

# Start container if not running
RUNNING=$(docker ps -q -f name=winarena)
if [ -z "$RUNNING" ]; then
    echo "Starting winarena container..."
    docker start winarena
fi

sleep 3
docker ps -f name=winarena --format "Container: {{.Names}}, Status: {{.Status}}"
'''

    result = subprocess.run(
        [
            "az", "vm", "run-command", "invoke",
            "--resource-group", resource_group,
            "--name", vm_name,
            "--command-id", "RunShellScript",
            "--scripts", start_script,
        ],
        capture_output=True,
        text=True,
        timeout=180,
    )
    if result.returncode != 0:
        print(f"WARNING: Server start command may have failed: {result.stderr}")
    else:
        print("      Server start command sent.")

    # Step 4: Probe until ready
    print(f"[4/4] Probing server at {server_url}...")

    try:
        import requests
    except ImportError:
        print("ERROR: requests package required")
        return 1

    for attempt in range(args.probe_attempts):
        try:
            resp = requests.get(f"{server_url}/probe", timeout=5.0)
            if resp.status_code == 200:
                print(f"\nSUCCESS: WAA server ready at {server_url}")
                print(f"\nRun evaluation with:")
                print(f"  uv run python -m openadapt_evals.benchmarks.cli live --server {server_url} --agent api-claude --task-ids notepad_1")
                return 0
        except Exception:
            pass
        print(f"      Attempt {attempt + 1}/{args.probe_attempts}: waiting...")
        time.sleep(args.probe_interval)

    print(f"\nWARNING: Server not responding after {args.probe_attempts} attempts.")
    print(f"Check server logs: az vm run-command invoke --resource-group {resource_group} --name {vm_name} --command-id RunShellScript --scripts 'cat /tmp/waa_server.log'")
    return 1


def cmd_azure(args: argparse.Namespace) -> int:
    """Run Azure-based parallel evaluation."""
    from openadapt_evals.benchmarks.azure import AzureConfig, AzureWAAOrchestrator
    from openadapt_evals.benchmarks import SmartMockAgent

    print("Setting up Azure evaluation...")

    try:
        config = AzureConfig.from_env()
    except ValueError as e:
        print(f"ERROR: {e}")
        print("\nSet these environment variables:")
        print("  AZURE_SUBSCRIPTION_ID")
        print("  AZURE_ML_RESOURCE_GROUP")
        print("  AZURE_ML_WORKSPACE_NAME")
        return 1

    if not args.waa_path:
        print("ERROR: --waa-path required (path to WAA repository)")
        return 1

    waa_path = Path(args.waa_path)
    if not waa_path.exists():
        print(f"ERROR: WAA repository not found at: {waa_path}")
        return 1

    orchestrator = AzureWAAOrchestrator(
        config=config,
        waa_repo_path=waa_path,
        experiment_name=args.experiment_name,
    )

    # Create agent
    agent = SmartMockAgent()

    # Parse task IDs if provided
    task_ids = None
    if args.task_ids:
        task_ids = args.task_ids.split(",")

    print(f"Starting evaluation with {args.workers} worker(s)...")

    try:
        results = orchestrator.run_evaluation(
            agent=agent,
            num_workers=args.workers,
            task_ids=task_ids,
            max_steps_per_task=args.max_steps,
            cleanup_on_complete=not args.no_cleanup,
            timeout_hours=args.timeout_hours,
        )

        # Report results
        success_count = sum(1 for r in results if r.success)
        print("\n" + "=" * 50)
        print("Azure Evaluation Complete")
        print("=" * 50)
        print(f"Tasks:        {len(results)}")
        print(f"Success rate: {success_count / len(results):.1%}")

        return 0

    except Exception as e:
        print(f"ERROR: Evaluation failed: {e}")
        return 1


def main() -> int:
    """Main entry point for CLI."""
    parser = argparse.ArgumentParser(
        description="Windows Agent Arena benchmark CLI",
        prog="python -m openadapt_evals.benchmarks.cli",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Mock evaluation
    mock_parser = subparsers.add_parser("mock", help="Run mock evaluation (no Windows VM)")
    mock_parser.add_argument("--tasks", type=int, default=10, help="Number of tasks")
    mock_parser.add_argument("--max-steps", type=int, default=15, help="Max steps per task")
    mock_parser.add_argument("--agent", type=str, default="mock",
                            help="Agent type: mock, api-claude, api-openai")
    mock_parser.add_argument("--demo", type=str, help="Demo trajectory file for ApiAgent")
    mock_parser.add_argument("--output", type=str, help="Output directory for traces")
    mock_parser.add_argument("--run-name", type=str, help="Name for this evaluation run")

    # Live evaluation
    live_parser = subparsers.add_parser("live", help="Run live evaluation against WAA server")
    live_parser.add_argument("--server", type=str, default="http://localhost:5000",
                            help="WAA server URL")
    live_parser.add_argument("--agent", type=str, default="mock",
                            help="Agent type: mock, api-claude, api-openai, retrieval-claude, retrieval-openai")
    live_parser.add_argument("--demo", type=str, help="Demo trajectory file for ApiAgent")
    live_parser.add_argument("--demo-library", type=str,
                            help="Path to demo library for retrieval agents")
    live_parser.add_argument("--task-ids", type=str, help="Comma-separated task IDs")
    live_parser.add_argument("--max-steps", type=int, default=15, help="Max steps per task")
    live_parser.add_argument("--output", type=str, help="Output directory for traces")
    live_parser.add_argument("--run-name", type=str, help="Name for this evaluation run")

    # Probe server
    probe_parser = subparsers.add_parser("probe", help="Check if WAA server is reachable")
    probe_parser.add_argument("--server", type=str, default="http://localhost:5000",
                             help="WAA server URL")
    probe_parser.add_argument("--wait", action="store_true",
                             help="Wait for server to become ready")
    probe_parser.add_argument("--wait-attempts", type=int, default=60,
                             help="Max attempts when waiting")
    probe_parser.add_argument("--wait-interval", type=int, default=5,
                             help="Seconds between attempts")

    # Generate viewer
    view_parser = subparsers.add_parser("view", help="Generate HTML viewer for results")
    view_parser.add_argument("--run-name", type=str, required=True,
                            help="Name of evaluation run")
    view_parser.add_argument("--benchmark-dir", type=str,
                            help="Benchmark results directory")
    view_parser.add_argument("--embed-screenshots", action="store_true",
                            help="Embed screenshots as base64")
    view_parser.add_argument("--no-open", action="store_true",
                            help="Don't auto-open browser")

    # Cost estimation
    estimate_parser = subparsers.add_parser("estimate", help="Estimate Azure costs")
    estimate_parser.add_argument("--tasks", type=int, default=154, help="Number of tasks")
    estimate_parser.add_argument("--workers", type=int, default=1, help="Number of workers")
    estimate_parser.add_argument("--task-duration", type=float, default=1.0,
                                help="Avg task duration (minutes)")
    estimate_parser.add_argument("--vm-cost", type=float, default=0.19,
                                help="VM hourly cost (USD)")

    # Azure evaluation
    azure_parser = subparsers.add_parser("azure", help="Run Azure-based parallel evaluation")
    azure_parser.add_argument("--waa-path", type=str, required=True,
                             help="Path to WAA repository")
    azure_parser.add_argument("--workers", type=int, default=1,
                             help="Number of parallel workers")
    azure_parser.add_argument("--task-ids", type=str, help="Comma-separated task IDs")
    azure_parser.add_argument("--max-steps", type=int, default=15, help="Max steps per task")
    azure_parser.add_argument("--experiment-name", type=str, default="waa-eval",
                             help="Experiment name prefix")
    azure_parser.add_argument("--timeout-hours", type=float, default=4.0,
                             help="Job timeout in hours")
    azure_parser.add_argument("--no-cleanup", action="store_true",
                             help="Don't delete VMs after completion")

    # VM management commands
    vm_start_parser = subparsers.add_parser("vm-start", help="Start an Azure VM")
    vm_start_parser.add_argument("--vm-name", type=str, default="waa-eval-vm",
                                help="Azure VM name")
    vm_start_parser.add_argument("--resource-group", type=str, default="OPENADAPT-AGENTS",
                                help="Azure resource group")

    vm_stop_parser = subparsers.add_parser("vm-stop", help="Stop (deallocate) an Azure VM")
    vm_stop_parser.add_argument("--vm-name", type=str, default="waa-eval-vm",
                               help="Azure VM name")
    vm_stop_parser.add_argument("--resource-group", type=str, default="OPENADAPT-AGENTS",
                               help="Azure resource group")
    vm_stop_parser.add_argument("--no-wait", action="store_true",
                               help="Don't wait for deallocation to complete")

    vm_status_parser = subparsers.add_parser("vm-status", help="Check Azure VM status")
    vm_status_parser.add_argument("--vm-name", type=str, default="waa-eval-vm",
                                 help="Azure VM name")
    vm_status_parser.add_argument("--resource-group", type=str, default="OPENADAPT-AGENTS",
                                 help="Azure resource group")
    vm_status_parser.add_argument("--json", action="store_true",
                                 help="Output raw JSON")

    server_start_parser = subparsers.add_parser("server-start", help="Start WAA server on VM")
    server_start_parser.add_argument("--vm-name", type=str, default="waa-eval-vm",
                                    help="Azure VM name")
    server_start_parser.add_argument("--resource-group", type=str, default="OPENADAPT-AGENTS",
                                    help="Azure resource group")

    up_parser = subparsers.add_parser("up", help="Start VM + WAA server (all-in-one)")
    up_parser.add_argument("--vm-name", type=str, default="waa-eval-vm",
                          help="Azure VM name")
    up_parser.add_argument("--resource-group", type=str, default="OPENADAPT-AGENTS",
                          help="Azure resource group")
    up_parser.add_argument("--boot-wait", type=int, default=30,
                          help="Seconds to wait for VM to boot")
    up_parser.add_argument("--probe-attempts", type=int, default=30,
                          help="Max probe attempts")
    up_parser.add_argument("--probe-interval", type=int, default=5,
                          help="Seconds between probe attempts")

    dashboard_parser = subparsers.add_parser("dashboard", help="Generate VM usage dashboard")
    dashboard_parser.add_argument("--vm-name", type=str, default="waa-eval-vm",
                                 help="Azure VM name")
    dashboard_parser.add_argument("--resource-group", type=str, default="openadapt-agents",
                                 help="Azure resource group")
    dashboard_parser.add_argument("--workspace-name", type=str, default="openadapt-ml",
                                 help="Azure ML workspace name")
    dashboard_parser.add_argument("--no-display", action="store_true",
                                 help="Don't display dashboard in terminal")
    dashboard_parser.add_argument("--open", action="store_true",
                                 help="Open dashboard in browser")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return 1

    # Dispatch to command handler
    handlers = {
        "mock": cmd_mock,
        "live": cmd_live,
        "probe": cmd_probe,
        "view": cmd_view,
        "estimate": cmd_estimate,
        "azure": cmd_azure,
        "vm-start": cmd_vm_start,
        "vm-stop": cmd_vm_stop,
        "vm-status": cmd_vm_status,
        "server-start": cmd_server_start,
        "up": cmd_up,
        "dashboard": cmd_dashboard,
    }

    handler = handlers.get(args.command)
    if handler:
        return handler(args)
    else:
        print(f"Unknown command: {args.command}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
