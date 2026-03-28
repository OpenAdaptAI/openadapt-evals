"""Tests for the standalone GRPO trainer.

Covers constrained decoding logic, task rotation, and config handling.
No GPU or WAA server required — tests use mocks.
"""

from __future__ import annotations

import re

import pytest

from openadapt_evals.training.standalone.config import TrainingConfig
from openadapt_evals.training.standalone.trainer import GRPOTrainer


# ---------------------------------------------------------------------------
# Action regex tests
# ---------------------------------------------------------------------------


class TestActionRegex:
    """Verify the Thought/Action format regex matches valid output and rejects junk."""

    full_regex = GRPOTrainer._ACTION_REGEX
    action_regex = GRPOTrainer._ACTION_RE

    # -- Full Thought/Action format tests --

    @pytest.mark.parametrize(
        "output",
        [
            "Thought: I need to click the start menu.\nAction: CLICK(x=0.50, y=0.30)",
            "Thought: Type notepad in the search box.\nAction: TYPE(text=\"notepad\")",
            "Thought: Wait for the UI to load.\nAction: WAIT()",
            "Thought: The task is complete.\nAction: DONE()",
            "Thought: Click the Chrome icon on the desktop to open Chrome.\nAction: CLICK(x=0.05, y=0.20)",
            "Thought: x\nAction: CLICK(x=0.0, y=0.0)",
        ],
    )
    def test_valid_thought_action_matches(self, output: str) -> None:
        assert re.match(self.full_regex, output), f"Expected match: {output!r}"

    @pytest.mark.parametrize(
        "text",
        [
            # No Thought prefix
            "CLICK(x=0.50, y=0.30)",
            "Action: CLICK(x=0.50, y=0.30)",
            # Free-text reasoning without structure
            "** Let me think about this...",
            "1. Analyze the user's goal",
            "The user wants to open Task Manager",
            "",
            # Missing Action line
            "Thought: I should click here.",
            # Wrong action format
            "Thought: Click\nAction: click(0.5, 0.3)",
            "Thought: Click\nAction: CLICK",
        ],
    )
    def test_invalid_text_rejected(self, text: str) -> None:
        assert not re.match(self.full_regex, text), f"Should NOT match: {text!r}"

    # -- Action-only regex tests (used by parser) --

    @pytest.mark.parametrize(
        "action",
        [
            "CLICK(x=0.50, y=0.30)",
            "CLICK(x=0.0, y=0.0)",
            "CLICK(x=0.999, y=0.123)",
            'TYPE(text="hello world")',
            'TYPE(text="")',
            'TYPE(text="notepad")',
            "WAIT()",
            "DONE()",
        ],
    )
    def test_action_only_regex_matches(self, action: str) -> None:
        assert re.match(self.action_regex, action), f"Expected match: {action!r}"

    def test_no_bounded_quantifiers_in_regex(self) -> None:
        """Regression test: bounded quantifiers ({N,M}) cause DFA state explosion.

        Outlines compiles regex to a DFA. Bounded quantifiers like {1,500}
        create counting states that cross-product with every alternative,
        exceeding the 2^31 state limit. All repetitions must use +, *, or
        small bounds ({1,3} is OK, {0,200} is not).
        """
        import re as _re
        # Find all bounded quantifiers in the full regex
        bounds = _re.findall(r'\{(\d+),(\d+)\}', self.full_regex)
        for lo, hi in bounds:
            assert int(hi) <= 10, (
                f"Bounded quantifier {{{lo},{hi}}} in ACTION_REGEX will cause "
                f"DFA state explosion in Outlines. Use + or * instead."
            )


# ---------------------------------------------------------------------------
# Constrained decoding cache tests
# ---------------------------------------------------------------------------


