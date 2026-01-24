"""Auto-launching Azure resource monitoring dashboard.

This module provides a real-time web dashboard that automatically displays:
- Active Azure resources (VMs, containers, compute instances)
- Real-time costs with breakdown by resource type
- Live activity from WAA evaluations (screenshots, actions, task progress)
- Resource utilization (CPU, memory, disk)
- Logs from vm-setup, evaluations, etc.
- Controls to stop/start expensive resources

The dashboard automatically launches in the browser when Azure resources are started
and persists across multiple command invocations.

Usage:
    # Auto-launch when starting resources
    from openadapt_evals.benchmarks.dashboard_server import ensure_dashboard_running

    ensure_dashboard_running()  # Starts server if not running, opens browser

    # Or run standalone
    python -m openadapt_evals.benchmarks.dashboard_server
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import threading
import time
import webbrowser
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from flask import Flask, jsonify, render_template_string, request
from flask_cors import CORS

logger = logging.getLogger(__name__)

# Global dashboard state
_dashboard_server_thread: threading.Thread | None = None
_dashboard_port: int = 5555
_dashboard_url: str = f"http://127.0.0.1:{_dashboard_port}"


@dataclass
class ResourceInfo:
    """Information about an Azure resource."""

    resource_type: str  # "vm", "compute", "container"
    name: str
    status: str
    cost_per_hour: float
    location: str
    size: str | None = None
    public_ip: str | None = None
    created_time: str | None = None
    uptime_hours: float = 0.0


@dataclass
class CostBreakdown:
    """Cost breakdown by resource type."""

    compute_per_hour: float = 0.0
    storage_per_hour: float = 0.0
    network_per_hour: float = 0.0
    total_per_hour: float = 0.0
    total_today: float = 0.0
    total_this_week: float = 0.0
    total_this_month: float = 0.0


@dataclass
class ActivityInfo:
    """Live activity information."""

    current_task: str | None = None
    task_progress: str | None = None  # "5/154 tasks completed"
    latest_screenshot: str | None = None  # base64 or URL
    action_count: int = 0
    latest_actions: list[str] | None = None
    logs: list[str] | None = None


class DashboardState:
    """Maintains current state of Azure resources and costs."""

    def __init__(self):
        self.resources: list[ResourceInfo] = []
        self.costs = CostBreakdown()
        self.activity = ActivityInfo()
        self.last_updated = datetime.now(timezone.utc)
        self._lock = threading.Lock()

    def update_resources(self, resources: list[ResourceInfo]) -> None:
        """Update resource list."""
        with self._lock:
            self.resources = resources
            self._update_costs()
            self.last_updated = datetime.now(timezone.utc)

    def update_activity(self, activity: ActivityInfo) -> None:
        """Update activity information."""
        with self._lock:
            self.activity = activity
            self.last_updated = datetime.now(timezone.utc)

    def _update_costs(self) -> None:
        """Calculate total costs from resources."""
        compute_cost = sum(r.cost_per_hour for r in self.resources if r.status == "running")

        # Estimate storage/network (usually much smaller than compute)
        storage_cost = len(self.resources) * 0.01  # ~$0.01/hour per resource
        network_cost = 0.05 if self.resources else 0.0  # Fixed small amount

        self.costs = CostBreakdown(
            compute_per_hour=compute_cost,
            storage_per_hour=storage_cost,
            network_per_hour=network_cost,
            total_per_hour=compute_cost + storage_cost + network_cost,
            total_today=compute_cost * 24,  # Rough estimate
            total_this_week=compute_cost * 24 * 7,
            total_this_month=compute_cost * 720,  # 30 days
        )

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        with self._lock:
            return {
                "resources": [asdict(r) for r in self.resources],
                "costs": asdict(self.costs),
                "activity": asdict(self.activity),
                "last_updated": self.last_updated.isoformat(),
            }


# Global state
dashboard_state = DashboardState()


def get_azure_resources() -> list[ResourceInfo]:
    """Query Azure for currently running resources.

    Returns:
        List of active Azure resources with cost information.
    """
    resources = []

    try:
        # Get VMs
        result = subprocess.run(
            ["az", "vm", "list", "--show-details", "--query",
             "[].{name:name, status:powerState, size:hardwareProfile.vmSize, "
             "location:location, rg:resourceGroup, publicIps:publicIps}", "-o", "json"],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode == 0:
            vms = json.loads(result.stdout)
            for vm in vms:
                # Estimate cost based on VM size
                cost = estimate_vm_cost(vm.get("size", "Unknown"))

                resources.append(ResourceInfo(
                    resource_type="vm",
                    name=vm.get("name", "Unknown"),
                    status=vm.get("status", "Unknown"),
                    cost_per_hour=cost,
                    location=vm.get("location", "Unknown"),
                    size=vm.get("size"),
                    public_ip=vm.get("publicIps"),
                ))
    except Exception as e:
        logger.warning(f"Failed to query Azure VMs: {e}")

    try:
        # Get Azure ML compute instances
        # This requires resource group and workspace name from env
        rg = os.getenv("AZURE_ML_RESOURCE_GROUP", "openadapt-agents")
        ws = os.getenv("AZURE_ML_WORKSPACE_NAME", "openadapt-ml")

        result = subprocess.run(
            ["az", "ml", "compute", "list",
             "--resource-group", rg,
             "--workspace-name", ws,
             "--query", "[].{name:name, status:state, size:size, created:created_on}",
             "-o", "json"],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode == 0:
            computes = json.loads(result.stdout)
            for compute in computes:
                cost = estimate_vm_cost(compute.get("size", "Unknown"))

                resources.append(ResourceInfo(
                    resource_type="compute",
                    name=compute.get("name", "Unknown"),
                    status=compute.get("status", "Unknown"),
                    cost_per_hour=cost,
                    location="azure-ml",
                    size=compute.get("size"),
                    created_time=compute.get("created"),
                ))
    except Exception as e:
        logger.warning(f"Failed to query Azure ML compute: {e}")

    return resources


def estimate_vm_cost(vm_size: str) -> float:
    """Estimate hourly cost for a VM size.

    Args:
        vm_size: Azure VM size (e.g., "Standard_D4_v3").

    Returns:
        Estimated hourly cost in USD.
    """
    # Map common VM sizes to costs (East US pricing)
    cost_map = {
        "Standard_D2_v3": 0.096,
        "Standard_D4_v3": 0.192,
        "Standard_D8_v3": 0.384,
        "Standard_D2s_v3": 0.096,
        "Standard_D4s_v3": 0.192,
        "Standard_D8s_v3": 0.384,
        "Standard_D4ds_v5": 0.20,
        "Standard_D4s_v5": 0.192,
    }

    return cost_map.get(vm_size, 0.20)  # Default to $0.20/hour


def get_live_activity() -> ActivityInfo:
    """Get current live activity from evaluation tracking.

    Returns:
        Current activity information.
    """
    activity = ActivityInfo()

    # Try to load live tracking file
    live_file = Path("benchmark_live.json")
    if live_file.exists():
        try:
            with open(live_file) as f:
                data = json.load(f)

            if data.get("status") == "running":
                current = data.get("current_task", {})
                activity.current_task = current.get("instruction", "Unknown task")

                total = data.get("total_tasks", 0)
                completed = data.get("tasks_completed", 0)
                activity.task_progress = f"{completed}/{total} tasks completed"

                # Get recent actions
                steps = current.get("steps", [])
                if steps:
                    activity.action_count = len(steps)
                    activity.latest_actions = [
                        f"Step {s['step_idx']}: {s['action']['type']}"
                        for s in steps[-5:]  # Last 5 actions
                    ]
        except Exception as e:
            logger.warning(f"Failed to read live tracking file: {e}")

    # Try to load recent logs
    try:
        log_files = sorted(Path(".").glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
        if log_files:
            with open(log_files[0]) as f:
                lines = f.readlines()
                activity.logs = [line.strip() for line in lines[-10:]]  # Last 10 lines
    except Exception as e:
        logger.warning(f"Failed to read log files: {e}")

    return activity


# HTML template for dashboard
DASHBOARD_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Azure Resource Dashboard</title>
    <style>
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
        }

        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: #0f0f0f;
            color: #e0e0e0;
            padding: 20px;
        }

        .container {
            max-width: 1400px;
            margin: 0 auto;
        }

        header {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            padding: 30px;
            border-radius: 10px;
            margin-bottom: 30px;
            box-shadow: 0 4px 6px rgba(0,0,0,0.3);
        }

        h1 {
            font-size: 32px;
            margin-bottom: 10px;
        }

        .subtitle {
            opacity: 0.9;
            font-size: 14px;
        }

        .grid {
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
            gap: 20px;
            margin-bottom: 30px;
        }

        .card {
            background: #1a1a1a;
            border-radius: 10px;
            padding: 25px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.3);
            border: 1px solid #333;
        }

        .card h2 {
            font-size: 18px;
            margin-bottom: 15px;
            color: #667eea;
        }

        .stat {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 10px 0;
            border-bottom: 1px solid #333;
        }

        .stat:last-child {
            border-bottom: none;
        }

        .stat-label {
            color: #999;
            font-size: 14px;
        }

        .stat-value {
            font-size: 20px;
            font-weight: 600;
        }

        .cost-value {
            color: #f59e0b;
        }

        .status-running {
            color: #10b981;
        }

        .status-stopped {
            color: #6b7280;
        }

        .status-failed {
            color: #ef4444;
        }

        .resource-item {
            background: #252525;
            padding: 15px;
            border-radius: 8px;
            margin-bottom: 10px;
            border-left: 4px solid #667eea;
        }

        .resource-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            margin-bottom: 8px;
        }

        .resource-name {
            font-weight: 600;
            font-size: 16px;
        }

        .resource-meta {
            font-size: 12px;
            color: #999;
            margin-top: 5px;
        }

        .action-log {
            background: #1a1a1a;
            border: 1px solid #333;
            border-radius: 5px;
            padding: 10px;
            margin: 5px 0;
            font-family: 'Courier New', monospace;
            font-size: 12px;
            color: #a0a0a0;
        }

        .btn {
            background: #667eea;
            color: white;
            border: none;
            padding: 8px 16px;
            border-radius: 5px;
            cursor: pointer;
            font-size: 14px;
            transition: background 0.2s;
        }

        .btn:hover {
            background: #5568d3;
        }

        .btn-danger {
            background: #ef4444;
        }

        .btn-danger:hover {
            background: #dc2626;
        }

        .btn-success {
            background: #10b981;
        }

        .btn-success:hover {
            background: #059669;
        }

        .alert {
            background: #7c2d12;
            border-left: 4px solid #ef4444;
            padding: 15px;
            border-radius: 5px;
            margin-bottom: 20px;
        }

        .alert-warning {
            background: #78350f;
            border-left-color: #f59e0b;
        }

        .refresh-info {
            text-align: center;
            color: #666;
            font-size: 12px;
            margin-top: 20px;
        }

        .loading {
            text-align: center;
            padding: 40px;
            color: #666;
        }

        .empty-state {
            text-align: center;
            padding: 40px;
            color: #666;
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>Azure Resource Dashboard</h1>
            <div class="subtitle">Real-time monitoring of Azure resources and costs</div>
        </header>

        <div id="cost-alert" style="display: none;" class="alert alert-warning">
            <strong>High Cost Alert:</strong> Your resources are costing over $5/hour.
            Consider stopping unused VMs to reduce costs.
        </div>

        <div class="grid">
            <!-- Cost Summary -->
            <div class="card">
                <h2>Cost Summary</h2>
                <div class="stat">
                    <span class="stat-label">Per Hour</span>
                    <span class="stat-value cost-value" id="cost-hourly">$0.00</span>
                </div>
                <div class="stat">
                    <span class="stat-label">Today (est.)</span>
                    <span class="stat-value cost-value" id="cost-daily">$0.00</span>
                </div>
                <div class="stat">
                    <span class="stat-label">This Week (est.)</span>
                    <span class="stat-value cost-value" id="cost-weekly">$0.00</span>
                </div>
                <div class="stat">
                    <span class="stat-label">This Month (est.)</span>
                    <span class="stat-value cost-value" id="cost-monthly">$0.00</span>
                </div>
            </div>

            <!-- Resource Count -->
            <div class="card">
                <h2>Active Resources</h2>
                <div class="stat">
                    <span class="stat-label">Running VMs</span>
                    <span class="stat-value status-running" id="count-vms">0</span>
                </div>
                <div class="stat">
                    <span class="stat-label">Compute Instances</span>
                    <span class="stat-value status-running" id="count-compute">0</span>
                </div>
                <div class="stat">
                    <span class="stat-label">Total Resources</span>
                    <span class="stat-value" id="count-total">0</span>
                </div>
            </div>

            <!-- Current Activity -->
            <div class="card">
                <h2>Current Activity</h2>
                <div class="stat">
                    <span class="stat-label">Task</span>
                    <span class="stat-value" id="current-task" style="font-size: 14px;">Idle</span>
                </div>
                <div class="stat">
                    <span class="stat-label">Progress</span>
                    <span class="stat-value" id="task-progress">-</span>
                </div>
                <div class="stat">
                    <span class="stat-label">Actions</span>
                    <span class="stat-value" id="action-count">0</span>
                </div>
            </div>
        </div>

        <!-- Resources List -->
        <div class="card" style="margin-bottom: 30px;">
            <h2>Resources</h2>
            <div id="resources-list">
                <div class="loading">Loading resources...</div>
            </div>
        </div>

        <!-- Recent Activity -->
        <div class="card" style="margin-bottom: 30px;">
            <h2>Recent Actions</h2>
            <div id="recent-actions">
                <div class="empty-state">No recent activity</div>
            </div>
            <div style="margin-top: 15px; padding-top: 15px; border-top: 1px solid #e0e0e0;">
                <a href="/benchmark/latest"
                   target="_blank"
                   style="color: #1976d2; text-decoration: none; font-size: 14px;">
                    📊 View Example Benchmark Results (Jan 16, 2026)
                </a>
                <div style="margin-top: 5px; font-size: 12px; color: #666;">
                    (Run new evaluation to update)
                </div>
            </div>
        </div>

        <!-- Logs -->
        <div class="card">
            <h2>Recent Logs</h2>
            <div id="logs">
                <div class="empty-state">No logs available</div>
            </div>
        </div>

        <div class="refresh-info">
            Auto-refreshing every 5 seconds | Last updated: <span id="last-updated">-</span>
        </div>
    </div>

    <script>
        let refreshInterval;

        async function fetchDashboardData() {
            try {
                const response = await fetch('/api/dashboard');
                const data = await response.json();
                updateDashboard(data);
            } catch (error) {
                console.error('Failed to fetch dashboard data:', error);
            }
        }

        function updateDashboard(data) {
            // Update costs
            const costs = data.costs;
            document.getElementById('cost-hourly').textContent = `$${costs.total_per_hour.toFixed(2)}`;
            document.getElementById('cost-daily').textContent = `$${costs.total_today.toFixed(2)}`;
            document.getElementById('cost-weekly').textContent = `$${costs.total_this_week.toFixed(2)}`;
            document.getElementById('cost-monthly').textContent = `$${costs.total_this_month.toFixed(2)}`;

            // Show alert if costs are high
            const alert = document.getElementById('cost-alert');
            if (costs.total_per_hour > 5) {
                alert.style.display = 'block';
            } else {
                alert.style.display = 'none';
            }

            // Update resource counts
            const resources = data.resources;
            const runningVMs = resources.filter(r => r.resource_type === 'vm' && r.status.includes('running')).length;
            const compute = resources.filter(r => r.resource_type === 'compute').length;

            document.getElementById('count-vms').textContent = runningVMs;
            document.getElementById('count-compute').textContent = compute;
            document.getElementById('count-total').textContent = resources.length;

            // Update activity
            const activity = data.activity;
            document.getElementById('current-task').textContent = activity.current_task || 'Idle';
            document.getElementById('task-progress').textContent = activity.task_progress || '-';
            document.getElementById('action-count').textContent = activity.action_count || 0;

            // Update resources list
            const resourcesList = document.getElementById('resources-list');
            if (resources.length === 0) {
                resourcesList.innerHTML = '<div class="empty-state">No active resources</div>';
            } else {
                resourcesList.innerHTML = resources.map(r => `
                    <div class="resource-item">
                        <div class="resource-header">
                            <span class="resource-name">${r.name}</span>
                            <span class="stat-value status-${r.status.includes('running') ? 'running' : 'stopped'}">
                                ${r.status}
                            </span>
                        </div>
                        <div class="resource-meta">
                            ${r.resource_type.toUpperCase()} | ${r.size || 'N/A'} | ${r.location}
                            | $${r.cost_per_hour.toFixed(2)}/hour
                        </div>
                        ${r.status.includes('running') ?
                            `<button class="btn btn-danger" onclick="stopResource('${r.name}', '${r.resource_type}')">Stop</button>` :
                            `<button class="btn btn-success" onclick="startResource('${r.name}', '${r.resource_type}')">Start</button>`
                        }
                    </div>
                `).join('');
            }

            // Update recent actions
            const actionsDiv = document.getElementById('recent-actions');
            if (activity.latest_actions && activity.latest_actions.length > 0) {
                actionsDiv.innerHTML = activity.latest_actions.map(a =>
                    `<div class="action-log">${a}</div>`
                ).join('');
            } else {
                actionsDiv.innerHTML = '<div class="empty-state">No recent activity</div>';
            }

            // Update logs
            const logsDiv = document.getElementById('logs');
            if (activity.logs && activity.logs.length > 0) {
                logsDiv.innerHTML = activity.logs.map(l =>
                    `<div class="action-log">${l}</div>`
                ).join('');
            } else {
                logsDiv.innerHTML = '<div class="empty-state">No logs available</div>';
            }

            // Update timestamp
            const timestamp = new Date(data.last_updated);
            document.getElementById('last-updated').textContent = timestamp.toLocaleTimeString();
        }

        async function stopResource(name, type) {
            if (!confirm(`Stop ${name}?`)) return;

            try {
                const response = await fetch('/api/control', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({action: 'stop', name, type}),
                });
                const result = await response.json();
                alert(result.message || 'Command sent');
                fetchDashboardData();  // Refresh
            } catch (error) {
                alert('Failed to stop resource: ' + error.message);
            }
        }

        async function startResource(name, type) {
            if (!confirm(`Start ${name}?`)) return;

            try {
                const response = await fetch('/api/control', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({action: 'start', name, type}),
                });
                const result = await response.json();
                alert(result.message || 'Command sent');
                fetchDashboardData();  // Refresh
            } catch (error) {
                alert('Failed to start resource: ' + error.message);
            }
        }

        // Initial load and auto-refresh
        fetchDashboardData();
        refreshInterval = setInterval(fetchDashboardData, 5000);  // Every 5 seconds
    </script>
</body>
</html>
"""


