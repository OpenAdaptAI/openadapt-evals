#!/usr/bin/env python3
"""
Comprehensive cost analysis for demo validation approaches.
Based on research-backed data from academic papers and industry sources.
"""

import json
from dataclasses import dataclass
from typing import Dict, List

@dataclass
class CostEstimate:
    """Cost estimate with confidence intervals and sources."""
    low: float
    mid: float
    high: float
    unit: str
    sources: List[str]

    def __str__(self):
        return f"${self.low:.2f} - ${self.high:.2f} (median: ${self.mid:.2f}) {self.unit}"


class DemoValidationCostAnalysis:
    """Cost analysis for different demo validation approaches."""

    def __init__(self):
        # Demo statistics (from actual data)
        self.total_demos = 154
        self.avg_steps_per_demo = 12.7
        self.total_steps = 1955
        self.avg_tokens_per_demo = 513  # words * 1.3

        # API pricing (2026 rates)
        self.claude_sonnet_45_input = 3.0 / 1_000_000  # per token
        self.claude_sonnet_45_output = 15.0 / 1_000_000  # per token
        self.gpt_5_input = 1.25 / 1_000_000  # per token
        self.gpt_5_output = 10.0 / 1_000_000  # per token

        # Human annotation rates (from research)
        self.annotation_hourly_rates = {
            'offshore_basic': CostEstimate(2, 5, 8, 'per hour',
                ['BasicAI 2025', 'Second Talent 2026']),
            'mid_tier': CostEstimate(10, 15, 25, 'per hour',
                ['Upwork median rates', 'ZipRecruiter 2026']),
            'us_specialist': CostEstimate(40, 60, 100, 'per hour',
                ['Scale AI reported', 'Domain expert rates']),
        }

        # Time estimates from research
        self.time_per_demo_minutes = {
            'simple_review': CostEstimate(2, 3, 5, 'minutes',
                ['Benchmark task duration standards', 'UX research']),
            'detailed_validation': CostEstimate(5, 8, 12, 'minutes',
                ['Mind2Web annotation methodology', 'OSWorld expert validation']),
            'full_execution_test': CostEstimate(10, 15, 25, 'minutes',
                ['WAA task completion estimates', 'Desktop automation benchmarks']),
        }

        # Azure compute costs
        self.azure_d4s_v3_hourly = 0.192  # 4 vCPUs, 16 GB RAM

        # Success rates from research
        self.success_rates = {
            'synthetic_demo_quality': 0.819,  # Diffusion RL study
            'llm_judge_human_agreement': 0.80,  # GPT-4 agreement rate
            'automated_regen_success': 0.53,  # Upper bound from self-edit loops
        }

    def path_1_llm_judge_full(self) -> Dict:
        """Path 1: LLM-as-Judge on all 154 demos."""
        # Estimate tokens per evaluation
        input_tokens_per_demo = self.avg_tokens_per_demo + 500  # demo + prompt
        output_tokens_per_demo = 300  # judgment + explanation

        # Claude Sonnet 4.5 costs
        claude_input_cost = self.total_demos * input_tokens_per_demo * self.claude_sonnet_45_input
        claude_output_cost = self.total_demos * output_tokens_per_demo * self.claude_sonnet_45_output
        claude_total = claude_input_cost + claude_output_cost

        # GPT-5 costs
        gpt_input_cost = self.total_demos * input_tokens_per_demo * self.gpt_5_input
        gpt_output_cost = self.total_demos * output_tokens_per_demo * self.gpt_5_output
        gpt_total = gpt_input_cost + gpt_output_cost

        # Human validation of 10% flagged cases (conservative)
        flagged_demos = int(self.total_demos * 0.10)
        time_per_flagged = self.time_per_demo_minutes['detailed_validation']
        total_hours = flagged_demos * time_per_flagged.mid / 60
        human_cost_low = total_hours * self.annotation_hourly_rates['mid_tier'].low
        human_cost_high = total_hours * self.annotation_hourly_rates['mid_tier'].high

        return {
            'approach': 'LLM-as-Judge on All Demos',
            'api_model_claude': f'${claude_total:.2f}',
            'api_model_gpt5': f'${gpt_total:.2f}',
            'human_validation': f'${human_cost_low:.2f} - ${human_cost_high:.2f}',
            'total_low': claude_total + human_cost_low,
            'total_high': gpt_total + human_cost_high,
            'time_estimate_days': 1,
            'expected_accuracy': '80% agreement with human judgment',
            'sources': [
                'G-Eval: 0.514 Spearman correlation',
                'GPT-4 80% human agreement rate',
                'Claude Sonnet 4.5 pricing: $3/$15 per 1M tokens'
            ]
        }

    def path_2_stratified_sample(self) -> Dict:
        """Path 2: Stratified sample (20% validation, 80% accept)."""
        sample_size = int(self.total_demos * 0.20)  # 31 demos

        # Human validation costs
        time_per_demo = self.time_per_demo_minutes['detailed_validation']
        total_hours = sample_size * time_per_demo.mid / 60

        cost_low = total_hours * self.annotation_hourly_rates['mid_tier'].low
        cost_mid = total_hours * self.annotation_hourly_rates['mid_tier'].mid
        cost_high = total_hours * self.annotation_hourly_rates['mid_tier'].high

        # Risk: 80% unvalidated
        unvalidated = self.total_demos - sample_size
        expected_errors = unvalidated * (1 - self.success_rates['synthetic_demo_quality'])

        return {
            'approach': 'Stratified Sample (20%)',
            'sample_size': sample_size,
            'total_cost_low': cost_low,
            'total_cost_mid': cost_mid,
            'total_cost_high': cost_high,
            'time_estimate_days': 1,
            'unvalidated_demos': unvalidated,
            'expected_errors_undetected': f'{expected_errors:.1f}',
            'risk_level': 'Medium - 80% unvalidated',
            'sources': [
                'AQL sampling standards (MIL-STD 105E)',
                'Statistical tolerance interval methods'
            ]
        }

    def path_3_full_human_validation(self) -> Dict:
        """Path 3: Full human validation of all 154 demos."""
        time_per_demo = self.time_per_demo_minutes['detailed_validation']
        total_hours = self.total_demos * time_per_demo.mid / 60

        # Different cost tiers
        costs = {}
        for tier, rate in self.annotation_hourly_rates.items():
            costs[tier] = {
                'low': total_hours * rate.low,
                'mid': total_hours * rate.mid,
                'high': total_hours * rate.high,
            }

        return {
            'approach': 'Full Human Validation',
            'demos_validated': self.total_demos,
            'total_hours': f'{total_hours:.1f}',
            'offshore_basic': f"${costs['offshore_basic']['low']:.2f} - ${costs['offshore_basic']['high']:.2f}",
            'mid_tier': f"${costs['mid_tier']['low']:.2f} - ${costs['mid_tier']['high']:.2f}",
            'us_specialist': f"${costs['us_specialist']['low']:.2f} - ${costs['us_specialist']['high']:.2f}",
            'time_estimate_days': 2,
            'expected_accuracy': '95-100% (gold standard)',
            'sources': [
                'Mind2Web: 1000+ hours for expert annotation',
                'OSWorld: 1800 person-hours for 369 tasks',
                'Upwork/ZipRecruiter 2026 rates'
            ]
        }

    def path_4_automated_execution(self) -> Dict:
        """Path 4: Automated execution testing on Azure."""
        # VM costs
        hours_per_demo = 0.25  # 15 minutes avg
        total_vm_hours = self.total_demos * hours_per_demo
        vm_cost = total_vm_hours * self.azure_d4s_v3_hourly

        # API costs for agent execution
        # Assume 500 tokens input per step, 200 tokens output
        tokens_per_step = 700
        total_tokens = self.total_steps * tokens_per_step

        api_cost_claude = (total_tokens * 0.5 * self.claude_sonnet_45_input +
                          total_tokens * 0.5 * self.claude_sonnet_45_output)
        api_cost_gpt = (total_tokens * 0.5 * self.gpt_5_input +
                       total_tokens * 0.5 * self.gpt_5_output)

        # Human review of failures (assume 30% fail)
        failed_demos = int(self.total_demos * 0.30)
        review_hours = failed_demos * 10 / 60  # 10 min per failure
        review_cost_low = review_hours * self.annotation_hourly_rates['mid_tier'].low
        review_cost_high = review_hours * self.annotation_hourly_rates['mid_tier'].high

        return {
            'approach': 'Automated Execution Testing',
            'vm_hours': f'{total_vm_hours:.1f}',
            'vm_cost': f'${vm_cost:.2f}',
            'api_cost_claude': f'${api_cost_claude:.2f}',
            'api_cost_gpt5': f'${api_cost_gpt:.2f}',
            'human_review': f'${review_cost_low:.2f} - ${review_cost_high:.2f}',
            'total_low': vm_cost + api_cost_gpt + review_cost_low,
            'total_high': vm_cost + api_cost_claude + review_cost_high,
            'time_estimate_days': 2,
            'expected_detection_rate': '70-90% of errors',
            'sources': [
                'Azure D4s_v3: $0.192/hour',
                'WAA paper: 20 min parallel evaluation',
                'PC Agent-E: 141% improvement with validation'
            ]
        }

    def path_5_hybrid_recommended(self) -> Dict:
        """Path 5: Hybrid approach (LLM + stratified human + selective execution)."""
        # Stage 1: LLM-as-Judge on all demos
        path1 = self.path_1_llm_judge_full()
        llm_cost = (float(path1['api_model_claude'].replace('$', '')) +
                    float(path1['api_model_gpt5'].replace('$', ''))) / 2

        # Stage 2: Human validation of 15% (10% flagged + 5% random)
        sample_size = int(self.total_demos * 0.15)
        validation_hours = sample_size * self.time_per_demo_minutes['detailed_validation'].mid / 60
        human_cost_low = validation_hours * self.annotation_hourly_rates['mid_tier'].low
        human_cost_high = validation_hours * self.annotation_hourly_rates['mid_tier'].high

        # Stage 3: Execution testing on 10 high-risk demos
        execution_demos = 10
        exec_vm_hours = execution_demos * 0.25
        exec_vm_cost = exec_vm_hours * self.azure_d4s_v3_hourly
        exec_api_cost = execution_demos * 12.7 * 700 * self.claude_sonnet_45_input * 1.5

        total_low = llm_cost + human_cost_low + exec_vm_cost + exec_api_cost
        total_high = llm_cost + human_cost_high + exec_vm_cost + exec_api_cost

        return {
            'approach': 'Hybrid (LLM + Human + Execution)',
            'stage_1_llm': f'${llm_cost:.2f}',
            'stage_2_human': f'${human_cost_low:.2f} - ${human_cost_high:.2f}',
            'stage_3_execution': f'${exec_vm_cost + exec_api_cost:.2f}',
            'total_low': total_low,
            'total_high': total_high,
            'time_estimate_days': 2,
            'coverage': '100% LLM reviewed, 15% human validated, 10 execution tested',
            'expected_quality': '90-95% confidence',
            'sources': [
                'Hybrid approaches: 80% cost reduction vs full human',
                'Sample-based validation with high confidence',
                'Execution testing for high-risk cases'
            ]
        }

    def generate_report(self) -> Dict:
        """Generate comprehensive cost analysis report."""
        return {
            'metadata': {
                'total_demos': self.total_demos,
                'avg_steps_per_demo': self.avg_steps_per_demo,
                'total_steps': self.total_steps,
                'current_status': '100% format-validated, 0% execution-validated',
                'generation_date': '2026-01-18',
            },
            'approaches': {
                'path_1_llm_judge': self.path_1_llm_judge_full(),
                'path_2_stratified_sample': self.path_2_stratified_sample(),
                'path_3_full_human': self.path_3_full_human_validation(),
                'path_4_automated_execution': self.path_4_automated_execution(),
                'path_5_hybrid_recommended': self.path_5_hybrid_recommended(),
            },
            'research_findings': {
                'synthetic_demo_quality': {
                    'success_rate': '81.9%',
                    'source': 'Diffusion RL study - synthetic data outperforming human',
                    'url': 'https://arxiv.org/html/2509.19752v1'
                },
                'llm_judge_effectiveness': {
                    'agreement_rate': '80%',
                    'cost_savings': '500x-5000x vs human',
                    'source': 'LLM-as-a-Judge research 2025',
                    'url': 'https://cameronrwolfe.substack.com/p/llm-as-a-judge'
                },
                'pc_agent_e_efficiency': {
                    'trajectories': '312 human demonstrations',
                    'improvement': '141% relative improvement',
                    'source': 'PC Agent-E paper',
                    'url': 'https://arxiv.org/html/2505.13909v1'
                },
                'annotation_time_estimates': {
                    'simple_tasks': '2-5 minutes',
                    'complex_tasks': '5-12 minutes',
                    'expert_validation': '10-25 minutes',
                    'sources': [
                        'METR: 50-200+ minute horizons for complex tasks',
                        'Mind2Web: 1000+ hours for benchmark construction',
                        'OSWorld: 1800 person-hours for 369 tasks'
                    ]
                }
            },
            'pricing_references': {
                'api_costs': {
                    'claude_sonnet_45': '$3 input / $15 output per 1M tokens',
                    'gpt_5': '$1.25 input / $10 output per 1M tokens',
                    'batch_discount': '50% off for async processing',
                },
                'human_annotation': {
                    'offshore_basic': '$2-8/hour (Africa, Asia)',
                    'mid_tier': '$10-25/hour (Upwork median)',
                    'us_specialist': '$40-100/hour (domain experts)',
                },
                'infrastructure': {
                    'azure_d4s_v3': '$0.192/hour (4 vCPU, 16 GB)',
                    'storage': 'Negligible for demo artifacts',
                }
            }
        }


