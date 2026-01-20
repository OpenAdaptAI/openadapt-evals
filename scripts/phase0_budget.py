#!/usr/bin/env python3
"""
Phase 0 Budget Tracker

Tracks API costs, runs completed, and budget utilization for Phase 0 experiment.
Provides real-time alerts when budget thresholds are reached.

Usage:
    python scripts/phase0_budget.py                    # Display current budget status
    python scripts/phase0_budget.py --add-run <cost>   # Add a run with cost
    python scripts/phase0_budget.py --reset            # Reset budget tracker
    python scripts/phase0_budget.py --report           # Generate budget report
"""

import json
import sys
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional


@dataclass
class RunRecord:
    """Record of a single evaluation run."""
    timestamp: str
    model: str  # "claude-sonnet-4.5" or "gpt-4v"
    condition: str  # "zero-shot" or "demo-conditioned"
    task_id: str
    trial: int  # 1, 2, or 3
    cost: float  # USD
    success: Optional[bool] = None
    steps: Optional[int] = None


@dataclass
class BudgetSummary:
    """Summary of budget utilization."""
    total_budget: float = 400.0
    spent: float = 0.0
    remaining: float = 400.0
    runs_completed: int = 0
    runs_target: int = 240
    cost_per_run_avg: float = 0.0

    # By condition
    zero_shot_runs: int = 0
    zero_shot_cost: float = 0.0
    demo_runs: int = 0
    demo_cost: float = 0.0

    # By model
    claude_runs: int = 0
    claude_cost: float = 0.0
    gpt_runs: int = 0
    gpt_cost: float = 0.0

    # Alerts
    budget_percentage: float = 0.0
    progress_percentage: float = 0.0
    alert_level: str = "green"  # green, yellow, orange, red


