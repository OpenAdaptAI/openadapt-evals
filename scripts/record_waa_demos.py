#!/usr/bin/env python3
"""Record WAA task demos with guided workflow.

This script guides you through recording demos for WAA benchmark tasks.
It handles everything: shows instructions, records, and sends via wormhole.

Usage:
    python record_waa_demos.py

Requirements (auto-installed if missing):
    - openadapt-capture
    - magic-wormhole
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

# WAA tasks to record
TASKS = [
    {
        "id": "366de66e-cbae-4d72-b042-26390db2b145-WOS",
        "instruction": (
            "Open Notepad, create a new file named 'draft.txt', "
            "type 'This is a draft.', and save it to the Documents folder."
        ),
        "domain": "notepad",
        "tips": [
            "Click Start menu or press Windows key",
            "Type 'notepad' and click the app",
            "Type the text",
            "Press Ctrl+S to save",
            "Navigate to Documents folder",
            "Name it 'draft.txt' and click Save",
        ],
    },
    {
        "id": "37e10fc4-b4c5-4b02-a65c-bfae8bc51d3f-wos",
        "instruction": "Turn off notifications for my system in the settings.",
        "domain": "settings",
        "tips": [
            "Click Start menu",
            "Click Settings (gear icon)",
            "Click 'System' in the sidebar",
            "Click 'Notifications'",
            "Toggle the main 'Notifications' switch to Off",
        ],
    },
    {
        "id": "0c9dda13-428c-492b-900b-f48562111f93-WOS",
        "instruction": (
            "Create a new folder named 'Archive' in the Documents folder "
            "and move all .docx files into it."
        ),
        "domain": "file_explorer",
        "setup": "create_docx_files",
        "tips": [
            "Open File Explorer (Win+E)",
            "Navigate to Documents",
            "Right-click → New → Folder, name it 'Archive'",
            "Find .docx files (use search or sort by type)",
            "Select all .docx files (Ctrl+click or Ctrl+A after filtering)",
            "Cut (Ctrl+X), open Archive folder, Paste (Ctrl+V)",
        ],
    },
]

# File names for the docx setup task
DOCX_FILES = ["report.docx", "meeting_notes.docx", "proposal.docx"]


def print_header(text: str) -> None:
    """Print a styled header."""
    width = max(60, len(text) + 4)
    print()
    print("=" * width)
    print(f"  {text}")
    print("=" * width)
    print()


def print_task(task: dict, index: int, total: int) -> None:
    """Print task details."""
    print(f"Task {index + 1} of {total}: [{task['domain']}]")
    print()
    print(f"  \"{task['instruction']}\"")
    print()
    print("  Steps:")
    for i, tip in enumerate(task["tips"], 1):
        print(f"    {i}. {tip}")
    print()


def check_dependencies() -> bool:
    """Check and install required dependencies."""
    print("Checking dependencies...")

    # Check openadapt-capture
    try:
        import openadapt_capture
        print("  ✓ openadapt-capture installed")
    except ImportError:
        print("  Installing openadapt-capture...")
        try:
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "openadapt-capture"],
                check=True,
                capture_output=True,
            )
            print("  ✓ openadapt-capture installed")
        except subprocess.CalledProcessError:
            print("  ✗ Failed to install openadapt-capture")
            return False

    # Check magic-wormhole
    import shutil
    if shutil.which("wormhole"):
        print("  ✓ magic-wormhole installed")
    else:
        print("  Installing magic-wormhole...")
        try:
            subprocess.run(
                [sys.executable, "-m", "pip", "install", "magic-wormhole"],
                check=True,
                capture_output=True,
            )
            print("  ✓ magic-wormhole installed")
        except subprocess.CalledProcessError:
            print("  ✗ Failed to install magic-wormhole")
            return False

    print()
    return True


def setup_create_docx_files() -> None:
    """Create dummy .docx files in Documents for the archive task."""
    docs_dir = Path.home() / "Documents"
    docs_dir.mkdir(parents=True, exist_ok=True)

    # Remove Archive folder from previous runs
    archive_dir = docs_dir / "Archive"
    if archive_dir.exists():
        import shutil
        shutil.rmtree(archive_dir)

    created = []
    for name in DOCX_FILES:
        path = docs_dir / name
        if not path.exists():
            path.write_bytes(b"")
            created.append(name)

    if created:
        print(f"  Created {len(created)} .docx file(s) in Documents: {', '.join(created)}")
    else:
        print(f"  .docx files already exist in Documents")


SETUP_FUNCTIONS = {
    "create_docx_files": setup_create_docx_files,
}


def get_recordings_dir() -> Path:
    """Get the recordings directory path."""
    # Use a standard location
    home = Path.home()
    recordings_dir = home / ".openadapt" / "waa_demos"
    recordings_dir.mkdir(parents=True, exist_ok=True)
    return recordings_dir


def record_task(task: dict, recordings_dir: Path) -> Path | None:
    """Record a single task.

    Returns:
        Path to recording directory if successful, None otherwise.
    """
    from openadapt_capture import Recorder

    recording_path = recordings_dir / task["id"]

    # Remove existing recording if any
    if recording_path.exists():
        import shutil
        shutil.rmtree(recording_path)

    print("Press ENTER when ready to start recording...")
    print("(Press Ctrl 3 times to stop recording)")
    input()

    print()
    print("🔴 RECORDING... (press Ctrl 3 times to stop)")
    print()

    try:
        with Recorder(
            recording_path,
            task_description=task["instruction"],
            capture_video=True,
            capture_audio=False,
        ) as recorder:
            recorder.wait_for_ready()
            try:
                while recorder.is_recording:
                    time.sleep(1)
            except KeyboardInterrupt:
                pass

        print()
        print(f"✓ Recorded {recorder.event_count} events")
        return recording_path

    except Exception as e:
        print(f"✗ Recording failed: {e}")
        return None


def send_all_recordings(recording_paths: list[Path]) -> None:
    """Send all recordings via wormhole sequentially.

    Each send blocks until the receiver accepts, so this prints clear
    instructions before each one.
    """
    from openadapt_capture.share import send

    for i, path in enumerate(recording_paths, 1):
        print(f"--- Recording {i}/{len(recording_paths)}: {path.name} ---")
        print("Run 'wormhole receive <code>' on the receiving machine.")
        print()
        send(str(path))
        print()


def main() -> int:
    """Main entry point."""
    print_header("WAA Demo Recording Tool")

    if not check_dependencies():
        print("Please install dependencies manually and try again.")
        return 1

    recordings_dir = get_recordings_dir()
    print(f"Recordings will be saved to: {recordings_dir}")

    # Track results
    results = {}  # task_id -> recording_path or None

    # Record each task
    task_index = 0
    while task_index < len(TASKS):
        task = TASKS[task_index]

        print_header(f"Task {task_index + 1} of {len(TASKS)}")
        print_task(task, task_index, len(TASKS))

        # Run setup if needed
        setup_name = task.get("setup")
        if setup_name and setup_name in SETUP_FUNCTIONS:
            print("  Setting up environment...")
            SETUP_FUNCTIONS[setup_name]()
            print()

        recording_path = record_task(task, recordings_dir)

        if recording_path:
            print()
            response = input("Keep this recording? [Y/n/r] ").strip().lower()

            if response in ("", "y", "yes"):
                results[task["id"]] = recording_path
                print(f"✓ Task {task_index + 1} saved")
                task_index += 1
            elif response in ("r", "redo"):
                print("Retrying...")
                continue
            else:
                results[task["id"]] = None
                print(f"✗ Task {task_index + 1} skipped")
                task_index += 1
        else:
            response = input("Recording failed. Retry? [Y/n] ").strip().lower()
            if response in ("", "y", "yes"):
                continue
            else:
                results[task["id"]] = None
                task_index += 1

    # Summary
    print_header("Summary")

    successful = [tid for tid, path in results.items() if path is not None]
    skipped = [tid for tid, path in results.items() if path is None]

    for task in TASKS:
        status = "✓ recorded" if results.get(task["id"]) else "✗ skipped"
        print(f"  Task [{task['domain']}]: {status}")

    print()

    if not successful:
        print("No recordings to send.")
        return 0

    # Send recordings
    response = input(f"Send {len(successful)} recording(s) now? [Y/n] ").strip().lower()

    if response not in ("", "y", "yes"):
        print()
        print("Recordings saved locally. To send later:")
        for task_id in successful:
            print(f"  capture share send {recordings_dir / task_id}")
        return 0

    print_header("Sending Recordings")
    print("Each recording will be sent one at a time.")
    print("You must run 'wormhole receive <code>' on the receiving machine for each one.")
    print()

    paths = [results[tid] for tid in successful]
    send_all_recordings(paths)

    print_header("Done!")

    return 0


if __name__ == "__main__":
    sys.exit(main())
