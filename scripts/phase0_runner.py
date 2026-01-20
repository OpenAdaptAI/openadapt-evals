#!/usr/bin/env python3
"""
Phase 0 Batch Runner

Runs batch evaluations for Phase 0 experiment (zero-shot and demo-conditioned).

Usage:
    # Run zero-shot baseline (120 runs)
    python scripts/phase0_runner.py --condition zero-shot --tasks phase0_tasks.json

    # Run demo-conditioned (120 runs)
    python scripts/phase0_runner.py --condition demo-conditioned --tasks phase0_tasks.json

    # Run specific task
    python scripts/phase0_runner.py --condition zero-shot --task-id notepad_1 --trials 3

    # Dry run (test without API calls)
    python scripts/phase0_runner.py --condition zero-shot --tasks phase0_tasks.json --dry-run
"""

import json
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from phase0_budget import Phase0BudgetTracker
except ImportError:
    sys.path.append(str(Path(__file__).parent))
    from phase0_budget import Phase0BudgetTracker


@dataclass
class TaskConfig:
    """Configuration for a single task."""
    task_id: str
    domain: str
    difficulty: str  # "simple", "medium", "hard"
    first_action: str  # "click", "type", "keyboard", "wait"


class Phase0Runner:
    """Batch runner for Phase 0 experiments."""

    # Model configurations
    MODELS = {
        "claude-sonnet-4.5": {
            "provider": "anthropic",
            "cost_zero_shot": 0.50,
            "cost_demo": 0.75,
        },
        "gpt-4v": {
            "provider": "openai",
            "cost_zero_shot": 1.50,
            "cost_demo": 2.00,
        },
    }

    def __init__(
        self,
        condition: str,
        tasks_file: Optional[Path] = None,
        trials: int = 3,
        dry_run: bool = False,
    ):
        """
        Initialize runner.

        Args:
            condition: "zero-shot" or "demo-conditioned"
            tasks_file: Path to JSON file with task list
            trials: Number of trials per task (default: 3)
            dry_run: If True, don't make API calls (testing only)
        """
        self.condition = condition
        self.tasks_file = tasks_file
        self.trials = trials
        self.dry_run = dry_run

        self.budget_tracker = Phase0BudgetTracker()
        self.tasks: List[TaskConfig] = []

        if tasks_file:
            self.load_tasks()

    def load_tasks(self):
        """Load task list from JSON file."""
        if not self.tasks_file.exists():
            raise FileNotFoundError(f"Tasks file not found: {self.tasks_file}")

        with open(self.tasks_file, 'r') as f:
            data = json.load(f)

        self.tasks = [TaskConfig(**task) for task in data.get("tasks", [])]
        print(f"Loaded {len(self.tasks)} tasks from {self.tasks_file}")

    def run_single_task(
        self,
        task_id: str,
        model: str,
        trial: int,
    ) -> dict:
        """
        Run a single evaluation.

        Args:
            task_id: Task identifier
            model: Model name ("claude-sonnet-4.5" or "gpt-4v")
            trial: Trial number (1, 2, or 3)

        Returns:
            Result dictionary with success, steps, cost, etc.
        """
        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Running {task_id} ({model}, {self.condition}, trial {trial})")

        if self.dry_run:
            # Simulate run without API call
            result = {
                "task_id": task_id,
                "model": model,
                "condition": self.condition,
                "trial": trial,
                "success": True,  # Mock success
                "steps": 5,
                "cost": self.MODELS[model][f"cost_{self.condition.replace('-', '_')}"],
                "timestamp": datetime.now().isoformat(),
                "dry_run": True,
            }
            print(f"   [DRY RUN] Success: {result['success']}, Steps: {result['steps']}, Cost: ${result['cost']:.2f}")
            return result

        # TODO: Actual evaluation logic
        # This is a placeholder - replace with actual evaluation code:
        #
        # from openadapt_evals import ApiAgent, WAALiveAdapter, evaluate_agent_on_benchmark
        #
        # if self.condition == "zero-shot":
        #     agent = ApiAgent(provider=self.MODELS[model]["provider"])
        # else:
        #     agent = RetrievalAugmentedAgent(
        #         provider=self.MODELS[model]["provider"],
        #         demo_library_path="demo_library/synthetic_demos"
        #     )
        #
        # adapter = WAALiveAdapter(server_url="http://vm:5000")
        # task = adapter.load_task(task_id)
        # result = evaluate_agent_on_benchmark(agent, adapter, [task])

        # Placeholder result
        result = {
            "task_id": task_id,
            "model": model,
            "condition": self.condition,
            "trial": trial,
            "success": False,  # Replace with actual result
            "steps": 0,  # Replace with actual steps
            "cost": self.MODELS[model][f"cost_{self.condition.replace('-', '_')}"],
            "timestamp": datetime.now().isoformat(),
        }

        print(f"   Success: {result['success']}, Steps: {result['steps']}, Cost: ${result['cost']:.2f}")

        # Add to budget tracker
        self.budget_tracker.add_run(
            model=model,
            condition=self.condition,
            task_id=task_id,
            trial=trial,
            cost=result["cost"],
            success=result["success"],
            steps=result["steps"],
        )

        return result

    def run_batch(self):
        """Run all tasks × models × trials."""
        if not self.tasks:
            raise ValueError("No tasks loaded. Use load_tasks() or provide tasks_file.")

        total_runs = len(self.tasks) * len(self.MODELS) * self.trials
        print(f"\n" + "=" * 70)
        print(f"PHASE 0 BATCH RUN: {self.condition.upper()}")
        print(f"=" * 70)
        print(f"Tasks: {len(self.tasks)}")
        print(f"Models: {len(self.MODELS)} ({', '.join(self.MODELS.keys())})")
        print(f"Trials: {self.trials}")
        print(f"Total runs: {total_runs}")
        print(f"Dry run: {self.dry_run}")
        print(f"=" * 70)

        results = []
        run_count = 0

        for task in self.tasks:
            for model in self.MODELS:
                for trial in range(1, self.trials + 1):
                    run_count += 1
                    print(f"\n[{run_count}/{total_runs}] ", end="")

                    result = self.run_single_task(
                        task_id=task.task_id,
                        model=model,
                        trial=trial,
                    )
                    results.append(result)

                    # Small delay to avoid rate limits
                    if not self.dry_run:
                        time.sleep(1)

        print(f"\n" + "=" * 70)
        print(f"BATCH COMPLETE: {run_count} runs")
        print(f"=" * 70)

        # Save results
        self._save_results(results)

        # Print summary
        self._print_summary(results)

    def _save_results(self, results: List[dict]):
        """Save results to JSON file."""
        output_file = Path(f"phase0_results_{self.condition}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")

        data = {
            "condition": self.condition,
            "trials": self.trials,
            "total_runs": len(results),
            "timestamp": datetime.now().isoformat(),
            "results": results,
        }

        with open(output_file, 'w') as f:
            json.dump(data, f, indent=2)

        print(f"\nResults saved to {output_file}")

    def _print_summary(self, results: List[dict]):
        """Print summary statistics."""
        successful = sum(1 for r in results if r.get("success", False))
        total = len(results)
        success_rate = (successful / total) * 100 if total > 0 else 0.0

        total_cost = sum(r.get("cost", 0.0) for r in results)
        avg_steps = sum(r.get("steps", 0) for r in results) / total if total > 0 else 0.0

        print(f"\n📊 SUMMARY:")
        print(f"   Success rate: {success_rate:.1f}% ({successful}/{total})")
        print(f"   Avg steps: {avg_steps:.1f}")
        print(f"   Total cost: ${total_cost:.2f}")
        print(f"   Avg cost/run: ${total_cost / total:.2f}")


