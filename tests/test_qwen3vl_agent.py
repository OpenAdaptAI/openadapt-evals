"""Tests for Qwen3VLAgent.

Tests cover:
1. Action parsing from Qwen3-VL output to BenchmarkAction
2. Coordinate normalization ([0, 1000] -> [0, 1])
3. Demo injection in prompts
4. Reset behavior
5. Think block handling
"""

import pytest

from openadapt_evals.adapters.base import (
    BenchmarkAction,
    BenchmarkObservation,
    BenchmarkTask,
)
from openadapt_evals.agents.qwen3vl_agent import (
    denormalize_action,
    parse_qwen_action,
)


def make_task(instruction="Open Notepad"):
    return BenchmarkTask(task_id="test_001", instruction=instruction, domain="desktop")


def make_observation(viewport=(1280, 720)):
    return BenchmarkObservation(screenshot=None, viewport=viewport)


# --- Action Parsing ---


class TestParseQwenAction:
    """Test parsing Qwen3-VL action strings into BenchmarkAction."""

    def test_click(self):
        action = parse_qwen_action("click(x=500, y=300)")
        assert action.type == "click"
        assert action.x == 500.0
        assert action.y == 300.0

    def test_click_with_spaces(self):
        action = parse_qwen_action("click( x = 500 , y = 300 )")
        assert action.type == "click"
        assert action.x == 500.0
        assert action.y == 300.0

    def test_double_click(self):
        action = parse_qwen_action("double_click(x=500, y=300)")
        assert action.type == "click"
        assert action.x == 500.0
        assert action.y == 300.0
        assert action.raw_action["click_variant"] == "double_click"

    def test_right_click(self):
        action = parse_qwen_action("right_click(x=100, y=200)")
        assert action.type == "click"
        assert action.x == 100.0
        assert action.y == 200.0
        assert action.raw_action["click_variant"] == "right_click"

    def test_type_action(self):
        action = parse_qwen_action('type(text="hello world")')
        assert action.type == "type"
        assert action.text == "hello world"

    def test_type_single_quotes(self):
        action = parse_qwen_action("type(text='hello world')")
        assert action.type == "type"
        assert action.text == "hello world"

    def test_press_single_key(self):
        action = parse_qwen_action('press(keys=["Return"])')
        assert action.type == "key"
        assert action.key == "Return"
        assert action.modifiers is None

    def test_press_with_modifiers(self):
        action = parse_qwen_action('press(keys=["ctrl", "s"])')
        assert action.type == "key"
        assert action.key == "s"
        assert action.modifiers == ["ctrl"]

    def test_press_multiple_modifiers(self):
        action = parse_qwen_action('press(keys=["ctrl", "shift", "s"])')
        assert action.type == "key"
        assert action.key == "s"
        assert action.modifiers == ["ctrl", "shift"]

    def test_scroll_with_amount(self):
        action = parse_qwen_action('scroll(direction="down", amount=5)')
        assert action.type == "scroll"
        assert action.scroll_direction == "down"
        assert action.scroll_amount == 5.0

    def test_scroll_without_amount(self):
        action = parse_qwen_action('scroll(direction="up")')
        assert action.type == "scroll"
        assert action.scroll_direction == "up"
        assert action.scroll_amount == 3.0  # default

    def test_drag(self):
        action = parse_qwen_action(
            "drag(from_coord=[200, 300], to_coord=[800, 500])"
        )
        assert action.type == "drag"
        assert action.x == 200.0
        assert action.y == 300.0
        assert action.end_x == 800.0
        assert action.end_y == 500.0

    def test_wait(self):
        action = parse_qwen_action("wait()")
        assert action.type == "done"
        assert action.raw_action.get("is_wait") is True

    def test_finished(self):
        action = parse_qwen_action("finished()")
        assert action.type == "done"

    def test_no_action_found(self):
        action = parse_qwen_action("I don't know what to do")
        assert action.type == "done"
        assert "parse_error" in action.raw_action

    def test_action_in_longer_text(self):
        """Parser finds action even when embedded in natural language."""
        action = parse_qwen_action(
            "I need to click the start button at click(x=500, y=950)"
        )
        assert action.type == "click"
        assert action.x == 500.0
        assert action.y == 950.0


# --- Think Block Handling ---


class TestThinkBlocks:
    """Test handling of <think>...</think> blocks."""

    def test_think_block_extracted(self):
        response = (
            "<think>\nI see the desktop. I should click the start button.\n</think>\n"
            "click(x=500, y=950)"
        )
        action = parse_qwen_action(response)
        assert action.type == "click"
        assert action.x == 500.0
        assert action.y == 950.0
        assert "thinking" in action.raw_action
        assert "start button" in action.raw_action["thinking"]

    def test_think_block_multiline(self):
        response = (
            "<think>\nLine 1\nLine 2\nLine 3\n</think>\n"
            'type(text="hello")'
        )
        action = parse_qwen_action(response)
        assert action.type == "type"
        assert action.text == "hello"
        assert "Line 2" in action.raw_action["thinking"]

    def test_no_think_block(self):
        action = parse_qwen_action("click(x=100, y=200)")
        assert "thinking" not in action.raw_action


# --- Coordinate Normalization ---


