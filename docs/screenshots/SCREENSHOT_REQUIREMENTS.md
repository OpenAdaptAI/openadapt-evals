# Screenshot Requirements

## Critical Requirement: Real Live Actions

**Problem**: Current benchmark viewers and demos have shown idle Windows desktop screenshots with no visible actions taking place. This creates a misleading impression of capabilities and makes it impossible to demonstrate or debug agent behavior.

**Solution**: All screenshots in benchmark viewers, documentation, demos, and evaluations MUST show real actions being performed by the agent or user.

## What Constitutes a "Good Screenshot"

A screenshot shows "real live actions" when it displays:

### ✅ Good Examples (REQUIRED)

1. **GUI Element Interaction**
   - Mouse cursor visible near or on a clickable element
   - Button highlighted/pressed state
   - Menu dropdown open
   - Dialog box with form fields being filled
   - Text selection visible
   - Window focus indicator active

2. **Visible State Changes**
   - Text appearing in a text editor as it's being typed
   - File save dialog showing the save process
   - Application window opening/closing animation
   - Scroll position changing between frames
   - Checkbox toggling between states
   - Tab switching with visible tab selection

3. **Action Evidence**
   - Cursor positioned at text insertion point (blinking caret)
   - Partially typed text in search box
   - Right-click context menu visible
   - Drag-and-drop in progress (item being dragged)
   - Window being resized (resize handles visible)
   - Progress bar showing ongoing operation

4. **Sequential Action Proof**
   - Before/after pairs showing state change
   - Multiple windows showing multi-step task
   - Breadcrumb trail in file explorer showing navigation
   - Multiple form fields filled in sequence
   - Search results appearing after query input

### ❌ Bad Examples (NOT ACCEPTABLE)

1. **Idle Desktop**
   - Empty Windows 11 desktop with wallpaper
   - Start menu closed, no applications open
   - Blank desktop with only taskbar visible
   - No mouse cursor or interaction visible
   - Static wallpaper with no active windows

2. **Blank/Empty Windows**
   - Notepad open with completely empty document
   - Browser showing blank page or new tab
   - File explorer with no selection or activity
   - Application windows with no content loaded
   - Dialog boxes that haven't been interacted with

3. **Loading/Waiting States**
   - Application splash screens
   - "Loading..." messages with no progress
   - Frozen/hung application windows
   - Blank white screens during app startup
   - Windows showing error messages without context

4. **Non-Interactive States**
   - Screenshot of screenshot (meta-screenshot)
   - Static documentation pages
   - Windows lock screen
   - Screen saver active
   - System sleep/hibernate screen

## Required Data Sources

To ensure screenshots show real actions, use one of these approved data sources:

### Option A: Real WAA Evaluation (PREFERRED)

Run actual WAA benchmark tasks and capture screenshots during execution:

```bash
# Run real WAA evaluation with screenshot capture
uv run python -m openadapt_evals.benchmarks.cli live \
    --agent api-claude \
    --server http://vm:5000 \
    --task-ids notepad_1,browser_5,office_3 \
    --save-screenshots
```

**Requirements:**
- VM must be running with WAA server active
- Agent must be executing real task instructions
- Screenshots captured at each action step
- Minimum 5 steps per task to show progression

**Verification:**
- Check that task succeeds or shows genuine attempt
- Verify cursor/interaction visible in screenshots
- Confirm state changes between consecutive screenshots
- Validate screenshots show actual GUI elements being used

### Option B: OpenAdapt Nightshift Recording (REAL macOS DATA)

Use the nightshift OpenAdapt recording that contains real macOS user interactions:

**Location:** `/path/to/openadapt/recordings/nightshift_recording.db`

**Why This Works:**
- Captured from real user performing real tasks
- Shows genuine macOS UI interactions
- Contains natural mouse movements and clicks
- Demonstrates real application usage patterns

**Usage:**
```python
from openadapt.db import crud
from openadapt.models import Recording

# Load nightshift recording
recording = crud.get_latest_recording()

# Extract screenshots showing actions
screenshots = [
    event.screenshot for event in recording.action_events
    if event.name in ["click", "type", "drag"]
]
```

**Requirements:**
- Recording must contain ActionEvents with screenshots
- Screenshots must show cursor position
- Must include visible application windows
- Should show text input, clicks, or navigation

### Option C: Live Recording Session (FALLBACK)

Record a new session performing actual tasks:

