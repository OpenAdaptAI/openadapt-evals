"""Tests for PlannerGrounderAgent."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from openadapt_evals.adapters.base import (
    BenchmarkAction,
    BenchmarkObservation,
    BenchmarkTask,
)
from openadapt_evals.agents.planner_grounder_agent import (
    PlannerGrounderAgent,
    _action_to_planner_output,
)


# -- Fixtures ----------------------------------------------------------------


@pytest.fixture
def task() -> BenchmarkTask:
    return BenchmarkTask(
        task_id="test_1",
        instruction="Open the Settings app and enable dark mode",
        domain="desktop",
    )


@pytest.fixture
def observation() -> BenchmarkObservation:
    return BenchmarkObservation(
        screenshot=b"\x89PNG\r\n\x1a\nfake",
        viewport=(1920, 1200),
        accessibility_tree={"role": "window", "name": "Desktop", "id": "1"},
    )


class MockPlannerAgent:
    """Mock planner that returns a COMMAND action with instruction in raw_action."""

    def __init__(self, instruction: str = "Click the Settings icon"):
        self.instruction = instruction
        self._reset_called = False

    def act(self, observation, task, history=None):
        return BenchmarkAction(
            type="click",
            x=0.5,
            y=0.5,
            raw_action={"instruction": self.instruction},
        )

    def reset(self):
        self._reset_called = True


class MockGrounderAgent:
    """Mock grounder that returns a click at specific coordinates."""

    def __init__(self, x: float = 0.8, y: float = 0.3):
        self.x = x
        self.y = y
        self._reset_called = False

    def act(self, observation, task, history=None):
        return BenchmarkAction(type="click", x=self.x, y=self.y)

    def reset(self):
        self._reset_called = True


class MockDonePlannerAgent:
    """Mock planner that returns a done action."""

    def act(self, observation, task, history=None):
        return BenchmarkAction(type="done", raw_action={"reasoning": "Task complete"})

    def reset(self):
        pass


# -- Tests: Agent-based planner + grounder ------------------------------------


class TestAgentBasedPipeline:
    def test_planner_instruction_flows_to_grounder(self, observation, task):
        """Planner instruction is passed to the grounder as the task instruction."""
        planner = MockPlannerAgent(instruction="Click the Settings icon")
        grounder = MockGrounderAgent(x=0.8, y=0.3)

        agent = PlannerGrounderAgent(planner=planner, grounder=grounder)
        action = agent.act(observation, task)

        assert action.type == "click"
        assert action.x == 0.8
        assert action.y == 0.3

    def test_planner_done_returns_done(self, observation, task):
        """When planner returns DONE, agent returns done without calling grounder."""
        planner = MockDonePlannerAgent()
        grounder = MockGrounderAgent()

        agent = PlannerGrounderAgent(planner=planner, grounder=grounder)
        action = agent.act(observation, task)

        assert action.type == "done"
        assert action.raw_action["source"] == "planner"

    def test_planner_metadata_attached_to_action(self, observation, task):
        """Planner output dict is attached to the final action's raw_action."""
        planner = MockPlannerAgent()
        grounder = MockGrounderAgent()

        agent = PlannerGrounderAgent(planner=planner, grounder=grounder)
        action = agent.act(observation, task)

        assert "planner_output" in action.raw_action
        assert action.raw_action["planner_output"]["decision"] == "COMMAND"


class TestActionHistory:
    def test_history_accumulates(self, observation, task):
        """Action history grows with each step."""
        planner = MockPlannerAgent()
        grounder = MockGrounderAgent()
        agent = PlannerGrounderAgent(planner=planner, grounder=grounder)

        agent.act(observation, task)
        assert len(agent._action_history) == 1

        agent.act(observation, task)
        assert len(agent._action_history) == 2

    def test_reset_clears_history(self, observation, task):
        """reset() clears action history."""
        planner = MockPlannerAgent()
        grounder = MockGrounderAgent()
        agent = PlannerGrounderAgent(planner=planner, grounder=grounder)

        agent.act(observation, task)
        assert len(agent._action_history) == 1

        agent.reset()
        assert len(agent._action_history) == 0

    def test_reset_propagates_to_sub_agents(self):
        """reset() calls reset on planner and grounder agents."""
        planner = MockPlannerAgent()
        grounder = MockGrounderAgent()
        agent = PlannerGrounderAgent(planner=planner, grounder=grounder)

        agent.reset()
        assert planner._reset_called
        assert grounder._reset_called

    def test_done_recorded_in_history(self, observation, task):
        """DONE decision is recorded in action history."""
        planner = MockDonePlannerAgent()
        grounder = MockGrounderAgent()
        agent = PlannerGrounderAgent(planner=planner, grounder=grounder)

        agent.act(observation, task)
        assert len(agent._action_history) == 1
        assert "DONE" in agent._action_history[0]