class TestDenormalizeAction:
    """Test converting [0, 1000] coordinates to [0, 1]."""

    def test_click_denormalization(self):
        action = BenchmarkAction(type="click", x=500.0, y=300.0)
        result = denormalize_action(action, viewport=(1280, 720))
        assert abs(result.x - 0.5) < 0.001
        assert abs(result.y - 0.3) < 0.001

    def test_origin_denormalization(self):
        action = BenchmarkAction(type="click", x=0.0, y=0.0)
        result = denormalize_action(action, viewport=(1280, 720))
        assert result.x == 0.0
        assert result.y == 0.0

    def test_max_denormalization(self):
        action = BenchmarkAction(type="click", x=1000.0, y=1000.0)
        result = denormalize_action(action, viewport=(1280, 720))
        assert abs(result.x - 1.0) < 0.001
        assert abs(result.y - 1.0) < 0.001

    def test_drag_denormalization(self):
        action = BenchmarkAction(
            type="drag", x=200.0, y=300.0, end_x=800.0, end_y=500.0
        )
        result = denormalize_action(action, viewport=(1920, 1080))
        assert abs(result.x - 0.2) < 0.001
        assert abs(result.y - 0.3) < 0.001
        assert abs(result.end_x - 0.8) < 0.001
        assert abs(result.end_y - 0.5) < 0.001

    def test_none_coords_preserved(self):
        action = BenchmarkAction(type="done")
        result = denormalize_action(action, viewport=(1280, 720))
        assert result.x is None
        assert result.y is None

    def test_non_coord_fields_preserved(self):
        action = BenchmarkAction(
            type="type",
            text="hello",
            raw_action={"response": "test"},
        )
        result = denormalize_action(action, viewport=(1280, 720))
        assert result.type == "type"
        assert result.text == "hello"
        assert result.raw_action == {"response": "test"}


# --- Demo Injection ---


class TestDemoInjection:
    """Test demo injection into prompts."""

    def test_prompt_includes_demo(self):
        from openadapt_evals.agents.qwen3vl_agent import Qwen3VLAgent

        agent = Qwen3VLAgent(
            demo="Step 0: click(x=450, y=950)\nStep 1: click(x=300, y=200)"
        )
        prompt = agent._build_prompt(make_observation(), make_task("Open Notepad"))
        assert "demonstration" in prompt.lower()
        assert "click(x=450, y=950)" in prompt
        assert "Open Notepad" in prompt

    def test_prompt_without_demo(self):
        from openadapt_evals.agents.qwen3vl_agent import Qwen3VLAgent

        agent = Qwen3VLAgent()
        prompt = agent._build_prompt(make_observation(), make_task("Open Notepad"))
        assert "demonstration" not in prompt.lower()
        assert "Open Notepad" in prompt

    def test_prompt_includes_action_history(self):
        from openadapt_evals.agents.qwen3vl_agent import Qwen3VLAgent

        agent = Qwen3VLAgent()
        agent._action_history = ["click(x=500, y=950)", 'type(text="notepad")']
        prompt = agent._build_prompt(make_observation(), make_task())
        assert "Previous actions:" in prompt
        assert "click(x=500, y=950)" in prompt
        assert 'type(text="notepad")' in prompt

    def test_prompt_with_thinking_mode(self):
        from openadapt_evals.agents.qwen3vl_agent import Qwen3VLAgent

        agent = Qwen3VLAgent(use_thinking=True)
        prompt = agent._build_prompt(make_observation(), make_task())
        assert "<think>" in prompt

    def test_prompt_without_thinking_mode(self):
        from openadapt_evals.agents.qwen3vl_agent import Qwen3VLAgent

        agent = Qwen3VLAgent(use_thinking=False)
        prompt = agent._build_prompt(make_observation(), make_task())
        assert "<think>" not in prompt


# --- Reset ---


class TestReset:
    """Test agent reset behavior."""

    def test_reset_clears_step_count(self):
        from openadapt_evals.agents.qwen3vl_agent import Qwen3VLAgent

        agent = Qwen3VLAgent()
        agent._step_count = 5
        agent._action_history = ["click(x=100, y=200)", "wait()"]

        agent.reset()

        assert agent._step_count == 0
        assert agent._action_history == []

    def test_reset_preserves_config(self):
        from openadapt_evals.agents.qwen3vl_agent import Qwen3VLAgent

        demo = "Step 0: click(x=500, y=500)"
        agent = Qwen3VLAgent(demo=demo, use_thinking=True)
        agent._step_count = 3
        agent._action_history = ["click(x=100, y=200)"]

        agent.reset()

        assert agent.demo == demo
        assert agent.use_thinking is True
        assert agent._step_count == 0
        assert agent._action_history == []


# --- Import ---


class TestImport:
    """Test that the agent can be imported from the package."""

    def test_import_from_agents_package(self):
        from openadapt_evals.agents import Qwen3VLAgent

        assert Qwen3VLAgent is not None

    def test_in_all(self):
        from openadapt_evals import agents

        assert "Qwen3VLAgent" in agents.__all__

    def test_parse_qwen_action_importable(self):
        from openadapt_evals.agents.qwen3vl_agent import parse_qwen_action

        assert callable(parse_qwen_action)

    def test_denormalize_action_importable(self):
        from openadapt_evals.agents.qwen3vl_agent import denormalize_action

        assert callable(denormalize_action)