def create_dashboard_app() -> Flask:
    """Create Flask app for dashboard."""
    app = Flask(__name__)
    CORS(app)

    @app.route("/")
    def index():
        """Serve dashboard HTML."""
        return render_template_string(DASHBOARD_HTML)

    @app.route("/api/dashboard")
    def get_dashboard_data():
        """Get current dashboard state."""
        # Update resources in background
        threading.Thread(target=_update_dashboard_state, daemon=True).start()

        return jsonify(dashboard_state.to_dict())

    @app.route("/api/control", methods=["POST"])
    def control_resource():
        """Start or stop a resource."""
        data = request.json
        action = data.get("action")
        name = data.get("name")
        resource_type = data.get("type")

        if not all([action, name, resource_type]):
            return jsonify({"error": "Missing required fields"}), 400

        try:
            if resource_type == "vm":
                if action == "stop":
                    subprocess.run(
                        ["uv", "run", "python", "-m", "openadapt_evals.benchmarks.cli",
                         "vm-stop", "--vm-name", name, "--no-wait"],
                        check=True,
                    )
                    return jsonify({"message": f"Stop command sent to {name}"})
                elif action == "start":
                    subprocess.run(
                        ["uv", "run", "python", "-m", "openadapt_evals.benchmarks.cli",
                         "vm-start", "--vm-name", name],
                        check=True,
                    )
                    return jsonify({"message": f"Start command sent to {name}"})

            return jsonify({"error": f"Unsupported action: {action} for {resource_type}"}), 400

        except subprocess.CalledProcessError as e:
            return jsonify({"error": f"Command failed: {e}"}), 500

    @app.route("/benchmark/latest")
    def latest_benchmark():
        """Serve latest benchmark viewer."""
        viewer_path = Path("/Users/abrichr/oa/src/openadapt-evals/benchmark_results/waa-live_eval_20260116_200004/viewer.html")
        if viewer_path.exists():
            return viewer_path.read_text()
        return "No benchmark results available", 404

    @app.route("/health")
    def health():
        """Health check."""
        return jsonify({"status": "ok"})

    return app


