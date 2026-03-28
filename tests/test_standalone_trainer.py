"""Tests for the standalone GRPO trainer.

Covers constrained decoding, task rotation, and config handling.
No GPU or WAA server required.
"""

from __future__ import annotations

import re

import pytest

from openadapt_evals.training.standalone.config import TrainingConfig
from openadapt_evals.training.standalone.trainer import GRPOTrainer


# ---------------------------------------------------------------------------
# Action regex
# ---------------------------------------------------------------------------


class TestActionRegex:
    """Verify the Thought/Action regex accepts valid output and rejects junk."""

    full_regex = GRPOTrainer._ACTION_REGEX
    action_regex = GRPOTrainer._ACTION_RE

    @pytest.mark.parametrize(
        "output",
        [
            "Thought: I need to click the start menu.\nAction: CLICK(x=0.50, y=0.30)",
            "Thought: Type notepad in the search box.\nAction: TYPE(text=\"notepad\")",
            "Thought: Wait for the UI to load.\nAction: WAIT()",
            "Thought: The task is complete.\nAction: DONE()",
            "Thought: Click Chrome icon.\nAction: CLICK(x=0.05, y=0.20)",
            "Thought: x\nAction: CLICK(x=0.0, y=0.0)",
        ],
    )
    def test_valid_thought_action(self, output: str) -> None:
        assert re.match(self.full_regex, output), f"Should match: {output!r}"

    @pytest.mark.parametrize(
        "text",
        [
            "CLICK(x=0.50, y=0.30)",
            "Action: CLICK(x=0.50, y=0.30)",
            "** Let me think about this...",
            "",
            "Thought: I should click here.",
            "Thought: Click\nAction: click(0.5, 0.3)",
            "Thought: Click\nAction: CLICK",
        ],
    )
    def test_invalid_text_rejected(self, text: str) -> None:
        assert not re.match(self.full_regex, text), f"Should NOT match: {text!r}"

    @pytest.mark.parametrize(
        "action",
        [
            "CLICK(x=0.50, y=0.30)",
            "CLICK(x=0.999, y=0.123)",
            'TYPE(text="hello world")',
            'TYPE(text="")',
            "WAIT()",
            "DONE()",
        ],
    )
    def test_action_only_regex(self, action: str) -> None:
        assert re.match(self.action_regex, action), f"Should match: {action!r}"

    def test_no_large_bounded_quantifiers(self) -> None:
        """Bounded quantifiers > 10 cause DFA state explosion in Outlines."""
        bounds = re.findall(r"\{(\d+),(\d+)\}", self.full_regex)
        for lo, hi in bounds:
            assert int(hi) <= 10, (
                f"Quantifier {{{lo},{hi}}} will explode Outlines DFA. Use +/*."
            )


# ---------------------------------------------------------------------------
# Outlines integration
# ---------------------------------------------------------------------------


class TestOutlinesIntegration:
    """Verify the Outlines API the trainer depends on."""

    def test_imports(self) -> None:
        """The three outlines functions the trainer calls must exist."""
        try:
            import outlines
        except ImportError:
            pytest.skip("outlines not installed")
        assert callable(outlines.from_transformers)
        assert callable(outlines.regex)
        assert callable(outlines.Generator)

    def test_regex_compiles(self) -> None:
        """The action regex must compile without DFA explosion."""
        try:
            import outlines
        except ImportError:
            pytest.skip("outlines not installed")
        assert outlines.regex(GRPOTrainer._ACTION_REGEX) is not None

    def test_multimodal_accepts_list_not_dict(self) -> None:
        """TransformersMultiModal dispatches on list, not dict."""
        try:
            from outlines.models.transformers import TransformersMultiModalTypeAdapter
        except ImportError:
            pytest.skip("outlines not installed")
        fmt = TransformersMultiModalTypeAdapter.__dict__["format_input"]
        registered = set(fmt.dispatcher.registry.keys())
        assert list in registered, f"list not registered: {registered}"
        assert dict not in registered, "dict accepted — trainer uses list"

    def test_image_wrapper(self) -> None:
        """outlines.Image wraps PIL images (requires .format set)."""
        try:
            import outlines
        except ImportError:
            pytest.skip("outlines not installed")
        from PIL import Image as PILImage
        import io
        img = PILImage.new("RGB", (10, 10))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        buf.seek(0)
        assert outlines.Image(PILImage.open(buf)) is not None

    def test_generator_callable_with_kwargs(self) -> None:
        """Generator.__call__ must accept **inference_kwargs (max_new_tokens)."""
        try:
            import inspect
            from outlines.generator import SteerableGenerator
        except ImportError:
            pytest.skip("outlines not installed")
        sig = inspect.signature(SteerableGenerator.__call__)
        has_kwargs = any(
            p.kind == inspect.Parameter.VAR_KEYWORD
            for p in sig.parameters.values()
        )
        assert has_kwargs, f"SteerableGenerator.__call__ needs **kwargs: {sig}"


# ---------------------------------------------------------------------------
# Generator cache
# ---------------------------------------------------------------------------


class TestGeneratorCache:
    """Verify the cache sentinel logic for _get_outlines_generator."""

    def test_starts_none(self) -> None:
        assert GRPOTrainer(TrainingConfig())._outlines_generator is None

    def test_false_means_failed(self) -> None:
        t = GRPOTrainer(TrainingConfig(constrained_decoding=True))
        t._outlines_generator = False
        assert t._get_outlines_generator() is None

    def test_cached_generator_returned(self) -> None:
        t = GRPOTrainer(TrainingConfig(constrained_decoding=True))
        t._outlines_generator = "mock"
        assert t._get_outlines_generator() == "mock"


# ---------------------------------------------------------------------------
# Task rotation
# ---------------------------------------------------------------------------


class TestTaskRotation:
    """Verify all tasks from task_dir load and rotate."""

    def test_all_tasks_loaded(self, tmp_path) -> None:
        import yaml
        for i in range(5):
            (tmp_path / f"t{i}.yaml").write_text(yaml.dump({
                "name": f"Task {i}", "id": f"task-{i}",
                "setup": [],
                "evaluate": [{"check": "screenshot", "description": "done"}],
            }))
        config = TrainingConfig(task_dir=str(tmp_path))
        GRPOTrainer(config)._load_task_configs()
        assert len(config.task_ids) == 5

    def test_explicit_ids_preserved(self, tmp_path) -> None:
        import yaml
        for i in range(3):
            (tmp_path / f"t{i}.yaml").write_text(yaml.dump({
                "name": f"Task {i}", "id": f"task-{i}", "setup": [], "evaluate": [],
            }))
        config = TrainingConfig(task_dir=str(tmp_path), task_ids=["task-1"])
        GRPOTrainer(config)._load_task_configs()
        assert config.task_ids == ["task-1"]

    def test_rotation_covers_all(self, tmp_path) -> None:
        import yaml
        for i in range(3):
            (tmp_path / f"t{i}.yaml").write_text(yaml.dump({
                "name": f"Task {i}", "id": f"task-{i}",
                "setup": [],
                "evaluate": [{"check": "screenshot", "description": "done"}],
            }))
        config = TrainingConfig(task_dir=str(tmp_path))
        GRPOTrainer(config)._load_task_configs()
        selected = {config.task_ids[s % len(config.task_ids)] for s in range(9)}
        assert selected == {"task-0", "task-1", "task-2"}
