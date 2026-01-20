# Screenshot Requirements - Quick Reference

## The Critical Rule

**Screenshots MUST show REAL ACTIONS being performed, not idle Windows desktop.**

This requirement is now permanently encoded across:
- ✅ `SCREENSHOT_REQUIREMENTS.md` - Complete specification (200+ lines)
- ✅ `CLAUDE.md` - Claude Code instructions with screenshot section
- ✅ `README.md` - Prominent mention with link
- ✅ Module docstrings - `viewer.py`, `auto_screenshot.py`, `validate_screenshots.py`
- ✅ Validation code - Idle desktop detection in `validate_screenshots.py`
- ✅ Sequence validation - `validate_screenshot_sequence.py` detects static frames
- ✅ Test suite - `tests/test_screenshot_requirements.py` (11 tests)

## Quick Check: Is This Screenshot Acceptable?

### ✅ YES - Shows Real Actions
- Notepad window with text being typed ("hel" partially visible)
- Browser with search results, cursor hovering over link
- File dialog with file name being entered
- Menu dropdown open showing options
- Form fields being filled in sequence

### ❌ NO - Idle Desktop
- Windows 11 desktop with wallpaper, no windows open
- Empty Notepad with blank document
- Browser on blank new tab page
- Application loading screen with no progress
- Static desktop background repeated across multiple frames

## What Changed

### Before (Problem)
- `benchmark_results/waa-live_eval_20260116_200004/viewer.html` showed idle Windows desktop
- No validation of screenshot quality
- Mock data used in demos and documentation
- Easy to forget requirement

### After (Solution)
1. **Documentation** - `SCREENSHOT_REQUIREMENTS.md` (comprehensive specification)
2. **Code Comments** - All screenshot modules reference requirements
3. **Validation** - Automated detection of idle desktop screenshots
4. **Sequence Check** - Validates progression between frames
5. **Tests** - 11 tests enforce requirements
6. **CLI Integration** - Warnings when idle screenshots detected

## How to Use

### Generate Valid Screenshots

**Option A: Real WAA Evaluation** (PREFERRED)
```bash
uv run python -m openadapt_evals.benchmarks.cli live \
    --agent api-claude \
    --server http://vm:5000 \
    --task-ids notepad_1,browser_5 \
    --save-screenshots
```

**Option B: Nightshift Recording** (macOS)
```python
from openadapt.db import crud

recording = crud.get_recording_by_name('nightshift')
screenshots = [event.screenshot for event in recording.action_events]
```

### Validate Screenshots

**Single screenshot:**
```python
from openadapt_evals.benchmarks.validate_screenshots import ScreenshotValidator

validator = ScreenshotValidator()
result = validator.validate_single("screenshot.png")

if not result.is_valid:
    print(f"INVALID: {result.errors}")
if result.warnings:
    print(f"WARNINGS: {result.warnings}")
```

**Screenshot sequence:**
```python
from openadapt_evals.benchmarks.validate_screenshot_sequence import validate_sequence

result = validate_sequence(
    screenshots=["step_001.png", "step_002.png", "step_003.png"],
    min_change_threshold=0.01  # 1% pixel difference
)

if result.static_frames > 0:
    print(f"Warning: {result.static_frames} static frames (no progression)")
```

**Via CLI:**
```bash
# Validate single screenshot
python -m openadapt_evals.benchmarks.validate_screenshots \
    --screenshot screenshot.png

# Validate directory with manifest
python -m openadapt_evals.benchmarks.validate_screenshots \
    --screenshot-dir screenshots/ \
    --manifest screenshots/manifest.json

# Validate sequence
python -m openadapt_evals.benchmarks.validate_screenshot_sequence \
    --screenshots step_*.png \
    --min-change-threshold 0.01
```

## Detection Methods

### 1. Pixel Variance (Automated)
- Low variance (<100) = likely uniform desktop wallpaper
- High variance (>5000) = complex GUI with text/windows
- Implemented in `validate_screenshots.py`

