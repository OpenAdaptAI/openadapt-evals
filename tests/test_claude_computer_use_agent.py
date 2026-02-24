"""Tests for ClaudeComputerUseAgent.

Tests cover:
1. Action mapping from Claude computer_use tool_use blocks to BenchmarkAction
2. Conversation management across steps
3. Demo injection in initial messages
4. Screenshot encoding
5. Coordinate normalization
6. Reset behavior
"""

import base64
from io import BytesIO
from unittest.mock import MagicMock, Mock, patch

import pytest
from PIL import Image

from openadapt_evals.adapters.base import (
    BenchmarkAction,
    BenchmarkObservation,
    BenchmarkTask,
)


def create_test_screenshot(width=1280, height=720):
    """Create a minimal test PNG screenshot."""
    img = Image.new("RGB", (width, height), color="blue")
    buffer = BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


def create_tool_use_block(action_type, **kwargs):
    """Create a mock tool_use content block."""
    block = Mock()
    block.type = "tool_use"
    block.name = "computer"
    block.id = f"toolu_{action_type}_001"
    block.input = {"action": action_type, **kwargs}
    return block


def create_text_block(text):
    """Create a mock text content block."""
    block = Mock()
    block.type = "text"
    block.text = text
    return block


def create_mock_response(*blocks):
    """Create a mock API response with given content blocks."""
    response = Mock()
    response.content = list(blocks)
    return response


def make_task(instruction="Open Notepad"):
    return BenchmarkTask(task_id="test_001", instruction=instruction, domain="desktop")


def make_observation(screenshot_bytes=None, viewport=(1280, 720)):
    if screenshot_bytes is None:
        screenshot_bytes = create_test_screenshot(*viewport)
    return BenchmarkObservation(screenshot=screenshot_bytes, viewport=viewport)


@pytest.fixture
def mock_anthropic_client():
    """Create a mock Anthropic client."""
    client = Mock()
    client.beta = Mock()
    client.beta.messages = Mock()
    return client


@pytest.fixture
def agent(mock_anthropic_client):
    """Create a ClaudeComputerUseAgent with mocked client."""
    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key-123"}):
        with patch("anthropic.Anthropic", return_value=mock_anthropic_client):
            from openadapt_evals.agents.claude_computer_use_agent import (
                ClaudeComputerUseAgent,
            )

            return ClaudeComputerUseAgent()


@pytest.fixture
def agent_with_demo(mock_anthropic_client):
    """Create a ClaudeComputerUseAgent with a demo."""
    with patch.dict("os.environ", {"ANTHROPIC_API_KEY": "test-key-123"}):
        with patch("anthropic.Anthropic", return_value=mock_anthropic_client):
            from openadapt_evals.agents.claude_computer_use_agent import (
                ClaudeComputerUseAgent,
            )

            return ClaudeComputerUseAgent(
                demo="Step 1: Click Start menu\nStep 2: Type notepad"
            )