def _update_dashboard_state() -> None:
    """Update dashboard state (run in background thread)."""
    try:
        resources = get_azure_resources()
        dashboard_state.update_resources(resources)

        activity = get_live_activity()
        dashboard_state.update_activity(activity)
    except Exception as e:
        logger.error(f"Failed to update dashboard state: {e}")


def run_dashboard_server(port: int = 5555, host: str = "127.0.0.1") -> None:
    """Run dashboard server (blocking).

    Args:
        port: Port to run on.
        host: Host to bind to.
    """
    app = create_dashboard_app()

    logger.info(f"Starting dashboard server on {host}:{port}")
    logger.info(f"Dashboard URL: http://{host}:{port}")

    # Initial state update
    _update_dashboard_state()

    # Run Flask app
    app.run(host=host, port=port, debug=False, threaded=True)


def is_dashboard_running(port: int = 5555) -> bool:
    """Check if dashboard server is already running.

    Args:
        port: Port to check.

    Returns:
        True if server is running, False otherwise.
    """
    try:
        import requests
        response = requests.get(f"http://127.0.0.1:{port}/health", timeout=2)
        return response.status_code == 200
    except Exception:
        return False


def start_dashboard_background(port: int = 5555) -> None:
    """Start dashboard server in background thread.

    Args:
        port: Port to run on.
    """
    global _dashboard_server_thread, _dashboard_port

    if is_dashboard_running(port):
        logger.info(f"Dashboard already running on port {port}")
        return

    _dashboard_port = port

    def run():
        run_dashboard_server(port=port)

    _dashboard_server_thread = threading.Thread(target=run, daemon=True)
    _dashboard_server_thread.start()

    # Wait a moment for server to start
    time.sleep(2)

    logger.info(f"Dashboard server started on port {port}")


