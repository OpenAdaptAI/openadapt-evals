"""Tests for screenshot validation infrastructure."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

try:
    from PIL import Image
    PILLOW_AVAILABLE = True
except ImportError:
    PILLOW_AVAILABLE = False

if PILLOW_AVAILABLE:
    from openadapt_evals.benchmarks.validate_screenshots import (
        ScreenshotValidator,
        ValidationResult,
        BatchValidationResult,
    )


@pytest.mark.skipif(not PILLOW_AVAILABLE, reason="Pillow not installed")
class TestValidationResult:
    """Tests for ValidationResult dataclass."""

    def test_valid_result(self):
        """Test creating a valid result."""
        result = ValidationResult(is_valid=True)
        assert result.is_valid
        assert len(result.errors) == 0
        assert len(result.warnings) == 0

    def test_invalid_result(self):
        """Test creating an invalid result."""
        result = ValidationResult(
            is_valid=False,
            errors=["Error 1", "Error 2"],
            warnings=["Warning 1"],
        )
        assert not result.is_valid
        assert len(result.errors) == 2
        assert len(result.warnings) == 1

    def test_to_dict(self):
        """Test converting to dictionary."""
        result = ValidationResult(
            is_valid=True,
            warnings=["Minor issue"],
            metadata={"width": 1920, "height": 1080},
        )
        data = result.to_dict()
        assert data["is_valid"] is True
        assert data["warnings"] == ["Minor issue"]
        assert data["metadata"]["width"] == 1920

    def test_string_representation(self):
        """Test string representation."""
        result = ValidationResult(
            is_valid=False,
            errors=["Critical error"],
            warnings=["Minor warning"],
        )
        str_repr = str(result)
        assert "INVALID" in str_repr
        assert "Critical error" in str_repr
        assert "Minor warning" in str_repr


@pytest.mark.skipif(not PILLOW_AVAILABLE, reason="Pillow not installed")
class TestBatchValidationResult:
    """Tests for BatchValidationResult dataclass."""

    def test_all_valid(self):
        """Test batch with all valid screenshots."""
        batch = BatchValidationResult(total=3, valid=3, invalid=0)
        assert batch.all_valid

    def test_some_invalid(self):
        """Test batch with some invalid screenshots."""
        batch = BatchValidationResult(total=3, valid=2, invalid=1)
        assert not batch.all_valid

    def test_to_dict(self):
        """Test converting to dictionary."""
        result1 = ValidationResult(is_valid=True)
        result2 = ValidationResult(is_valid=False, errors=["Error"])

        batch = BatchValidationResult(
            total=2,
            valid=1,
            invalid=1,
            results={
                "screenshot1.png": result1,
                "screenshot2.png": result2,
            }
        )

        data = batch.to_dict()
        assert data["total"] == 2
        assert data["valid"] == 1
        assert data["all_valid"] is False
        assert "screenshot1.png" in data["results"]


@pytest.mark.skipif(not PILLOW_AVAILABLE, reason="Pillow not installed")
class TestScreenshotValidator:
    """Tests for ScreenshotValidator class."""

    @pytest.fixture
    def validator(self):
        """Create a validator instance."""
        return ScreenshotValidator(enable_ocr=False)

    @pytest.fixture
    def temp_screenshot(self, tmp_path):
        """Create a temporary screenshot for testing."""
        screenshot_path = tmp_path / "test_screenshot.png"

        # Create a test image with realistic size (800x600 with gradient for realistic file size)
        img = Image.new('RGB', (800, 600), color='red')
        # Add some variation to make file size realistic
        pixels = img.load()
        for i in range(800):
            for j in range(600):
                pixels[i, j] = (i % 256, j % 256, (i + j) % 256)
        img.save(screenshot_path)

        return screenshot_path

    @pytest.fixture
    def large_screenshot(self, tmp_path):
        """Create a larger temporary screenshot."""
        screenshot_path = tmp_path / "large_screenshot.png"

        # Create a larger image (1920x1080)
        img = Image.new('RGB', (1920, 1080), color='blue')
        img.save(screenshot_path)

        return screenshot_path

    @pytest.fixture
    def blank_screenshot(self, tmp_path):
        """Create a blank (all white) screenshot."""
        screenshot_path = tmp_path / "blank_screenshot.png"

        # Create all white image
        img = Image.new('RGB', (100, 100), color='white')
        img.save(screenshot_path)

        return screenshot_path

    def test_validator_initialization(self):
        """Test validator initialization."""
        validator = ScreenshotValidator(enable_ocr=False)
        assert validator is not None
        assert not validator.enable_ocr

    def test_validate_file_integrity_success(self, validator, temp_screenshot):
        """Test successful file integrity validation."""
        result = validator.validate_file_integrity(temp_screenshot)
        assert result.is_valid
        assert len(result.errors) == 0
        assert result.metadata["format"] == "PNG"

    def test_validate_file_integrity_missing_file(self, validator):
        """Test validation of missing file."""
        result = validator.validate_file_integrity("nonexistent.png")
        assert not result.is_valid
        assert any("does not exist" in error for error in result.errors)

    def test_validate_file_integrity_empty_file(self, validator, tmp_path):
        """Test validation of empty file."""
        empty_file = tmp_path / "empty.png"
        empty_file.write_text("")

        result = validator.validate_file_integrity(empty_file)
        assert not result.is_valid
        assert any("too small" in error for error in result.errors)

    def test_validate_dimensions_success(self, validator, temp_screenshot):
        """Test successful dimension validation."""
        result = validator.validate_dimensions(temp_screenshot)
        assert result.is_valid
        assert result.metadata["width"] == 800
        assert result.metadata["height"] == 600

    def test_validate_dimensions_expected_match(self, validator, temp_screenshot):
        """Test dimension validation with expected values."""
        result = validator.validate_dimensions(
            temp_screenshot,
            expected_width=800,
            expected_height=600,
        )
        assert result.is_valid
        assert len(result.errors) == 0

    def test_validate_dimensions_expected_mismatch(self, validator, temp_screenshot):
        """Test dimension validation with mismatched expected values."""
        result = validator.validate_dimensions(
            temp_screenshot,
            expected_width=200,
            expected_height=200,
            allow_tolerance=5,
        )
        assert not result.is_valid
        assert any("Width mismatch" in error for error in result.errors)
        assert any("Height mismatch" in error for error in result.errors)

    def test_validate_dimensions_with_tolerance(self, validator, temp_screenshot):
        """Test dimension validation with tolerance."""
        result = validator.validate_dimensions(
            temp_screenshot,
            expected_width=805,
            expected_height=605,
            allow_tolerance=10,
        )
        assert result.is_valid
        # Should have warnings but no errors
        assert len(result.errors) == 0
        assert len(result.warnings) == 2

    def test_validate_content_success(self, validator, temp_screenshot):
        """Test successful content validation."""
        result = validator.validate_content(temp_screenshot)
        assert result.is_valid
        assert len(result.errors) == 0

    def test_validate_content_blank_image(self, validator, blank_screenshot):
        """Test content validation on blank image."""
        result = validator.validate_content(blank_screenshot)
        assert not result.is_valid
        assert any("completely white" in error for error in result.errors)

    def test_validate_single_complete(self, validator, temp_screenshot):
        """Test complete validation of a single screenshot."""
        result = validator.validate_single(
            temp_screenshot,
            expected_width=800,
            expected_height=600,
        )
        assert result.is_valid
        assert "width" in result.metadata
        assert "height" in result.metadata
        assert "format" in result.metadata

    def test_validate_screenshots_batch(self, validator, temp_screenshot, large_screenshot):
        """Test batch validation of multiple screenshots."""
        batch_result = validator.validate_screenshots(
            screenshot_paths=[temp_screenshot, large_screenshot]
        )

        assert batch_result.total == 2
        assert batch_result.valid == 2
        assert batch_result.invalid == 0
        assert batch_result.all_valid

    def test_validate_screenshots_directory(self, validator, tmp_path):
        """Test validation of screenshots in a directory."""
        # Create multiple screenshots with realistic size
        for i in range(3):
            img = Image.new('RGB', (800, 600), color='green')
            # Add variation for realistic file size
            pixels = img.load()
            for x in range(800):
                for y in range(600):
                    pixels[x, y] = ((i * 50 + x) % 256, y % 256, (x + y) % 256)
            img.save(tmp_path / f"screenshot_{i}.png")

        batch_result = validator.validate_screenshots(screenshot_dir=tmp_path)

        assert batch_result.total == 3
        assert batch_result.all_valid

    def test_validate_screenshots_with_manifest(self, validator, tmp_path):
        """Test validation with manifest."""
        # Create screenshot
        screenshot_path = tmp_path / "desktop_overview.png"
        img = Image.new('RGB', (1920, 1080), color='blue')
        img.save(screenshot_path)

        # Create manifest
        manifest = {
            "screenshots": [
                {
                    "filename": "desktop_overview.png",
                    "description": "Desktop overview",
                    "expected_dimensions": [1920, 1080],
                    "viewport": "desktop",
                }
            ]
        }
        manifest_path = tmp_path / "manifest.json"
        with open(manifest_path, 'w') as f:
            json.dump(manifest, f)

        # Validate
        batch_result = validator.validate_screenshots(
            screenshot_dir=tmp_path,
            manifest_path=manifest_path,
        )

        assert batch_result.total >= 1
        # Check that manifest metadata was included
        for result in batch_result.results.values():
            if "desktop_overview.png" in str(result.metadata.get("manifest_description", "")):
                assert result.metadata["manifest_viewport"] == "desktop"
                break

    def test_validate_screenshots_with_invalid(self, validator, tmp_path, blank_screenshot):
        """Test batch validation with some invalid screenshots."""
        # Create valid screenshot with realistic size
        valid_path = tmp_path / "valid.png"
        img = Image.new('RGB', (800, 600), color='red')
        # Add variation for realistic file size
        pixels = img.load()
        for x in range(800):
            for y in range(600):
                pixels[x, y] = (x % 256, y % 256, (x + y) % 256)
        img.save(valid_path)

        # Validate with both valid and invalid
        batch_result = validator.validate_screenshots(
            screenshot_paths=[valid_path, blank_screenshot]
        )

        assert batch_result.total == 2
        assert batch_result.valid == 1
        assert batch_result.invalid == 1
        assert not batch_result.all_valid


@pytest.mark.skipif(not PILLOW_AVAILABLE, reason="Pillow not installed")
class TestIntegrationWithExistingScreenshots:
    """Integration tests with existing screenshots in the project."""

    def test_validate_project_screenshots(self):
        """Test validation of actual project screenshots."""
        screenshots_dir = Path(__file__).parent.parent / "screenshots"

        if not screenshots_dir.exists():
            pytest.skip("Screenshots directory not found")

        validator = ScreenshotValidator()
        batch_result = validator.validate_screenshots(screenshot_dir=screenshots_dir)

        # At least some screenshots should exist
        assert batch_result.total > 0

        # Print results for debugging
        if not batch_result.all_valid:
            for path, result in batch_result.results.items():
                if not result.is_valid:
                    print(f"\nInvalid screenshot: {path}")
                    for error in result.errors:
                        print(f"  Error: {error}")
                    for warning in result.warnings:
                        print(f"  Warning: {warning}")

    def test_validate_with_manifest(self):
        """Test validation with the project manifest."""
        screenshots_dir = Path(__file__).parent.parent / "screenshots"
        manifest_path = screenshots_dir / "manifest.json"

        if not manifest_path.exists():
            pytest.skip("Manifest not found")

        validator = ScreenshotValidator()
        batch_result = validator.validate_screenshots(
            screenshot_dir=screenshots_dir,
            manifest_path=manifest_path,
        )

        assert batch_result.total > 0

        # Check that manifest data was used
        for result in batch_result.results.values():
            if "manifest_description" in result.metadata:
                # At least some screenshots should have manifest metadata
                assert "manifest_viewport" in result.metadata
                break


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