class TestActionMapping:
    """Test mapping from Claude tool_use inputs to BenchmarkAction."""

    def test_left_click(self, agent, mock_anthropic_client):
        """Left click maps to BenchmarkAction(type='click') with normalized coords."""
        response = create_mock_response(
            create_tool_use_block("left_click", coordinate=[640, 360])
        )
        mock_anthropic_client.beta.messages.create.return_value = response

        action = agent.act(make_observation(), make_task())

        assert action.type == "click"
        assert abs(action.x - 0.5) < 0.01  # 640/1280 = 0.5
        assert abs(action.y - 0.5) < 0.01  # 360/720 = 0.5

    def test_right_click(self, agent, mock_anthropic_client):
        """Right click maps to click with click_variant in raw_action."""
        response = create_mock_response(
            create_tool_use_block("right_click", coordinate=[100, 200])
        )
        mock_anthropic_client.beta.messages.create.return_value = response

        action = agent.act(make_observation(), make_task())

        assert action.type == "click"
        assert action.raw_action["click_variant"] == "right_click"

    def test_double_click(self, agent, mock_anthropic_client):
        """Double click maps to click with click_variant in raw_action."""
        response = create_mock_response(
            create_tool_use_block("double_click", coordinate=[100, 200])
        )
        mock_anthropic_client.beta.messages.create.return_value = response

        action = agent.act(make_observation(), make_task())

        assert action.type == "click"
        assert action.raw_action["click_variant"] == "double_click"

    def test_type_action(self, agent, mock_anthropic_client):
        """Type action maps to BenchmarkAction(type='type')."""
        response = create_mock_response(
            create_tool_use_block("type", text="Hello world")
        )
        mock_anthropic_client.beta.messages.create.return_value = response

        action = agent.act(make_observation(), make_task())

        assert action.type == "type"
        assert action.text == "Hello world"

    def test_key_simple(self, agent, mock_anthropic_client):
        """Simple key press maps correctly."""
        response = create_mock_response(
            create_tool_use_block("key", text="Return")
        )
        mock_anthropic_client.beta.messages.create.return_value = response

        action = agent.act(make_observation(), make_task())

        assert action.type == "key"
        assert action.key == "Return"
        assert action.modifiers is None

    def test_key_with_modifier(self, agent, mock_anthropic_client):
        """Key with modifier splits correctly."""
        response = create_mock_response(
            create_tool_use_block("key", text="ctrl+s")
        )
        mock_anthropic_client.beta.messages.create.return_value = response

        action = agent.act(make_observation(), make_task())

        assert action.type == "key"
        assert action.key == "s"
        assert action.modifiers == ["ctrl"]

    def test_scroll_action(self, agent, mock_anthropic_client):
        """Scroll maps to BenchmarkAction(type='scroll')."""
        response = create_mock_response(
            create_tool_use_block(
                "scroll",
                coordinate=[640, 400],
                scroll_direction="down",
                scroll_amount=3,
            )
        )
        mock_anthropic_client.beta.messages.create.return_value = response

        action = agent.act(make_observation(), make_task())

        assert action.type == "scroll"
        assert action.scroll_direction == "down"
        assert action.scroll_amount == 3.0

    def test_drag_action(self, agent, mock_anthropic_client):
        """Drag maps to BenchmarkAction(type='drag') with normalized coords."""
        response = create_mock_response(
            create_tool_use_block(
                "left_click_drag",
                startCoordinate=[128, 72],
                endCoordinate=[640, 360],
            )
        )
        mock_anthropic_client.beta.messages.create.return_value = response

        action = agent.act(make_observation(), make_task())

        assert action.type == "drag"
        assert abs(action.x - 0.1) < 0.01  # 128/1280 = 0.1
        assert abs(action.y - 0.1) < 0.01  # 72/720 = 0.1
        assert abs(action.end_x - 0.5) < 0.01
        assert abs(action.end_y - 0.5) < 0.01

    def test_no_tool_use_returns_done(self, agent, mock_anthropic_client):
        """Response with no tool_use block maps to done."""
        response = create_mock_response(
            create_text_block("Task completed successfully.")
        )
        mock_anthropic_client.beta.messages.create.return_value = response

        action = agent.act(make_observation(), make_task())

        assert action.type == "done"
        assert "no_tool_use" in action.raw_action.get("reason", "")

    def test_screenshot_action_returns_done(self, agent, mock_anthropic_client):
        """Screenshot action maps to done (next step sends screenshot back)."""
        response = create_mock_response(
            create_tool_use_block("screenshot")
        )
        mock_anthropic_client.beta.messages.create.return_value = response

        action = agent.act(make_observation(), make_task())

        assert action.type == "done"

    def test_wait_action_returns_done(self, agent, mock_anthropic_client):
        """Wait action maps to done."""
        response = create_mock_response(
            create_tool_use_block("wait", duration=1.0)
        )
        mock_anthropic_client.beta.messages.create.return_value = response

        action = agent.act(make_observation(), make_task())

        assert action.type == "done"


