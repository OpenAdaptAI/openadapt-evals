#!/usr/bin/env python3
"""
Phase 0 Results Analysis Script

Analyzes Phase 0 prompting baseline results, comparing zero-shot vs demo-conditioned
performance across models and tasks.

Statistical tests:
- McNemar's test for paired binary outcomes
- Bootstrap confidence intervals
- Effect size calculation (Cohen's h)

Usage:
    python scripts/phase0_analyze.py
    python scripts/phase0_analyze.py --results-dir phase0_results
    python scripts/phase0_analyze.py --export analysis.json
    python scripts/phase0_analyze.py --plot
"""

import json
import sys
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, asdict
from statistics import mean, stdev, median
from collections import defaultdict
import argparse


@dataclass
class TaskResult:
    """Result for a single task evaluation"""
    task_id: str
    model: str
    condition: str
    trial: int
    success: bool
    steps: int
    cost: float
    error: Optional[str] = None


@dataclass
class ConditionStats:
    """Statistics for a condition"""
    condition: str
    model: str
    n_tasks: int
    n_trials: int
    success_rate: float
    avg_steps: float
    std_steps: float
    median_steps: float
    total_cost: float
    failures: List[str]


@dataclass
class ComparisonResult:
    """Comparison between two conditions"""
    model: str
    baseline_success_rate: float
    treatment_success_rate: float
    improvement_pp: float  # percentage points
    mcnemar_p_value: float
    effect_size: float  # Cohen's h
    ci_lower: float
    ci_upper: float
    significant: bool


def load_result_file(file_path: Path) -> Optional[TaskResult]:
    """Load a single result JSON file"""
    try:
        with open(file_path) as f:
            data = json.load(f)

        # Extract task_id from filename
        filename = file_path.stem
        parts = filename.rsplit('_trial', 1)
        task_id = parts[0]
        trial = int(parts[1]) if len(parts) > 1 else 1

        # Determine condition and model from path
        condition = file_path.parent.parent.name
        model = file_path.parent.name

        # Extract metrics
        summary = data.get("summary", {})
        success = summary.get("episode_success", False)
        steps = summary.get("total_steps", 0)
        cost = summary.get("total_cost", 0.0)
        error = summary.get("error")

        return TaskResult(
            task_id=task_id,
            model=model,
            condition=condition,
            trial=trial,
            success=success,
            steps=steps,
            cost=cost,
            error=error,
        )
    except Exception as e:
        print(f"Warning: Failed to load {file_path}: {e}", file=sys.stderr)
        return None


def load_all_results(results_dir: Path) -> List[TaskResult]:
    """Load all result files from directory"""
    results = []

    for json_file in results_dir.rglob("*.json"):
        # Skip checkpoint and cost log files
        if json_file.name.startswith('.'):
            continue

        result = load_result_file(json_file)
        if result:
            results.append(result)

    return results


def compute_condition_stats(results: List[TaskResult], condition: str, model: str) -> ConditionStats:
    """Compute statistics for a condition"""
    filtered = [r for r in results if r.condition == condition and r.model == model]

    if not filtered:
        return ConditionStats(
            condition=condition,
            model=model,
            n_tasks=0,
            n_trials=0,
            success_rate=0.0,
            avg_steps=0.0,
            std_steps=0.0,
            median_steps=0.0,
            total_cost=0.0,
            failures=[],
        )

    successes = [r.success for r in filtered]
    steps = [r.steps for r in filtered]
    costs = [r.cost for r in filtered]
    failures = [r.task_id for r in filtered if not r.success]

    # Count unique tasks
    unique_tasks = len(set(r.task_id for r in filtered))

    return ConditionStats(
        condition=condition,
        model=model,
        n_tasks=unique_tasks,
        n_trials=len(filtered),
        success_rate=sum(successes) / len(successes) if successes else 0.0,
        avg_steps=mean(steps) if steps else 0.0,
        std_steps=stdev(steps) if len(steps) > 1 else 0.0,
        median_steps=median(steps) if steps else 0.0,
        total_cost=sum(costs),
        failures=list(set(failures)),
    )


def mcnemar_test(a_success: List[bool], b_success: List[bool]) -> float:
    """
    McNemar's test for paired binary outcomes
    Returns p-value
    """
    if len(a_success) != len(b_success):
        raise ValueError("Lists must have same length")

    # Build contingency table
    # b=1  b=0
    # a=1  n11  n10
    # a=0  n01  n00

    n10 = sum(1 for a, b in zip(a_success, b_success) if a and not b)
    n01 = sum(1 for a, b in zip(a_success, b_success) if not a and b)

    # McNemar's chi-squared statistic with continuity correction
    if n10 + n01 == 0:
        return 1.0  # No discordant pairs

    chi2 = ((abs(n10 - n01) - 1) ** 2) / (n10 + n01)

    # Approximate p-value using chi-squared distribution with 1 df
    # For simplicity, using critical values:
    # chi2 > 3.84 -> p < 0.05
    # chi2 > 6.63 -> p < 0.01
    # chi2 > 10.83 -> p < 0.001
    if chi2 > 10.83:
        return 0.001
    elif chi2 > 6.63:
        return 0.01
    elif chi2 > 3.84:
        return 0.05
    else:
        return 0.10  # Not significant


