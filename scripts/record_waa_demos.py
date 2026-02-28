#!/usr/bin/env python3
"""Record WAA task demos with guided workflow.

This script guides you through recording demos for WAA benchmark tasks.
Supports local recording (via openadapt-capture), remote interactive recording
(via WAA API + VNC), VLM annotation, and demo-conditioned evaluation.

Usage:
    # Local recording (original workflow)
    python record_waa_demos.py record

    # Interactive recording via WAA API (user performs actions on VNC)
    python record_waa_demos.py record-waa \
      --tasks 04d9aeaf,0a0faba3 \
      --server http://localhost:5001 \
      --output waa_recordings/

    # VLM annotation of recorded screenshots
    python record_waa_demos.py annotate \
      --recordings waa_recordings/ \
      --output annotated_demos/ \
      --provider openai

    # Run demo-conditioned eval (wraps eval-suite)
    python record_waa_demos.py eval \
      --demo_dir annotated_demos/ \
      --tasks 04d9aeaf,0a0faba3 \
      --agent api-openai
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# Load .env for API keys
from dotenv import load_dotenv
load_dotenv()

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

# 12 harder WAA task IDs for demo-conditioned eval
HARDER_TASK_IDS = [
    "04d9aeaf-7bed-4024-bedb-e10e6f00eb7f-WOS",
    "0a0faba3-5580-44df-965d-f562a99b291c-WOS",
    "0bf05a7d-b28b-44d2-955a-50b41e24012a-WOS",
    "0e763496-b6bb-4508-a427-fad0b6c3e195-WOS",
    "4bcb1253-a636-4df4-8cb0-a35c04dfef31-WOS",
    "70745df8-f2f5-42bd-8074-fbc10334fcc5-2-WOS",
    "8b1ce5f2-59d2-4dcc-b0b0-666a714b9a14-WOS",
    "e2b5e914-ffe1-44d2-8e92-58f8c5d92bb2-WOS",
    "ec71221e-ac43-46f9-89b8-ee7d80f7e1c5-WOS",
    "fba2c100-79e8-42df-ae74-b592418d54f4-WOS",
    "INF-0d95d28a-9587-433b-a805-1fbe5467d598-WOS",
    "INF-5ac2891a-eacd-4954-b339-98abba077adb-WOS",
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


# ---------------------------------------------------------------------------
# WAA API interactive recording
# ---------------------------------------------------------------------------


def _take_screenshot(server: str) -> bytes:
    """Take a screenshot from the WAA server, raising on failure."""
    import requests

    resp = requests.get(f"{server}/screenshot", timeout=30)
    resp.raise_for_status()
    return resp.content


def _generate_steps(
    screenshot_png: bytes,
    instruction: str,
    task_config: dict,
) -> str:
    """Use a VLM to generate step-by-step instructions from the current screen.

    Returns plain-text numbered steps, or a fallback message on error.
    """
    import base64
    import os

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return "(No OPENAI_API_KEY set — skipping AI step generation)"

    import requests as _req

    b64 = base64.b64encode(screenshot_png).decode()

    setup_desc = ""
    for entry in task_config.get("config", []):
        t = entry.get("type", "")
        p = entry.get("parameters", {})
        if t == "download":
            for f in p.get("files", []):
                setup_desc += f"  - File downloaded: {f['path']}\n"
        elif t == "open":
            setup_desc += f"  - File opened: {p.get('path', '?')}\n"
        elif t == "launch":
            setup_desc += f"  - App launched: {p.get('command', '?')}\n"

    prompt = f"""You are helping a human perform a task on a Windows desktop via VNC.

TASK: {instruction}

ENVIRONMENT SETUP (already done automatically):
{setup_desc if setup_desc else "  (none)"}

