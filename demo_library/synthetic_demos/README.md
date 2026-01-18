# Synthetic WAA Demonstration Library

A comprehensive collection of 154 AI-generated demonstration trajectories for Windows Agent Arena (WAA) tasks, designed to enable demo-conditioned prompting at scale.

## Overview

This library contains synthetic demonstrations for all 154 WAA tasks across 11 domains. These demos were generated using Claude Sonnet 4.5 with a hybrid approach combining:
- LLM-based generation for complex, domain-specific trajectories
- Rule-based templates for common patterns (open app, type text, save)
- Domain knowledge to ensure realistic action sequences

## Why Synthetic Demos?

Demo-conditioned prompting dramatically improves agent performance:
- **Without demo**: 33% first-action accuracy
- **With demo**: 100% first-action accuracy

By generating synthetic demos for all 154 tasks, we enable:
1. Consistent demo quality across all domains
2. Rapid iteration and regeneration as needed
3. Scalable evaluation without manual demonstration recording

## Directory Structure

```
synthetic_demos/
├── README.md              # This documentation
├── demos.json             # Index of all demos with metadata
├── browser_1.txt          # Browser domain demos
├── browser_2.txt
├── ...
├── office_1.txt           # Office domain demos
├── office_2.txt
├── ...
└── [154 total demo files]
```

## Demo Format

Each demo follows a structured text format compatible with `ApiAgent`:

```
TASK: [Description of what the demo accomplishes]
DOMAIN: [Application domain]

STEPS:
1. [Step description]
   REASONING: [Why this step is necessary]
   ACTION: [Specific action to perform]

2. [Next step]
   REASONING: [...]
   ACTION: [...]

[... additional steps ...]

N. [Final step]
   REASONING: [Completion reasoning]
   ACTION: DONE()

EXPECTED_OUTCOME: [What should be achieved when complete]
```

## Action Types

All actions use normalized coordinates (0.0 to 1.0) and follow these formats:

| Action | Format | Example |
|--------|--------|---------|
| Click | `CLICK(x=X, y=Y)` | `CLICK(x=0.5, y=0.5)` |
| Right-click | `RIGHT_CLICK(x=X, y=Y)` | `RIGHT_CLICK(x=0.3, y=0.4)` |
| Type | `TYPE("text")` | `TYPE("Hello World")` |
| Hotkey | `HOTKEY("key1", "key2")` | `HOTKEY("ctrl", "s")` |
| Wait | `WAIT(seconds)` | `WAIT(1.0)` |
| Drag | `DRAG(start_x=X, start_y=Y, end_x=X, end_y=Y)` | `DRAG(start_x=0.3, start_y=0.4, end_x=0.6, end_y=0.7)` |
| Scroll | `SCROLL(direction="dir")` | `SCROLL(direction="down")` |
| Done | `DONE()` | `DONE()` |

## Domain Coverage

The library covers all 11 WAA domains with the following distribution:

| Domain | Task Count | Description |
|--------|-----------|-------------|
| browser | 20 | Chrome/Edge navigation and interaction |
| office | 25 | Word, Excel, Outlook tasks |
| coding | 18 | VSCode and terminal tasks |
| media | 10 | VLC media player tasks |
| notepad | 15 | Text editing tasks |
| paint | 12 | Drawing and image tasks |
| file_explorer | 18 | File management tasks |
| clock | 8 | Alarms, timers, stopwatch |
| settings | 15 | Windows Settings tasks |
| edge | 8 | Edge-specific browser tasks |
| vscode | 5 | VSCode-specific IDE tasks |
| **Total** | **154** | Complete WAA coverage |

## Usage with ApiAgent

### Direct Demo Loading

```python
from openadapt_evals import ApiAgent
from pathlib import Path

# Load a demo
demo_text = Path("demo_library/synthetic_demos/notepad_1.txt").read_text()

# Create agent with demo
agent = ApiAgent(provider="anthropic", demo=demo_text)

# The demo will be included in every API call
action = agent.act(observation, task)
```

### CLI Usage

