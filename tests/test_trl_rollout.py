"""Tests for TRL GRPOTrainer rollout function."""

from __future__ import annotations

import textwrap
from unittest.mock import MagicMock, patch

import pytest

from openadapt_evals.adapters.base import (
    BenchmarkAction,
    BenchmarkObservation,
    BenchmarkResult,
    BenchmarkTask,
)
from openadapt_evals.task_config import Milestone, TaskCheck, TaskConfig
from openadapt_evals.training.trl_rollout import (
    ACTION_REGEX,
    _AgentOutput,
    make_waa_rollout_func,
    parse_action_json,
)


# ---------------------------------------------------------------------------
# parse_action_json tests
# ---------------------------------------------------------------------------


class TestParseActionJson:
    def test_simple_click(self):
        action = parse_action_json('{"type": "click", "x": 0.5, "y": 0.3}')
        assert action.type == "click"
        assert action.x == 0.5
        assert action.y == 0.3

    def test_type_action(self):
        action = parse_action_json('{"type": "type", "text": "hello world"}')
        assert action.type == "type"
        assert action.text == "hello world"

    def test_key_action(self):
        action = parse_action_json('{"type": "key", "key": "Enter"}')
        assert action.type == "key"
        assert action.key == "Enter"

    def test_done_action(self):
        action = parse_action_json('{"type": "done"}')
        assert action.type == "done"

    def test_with_thinking_prefix(self):
        text = """I need to click the button.

```json
{"type": "click", "x": 0.2, "y": 0.8}
```"""
        action = parse_action_json(text)
        assert action.type == "click"
        assert action.x == 0.2

    def test_with_markdown_fence(self):
        action = parse_action_json('```json\n{"type": "scroll", "x": 0.5, "y": 0.5}\n```')
        assert action.type == "scroll"

    def test_no_json_returns_done(self):
        action = parse_action_json("I'm not sure what to do")
        assert action.type == "done"

    def test_invalid_json_returns_done(self):
        action = parse_action_json("{broken json}")
        assert action.type == "done"

    def test_unknown_type_returns_done(self):
        action = parse_action_json('{"type": "fly_to_moon", "x": 0}')
        assert action.type == "done"

    def test_noop(self):
        action = parse_action_json('{"type": "noop"}')
        assert action.type == "noop"

    # --- DSL fallback tests ---

    def test_parse_action_json_dsl_click(self):
        """DSL CLICK(x=0.5, y=0.3) parses to BenchmarkAction click."""
        action = parse_action_json("CLICK(x=0.50, y=0.30)")
        assert action.type == "click"
        assert action.x == 0.5
        assert action.y == 0.3

    def test_parse_action_json_dsl_type(self):
        """DSL TYPE(text="hello") parses to BenchmarkAction type."""
        action = parse_action_json('TYPE(text="hello")')
        assert action.type == "type"
        assert action.text == "hello"

    def test_parse_action_json_dsl_wait(self):
        """DSL WAIT() parses to BenchmarkAction wait."""
        action = parse_action_json("WAIT()")
        assert action.type == "wait"

    def test_parse_action_json_dsl_done(self):
        """DSL DONE() parses to BenchmarkAction done."""
        action = parse_action_json("DONE()")
        assert action.type == "done"

    def test_parse_action_json_dsl_with_thought(self):
        """Thought/Action format with DSL parses correctly."""
        text = "Thought: I need to click the start menu\nAction: CLICK(x=0.50, y=0.30)"
        action = parse_action_json(text)
        assert action.type == "click"
        assert action.x == 0.5
        assert action.y == 0.3

    def test_parse_action_json_with_reasoning(self):
        """JSON with reasoning field parses correctly."""
        text = '{"reasoning": "clicking the button", "type": "click", "x": 0.5, "y": 0.3}'
        action = parse_action_json(text)
        assert action.type == "click"
        assert action.x == 0.5
        assert action.y == 0.3

    def test_parse_action_json_wait_type(self):
        """JSON with wait type parses correctly."""
        action = parse_action_json('{"type": "wait"}')
        assert action.type == "wait"


# ---------------------------------------------------------------------------
# ACTION_REGEX tests
# ---------------------------------------------------------------------------