def cohens_h(p1: float, p2: float) -> float:
    """
    Cohen's h effect size for proportions
    """
    import math

    phi1 = 2 * math.asin(math.sqrt(p1))
    phi2 = 2 * math.asin(math.sqrt(p2))
    return phi1 - phi2


def bootstrap_ci(a_success: List[bool], b_success: List[bool], n_bootstrap: int = 10000) -> Tuple[float, float]:
    """
    Bootstrap confidence interval for difference in success rates
    Returns (lower, upper) 95% CI
    """
    import random

    differences = []
    n = len(a_success)

    for _ in range(n_bootstrap):
        # Resample with replacement
        indices = [random.randint(0, n - 1) for _ in range(n)]
        a_sample = [a_success[i] for i in indices]
        b_sample = [b_success[i] for i in indices]

        a_rate = sum(a_sample) / len(a_sample)
        b_rate = sum(b_sample) / len(b_sample)
        differences.append(b_rate - a_rate)

    differences.sort()
    lower_idx = int(0.025 * n_bootstrap)
    upper_idx = int(0.975 * n_bootstrap)

    return differences[lower_idx], differences[upper_idx]


def compare_conditions(
    results: List[TaskResult],
    model: str,
    baseline: str = "zero-shot",
    treatment: str = "demo-conditioned",
) -> ComparisonResult:
    """
    Compare two conditions using paired statistical tests
    """
    # Get results for each condition
    baseline_results = [r for r in results if r.condition == baseline and r.model == model]
    treatment_results = [r for r in results if r.condition == treatment and r.model == model]

    # Group by task (average across trials)
    baseline_by_task = defaultdict(list)
    treatment_by_task = defaultdict(list)

    for r in baseline_results:
        baseline_by_task[r.task_id].append(r.success)

    for r in treatment_results:
        treatment_by_task[r.task_id].append(r.success)

    # Get paired success rates
    paired_tasks = set(baseline_by_task.keys()) & set(treatment_by_task.keys())

    baseline_success = []
    treatment_success = []

    for task in sorted(paired_tasks):
        # Average across trials
        baseline_success.append(sum(baseline_by_task[task]) / len(baseline_by_task[task]) >= 0.5)
        treatment_success.append(sum(treatment_by_task[task]) / len(treatment_by_task[task]) >= 0.5)

    # Compute statistics
    baseline_rate = sum(baseline_success) / len(baseline_success) if baseline_success else 0.0
    treatment_rate = sum(treatment_success) / len(treatment_success) if treatment_success else 0.0
    improvement = treatment_rate - baseline_rate

    # McNemar's test
    p_value = mcnemar_test(baseline_success, treatment_success)

    # Effect size
    effect_size = cohens_h(baseline_rate, treatment_rate)

    # Bootstrap CI
    ci_lower, ci_upper = bootstrap_ci(baseline_success, treatment_success)

    return ComparisonResult(
        model=model,
        baseline_success_rate=baseline_rate,
        treatment_success_rate=treatment_rate,
        improvement_pp=improvement * 100,  # Convert to percentage points
        mcnemar_p_value=p_value,
        effect_size=effect_size,
        ci_lower=ci_lower * 100,
        ci_upper=ci_upper * 100,
        significant=p_value < 0.05,
    )


def analyze_failure_modes(results: List[TaskResult]) -> Dict[str, List[str]]:
    """
    Categorize failure modes by condition
    """
    failures = defaultdict(list)

    for r in results:
        if not r.success:
            key = f"{r.condition}/{r.model}"
            failures[key].append(r.task_id)

    return dict(failures)


def print_stats(stats: ConditionStats):
    """Print statistics for a condition"""
    print(f"\n{stats.condition.upper()} ({stats.model})")
    print(f"{'=' * 60}")
    print(f"Tasks:        {stats.n_tasks}")
    print(f"Trials:       {stats.n_trials}")
    print(f"Success Rate: {stats.success_rate * 100:.1f}%")
    print(f"Avg Steps:    {stats.avg_steps:.1f} ± {stats.std_steps:.1f}")
    print(f"Median Steps: {stats.median_steps:.0f}")
    print(f"Total Cost:   ${stats.total_cost:.2f}")

    if stats.failures:
        print(f"\nFailed Tasks ({len(stats.failures)}):")
        for task in sorted(stats.failures)[:5]:
            print(f"  - {task}")
        if len(stats.failures) > 5:
            print(f"  ... and {len(stats.failures) - 5} more")