# -- Tests: VLM-based planner + grounder -------------------------------------


class TestVLMBasedPipeline:
    @patch("openadapt_evals.vlm.vlm_call")
    @patch("openadapt_evals.vlm.extract_json")
    @patch("openadapt_evals.training.trl_rollout.parse_action_json")
    def test_vlm_planner_command_grounder_click(
        self, mock_parse, mock_extract, mock_vlm, observation, task
    ):
        """VLM planner outputs COMMAND, VLM grounder outputs click coordinates."""
        # Planner returns COMMAND with instruction.
        mock_vlm.return_value = '{"decision": "COMMAND", "instruction": "Click Settings"}'
        mock_extract.return_value = {
            "decision": "COMMAND",
            "instruction": "Click Settings",
            "reasoning": "Need to open settings",
        }
        # Grounder returns a click action.
        mock_parse.return_value = BenchmarkAction(type="click", x=0.5, y=0.3)

        agent = PlannerGrounderAgent(
            planner="claude-sonnet-4-20250514",
            grounder="gpt-4.1-mini",
            planner_provider="anthropic",
            grounder_provider="openai",
        )
        action = agent.act(observation, task)

        assert action.type == "click"
        assert action.x == 0.5
        assert action.y == 0.3
        # vlm_call should be called twice: once for planner, once for grounder.
        assert mock_vlm.call_count == 2

    @patch("openadapt_evals.vlm.vlm_call")
    @patch("openadapt_evals.vlm.extract_json")
    def test_vlm_planner_done(self, mock_extract, mock_vlm, observation, task):
        """VLM planner outputs DONE, agent returns done without calling grounder."""
        mock_vlm.return_value = '{"decision": "DONE"}'
        mock_extract.return_value = {
            "decision": "DONE",
            "instruction": "",
            "reasoning": "Task is complete",
        }

        agent = PlannerGrounderAgent(
            planner="claude-sonnet-4-20250514",
            grounder="gpt-4.1-mini",
            planner_provider="anthropic",
            grounder_provider="openai",
        )
        action = agent.act(observation, task)

        assert action.type == "done"
        assert action.raw_action["source"] == "planner"
        # vlm_call should only be called once (planner only).
        assert mock_vlm.call_count == 1

    @patch("openadapt_evals.vlm.vlm_call")
    @patch("openadapt_evals.vlm.extract_json")
    def test_vlm_planner_fail(self, mock_extract, mock_vlm, observation, task):
        """VLM planner outputs FAIL, agent returns done with fail reason."""
        mock_vlm.return_value = '{"decision": "FAIL"}'
        mock_extract.return_value = {
            "decision": "FAIL",
            "instruction": "",
            "reasoning": "Cannot find the required element",
        }

        agent = PlannerGrounderAgent(
            planner="claude-sonnet-4-20250514",
            grounder="gpt-4.1-mini",
            planner_provider="anthropic",
            grounder_provider="openai",
        )
        action = agent.act(observation, task)

        assert action.type == "done"
        assert "fail_reason" in action.raw_action

    @patch("openadapt_evals.vlm.vlm_call")
    @patch("openadapt_evals.vlm.extract_json")
    def test_vlm_planner_json_parse_failure_uses_raw_text(
        self, mock_extract, mock_vlm, observation, task
    ):
        """When planner JSON parse fails, raw text is used as instruction."""
        mock_vlm.return_value = "Click the big red button"
        mock_extract.return_value = None  # JSON extraction fails

        agent = PlannerGrounderAgent(
            planner="claude-sonnet-4-20250514",
            grounder=MockGrounderAgent(),
            planner_provider="anthropic",
        )
        action = agent.act(observation, task)

        # Should still produce an action because raw text fallback is used.
        assert action.type == "click"