```bash
# Record real task execution
uv run python -m openadapt.app record --task "Open Notepad and type hello"

# Extract screenshots from recording
uv run python -m openadapt_evals.benchmarks.extract_recording_screenshots \
    --recording-id <id> \
    --output-dir screenshots/
```

**Requirements:**
- Record real user performing actual task
- Minimum 10 actions per recording
- Include varied interaction types (click, type, drag)
- Capture at least 1 screenshot per second during actions

## Screenshot Validation

All screenshots MUST pass these validation checks before use:

### 1. Technical Validation (Automated)

```python
from openadapt_evals.benchmarks.validate_screenshots import ScreenshotValidator

validator = ScreenshotValidator()
result = validator.validate_single(
    screenshot_path="step_001.png",
    expected_keywords=["Notepad", "File", "Edit"]  # Expected UI text
)

if not result.is_valid:
    raise ValueError(f"Screenshot validation failed: {result.errors}")
```

**Checks:**
- File integrity (valid PNG/JPEG)
- Minimum dimensions (800x600)
- Not blank (all white/black)
- Reasonable color diversity (>10 unique colors)
- File size within bounds (1KB - 50MB)

### 2. Action Validation (Visual Inspection)

Manual inspection checklist:

- [ ] Cursor visible OR element clearly in focus
- [ ] GUI window visible (not just desktop)
- [ ] At least one interactive element visible (button, text field, menu)
- [ ] Screenshot differs from previous screenshot (action occurred)
- [ ] Timestamp/sequence number shows progression
- [ ] Task instruction matches visible action

### 3. Sequence Validation (Automated)

```python
from openadapt_evals.benchmarks.validate_screenshot_sequence import validate_sequence

# Check that screenshots show progression
result = validate_sequence(
    screenshots=["step_001.png", "step_002.png", "step_003.png"],
    min_change_threshold=0.01  # At least 1% pixel difference
)

if result.static_frames > 0:
    raise ValueError(f"Found {result.static_frames} static/duplicate screenshots")
```

**Checks:**
- Each screenshot differs from previous by at least 1%
- No more than 2 consecutive identical screenshots
- Sequence shows clear progression toward goal
- Final screenshot shows task completion or failure state

## Integration Points

### viewer.py - Benchmark Viewer Generation

Add validation when generating viewer HTML:

```python
# In generate_benchmark_viewer()
def generate_benchmark_viewer(
    benchmark_dir: Path,
    output_path: Path | None = None,
    embed_screenshots: bool = False,
    validate_screenshots: bool = True,  # NEW: Default to validating
) -> Path:
    """Generate HTML viewer for benchmark results.

    Args:
        validate_screenshots: If True, validates that screenshots show
            real actions (not idle desktop). Raises error if validation fails.
    """

    if validate_screenshots:
        validator = ScreenshotValidator()
        screenshots_dir = benchmark_dir / "screenshots"

        if screenshots_dir.exists():
            result = validator.validate_screenshots(screenshot_dir=screenshots_dir)

            if not result.all_valid:
                logger.warning(
                    f"Screenshot validation failed: {result.invalid}/{result.total} invalid. "
                    "Viewer may show idle desktop screenshots instead of real actions."
                )

                # Log specific issues
                for path, validation in result.results.items():
                    if not validation.is_valid:
                        logger.error(f"Invalid screenshot {path}: {validation.errors}")
```

### auto_screenshot.py - Screenshot Capture Tool

Add action detection when capturing screenshots:

```python
# In generate_screenshots()
def generate_screenshots(
    html_path: str | Path,
    output_dir: str | Path,
    require_actions: bool = True,  # NEW: Require visible actions
) -> dict[str, list[Path]]:
    """Generate screenshots of benchmark viewer.

    IMPORTANT: Screenshots must show real actions being performed,
    not idle desktop or blank windows.

    Args:
        require_actions: If True, validates that screenshots show visible
            GUI interactions (cursor, typed text, buttons, etc.).
    """

    if require_actions:
        # Verify page shows actual task execution
        page.wait_for_selector(".step-viewer", timeout=5000)

        # Check that screenshots show actions
        screenshot_img = page.query_selector("#screenshot-img")
        if not screenshot_img:
            raise ValueError("No screenshot visible in viewer - cannot capture real actions")
```

### CLI - Evaluation Commands

Add validation flag to CLI commands:

```bash
# Validate screenshots after evaluation
uv run python -m openadapt_evals.benchmarks.cli live \
    --agent api-claude \
    --server http://vm:5000 \
    --task-ids notepad_1 \
    --validate-screenshots  # NEW: Fail if screenshots are idle desktop

# Generate viewer with validation
uv run python -m openadapt_evals.benchmarks.cli view \
    --run-name waa_eval_20260116 \
    --validate-screenshots  # NEW: Warn about idle screenshots
```