class Phase0BudgetTracker:
    """Tracks budget and costs for Phase 0 experiment."""

    # Budget thresholds
    TOTAL_BUDGET = 400.0
    ALERT_THRESHOLDS = {
        "yellow": 0.50,  # 50%
        "orange": 0.75,  # 75%
        "red": 0.90,     # 90%
    }

    # Expected costs per run (for estimation)
    EXPECTED_COSTS = {
        ("claude-sonnet-4.5", "zero-shot"): 0.50,
        ("claude-sonnet-4.5", "demo-conditioned"): 0.75,
        ("gpt-4v", "zero-shot"): 1.50,
        ("gpt-4v", "demo-conditioned"): 2.00,
    }

    def __init__(self, data_file: Path = Path("phase0_budget.json")):
        """Initialize budget tracker."""
        self.data_file = data_file
        self.runs: List[RunRecord] = []
        self.load()

    def load(self):
        """Load existing budget data."""
        if self.data_file.exists():
            with open(self.data_file, 'r') as f:
                data = json.load(f)
                self.runs = [RunRecord(**run) for run in data.get("runs", [])]

    def save(self):
        """Save budget data to disk."""
        data = {
            "runs": [asdict(run) for run in self.runs],
            "last_updated": datetime.now().isoformat(),
        }
        with open(self.data_file, 'w') as f:
            json.dump(data, f, indent=2)

    def add_run(self, model: str, condition: str, task_id: str, trial: int,
                cost: float, success: Optional[bool] = None, steps: Optional[int] = None):
        """Add a completed run to the tracker."""
        run = RunRecord(
            timestamp=datetime.now().isoformat(),
            model=model,
            condition=condition,
            task_id=task_id,
            trial=trial,
            cost=cost,
            success=success,
            steps=steps,
        )
        self.runs.append(run)
        self.save()

        # Check for budget alerts
        summary = self.get_summary()
        self._check_alerts(summary)

    def get_summary(self) -> BudgetSummary:
        """Get current budget summary."""
        summary = BudgetSummary()

        if not self.runs:
            return summary

        # Overall stats
        summary.spent = sum(run.cost for run in self.runs)
        summary.remaining = summary.total_budget - summary.spent
        summary.runs_completed = len(self.runs)
        summary.cost_per_run_avg = summary.spent / summary.runs_completed if summary.runs_completed > 0 else 0.0

        # By condition
        zero_shot_runs = [r for r in self.runs if r.condition == "zero-shot"]
        demo_runs = [r for r in self.runs if r.condition == "demo-conditioned"]
        summary.zero_shot_runs = len(zero_shot_runs)
        summary.zero_shot_cost = sum(r.cost for r in zero_shot_runs)
        summary.demo_runs = len(demo_runs)
        summary.demo_cost = sum(r.cost for r in demo_runs)

        # By model
        claude_runs = [r for r in self.runs if "claude" in r.model.lower()]
        gpt_runs = [r for r in self.runs if "gpt" in r.model.lower()]
        summary.claude_runs = len(claude_runs)
        summary.claude_cost = sum(r.cost for r in claude_runs)
        summary.gpt_runs = len(gpt_runs)
        summary.gpt_cost = sum(r.cost for r in gpt_runs)

        # Percentages
        summary.budget_percentage = (summary.spent / summary.total_budget) * 100
        summary.progress_percentage = (summary.runs_completed / summary.runs_target) * 100

        # Alert level
        budget_ratio = summary.spent / summary.total_budget
        if budget_ratio >= self.ALERT_THRESHOLDS["red"]:
            summary.alert_level = "red"
        elif budget_ratio >= self.ALERT_THRESHOLDS["orange"]:
            summary.alert_level = "orange"
        elif budget_ratio >= self.ALERT_THRESHOLDS["yellow"]:
            summary.alert_level = "yellow"
        else:
            summary.alert_level = "green"

        return summary

    def _check_alerts(self, summary: BudgetSummary):
        """Check for budget alerts and print warnings."""
        budget_ratio = summary.spent / summary.total_budget

        if budget_ratio >= self.ALERT_THRESHOLDS["red"]:
            print(f"\n🔴 RED ALERT: Budget at {summary.budget_percentage:.1f}% (${summary.spent:.2f}/${summary.total_budget})")
            print(f"   Only ${summary.remaining:.2f} remaining!")
            print(f"   Consider stopping or reducing trials.")
        elif budget_ratio >= self.ALERT_THRESHOLDS["orange"]:
            print(f"\n🟠 ORANGE ALERT: Budget at {summary.budget_percentage:.1f}% (${summary.spent:.2f}/${summary.total_budget})")
            print(f"   ${summary.remaining:.2f} remaining.")
        elif budget_ratio >= self.ALERT_THRESHOLDS["yellow"]:
            print(f"\n🟡 YELLOW ALERT: Budget at {summary.budget_percentage:.1f}% (${summary.spent:.2f}/${summary.total_budget})")
            print(f"   ${summary.remaining:.2f} remaining.")

    def estimate_remaining_cost(self) -> float:
        """Estimate cost to complete all 240 runs."""
        summary = self.get_summary()
        runs_remaining = summary.runs_target - summary.runs_completed

        if summary.runs_completed == 0:
            # Use expected costs
            cost_estimate = (
                60 * self.EXPECTED_COSTS[("claude-sonnet-4.5", "zero-shot")] +
                60 * self.EXPECTED_COSTS[("claude-sonnet-4.5", "demo-conditioned")] +
                60 * self.EXPECTED_COSTS[("gpt-4v", "zero-shot")] +
                60 * self.EXPECTED_COSTS[("gpt-4v", "demo-conditioned")]
            )
        else:
            # Use actual average
            cost_estimate = summary.cost_per_run_avg * runs_remaining

        return cost_estimate

    def print_summary(self):
        """Print budget summary to console."""
        summary = self.get_summary()

        print("\n" + "=" * 60)
        print("PHASE 0 BUDGET TRACKER")
        print("=" * 60)

        # Overall progress
        print(f"\n📊 Overall Progress:")
        print(f"   Runs: {summary.runs_completed}/{summary.runs_target} ({summary.progress_percentage:.1f}%)")
        print(f"   Budget: ${summary.spent:.2f}/${summary.total_budget} ({summary.budget_percentage:.1f}%)")
        print(f"   Remaining: ${summary.remaining:.2f}")
        print(f"   Avg cost/run: ${summary.cost_per_run_avg:.2f}")

        # Alert status
        alert_emoji = {"green": "🟢", "yellow": "🟡", "orange": "🟠", "red": "🔴"}
        print(f"\n{alert_emoji[summary.alert_level]} Status: {summary.alert_level.upper()}")

        # By condition
        print(f"\n📋 By Condition:")
        print(f"   Zero-shot: {summary.zero_shot_runs} runs, ${summary.zero_shot_cost:.2f}")
        print(f"   Demo-conditioned: {summary.demo_runs} runs, ${summary.demo_cost:.2f}")

        # By model
        print(f"\n🤖 By Model:")
        print(f"   Claude Sonnet 4.5: {summary.claude_runs} runs, ${summary.claude_cost:.2f}")
        print(f"   GPT-4V: {summary.gpt_runs} runs, ${summary.gpt_cost:.2f}")

        # Estimate
        remaining_cost = self.estimate_remaining_cost()
        projected_total = summary.spent + remaining_cost
        print(f"\n💰 Cost Estimate:")
        print(f"   Remaining runs: {summary.runs_target - summary.runs_completed}")
        print(f"   Estimated remaining cost: ${remaining_cost:.2f}")
        print(f"   Projected total: ${projected_total:.2f}")

        if projected_total > summary.total_budget:
            print(f"   ⚠️  WARNING: Projected cost exceeds budget by ${projected_total - summary.total_budget:.2f}!")

        print("\n" + "=" * 60 + "\n")

    def generate_report(self) -> Dict:
        """Generate detailed budget report."""
        summary = self.get_summary()

        # Cost breakdown by model and condition
        breakdown = {}
        for model in ["claude-sonnet-4.5", "gpt-4v"]:
            for condition in ["zero-shot", "demo-conditioned"]:
                runs = [r for r in self.runs if r.model == model and r.condition == condition]
                breakdown[f"{model}_{condition}"] = {
                    "runs": len(runs),
                    "cost": sum(r.cost for r in runs),
                    "avg_cost": sum(r.cost for r in runs) / len(runs) if runs else 0.0,
                }

        report = {
            "summary": asdict(summary),
            "breakdown": breakdown,
            "estimated_remaining": self.estimate_remaining_cost(),
            "runs": [asdict(run) for run in self.runs],
            "generated_at": datetime.now().isoformat(),
        }

        return report

    def reset(self):
        """Reset budget tracker (use with caution!)."""
        confirm = input("Are you sure you want to reset the budget tracker? (yes/no): ")
        if confirm.lower() == "yes":
            self.runs = []
            self.save()
            print("Budget tracker reset.")
        else:
            print("Reset cancelled.")


def main():
    """CLI for budget tracker."""
    tracker = Phase0BudgetTracker()

    if len(sys.argv) == 1:
        # Default: print summary
        tracker.print_summary()

    elif "--add-run" in sys.argv:
        # Add a run manually
        idx = sys.argv.index("--add-run")
        if idx + 5 > len(sys.argv):
            print("Usage: --add-run <model> <condition> <task_id> <trial> <cost>")
            sys.exit(1)

        model = sys.argv[idx + 1]
        condition = sys.argv[idx + 2]
        task_id = sys.argv[idx + 3]
        trial = int(sys.argv[idx + 4])
        cost = float(sys.argv[idx + 5])

        tracker.add_run(model, condition, task_id, trial, cost)
        print(f"Added run: {model} {condition} {task_id} trial {trial} (${cost:.2f})")
        tracker.print_summary()

    elif "--reset" in sys.argv:
        # Reset tracker
        tracker.reset()

    elif "--report" in sys.argv:
        # Generate JSON report
        report = tracker.generate_report()
        report_file = Path("phase0_budget_report.json")
        with open(report_file, 'w') as f:
            json.dump(report, f, indent=2)
        print(f"Report saved to {report_file}")

    else:
        print(__doc__)


if __name__ == "__main__":
    main()