### 2. OCR Text Detection (Optional)
- Detects taskbar elements (Search, Start, Widgets)
- Detects application elements (File, Edit, OK, Cancel)
- Idle if taskbar present but no app elements
- Requires `pytesseract` installation

### 3. Sequential Change (Automated)
- Compares consecutive screenshots
- <1% pixel change = static/duplicate frame
- Too many static frames = idle or stuck agent
- Implemented in `validate_screenshot_sequence.py`

## Files Changed

### New Files
1. `/SCREENSHOT_REQUIREMENTS.md` - Complete specification
2. `/SCREENSHOT_REQUIREMENTS_SUMMARY.md` - This quick reference
3. `/openadapt_evals/benchmarks/validate_screenshot_sequence.py` - Sequence validation
4. `/tests/test_screenshot_requirements.py` - 11 validation tests

### Updated Files
1. `/CLAUDE.md` - Added screenshot quality requirements section
2. `/README.md` - Added critical requirement mention
3. `/openadapt_evals/benchmarks/viewer.py` - Updated docstring
4. `/openadapt_evals/benchmarks/auto_screenshot.py` - Updated docstring
5. `/openadapt_evals/benchmarks/validate_screenshots.py` - Added idle desktop detection

## Test Results

All 11 tests pass:
```
tests/test_screenshot_requirements.py::TestScreenshotRequirements::test_idle_desktop_detection_pixel_variance PASSED
tests/test_screenshot_requirements.py::TestScreenshotRequirements::test_action_screenshot_high_variance PASSED
tests/test_screenshot_requirements.py::TestScreenshotRequirements::test_sequence_validation_static_frames PASSED
tests/test_screenshot_requirements.py::TestScreenshotRequirements::test_sequence_validation_with_progression PASSED
tests/test_screenshot_requirements.py::TestScreenshotRequirements::test_viewer_generation_with_validation PASSED
tests/test_screenshot_requirements.py::TestScreenshotRequirementsDocumentation::test_screenshot_requirements_file_exists PASSED
tests/test_screenshot_requirements.py::TestScreenshotRequirementsDocumentation::test_viewer_docstring_mentions_requirements PASSED
tests/test_screenshot_requirements.py::TestScreenshotRequirementsDocumentation::test_auto_screenshot_docstring_mentions_requirements PASSED
tests/test_screenshot_requirements.py::TestScreenshotRequirementsDocumentation::test_validate_screenshots_has_idle_detection PASSED
tests/test_screenshot_requirements.py::TestRealDataUsageEnforcement::test_claude_md_mentions_real_data PASSED
tests/test_screenshot_requirements.py::TestRealDataUsageEnforcement::test_readme_uses_real_data_examples PASSED
```

## Next Steps

When generating new viewer or documentation:

1. **Before Capture**:
   - Verify WAA server is running: `curl http://vm:5000/probe`
   - Run real evaluation, not mock: `--agent api-claude --server http://vm:5000`
   - Ensure task has evaluator config

2. **After Capture**:
   - Run validation: `python -m openadapt_evals.benchmarks.validate_screenshots --screenshot-dir screenshots/`
   - Visual inspection: Open each screenshot, verify actions visible
   - Check sequence: `python -m openadapt_evals.benchmarks.validate_screenshot_sequence --screenshots step_*.png`

3. **For Documentation**:
   - Use screenshots from real evaluations
   - Avoid mock adapter screenshots in public-facing content
   - Label any test screenshots clearly as "testing infrastructure only"

## References

- **Complete Specification**: `SCREENSHOT_REQUIREMENTS.md`
- **Implementation**: `validate_screenshots.py`, `validate_screenshot_sequence.py`
- **Tests**: `tests/test_screenshot_requirements.py`
- **Claude Instructions**: `CLAUDE.md` (Screenshot Quality Requirements section)

---

**Remember**: The goal is to show the agent actually doing something, not show an idle state. This is critical for convincing demos and proper evaluation visualization.
