"""Screenshot validation infrastructure for systematic review of generated screenshots.

This module provides functionality to validate screenshots to ensure they show expected
content, have correct dimensions, and don't contain issues like blank images or errors.

Usage:
    # Validate a single screenshot
    from openadapt_evals.benchmarks.validate_screenshots import ScreenshotValidator

    validator = ScreenshotValidator()
    result = validator.validate_file_integrity("screenshot.png")
    if result.is_valid:
        print("Screenshot is valid!")
    else:
        print(f"Errors: {result.errors}")

    # Validate with manifest
    results = validator.validate_screenshots(
        screenshot_dir="screenshots",
        manifest_path="screenshots/manifest.json"
    )

CLI Usage:
    # Validate single file
    python -m openadapt_evals.benchmarks.validate_screenshots \
        --screenshot screenshots/desktop_overview.png

    # Validate directory with manifest
    python -m openadapt_evals.benchmarks.validate_screenshots \
        --screenshot-dir screenshots/ \
        --manifest screenshots/manifest.json

    # Generate JSON report
    python -m openadapt_evals.benchmarks.validate_screenshots \
        --screenshot-dir screenshots/ \
        --output-report validation_report.json

    # Enable OCR text detection (requires pytesseract)
    python -m openadapt_evals.benchmarks.validate_screenshots \
        --screenshot screenshots/desktop_overview.png \
        --ocr \
        --expected-keywords "Task,Status,Runtime"
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any

try:
    from PIL import Image
    PILLOW_AVAILABLE = True
except ImportError:
    PILLOW_AVAILABLE = False

logger = logging.getLogger(__name__)

# Minimum file size for valid screenshots (1KB - allows for small test images)
MIN_FILE_SIZE = 1 * 1024

# Maximum file size for reasonable screenshots (50MB)
MAX_FILE_SIZE = 50 * 1024 * 1024

# Minimum dimensions to be considered a valid screenshot
MIN_WIDTH = 100
MIN_HEIGHT = 100


@dataclass
class ValidationResult:
    """Result of screenshot validation.

    Attributes:
        is_valid: Whether the screenshot passed all validation checks.
        errors: List of error messages (critical issues).
        warnings: List of warning messages (non-critical issues).
        metadata: Additional metadata about the screenshot.
    """
    is_valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    def __str__(self) -> str:
        """Human-readable string representation."""
        status = "VALID" if self.is_valid else "INVALID"
        parts = [f"ValidationResult: {status}"]

        if self.errors:
            parts.append(f"  Errors ({len(self.errors)}):")
            for error in self.errors:
                parts.append(f"    - {error}")

        if self.warnings:
            parts.append(f"  Warnings ({len(self.warnings)}):")
            for warning in self.warnings:
                parts.append(f"    - {warning}")

        if self.metadata:
            parts.append(f"  Metadata: {self.metadata}")

        return "\n".join(parts)


@dataclass
class BatchValidationResult:
    """Result of batch screenshot validation.

    Attributes:
        total: Total number of screenshots validated.
        valid: Number of valid screenshots.
        invalid: Number of invalid screenshots.
        results: Dictionary mapping screenshot paths to ValidationResults.
    """
    total: int
    valid: int
    invalid: int
    results: dict[str, ValidationResult] = field(default_factory=dict)

    @property
    def all_valid(self) -> bool:
        """Check if all screenshots are valid."""
        return self.invalid == 0

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "total": self.total,
            "valid": self.valid,
            "invalid": self.invalid,
            "all_valid": self.all_valid,
            "results": {
                str(path): result.to_dict()
                for path, result in self.results.items()
            }
        }

    def __str__(self) -> str:
        """Human-readable string representation."""
        parts = [
            f"Batch Validation Results:",
            f"  Total: {self.total}",
            f"  Valid: {self.valid}",
            f"  Invalid: {self.invalid}",
            f"  All Valid: {self.all_valid}",
        ]

        if self.results:
            parts.append("\nDetails:")
            for path, result in self.results.items():
                status = "✓" if result.is_valid else "✗"
                parts.append(f"  {status} {path}")
                if result.errors:
                    for error in result.errors:
                        parts.append(f"      ERROR: {error}")
                if result.warnings:
                    for warning in result.warnings:
                        parts.append(f"      WARNING: {warning}")

        return "\n".join(parts)


class ScreenshotValidator:
    """Validator for screenshot files.

    Provides methods to validate screenshot file integrity, dimensions, and content.
    """

    def __init__(self, enable_ocr: bool = False):
        """Initialize the validator.

        Args:
            enable_ocr: Whether to enable OCR-based text detection (requires pytesseract).
        """
        if not PILLOW_AVAILABLE:
            raise ImportError(
                "Pillow is required for screenshot validation. "
                "Install with: pip install Pillow"
            )

        self.enable_ocr = enable_ocr
        self.pytesseract = None

        if enable_ocr:
            try:
                import pytesseract
                self.pytesseract = pytesseract
            except ImportError:
                logger.warning(
                    "pytesseract not available. OCR validation will be skipped. "
                    "Install with: pip install pytesseract"
                )
                self.enable_ocr = False

    def validate_file_integrity(self, screenshot_path: str | Path) -> ValidationResult:
        """Validate basic file integrity.

        Checks:
        - File exists
        - File size is reasonable (not empty, not too large)
        - File is a valid image format
        - Image can be opened without errors

        Args:
            screenshot_path: Path to the screenshot file.

        Returns:
            ValidationResult with errors if any issues are found.
        """
        screenshot_path = Path(screenshot_path)
        result = ValidationResult(is_valid=True)

        # Check file exists
        if not screenshot_path.exists():
            result.is_valid = False
            result.errors.append(f"File does not exist: {screenshot_path}")
            return result

        # Check file size
        file_size = screenshot_path.stat().st_size
        result.metadata["file_size"] = file_size

        if file_size < MIN_FILE_SIZE:
            result.is_valid = False
            result.errors.append(
                f"File size too small ({file_size} bytes). "
                f"Expected at least {MIN_FILE_SIZE} bytes."
            )

        if file_size > MAX_FILE_SIZE:
            result.warnings.append(
                f"File size very large ({file_size} bytes). "
                f"Consider optimizing the image."
            )

        # Check file format
        try:
            with Image.open(screenshot_path) as img:
                result.metadata["format"] = img.format
                result.metadata["mode"] = img.mode
                result.metadata["size"] = img.size

                # Verify image is not corrupted by attempting to load it
                img.verify()
        except Exception as e:
            result.is_valid = False
            result.errors.append(f"Failed to open image: {e}")
            return result

        return result

    def validate_dimensions(
        self,
        screenshot_path: str | Path,
        expected_width: int | None = None,
        expected_height: int | None = None,
        allow_tolerance: int = 10,
    ) -> ValidationResult:
        """Validate image dimensions.

        Args:
            screenshot_path: Path to the screenshot file.
            expected_width: Expected width in pixels (None to skip).
            expected_height: Expected height in pixels (None to skip).
            allow_tolerance: Allowed pixel difference for expected dimensions.

        Returns:
            ValidationResult with dimension validation results.
        """
        screenshot_path = Path(screenshot_path)
        result = ValidationResult(is_valid=True)

        try:
            with Image.open(screenshot_path) as img:
                width, height = img.size
                result.metadata["width"] = width
                result.metadata["height"] = height

                # Check minimum dimensions
                if width < MIN_WIDTH:
                    result.is_valid = False
                    result.errors.append(
                        f"Width too small ({width}px). "
                        f"Minimum: {MIN_WIDTH}px."
                    )

                if height < MIN_HEIGHT:
                    result.is_valid = False
                    result.errors.append(
                        f"Height too small ({height}px). "
                        f"Minimum: {MIN_HEIGHT}px."
                    )

                # Check expected dimensions
                if expected_width is not None:
                    diff = abs(width - expected_width)
                    if diff > allow_tolerance:
                        result.is_valid = False
                        result.errors.append(
                            f"Width mismatch: expected {expected_width}px, "
                            f"got {width}px (diff: {diff}px)"
                        )
                    elif diff > 0:
                        result.warnings.append(
                            f"Width slightly different: expected {expected_width}px, "
                            f"got {width}px (diff: {diff}px)"
                        )

                if expected_height is not None:
                    diff = abs(height - expected_height)
                    if diff > allow_tolerance:
                        result.is_valid = False
                        result.errors.append(
                            f"Height mismatch: expected {expected_height}px, "
                            f"got {height}px (diff: {diff}px)"
                        )
                    elif diff > 0:
                        result.warnings.append(
                            f"Height slightly different: expected {expected_height}px, "
                            f"got {height}px (diff: {diff}px)"
                        )

        except Exception as e:
            result.is_valid = False
            result.errors.append(f"Failed to read image dimensions: {e}")

        return result

    def validate_content(
        self,
        screenshot_path: str | Path,
        expected_keywords: list[str] | None = None,
        detect_idle_desktop: bool = True,
    ) -> ValidationResult:
        """Validate screenshot content.

        Performs basic content checks:
        - Not all white (blank)
        - Not all black (failed to render)
        - Reasonable color distribution
        - Optional OCR text detection
        - Detects idle desktop screenshots (no visible actions)

        IMPORTANT: Screenshots must show real actions being performed.
        See SCREENSHOT_REQUIREMENTS.md for requirements.

        Args:
            screenshot_path: Path to the screenshot file.
            expected_keywords: Optional list of keywords to detect via OCR.
            detect_idle_desktop: If True, detects idle desktop with no actions.

        Returns:
            ValidationResult with content validation results.
        """
        screenshot_path = Path(screenshot_path)
        result = ValidationResult(is_valid=True)

        try:
            with Image.open(screenshot_path) as img:
                # Convert to RGB for analysis
                if img.mode != 'RGB':
                    img = img.convert('RGB')

                # Get image statistics
                extrema = img.getextrema()
                result.metadata["extrema"] = extrema

                # Check if image is all white
                if all(ext == (255, 255) for ext in extrema):
                    result.is_valid = False
                    result.errors.append("Image is completely white (blank)")

                # Check if image is all black
                if all(ext == (0, 0) for ext in extrema):
                    result.is_valid = False
                    result.errors.append("Image is completely black (failed to render)")

                # Check color distribution
                try:
                    colors = img.getcolors(maxcolors=256 * 256 * 256)
                    if colors and len(colors) < 10:
                        result.warnings.append(
                            f"Very low color diversity ({len(colors)} unique colors). "
                            "May indicate rendering issue."
                        )
                    result.metadata["unique_colors"] = len(colors) if colors else "too many"
                except Exception:
                    # Too many colors to count (normal for complex screenshots)
                    result.metadata["unique_colors"] = "complex"

                # Detect idle desktop (no visible actions)
                if detect_idle_desktop:
                    # Heuristics for detecting idle desktop:
                    # 1. Very uniform color distribution (desktop wallpaper)
                    # 2. Large regions of similar color (no GUI elements)
                    # 3. Low edge density (no windows/buttons/text)

                    # Simple check: Calculate image variance
                    # Low variance = uniform image = likely idle desktop
                    try:
                        # Convert to grayscale for variance calculation
                        gray = img.convert('L')
                        pixels = list(gray.getdata())
                        mean = sum(pixels) / len(pixels)
                        variance = sum((p - mean) ** 2 for p in pixels) / len(pixels)

                        result.metadata["pixel_variance"] = variance

                        # Very low variance suggests uniform background
                        if variance < 100:
                            result.warnings.append(
                                "Very low pixel variance - may indicate idle desktop with no windows. "
                                "Screenshots should show GUI elements being interacted with. "
                                "See SCREENSHOT_REQUIREMENTS.md for validation requirements."
                            )
                        # High variance is good (complex GUI with windows, text, buttons)
                        elif variance > 5000:
                            result.metadata["complexity"] = "high (good - shows GUI elements)"

                    except Exception as e:
                        logger.debug(f"Failed to calculate pixel variance: {e}")

                # OCR text detection
                if self.enable_ocr and self.pytesseract and expected_keywords:
                    try:
                        text = self.pytesseract.image_to_string(img)
                        result.metadata["detected_text_length"] = len(text)

                        missing_keywords = []
                        for keyword in expected_keywords:
                            if keyword.lower() not in text.lower():
                                missing_keywords.append(keyword)

                        if missing_keywords:
                            result.warnings.append(
                                f"Missing expected keywords: {', '.join(missing_keywords)}"
                            )

                        result.metadata["ocr_text_sample"] = text[:200] if text else ""

                    except Exception as e:
                        result.warnings.append(f"OCR text detection failed: {e}")

                # OCR-based idle desktop detection
                if self.enable_ocr and self.pytesseract:
                    try:
                        text = self.pytesseract.image_to_string(img).lower()

                        # Check for Windows idle desktop indicators
                        idle_indicators = [
                            "search",  # Windows search box
                            "widgets",  # Windows 11 widgets
                            "start",   # Start button
                        ]

                        # Check for application window indicators (want these!)
                        app_indicators = [
                            "file", "edit", "view", "help",  # Menu bars
                            "ok", "cancel", "apply",  # Dialog buttons
                            "save", "open", "close",  # Common actions
                        ]

                        idle_count = sum(1 for indicator in idle_indicators if indicator in text)
                        app_count = sum(1 for indicator in app_indicators if indicator in text)

                        if idle_count > 0 and app_count == 0:
                            result.warnings.append(
                                "Screenshot may show idle desktop (found taskbar elements but no application windows). "
                                "Screenshots should show real actions: GUI elements, text being typed, buttons being clicked. "
                                "See SCREENSHOT_REQUIREMENTS.md for requirements."
                            )
                            result.metadata["idle_desktop_indicators"] = idle_count
                        elif app_count > 0:
                            result.metadata["application_indicators"] = app_count
                            result.metadata["shows_gui_elements"] = True

                    except Exception as e:
                        logger.debug(f"Failed OCR idle detection: {e}")

        except Exception as e:
            result.is_valid = False
            result.errors.append(f"Failed to analyze image content: {e}")

        return result

    def validate_single(
        self,
        screenshot_path: str | Path,
        expected_width: int | None = None,
        expected_height: int | None = None,
        expected_keywords: list[str] | None = None,
    ) -> ValidationResult:
        """Perform complete validation on a single screenshot.

        Combines file integrity, dimension, and content validation.

        Args:
            screenshot_path: Path to the screenshot file.
            expected_width: Expected width in pixels (None to skip).
            expected_height: Expected height in pixels (None to skip).
            expected_keywords: Optional list of keywords to detect via OCR.

        Returns:
            Combined ValidationResult from all checks.
        """
        # File integrity
        result = self.validate_file_integrity(screenshot_path)
        if not result.is_valid:
            return result  # Early exit if file is not readable

        # Dimensions
        dim_result = self.validate_dimensions(
            screenshot_path,
            expected_width,
            expected_height
        )
        result.errors.extend(dim_result.errors)
        result.warnings.extend(dim_result.warnings)
        result.metadata.update(dim_result.metadata)
        result.is_valid = result.is_valid and dim_result.is_valid

        # Content
        content_result = self.validate_content(screenshot_path, expected_keywords)
        result.errors.extend(content_result.errors)
        result.warnings.extend(content_result.warnings)
        result.metadata.update(content_result.metadata)
        result.is_valid = result.is_valid and content_result.is_valid

        return result

    def validate_screenshots(
        self,
        screenshot_dir: str | Path | None = None,
        screenshot_paths: list[str | Path] | None = None,
        manifest_path: str | Path | None = None,
    ) -> BatchValidationResult:
        """Validate multiple screenshots, optionally using a manifest.

        Args:
            screenshot_dir: Directory containing screenshots to validate.
            screenshot_paths: Explicit list of screenshot paths to validate.
            manifest_path: Path to manifest JSON with expected values.

        Returns:
            BatchValidationResult with validation results for all screenshots.
        """
        # Load manifest if provided
        manifest = {}
        if manifest_path:
            manifest_path = Path(manifest_path)
            if manifest_path.exists():
                try:
                    with open(manifest_path) as f:
                        manifest_data = json.load(f)
                        # Convert to dict keyed by filename
                        for item in manifest_data.get("screenshots", []):
                            manifest[item["filename"]] = item
                except Exception as e:
                    logger.warning(f"Failed to load manifest: {e}")

        # Collect screenshot paths
        paths: list[Path] = []

        if screenshot_paths:
            paths = [Path(p) for p in screenshot_paths]
        elif screenshot_dir:
            screenshot_dir = Path(screenshot_dir)
            if screenshot_dir.is_dir():
                # Find all image files
                for ext in ['*.png', '*.jpg', '*.jpeg', '*.gif', '*.bmp']:
                    paths.extend(screenshot_dir.glob(ext))

        # Validate each screenshot
        results = {}
        valid_count = 0

        for path in paths:
            # Get expected values from manifest
            manifest_entry = manifest.get(path.name, {})

            expected_dims = manifest_entry.get("expected_dimensions")
            expected_width = expected_dims[0] if expected_dims and len(expected_dims) >= 1 else None
            expected_height = expected_dims[1] if expected_dims and len(expected_dims) >= 2 else None
            expected_keywords = manifest_entry.get("expected_keywords")

            # Validate
            result = self.validate_single(
                path,
                expected_width=expected_width,
                expected_height=expected_height,
                expected_keywords=expected_keywords,
            )

            # Add manifest metadata
            if manifest_entry:
                result.metadata["manifest_description"] = manifest_entry.get("description")
                result.metadata["manifest_viewport"] = manifest_entry.get("viewport")
                result.metadata["manifest_state"] = manifest_entry.get("state")

            results[str(path)] = result
            if result.is_valid:
                valid_count += 1

        return BatchValidationResult(
            total=len(results),
            valid=valid_count,
            invalid=len(results) - valid_count,
            results=results,
        )


def main():
    """CLI entry point for screenshot validation."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Validate screenshots for PRs, READMEs, and documentation"
    )

    # Input options
    input_group = parser.add_mutually_exclusive_group(required=True)
    input_group.add_argument(
        "--screenshot",
        type=str,
        help="Single screenshot file to validate",
    )
    input_group.add_argument(
        "--screenshot-dir",
        type=str,
        help="Directory containing screenshots to validate",
    )

    # Validation options
    parser.add_argument(
        "--manifest",
        type=str,
        help="Path to manifest JSON with expected values",
    )
    parser.add_argument(
        "--expected-width",
        type=int,
        help="Expected width in pixels",
    )
    parser.add_argument(
        "--expected-height",
        type=int,
        help="Expected height in pixels",
    )
    parser.add_argument(
        "--expected-keywords",
        type=str,
        help="Comma-separated list of keywords to detect (requires --ocr)",
    )
    parser.add_argument(
        "--ocr",
        action="store_true",
        help="Enable OCR text detection (requires pytesseract)",
    )

    # Output options
    parser.add_argument(
        "--output-report",
        type=str,
        help="Path to save JSON validation report",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Print detailed validation results",
    )

    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    # Parse expected keywords
    expected_keywords = None
    if args.expected_keywords:
        expected_keywords = [k.strip() for k in args.expected_keywords.split(",")]

    # Create validator
    validator = ScreenshotValidator(enable_ocr=args.ocr)

    # Validate
    if args.screenshot:
        # Single screenshot
        result = validator.validate_single(
            args.screenshot,
            expected_width=args.expected_width,
            expected_height=args.expected_height,
            expected_keywords=expected_keywords,
        )

        print(result)

        if args.output_report:
            with open(args.output_report, 'w') as f:
                json.dump(result.to_dict(), f, indent=2)
            print(f"\nReport saved to: {args.output_report}")

        # Exit with error code if invalid
        exit(0 if result.is_valid else 1)

    else:
        # Multiple screenshots
        batch_result = validator.validate_screenshots(
            screenshot_dir=args.screenshot_dir,
            manifest_path=args.manifest,
        )

        print(batch_result)

        if args.output_report:
            with open(args.output_report, 'w') as f:
                json.dump(batch_result.to_dict(), f, indent=2)
            print(f"\nReport saved to: {args.output_report}")

        # Exit with error code if any invalid
        exit(0 if batch_result.all_valid else 1)


if __name__ == "__main__":
    main()