def main():
    """Generate and display cost analysis."""
    analysis = DemoValidationCostAnalysis()
    report = analysis.generate_report()

    # Save to JSON
    output_file = '/Users/abrichr/oa/src/openadapt-evals/demo_validation_cost_report.json'
    with open(output_file, 'w') as f:
        json.dump(report, f, indent=2)

    print(f"Cost analysis report saved to: {output_file}")
    print("\n" + "="*80)
    print("DEMO VALIDATION COST ANALYSIS SUMMARY")
    print("="*80)

    print(f"\nTotal Demos: {report['metadata']['total_demos']}")
    print(f"Average Steps: {report['metadata']['avg_steps_per_demo']}")
    print(f"Current Status: {report['metadata']['current_status']}")

    print("\n" + "-"*80)
    print("COST COMPARISON BY APPROACH")
    print("-"*80)

    for path_name, path_data in report['approaches'].items():
        print(f"\n{path_data['approach']}:")
        if 'total_low' in path_data:
            print(f"  Total Cost: ${path_data['total_low']:.2f} - ${path_data['total_high']:.2f}")
        if 'time_estimate_days' in path_data:
            print(f"  Time Estimate: {path_data['time_estimate_days']} days")
        if 'expected_accuracy' in path_data:
            print(f"  Quality: {path_data['expected_accuracy']}")
        elif 'expected_quality' in path_data:
            print(f"  Quality: {path_data['expected_quality']}")

    print("\n" + "="*80)
    print("RECOMMENDATION: Path 5 - Hybrid Approach")
    print("="*80)
    hybrid = report['approaches']['path_5_hybrid_recommended']
    print(f"Total Cost: ${hybrid['total_low']:.2f} - ${hybrid['total_high']:.2f}")
    print(f"Timeline: {hybrid['time_estimate_days']} days")
    print(f"Coverage: {hybrid['coverage']}")
    print(f"Expected Quality: {hybrid['expected_quality']}")

    return report


if __name__ == '__main__':
    main()
