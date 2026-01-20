#!/usr/bin/env python3
"""
Phase 0 Dashboard

Simple real-time dashboard showing Phase 0 progress, budget, and recent results.

Usage:
    python scripts/phase0_dashboard.py              # Display dashboard once
    python scripts/phase0_dashboard.py --watch      # Auto-refresh every 5 seconds
    python scripts/phase0_dashboard.py --html       # Generate HTML dashboard
"""

import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

try:
    from phase0_budget import Phase0BudgetTracker
except ImportError:
    # Handle running from different directory
    sys.path.append(str(Path(__file__).parent))
    from phase0_budget import Phase0BudgetTracker


class Phase0Dashboard:
    """Real-time dashboard for Phase 0 progress."""

    def __init__(self):
        """Initialize dashboard."""
        self.budget_tracker = Phase0BudgetTracker()
        self.results_dir = Path("benchmark_results")

    def get_recent_results(self, n: int = 10) -> List[Dict]:
        """Get N most recent evaluation results."""
        if not self.results_dir.exists():
            return []

        # Find all result JSON files
        result_files = sorted(
            self.results_dir.glob("**/*.json"),
            key=lambda p: p.stat().st_mtime,
            reverse=True
        )

        recent_results = []
        for result_file in result_files[:n]:
            try:
                with open(result_file, 'r') as f:
                    result = json.load(f)
                    recent_results.append({
                        "file": result_file.name,
                        "task_id": result.get("task_id", "unknown"),
                        "success": result.get("success", False),
                        "steps": result.get("steps", 0),
                        "timestamp": result.get("timestamp", "unknown"),
                    })
            except Exception as e:
                continue

        return recent_results

    def get_success_rates(self) -> Dict:
        """Compute success rates from budget tracker runs."""
        runs = self.budget_tracker.runs

        if not runs:
            return {
                "zero_shot": {"total": 0, "success": 0, "rate": 0.0},
                "demo": {"total": 0, "success": 0, "rate": 0.0},
                "improvement": 0.0,
            }

        # Filter by condition
        zero_shot_runs = [r for r in runs if r.condition == "zero-shot" and r.success is not None]
        demo_runs = [r for r in runs if r.condition == "demo-conditioned" and r.success is not None]

        zero_shot_success = sum(1 for r in zero_shot_runs if r.success)
        demo_success = sum(1 for r in demo_runs if r.success)

        zero_shot_rate = (zero_shot_success / len(zero_shot_runs)) * 100 if zero_shot_runs else 0.0
        demo_rate = (demo_success / len(demo_runs)) * 100 if demo_runs else 0.0

        return {
            "zero_shot": {
                "total": len(zero_shot_runs),
                "success": zero_shot_success,
                "rate": zero_shot_rate,
            },
            "demo": {
                "total": len(demo_runs),
                "success": demo_success,
                "rate": demo_rate,
            },
            "improvement": demo_rate - zero_shot_rate,
        }

    def get_eta(self) -> str:
        """Estimate time to completion."""
        summary = self.budget_tracker.get_summary()

        if summary.runs_completed == 0:
            return "Unknown (no runs completed)"

        # Estimate based on runs completed so far
        runs_remaining = summary.runs_target - summary.runs_completed

        # Assume 2 minutes per run (rough estimate)
        minutes_remaining = runs_remaining * 2
        hours_remaining = minutes_remaining / 60
        days_remaining = hours_remaining / 8  # 8-hour work day

        if days_remaining < 1:
            return f"{hours_remaining:.1f} hours"
        else:
            return f"{days_remaining:.1f} days"

    def display_dashboard(self):
        """Display dashboard in terminal."""
        # Clear screen (Unix/Mac)
        print("\033[2J\033[H", end="")

        print("=" * 70)
        print(" " * 20 + "PHASE 0 DASHBOARD")
        print(" " * 15 + "Demo-Augmentation Prompting Baseline")
        print("=" * 70)

        # Progress
        summary = self.budget_tracker.get_summary()
        print(f"\n📊 PROGRESS")
        print(f"   Runs: {summary.runs_completed}/{summary.runs_target} ({summary.progress_percentage:.1f}%)")
        progress_bar = self._progress_bar(summary.runs_completed, summary.runs_target, width=40)
        print(f"   {progress_bar}")

        # Budget
        print(f"\n💰 BUDGET")
        print(f"   Spent: ${summary.spent:.2f}/${summary.total_budget} ({summary.budget_percentage:.1f}%)")
        budget_bar = self._progress_bar(summary.spent, summary.total_budget, width=40, char='$')
        print(f"   {budget_bar}")

        alert_emoji = {"green": "🟢", "yellow": "🟡", "orange": "🟠", "red": "🔴"}
        print(f"   Status: {alert_emoji[summary.alert_level]} {summary.alert_level.upper()}")

        # Success rates
        success_rates = self.get_success_rates()
        print(f"\n📈 SUCCESS RATES")
        print(f"   Zero-shot: {success_rates['zero_shot']['rate']:.1f}% ({success_rates['zero_shot']['success']}/{success_rates['zero_shot']['total']} runs)")
        print(f"   Demo-conditioned: {success_rates['demo']['rate']:.1f}% ({success_rates['demo']['success']}/{success_rates['demo']['total']} runs)")

        if success_rates['demo']['total'] > 0:
            improvement = success_rates['improvement']
            arrow = "↑" if improvement > 0 else "↓" if improvement < 0 else "→"
            print(f"   Improvement: {arrow} {abs(improvement):.1f}pp")

        # ETA
        eta = self.get_eta()
        print(f"\n⏱️  ETA: {eta}")

        # Recent failures (last 5)
        print(f"\n❌ RECENT FAILURES")
        recent_runs = self.budget_tracker.runs[-20:]  # Last 20 runs
        failures = [r for r in recent_runs if r.success is False][-5:]

        if not failures:
            print("   None (or no data yet)")
        else:
            for failure in failures:
                print(f"   - {failure.task_id} ({failure.model}, {failure.condition})")

        # Footer
        print(f"\n" + "=" * 70)
        print(f"Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 70 + "\n")

    def _progress_bar(self, current: float, total: float, width: int = 40, char: str = '█') -> str:
        """Generate a progress bar."""
        if total == 0:
            return "[" + " " * width + "] 0%"

        filled = int((current / total) * width)
        empty = width - filled
        percentage = (current / total) * 100

        return f"[{char * filled}{' ' * empty}] {percentage:.1f}%"

    def generate_html(self, output_file: Path = Path("phase0_dashboard.html")):
        """Generate HTML dashboard."""
        summary = self.budget_tracker.get_summary()
        success_rates = self.get_success_rates()
        eta = self.get_eta()

        html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <title>Phase 0 Dashboard</title>
    <meta http-equiv="refresh" content="30">
    <style>
        body {{
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
            background-color: #1e1e1e;
            color: #d4d4d4;
            margin: 0;
            padding: 20px;
        }}
        .container {{
            max-width: 1200px;
            margin: 0 auto;
        }}
        h1 {{
            text-align: center;
            color: #4fc3f7;
            border-bottom: 2px solid #4fc3f7;
            padding-bottom: 10px;
        }}
        .card {{
            background-color: #252526;
            border-radius: 8px;
            padding: 20px;
            margin: 20px 0;
            box-shadow: 0 2px 4px rgba(0,0,0,0.3);
        }}
        .card h2 {{
            margin-top: 0;
            color: #4fc3f7;
        }}
        .metric {{
            display: flex;
            justify-content: space-between;
            margin: 10px 0;
            padding: 10px;
            background-color: #2d2d30;
            border-radius: 4px;
        }}
        .metric-label {{
            font-weight: bold;
        }}
        .metric-value {{
            color: #4fc3f7;
        }}
        .progress-bar {{
            width: 100%;
            height: 30px;
            background-color: #3c3c3c;
            border-radius: 15px;
            overflow: hidden;
            margin: 10px 0;
        }}
        .progress-fill {{
            height: 100%;
            background: linear-gradient(90deg, #4fc3f7, #2196f3);
            transition: width 0.3s ease;
        }}
        .alert-green {{ color: #4caf50; }}
        .alert-yellow {{ color: #ffeb3b; }}
        .alert-orange {{ color: #ff9800; }}
        .alert-red {{ color: #f44336; }}
        .footer {{
            text-align: center;
            margin-top: 40px;
            color: #888;
        }}
    </style>
</head>
<body>
    <div class="container">
        <h1>Phase 0 Dashboard</h1>
        <p style="text-align: center; color: #888;">Demo-Augmentation Prompting Baseline</p>

        <div class="card">
            <h2>📊 Progress</h2>
            <div class="metric">
                <span class="metric-label">Runs Completed</span>
                <span class="metric-value">{summary.runs_completed}/{summary.runs_target} ({summary.progress_percentage:.1f}%)</span>
            </div>
            <div class="progress-bar">
                <div class="progress-fill" style="width: {summary.progress_percentage}%;"></div>
            </div>
        </div>

        <div class="card">
            <h2>💰 Budget</h2>
            <div class="metric">
                <span class="metric-label">Spent</span>
                <span class="metric-value">${summary.spent:.2f}/${summary.total_budget} ({summary.budget_percentage:.1f}%)</span>
            </div>
            <div class="progress-bar">
                <div class="progress-fill" style="width: {summary.budget_percentage}%; background: linear-gradient(90deg, #ff9800, #f44336);"></div>
            </div>
            <div class="metric">
                <span class="metric-label">Remaining</span>
                <span class="metric-value">${summary.remaining:.2f}</span>
            </div>
            <div class="metric">
                <span class="metric-label">Status</span>
                <span class="metric-value alert-{summary.alert_level}">{summary.alert_level.upper()}</span>
            </div>
        </div>

        <div class="card">
            <h2>📈 Success Rates</h2>
            <div class="metric">
                <span class="metric-label">Zero-shot</span>
                <span class="metric-value">{success_rates['zero_shot']['rate']:.1f}% ({success_rates['zero_shot']['success']}/{success_rates['zero_shot']['total']} runs)</span>
            </div>
            <div class="metric">
                <span class="metric-label">Demo-conditioned</span>
                <span class="metric-value">{success_rates['demo']['rate']:.1f}% ({success_rates['demo']['success']}/{success_rates['demo']['total']} runs)</span>
            </div>
            <div class="metric">
                <span class="metric-label">Improvement</span>
                <span class="metric-value">{success_rates['improvement']:+.1f}pp</span>
            </div>
        </div>

        <div class="card">
            <h2>⏱️ Estimate</h2>
            <div class="metric">
                <span class="metric-label">ETA to Completion</span>
                <span class="metric-value">{eta}</span>
            </div>
            <div class="metric">
                <span class="metric-label">Avg Cost/Run</span>
                <span class="metric-value">${summary.cost_per_run_avg:.2f}</span>
            </div>
        </div>

        <div class="footer">
            Last updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}<br>
            Auto-refreshes every 30 seconds
        </div>
    </div>
</body>
</html>
"""

        with open(output_file, 'w') as f:
            f.write(html_content)

        print(f"HTML dashboard saved to {output_file}")
        print(f"Open with: open {output_file}")


def main():
    """CLI for dashboard."""
    dashboard = Phase0Dashboard()

    if "--html" in sys.argv:
        # Generate HTML dashboard
        dashboard.generate_html()

    elif "--watch" in sys.argv:
        # Auto-refresh every 5 seconds
        try:
            while True:
                dashboard.display_dashboard()
                time.sleep(5)
        except KeyboardInterrupt:
            print("\nDashboard stopped.")

    else:
        # Display once
        dashboard.display_dashboard()


if __name__ == "__main__":
    main()