Look at the screenshot and give step-by-step instructions to complete the task.
Be specific about what to click, what to type, and what menus to use.
If a file should already be open but isn't visible, say how to open it.
Keep each step to one action. Use plain text, numbered list.
Be concise — the user will read this on a phone screen."""

    try:
        resp = _req.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "model": "gpt-4o",
                "max_tokens": 800,
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{b64}",
                                    "detail": "high",
                                },
                            },
                        ],
                    }
                ],
            },
            timeout=30,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        return f"(AI step generation failed: {e})"


def cmd_record_waa(
    tasks: str = ",".join(HARDER_TASK_IDS),
    server: str = "http://localhost:5001",
    evaluate_url: str = "http://localhost:5050",
    output: str = "waa_recordings",
    vnc_url: str = "http://localhost:8006",
    verify: bool = True,
) -> None:
    """Record demos interactively via WAA API while user performs actions on VNC.

    Args:
        tasks: Comma-separated task IDs (or prefix matches).
        server: WAA server URL.
        evaluate_url: Evaluate server URL (for /task/<id> lookups).
        output: Output directory for recordings.
        vnc_url: VNC URL for the user to open in a browser.
        verify: Pre-flight check that all required apps are installed (default True).
    """
    import requests

    output_dir = Path(output)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Parse task IDs — support prefix matching against HARDER_TASK_IDS
    raw_ids = [t.strip() for t in tasks.split(",") if t.strip()]
    task_ids = []
    for raw in raw_ids:
        # Try exact match first
        if any(raw == tid for tid in HARDER_TASK_IDS):
            task_ids.append(raw)
        else:
            # Prefix match
            matches = [tid for tid in HARDER_TASK_IDS if tid.startswith(raw)]
            if len(matches) == 1:
                task_ids.append(matches[0])
            elif len(matches) > 1:
                print(f"Ambiguous prefix '{raw}' matches: {matches}")
                return
            else:
                # Not in HARDER_TASK_IDS — use as-is (custom task ID)
                task_ids.append(raw)

    # Verify connection
    print(f"Connecting to WAA server at {server}...")
    try:
        resp = requests.get(f"{server}/probe", timeout=5)
        resp.raise_for_status()
        print(f"  Connected ({resp.status_code})")
    except Exception as e:
        print(f"  Failed to connect: {e}")
        print("  Make sure the WAA server is running and SSH tunnels are up.")
        return

    # Pre-flight: verify all required apps are installed
    if verify:
        print("Verifying required apps across all tasks...")
        all_apps: set[str] = set()
        for task_id in task_ids:
            try:
                resp = requests.get(f"{evaluate_url}/task/{task_id}", timeout=10)
                if resp.ok:
                    all_apps.update(resp.json().get("related_apps", []))
            except Exception:
                pass
        if all_apps:
            resp = requests.post(
                f"{evaluate_url}/setup",
                json={"config": [{"type": "verify_apps", "parameters": {"apps": list(all_apps)}}]},
                timeout=30,
            )
            if resp.status_code != 200:
                errors = [
                    r for r in resp.json().get("results", [])
                    if r.get("status") == "error"
                ]
                for err in errors:
                    print(f"  ERROR: {err.get('error', '?')}")
                answer = input("  Missing apps detected. Continue anyway? [y/N] ").strip().lower()
                if answer not in ("y", "yes"):
                    print("  Aborting. Install missing apps and retry.")
                    return
            else:
                print(f"  All {len(all_apps)} required app(s) present.")
        else:
            print("  No app checks needed (no related_apps in task configs).")
        print()

    print(f"Recording {len(task_ids)} task(s) to {output_dir}")
    print(f"\n  VNC (open in browser): {vnc_url}\n")

    recorded = []
    for task_num, task_id in enumerate(task_ids, 1):
        print_header(f"Task {task_num}/{len(task_ids)}: {task_id[:12]}...")

        task_dir = output_dir / task_id
        task_dir.mkdir(parents=True, exist_ok=True)

        # Load task config from evaluate server
        instruction = task_id  # fallback
        task_config = {}
        try:
            task_resp = requests.get(
                f"{evaluate_url}/task/{task_id}", timeout=10
            )
            if task_resp.ok:
                task_config = task_resp.json()
                instruction = task_config.get(
                    "instruction", task_config.get("task", task_id)
                )
        except Exception as e:
            print(f"  Warning: could not load task config: {e}")

        # Reset environment
        print("  Resetting environment...")
        try:
            resp = requests.post(f"{server}/setup/close_all", timeout=30)
            print(f"    close_all: {resp.status_code}")
            time.sleep(2)
            setup_config = task_config.get("config", [])
            related_apps = task_config.get("related_apps", [])
            if related_apps:
                setup_config = [
                    {"type": "verify_apps", "parameters": {"apps": related_apps}}
                ] + setup_config
            if setup_config:
                resp = requests.post(
                    f"{evaluate_url}/setup",
                    json={"config": setup_config},
                    timeout=120,
                )
                resp.raise_for_status()
                results = resp.json().get("results", [])
                for r in results:
                    status = r.get("status", "?")
                    stype = r.get("type", "?")
                    print(f"    setup {stype}: {status}")
            time.sleep(3)
        except Exception as e:
            print(f"  WARNING: environment setup failed: {e}")
            print(f"  The task app may not be open. Check VNC.")

        # Take initial screenshot
        print("  Taking initial screenshot...")
        before_png = _take_screenshot(server)

        print(f"\n  VNC: {vnc_url}")
        print(f"  Task: {instruction}\n")

        # Generate AI step-by-step guidance from screenshot
        print("  Generating suggested steps...")
        suggested = _generate_steps(before_png, instruction, task_config)
        print()
        print("  ┌─ SUGGESTED STEPS ──────────────────────────────")
        for line in suggested.splitlines():
            print(f"  │ {line}")
        print("  └────────────────────────────────────────────────")
        print()
        print("  Perform each action in VNC, then press Enter here.")
        print("  Press 'd' when done, 'r' to redo last step.\n")

        steps = []
        step_idx = 0
        while True:
            # Save before screenshot
            (task_dir / f"step_{step_idx:02d}_before.png").write_bytes(
                before_png
            )

            action_desc = input(
                f"  Step {step_idx + 1}: Press Enter after action "
                "(or 'd' if done, 'r' to redo last): "
            ).strip()

            if action_desc.lower() == "d":
                # Save final screenshot as the last after
                after_png = _take_screenshot(server)
                (task_dir / f"step_{step_idx:02d}_after.png").write_bytes(
                    after_png
                )
                steps.append({"action_hint": action_desc or None})
                step_idx += 1
                break

            if action_desc.lower() == "r" and step_idx > 0:
                # Redo: go back one step
                step_idx -= 1
                steps.pop()
                # Re-take the before screenshot from current state
                before_png = _take_screenshot(server)
                print(f"  Redoing step {step_idx + 1}...")
                continue

            # Take after screenshot
            after_png = _take_screenshot(server)
            (task_dir / f"step_{step_idx:02d}_after.png").write_bytes(
                after_png
            )

            steps.append({"action_hint": action_desc or None})
            before_png = after_png  # next step's before = this step's after
            step_idx += 1

        # Save metadata
        meta = {
            "task_id": task_id,
            "instruction": instruction,
            "num_steps": len(steps),
            "steps": steps,
            "server_url": server,
            "recorded_at": datetime.now(timezone.utc).isoformat(),
        }
        (task_dir / "meta.json").write_text(
            json.dumps(meta, indent=2), encoding="utf-8"
        )

        recorded.append(task_id)
        print(f"\n  Saved {len(steps)} step(s) to {task_dir}")

    # Summary
    print_header("Recording Summary")
    print(f"  Recorded: {len(recorded)}/{len(task_ids)} tasks")
    for tid in recorded:
        print(f"    {tid}")
    print(f"\n  Output directory: {output_dir}")
    print(
        f"\n  Next: python {__file__} annotate "
        f"--recordings {output_dir} --output annotated_demos/"
    )


# ---------------------------------------------------------------------------
# VLM annotation of WAA recordings
# ---------------------------------------------------------------------------


def cmd_annotate_waa(
    recordings: str = "waa_recordings",
    output: str = "annotated_demos",
    provider: str = "openai",
    model: str | None = None,
    api_key: str | None = None,
) -> None:
    """Annotate WAA recordings with VLM to produce structured demo traces.

    Args:
        recordings: Directory containing task recording subdirectories.
        output: Output directory for annotated demo JSON/TXT files.
        provider: VLM provider ("openai", "anthropic", "google").
        model: Model override (default: provider's default).
        api_key: API key override.
    """
    from PIL import Image

    from openadapt_ml.experiments.demo_prompt.annotate import (
        ANNOTATION_STEP_PROMPT,
        ANNOTATION_SYSTEM_PROMPT,
        AnnotatedDemo,
        AnnotatedStep,
        _parse_annotation_response,
        format_annotated_demo,
        validate_annotations,
    )
    from openadapt_ml.models.providers import get_provider

    recordings_dir = Path(recordings)
    output_dir = Path(output)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Find task directories with meta.json
    task_dirs = sorted(
        d for d in recordings_dir.iterdir()
        if d.is_dir() and (d / "meta.json").exists()
    )

    if not task_dirs:
        print(f"No recordings found in {recordings_dir}")
        return

    print(f"Found {len(task_dirs)} recording(s) to annotate")
    print(f"Provider: {provider}, Model: {model or 'default'}\n")

    prov = get_provider(provider)
    if api_key is None:
        api_key = prov.get_api_key()
    client = prov.create_client(api_key)
    resolved_model = model or prov.default_model

    for task_dir in task_dirs:
        meta = json.loads((task_dir / "meta.json").read_text(encoding="utf-8"))
        task_id = meta["task_id"]
        instruction = meta["instruction"]
        num_steps = meta["num_steps"]

        print(f"{'=' * 60}")
        print(f"Annotating: {task_id[:40]}... ({num_steps} steps)")
        print(f"{'=' * 60}")

        annotated_steps = []
        prev_annotation = None

        for i in range(num_steps):
            before_path = task_dir / f"step_{i:02d}_before.png"
            after_path = task_dir / f"step_{i:02d}_after.png"

            if not before_path.exists():
                print(f"  Step {i}: missing before screenshot, skipping")
                continue

            img_before = Image.open(before_path)
            img_after = Image.open(after_path) if after_path.exists() else None

            # Build action_raw from hints if available
            step_meta = meta.get("steps", [{}])
            action_hint = ""
            if i < len(step_meta):
                action_hint = step_meta[i].get("action_hint") or ""
            action_raw = action_hint or f"(user action at step {i + 1})"

            # Build previous context
            previous_context = ""
            if prev_annotation is not None:
                previous_context = (
                    f"Previous step: {prev_annotation.action}\n"
                    f"Previous result: {prev_annotation.result_observation}\n"
                )

            no_after_note = ""
            if img_after is None:
                no_after_note = (
                    " (No AFTER image available — describe expected result only.)"
                )

            prompt_text = ANNOTATION_STEP_PROMPT.format(
                instruction=instruction,
                step_num=i + 1,
                total_steps=num_steps,
                action_raw=action_raw,
                previous_context=previous_context,
                no_after_note=no_after_note,
            )

            # Build content blocks with images
            content = [
                {"type": "text", "text": prompt_text},
                {"type": "text", "text": "BEFORE image:"},
                prov.encode_image(img_before),
            ]
            if img_after is not None:
                content.append({"type": "text", "text": "AFTER image:"})
                content.append(prov.encode_image(img_after))

            print(f"  Step {i + 1}/{num_steps}...", end=" ", flush=True)

            try:
                response = prov.send_message(
                    client,
                    model=resolved_model,
                    system=ANNOTATION_SYSTEM_PROMPT,
                    content=content,
                    max_tokens=512,
                    temperature=0.1,
                )
                parsed = _parse_annotation_response(response)
            except Exception as e:
                print(f"error: {e}")
                parsed = {
                    "observation": "",
                    "intent": "",
                    "action": action_raw,
                    "result_observation": "",
                    "expected_result": "",
                }

            annotated = AnnotatedStep(
                step_index=i,
                timestamp_ms=None,
                observation=parsed.get("observation", ""),
                intent=parsed.get("intent", ""),
                action=parsed.get("action", action_raw),
                action_raw=action_raw,
                action_px=None,
                result_observation=parsed.get("result_observation", ""),
                expected_result=parsed.get("expected_result", ""),
            )
            annotated_steps.append(annotated)
            prev_annotation = annotated
            print("done")

        demo = AnnotatedDemo(
            schema_version="0.1",
            task_id=task_id,
            instruction=instruction,
            source="recorded",
            annotator={"provider": provider, "model": resolved_model},
            recording_meta={
                "platform": "windows",
                "screen_px": None,
                "source": "waa_api_recording",
                "raw_step_count": num_steps,
                "annotated_step_count": len(annotated_steps),
            },
            steps=annotated_steps,
        )

        # Save JSON
        json_path = output_dir / f"{task_id}.json"
        demo.save(json_path)

        # Save formatted text for eval-suite
        txt = format_annotated_demo(demo, compact=True)
        txt_path = output_dir / f"{task_id}.txt"
        txt_path.write_text(txt, encoding="utf-8")

        # Validate
        warnings = validate_annotations(demo)
        if warnings:
            print(f"  Warnings ({len(warnings)}):")
            for w in warnings:
                print(f"    - {w}")
        else:
            print("  Validation: all checks passed")

        print(f"  -> {json_path}")
        print(f"  -> {txt_path}\n")

    print_header("Annotation Summary")
    print(f"  Annotated: {len(task_dirs)} recording(s)")
    print(f"  Output: {output_dir}")
    print(
        f"\n  Next: python {__file__} eval "
        f"--demo_dir {output_dir} --tasks <task_ids>"
    )


# ---------------------------------------------------------------------------
# Demo-conditioned eval (delegates to eval-suite)
# ---------------------------------------------------------------------------


def cmd_eval_dc(
    demo_dir: str = "annotated_demos",
    tasks: str = ",".join(HARDER_TASK_IDS),
    agent: str = "api-openai",
    server: str = "http://localhost:5001",
    evaluate_url: str = "http://localhost:5050",
    max_steps: int = 15,
    output: str = "benchmark_results",
    suite_name: str | None = None,
) -> None:
    """Run demo-conditioned evaluation using eval-suite.

    Args:
        demo_dir: Directory with annotated demos (.json/.txt files).
        tasks: Comma-separated task IDs.
        agent: Agent type (api-openai, api-claude, api-claude-cu, qwen3vl).
        server: WAA server URL.
        evaluate_url: Evaluate server URL.
        max_steps: Maximum steps per task.
        output: Output directory for benchmark results.
        suite_name: Suite name prefix (default: auto-generated timestamp).
    """
    cmd = [
        sys.executable, "-m", "openadapt_evals.benchmarks.cli",
        "eval-suite",
        "--tasks", tasks,
        "--demo-dir", str(Path(demo_dir).resolve()),
        "--agent", agent,
        "--server", server,
        "--evaluate-url", evaluate_url,
        "--max-steps", str(max_steps),
        "--output", output,
        "--no-pool-create",
        "--no-pool-cleanup",
    ]
    if suite_name:
        cmd.extend(["--suite-name", suite_name])

    print(f"Running eval-suite with demo-conditioned demos from {demo_dir}")
    print(f"Command: {' '.join(cmd)}\n")

    result = subprocess.run(cmd)
    if result.returncode != 0:
        sys.exit(result.returncode)


if __name__ == "__main__":
    import fire

    fire.Fire({
        "record": main,
        "record-waa": cmd_record_waa,
        "annotate": cmd_annotate_waa,
        "eval": cmd_eval_dc,
    })