def create_example_tasks_file():
    """Create an example tasks file for Phase 0."""
    tasks = {
        "description": "Phase 0 task set - 20 tasks for demo-augmentation experiment",
        "total_tasks": 20,
        "tasks": [
            # Notepad tasks (4)
            {"task_id": "notepad_1", "domain": "notepad", "difficulty": "simple", "first_action": "click"},
            {"task_id": "notepad_2", "domain": "notepad", "difficulty": "medium", "first_action": "type"},
            {"task_id": "notepad_3", "domain": "notepad", "difficulty": "medium", "first_action": "keyboard"},
            {"task_id": "notepad_4", "domain": "notepad", "difficulty": "hard", "first_action": "click"},

            # Browser tasks (4)
            {"task_id": "browser_1", "domain": "browser", "difficulty": "simple", "first_action": "click"},
            {"task_id": "browser_2", "domain": "browser", "difficulty": "medium", "first_action": "type"},
            {"task_id": "browser_3", "domain": "browser", "difficulty": "hard", "first_action": "click"},
            {"task_id": "browser_4", "domain": "browser", "difficulty": "medium", "first_action": "wait"},

            # Office tasks (4)
            {"task_id": "excel_1", "domain": "office", "difficulty": "simple", "first_action": "click"},
            {"task_id": "word_1", "domain": "office", "difficulty": "medium", "first_action": "type"},
            {"task_id": "powerpoint_1", "domain": "office", "difficulty": "hard", "first_action": "click"},
            {"task_id": "excel_2", "domain": "office", "difficulty": "medium", "first_action": "type"},

            # System tasks (4)
            {"task_id": "file_explorer_1", "domain": "system", "difficulty": "simple", "first_action": "click"},
            {"task_id": "settings_1", "domain": "system", "difficulty": "medium", "first_action": "click"},
            {"task_id": "calculator_1", "domain": "system", "difficulty": "simple", "first_action": "type"},
            {"task_id": "file_explorer_2", "domain": "system", "difficulty": "hard", "first_action": "keyboard"},

            # Coding tasks (4)
            {"task_id": "vscode_1", "domain": "coding", "difficulty": "medium", "first_action": "click"},
            {"task_id": "terminal_1", "domain": "coding", "difficulty": "medium", "first_action": "type"},
            {"task_id": "vscode_2", "domain": "coding", "difficulty": "hard", "first_action": "keyboard"},
            {"task_id": "git_1", "domain": "coding", "difficulty": "hard", "first_action": "type"},
        ]
    }

    output_file = Path("phase0_tasks.json")
    with open(output_file, 'w') as f:
        json.dump(tasks, f, indent=2)

    print(f"Example tasks file created: {output_file}")
    print(f"Total tasks: {tasks['total_tasks']}")
    print(f"Domains: notepad (4), browser (4), office (4), system (4), coding (4)")


