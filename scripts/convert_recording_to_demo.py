#!/usr/bin/env python3
"""Convert WAA recordings (meta.json + screenshots) to demo text files.

Produces demo .txt files in the format expected by eval-suite's --demo-dir.

Two modes:
  --mode text   : Fast, free. Converts step descriptions from meta.json directly.
  --mode vlm    : Richer. Sends screenshots to a VLM for Observation/Intent/Action/Result.

Usage:
    # Text-only (instant, no API calls)
    python scripts/convert_recording_to_demo.py \
        --recordings waa_recordings \
        --output demo_prompts \
        --mode text

    # VLM-enriched (sends screenshots to OpenAI/Anthropic)
    python scripts/convert_recording_to_demo.py \
        --recordings waa_recordings \
        --output demo_prompts \
        --mode vlm \
        --provider openai
"""
from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def convert_text(meta: dict) -> str:
    """Convert recording meta.json to demo text using step descriptions only."""
    instruction = meta["instruction"]
    steps = meta.get("steps", [])

    lines = [
        "DEMONSTRATION:",
        f"Task: {instruction}",
        "",
    ]

    for i, step in enumerate(steps):
        desc = step.get("suggested_step", f"(step {i + 1})")
        lines.append(f"Step {i + 1}:")
        lines.append(f"  Action: {desc}")
        lines.append("")

    lines.append("---")
    return "\n".join(lines)


def convert_vlm(
    meta: dict,
    task_dir: Path,
    provider: str = "openai",
    model: str | None = None,
) -> str:
    """Convert recording to demo text using VLM to describe screenshots."""
    instruction = meta["instruction"]
    steps = meta.get("steps", [])
    num_steps = meta.get("num_steps", len(steps))

    lines = [
        "DEMONSTRATION:",
        f"Task: {instruction}",
        "",
    ]

    for i in range(num_steps):
        step_desc = steps[i].get("suggested_step", "") if i < len(steps) else ""
        before_path = task_dir / f"step_{i:02d}_before.png"
        after_path = task_dir / f"step_{i:02d}_after.png"

        if not before_path.exists():
            # Fallback to text-only for this step
            lines.append(f"Step {i + 1}:")
            lines.append(f"  Action: {step_desc}")
            lines.append("")
            continue

        print(f"  Step {i + 1}/{num_steps}...", end=" ", flush=True)

        # Build VLM prompt
        images = [_encode_image(before_path)]
        has_after = after_path.exists()
        if has_after:
            images.append(_encode_image(after_path))

        prompt = (
            f"You are annotating step {i + 1} of {num_steps} in a desktop task demonstration.\n"
            f"Task: {instruction}\n"
            f"Recorded action: {step_desc}\n\n"
            f"{'The first image is BEFORE the action, the second is AFTER.' if has_after else 'This image shows the screen BEFORE the action.'}\n\n"
            f"Provide a concise annotation with exactly these fields:\n"
            f"Observation: (what the screen shows before the action, ~1 sentence)\n"
            f"Intent: (why this action is being taken, ~1 sentence)\n"
            f"Action: (the specific action taken — e.g. CLICK, TYPE, KEY, DRAG)\n"
            f"Result: (what changed after the action, ~1 sentence)\n\n"
            f"Be specific about UI elements, cell references, and values visible on screen."
        )

        try:
            annotation = _vlm_call(prompt, images, provider, model)
            lines.append(f"Step {i + 1}:")
            # Parse the annotation — it should have Observation/Intent/Action/Result lines
            for line in annotation.strip().split("\n"):
                line = line.strip()
                if line:
                    lines.append(f"  {line}")
            lines.append("")
            print("done")
        except Exception as e:
            print(f"error: {e}")
            # Fallback to text-only
            lines.append(f"Step {i + 1}:")
            lines.append(f"  Action: {step_desc}")
            lines.append("")

    lines.append("---")
    return "\n".join(lines)


def _encode_image(path: Path) -> str:
    """Read an image file and return base64-encoded string."""
    return base64.b64encode(path.read_bytes()).decode("utf-8")


def _vlm_call(
    prompt: str,
    images_b64: list[str],
    provider: str = "openai",
    model: str | None = None,
) -> str:
    """Send a prompt with images to a VLM and return the response text."""
    if provider == "openai":
        return _vlm_call_openai(prompt, images_b64, model or "gpt-4.1-mini")
    elif provider in ("anthropic", "claude"):
        return _vlm_call_anthropic(prompt, images_b64, model or "claude-sonnet-4-20250514")
    else:
        raise ValueError(f"Unsupported provider: {provider}")


def _vlm_call_openai(prompt: str, images_b64: list[str], model: str) -> str:
    import openai

    content: list[dict] = [{"type": "text", "text": prompt}]
    for img in images_b64:
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/png;base64,{img}", "detail": "low"},
        })

    client = openai.OpenAI()
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": content}],
        max_tokens=400,
        temperature=0.1,
    )
    return resp.choices[0].message.content


def _vlm_call_anthropic(prompt: str, images_b64: list[str], model: str) -> str:
    import anthropic

    content: list[dict] = [{"type": "text", "text": prompt}]
    for img in images_b64:
        content.append({
            "type": "image",
            "source": {"type": "base64", "media_type": "image/png", "data": img},
        })

    client = anthropic.Anthropic()
    resp = client.messages.create(
        model=model,
        messages=[{"role": "user", "content": content}],
        max_tokens=400,
        temperature=0.1,
    )
    return resp.content[0].text


def main(
    recordings: str = "waa_recordings",
    output: str = "demo_prompts",
    mode: str = "text",
    provider: str = "openai",
    model: str | None = None,
    task: str | None = None,
) -> None:
    """Convert WAA recordings to demo text files.

    Args:
        recordings: Directory containing recording subdirectories.
        output: Output directory for demo .txt files.
        mode: "text" (free, instant) or "vlm" (richer, uses API).
        provider: VLM provider for vlm mode ("openai" or "anthropic").
        model: Model override.
        task: Specific task ID prefix to convert (default: all).
    """
    recordings_dir = Path(recordings)
    output_dir = Path(output)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Find task directories with meta.json
    task_dirs = sorted(
        d for d in recordings_dir.iterdir()
        if d.is_dir() and (d / "meta.json").exists()
    )

    if task:
        task_dirs = [d for d in task_dirs if d.name.startswith(task)]

    if not task_dirs:
        print(f"No recordings found in {recordings_dir}")
        sys.exit(1)

    print(f"Converting {len(task_dirs)} recording(s) to demo text (mode={mode})")
    print()

    for task_dir in task_dirs:
        meta = json.loads((task_dir / "meta.json").read_text(encoding="utf-8"))
        task_id = meta["task_id"]
        num_steps = meta.get("num_steps", len(meta.get("steps", [])))

        print(f"{'=' * 60}")
        print(f"Task: {task_id[:40]}... ({num_steps} steps)")
        print(f"{'=' * 60}")

        if mode == "vlm":
            demo_text = convert_vlm(meta, task_dir, provider, model)
        else:
            demo_text = convert_text(meta)

        txt_path = output_dir / f"{task_id}.txt"
        txt_path.write_text(demo_text, encoding="utf-8")
        print(f"  -> {txt_path}")
        print()

    print("Done. Use with eval-suite:")
    print(f"  openadapt-evals eval-suite --demo-dir {output_dir} --tasks ...")


if __name__ == "__main__":
    import fire

    fire.Fire(main)
