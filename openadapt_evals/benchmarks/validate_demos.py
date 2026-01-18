"""Validate synthetic demo format and compatibility with APIBenchmarkAgent.

This script validates that generated demos:
1. Follow the correct format (TASK, DOMAIN, STEPS, EXPECTED_OUTCOME)
2. Have valid action syntax
3. Are compatible with ApiAgent demo loading
4. Can be parsed correctly

Usage:
    python -m openadapt_evals.benchmarks.validate_demos --demo-dir demo_library/synthetic_demos
    python -m openadapt_evals.benchmarks.validate_demos --demo-file demo_library/synthetic_demos/notepad_1.txt
"""

import argparse
import json
import logging
import re
from pathlib import Path
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)

# Valid action types
VALID_ACTIONS = [
    "CLICK",
    "RIGHT_CLICK",
    "DOUBLE_CLICK",
    "TRIPLE_CLICK",
    "TYPE",
    "HOTKEY",
    "WAIT",
    "DRAG",
    "HOVER",
    "SCROLL",
    "DONE",
    "FAIL",
]


class DemoValidator:
    """Validates demo file format and content."""

    def __init__(self):
        self.errors: List[str] = []
        self.warnings: List[str] = []

    def validate_demo(self, demo_path: Path) -> Tuple[bool, List[str], List[str]]:
        """Validate a single demo file.

        Args:
            demo_path: Path to demo file

        Returns:
            Tuple of (is_valid, errors, warnings)
        """
        self.errors = []
        self.warnings = []

        try:
            content = demo_path.read_text(encoding="utf-8")
        except Exception as e:
            self.errors.append(f"Failed to read file: {e}")
            return False, self.errors, self.warnings

        # Check required sections
        if not content.startswith("TASK:"):
            self.errors.append("Demo must start with 'TASK:' line")

        if "DOMAIN:" not in content:
            self.errors.append("Missing 'DOMAIN:' section")

        if "STEPS:" not in content:
            self.errors.append("Missing 'STEPS:' section")

        if "EXPECTED_OUTCOME:" not in content:
            self.warnings.append("Missing 'EXPECTED_OUTCOME:' section")

        # Extract and validate steps
        steps_section = self._extract_section(content, "STEPS:", "EXPECTED_OUTCOME:")
        if steps_section:
            self._validate_steps(steps_section)
        else:
            self.errors.append("Could not extract STEPS section")

        # Check for DONE() action
        if "DONE()" not in content:
            self.errors.append("Demo must end with DONE() action")

        is_valid = len(self.errors) == 0
        return is_valid, self.errors, self.warnings

    def _extract_section(self, content: str, start_marker: str, end_marker: str) -> str:
        """Extract a section between two markers."""
        try:
            start_idx = content.index(start_marker) + len(start_marker)
            if end_marker:
                end_idx = content.index(end_marker)
                return content[start_idx:end_idx].strip()
            else:
                return content[start_idx:].strip()
        except ValueError:
            return ""

    def _validate_steps(self, steps_content: str) -> None:
        """Validate the STEPS section."""
        lines = steps_content.split("\n")
        step_numbers = []
        actions = []

        for line in lines:
            line = line.strip()
            if not line:
                continue

            # Check for step numbers (e.g., "1. ", "2. ", etc.)
            step_match = re.match(r"^(\d+)\.\s+(.+)", line)
            if step_match:
                step_num = int(step_match.group(1))
                step_numbers.append(step_num)
                continue

            # Check for ACTION: lines
            if line.startswith("ACTION:"):
                action_str = line[7:].strip()
                actions.append(action_str)
                self._validate_action(action_str)

        # Validate step numbering
        if step_numbers:
            expected = list(range(1, len(step_numbers) + 1))
            if step_numbers != expected:
                self.errors.append(
                    f"Step numbering is not sequential: {step_numbers} (expected {expected})"
                )
        else:
            self.warnings.append("No numbered steps found")

        # Validate actions
        if not actions:
            self.errors.append("No ACTION statements found")
        elif actions[-1] != "DONE()":
            self.warnings.append("Last action should be DONE()")

    def _validate_action(self, action_str: str) -> None:
        """Validate an individual action string."""
        # Extract action type
        action_type_match = re.match(r"^([A-Z_]+)\(", action_str)
        if not action_type_match:
            self.errors.append(f"Invalid action format: {action_str}")
            return

        action_type = action_type_match.group(1)
        if action_type not in VALID_ACTIONS:
            self.errors.append(f"Unknown action type: {action_type}")

        # Validate specific action formats
        if action_type == "CLICK":
            if not re.match(r"CLICK\(x=[\d.]+,\s*y=[\d.]+\)", action_str):
                self.errors.append(f"Invalid CLICK format: {action_str}")
                return
            # Check coordinate ranges
            x_match = re.search(r"x=([\d.]+)", action_str)
            y_match = re.search(r"y=([\d.]+)", action_str)
            if x_match and y_match:
                x = float(x_match.group(1))
                y = float(y_match.group(1))
                if not (0.0 <= x <= 1.0) or not (0.0 <= y <= 1.0):
                    self.warnings.append(
                        f"Coordinates outside normalized range [0,1]: {action_str}"
                    )

        elif action_type in ["RIGHT_CLICK", "DOUBLE_CLICK", "HOVER"]:
            if not re.match(rf"{action_type}\(x=[\d.]+,\s*y=[\d.]+\)", action_str):
                self.errors.append(f"Invalid {action_type} format: {action_str}")

        elif action_type == "TYPE":
            if not re.match(r'TYPE\(".*"\)', action_str):
                self.errors.append(f"Invalid TYPE format (should use double quotes): {action_str}")

        elif action_type == "HOTKEY":
            # Support both formats: HOTKEY("ctrl+s") and HOTKEY("ctrl", "s")
            # Also support special chars like "+", "-", etc.
            if not (re.match(r'HOTKEY\("[\w\s,+\-=]+"\)', action_str) or
                    re.match(r'HOTKEY\("[\w\-+=]+"\s*(,\s*"[\w\-+=]+"\s*)*\)', action_str)):
                self.errors.append(f"Invalid HOTKEY format: {action_str}")

        elif action_type == "WAIT":
            if not re.match(r"WAIT\([\d.]+\)", action_str):
                self.errors.append(f"Invalid WAIT format: {action_str}")

        elif action_type == "DRAG":
            if not re.match(
                r"DRAG\(start_x=[\d.]+,\s*start_y=[\d.]+,\s*end_x=[\d.]+,\s*end_y=[\d.]+\)",
                action_str,
            ):
                self.errors.append(f"Invalid DRAG format: {action_str}")

        elif action_type == "SCROLL":
            if not re.match(r'SCROLL\(direction="(up|down|left|right)"\)', action_str):
                self.errors.append(f"Invalid SCROLL format: {action_str}")

        elif action_type in ["DONE", "FAIL"]:
            if action_str not in [f"{action_type}()"]:
                self.errors.append(f"Invalid {action_type} format (should be '{action_type}()'): {action_str}")


