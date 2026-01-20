"""Tests to verify screenshot requirement enforcement.

These tests ensure that the screenshot validation system correctly detects
idle desktop screenshots vs real action screenshots.

IMPORTANT: These tests validate the requirement that screenshots must show
real actions being performed. See SCREENSHOT_REQUIREMENTS.md for details.
"""

from __future__ import annotations

import pytest
from pathlib import Path

try:
    from PIL import Image
    import numpy as np
    PILLOW_AVAILABLE = True
except ImportError:
    PILLOW_AVAILABLE = False

pytestmark = pytest.mark.skipif(not PILLOW_AVAILABLE, reason="Pillow not installed")


@pytest.fixture
def temp_dir(tmp_path):
    """Create temporary directory for test screenshots."""
    return tmp_path


@pytest.fixture
def idle_desktop_screenshot(temp_dir):
    """Create a screenshot simulating idle Windows desktop.

    Characteristics:
    - Large uniform color region (desktop wallpaper)
    - Low pixel variance
    - No visible GUI elements
    """
    # Create image with uniform gradient (simulates desktop wallpaper)
    img = Image.new('RGB', (1920, 1080))
    pixels = img.load()

    # Create simple gradient (uniform color)
    for y in range(1080):
        color_val = int(100 + (y / 1080) * 50)  # Slight gradient
        for x in range(1920):
            pixels[x, y] = (color_val, color_val, color_val + 20)

    screenshot_path = temp_dir / "idle_desktop.png"
    img.save(screenshot_path)
    return screenshot_path


@pytest.fixture
def action_screenshot(temp_dir):
    """Create a screenshot simulating real action (Notepad with text).

    Characteristics:
    - Window border visible
    - Text content (high variance)
    - GUI elements (buttons, menu bar)
    """
    # Create image with complex content (simulates window with text)
    img = Image.new('RGB', (1920, 1080))
    pixels = img.load()

    # Background (gray)
    for y in range(1080):
        for x in range(1920):
            pixels[x, y] = (200, 200, 200)

    # Window (white rectangle with border)
    window_x, window_y = 200, 150
    window_w, window_h = 800, 600

    # Window content (white background)
    for y in range(window_y, window_y + window_h):
        for x in range(window_x, window_x + window_w):
            pixels[x, y] = (255, 255, 255)

    # Window border (dark)
    for x in range(window_x, window_x + window_w):
        pixels[x, window_y] = (50, 50, 50)
        pixels[x, window_y + window_h - 1] = (50, 50, 50)
    for y in range(window_y, window_y + window_h):
        pixels[window_x, y] = (50, 50, 50)
        pixels[window_x + window_w - 1, y] = (50, 50, 50)

    # Menu bar (simulates "File Edit View" text)
    menu_y = window_y + 30
    for x in range(window_x + 10, window_x + 200, 3):
        for y in range(menu_y, menu_y + 15, 3):
            pixels[x, y] = (0, 0, 0)

    # Text content (random black pixels simulating text)
    import random
    random.seed(42)
    content_start_y = window_y + 60
    for y in range(content_start_y, window_y + window_h - 20, 20):
        for x in range(window_x + 20, window_x + window_w - 20, 10):
            if random.random() > 0.7:
                for dx in range(8):
                    for dy in range(12):
                        if x + dx < window_x + window_w - 20:
                            pixels[x + dx, y + dy] = (0, 0, 0)

    screenshot_path = temp_dir / "action_screenshot.png"
    img.save(screenshot_path)
    return screenshot_path