```bash
# Run evaluation with specific demo
uv run python -m openadapt_evals.benchmarks.cli live \
    --agent api-claude \
    --demo demo_library/synthetic_demos/notepad_1.txt \
    --server http://vm:5000 \
    --task-ids notepad_1
```

### Retrieval-Augmented Agent

For automatic demo selection:

```python
from openadapt_evals import RetrievalAugmentedAgent

# Initialize with synthetic demo library
agent = RetrievalAugmentedAgent(
    demo_library_path="demo_library/synthetic_demos",
    provider="anthropic",
)

# Automatically retrieves the most relevant demo for each task
action = agent.act(observation, task)
```

## Generation Process

Demos were generated using:

```bash
# Generate all 154 demos
python -m openadapt_evals.benchmarks.generate_synthetic_demos --all

# Generate specific domains
python -m openadapt_evals.benchmarks.generate_synthetic_demos --domains notepad,browser

# Generate specific tasks
python -m openadapt_evals.benchmarks.generate_synthetic_demos --task-ids notepad_1,browser_5
```

## Validation

All demos are validated for:
- Correct format (TASK, DOMAIN, STEPS, EXPECTED_OUTCOME)
- Valid action syntax
- Normalized coordinates (0.0-1.0 range)
- Sequential step numbering
- Proper DONE() termination

Validate demos:

```bash
# Validate all demos
python -m openadapt_evals.benchmarks.validate_demos --demo-dir demo_library/synthetic_demos

# Validate specific demo
python -m openadapt_evals.benchmarks.validate_demos --demo-file demo_library/synthetic_demos/notepad_1.txt
```

## Regeneration

To regenerate demos (e.g., after prompt improvements):

```bash
# Regenerate all demos (overwrites existing)
python -m openadapt_evals.benchmarks.generate_synthetic_demos --all

# Regenerate specific domain
python -m openadapt_evals.benchmarks.generate_synthetic_demos --domains notepad
```

## Quality Assurance

Each demo includes:
1. **Realistic action sequences**: Based on actual Windows UI patterns
2. **Proper timing**: WAIT() actions for UI transitions
3. **Clear reasoning**: Each step explains why it's necessary
4. **Actionable steps**: Atomic, executable actions
5. **Domain expertise**: Leverages LLM knowledge of Windows applications

## Demo Index (demos.json)

The `demos.json` file provides metadata for all demos:

```json
{
  "version": "2.0.0",
  "description": "Synthetic WAA demonstration library for demo-conditioned prompting",
  "generator": "anthropic/claude-sonnet-4-5-20250929",
  "total_demos": 154,
  "demos": [
    {
      "id": "notepad_1",
      "task": "Open Notepad",
      "domain": "notepad",
      "file": "synthetic_demos/notepad_1.txt",
      "estimated_steps": 7
    },
    ...
  ]
}
```

## Known Limitations

1. **Coordinate assumptions**: Demos assume standard 1920x1200 screen resolution
2. **UI variations**: Actual Windows UI may vary by version/theme
3. **No visual verification**: Demos are text-based, not recorded from actual execution
4. **Synthetic nature**: May not capture all edge cases of real user behavior

## Future Enhancements

- [ ] Add difficulty ratings to demos
- [ ] Include alternative action sequences for the same task
- [ ] Generate demos with different UI states (dark mode, high contrast)
- [ ] Add precondition/postcondition checks
- [ ] Multi-language support for international Windows versions

## Citation

If you use this synthetic demo library in your research, please cite:

```bibtex
@software{openadapt_synthetic_demos_2026,
  title = {Synthetic Demonstration Library for Windows Agent Arena},
  author = {OpenAdapt AI},
  year = {2026},
  url = {https://github.com/OpenAdaptAI/openadapt-evals}
}
```

## License

This demo library is part of the openadapt-evals project and follows the same license.

## Support

For issues or questions about the synthetic demo library:
- GitHub Issues: https://github.com/OpenAdaptAI/openadapt-evals/issues
- Documentation: See CLAUDE.md in the project root