## Common Failure Modes

### Issue 1: VM Not Running / Server Not Responding

**Symptom:** Screenshots show Windows desktop with no applications open.

**Cause:** WAA server failed to start or VM is not accessible.

**Solution:**
```bash
# Verify VM and server are running
uv run python -m openadapt_evals.benchmarks.cli probe --server http://vm:5000 --wait

# Check VM status
uv run python -m openadapt_evals.benchmarks.cli vm-status

# Restart WAA server if needed
uv run python -m openadapt_evals.benchmarks.cli server-start
```

### Issue 2: Agent Not Taking Actions

**Symptom:** Screenshots show Notepad open but empty, no text typed.

**Cause:** Agent's action commands not reaching WAA server or being rejected.

**Solution:**
- Check agent logs for action API call responses
- Verify action coordinates are valid (0.0-1.0 range)
- Test with known-good action sequence
- Enable verbose logging: `--log-level DEBUG`

### Issue 3: Screenshots Captured Too Early

**Symptom:** Screenshots show loading states or blank windows before content appears.

**Cause:** Screenshot captured before Windows UI finishes rendering.

**Solution:**
```python
# Add wait after action before capturing screenshot
action_result = await adapter.execute_action(action)
await asyncio.sleep(0.5)  # Wait for UI to update
screenshot = await adapter.get_screenshot()
```

### Issue 4: Mock Data Used Instead of Real Data

**Symptom:** Screenshots show synthetic/mock desktop with unrealistic elements.

**Cause:** Running with mock adapter instead of live WAA server.

**Solution:**
```bash
# Don't use mock adapter for demos/screenshots
# ❌ BAD
uv run python -m openadapt_evals.benchmarks.cli mock --tasks 10

# ✅ GOOD
uv run python -m openadapt_evals.benchmarks.cli live --server http://vm:5000 --task-ids notepad_1
```

## Testing Checklist

Before considering screenshots acceptable for demos, documentation, or viewer:

### Pre-Capture Checklist

- [ ] WAA server is running and responding (`curl http://vm:5000/probe`)
- [ ] Agent is configured correctly (API key set, model specified)
- [ ] Task IDs are valid and have evaluator configs
- [ ] VM has sufficient resources (CPU, memory, disk)
- [ ] Screenshot capture is enabled in configuration

### Post-Capture Checklist

- [ ] Screenshot files exist and are non-empty
- [ ] Screenshots pass automated validation (not blank, correct size)
- [ ] Visual inspection confirms actions visible
- [ ] Sequence shows clear progression (not identical frames)
- [ ] Task instruction matches visible actions in screenshots
- [ ] At least 5 screenshots per task showing different states

### Documentation Checklist

- [ ] Screenshots used in README show real actions
- [ ] Demo GIFs show actual agent executing tasks
- [ ] Viewer HTML includes real execution screenshots
- [ ] Tutorial examples use real data, not mocks
- [ ] Error examples show genuine failure modes

## Enforcement

To ensure this requirement is never forgotten:

1. **Code Comments**: All screenshot-related functions have explicit comments:
   ```python
   # IMPORTANT: Screenshots must show real actions, not idle desktop.
   # See SCREENSHOT_REQUIREMENTS.md for validation requirements.
   ```

2. **Validation by Default**: Screenshot validation is ENABLED by default, must be explicitly disabled:
   ```python
   generate_viewer(validate_screenshots=True)  # Default: True
   ```

3. **CI/CD Checks**: GitHub Actions validates screenshots in PRs:
   ```yaml
   - name: Validate screenshots
     run: uv run python -m openadapt_evals.benchmarks.validate_screenshots --screenshot-dir screenshots/
   ```

4. **Documentation**: This file (`SCREENSHOT_REQUIREMENTS.md`) is prominently linked from:
   - `README.md`
   - `CLAUDE.md`
   - `CONTRIBUTING.md`
   - Module docstrings in `viewer.py`, `auto_screenshot.py`, `validate_screenshots.py`

## Examples

### Good Screenshot Example (Notepad Task)

**Description:** Shows user typing "hello" into Notepad

**Visible Elements:**
- Notepad window in foreground
- Text "hel" partially typed (mid-action)
- Cursor blinking at insertion point
- Window title: "Untitled - Notepad"
- File menu visible showing Notepad is active

