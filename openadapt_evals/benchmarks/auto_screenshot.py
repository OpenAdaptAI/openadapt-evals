"""Auto-screenshot tool for capturing benchmark viewer in multiple viewports.

This module provides functionality to automatically capture screenshots of the
benchmark viewer HTML in different viewport sizes (desktop, tablet, mobile) and
different states (overview, details panel, log panel, etc.).

Usage:
    from openadapt_evals.benchmarks.auto_screenshot import generate_screenshots

    generate_screenshots(
        html_path="benchmark_results/viewer_demo/viewer.html",
        output_dir="screenshots",
        viewports=["desktop", "tablet", "mobile"],
    )

Requirements:
    pip install playwright
    playwright install chromium
"""

from __future__ import annotations

import logging
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Viewport configurations
VIEWPORTS = {
    "desktop": {"width": 1920, "height": 1080},
    "tablet": {"width": 768, "height": 1024},
    "mobile": {"width": 375, "height": 667},
}


def ensure_playwright_installed() -> bool:
    """Check if Playwright is installed and install if needed.

    Returns:
        True if Playwright is available, False otherwise.
    """
    try:
        import playwright
        return True
    except ImportError:
        logger.warning("Playwright not installed. Installing...")
        try:
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "playwright"],
                check=True,
                capture_output=True,
            )
            subprocess.run(
                ["playwright", "install", "chromium"],
                check=True,
                capture_output=True,
            )
            logger.info("Playwright installed successfully")
            return True
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to install Playwright: {e}")
            return False


def generate_screenshots(
    html_path: str | Path,
    output_dir: str | Path,
    viewports: list[str] | None = None,
    states: list[str] | None = None,
) -> dict[str, list[Path]]:
    """Generate screenshots of benchmark viewer in different viewports and states.

    Args:
        html_path: Path to the benchmark viewer HTML file.
        output_dir: Directory to save screenshots.
        viewports: List of viewport names to capture (default: all).
        states: List of states to capture (default: all).
            Options: "overview", "task_detail", "log_expanded", "log_collapsed"

    Returns:
        Dictionary mapping viewport names to lists of screenshot paths.
    """
    if not ensure_playwright_installed():
        logger.error("Cannot generate screenshots without Playwright")
        return {}

    from playwright.sync_api import sync_playwright

    html_path = Path(html_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if viewports is None:
        viewports = list(VIEWPORTS.keys())

    if states is None:
        states = ["overview", "task_detail", "log_expanded", "log_collapsed"]

    screenshots: dict[str, list[Path]] = {vp: [] for vp in viewports}

    with sync_playwright() as p:
        browser = p.chromium.launch()

        for viewport_name in viewports:
            if viewport_name not in VIEWPORTS:
                logger.warning(f"Unknown viewport: {viewport_name}, skipping")
                continue

            viewport = VIEWPORTS[viewport_name]
            logger.info(f"Capturing {viewport_name} screenshots ({viewport['width']}x{viewport['height']})")

            page = browser.new_page(viewport=viewport)

            # Load the HTML file
            page.goto(f"file://{html_path.absolute()}")

            # Wait for page to load
            page.wait_for_load_state("networkidle")
            time.sleep(1)  # Extra wait for animations

            # Capture overview state
            if "overview" in states:
                screenshot_path = output_dir / f"{viewport_name}_overview.png"
                page.screenshot(path=str(screenshot_path), full_page=True)
                screenshots[viewport_name].append(screenshot_path)
                logger.info(f"  Saved: {screenshot_path}")

            # Select first task to show task detail
            try:
                task_items = page.query_selector_all(".task-item")
                if task_items and len(task_items) > 0:
                    task_items[0].click()
                    time.sleep(0.5)  # Wait for task detail to load

                    # Capture task detail state
                    if "task_detail" in states:
                        screenshot_path = output_dir / f"{viewport_name}_task_detail.png"
                        page.screenshot(path=str(screenshot_path), full_page=True)
                        screenshots[viewport_name].append(screenshot_path)
                        logger.info(f"  Saved: {screenshot_path}")

                    # Expand log panel if it exists
                    log_header = page.query_selector(".log-panel-header")
                    if log_header and "log_expanded" in states:
                        # Check if log panel is collapsed
                        log_container = page.query_selector(".log-container")
                        if log_container and "collapsed" in log_container.get_attribute("class"):
                            log_header.click()
                            time.sleep(0.3)

                        screenshot_path = output_dir / f"{viewport_name}_log_expanded.png"
                        page.screenshot(path=str(screenshot_path), full_page=True)
                        screenshots[viewport_name].append(screenshot_path)
                        logger.info(f"  Saved: {screenshot_path}")

                    # Collapse log panel
                    if log_header and "log_collapsed" in states:
                        log_header.click()
                        time.sleep(0.3)

                        screenshot_path = output_dir / f"{viewport_name}_log_collapsed.png"
                        page.screenshot(path=str(screenshot_path), full_page=True)
                        screenshots[viewport_name].append(screenshot_path)
                        logger.info(f"  Saved: {screenshot_path}")

            except Exception as e:
                logger.warning(f"Error capturing task detail states: {e}")

            page.close()

        browser.close()

    logger.info(f"Generated {sum(len(paths) for paths in screenshots.values())} screenshots")
    return screenshots


def main():
    """CLI entry point for auto-screenshot tool."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Generate screenshots of benchmark viewer"
    )
    parser.add_argument(
        "--html-path",
        required=True,
        help="Path to benchmark viewer HTML file",
    )
    parser.add_argument(
        "--output-dir",
        default="screenshots",
        help="Output directory for screenshots (default: screenshots)",
    )
    parser.add_argument(
        "--viewports",
        nargs="+",
        choices=list(VIEWPORTS.keys()),
        default=list(VIEWPORTS.keys()),
        help="Viewports to capture (default: all)",
    )
    parser.add_argument(
        "--states",
        nargs="+",
        choices=["overview", "task_detail", "log_expanded", "log_collapsed"],
        default=["overview", "task_detail", "log_expanded", "log_collapsed"],
        help="States to capture (default: all)",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%H:%M:%S",
    )

    screenshots = generate_screenshots(
        html_path=args.html_path,
        output_dir=args.output_dir,
        viewports=args.viewports,
        states=args.states,
    )

    print("\nGenerated screenshots:")
    for viewport, paths in screenshots.items():
        print(f"\n{viewport}:")
        for path in paths:
            print(f"  - {path}")


if __name__ == "__main__":
    main()