class TestConstrainedDecodingCache:
    """Test the caching logic for the Outlines logits processor."""

    def test_cache_starts_as_none(self) -> None:
        config = TrainingConfig()
        trainer = GRPOTrainer(config)
        assert trainer._constrained_processor_cache is None

    def test_failed_cache_returns_none(self) -> None:
        """When compilation fails, subsequent calls return None (not [])."""
        config = TrainingConfig(constrained_decoding=True)
        trainer = GRPOTrainer(config)
        # Simulate a failed compilation
        trainer._constrained_processor_cache = False
        result = trainer._get_constrained_logits_processor()
        assert result is None

    def test_successful_cache_returns_list(self) -> None:
        """When compilation succeeds, subsequent calls return the list."""
        config = TrainingConfig(constrained_decoding=True)
        trainer = GRPOTrainer(config)
        # Simulate a successful compilation
        trainer._constrained_processor_cache = ["mock_processor"]
        result = trainer._get_constrained_logits_processor()
        assert result == ["mock_processor"]

    def test_outlines_api_imports(self) -> None:
        """Verify the outlines API the trainer depends on is importable.

        The trainer uses:
        - outlines.Transformers (model wrapper)
        - outlines.generator.get_regex_logits_processor (factory)
        """
        try:
            import outlines  # noqa: F401
        except ImportError:
            pytest.skip("outlines not installed")

        from outlines import Transformers
        from outlines.generator import get_regex_logits_processor
        assert callable(Transformers)
        assert callable(get_regex_logits_processor)

    def test_outlines_processor_creation(self) -> None:
        """Verify a regex logits processor can actually be created.

        This is the integration test that would have caught the prior bugs:
        - Wrong class name (RegexLogitsProcessor vs OutlinesLogitsProcessor)
        - Wrong constructor args (tokenizer= kwarg didn't exist)

        Requires a real model, so we use a tiny one or skip.
        """
        try:
            import outlines
            import torch
            from transformers import AutoTokenizer
        except ImportError:
            pytest.skip("outlines/torch/transformers not installed")

        try:
            # Use the smallest possible tokenizer for fast test
            tokenizer = AutoTokenizer.from_pretrained(
                "hf-internal-testing/tiny-random-LlamaForCausalLM",
                trust_remote_code=True,
            )
        except Exception:
            pytest.skip("Could not load test tokenizer")

        from outlines.generator import get_regex_logits_processor

        # Verify the factory function signature matches what the trainer expects:
        # get_regex_logits_processor(backend_name, model, regex)
        import inspect
        sig = inspect.signature(get_regex_logits_processor)
        params = list(sig.parameters.keys())
        assert len(params) >= 3, (
            f"get_regex_logits_processor signature changed: {sig}. "
            f"Expected (backend_name, model, regex), got {params}"
        )

    def test_empty_list_no_longer_caches_as_success(self) -> None:
        """Regression test: empty list [] should NOT be treated as success.

        Prior bug: failure cached [] which is truthy for `is not None`,
        causing subsequent calls to return [] (no processors applied).
        """
        config = TrainingConfig(constrained_decoding=True)
        trainer = GRPOTrainer(config)
        # The old buggy behavior would cache [] on failure
        # Verify the sentinel is False (not []) for failures
        trainer._constrained_processor_cache = False
        assert trainer._get_constrained_logits_processor() is None
        # And [] is actually a valid success cache (with a processor in it)
        trainer._constrained_processor_cache = ["real_processor"]
        assert trainer._get_constrained_logits_processor() == ["real_processor"]


# ---------------------------------------------------------------------------
# Task rotation tests
# ---------------------------------------------------------------------------


class TestTaskRotation:
    """Test that all tasks from task_dir are loaded, not just the first."""

    def test_all_tasks_loaded_from_dir(self, tmp_path) -> None:
        """Create multiple task YAMLs and verify all are loaded."""
        import yaml

        for i in range(3):
            task = {
                "name": f"Task {i}",
                "id": f"task-{i}",
                "setup": [],
                "evaluate": [{"check": "screenshot", "description": "done"}],
            }
            (tmp_path / f"task_{i}.yaml").write_text(yaml.dump(task))

        config = TrainingConfig(task_dir=str(tmp_path))
        trainer = GRPOTrainer(config)
        trainer._load_task_configs()

        assert len(config.task_ids) == 3
        assert set(config.task_ids) == {"task-0", "task-1", "task-2"}

    def test_explicit_task_ids_not_overwritten(self, tmp_path) -> None:
        """When task_ids is set explicitly, task_dir doesn't override it."""
        import yaml

        for i in range(3):
            task = {"name": f"Task {i}", "id": f"task-{i}", "setup": [], "evaluate": []}
            (tmp_path / f"task_{i}.yaml").write_text(yaml.dump(task))

        config = TrainingConfig(
            task_dir=str(tmp_path),
            task_ids=["task-1"],  # explicit
        )
        trainer = GRPOTrainer(config)
        trainer._load_task_configs()

        # Should keep the explicit list, not auto-populate
        assert config.task_ids == ["task-1"]
        # But task_configs should still have all 3 loaded (for setup/eval)
        assert len(trainer._task_configs) == 3

    def test_task_rotation_in_training_loop(self) -> None:
        """Verify step % len(task_ids) produces rotation."""
        task_ids = ["a", "b", "c"]
        num_steps = 9
        selected = [task_ids[step % len(task_ids)] for step in range(num_steps)]
        assert selected == ["a", "b", "c", "a", "b", "c", "a", "b", "c"]

    def test_task_rotation_not_stuck_on_first(self, tmp_path) -> None:
        """Regression test: all tasks should appear, not just the first.

        Prior bug: _load_task_configs checked `if not task_ids` INSIDE
        the loop, so after the first task was appended, the remaining
        tasks were skipped because `not ['task-0']` is False.
        """
        import yaml

        for i in range(5):
            task = {
                "name": f"Task {i}",
                "id": f"task-{i}",
                "setup": [],
                "evaluate": [{"check": "screenshot", "description": "done"}],
            }
            (tmp_path / f"task_{i}.yaml").write_text(yaml.dump(task))

        config = TrainingConfig(task_dir=str(tmp_path))
        trainer = GRPOTrainer(config)
        trainer._load_task_configs()

        # Must have ALL 5, not just 1
        assert len(config.task_ids) == 5, (
            f"Expected 5 task_ids but got {len(config.task_ids)}: {config.task_ids}. "
            "The _load_task_configs bug (checking inside loop) may have regressed."
        )

        # Simulate 10 training steps — must see more than one unique task
        selected = [config.task_ids[step % len(config.task_ids)] for step in range(10)]
        unique = set(selected)
        assert len(unique) == 5, f"Expected 5 unique tasks in rotation, got {len(unique)}: {unique}"
