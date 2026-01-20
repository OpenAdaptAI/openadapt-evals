#!/usr/bin/env python3
"""
Demo Test Results Analysis Script

Analyzes results from demo-conditioned prompting tests, comparing baseline
(no demo) vs treatment (with demo) vs negative control (wrong demo).

Usage:
    python scripts/analyze_demo_results.py
    python scripts/analyze_demo_results.py --results-dir benchmark_results
    python scripts/analyze_demo_results.py --export results.json
"""

import json
import sys
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass
from statistics import mean, stdev
import argparse


@dataclass
class ScenarioResults:
    """Results for a test scenario"""
    name: str
    runs: int
    avg_success_rate: float
    avg_steps: float
    avg_time: float
    success_variance: float
    summaries: List[Dict]


def load_summary(result_dir: Path) -> Optional[Dict]:
    """Load summary.json from result directory"""
    summary_path = result_dir / "summary.json"
    if not summary_path.exists():
        print(f"Warning: No summary.json in {result_dir}", file=sys.stderr)
        return None

    try:
        with open(summary_path) as f:
            return json.load(f)
    except Exception as e:
        print(f"Error loading {summary_path}: {e}", file=sys.stderr)
        return None


def analyze_scenario(scenario_name: str, run_dirs: List[Path]) -> ScenarioResults:
    """Analyze multiple runs of same scenario"""
    summaries = [load_summary(run_dir) for run_dir in run_dirs]
    summaries = [s for s in summaries if s is not None]

    if not summaries:
        return ScenarioResults(
            name=scenario_name,
            runs=0,
            avg_success_rate=0.0,
            avg_steps=0.0,
            avg_time=0.0,
            success_variance=0.0,
            summaries=[]
        )

    success_rates = [s.get("success_rate", 0.0) for s in summaries]
    steps = [s.get("avg_steps", 0.0) for s in summaries]
    times = [s.get("avg_time_seconds", 0.0) for s in summaries]

    return ScenarioResults(
        name=scenario_name,
        runs=len(summaries),
        avg_success_rate=mean(success_rates),
        avg_steps=mean(steps),
        avg_time=mean(times),
        success_variance=max(success_rates) - min(success_rates) if len(success_rates) > 1 else 0.0,
        summaries=summaries
    )


def print_results(results: List[ScenarioResults]):
    """Print analysis results to console"""
    print("=" * 80)
    print("DEMO TEST RESULTS ANALYSIS")
    print("=" * 80)
    print()

    # Individual scenario results
    for result in results:
        print(f"{result.name}:")
        if result.runs == 0:
            print("  No valid results found")
            print()
            continue

        print(f"  Runs: {result.runs}")
        print(f"  Avg Success Rate: {result.avg_success_rate*100:.1f}%")
        print(f"  Avg Steps: {result.avg_steps:.1f}")
        print(f"  Avg Time: {result.avg_time:.1f}s")
        if result.runs > 1:
            print(f"  Success Variance: ±{result.success_variance*100:.1f}%")
        print()

    # Comparative analysis
    baseline = next((r for r in results if "baseline" in r.name.lower()), None)
    treatment = next((r for r in results if "treatment" in r.name.lower() or "with demo" in r.name.lower()), None)
    negative = next((r for r in results if "negative" in r.name.lower() or "wrong" in r.name.lower()), None)

    if baseline and treatment and baseline.runs > 0 and treatment.runs > 0:
        print("=" * 80)
        print("COMPARATIVE ANALYSIS")
        print("=" * 80)
        print()

        improvement = treatment.avg_success_rate - baseline.avg_success_rate
        step_change = treatment.avg_steps - baseline.avg_steps
        time_change = treatment.avg_time - baseline.avg_time

        print(f"Success Rate:")
        print(f"  Baseline (no demo): {baseline.avg_success_rate*100:.1f}%")
        print(f"  Treatment (with demo): {treatment.avg_success_rate*100:.1f}%")
        print(f"  Improvement: {improvement*100:+.1f} percentage points")
        print()

        print(f"Step Efficiency:")
        print(f"  Baseline: {baseline.avg_steps:.1f} steps")
        print(f"  Treatment: {treatment.avg_steps:.1f} steps")
        print(f"  Change: {step_change:+.1f} steps")
        print()

        print(f"Time Efficiency:")
        print(f"  Baseline: {baseline.avg_time:.1f}s")
        print(f"  Treatment: {treatment.avg_time:.1f}s")
        print(f"  Change: {time_change:+.1f}s")
        print()

        # Effect size interpretation
        if improvement >= 0.5:
            effect = "LARGE"
        elif improvement >= 0.3:
            effect = "MEDIUM"
        elif improvement >= 0.1:
            effect = "SMALL"
        else:
            effect = "NEGLIGIBLE"

        print(f"Effect Size: {effect}")
        print()

        # Negative control validation
        if negative and negative.runs > 0:
            print(f"Negative Control (wrong demo): {negative.avg_success_rate*100:.1f}%")
            if negative.avg_success_rate < treatment.avg_success_rate:
                print("  ✓ Negative control validates: wrong demo performs worse")
            else:
                print("  ✗ WARNING: Wrong demo performs as well or better!")
            print()

        # Success criteria evaluation
        print("=" * 80)
        print("SUCCESS CRITERIA EVALUATION")
        print("=" * 80)
        print()

        criteria = [
            ("Episode Success >50%", treatment.avg_success_rate > 0.5),
            ("Episode Success >80% (target)", treatment.avg_success_rate > 0.8),
            ("Improvement >30%", improvement > 0.3),
            ("Improvement >50% (large)", improvement > 0.5),
            ("Negative control valid", negative and negative.avg_success_rate < treatment.avg_success_rate if negative else None),
        ]

        for criterion, passed in criteria:
            if passed is None:
                status = "⊘ N/A"
            elif passed:
                status = "✓ PASS"
            else:
                status = "✗ FAIL"
            print(f"  {status}  {criterion}")
        print()