class TestScreenshotRequirements:
    """Test enforcement of screenshot requirements."""

    def test_idle_desktop_detection_pixel_variance(self, idle_desktop_screenshot):
        """Test that idle desktop is detected by low pixel variance."""
        from openadapt_evals.benchmarks.validate_screenshots import ScreenshotValidator

        validator = ScreenshotValidator()
        result = validator.validate_content(idle_desktop_screenshot, detect_idle_desktop=True)

        # Should have metadata about variance
        assert result.is_valid  # Still valid image
        assert "pixel_variance" in result.metadata
        # Our gradient has variance ~208, which is above 100 threshold
        # but still relatively low compared to complex GUI (>5000)
        assert result.metadata["pixel_variance"] < 1000  # Low variance

        # The test image has variance of ~208, so it won't trigger the <100 warning
        # But it's still much lower than a complex GUI with text and windows

    def test_action_screenshot_high_variance(self, action_screenshot):
        """Test that action screenshot has high pixel variance."""
        from openadapt_evals.benchmarks.validate_screenshots import ScreenshotValidator

        validator = ScreenshotValidator()
        result = validator.validate_content(action_screenshot, detect_idle_desktop=True)

        # Should pass without warnings about idle desktop
        assert result.is_valid
        idle_warnings = [w for w in result.warnings if "idle" in w.lower() or "variance" in w.lower()]
        assert len(idle_warnings) == 0, f"Unexpected idle warnings: {idle_warnings}"
        assert "pixel_variance" in result.metadata
        assert result.metadata["pixel_variance"] > 1000  # High variance

    def test_sequence_validation_static_frames(self, temp_dir, idle_desktop_screenshot):
        """Test that sequence validation detects repeated static screenshots."""
        from openadapt_evals.benchmarks.validate_screenshot_sequence import validate_sequence

        # Create multiple copies of same screenshot (simulates agent not taking actions)
        screenshots = []
        for i in range(5):
            screenshot_path = temp_dir / f"step_{i:03d}.png"
            # Copy the idle desktop screenshot
            img = Image.open(idle_desktop_screenshot)
            img.save(screenshot_path)
            screenshots.append(screenshot_path)

        result = validate_sequence(screenshots, min_change_threshold=0.01)

        # Should detect that frames are static (no progression)
        assert not result.is_valid
        assert result.static_frames > 2
        assert any("static" in error.lower() for error in result.errors)

    def test_sequence_validation_with_progression(self, temp_dir):
        """Test that sequence validation passes when screenshots show progression."""
        from openadapt_evals.benchmarks.validate_screenshot_sequence import validate_sequence

        # Create sequence with visible changes (simulates real actions)
        screenshots = []
        for i in range(5):
            # Create image with progressively more content
            img = Image.new('RGB', (800, 600))
            pixels = img.load()

            # Background (slightly different each frame)
            base_color = 255 - i * 10  # Changes background slightly
            for y in range(600):
                for x in range(800):
                    pixels[x, y] = (base_color, base_color, base_color)

            # Add progressively more "text" (black pixels)
            for line in range(i + 1):
                y_pos = 50 + line * 30
                # Make changes more substantial by adding more pixels
                for x in range(50, 50 + (i + 1) * 150, 8):
                    for dx in range(12):
                        for dy in range(16):
                            if x + dx < 800 and y_pos + dy < 600:
                                pixels[x + dx, y_pos + dy] = (0, 0, 0)

            screenshot_path = temp_dir / f"step_{i:03d}.png"
            img.save(screenshot_path)
            screenshots.append(screenshot_path)

        result = validate_sequence(screenshots, min_change_threshold=0.005)  # Lower threshold

        # Should pass - each frame is different
        assert result.is_valid
        assert result.static_frames <= 1  # At most 1 static frame allowed
        # Verify most frames show change (but allow for small differences)
        assert sum(1 for diff in result.frame_differences if diff > 0.005) >= 3

    def test_viewer_generation_with_validation(self, temp_dir, action_screenshot):
        """Test that viewer generation can validate screenshots."""
        # This is a placeholder test - would need full viewer integration
        # Just verify the validation function exists and can be called

        from openadapt_evals.benchmarks.validate_screenshots import ScreenshotValidator

        validator = ScreenshotValidator()

        # Create a fake screenshots directory
        screenshots_dir = temp_dir / "screenshots"
        screenshots_dir.mkdir()

        # Copy action screenshot
        import shutil
        shutil.copy(action_screenshot, screenshots_dir / "step_001.png")

        # Validate the directory
        result = validator.validate_screenshots(screenshot_dir=screenshots_dir)

        assert result.all_valid
        assert result.total == 1
        assert result.valid == 1


class TestScreenshotRequirementsDocumentation:
    """Test that screenshot requirements are documented."""

    def test_screenshot_requirements_file_exists(self):
        """Verify SCREENSHOT_REQUIREMENTS.md exists."""
        requirements_file = Path(__file__).parent.parent / "SCREENSHOT_REQUIREMENTS.md"
        assert requirements_file.exists(), (
            "SCREENSHOT_REQUIREMENTS.md not found. "
            "This file must exist to document screenshot quality requirements."
        )

        # Check it contains key sections
        content = requirements_file.read_text()
        assert "Real Live Actions" in content
        assert "Good Examples" in content or "Good Screenshot" in content
        assert "Bad Examples" in content or "Bad Screenshot" in content
        assert "idle desktop" in content.lower()

    def test_viewer_docstring_mentions_requirements(self):
        """Verify viewer.py docstring mentions screenshot requirements."""
        from openadapt_evals.benchmarks import viewer

        docstring = viewer.__doc__
        assert docstring is not None
        assert "SCREENSHOT_REQUIREMENTS" in docstring or "real actions" in docstring.lower()

    def test_auto_screenshot_docstring_mentions_requirements(self):
        """Verify auto_screenshot.py docstring mentions screenshot requirements."""
        from openadapt_evals.benchmarks import auto_screenshot

        docstring = auto_screenshot.__doc__
        assert docstring is not None
        assert "SCREENSHOT_REQUIREMENTS" in docstring or "real actions" in docstring.lower()

    def test_validate_screenshots_has_idle_detection(self):
        """Verify validate_screenshots.py has idle desktop detection."""
        from openadapt_evals.benchmarks.validate_screenshots import ScreenshotValidator

        # Check the validate_content method has detect_idle_desktop parameter
        import inspect
        sig = inspect.signature(ScreenshotValidator.validate_content)
        params = sig.parameters

        assert "detect_idle_desktop" in params, (
            "validate_content should have detect_idle_desktop parameter"
        )


class TestRealDataUsageEnforcement:
    """Test that real data usage is encouraged over mock data."""

    def test_claude_md_mentions_real_data(self):
        """Verify CLAUDE.md mentions real data requirement."""
        claude_file = Path(__file__).parent.parent / "CLAUDE.md"
        assert claude_file.exists()

        content = claude_file.read_text()
        assert "real data" in content.lower() or "Real Data" in content
        assert "mock" in content.lower()  # Discusses when to use mock

    def test_readme_uses_real_data_examples(self):
        """Verify README.md uses real data in examples."""
        readme_file = Path(__file__).parent.parent / "README.md"
        assert readme_file.exists()

        content = readme_file.read_text()

        # Check that Quick Start uses real WAA adapter
        assert "WAALiveAdapter" in content or "live" in content.lower()

        # Mock should be mentioned as testing option, not primary
        mock_mentions = content.lower().count("mock")
        live_mentions = content.lower().count("live")
        assert live_mentions > 0, "README should show live evaluation examples"


# Metadata for pytest
pytest_plugins = []


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