class TestConversationManagement:
    """Test that conversation state is maintained across steps."""

    def test_first_step_sends_task_instruction(self, agent, mock_anthropic_client):
        """First step builds initial messages with task instruction."""
        response = create_mock_response(
            create_tool_use_block("left_click", coordinate=[100, 100])
        )
        mock_anthropic_client.beta.messages.create.return_value = response

        agent.act(make_observation(), make_task("Open Notepad"))

        call_args = mock_anthropic_client.beta.messages.create.call_args
        messages = call_args.kwargs["messages"]
        # After act(): messages = [user(initial), assistant(response)]
        # The list is mutated after the call, so we see the post-call state
        assert len(messages) == 2
        assert messages[0]["role"] == "user"
        assert messages[1]["role"] == "assistant"
        # Check task instruction is in the content
        content = messages[0]["content"]
        text_parts = [p["text"] for p in content if p.get("type") == "text"]
        assert any("Open Notepad" in t for t in text_parts)

    def test_second_step_sends_tool_result(self, agent, mock_anthropic_client):
        """Second step sends screenshot as tool_result."""
        # Step 1: click
        response1 = create_mock_response(
            create_tool_use_block("left_click", coordinate=[100, 100])
        )
        mock_anthropic_client.beta.messages.create.return_value = response1
        agent.act(make_observation(), make_task())

        # Step 2: type
        response2 = create_mock_response(
            create_tool_use_block("type", text="hello")
        )
        mock_anthropic_client.beta.messages.create.return_value = response2
        agent.act(make_observation(), make_task())

        # After both steps, messages list has been mutated to:
        # [user(initial), assistant(step1), user(tool_result), assistant(step2)]
        call_args = mock_anthropic_client.beta.messages.create.call_args
        messages = call_args.kwargs["messages"]
        assert len(messages) == 4
        assert messages[0]["role"] == "user"
        assert messages[1]["role"] == "assistant"
        assert messages[2]["role"] == "user"
        assert messages[3]["role"] == "assistant"
        # Check tool_result structure in second user message
        tool_result = messages[2]["content"][0]
        assert tool_result["type"] == "tool_result"
        assert tool_result["tool_use_id"] == "toolu_left_click_001"

    def test_uses_beta_api(self, agent, mock_anthropic_client):
        """Verifies the beta API is used with correct betas parameter."""
        response = create_mock_response(
            create_tool_use_block("left_click", coordinate=[100, 100])
        )
        mock_anthropic_client.beta.messages.create.return_value = response

        agent.act(make_observation(), make_task())

        call_args = mock_anthropic_client.beta.messages.create.call_args
        assert "betas" in call_args.kwargs
        assert "computer-use-2025-11-24" in call_args.kwargs["betas"]

    def test_uses_computer_tool(self, agent, mock_anthropic_client):
        """Verifies computer_20251124 tool is passed."""
        response = create_mock_response(
            create_tool_use_block("left_click", coordinate=[100, 100])
        )
        mock_anthropic_client.beta.messages.create.return_value = response

        agent.act(make_observation(), make_task())

        call_args = mock_anthropic_client.beta.messages.create.call_args
        tools = call_args.kwargs["tools"]
        assert len(tools) == 1
        assert tools[0]["type"] == "computer_20251124"
        assert tools[0]["name"] == "computer"
        assert tools[0]["display_width_px"] == 1280
        assert tools[0]["display_height_px"] == 720

    def test_reset_clears_state(self, agent, mock_anthropic_client):
        """Reset clears conversation history."""
        response = create_mock_response(
            create_tool_use_block("left_click", coordinate=[100, 100])
        )
        mock_anthropic_client.beta.messages.create.return_value = response

        agent.act(make_observation(), make_task())
        assert agent._step_count == 1
        assert len(agent._messages) > 0

        agent.reset()
        assert agent._step_count == 0
        assert len(agent._messages) == 0
        assert agent._last_tool_use_id is None


class TestDemoInjection:
    """Test demo conditioning support."""

    def test_demo_included_in_first_step(self, agent_with_demo, mock_anthropic_client):
        """Demo text is included in the first step's user message."""
        response = create_mock_response(
            create_tool_use_block("left_click", coordinate=[100, 100])
        )
        mock_anthropic_client.beta.messages.create.return_value = response

        agent_with_demo.act(make_observation(), make_task("Open Notepad"))

        call_args = mock_anthropic_client.beta.messages.create.call_args
        messages = call_args.kwargs["messages"]
        content = messages[0]["content"]
        text_parts = [p["text"] for p in content if p.get("type") == "text"]
        full_text = " ".join(text_parts)
        assert "demonstration" in full_text.lower()
        assert "Click Start menu" in full_text
        assert "Open Notepad" in full_text

    def test_no_demo_sends_plain_instruction(self, agent, mock_anthropic_client):
        """Without demo, just sends task instruction."""
        response = create_mock_response(
            create_tool_use_block("left_click", coordinate=[100, 100])
        )
        mock_anthropic_client.beta.messages.create.return_value = response

        agent.act(make_observation(), make_task("Open Notepad"))

        call_args = mock_anthropic_client.beta.messages.create.call_args
        messages = call_args.kwargs["messages"]
        content = messages[0]["content"]
        text_parts = [p["text"] for p in content if p.get("type") == "text"]
        full_text = " ".join(text_parts)
        assert "Task: Open Notepad" in full_text
        assert "demonstration" not in full_text.lower()


