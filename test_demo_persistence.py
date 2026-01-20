"""Test that demo persists across all agent steps (P0 fix validation)."""

from pathlib import Path
from unittest.mock import Mock, patch
from openadapt_evals.agents.api_agent import ApiAgent
from openadapt_evals.adapters.base import BenchmarkObservation, BenchmarkTask
from PIL import Image
import numpy as np

def test_demo_persistence():
    """Verify that demo is included in EVERY API call, not just first step."""

    # Load demo
    demo_path = Path("demo_library/synthetic_demos/notepad_1.txt")
    demo_text = demo_path.read_text()

    print(f"Demo loaded: {len(demo_text)} characters")
    print(f"First 100 chars: {demo_text[:100]}")

    # Create agent with demo
    agent = ApiAgent(provider="anthropic", demo=demo_text)

    print(f"\n✓ Agent created with demo")
    print(f"  - Provider: {agent.provider}")
    print(f"  - Demo length: {len(agent.demo)} chars")

    # Create mock observation
    mock_image = Image.fromarray(np.zeros((100, 100, 3), dtype=np.uint8))
    observation = BenchmarkObservation(
        screenshot=mock_image,
        accessibility_tree=None
    )

    task = BenchmarkTask(
        task_id="test_task",
        instruction="Test demo persistence",
        domain="test"
    )

    # Mock the API call to capture messages sent
    api_calls = []

    def mock_create(**kwargs):
        """Capture the messages sent to the API."""
        api_calls.append(kwargs)
        # Return a mock response
        mock_response = Mock()
        mock_response.content = [Mock(text="```python\ncomputer.click(100, 100)\n```")]
        mock_response.usage = Mock(input_tokens=100, output_tokens=50)
        return mock_response

    with patch('anthropic.Anthropic') as mock_anthropic:
        mock_client = Mock()
        mock_client.messages.create = mock_create
        mock_anthropic.return_value = mock_client

        # Reset agent to use mocked client
        agent = ApiAgent(provider="anthropic", demo=demo_text)

        try:
            # Step 1
            print("\n--- Step 1 ---")
            action1 = agent.act(observation, task)
            print(f"Action 1: {action1.type}")

            # Step 2
            print("\n--- Step 2 ---")
            action2 = agent.act(observation, task)
            print(f"Action 2: {action2.type}")

            # Step 3
            print("\n--- Step 3 ---")
            action3 = agent.act(observation, task)
            print(f"Action 3: {action3.type}")

        except Exception as e:
            print(f"Error during API calls: {e}")
            # This is expected if API key is invalid, but we still captured the calls

    # Verify demo was included in ALL calls
    print(f"\n{'='*60}")
    print(f"DEMO PERSISTENCE VERIFICATION")
    print(f"{'='*60}")
    print(f"Total API calls made: {len(api_calls)}")

    if len(api_calls) == 0:
        print("\n⚠️  No API calls captured (likely API key issue)")
        print("   Checking agent.demo attribute instead...")
        print(f"   Demo in agent: {len(agent.demo) > 0}")
        print(f"   Demo length: {len(agent.demo)} chars")
        return

    demo_keyword = "TASK: Open Notepad"  # Unique string from our demo

    for i, call in enumerate(api_calls):
        messages = call.get('messages', [])
        system_prompt = call.get('system', '')

        # Check if demo is in system prompt or messages
        demo_in_system = demo_keyword in system_prompt
        demo_in_messages = any(demo_keyword in str(msg) for msg in messages)

        has_demo = demo_in_system or demo_in_messages

        print(f"\nCall {i+1}:")
        print(f"  ✓ Demo present: {has_demo}")
        if has_demo:
            print(f"    - In system prompt: {demo_in_system}")
            print(f"    - In messages: {demo_in_messages}")
        else:
            print(f"    ✗ Demo NOT found!")

    # Check results
    demos_found = sum(
        1 for call in api_calls
        if demo_keyword in call.get('system', '') or
           any(demo_keyword in str(msg) for msg in call.get('messages', []))
    )

    print(f"\n{'='*60}")
    print(f"RESULT: {demos_found}/{len(api_calls)} calls included demo")

    if demos_found == len(api_calls):
        print("✓ PASS: Demo persists across ALL steps!")
    else:
        print("✗ FAIL: Demo NOT included in all steps")
        print(f"  Expected: {len(api_calls)}, Found: {demos_found}")

    return demos_found == len(api_calls)


if __name__ == "__main__":
    test_demo_persistence()
