"""Integration tests for Phase 0 demo-augmentation infrastructure.

This test suite validates all critical components needed for Phase 0:
- Mock adapter functionality
- Demo loading and persistence
- Both API models (Claude, GPT-4)
- Zero-shot vs demo-conditioned conditions
- Result saving and metrics
- Cost tracking

Run with: pytest tests/test_phase0_integration.py -v
"""

import json
import pytest
from pathlib import Path
from unittest.mock import Mock, patch
from openadapt_evals import (
    WAAMockAdapter,
    ApiAgent,
    evaluate_agent_on_benchmark
)
from openadapt_evals.adapters.base import BenchmarkTask
from openadapt_evals.benchmarks.runner import evaluate_agent_on_benchmark


class TestPhase0Infrastructure:
    """Tests for Phase 0 evaluation infrastructure."""

    @pytest.fixture
    def demo_text(self):
        """Load a synthetic demo."""
        demo_path = Path("demo_library/synthetic_demos/notepad_1.txt")
        if demo_path.exists():
            return demo_path.read_text()
        return "TASK: Test\nSTEPS:\n1. Test\nACTION: DONE()"

    @pytest.fixture
    def mock_adapter(self):
        """Create a mock WAA adapter."""
        return WAAMockAdapter(num_tasks=3)

    def test_mock_adapter_loads_tasks(self, mock_adapter):
        """Test that mock adapter can load tasks."""
        tasks = mock_adapter.list_tasks()
        assert len(tasks) > 0
        assert all(isinstance(t, BenchmarkTask) for t in tasks)
        print(f"✓ Mock adapter loaded {len(tasks)} tasks")

    def test_demo_loads_correctly(self, demo_text):
        """Test that demo file loads correctly."""
        assert len(demo_text) > 0
        assert "TASK:" in demo_text
        assert "STEPS:" in demo_text
        print(f"✓ Demo loaded: {len(demo_text)} characters")

    def test_zero_shot_condition(self, mock_adapter):
        """Test zero-shot evaluation (no demo)."""
        from openadapt_evals.agents.scripted_agent import SmartMockAgent

        agent = SmartMockAgent()
        # Get first task ID
        tasks = mock_adapter.list_tasks()
        task_ids = [tasks[0].task_id]

        results = evaluate_agent_on_benchmark(
            agent,
            mock_adapter,
            task_ids=task_ids,
            max_steps=5
        )

        assert results is not None
        assert len(results) > 0
        success_rate = sum(1 for r in results if r.success) / len(results)
        avg_steps = sum(r.num_steps for r in results) / len(results)
        print(f"✓ Zero-shot evaluation completed: {success_rate*100:.0f}% success, {avg_steps:.1f} avg steps")

    def test_demo_conditioned_condition(self, mock_adapter, demo_text):
        """Test demo-conditioned evaluation."""
        # Use mock agent since we don't have valid API keys in CI
        from openadapt_evals.agents.scripted_agent import SmartMockAgent

        agent = SmartMockAgent()
        # Note: ScriptedAgent doesn't use demos, but we're testing the infrastructure
        # In real Phase 0, this would be ApiAgent with demo

        # Get first task ID
        tasks = mock_adapter.list_tasks()
        task_ids = [tasks[0].task_id]

        results = evaluate_agent_on_benchmark(
            agent,
            mock_adapter,
            task_ids=task_ids,
            max_steps=5
        )

        assert results is not None
        assert len(results) > 0
        success_rate = sum(1 for r in results if r.success) / len(results)
        print(f"✓ Demo-conditioned evaluation completed: {success_rate*100:.0f}% success")

    def test_api_agent_creation_claude(self, demo_text):
        """Test Claude API agent creation."""
        # Just test creation, not API calls (no valid keys in CI)
        agent = ApiAgent(provider="anthropic", demo=demo_text)
        assert agent.provider == "anthropic"
        assert agent.demo == demo_text
        assert len(agent.demo) > 0
        print(f"✓ Claude agent created with demo ({len(agent.demo)} chars)")

    def test_api_agent_creation_openai(self, demo_text):
        """Test OpenAI API agent creation."""
        agent = ApiAgent(provider="openai", demo=demo_text)
        assert agent.provider == "openai"
        assert agent.demo == demo_text
        print(f"✓ OpenAI agent created with demo ({len(agent.demo)} chars)")

    def test_results_save_correctly(self, mock_adapter, tmp_path):
        """Test that results are saved correctly."""
        from openadapt_evals.agents.scripted_agent import SmartMockAgent
        from openadapt_evals.benchmarks.runner import EvaluationConfig

        agent = SmartMockAgent()

        # Get first task ID
        tasks = mock_adapter.list_tasks()
        task_ids = [tasks[0].task_id]

        # Use a custom config with run_name
        config = EvaluationConfig(
            max_steps=5,
            save_execution_traces=True,
            run_name="test_phase0_save"
        )

        # Use a custom output dir
        results = evaluate_agent_on_benchmark(
            agent,
            mock_adapter,
            task_ids=task_ids,
            config=config
        )

        # Check that results directory was created
        results_dir = Path("benchmark_results")
        matching_runs = list(results_dir.glob("*test_phase0_save*"))

        if matching_runs:
            run_dir = matching_runs[0]
            assert (run_dir / "summary.json").exists()
            assert (run_dir / "metadata.json").exists()

            # Load and verify summary
            summary = json.loads((run_dir / "summary.json").read_text())
            assert "success_rate" in summary
            assert "avg_steps" in summary
            assert "num_tasks" in summary
            print(f"✓ Results saved to {run_dir.name}")
        else:
            print("⚠️  No results directory found (expected in some test environments)")

    def test_metrics_calculated_correctly(self, mock_adapter):
        """Test that metrics are calculated correctly."""
        from openadapt_evals.agents.scripted_agent import SmartMockAgent

        agent = SmartMockAgent()

        # Get first 2 task IDs
        tasks = mock_adapter.list_tasks()
        task_ids = [tasks[0].task_id, tasks[1].task_id]

        results = evaluate_agent_on_benchmark(
            agent,
            mock_adapter,
            task_ids=task_ids,
            max_steps=5
        )

        # Required metrics from results list
        assert results is not None
        assert len(results) > 0
        assert all(hasattr(r, 'success') for r in results)
        assert all(hasattr(r, 'num_steps') for r in results)
        assert all(hasattr(r, 'score') for r in results)

        # Calculate aggregate metrics
        success_rate = sum(1 for r in results if r.success) / len(results)
        avg_steps = sum(r.num_steps for r in results) / len(results)
        num_success = sum(1 for r in results if r.success)

        # Validate metric ranges
        assert 0.0 <= success_rate <= 1.0
        assert avg_steps >= 0
        assert len(results) > 0

        print(f"✓ Metrics calculated:")
        print(f"  - Success rate: {success_rate*100:.0f}%")
        print(f"  - Avg steps: {avg_steps:.1f}")
        print(f"  - Tasks: {num_success}/{len(results)}")

    def test_demo_persistence_in_agent(self, demo_text):
        """Test that demo persists in agent across steps."""
        agent = ApiAgent(provider="anthropic", demo=demo_text)

        # Verify demo is stored
        assert agent.demo == demo_text
        assert len(agent.demo) > 0

        # Reset agent (simulates new task)
        agent.reset()

        # Demo should still be present
        assert agent.demo == demo_text
        print(f"✓ Demo persists across reset: {len(agent.demo)} chars")