class TestActionRegex:
    def test_action_regex_matches_click_json(self):
        """ACTION_REGEX matches a valid JSON click action."""
        import re

        text = '{"reasoning": "click the button", "type": "click", "x": 0.50, "y": 0.30}'
        assert re.fullmatch(ACTION_REGEX, text) is not None

    def test_action_regex_matches_type_json(self):
        """ACTION_REGEX matches a valid JSON type action."""
        import re

        text = '{"reasoning": "type hello", "type": "type", "text": "hello"}'
        assert re.fullmatch(ACTION_REGEX, text) is not None

    def test_action_regex_matches_done_json(self):
        """ACTION_REGEX matches a valid JSON done action."""
        import re

        text = '{"reasoning": "task complete", "type": "done"}'
        assert re.fullmatch(ACTION_REGEX, text) is not None

    def test_action_regex_matches_wait_json(self):
        """ACTION_REGEX matches a valid JSON wait action."""
        import re

        text = '{"reasoning": "waiting for load", "type": "wait"}'
        assert re.fullmatch(ACTION_REGEX, text) is not None


# ---------------------------------------------------------------------------
# _AgentOutput schema tests
# ---------------------------------------------------------------------------


class TestAgentOutputSchema:
    def test_agent_output_schema_valid_click(self):
        """_AgentOutput validates a click action correctly."""
        output = _AgentOutput(
            reasoning="clicking the submit button",
            type="click",
            x=0.5,
            y=0.3,
        )
        assert output.type == "click"
        assert output.x == 0.5
        assert output.y == 0.3
        assert output.text is None
        assert output.key is None

    def test_agent_output_schema_valid_type(self):
        """_AgentOutput validates a type action correctly."""
        output = _AgentOutput(
            reasoning="typing into search box",
            type="type",
            text="hello world",
        )
        assert output.type == "type"
        assert output.text == "hello world"

    def test_agent_output_schema_valid_done(self):
        """_AgentOutput validates a done action correctly."""
        output = _AgentOutput(
            reasoning="task is complete",
            type="done",
        )
        assert output.type == "done"

    def test_agent_output_schema_json_roundtrip(self):
        """_AgentOutput serializes to JSON and back correctly."""
        import json

        output = _AgentOutput(
            reasoning="click button",
            type="click",
            x=0.5,
            y=0.3,
        )
        data = json.loads(output.model_dump_json())
        assert data["reasoning"] == "click button"
        assert data["type"] == "click"
        assert data["x"] == 0.5
        assert data["y"] == 0.3


# ---------------------------------------------------------------------------
# make_waa_rollout_func tests
# ---------------------------------------------------------------------------


def _make_mock_adapter(steps_to_done=3):
    adapter = MagicMock()
    call_count = {"n": 0}

    _fake_obs = BenchmarkObservation(
        screenshot=b"\x89PNG\r\n\x1a\n" + b"\x00" * 100,
        raw_observation={},
    )

    def mock_step(action):
        call_count["n"] += 1
        done = call_count["n"] >= steps_to_done
        return (
            BenchmarkObservation(
                screenshot=b"\x89PNG\r\n\x1a\n" + b"\x00" * 100,
                raw_observation={},
            ),
            done,
            {},
        )

    adapter.step.side_effect = mock_step
    adapter.reset.return_value = _fake_obs
    # observe() is called by the pre-rollout health check
    adapter.observe.return_value = _fake_obs
    adapter.load_task.return_value = BenchmarkTask(
        task_id="test-task", instruction="Test", domain="desktop"
    )
    adapter.load_task_from_json.return_value = BenchmarkTask(
        task_id="test-task", instruction="Test", domain="desktop"
    )
    adapter.evaluate.return_value = BenchmarkResult(
        task_id="test-task", success=False, score=0.0
    )
    adapter.config = MagicMock(server_url="http://mock:5001")
    return adapter


def _make_task_config():
    return TaskConfig(
        name="Test task",
        id="test-task",
        domain="desktop",
        setup=[],
        checks=[],
        combine="and",
        max_steps=5,
        milestones=[
            Milestone(
                name="Step done",
                check=TaskCheck(check="command", run="echo 1", expect="1", match="exact"),
            ),
        ],
    )


def _make_mock_trainer():
    """Create a mock TRL GRPOTrainer."""
    trainer = MagicMock()
    trainer.args = MagicMock()
    trainer.args.num_generations = 2
    # Mock processor and model would be set in integration tests
    return trainer