def main():
    """CLI for Phase 0 runner."""
    import argparse

    parser = argparse.ArgumentParser(description="Phase 0 Batch Runner")
    parser.add_argument(
        "--condition",
        choices=["zero-shot", "demo-conditioned"],
        required=False,
        help="Evaluation condition"
    )
    parser.add_argument(
        "--tasks",
        type=Path,
        help="Path to tasks JSON file"
    )
    parser.add_argument(
        "--task-id",
        help="Run single task (for testing)"
    )
    parser.add_argument(
        "--trials",
        type=int,
        default=3,
        help="Number of trials per task (default: 3)"
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Test run without API calls"
    )
    parser.add_argument(
        "--create-tasks",
        action="store_true",
        help="Create example tasks file"
    )

    args = parser.parse_args()

    if args.create_tasks:
        create_example_tasks_file()
        return

    if not args.condition:
        parser.print_help()
        return

    runner = Phase0Runner(
        condition=args.condition,
        tasks_file=args.tasks,
        trials=args.trials,
        dry_run=args.dry_run,
    )

    if args.task_id:
        # Run single task
        for model in runner.MODELS:
            for trial in range(1, args.trials + 1):
                runner.run_single_task(
                    task_id=args.task_id,
                    model=model,
                    trial=trial,
                )
    else:
        # Run full batch
        runner.run_batch()


if __name__ == "__main__":
    main()