class TestGrounderRetry:
    @patch("openadapt_evals.vlm.vlm_call")
    @patch("openadapt_evals.training.trl_rollout.parse_action_json")
    def test_grounder_retries_on_parse_failure(
        self, mock_parse, mock_vlm, observation, task
    ):
        """Grounder retries once with simplified prompt when first parse fails."""
        # First call fails (returns done from parse failure), second succeeds.
        mock_parse.side_effect = [
            BenchmarkAction(type="done"),  # First parse fails
            BenchmarkAction(type="click", x=0.5, y=0.3),  # Retry succeeds
        ]
        mock_vlm.return_value = "some output"

        agent = PlannerGrounderAgent(
            planner=MockPlannerAgent(),
            grounder="gpt-4.1-mini",
            grounder_provider="openai",
        )
        action = agent.act(observation, task)

        assert action.type == "click"
        assert action.x == 0.5
        # vlm_call called twice for grounder (original + retry).
        assert mock_vlm.call_count == 2

    @patch("openadapt_evals.vlm.vlm_call")
    @patch("openadapt_evals.training.trl_rollout.parse_action_json")
    def test_grounder_returns_done_after_both_fail(
        self, mock_parse, mock_vlm, observation, task
    ):
        """Grounder returns done when both attempts fail to parse."""
        mock_parse.return_value = BenchmarkAction(type="done")
        mock_vlm.return_value = "unparseable gibberish"

        agent = PlannerGrounderAgent(
            planner=MockPlannerAgent(),
            grounder="gpt-4.1-mini",
            grounder_provider="openai",
        )
        action = agent.act(observation, task)

        assert action.type == "done"


# -- Tests: HTTP grounder ----------------------------------------------------


