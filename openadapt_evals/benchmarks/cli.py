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
import os
import subprocess
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def _resolve_vm_context(args: argparse.Namespace) -> tuple[str, str] | None:
    """Resolve VM name/resource group from args, env, or Azure CLI tags.

    Resolution order:
    1) CLI args
    2) Environment variables
    3) Azure CLI: running VM tagged openadapt-role=waa
    """
    vm_name = (
        getattr(args, "vm_name", None)
        or os.getenv("AZURE_WAA_VM_NAME")
        or os.getenv("AZURE_VM_NAME")
    )
    resource_group = (
        getattr(args, "resource_group", None)
        or os.getenv("AZURE_ML_RESOURCE_GROUP")
        or os.getenv("AZURE_RESOURCE_GROUP")
    )

    if vm_name and resource_group:
        return vm_name, resource_group

    # If only vm name is provided, try to resolve resource group.
    if vm_name and not resource_group:
        try:
            result = subprocess.run(
                [
                    "az",
                    "vm",
                    "list",
                    "--query",
                    f"[?name=='{vm_name}'].resourceGroup | [0]",
                    "-o",
                    "tsv",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode == 0 and result.stdout.strip():
                return vm_name, result.stdout.strip()
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None

    # Prefer tagged running VM, but fall back to any tagged VM.
    queries = [
        (
            "[?tags.\"openadapt-role\"=='waa' && powerState=='VM running']."
            "{name:name, rg:resourceGroup, tags:tags, status:powerState}"
        ),
        (
            "[?tags.\"openadapt-role\"=='waa']."
            "{name:name, rg:resourceGroup, tags:tags, status:powerState}"
        ),
    ]

    vms = []
    for query in queries:
        try:
            result = subprocess.run(
                [
                    "az",
                    "vm",
                    "list",
                    "--show-details",
                    "--query",
                    query,
                    "-o",
                    "json",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired):
            return None

        if result.returncode != 0:
            continue

        try:
            vms = json.loads(result.stdout)
        except json.JSONDecodeError:
            continue

        if vms:
            break

    if not vms:
        return None

    if len(vms) > 1:
        print("WARNING: Multiple tagged WAA VMs found. Using the first:")
        for vm in vms:
            status = vm.get("status") or "unknown"
            print(f"  - {vm.get('name')} ({vm.get('rg')}) [{status}]")

    vm = vms[0]
    name = vm.get("name")
    rg = vm.get("rg")
    if not name or not rg:
        return None
    return name, rg


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
    from openadapt_evals.agents.scripted_agent import ScriptedAgent
    from openadapt_evals.adapters.base import BenchmarkAction
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
    elif agent_type in ("noop", "done"):
        # Minimal smoke-test agent: immediately returns DONE.
        # This is useful for validating end-to-end connectivity + /evaluate plumbing
        # without requiring API keys.
        agent = ScriptedAgent([BenchmarkAction(type="done")])
        print("Using ScriptedAgent (noop): immediate DONE")
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
        print(
            "Available: mock, noop, api-claude, api-openai, retrieval-claude, retrieval-openai"
        )
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


def cmd_smoke_live(args: argparse.Namespace) -> int:
    """One-command live smoke test.

    Starts the tagged WAA VM (or specified vm-name/resource-group), starts the
    existing 'winarena' container, patches /evaluate, probes until ready, runs a
    single live task, then deallocates the VM by default.

    This is intended to validate "end-to-end" wiring (VM -> server -> adapter ->
    runner -> /evaluate) without requiring any API keys.
    """
    import base64
    import time
    from pathlib import Path

    from openadapt_evals.adapters import WAALiveAdapter, WAALiveConfig
    from openadapt_evals.adapters.base import BenchmarkAction
    from openadapt_evals.agents.scripted_agent import ScriptedAgent
    from openadapt_evals.benchmarks import EvaluationConfig, compute_metrics, evaluate_agent_on_benchmark

    vm_context = _resolve_vm_context(args)
    if not vm_context:
        print("ERROR: Unable to resolve VM name/resource group.")
        print("Set --vm-name/--resource-group or tag VM with openadapt-role=waa.")
        print("Example: az vm update -g <rg> -n <vm> --set tags.openadapt-role=waa")
        return 1
    vm_name, resource_group = vm_context

    def _run(cmd: list[str], *, timeout: int | None = None) -> subprocess.CompletedProcess:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)

    def patch_evaluate_endpoint() -> bool:
        eval_path = Path(__file__).resolve().parents[1] / "server" / "evaluate_endpoint.py"
        if not eval_path.exists():
            print(f"WARNING: evaluate_endpoint.py not found at {eval_path}")
            return False

        payload = base64.b64encode(eval_path.read_bytes()).decode("ascii")
        patch_script = f'''
set -e
CONTAINER_ID=$(docker ps -aq -f name=winarena)
if [ -z "$CONTAINER_ID" ]; then
    echo "ERROR: No winarena container found"
    exit 1
fi

TMPFILE=$(mktemp)
echo "{payload}" | base64 -d > "$TMPFILE"

docker cp "$TMPFILE" winarena:/home/azureuser/WindowsAgentArena/src/win-arena-container/vm/setup/server/evaluate_endpoint.py
rm -f "$TMPFILE"

docker exec winarena python - <<'PY'
from pathlib import Path

main_path = Path("/home/azureuser/WindowsAgentArena/src/win-arena-container/vm/setup/server/main.py")
marker = "# openadapt-evals: /evaluate endpoint"
content = main_path.read_text()

if marker not in content:
    patch_block = (
        "\n\n"
        "# openadapt-evals: /evaluate endpoint\n"
        "try:\n"
        "    from evaluate_endpoint import create_evaluate_blueprint\n"
        "    evaluate_bp = create_evaluate_blueprint()\n"
        "    app.register_blueprint(evaluate_bp)\n"
        "except Exception as exc:\n"
        "    print(f\"WAA /evaluate endpoint disabled: {{exc}}\")\n"
    )
    if "if __name__ == \"__main__\":" in content:
        parts = content.split("if __name__ == \"__main__\":", 1)
        content = parts[0] + patch_block + "\nif __name__ == \"__main__\":" + parts[1]
    else:
        content += patch_block
    main_path.write_text(content)

print("/evaluate endpoint patched")
PY
'''

        try:
            result = _run(
            [
                "az",
                "vm",
                "run-command",
                "invoke",
                "--resource-group",
                resource_group,
                "--name",
                vm_name,
                "--command-id",
                "RunShellScript",
                "--scripts",
                patch_script,
            ],
            timeout=900,
            )
        except subprocess.TimeoutExpired:
            print("WARNING: /evaluate patch timed out (az vm run-command).")
            return False

        if result.returncode != 0:
            print(f"WARNING: /evaluate patch failed: {result.stderr.strip()}")
            return False
        return True

    server_url: str | None = None
    try:
        print(f"[1/6] Starting VM '{vm_name}'...")
        result = _run(["az", "vm", "start", "--name", vm_name, "--resource-group", resource_group])
        if result.returncode != 0:
            print(f"ERROR: Failed to start VM: {result.stderr.strip()}")
            return 1

        print("[2/6] Getting public IP...")
        result = _run(
            [
                "az",
                "vm",
                "show",
                "--name",
                vm_name,
                "--resource-group",
                resource_group,
                "--show-details",
                "--query",
                "publicIps",
                "-o",
                "tsv",
            ]
        )
        if result.returncode != 0 or not result.stdout.strip():
            print("ERROR: Could not get public IP")
            return 1

        public_ip = result.stdout.strip()
        server_url = f"http://{public_ip}:5000"
        print(f"      Server URL: {server_url}")

        print(f"[3/6] Waiting {args.boot_wait}s then starting winarena container...")
        time.sleep(args.boot_wait)

        start_script = '''
set -e
CONTAINER_ID=$(docker ps -aq -f name=winarena)
if [ -z "$CONTAINER_ID" ]; then
    echo "ERROR: No winarena container found"
    exit 1
fi

RUNNING=$(docker ps -q -f name=winarena)
if [ -z "$RUNNING" ]; then
    echo "Starting winarena container (async)..."
    nohup docker start winarena >/tmp/winarena_start.log 2>&1 &
    disown || true
    echo "Started docker start in background; see /tmp/winarena_start.log"
fi

sleep 3
docker ps -f name=winarena --format "Container: {{.Names}}, Status: {{.Status}}"
'''

        try:
            result = _run(
            [
                "az",
                "vm",
                "run-command",
                "invoke",
                "--resource-group",
                resource_group,
                "--name",
                vm_name,
                "--command-id",
                "RunShellScript",
                "--scripts",
                start_script,
            ],
            timeout=900,
            )
        except subprocess.TimeoutExpired:
            print("ERROR: Timed out while starting winarena container (az vm run-command).")
            return 1
        if result.returncode != 0:
            print(f"ERROR: Failed to start container: {result.stderr.strip()}")
            return 1

        print("[4/6] Patching /evaluate endpoint...")
        patch_evaluate_endpoint()

        print(f"[5/6] Probing server at {server_url}...")
        try:
            import requests
        except ImportError:
            print("ERROR: requests package required")
            return 1

        ready = False
        for attempt in range(args.probe_attempts):
            try:
                resp = requests.get(f"{server_url}/probe", timeout=5.0)
                if resp.status_code == 200:
                    ready = True
                    break
            except Exception:
                pass
            time.sleep(args.probe_interval)
            print(f"      Attempt {attempt + 1}/{args.probe_attempts}: waiting...")

        if not ready:
            print("ERROR: WAA server not reachable after probing")
            return 1

        # Optional /evaluate health check
        try:
            eval_resp = requests.get(f"{server_url}/evaluate/health", timeout=5.0)
            if eval_resp.status_code == 200:
                print("      /evaluate endpoint: ready")
            else:
                print(f"      WARNING: /evaluate endpoint health returned {eval_resp.status_code}")
        except Exception:
            print("      WARNING: /evaluate endpoint health check failed")

        print("[6/6] Running single-task live evaluation...")

        agent = ScriptedAgent([BenchmarkAction(type="done")])
        adapter = WAALiveAdapter(WAALiveConfig(server_url=server_url, max_steps=args.max_steps))

        eval_config = EvaluationConfig(
            max_steps=args.max_steps,
            save_execution_traces=args.save_traces,
            enable_live_tracking=False,
            output_dir=args.output,
            run_name=args.run_name,
            model_id="noop",
        )
        results = evaluate_agent_on_benchmark(
            agent=agent,
            adapter=adapter,
            task_ids=[args.task_id],
            max_steps=args.max_steps,
            config=eval_config,
        )

        metrics = compute_metrics(results)
        print("\n" + "=" * 50)
        print("Smoke Live Results")
        print("=" * 50)
        print(f"Tasks:        {metrics['num_tasks']}")
        print(f"Success rate: {metrics['success_rate']:.1%}")
        print(f"Avg score:    {metrics['avg_score']:.3f}")
        print(f"Avg steps:    {metrics['avg_steps']:.1f}")

        return 0

    finally:
        if args.stop_vm:
            print(f"\nStopping VM '{vm_name}' (deallocate)...")
            _run(["az", "vm", "deallocate", "--name", vm_name, "--resource-group", resource_group])
            print("VM deallocate requested.")


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
    vm_context = _resolve_vm_context(args)
    if not vm_context:
        print("ERROR: Unable to resolve VM name/resource group.")
        print("Set --vm-name/--resource-group or tag VM with openadapt-role=waa.")
        print("Example: az vm update -g <rg> -n <vm> --set tags.openadapt-role=waa")
        return 1
    vm_name, resource_group = vm_context

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
    vm_context = _resolve_vm_context(args)
    if not vm_context:
        print("ERROR: Unable to resolve VM name/resource group.")
        print("Set --vm-name/--resource-group or tag VM with openadapt-role=waa.")
        print("Example: az vm update -g <rg> -n <vm> --set tags.openadapt-role=waa")
        return 1
    vm_name, resource_group = vm_context

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
    import json as json_module

    vm_context = _resolve_vm_context(args)
    if not vm_context:
        print("ERROR: Unable to resolve VM name/resource group.")
        print("Set --vm-name/--resource-group or tag VM with openadapt-role=waa.")
        print("Example: az vm update -g <rg> -n <vm> --set tags.openadapt-role=waa")
        return 1
    vm_name, resource_group = vm_context

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


def cmd_vm_debug(args: argparse.Namespace) -> int:
    """Run non-blocking diagnostics on the Azure VM.

    This is designed to be safe to run even when docker is wedged: each command
    is wrapped with a short timeout so `az vm run-command` returns.
    """
    vm_context = _resolve_vm_context(args)
    if not vm_context:
        print("ERROR: Unable to resolve VM name/resource group.")
        print("Set --vm-name/--resource-group or tag VM with openadapt-role=waa.")
        return 1
    vm_name, resource_group = vm_context

    print(f"Running VM diagnostics on '{vm_name}'...")

    diag_script = r'''
set -u

run() {
  title="$1"
  shift
  echo ""
  echo "===== ${title} ====="
  # Ensure we never hang.
  timeout 20 bash -lc "$*" 2>&1 || echo "(command failed or timed out: $*)"
}

run "TIME" "date"
run "KERNEL" "uname -a"
run "UPTIME" "uptime || true"
run "DISK" "df -h || true"
run "MEM" "free -h || true"
run "DOCKER VERSION" "docker --version || true"
run "DOCKER INFO" "docker info --format '{{json .}}' | head -c 4000 || docker info || true"
run "DOCKER PS" "docker ps -a --no-trunc || true"
run "DOCKER IMAGES" "docker images --digests | head -n 50 || true"
run "WINARENA INSPECT" "docker inspect winarena --format '{{.Name}} {{.State.Status}} {{.State.Running}} {{.State.Error}}' || true"
run "WINARENA LOGS" "docker logs --tail 200 winarena || true"
run "DOCKER SERVICE" "systemctl status docker --no-pager || true"
run "DOCKER JOURNAL" "journalctl -u docker -n 200 --no-pager || true"
run "WINARENA START LOG" "tail -n 200 /tmp/winarena_start.log 2>/dev/null || true"
'''

    try:
        result = subprocess.run(
            [
                "az",
                "vm",
                "run-command",
                "invoke",
                "--resource-group",
                resource_group,
                "--name",
                vm_name,
                "--command-id",
                "RunShellScript",
                "--scripts",
                diag_script,
            ],
            capture_output=True,
            text=True,
            timeout=900,
        )
    except subprocess.TimeoutExpired:
        print("ERROR: vm-debug timed out (az vm run-command).")
        return 1

    if result.returncode != 0:
        print(f"ERROR: vm-debug failed: {result.stderr.strip()}")
        return 1

    # Azure returns JSON; print raw output for now.
    print(result.stdout)
    return 0


def cmd_server_start(args: argparse.Namespace) -> int:
    """Start WAA server on the Azure VM via run-command.

    WAA runs inside a Docker container with Windows nested virtualization.
    This command starts the existing 'winarena' container.
    """
    import time

    vm_context = _resolve_vm_context(args)
    if not vm_context:
        print("ERROR: Unable to resolve VM name/resource group.")
        print("Set --vm-name/--resource-group or tag VM with openadapt-role=waa.")
        print("Example: az vm update -g <rg> -n <vm> --set tags.openadapt-role=waa")
        return 1
    vm_name, resource_group = vm_context

    print(f"Starting WAA Docker container on VM '{vm_name}'...")

    # Script to start the WAA Docker container.
    # IMPORTANT: do not block on `docker start` inside run-command.
    # If docker/image is unhealthy, it can hang and the run-command call will time out.
    start_script = '''
 set -e
 
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
     echo "Starting container (async)..."
     nohup docker start winarena >/tmp/winarena_start.log 2>&1 &
     disown || true
     echo "Started docker start in background; see /tmp/winarena_start.log"
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
        timeout=900,
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


def cmd_vnc(args: argparse.Namespace) -> int:
    """Start an SSH tunnel for VNC access."""
    import socket

    vm_context = _resolve_vm_context(args)
    if not vm_context:
        print("ERROR: Unable to resolve VM name/resource group.")
        print("Set --vm-name/--resource-group or tag VM with openadapt-role=waa.")
        print("Example: az vm update -g <rg> -n <vm> --set tags.openadapt-role=waa")
        return 1
    vm_name, resource_group = vm_context

    ip_result = subprocess.run(
        [
            "az",
            "vm",
            "show",
            "--name",
            vm_name,
            "--resource-group",
            resource_group,
            "--show-details",
            "--query",
            "publicIps",
            "-o",
            "tsv",
        ],
        capture_output=True,
        text=True,
    )
    if ip_result.returncode != 0 or not ip_result.stdout.strip():
        print("ERROR: Could not get VM public IP")
        return 1
    public_ip = ip_result.stdout.strip()

    tunnel_cmd = [
        "ssh",
        "-f",
        "-N",
        "-L",
        f"{args.local_port}:127.0.0.1:{args.remote_port}",
        f"azureuser@{public_ip}",
        "-o",
        "ExitOnForwardFailure=yes",
        "-o",
        "StrictHostKeyChecking=no",
        "-o",
        "UserKnownHostsFile=/dev/null",
    ]

    result = subprocess.run(tunnel_cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"ERROR: SSH tunnel failed: {result.stderr.strip()}")
        return 1

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(2)
        if sock.connect_ex(("localhost", args.local_port)) == 0:
            print(f"VNC tunnel ready: http://localhost:{args.local_port}")
            return 0

    print("WARNING: Tunnel started but local port is not reachable yet.")
    print(f"Try: http://localhost:{args.local_port}")
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
    import time
    import base64
    from pathlib import Path

    vm_context = _resolve_vm_context(args)
    if not vm_context:
        print("ERROR: Unable to resolve VM name/resource group.")
        print("Set --vm-name/--resource-group or tag VM with openadapt-role=waa.")
        print("Example: az vm update -g <rg> -n <vm> --set tags.openadapt-role=waa")
        return 1
    vm_name, resource_group = vm_context

    def patch_evaluate_endpoint() -> bool:
        """Patch WAA server to add /evaluate endpoint on VM."""
        eval_path = Path(__file__).resolve().parents[1] / "server" / "evaluate_endpoint.py"
        if not eval_path.exists():
            print(f"WARNING: evaluate_endpoint.py not found at {eval_path}")
            return False

        payload = base64.b64encode(eval_path.read_bytes()).decode("ascii")
        patch_script = f'''
set -e
CONTAINER_ID=$(docker ps -aq -f name=winarena)
if [ -z "$CONTAINER_ID" ]; then
    echo "ERROR: No winarena container found"
    exit 1
fi

TMPFILE=$(mktemp)
echo "{payload}" | base64 -d > "$TMPFILE"

docker cp "$TMPFILE" winarena:/home/azureuser/WindowsAgentArena/src/win-arena-container/vm/setup/server/evaluate_endpoint.py
rm -f "$TMPFILE"

docker exec winarena python - <<'PY'
from pathlib import Path

main_path = Path("/home/azureuser/WindowsAgentArena/src/win-arena-container/vm/setup/server/main.py")
marker = "# openadapt-evals: /evaluate endpoint"
content = main_path.read_text()

if marker not in content:
    patch_block = (
        "\n\n"
        "# openadapt-evals: /evaluate endpoint\n"
        "try:\n"
        "    from evaluate_endpoint import create_evaluate_blueprint\n"
        "    evaluate_bp = create_evaluate_blueprint()\n"
        "    app.register_blueprint(evaluate_bp)\n"
        "except Exception as exc:\n"
        "    print(f\"WAA /evaluate endpoint disabled: {{exc}}\")\n"
    )
    if "if __name__ == \"__main__\":" in content:
        parts = content.split("if __name__ == \"__main__\":", 1)
        content = parts[0] + patch_block + "\nif __name__ == \"__main__\":" + parts[1]
    else:
        content += patch_block
    main_path.write_text(content)

print("/evaluate endpoint patched")
PY
'''

        result = subprocess.run(
            [
                "az",
                "vm",
                "run-command",
                "invoke",
                "--resource-group",
                resource_group,
                "--name",
                vm_name,
                "--command-id",
                "RunShellScript",
                "--scripts",
                patch_script,
            ],
            capture_output=True,
            text=True,
            timeout=900,
        )
        if result.returncode != 0:
            print(f"WARNING: /evaluate patch failed: {result.stderr}")
            return False
        return True

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
     echo "Starting winarena container (async)..."
     nohup docker start winarena >/tmp/winarena_start.log 2>&1 &
     disown || true
     echo "Started docker start in background; see /tmp/winarena_start.log"
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
        timeout=900,
    )
    if result.returncode != 0:
        print(f"WARNING: Server start command may have failed: {result.stderr}")
    else:
        print("      Server start command sent.")

    print("[4/5] Patching WAA server to enable /evaluate endpoint...")
    patch_evaluate_endpoint()

    # Step 5: Probe until ready
    print(f"[5/5] Probing server at {server_url}...")

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
                try:
                    eval_resp = requests.get(f"{server_url}/evaluate/health", timeout=5.0)
                    if eval_resp.status_code == 200:
                        print("      /evaluate endpoint: ready")
                    else:
                        print("      WARNING: /evaluate endpoint not available")
                        print("      Run: python scripts/patch_waa_evaluate.py --waa-path /path/to/WindowsAgentArena")
                except Exception:
                    print("      WARNING: /evaluate endpoint health check failed")
                print("\nRun a no-API-key smoke test with:")
                print(
                    f"  uv run python -m openadapt_evals.benchmarks.cli live --server {server_url} --agent noop --task-ids notepad_1"
                )
                print("\nOr fully automated (starts + tests + deallocates):")
                print("  uv run python -m openadapt_evals.benchmarks.cli smoke-live --task-id notepad_1")
                return 0
        except Exception:
            pass
        print(f"      Attempt {attempt + 1}/{args.probe_attempts}: waiting...")
        time.sleep(args.probe_interval)

    print(f"\nWARNING: Server not responding after {args.probe_attempts} attempts.")
    print(f"Check server logs: az vm run-command invoke --resource-group {resource_group} --name {vm_name} --command-id RunShellScript --scripts 'cat /tmp/waa_server.log'")
    return 1


def cmd_wandb_demo(args: argparse.Namespace) -> int:
    """Populate wandb with synthetic evaluation data for demo."""
    try:
        from openadapt_evals.integrations.demo_wandb import main as demo_main
    except ImportError as e:
        print(f"ERROR: wandb integration not available: {e}")
        print("Install with: pip install openadapt-evals[wandb]")
        return 1

    # Override sys.argv to pass our args to the demo script
    import sys
    old_argv = sys.argv
    new_argv = ["demo_wandb", "--project", args.project]

    if args.entity:
        new_argv.extend(["--entity", args.entity])
    if args.scenarios:
        new_argv.extend(["--scenarios"] + args.scenarios)
    if args.num_tasks:
        new_argv.extend(["--num-tasks", str(args.num_tasks)])
    if args.seed:
        new_argv.extend(["--seed", str(args.seed)])
    if args.dry_run:
        new_argv.append("--dry-run")

    sys.argv = new_argv
    try:
        demo_main()
        return 0
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 1
    finally:
        sys.argv = old_argv


def cmd_wandb_report(args: argparse.Namespace) -> int:
    """Generate a wandb report from benchmark results."""
    try:
        from openadapt_evals.integrations.wandb_reports import (
            WandbReportGenerator,
            generate_demo_report,
        )
    except ImportError as e:
        print(f"ERROR: wandb reports API not available: {e}")
        print("Install with: pip install openadapt-evals[wandb]")
        return 1

    try:
        generator = WandbReportGenerator(
            project=args.project,
            entity=args.entity,
        )
    except ValueError as e:
        print(f"ERROR: {e}")
        return 1

    try:
        if args.demo:
            # Generate demo report for synthetic scenarios
            print("Generating demo report for synthetic scenarios...")
            report_url = generator.create_scenario_report(
                title="OpenAdapt Evals Demo - Synthetic Scenarios",
            )
        elif args.compare and args.model_ids:
            # Generate model comparison report
            model_ids = args.model_ids.split(",")
            print(f"Generating comparison report for models: {model_ids}")
            report_url = generator.create_comparison_report(
                model_ids=model_ids,
                title=args.title,
            )
        else:
            # Generate standard benchmark report
            run_ids = args.run_ids.split(",") if args.run_ids else None
            include_charts = args.charts.split(",") if args.charts else None

            print("Generating benchmark report...")
            report_url = generator.create_benchmark_report(
                run_ids=run_ids,
                title=args.title,
                description=args.description,
                include_charts=include_charts,
            )

        print(f"\nReport created: {report_url}")
        return 0

    except Exception as e:
        print(f"ERROR: Failed to create report: {e}")
        import traceback
        traceback.print_exc()
        return 1


def cmd_wandb_log(args: argparse.Namespace) -> int:
    """Log existing benchmark results to wandb."""
    from pathlib import Path

    try:
        from openadapt_evals.integrations.wandb_logger import WandbLogger, load_results_from_summary
    except ImportError as e:
        print(f"ERROR: wandb integration not available: {e}")
        print("Install with: pip install openadapt-evals[wandb]")
        return 1

    benchmark_dir = Path(args.benchmark_dir or "benchmark_results") / args.run_name

    if not benchmark_dir.exists():
        print(f"ERROR: Benchmark directory not found: {benchmark_dir}")
        return 1

    summary_path = benchmark_dir / "summary.json"
    if not summary_path.exists():
        print(f"ERROR: summary.json not found in {benchmark_dir}")
        return 1

    print(f"Loading results from: {summary_path}")
    results = load_results_from_summary(summary_path)
    print(f"Loaded {len(results)} task results")

    # Load metadata
    metadata_path = benchmark_dir / "metadata.json"
    config = {}
    if metadata_path.exists():
        import json
        with open(metadata_path) as f:
            config = json.load(f)

    # Override with CLI args
    if args.model_id:
        config["model_id"] = args.model_id

    wandb_logger = WandbLogger(
        project=args.project,
        entity=args.entity,
        config=config,
        tags=args.tags.split(",") if args.tags else None,
        name=args.wandb_run_name or args.run_name,
        mode="disabled" if args.dry_run else "online",
    )

    try:
        wandb_logger.init()
        wandb_logger.log_results(results)

        # Upload artifacts if requested
        if args.include_artifacts:
            print("Uploading artifacts...")
            wandb_logger.log_benchmark_dir(
                benchmark_dir,
                include_screenshots=not args.no_screenshots,
            )

        print(f"\nResults logged to: {wandb_logger._run.url}")
        return 0
    except Exception as e:
        print(f"ERROR: {e}")
        return 1
    finally:
        wandb_logger.finish()


def cmd_azure_monitor(args: argparse.Namespace) -> int:
    """Monitor an existing Azure ML job with live tracking."""
    from openadapt_evals.benchmarks.azure import AzureConfig, AzureWAAOrchestrator

    print(f"Monitoring Azure ML job: {args.job_name}")

    try:
        config = AzureConfig.from_env()
    except ValueError as e:
        print(f"ERROR: {e}")
        print("\nSet these environment variables:")
        print("  AZURE_SUBSCRIPTION_ID")
        print("  AZURE_ML_RESOURCE_GROUP")
        print("  AZURE_ML_WORKSPACE_NAME")
        return 1

    # Use a dummy WAA path since we're not running evaluation
    orchestrator = AzureWAAOrchestrator(
        config=config,
        waa_repo_path=Path("/tmp/dummy"),
        experiment_name="monitor",
    )

    try:
        orchestrator.monitor_job(
            job_name=args.job_name,
            live_tracking_file=args.output,
        )
        print(f"\nMonitoring complete. Live data written to: {args.output}")
        return 0
    except KeyboardInterrupt:
        print("\n\nMonitoring interrupted by user.")
        return 130
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
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

    # Determine WAA path (required unless cleanup-only)
    waa_path = None
    if args.cleanup_only:
        # For cleanup-only, we don't need WAA repo
        # Just use a dummy path
        waa_path = Path("/tmp/dummy")
    else:
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

    # Handle cleanup-only mode
    if args.cleanup_only:
        print("Cleanup-only mode: scanning for stale compute instances...")
        prefix = getattr(args, "cleanup_prefix", "waa")
        dry_run = getattr(args, "dry_run", False)

        if dry_run:
            print("DRY-RUN MODE: Will list instances without deleting.")

        stale_count = orchestrator.cleanup_stale_instances(prefix=prefix, dry_run=dry_run)

        if stale_count == 0:
            print("\nNo stale instances found.")
        elif dry_run:
            print(f"\nFound {stale_count} stale instance(s). Run without --dry-run to delete.")
        else:
            print(f"\nSuccessfully cleaned up {stale_count} stale instance(s).")

        return 0

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
            cleanup_stale_on_start=not args.skip_cleanup_stale,
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

    except KeyboardInterrupt:
        print("\n\nEvaluation interrupted by user.")
        return 130  # Standard exit code for SIGINT

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
                            help="Agent type: mock, noop, api-claude, api-openai, retrieval-claude, retrieval-openai")
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
    azure_parser.add_argument("--waa-path", type=str,
                             help="Path to WAA repository (not needed for --cleanup-only)")
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
    azure_parser.add_argument("--skip-cleanup-stale", action="store_true",
                             help="Skip cleanup of stale instances before starting (not recommended)")
    azure_parser.add_argument("--cleanup-only", action="store_true",
                             help="Only cleanup stale instances, don't run evaluation")
    azure_parser.add_argument("--cleanup-prefix", type=str, default="waa",
                             help="Prefix filter for cleanup (default: 'waa')")
    azure_parser.add_argument("--dry-run", action="store_true",
                             help="List instances without deleting (for --cleanup-only)")

    # VM management commands
    vm_start_parser = subparsers.add_parser("vm-start", help="Start an Azure VM")
    vm_start_parser.add_argument("--vm-name", type=str, default=None,
                                help="Azure VM name (optional if tagged)")
    vm_start_parser.add_argument("--resource-group", type=str, default=None,
                                help="Azure resource group (optional if tagged)")

    vm_stop_parser = subparsers.add_parser("vm-stop", help="Stop (deallocate) an Azure VM")
    vm_stop_parser.add_argument("--vm-name", type=str, default=None,
                               help="Azure VM name (optional if tagged)")
    vm_stop_parser.add_argument("--resource-group", type=str, default=None,
                               help="Azure resource group (optional if tagged)")
    vm_stop_parser.add_argument("--no-wait", action="store_true",
                               help="Don't wait for deallocation to complete")

    vm_status_parser = subparsers.add_parser("vm-status", help="Check Azure VM status")
    vm_status_parser.add_argument("--vm-name", type=str, default=None,
                                 help="Azure VM name (optional if tagged)")
    vm_status_parser.add_argument("--resource-group", type=str, default=None,
                                 help="Azure resource group (optional if tagged)")
    vm_status_parser.add_argument("--json", action="store_true",
                                 help="Output raw JSON")

    vm_debug_parser = subparsers.add_parser("vm-debug", help="Run diagnostic commands on Azure VM")
    vm_debug_parser.add_argument("--vm-name", type=str, default=None,
                                 help="Azure VM name (optional if tagged)")
    vm_debug_parser.add_argument("--resource-group", type=str, default=None,
                                 help="Azure resource group (optional if tagged)")

    server_start_parser = subparsers.add_parser("server-start", help="Start WAA server on VM")
    server_start_parser.add_argument("--vm-name", type=str, default=None,
                                    help="Azure VM name (optional if tagged)")
    server_start_parser.add_argument("--resource-group", type=str, default=None,
                                    help="Azure resource group (optional if tagged)")

    vnc_parser = subparsers.add_parser("vnc", help="Open VNC tunnel to WAA VM")
    vnc_parser.add_argument("--vm-name", type=str, default=None,
                           help="Azure VM name (optional if tagged)")
    vnc_parser.add_argument("--resource-group", type=str, default=None,
                           help="Azure resource group (optional if tagged)")
    vnc_parser.add_argument("--local-port", type=int, default=8006,
                           help="Local port for VNC tunnel")
    vnc_parser.add_argument("--remote-port", type=int, default=8006,
                           help="Remote VNC port on VM")

    up_parser = subparsers.add_parser("up", help="Start VM + WAA server (all-in-one)")
    up_parser.add_argument("--vm-name", type=str, default=None,
                          help="Azure VM name (optional if tagged)")
    up_parser.add_argument("--resource-group", type=str, default=None,
                          help="Azure resource group (optional if tagged)")
    up_parser.add_argument("--boot-wait", type=int, default=30,
                          help="Seconds to wait for VM to boot")
    up_parser.add_argument("--probe-attempts", type=int, default=30,
                          help="Max probe attempts")
    up_parser.add_argument("--probe-interval", type=int, default=5,
                          help="Seconds between probe attempts")

    smoke_live_parser = subparsers.add_parser(
        "smoke-live",
        help="End-to-end smoke test: VM + server + single live task (auto-deallocate)",
    )
    smoke_live_parser.add_argument("--vm-name", type=str, default=None,
                                  help="Azure VM name (optional if tagged)")
    smoke_live_parser.add_argument("--resource-group", type=str, default=None,
                                  help="Azure resource group (optional if tagged)")
    smoke_live_parser.add_argument("--task-id", type=str, default="notepad_1",
                                  help="Single task ID to run")
    smoke_live_parser.add_argument("--max-steps", type=int, default=15,
                                  help="Max steps per task")
    smoke_live_parser.add_argument("--boot-wait", type=int, default=30,
                                  help="Seconds to wait for VM to boot")
    smoke_live_parser.add_argument("--probe-attempts", type=int, default=60,
                                  help="Max probe attempts")
    smoke_live_parser.add_argument("--probe-interval", type=int, default=5,
                                  help="Seconds between probe attempts")
    smoke_live_parser.add_argument("--output", type=str, default="benchmark_results",
                                  help="Output directory (only used if --save-traces)")
    smoke_live_parser.add_argument("--run-name", type=str, default="smoke_live",
                                  help="Run name (only used if --save-traces)")
    smoke_live_parser.add_argument("--save-traces", action="store_true",
                                  help="Save execution traces (viewer artifacts)")
    smoke_live_parser.add_argument("--no-stop-vm", dest="stop_vm", action="store_false",
                                  help="Do not deallocate VM after smoke test")
    smoke_live_parser.set_defaults(stop_vm=True)

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

    # Azure job monitoring
    monitor_parser = subparsers.add_parser("azure-monitor", help="Monitor Azure ML job with live tracking")
    monitor_parser.add_argument("--job-name", type=str, required=True,
                               help="Azure ML job name to monitor")
    monitor_parser.add_argument("--output", type=str, default="benchmark_live.json",
                               help="Output file for live tracking data")

    # Wandb demo command
    wandb_demo_parser = subparsers.add_parser(
        "wandb-demo",
        help="Populate wandb with synthetic evaluation data for demo"
    )
    wandb_demo_parser.add_argument("--project", type=str, default="openadapt-evals-demo",
                                   help="Wandb project name")
    wandb_demo_parser.add_argument("--entity", type=str, default=None,
                                   help="Wandb entity (team/org)")
    wandb_demo_parser.add_argument("--scenarios", nargs="+",
                                   choices=["noise", "best", "worst", "median", "comparison", "all"],
                                   default=["all"],
                                   help="Scenarios to generate")
    wandb_demo_parser.add_argument("--num-tasks", type=int, default=154,
                                   help="Number of tasks per scenario")
    wandb_demo_parser.add_argument("--seed", type=int, default=None,
                                   help="Random seed for reproducibility")
    wandb_demo_parser.add_argument("--dry-run", action="store_true",
                                   help="Generate data but don't upload")

    # Wandb report command
    wandb_report_parser = subparsers.add_parser(
        "wandb-report",
        help="Generate a wandb report from benchmark results"
    )
    wandb_report_parser.add_argument("--project", type=str, default="openadapt-evals",
                                      help="Wandb project name")
    wandb_report_parser.add_argument("--entity", type=str, default=None,
                                      help="Wandb entity (team/org)")
    wandb_report_parser.add_argument("--title", type=str,
                                      help="Report title")
    wandb_report_parser.add_argument("--description", type=str,
                                      help="Report description")
    wandb_report_parser.add_argument("--run-ids", type=str,
                                      help="Comma-separated run IDs to include")
    wandb_report_parser.add_argument("--charts", type=str,
                                      help="Comma-separated chart types: success_rate,domain_breakdown,step_distribution,error_breakdown,cost_performance")
    wandb_report_parser.add_argument("--demo", action="store_true",
                                      help="Generate demo report for synthetic scenarios")
    wandb_report_parser.add_argument("--compare", action="store_true",
                                      help="Generate model comparison report")
    wandb_report_parser.add_argument("--model-ids", type=str,
                                      help="Comma-separated model IDs for comparison (requires --compare)")

    # Wandb log command
    wandb_log_parser = subparsers.add_parser(
        "wandb-log",
        help="Log existing benchmark results to wandb"
    )
    wandb_log_parser.add_argument("--run-name", type=str, required=True,
                                  help="Name of evaluation run to log")
    wandb_log_parser.add_argument("--benchmark-dir", type=str,
                                  help="Benchmark results directory")
    wandb_log_parser.add_argument("--project", type=str, default="openadapt-evals",
                                  help="Wandb project name")
    wandb_log_parser.add_argument("--entity", type=str, default=None,
                                  help="Wandb entity (team/org)")
    wandb_log_parser.add_argument("--model-id", type=str,
                                  help="Model ID to override in config")
    wandb_log_parser.add_argument("--wandb-run-name", type=str,
                                  help="Custom wandb run name")
    wandb_log_parser.add_argument("--tags", type=str,
                                  help="Comma-separated tags")
    wandb_log_parser.add_argument("--include-artifacts", action="store_true",
                                  help="Upload execution traces and screenshots")
    wandb_log_parser.add_argument("--no-screenshots", action="store_true",
                                  help="Exclude screenshots from artifacts")
    wandb_log_parser.add_argument("--dry-run", action="store_true",
                                  help="Validate data but don't upload")

    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        return 1

    # Dispatch to command handler
    handlers = {
        "mock": cmd_mock,
        "live": cmd_live,
        "smoke-live": cmd_smoke_live,
        "probe": cmd_probe,
        "view": cmd_view,
        "estimate": cmd_estimate,
        "azure": cmd_azure,
        "azure-monitor": cmd_azure_monitor,
        "vm-start": cmd_vm_start,
        "vm-stop": cmd_vm_stop,
        "vm-status": cmd_vm_status,
        "vm-debug": cmd_vm_debug,
        "server-start": cmd_server_start,
        "vnc": cmd_vnc,
        "up": cmd_up,
        "dashboard": cmd_dashboard,
        "wandb-demo": cmd_wandb_demo,
        "wandb-report": cmd_wandb_report,
        "wandb-log": cmd_wandb_log,
    }

    handler = handlers.get(args.command)
    if handler:
        return handler(args)
    else:
        print(f"Unknown command: {args.command}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