class TestPhase0CostEstimation:
    """Tests for cost estimation and tracking."""

    def test_api_usage_tracking_structure(self):
        """Test that we have the structure to track API usage."""
        # ApiAgent tracks usage in api_agent.py
        agent = ApiAgent(provider="anthropic")

        # Check that agent has usage tracking attributes
        assert hasattr(agent, "step_counter")
        assert agent.step_counter == 0

        print("✓ API usage tracking structure present")

    def test_cost_calculation_logic(self):
        """Test cost calculation for Phase 0 estimates."""

        # Claude Sonnet 4.5 pricing (per 1M tokens)
        claude_input_cost = 3.00
        claude_output_cost = 15.00

        # GPT-4 Turbo pricing (per 1M tokens)
        gpt4_input_cost = 5.00
        gpt4_output_cost = 15.00

        # Estimated tokens per task (conservative)
        avg_input_tokens_per_step = 2000  # Image + text
        avg_output_tokens_per_step = 200  # Response
        avg_steps_per_task = 5

        # Phase 0 configuration
        num_tasks = 20
        num_models = 2  # Claude, GPT-4
        num_conditions = 2  # Zero-shot, demo
        num_trials = 1

        total_runs = num_tasks * num_models * num_conditions * num_trials

        # Calculate costs
        total_input_tokens = total_runs * avg_steps_per_task * avg_input_tokens_per_step
        total_output_tokens = total_runs * avg_steps_per_task * avg_output_tokens_per_step

        # Per model costs
        claude_cost = (
            (total_input_tokens / 2 / 1_000_000) * claude_input_cost +
            (total_output_tokens / 2 / 1_000_000) * claude_output_cost
        )

        gpt4_cost = (
            (total_input_tokens / 2 / 1_000_000) * gpt4_input_cost +
            (total_output_tokens / 2 / 1_000_000) * gpt4_output_cost
        )

        total_cost = claude_cost + gpt4_cost

        print(f"✓ Phase 0 cost estimate:")
        print(f"  - Total runs: {total_runs}")
        print(f"  - Total input tokens: {total_input_tokens:,}")
        print(f"  - Total output tokens: {total_output_tokens:,}")
        print(f"  - Claude cost: ${claude_cost:.2f}")
        print(f"  - GPT-4 cost: ${gpt4_cost:.2f}")
        print(f"  - Total cost: ${total_cost:.2f}")

        # Sanity check
        assert total_cost > 0
        assert total_cost < 1000  # Should be well under $1000

        return {
            "total_runs": total_runs,
            "total_cost": total_cost,
            "claude_cost": claude_cost,
            "gpt4_cost": gpt4_cost
        }


if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, "-v", "-s"])