def ensure_dashboard_running(auto_open: bool = True, port: int = 5555) -> str:
    """Ensure dashboard server is running and optionally open browser.

    This is the main entry point for auto-launching the dashboard.

    Args:
        auto_open: Whether to open browser automatically.
        port: Port to run on.

    Returns:
        Dashboard URL.
    """
    global _dashboard_url
    _dashboard_url = f"http://127.0.0.1:{port}"

    # Start server if not running
    if not is_dashboard_running(port):
        logger.info("Starting dashboard server...")
        start_dashboard_background(port)

        # Wait for server to be ready
        for _ in range(10):
            if is_dashboard_running(port):
                break
            time.sleep(0.5)

    # Open browser
    if auto_open:
        logger.info(f"Opening dashboard in browser: {_dashboard_url}")
        webbrowser.open(_dashboard_url)

    return _dashboard_url


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Azure Resource Dashboard")
    parser.add_argument("--port", type=int, default=5555, help="Port to run on")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host to bind to")
    parser.add_argument("--no-open", action="store_true", help="Don't open browser")

    args = parser.parse_args()

    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    # Open browser unless disabled
    if not args.no_open:
        url = f"http://{args.host}:{args.port}"
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    # Run server (blocking)
    run_dashboard_server(port=args.port, host=args.host)

    return 0


if __name__ == "__main__":
    sys.exit(main())