class TestScreenshotEncoding:
    """Test screenshot encoding and display dimension handling."""

    def test_screenshot_bytes_encoded(self, agent, mock_anthropic_client):
        """Screenshot bytes are base64 encoded in messages."""
        response = create_mock_response(
            create_tool_use_block("left_click", coordinate=[100, 100])
        )
        mock_anthropic_client.beta.messages.create.return_value = response

        obs = make_observation()
        agent.act(obs, make_task())

        call_args = mock_anthropic_client.beta.messages.create.call_args
        messages = call_args.kwargs["messages"]
        content = messages[0]["content"]
        image_parts = [p for p in content if p.get("type") == "image"]
        assert len(image_parts) == 1
        assert image_parts[0]["source"]["media_type"] == "image/png"
        # Verify it's valid base64
        decoded = base64.b64decode(image_parts[0]["source"]["data"])
        assert len(decoded) > 0

    def test_viewport_updates_display_dimensions(self, agent, mock_anthropic_client):
        """Display dimensions update from observation viewport."""
        response = create_mock_response(
            create_tool_use_block("left_click", coordinate=[960, 540])
        )
        mock_anthropic_client.beta.messages.create.return_value = response

        obs = make_observation(
            screenshot_bytes=create_test_screenshot(1920, 1080),
            viewport=(1920, 1080),
        )
        action = agent.act(obs, make_task())

        # Coordinates should be normalized against 1920x1080
        assert abs(action.x - 0.5) < 0.01  # 960/1920 = 0.5
        assert abs(action.y - 0.5) < 0.01  # 540/1080 = 0.5

    def test_no_screenshot_still_works(self, agent, mock_anthropic_client):
        """Agent works even without a screenshot."""
        response = create_mock_response(
            create_text_block("I cannot see the screen.")
        )
        mock_anthropic_client.beta.messages.create.return_value = response

        obs = BenchmarkObservation(screenshot=None)
        action = agent.act(obs, make_task())

        assert action.type == "done"


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_api_error_returns_done(self, agent, mock_anthropic_client):
        """API error results in done action."""
        mock_anthropic_client.beta.messages.create.side_effect = Exception("API error")

        action = agent.act(make_observation(), make_task())

        assert action.type == "done"
        assert "error" in (action.raw_action or {})

    def test_unknown_action_returns_done(self, agent, mock_anthropic_client):
        """Unknown action type returns done."""
        response = create_mock_response(
            create_tool_use_block("unknown_action_xyz")
        )
        mock_anthropic_client.beta.messages.create.return_value = response

        action = agent.act(make_observation(), make_task())

        assert action.type == "done"

    def test_key_with_multiple_modifiers(self, agent, mock_anthropic_client):
        """Key with multiple modifiers splits correctly."""
        response = create_mock_response(
            create_tool_use_block("key", text="ctrl+shift+s")
        )
        mock_anthropic_client.beta.messages.create.return_value = response

        action = agent.act(make_observation(), make_task())

        assert action.type == "key"
        assert action.key == "s"
        assert action.modifiers == ["ctrl", "shift"]

    def test_coordinate_edge_values(self, agent, mock_anthropic_client):
        """Coordinates at display edges normalize correctly."""
        response = create_mock_response(
            create_tool_use_block("left_click", coordinate=[0, 0])
        )
        mock_anthropic_client.beta.messages.create.return_value = response

        action = agent.act(make_observation(), make_task())

        assert action.type == "click"
        assert action.x == 0.0
        assert action.y == 0.0

    def test_missing_api_key_raises(self):
        """Missing API key raises RuntimeError."""
        with patch.dict("os.environ", {}, clear=True):
            # Remove ANTHROPIC_API_KEY
            import os

            orig = os.environ.pop("ANTHROPIC_API_KEY", None)
            try:
                from openadapt_evals.agents.claude_computer_use_agent import (
                    ClaudeComputerUseAgent,
                )

                with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
                    ClaudeComputerUseAgent()
            finally:
                if orig:
                    os.environ["ANTHROPIC_API_KEY"] = orig


class TestImport:
    """Test that the agent can be imported from the package."""

    def test_import_from_agents_package(self):
        """ClaudeComputerUseAgent is importable from agents package."""
        from openadapt_evals.agents import ClaudeComputerUseAgent

        assert ClaudeComputerUseAgent is not None

    def test_in_all(self):
        """ClaudeComputerUseAgent is in __all__."""
        from openadapt_evals import agents

        assert "ClaudeComputerUseAgent" in agents.__all__