class TestHTTPGrounder:
    def test_http_grounder_requires_endpoint(self):
        """grounder_provider='http' requires grounder_endpoint."""
        with pytest.raises(ValueError, match="grounder_endpoint is required"):
            PlannerGrounderAgent(
                planner=MockPlannerAgent(),
                grounder="http",
                grounder_provider="http",
            )

    @patch("requests.post")
    def test_http_grounder_calls_endpoint(self, mock_post, observation, task):
        """HTTP grounder calls OpenAI-compatible endpoint."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "choices": [{"message": {"content": '{"type": "click", "x": 0.7, "y": 0.2}'}}]
        }
        mock_post.return_value = mock_resp

        agent = PlannerGrounderAgent(
            planner=MockPlannerAgent(),
            grounder="http",
            grounder_provider="http",
            grounder_endpoint="http://gpu-box:8080",
        )
        action = agent.act(observation, task)

        assert action.type == "click"
        assert action.x == 0.7
        assert action.y == 0.2
        # Verify it called the OpenAI-compatible endpoint
        call_url = mock_post.call_args[0][0]
        assert "/v1/chat/completions" in call_url


# -- Tests: _action_to_planner_output helper ----------------------------------


class TestActionToPlannerOutput:
    def test_done_action(self):
        """Done action maps to DONE decision."""
        action = BenchmarkAction(
            type="done", raw_action={"reasoning": "all done"}
        )
        result = _action_to_planner_output(action)

        assert result["decision"] == "DONE"
        assert result["reasoning"] == "all done"

    def test_click_action_with_instruction(self):
        """Click action with instruction in raw_action uses that instruction."""
        action = BenchmarkAction(
            type="click",
            x=0.5,
            y=0.5,
            raw_action={"instruction": "Click the submit button"},
        )
        result = _action_to_planner_output(action)

        assert result["decision"] == "COMMAND"
        assert result["instruction"] == "Click the submit button"

    def test_click_action_without_raw_action(self):
        """Click action without raw_action falls back to action_to_string."""
        action = BenchmarkAction(type="click", x=0.5, y=0.3)
        result = _action_to_planner_output(action)

        assert result["decision"] == "COMMAND"
        assert "CLICK" in result["instruction"]
        assert "0.500" in result["instruction"]

    def test_done_action_no_raw_action(self):
        """Done action without raw_action still returns DONE."""
        action = BenchmarkAction(type="done")
        result = _action_to_planner_output(action)

        assert result["decision"] == "DONE"
        assert result["reasoning"] == ""


# -- Tests: Accessibility tree formatting -------------------------------------


class TestA11yTreeInPlanner:
    @patch("openadapt_evals.vlm.vlm_call")
    @patch("openadapt_evals.vlm.extract_json")
    def test_a11y_tree_included_in_planner_prompt(
        self, mock_extract, mock_vlm, task
    ):
        """Accessibility tree is formatted and included in the planner prompt."""
        observation = BenchmarkObservation(
            screenshot=b"\x89PNG\r\n\x1a\nfake",
            viewport=(1920, 1200),
            accessibility_tree={
                "role": "window",
                "name": "Desktop",
                "id": "1",
                "children": [
                    {"role": "button", "name": "Settings", "id": "2"},
                ],
            },
        )

        mock_extract.return_value = {
            "decision": "DONE",
            "instruction": "",
            "reasoning": "",
        }
        mock_vlm.return_value = "{}"

        agent = PlannerGrounderAgent(
            planner="claude-sonnet-4-20250514",
            grounder="gpt-4.1-mini",
            planner_provider="anthropic",
            grounder_provider="openai",
        )
        agent.act(observation, task)

        # Verify the prompt passed to vlm_call includes the a11y tree.
        call_args = mock_vlm.call_args_list[0]
        prompt = call_args.args[0] if call_args.args else call_args.kwargs.get("prompt", "")
        assert "Settings" in prompt
        assert "button" in prompt

    @patch("openadapt_evals.vlm.vlm_call")
    @patch("openadapt_evals.vlm.extract_json")
    def test_no_a11y_tree_uses_fallback(self, mock_extract, mock_vlm, task):
        """When no accessibility tree is available, prompt shows 'not available'."""
        observation = BenchmarkObservation(
            screenshot=b"\x89PNG\r\n\x1a\nfake",
            viewport=(1920, 1200),
            accessibility_tree=None,
        )

        mock_extract.return_value = {
            "decision": "DONE",
            "instruction": "",
            "reasoning": "",
        }
        mock_vlm.return_value = "{}"

        agent = PlannerGrounderAgent(
            planner="claude-sonnet-4-20250514",
            grounder="gpt-4.1-mini",
            planner_provider="anthropic",
            grounder_provider="openai",
        )
        agent.act(observation, task)

        call_args = mock_vlm.call_args_list[0]
        prompt = call_args.args[0] if call_args.args else call_args.kwargs.get("prompt", "")
        assert "(not available)" in prompt


# -- Tests: Mixed planner/grounder types -------------------------------------


class TestMixedTypes:
    def test_agent_planner_vlm_grounder(self, observation, task):
        """Agent planner + VLM grounder works correctly."""
        planner = MockPlannerAgent(instruction="Click the big button")

        with patch("openadapt_evals.vlm.vlm_call") as mock_vlm, patch(
            "openadapt_evals.training.trl_rollout.parse_action_json"
        ) as mock_parse:
            mock_vlm.return_value = '{"type": "click", "x": 0.5, "y": 0.3}'
            mock_parse.return_value = BenchmarkAction(type="click", x=0.5, y=0.3)

            agent = PlannerGrounderAgent(
                planner=planner,
                grounder="gpt-4.1-mini",
                grounder_provider="openai",
            )
            action = agent.act(observation, task)

            assert action.type == "click"
            assert action.x == 0.5

    @patch("openadapt_evals.vlm.vlm_call")
    @patch("openadapt_evals.vlm.extract_json")
    def test_vlm_planner_agent_grounder(
        self, mock_extract, mock_vlm, observation, task
    ):
        """VLM planner + agent grounder works correctly."""
        mock_extract.return_value = {
            "decision": "COMMAND",
            "instruction": "Click OK",
            "reasoning": "",
        }
        mock_vlm.return_value = "{}"

        grounder = MockGrounderAgent(x=0.9, y=0.1)

        agent = PlannerGrounderAgent(
            planner="claude-sonnet-4-20250514",
            grounder=grounder,
            planner_provider="anthropic",
        )
        action = agent.act(observation, task)

        assert action.type == "click"
        assert action.x == 0.9
        assert action.y == 0.1