class TestMakeWaaRolloutFunc:
    def test_returns_callable(self):
        adapter = _make_mock_adapter()
        func = make_waa_rollout_func(adapter)
        assert callable(func)

    def test_rollout_with_mock_generate(self):
        """Test full rollout with a mock generate function."""
        adapter = _make_mock_adapter(steps_to_done=2)
        tc = _make_task_config()

        func = make_waa_rollout_func(
            adapter=adapter,
            task_configs=[tc],
            max_steps=5,
        )

        # Create a mock trainer with a fake generate function
        trainer = _make_mock_trainer()
        trainer.args.num_generations = 1

        # Patch _run_episode to avoid needing a real model
        from openadapt_evals.training import trl_rollout

        original_run = trl_rollout._run_episode

        def mock_run_episode(env, generate_fn, instruction, task_id, max_steps):
            """Simplified episode that doesn't need a real model."""
            from openadapt_evals.adapters.rl_env import ResetConfig

            obs = env.reset(config=ResetConfig(task_id=task_id))

            # Simulate 2 steps
            for _ in range(2):
                action = BenchmarkAction(type="click", x=100, y=100)
                step_result = env.step(action)
                if step_result.done:
                    break

            # Evaluate
            with patch.object(TaskConfig, "_run_vm_command", return_value="1"):
                reward = env.evaluate_dense()

            return [1, 2, 3], [4, 5, 6], [-0.5, -0.3, -0.1], reward

        with patch.object(trl_rollout, "_run_episode", side_effect=mock_run_episode):
            result = func(["Test task"], trainer)

        assert "prompt_ids" in result
        assert "completion_ids" in result
        assert "logprobs" in result
        assert "env_reward" in result
        assert len(result["env_reward"]) == 1  # 1 prompt × 1 generation
        assert result["env_reward"][0] == 1.0  # milestone passed

    def test_rollout_output_shape_multiple_prompts(self):
        """Verify output shape with multiple prompts × generations."""
        adapter = _make_mock_adapter(steps_to_done=1)
        tc = _make_task_config()

        func = make_waa_rollout_func(adapter, task_configs=[tc], max_steps=3)

        trainer = _make_mock_trainer()
        trainer.args.num_generations = 3

        from openadapt_evals.training import trl_rollout

        def mock_run(env, gfn, instr, tid, ms):
            from openadapt_evals.adapters.rl_env import ResetConfig
            env.reset(config=ResetConfig(task_id=tid))
            env.step(BenchmarkAction(type="done"))
            with patch.object(TaskConfig, "_run_vm_command", return_value="1"):
                reward = env.evaluate_dense()
            return [1], [2], [-0.5], reward

        with patch.object(trl_rollout, "_run_episode", side_effect=mock_run):
            result = func(["Task A", "Task B"], trainer)

        # 2 prompts × 3 generations = 6 entries
        assert len(result["env_reward"]) == 6
        assert len(result["prompt_ids"]) == 6
        assert len(result["completion_ids"]) == 6
        assert len(result["logprobs"]) == 6

    def test_rollout_handles_episode_failure(self):
        """Verify graceful handling when an episode throws an exception."""
        adapter = _make_mock_adapter()
        func = make_waa_rollout_func(adapter, max_steps=3)

        trainer = _make_mock_trainer()
        trainer.args.num_generations = 1

        from openadapt_evals.training import trl_rollout

        def failing_run(env, gfn, instr, tid, ms):
            raise RuntimeError("VM connection lost")

        with patch.object(trl_rollout, "_run_episode", side_effect=failing_run):
            result = func(["Failing task"], trainer)

        # Should return zeros, not crash
        assert result["env_reward"] == [0.0]
        assert result["prompt_ids"] == [[]]
        assert result["completion_ids"] == [[]]
        assert result["logprobs"] == [[]]

    def test_task_config_lookup_by_name(self):
        """Verify task_configs are indexed by name for prompt matching."""
        tc1 = TaskConfig(
            name="Open Notepad", id="notepad-1", domain="desktop",
            setup=[], checks=[], combine="and", max_steps=5, milestones=[],
        )
        tc2 = TaskConfig(
            name="Create folder", id="folder-1", domain="desktop",
            setup=[], checks=[], combine="and", max_steps=5, milestones=[],
        )

        adapter = _make_mock_adapter(steps_to_done=1)
        func = make_waa_rollout_func(adapter, task_configs=[tc1, tc2])

        trainer = _make_mock_trainer()
        trainer.args.num_generations = 1

        from openadapt_evals.training import trl_rollout

        captured_task_ids = []

        def capture_run(env, gfn, instr, tid, ms):
            captured_task_ids.append(tid)
            from openadapt_evals.adapters.rl_env import ResetConfig
            env.reset(config=ResetConfig(task_id=tid))
            env.step(BenchmarkAction(type="done"))
            return [1], [2], [-0.1], 0.0

        with patch.object(trl_rollout, "_run_episode", side_effect=capture_run):
            func(["Open Notepad", "Create folder"], trainer)

        assert captured_task_ids == ["notepad-1", "folder-1"]
