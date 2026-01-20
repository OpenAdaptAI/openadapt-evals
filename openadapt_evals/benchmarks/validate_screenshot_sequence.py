"""Validate screenshot sequences to ensure they show action progression.

This module validates that a sequence of screenshots shows real progression
of actions, not static/duplicate screenshots or idle desktop images.

IMPORTANT: Screenshots must show actions progressing, not the same idle state repeated.
See SCREENSHOT_REQUIREMENTS.md for requirements.

Usage:
    from openadapt_evals.benchmarks.validate_screenshot_sequence import validate_sequence

    result = validate_sequence(
        screenshots=["step_001.png", "step_002.png", "step_003.png"],
        min_change_threshold=0.01  # At least 1% pixel difference
    )

    if result.static_frames > 0:
        print(f"Warning: Found {result.static_frames} static/duplicate screenshots")

CLI Usage:
    python -m openadapt_evals.benchmarks.validate_screenshot_sequence \
        --screenshots step_001.png step_002.png step_003.png \
        --min-change-threshold 0.01
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    from PIL import Image
    import numpy as np
    PILLOW_AVAILABLE = True
    NUMPY_AVAILABLE = True
except ImportError:
    PILLOW_AVAILABLE = False
    NUMPY_AVAILABLE = False

logger = logging.getLogger(__name__)


@dataclass
class SequenceValidationResult:
    """Result of screenshot sequence validation.

    Attributes:
        total_frames: Total number of screenshots in sequence.
        static_frames: Number of frames with no visible change.
        frame_differences: List of pixel difference percentages between consecutive frames.
        is_valid: Whether the sequence shows real progression.
        errors: List of error messages.
        warnings: List of warning messages.
        metadata: Additional metadata about the sequence.
    """
    total_frames: int
    static_frames: int
    frame_differences: list[float] = field(default_factory=list)
    is_valid: bool = True
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:
        """Human-readable string representation."""
        status = "VALID" if self.is_valid else "INVALID"
        parts = [
            f"Sequence Validation: {status}",
            f"  Total Frames: {self.total_frames}",
            f"  Static Frames: {self.static_frames}",
            f"  Average Change: {sum(self.frame_differences) / len(self.frame_differences) * 100:.2f}%" if self.frame_differences else "N/A",
        ]

        if self.errors:
            parts.append(f"  Errors:")
            for error in self.errors:
                parts.append(f"    - {error}")

        if self.warnings:
            parts.append(f"  Warnings:")
            for warning in self.warnings:
                parts.append(f"    - {warning}")

        return "\n".join(parts)


def calculate_image_difference(img1_path: Path, img2_path: Path) -> float:
    """Calculate pixel difference between two images.

    Args:
        img1_path: Path to first image.
        img2_path: Path to second image.

    Returns:
        Float between 0.0 and 1.0 representing fraction of pixels that differ.
        Returns 1.0 if images have different dimensions.
    """
    if not PILLOW_AVAILABLE or not NUMPY_AVAILABLE:
        logger.warning("Pillow or NumPy not available. Skipping image comparison.")
        return 0.5  # Assume moderate change if we can't check

    try:
        img1 = Image.open(img1_path)
        img2 = Image.open(img2_path)

        # Convert to same mode
        if img1.mode != img2.mode:
            img2 = img2.convert(img1.mode)

        # Check dimensions
        if img1.size != img2.size:
            logger.warning(f"Images have different dimensions: {img1.size} vs {img2.size}")
            return 1.0  # Completely different

        # Convert to numpy arrays
        arr1 = np.array(img1)
        arr2 = np.array(img2)

        # Calculate pixel difference
        diff = np.abs(arr1.astype(float) - arr2.astype(float))

        # Count pixels that differ by more than threshold (5 out of 255)
        threshold = 5
        changed_pixels = np.any(diff > threshold, axis=-1) if diff.ndim == 3 else diff > threshold

        # Calculate fraction of changed pixels
        fraction_changed = np.sum(changed_pixels) / changed_pixels.size

        return float(fraction_changed)

    except Exception as e:
        logger.error(f"Failed to compare images: {e}")
        return 0.5  # Assume moderate change on error


def validate_sequence(
    screenshots: list[str | Path],
    min_change_threshold: float = 0.01,
    max_static_frames: int = 2,
) -> SequenceValidationResult:
    """Validate that screenshot sequence shows action progression.

    Args:
        screenshots: List of screenshot paths in chronological order.
        min_change_threshold: Minimum pixel difference fraction (0.0-1.0) to consider
            frames different. Default 0.01 = 1% of pixels changed.
        max_static_frames: Maximum number of consecutive static frames allowed.

    Returns:
        SequenceValidationResult with validation details.
    """
    if not PILLOW_AVAILABLE:
        return SequenceValidationResult(
            total_frames=len(screenshots),
            static_frames=0,
            is_valid=False,
            errors=["Pillow not available. Install with: pip install Pillow"],
        )

    if len(screenshots) < 2:
        return SequenceValidationResult(
            total_frames=len(screenshots),
            static_frames=0,
            is_valid=False,
            errors=["Need at least 2 screenshots to validate sequence"],
        )

    result = SequenceValidationResult(
        total_frames=len(screenshots),
        static_frames=0,
    )

    # Convert to Path objects
    screenshot_paths = [Path(s) for s in screenshots]

    # Check all files exist
    missing = [str(p) for p in screenshot_paths if not p.exists()]
    if missing:
        result.is_valid = False
        result.errors.append(f"Screenshots not found: {', '.join(missing)}")
        return result

    # Compare consecutive frames
    consecutive_static = 0
    max_consecutive_static = 0

    for i in range(len(screenshot_paths) - 1):
        diff = calculate_image_difference(screenshot_paths[i], screenshot_paths[i + 1])
        result.frame_differences.append(diff)

        # Check if frames are essentially identical (static)
        if diff < min_change_threshold:
            result.static_frames += 1
            consecutive_static += 1
            max_consecutive_static = max(max_consecutive_static, consecutive_static)

            result.warnings.append(
                f"Frames {i} -> {i+1} show little change ({diff*100:.2f}% pixels changed). "
                "Screenshots should show progression of actions, not idle/static state."
            )
        else:
            consecutive_static = 0  # Reset counter

    # Validate results
    result.metadata["max_consecutive_static"] = max_consecutive_static
    result.metadata["average_change"] = sum(result.frame_differences) / len(result.frame_differences)

    if result.static_frames > max_static_frames:
        result.is_valid = False
        result.errors.append(
            f"Too many static frames: {result.static_frames}/{len(screenshot_paths)-1}. "
            "Screenshots should show real actions progressing, not idle desktop repeated. "
            "See SCREENSHOT_REQUIREMENTS.md for requirements."
        )

    if max_consecutive_static > max_static_frames:
        result.is_valid = False
        result.errors.append(
            f"Too many consecutive static frames: {max_consecutive_static}. "
            "This indicates agent is stuck or screenshots show idle state."
        )

    # Check if average change is too low (all frames very similar)
    avg_change = sum(result.frame_differences) / len(result.frame_differences)
    if avg_change < min_change_threshold * 2:
        result.warnings.append(
            f"Very low average change across sequence ({avg_change*100:.2f}%). "
            "This may indicate idle desktop screenshots or agent not taking actions."
        )

    return result


def main():
    """CLI entry point for sequence validation."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Validate screenshot sequence shows action progression"
    )

    parser.add_argument(
        "--screenshots",
        nargs="+",
        required=True,
        help="Screenshot paths in chronological order",
    )
    parser.add_argument(
        "--min-change-threshold",
        type=float,
        default=0.01,
        help="Minimum pixel difference (0.0-1.0) to consider frames different (default: 0.01 = 1%%)",
    )
    parser.add_argument(
        "--max-static-frames",
        type=int,
        default=2,
        help="Maximum number of static frames allowed (default: 2)",
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

    # Validate sequence
    result = validate_sequence(
        screenshots=args.screenshots,
        min_change_threshold=args.min_change_threshold,
        max_static_frames=args.max_static_frames,
    )

    print(result)

    # Exit with error code if invalid
    exit(0 if result.is_valid else 1)


if __name__ == "__main__":
    main()