def validate_all_demos(demo_dir: Path) -> Dict[str, Dict]:
    """Validate all demos in a directory.

    Args:
        demo_dir: Directory containing demo files

    Returns:
        Dictionary mapping demo_id to validation results
    """
    validator = DemoValidator()
    results = {}

    demo_files = sorted(demo_dir.glob("*.txt"))
    logger.info(f"Validating {len(demo_files)} demos in {demo_dir}")

    for demo_file in demo_files:
        demo_id = demo_file.stem
        is_valid, errors, warnings = validator.validate_demo(demo_file)

        results[demo_id] = {
            "valid": is_valid,
            "errors": errors,
            "warnings": warnings,
            "file": str(demo_file),
        }

        if is_valid:
            if warnings:
                logger.info(f"✓ {demo_id} (valid with {len(warnings)} warnings)")
            else:
                logger.info(f"✓ {demo_id} (valid)")
        else:
            logger.error(f"✗ {demo_id} (invalid - {len(errors)} errors)")

    return results


def main():
    """Main CLI entry point."""
    parser = argparse.ArgumentParser(description="Validate synthetic demo files")
    parser.add_argument(
        "--demo-dir",
        type=Path,
        help="Directory containing demo files to validate",
    )
    parser.add_argument(
        "--demo-file",
        type=Path,
        help="Specific demo file to validate",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Show detailed error messages",
    )
    parser.add_argument(
        "--json-output",
        type=Path,
        help="Save validation results to JSON file",
    )

    args = parser.parse_args()

    # Setup logging
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(message)s",
    )

    # Validate demos
    if args.demo_file:
        # Validate single file
        validator = DemoValidator()
        is_valid, errors, warnings = validator.validate_demo(args.demo_file)

        print(f"\nValidation Results for {args.demo_file.name}:")
        print(f"{'=' * 60}")
        print(f"Valid: {is_valid}")

        if errors:
            print(f"\nErrors ({len(errors)}):")
            for error in errors:
                print(f"  - {error}")

        if warnings:
            print(f"\nWarnings ({len(warnings)}):")
            for warning in warnings:
                print(f"  - {warning}")

        return 0 if is_valid else 1

    elif args.demo_dir:
        # Validate directory
        results = validate_all_demos(args.demo_dir)

        # Summary
        total = len(results)
        valid = sum(1 for r in results.values() if r["valid"])
        invalid = total - valid

        print(f"\n{'=' * 60}")
        print("VALIDATION SUMMARY")
        print(f"{'=' * 60}")
        print(f"Total demos: {total}")
        print(f"Valid: {valid} ({valid/total*100:.1f}%)")
        print(f"Invalid: {invalid} ({invalid/total*100:.1f}%)")

        # Show errors if verbose
        if args.verbose and invalid > 0:
            print(f"\n{'=' * 60}")
            print("DETAILED ERRORS")
            print(f"{'=' * 60}")
            for demo_id, result in results.items():
                if not result["valid"]:
                    print(f"\n{demo_id}:")
                    for error in result["errors"]:
                        print(f"  - {error}")

        # Save JSON output
        if args.json_output:
            with open(args.json_output, "w") as f:
                json.dump(results, f, indent=2)
            print(f"\nValidation results saved to {args.json_output}")

        return 0 if invalid == 0 else 1

    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    exit(main())