def print_comparison(comp: ComparisonResult):
    """Print comparison results"""
    print(f"\n{'=' * 60}")
    print(f"COMPARISON: Zero-Shot vs Demo-Conditioned ({comp.model})")
    print(f"{'=' * 60}")
    print(f"Baseline Success Rate:   {comp.baseline_success_rate * 100:.1f}%")
    print(f"Treatment Success Rate:  {comp.treatment_success_rate * 100:.1f}%")
    print(f"Improvement:             {comp.improvement_pp:+.1f} pp")
    print(f"95% CI:                  [{comp.ci_lower:+.1f}, {comp.ci_upper:+.1f}] pp")
    print(f"Effect Size (Cohen's h): {comp.effect_size:.3f}")
    print(f"McNemar's p-value:       {comp.mcnemar_p_value:.4f}")
    print(f"Significant (p<0.05):    {'YES' if comp.significant else 'NO'}")

    # Interpretation
    print("\nInterpretation:")
    if abs(comp.improvement_pp) < 5:
        interpretation = "Negligible difference"
    elif abs(comp.improvement_pp) < 10:
        interpretation = "Small improvement"
    elif abs(comp.improvement_pp) < 20:
        interpretation = "Moderate improvement"
    else:
        interpretation = "Large improvement"

    print(f"  Effect Size: {interpretation}")

    if comp.significant:
        print(f"  Statistical Significance: YES (p={comp.mcnemar_p_value:.4f})")
    else:
        print(f"  Statistical Significance: NO (p={comp.mcnemar_p_value:.4f})")

    # Decision gate
    print("\nDecision Gate:")
    if comp.improvement_pp > 20:
        print("  ✓ PROCEED to Phase 1 (>20pp improvement)")
    elif comp.improvement_pp > 10:
        print("  ? BORDERLINE - Cost-benefit analysis needed (10-20pp)")
    else:
        print("  ✗ DO NOT PROCEED - Improvement too small (<10pp)")


def main():
    parser = argparse.ArgumentParser(description="Analyze Phase 0 results")
    parser.add_argument(
        "--results-dir",
        type=Path,
        default=Path("phase0_results"),
        help="Results directory (default: phase0_results)",
    )
    parser.add_argument(
        "--export",
        type=Path,
        help="Export analysis to JSON file",
    )
    parser.add_argument(
        "--plot",
        action="store_true",
        help="Generate plots (requires matplotlib)",
    )

    args = parser.parse_args()

    if not args.results_dir.exists():
        print(f"Error: Results directory not found: {args.results_dir}", file=sys.stderr)
        sys.exit(1)

    # Load all results
    print(f"Loading results from {args.results_dir}...")
    results = load_all_results(args.results_dir)
    print(f"Loaded {len(results)} evaluation results")

    if not results:
        print("Error: No results found", file=sys.stderr)
        sys.exit(1)

    # Get unique models and conditions
    models = sorted(set(r.model for r in results))
    conditions = sorted(set(r.condition for r in results))

    print(f"Models: {', '.join(models)}")
    print(f"Conditions: {', '.join(conditions)}")

    # Compute statistics for each condition
    all_stats = []
    for model in models:
        for condition in conditions:
            stats = compute_condition_stats(results, condition, model)
            all_stats.append(stats)
            print_stats(stats)

    # Compare conditions
    comparisons = []
    for model in models:
        comp = compare_conditions(results, model)
        comparisons.append(comp)
        print_comparison(comp)

    # Failure mode analysis
    print(f"\n{'=' * 60}")
    print("FAILURE MODE ANALYSIS")
    print(f"{'=' * 60}")
    failures = analyze_failure_modes(results)
    for key, tasks in sorted(failures.items()):
        print(f"\n{key}: {len(tasks)} failures")
        for task in sorted(tasks)[:5]:
            print(f"  - {task}")
        if len(tasks) > 5:
            print(f"  ... and {len(tasks) - 5} more")

    # Export to JSON
    if args.export:
        export_data = {
            "statistics": [asdict(s) for s in all_stats],
            "comparisons": [asdict(c) for c in comparisons],
            "failures": failures,
        }

        with open(args.export, 'w') as f:
            json.dump(export_data, f, indent=2)

        print(f"\nExported analysis to {args.export}")

    # Generate plots
    if args.plot:
        try:
            import matplotlib.pyplot as plt

            # Success rate comparison
            fig, ax = plt.subplots(figsize=(10, 6))

            for model in models:
                baseline_stats = next(s for s in all_stats if s.model == model and s.condition == "zero-shot")
                treatment_stats = next(s for s in all_stats if s.model == model and s.condition == "demo-conditioned")

                x = [0, 1]
                y = [baseline_stats.success_rate * 100, treatment_stats.success_rate * 100]
                ax.plot(x, y, marker='o', label=model)

            ax.set_xticks([0, 1])
            ax.set_xticklabels(['Zero-Shot', 'Demo-Conditioned'])
            ax.set_ylabel('Success Rate (%)')
            ax.set_title('Phase 0: Success Rate by Condition')
            ax.legend()
            ax.grid(True, alpha=0.3)

            plt.tight_layout()
            plot_file = args.results_dir / "success_rate_comparison.png"
            plt.savefig(plot_file, dpi=150)
            print(f"\nSaved plot to {plot_file}")

        except ImportError:
            print("\nWarning: matplotlib not installed, skipping plots", file=sys.stderr)


if __name__ == "__main__":
    main()