def export_results(results: List[ScenarioResults], output_path: Path):
    """Export results to JSON"""
    export_data = {
        "scenarios": [
            {
                "name": r.name,
                "runs": r.runs,
                "avg_success_rate": r.avg_success_rate,
                "avg_steps": r.avg_steps,
                "avg_time": r.avg_time,
                "success_variance": r.success_variance,
                "raw_summaries": r.summaries,
            }
            for r in results
        ]
    }

    with open(output_path, 'w') as f:
        json.dump(export_data, f, indent=2)

    print(f"Results exported to: {output_path}")


def main():
    parser = argparse.ArgumentParser(description="Analyze demo test results")
    parser.add_argument("--results-dir", type=Path, default=Path("benchmark_results"),
                      help="Directory containing test results")
    parser.add_argument("--export", type=Path, help="Export results to JSON file")
    args = parser.parse_args()

    results_dir = args.results_dir
    if not results_dir.exists():
        print(f"Error: Results directory not found: {results_dir}", file=sys.stderr)
        sys.exit(1)

    # Define scenarios (auto-discover or use predefined patterns)
    scenario_patterns = {
        "Baseline (No Demo)": ["baseline", "no_demo", "baseline_run"],
        "Treatment (With Demo)": ["treatment", "with_demo", "treatment_run"],
        "Negative Control (Wrong Demo)": ["negative", "wrong_demo"],
        "Retrieval Agent": ["retrieval"],
    }

    scenarios = {}
    for scenario_name, patterns in scenario_patterns.items():
        matching_dirs = []
        for pattern in patterns:
            matching_dirs.extend(results_dir.glob(f"*{pattern}*"))

        # Remove duplicates, sort by name
        matching_dirs = sorted(set(matching_dirs), key=lambda p: p.name)

        if matching_dirs:
            scenarios[scenario_name] = matching_dirs

    if not scenarios:
        print(f"No test results found in {results_dir}", file=sys.stderr)
        print("\nExpected directory patterns:", file=sys.stderr)
        for patterns in scenario_patterns.values():
            print(f"  - {', '.join(patterns)}", file=sys.stderr)
        sys.exit(1)

    # Analyze each scenario
    results = []
    for scenario_name, run_dirs in scenarios.items():
        result = analyze_scenario(scenario_name, run_dirs)
        results.append(result)

    # Print results
    print_results(results)

    # Export if requested
    if args.export:
        export_results(results, args.export)


if __name__ == "__main__":
    main()