**Why Good:** Clearly shows text being typed, cursor position, active window state.

### Bad Screenshot Example (Idle Desktop)

**Description:** Windows 11 desktop with default wallpaper

**Visible Elements:**
- Desktop background (blue gradient)
- Taskbar at bottom
- No windows open
- No cursor visible
- Start menu closed

**Why Bad:** No evidence of any action being performed. Could be any Windows installation.

### Good Screenshot Example (Browser Navigation)

**Description:** Shows user clicking on search result

**Visible Elements:**
- Browser window with Google search results
- Mouse cursor over second search result link
- Link shows hover state (underlined, different color)
- Address bar shows "google.com/search?q=python"
- Multiple tabs open showing browsing session

**Why Good:** Clear evidence of user about to click, browser shows real content, multiple interaction points visible.

## Nightshift Recording Details

**What is Nightshift?**
Nightshift is a real OpenAdapt recording of actual macOS usage captured during evening hours. It contains genuine user interactions including:

- Opening and switching between applications
- Typing in text editors and terminals
- Web browsing and navigation
- File management operations
- System settings changes

**How to Access:**
```bash
# Location of nightshift recording
RECORDING_PATH="/path/to/openadapt/recordings/nightshift.db"

# Extract screenshots
python -c "
from openadapt.db import crud
from pathlib import Path

# Load nightshift recording
recording = crud.get_recording_by_name('nightshift')

# Save action screenshots
output_dir = Path('screenshots/nightshift')
output_dir.mkdir(parents=True, exist_ok=True)

for i, event in enumerate(recording.action_events[:20]):
    if event.screenshot:
        screenshot_path = output_dir / f'action_{i:03d}.png'
        event.screenshot.save(screenshot_path)
        print(f'Saved: {screenshot_path}')
"
```

**When to Use Nightshift:**
- Demos showing real macOS UI interactions
- Examples of natural user behavior
- Training data for action prediction models
- Validation of cross-platform compatibility

**Note:** Nightshift contains real user data. Ensure screenshots are reviewed for sensitive information (passwords, personal data) before public use.

## Questions & Answers

**Q: What if we need screenshots for testing but don't have a running VM?**

A: Use mock adapter ONLY for testing code infrastructure, never for demos or documentation. Always label mock screenshots clearly:

```python
# test_viewer.py
def test_viewer_generation():
    """Test viewer HTML generation (uses mock screenshots for testing only)."""
    # This is acceptable because it's testing code, not demonstrating capabilities
    adapter = WAAMockAdapter()
    results = evaluate_agent(agent, adapter)
    viewer_path = generate_viewer(results, validate_screenshots=False)  # Disable for tests
```

**Q: What if task execution fails and we get error screenshots?**

A: Error screenshots are acceptable IF they show real execution failure:
- Screenshot shows error dialog with actual error message
- Stack trace or error log visible in window
- Application crash dialog
- Windows "program not responding" dialog

These show real issues and are valuable for debugging.

**Q: How do we handle screenshot capture timing issues?**

A: Add explicit waits after actions:
```python
# Wait for action to complete and UI to update
await adapter.execute_action(action)
await asyncio.sleep(0.5)  # 500ms for UI rendering
screenshot = await adapter.get_screenshot()
```

**Q: Can we use screen recordings instead of screenshots?**

A: Yes! Screen recordings (MP4, GIF) are even better because they show continuous action. Convert to GIF for documentation:

```bash
# Record screen during evaluation
ffmpeg -f x11grab -i :0.0 -t 30 -r 10 output.mp4

# Convert to GIF
ffmpeg -i output.mp4 -vf "fps=10,scale=800:-1" output.gif
```

## Summary

**Golden Rule:** If a screenshot doesn't show a visible action being performed (cursor movement, text input, button press, window change), it should not be used in demos, documentation, or viewers.

**Validation Rule:** All screenshots must pass automated validation AND visual inspection before use.

**Data Source Rule:** Always use real WAA evaluations or real OpenAdapt recordings. Never use mock data for public-facing content.

**Enforcement Rule:** Screenshot validation is enabled by default and must be explicitly disabled. CI/CD checks enforce this in PRs.

This requirement is encoded in:
- This document (`SCREENSHOT_REQUIREMENTS.md`)
- `CLAUDE.md` (updated with screenshot requirements section)
- Code docstrings (`viewer.py`, `auto_screenshot.py`, `validate_screenshots.py`)
- Validation logic (enabled by default in `validate_screenshots.py`)
- CLI warnings (shows warning when idle screenshots detected)
