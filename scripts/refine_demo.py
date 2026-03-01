#!/usr/bin/env python3
"""Post-process WAA demo recordings to fix annotation mistakes.

Analyses before/after screenshots and step text descriptions using an LLM
to detect and correct errors made during interactive VNC recording (e.g.,
pressing Enter instead of Tab, clicking the wrong cell, extra keystrokes).

Two-pass analysis:
  Pass 1 — Holistic review: full task context sent to the LLM to flag
           problematic steps.
  Pass 2 — Per-step verification: flagged steps analysed individually with
           surrounding context and before/after screenshots.

Results are saved as ``meta_refined.json`` alongside the original
``meta.json`` (which is never modified).

Usage:
    # Refine a single recording
    python scripts/refine_demo.py waa_recordings/04d9aeaf-...-WOS/

    # Refine all recordings
    python scripts/refine_demo.py --all

    # Non-interactive mode (auto-accept all LLM suggestions)
    python scripts/refine_demo.py --auto waa_recordings/04d9aeaf-...-WOS/

    # Dry run (show suggestions without saving)
    python scripts/refine_demo.py --dry-run waa_recordings/04d9aeaf-...-WOS/
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import platform
import subprocess
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

DEFAULT_MODEL = "gpt-4.1-mini"
MAX_TOKENS_HOLISTIC = 4096
MAX_TOKENS_PER_STEP = 1024
# Maximum number of before/after screenshot pairs to include in holistic pass.
# Sending all screenshots for a 20+ step recording would be very expensive;
# we sample evenly to stay within budget while giving the LLM visual context.
HOLISTIC_MAX_SCREENSHOT_PAIRS = 8

REPO_ROOT = Path(__file__).resolve().parent.parent
RECORDINGS_DIR = REPO_ROOT / "waa_recordings"

# ---------------------------------------------------------------------------
# LLM call (consilium with OpenAI fallback)
# ---------------------------------------------------------------------------


def _vlm_call(
    messages: list[dict],
    api_key: str | None = None,
    model: str = DEFAULT_MODEL,
    max_tokens: int = 1024,
    *,
    use_council: bool = True,
) -> str:
    """Send a VLM query, optionally using multi-model consilium council.

    When ``use_council=True`` (default), queries multiple LLMs via consilium
    in Stage-1-only mode (skip_review) for fast multi-model consensus.
    Falls back to single-model OpenAI if consilium is unavailable.
    """
    # Extract system prompt, all text blocks, and images from messages
    system_text = ""
    text_parts: list[str] = []
    image_bytes_list: list[bytes] | None = None
    for msg in messages:
        if msg.get("role") == "system":
            # System prompt — capture separately
            content = msg.get("content", "")
            if isinstance(content, str):
                system_text = content
            continue
        if isinstance(msg.get("content"), list):
            for block in msg["content"]:
                if block.get("type") == "text":
                    text_parts.append(block["text"])
                elif block.get("type") == "image_url":
                    url = block["image_url"]["url"]
                    if url.startswith("data:image/png;base64,"):
                        raw = base64.b64decode(url.split(",", 1)[1])
                        if image_bytes_list is None:
                            image_bytes_list = []
                        image_bytes_list.append(raw)
        elif isinstance(msg.get("content"), str):
            text_parts.append(msg["content"])

    # Combine system prompt + all text blocks into one prompt for consilium
    prompt_text = "\n\n".join(
        ([system_text] if system_text else []) + text_parts
    )

    if use_council:
        try:
            from consilium import council_query

            result = council_query(
                prompt_text,
                images=image_bytes_list,
                skip_review=True,
                budget=0.50,
            )
            return result["final_answer"]
        except ImportError:
            print("  (consilium not installed -- falling back to single-model)")
        except Exception as e:
            print(f"  (consilium failed: {e} -- falling back to single-model)")

    # Fallback: single-model OpenAI call
    if not api_key:
        api_key = os.environ.get("OPENAI_API_KEY", "")
    if not api_key:
        raise RuntimeError(
            "No OPENAI_API_KEY set and consilium unavailable. "
            "Set the OPENAI_API_KEY environment variable or install consilium."
        )

    import requests as _req

    resp = _req.post(
        "https://api.openai.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {api_key}"},
        json={"model": model, "max_tokens": max_tokens, "messages": messages},
        timeout=120,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


# ---------------------------------------------------------------------------
# Screenshot helpers
# ---------------------------------------------------------------------------


def _encode_png_b64(path: Path) -> str | None:
    """Return a data-URI base64 string for a PNG file, or None if missing."""
    if not path.exists():
        return None
    raw = path.read_bytes()
    b64 = base64.b64encode(raw).decode("ascii")
    return f"data:image/png;base64,{b64}"


def _image_content_block(data_uri: str) -> dict:
    """Build an OpenAI-style image_url content block."""
    return {
        "type": "image_url",
        "image_url": {"url": data_uri, "detail": "low"},
    }


# ---------------------------------------------------------------------------
# Prompt templates
# ---------------------------------------------------------------------------

HOLISTIC_SYSTEM_PROMPT = textwrap.dedent("""\
    You are an expert reviewer of GUI automation demo recordings. Each demo
    consists of numbered steps describing actions a human performed on a
    Windows desktop (via VNC). Screenshots before and after each step are
    provided for a sample of steps.

    Your job is to identify steps that appear PROBLEMATIC. Common issues:

    1. WRONG ACTION: Step text says "Press Tab" but the after screenshot shows
       the cursor moved down (Enter was pressed instead). Fix: change text to
       match what actually happened.
    2. WRONG TARGET: Step says "Click cell A1" but the after screenshot shows
       B1 is selected. Fix: correct the cell reference.
    3. REDUNDANT PAIR: Two consecutive steps that should be one, e.g.
       "Click cell A1" then "Type Year" -> combine to "Click cell A1 and type
       'Year'".
    4. NO-OP STEP: A step whose before and after screenshots are virtually
       identical — the action didn't change anything visible. Suggest removal.
    5. EXTRA STEP: An action performed at the end that belongs to the next
       task or was accidental. Suggest removal.
    6. MISSING CONTEXT: Step text is vague ("Click somewhere") when the
       screenshots clearly show a specific target.

    Respond with a JSON array of objects. Each object:
    {
        "step_index": <0-based index>,
        "issue_type": "<one of: wrong_action, wrong_target, redundant_pair, noop, extra, vague, other>",
        "reason": "<brief explanation>"
    }

    If no steps are problematic, return an empty array: []

    Return ONLY valid JSON. No markdown fences. No commentary outside the array.
""")

PER_STEP_SYSTEM_PROMPT = textwrap.dedent("""\
    You are an expert reviewer of a single GUI automation step. You will see:
    - The overall task instruction
    - Context: the previous 2 steps and the next step (if any)
    - The step under review (its text, before screenshot, after screenshot)
    - The issue flagged in holistic review

    Your job: produce a CORRECTED step text that accurately describes what
    happened based on the before/after screenshots. Follow these examples:

    EXAMPLE 1 — Wrong key:
      Original: "Press Tab and type 'FA changes'"
      Before: cursor in cell B1
      After: cursor in cell A2 (moved down, not right)
      Corrected: "Press Enter, click cell B1, and type 'FA changes'"
      Reason: The after screenshot shows the cursor moved down (Enter), not right (Tab).

    EXAMPLE 2 — Wrong cell:
      Original: "Click cell A1 and type 'Year'"
      Before: empty spreadsheet
      After: "Year" appears in B1
      Corrected: "Click cell B1 and type 'Year'"
      Reason: The text ended up in B1, not A1.

    EXAMPLE 3 — Redundant pair:
      Original: "Click cell A1" (step 3) + "Type 'Year'" (step 4)
      Suggestion: Combine into "Click cell A1 and type 'Year'" and mark step 4
        for removal.

    EXAMPLE 4 — No-op:
      Original: "Press Escape"
      Before and after screenshots are identical.
      Corrected: "[REMOVE] Accidental Escape press — no visible effect"
      Reason: Screenshots show no change.

    EXAMPLE 5 — Extra step at end:
      Original: "Click File menu" (last step, but task was already complete)
      Corrected: "[REMOVE] Accidental action after task completion"

    Respond with a JSON object:
    {
        "corrected_step": "<new step text, or '[REMOVE] <reason>' to delete>",
        "reason": "<explanation of what was wrong and how you fixed it>",
        "confidence": <float 0.0-1.0>
    }

    Return ONLY valid JSON. No markdown fences.
""")


# ---------------------------------------------------------------------------
# Pass 1: Holistic review
# ---------------------------------------------------------------------------


def _build_holistic_messages(
    rec_dir: Path,
    meta: dict,
) -> list[dict]:
    """Build the messages array for the holistic review pass."""
    steps = meta["steps"]
    num_steps = meta["num_steps"]
    instruction = meta["instruction"]

    # Build a numbered list of step texts
    step_list = "\n".join(
        f"  [{i:02d}] {s['suggested_step']}" for i, s in enumerate(steps)
    )

    # Sample screenshots evenly across the recording
    sample_indices = _sample_indices(num_steps, HOLISTIC_MAX_SCREENSHOT_PAIRS)

    content_blocks: list[dict] = []
    content_blocks.append(
        {
            "type": "text",
            "text": (
                f"TASK INSTRUCTION:\n{instruction}\n\n"
                f"STEP LIST ({num_steps} steps):\n{step_list}\n\n"
                f"Below are before/after screenshot pairs for a sample of "
                f"steps (indices: {sample_indices}). Use these to verify "
                f"that the step text matches what actually happened on screen."
            ),
        }
    )

    for idx in sample_indices:
        before_uri = _encode_png_b64(rec_dir / f"step_{idx:02d}_before.png")
        after_uri = _encode_png_b64(rec_dir / f"step_{idx:02d}_after.png")
        content_blocks.append(
            {"type": "text", "text": f"\n--- Step [{idx:02d}] ---"}
        )
        content_blocks.append(
            {
                "type": "text",
                "text": f"Text: {steps[idx]['suggested_step']}",
            }
        )
        if before_uri:
            content_blocks.append(
                {"type": "text", "text": "Before:"}
            )
            content_blocks.append(_image_content_block(before_uri))
        if after_uri:
            content_blocks.append(
                {"type": "text", "text": "After:"}
            )
            content_blocks.append(_image_content_block(after_uri))

    return [
        {"role": "system", "content": HOLISTIC_SYSTEM_PROMPT},
        {"role": "user", "content": content_blocks},
    ]


def _sample_indices(total: int, max_samples: int) -> list[int]:
    """Return up to *max_samples* evenly-spaced indices from [0, total)."""
    if total <= max_samples:
        return list(range(total))
    step = total / max_samples
    return sorted(set(int(i * step) for i in range(max_samples)))


def run_holistic_review(
    rec_dir: Path,
    meta: dict,
    *,
    model: str = DEFAULT_MODEL,
    api_key: str | None = None,
    use_council: bool = True,
) -> list[dict]:
    """Pass 1: holistic review. Returns list of flagged steps."""
    messages = _build_holistic_messages(rec_dir, meta)
    print("  Sending holistic review to LLM...")
    raw = _vlm_call(
        messages,
        api_key=api_key,
        model=model,
        max_tokens=MAX_TOKENS_HOLISTIC,
        use_council=use_council,
    )
    # Parse JSON from response (strip markdown fences if present)
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()
    try:
        flagged = json.loads(raw)
    except json.JSONDecodeError:
        print(f"  WARNING: Could not parse holistic review response as JSON.")
        print(f"  Raw response:\n{raw[:500]}")
        return []
    if not isinstance(flagged, list):
        print(f"  WARNING: Expected JSON array, got {type(flagged).__name__}.")
        return []
    # Validate entries
    valid = []
    num_steps = meta["num_steps"]
    for entry in flagged:
        idx = entry.get("step_index")
        if not isinstance(idx, int) or idx < 0 or idx >= num_steps:
            print(f"  WARNING: Ignoring invalid step_index={idx}")
            continue
        valid.append(entry)
    return valid


# ---------------------------------------------------------------------------
# Pass 2: Per-step verification
# ---------------------------------------------------------------------------


def _build_per_step_messages(
    rec_dir: Path,
    meta: dict,
    step_idx: int,
    holistic_flag: dict,
) -> list[dict]:
    """Build messages for per-step verification of a flagged step."""
    steps = meta["steps"]
    instruction = meta["instruction"]
    num_steps = meta["num_steps"]

    # Context: previous 2, current, next 1
    context_lines = []
    for ci in range(max(0, step_idx - 2), min(num_steps, step_idx + 2)):
        marker = " >>>" if ci == step_idx else "    "
        context_lines.append(
            f"{marker} [{ci:02d}] {steps[ci]['suggested_step']}"
        )
    context_text = "\n".join(context_lines)

    content_blocks: list[dict] = []
    content_blocks.append(
        {
            "type": "text",
            "text": (
                f"TASK INSTRUCTION:\n{instruction}\n\n"
                f"SURROUNDING STEPS (>>> marks the step under review):\n"
                f"{context_text}\n\n"
                f"STEP UNDER REVIEW (index {step_idx}):\n"
                f"  Text: {steps[step_idx]['suggested_step']}\n\n"
                f"HOLISTIC REVIEW FLAG:\n"
                f"  Issue type: {holistic_flag.get('issue_type', 'unknown')}\n"
                f"  Reason: {holistic_flag.get('reason', 'N/A')}\n\n"
                f"Below are the before and after screenshots for this step."
            ),
        }
    )

    before_uri = _encode_png_b64(rec_dir / f"step_{step_idx:02d}_before.png")
    after_uri = _encode_png_b64(rec_dir / f"step_{step_idx:02d}_after.png")
    if before_uri:
        content_blocks.append({"type": "text", "text": "BEFORE screenshot:"})
        content_blocks.append(_image_content_block(before_uri))
    else:
        content_blocks.append(
            {"type": "text", "text": "(Before screenshot not available)"}
        )
    if after_uri:
        content_blocks.append({"type": "text", "text": "AFTER screenshot:"})
        content_blocks.append(_image_content_block(after_uri))
    else:
        content_blocks.append(
            {"type": "text", "text": "(After screenshot not available)"}
        )

    return [
        {"role": "system", "content": PER_STEP_SYSTEM_PROMPT},
        {"role": "user", "content": content_blocks},
    ]


def run_per_step_review(
    rec_dir: Path,
    meta: dict,
    step_idx: int,
    holistic_flag: dict,
    *,
    model: str = DEFAULT_MODEL,
    api_key: str | None = None,
    use_council: bool = True,
) -> dict | None:
    """Pass 2: per-step verification. Returns correction dict or None."""
    messages = _build_per_step_messages(rec_dir, meta, step_idx, holistic_flag)
    raw = _vlm_call(
        messages,
        api_key=api_key,
        model=model,
        max_tokens=MAX_TOKENS_PER_STEP,
        use_council=use_council,
    )
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1] if "\n" in raw else raw[3:]
        if raw.endswith("```"):
            raw = raw[:-3]
        raw = raw.strip()
    try:
        correction = json.loads(raw)
    except json.JSONDecodeError:
        print(f"    WARNING: Could not parse per-step response as JSON.")
        print(f"    Raw response:\n{raw[:300]}")
        return None
    if not isinstance(correction, dict):
        print(f"    WARNING: Expected JSON object, got {type(correction).__name__}.")
        return None
    return correction


# ---------------------------------------------------------------------------
# Interactive review
# ---------------------------------------------------------------------------


def _open_image(path: Path) -> None:
    """Open an image file using the platform's default viewer."""
    if not path.exists():
        print(f"    File not found: {path}")
        return
    system = platform.system()
    try:
        if system == "Darwin":
            subprocess.Popen(["open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif system == "Linux":
            subprocess.Popen(["xdg-open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif system == "Windows":
            os.startfile(str(path))  # type: ignore[attr-defined]
        else:
            print(f"    Cannot open images on {system}. Path: {path}")
    except Exception as e:
        print(f"    Failed to open image: {e}")


def interactive_review(
    rec_dir: Path,
    step_idx: int,
    original_text: str,
    correction: dict,
    holistic_flag: dict,
) -> dict:
    """Present a proposed correction to the user for interactive review.

    Returns a decision dict:
        {
            "decision": "accept" | "reject" | "edit",
            "final_text": "<the text to use>",
            "reason": "<LLM reason>",
        }
    """
    corrected_text = correction.get("corrected_step", original_text)
    reason = correction.get("reason", "N/A")
    confidence = correction.get("confidence", 0.0)
    issue_type = holistic_flag.get("issue_type", "unknown")

    print()
    print(f"  --- Step [{step_idx:02d}] ({issue_type}) ---")
    print(f"  Original:   {original_text}")
    print(f"  Suggested:  {corrected_text}")
    print(f"  Reason:     {reason}")
    print(f"  Confidence: {confidence:.0%}")
    print()

    while True:
        choice = input("  [a]ccept / [r]eject / [e]dit / [v]iew screenshots? ").strip().lower()
        if choice in ("a", "accept"):
            return {
                "decision": "accept",
                "final_text": corrected_text,
                "reason": reason,
            }
        elif choice in ("r", "reject"):
            return {
                "decision": "reject",
                "final_text": original_text,
                "reason": reason,
            }
        elif choice in ("e", "edit"):
            custom = input("  Enter corrected text: ").strip()
            if custom:
                return {
                    "decision": "edit",
                    "final_text": custom,
                    "reason": reason,
                }
            else:
                print("  Empty input, try again.")
        elif choice in ("v", "view"):
            before_path = rec_dir / f"step_{step_idx:02d}_before.png"
            after_path = rec_dir / f"step_{step_idx:02d}_after.png"
            print(f"    Opening: {before_path.name}, {after_path.name}")
            _open_image(before_path)
            _open_image(after_path)
        else:
            print("  Invalid choice. Enter a, r, e, or v.")


# ---------------------------------------------------------------------------
# Saving results
# ---------------------------------------------------------------------------


def save_refined_meta(
    rec_dir: Path,
    meta: dict,
    refinements: list[dict],
) -> Path:
    """Write ``meta_refined.json`` with corrections applied.

    Steps marked ``[REMOVE]`` are excluded from the output.  The
    ``step_was_refined`` flag is set to True on modified steps.

    Returns the path to the written file.
    """
    # Index refinements by step index for O(1) lookup
    changes_by_idx: dict[int, dict] = {}
    for r in refinements:
        if r["decision"] != "reject":
            changes_by_idx[r["step_index"]] = r

    new_steps = []
    for i, step in enumerate(meta["steps"]):
        change = changes_by_idx.get(i)
        if change is not None:
            final_text = change["final_text"]
            if final_text.startswith("[REMOVE]"):
                # Skip removed steps
                continue
            new_step = {
                "action_hint": step.get("action_hint"),
                "suggested_step": final_text,
                "step_was_refined": True,
            }
        else:
            new_step = {
                "action_hint": step.get("action_hint"),
                "suggested_step": step["suggested_step"],
                "step_was_refined": step.get("step_was_refined", False),
            }
        new_steps.append(new_step)

    refined_meta = {
        "task_id": meta["task_id"],
        "instruction": meta["instruction"],
        "num_steps": len(new_steps),
        "steps": new_steps,
        "step_plans": meta.get("step_plans", []),
        "server_url": meta.get("server_url", ""),
        "recorded_at": meta.get("recorded_at", ""),
        "refined_at": datetime.now(timezone.utc).isoformat(),
        "original_num_steps": meta["num_steps"],
    }

    out_path = rec_dir / "meta_refined.json"
    out_path.write_text(json.dumps(refined_meta, indent=2), encoding="utf-8")
    return out_path


def save_refinement_log(
    rec_dir: Path,
    flagged: list[dict],
    refinements: list[dict],
    meta: dict,
) -> Path:
    """Write ``refinement_log.json`` with full details of all changes.

    Returns the path to the written file.
    """
    log_entries = []
    for r in refinements:
        idx = r["step_index"]
        original = meta["steps"][idx]["suggested_step"]
        entry = {
            "step_index": idx,
            "original_text": original,
            "issue_type": r.get("issue_type", "unknown"),
            "holistic_reason": r.get("holistic_reason", ""),
            "llm_corrected_text": r.get("llm_corrected_text", ""),
            "llm_reason": r.get("reason", ""),
            "llm_confidence": r.get("confidence", 0.0),
            "decision": r["decision"],
            "final_text": r["final_text"],
        }
        log_entries.append(entry)

    log = {
        "task_id": meta["task_id"],
        "recording_dir": str(rec_dir),
        "refined_at": datetime.now(timezone.utc).isoformat(),
        "total_steps": meta["num_steps"],
        "steps_flagged": len(flagged),
        "steps_accepted": sum(1 for r in refinements if r["decision"] == "accept"),
        "steps_edited": sum(1 for r in refinements if r["decision"] == "edit"),
        "steps_rejected": sum(1 for r in refinements if r["decision"] == "reject"),
        "entries": log_entries,
    }

    out_path = rec_dir / "refinement_log.json"
    out_path.write_text(json.dumps(log, indent=2), encoding="utf-8")
    return out_path


# ---------------------------------------------------------------------------
# Main refinement pipeline
# ---------------------------------------------------------------------------


def refine_recording(
    rec_dir: Path,
    *,
    model: str = DEFAULT_MODEL,
    api_key: str | None = None,
    auto: bool = False,
    dry_run: bool = False,
    use_council: bool = True,
) -> bool:
    """Run the full refinement pipeline on one recording.

    Returns True if refinement completed (even if no changes were made).
    Returns False on error.
    """
    meta_path = rec_dir / "meta.json"
    if not meta_path.exists():
        print(f"  ERROR: {meta_path} not found. Skipping.")
        return False

    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"  ERROR: Failed to read {meta_path}: {e}")
        return False

    if not meta.get("steps"):
        print("  ERROR: No steps found in meta.json. Skipping.")
        return False

    task_id = meta.get("task_id", rec_dir.name)
    num_steps = meta.get("num_steps", len(meta["steps"]))
    instruction = meta.get("instruction", "(no instruction)")

    print(f"\n  Task: {task_id}")
    print(f"  Instruction: {instruction[:100]}{'...' if len(instruction) > 100 else ''}")
    print(f"  Steps: {num_steps}")

    # Check for existing refined meta
    refined_path = rec_dir / "meta_refined.json"
    if refined_path.exists() and not dry_run:
        print(f"  NOTE: meta_refined.json already exists.")
        if not auto:
            choice = input("  Overwrite? [y/N] ").strip().lower()
            if choice not in ("y", "yes"):
                print("  Skipped.")
                return True
        else:
            print("  (--auto: overwriting existing refined meta)")

    # ------------------------------------------------------------------
    # Pass 1: Holistic review
    # ------------------------------------------------------------------
    print("\n  === Pass 1: Holistic Review ===")
    flagged = run_holistic_review(
        rec_dir,
        meta,
        model=model,
        api_key=api_key,
        use_council=use_council,
    )

    if not flagged:
        print("  No problematic steps detected. Recording looks clean.")
        if not dry_run:
            # Save unchanged meta_refined.json to mark as reviewed
            save_refined_meta(rec_dir, meta, [])
            save_refinement_log(rec_dir, [], [], meta)
            print("  Saved meta_refined.json (no changes).")
        return True

    print(f"  Flagged {len(flagged)} step(s):")
    for f in flagged:
        idx = f.get("step_index", "?")
        issue = f.get("issue_type", "unknown")
        reason = f.get("reason", "N/A")
        step_text = meta["steps"][idx]["suggested_step"] if isinstance(idx, int) and idx < num_steps else "?"
        print(f"    [{idx:02d}] ({issue}) {step_text}")
        print(f"         Reason: {reason}")

    # ------------------------------------------------------------------
    # Pass 2: Per-step verification
    # ------------------------------------------------------------------
    print(f"\n  === Pass 2: Per-Step Verification ===")
    refinements: list[dict] = []

    for i, flag in enumerate(flagged):
        step_idx = flag["step_index"]
        original_text = meta["steps"][step_idx]["suggested_step"]
        print(f"\n  Analysing step [{step_idx:02d}] ({i + 1}/{len(flagged)})...")

        correction = run_per_step_review(
            rec_dir,
            meta,
            step_idx,
            flag,
            model=model,
            api_key=api_key,
            use_council=use_council,
        )

        if correction is None:
            print(f"    LLM returned invalid response. Skipping step [{step_idx:02d}].")
            refinements.append(
                {
                    "step_index": step_idx,
                    "issue_type": flag.get("issue_type", "unknown"),
                    "holistic_reason": flag.get("reason", ""),
                    "llm_corrected_text": "",
                    "reason": "LLM response was unparseable",
                    "confidence": 0.0,
                    "decision": "reject",
                    "final_text": original_text,
                }
            )
            continue

        corrected_text = correction.get("corrected_step", original_text)
        reason = correction.get("reason", "N/A")
        confidence = correction.get("confidence", 0.0)

        if dry_run or auto:
            # In dry-run, just display; in auto, accept all
            decision = "accept" if auto else "reject"
            print(f"    Original:  {original_text}")
            print(f"    Suggested: {corrected_text}")
            print(f"    Reason:    {reason}")
            print(f"    Confidence: {confidence:.0%}")
            if dry_run:
                print(f"    (dry-run: not saving)")
                decision = "reject"  # dry-run never actually changes anything

            refinements.append(
                {
                    "step_index": step_idx,
                    "issue_type": flag.get("issue_type", "unknown"),
                    "holistic_reason": flag.get("reason", ""),
                    "llm_corrected_text": corrected_text,
                    "reason": reason,
                    "confidence": confidence,
                    "decision": decision,
                    "final_text": corrected_text if decision == "accept" else original_text,
                }
            )
        else:
            # Interactive review
            review = interactive_review(
                rec_dir, step_idx, original_text, correction, flag,
            )
            refinements.append(
                {
                    "step_index": step_idx,
                    "issue_type": flag.get("issue_type", "unknown"),
                    "holistic_reason": flag.get("reason", ""),
                    "llm_corrected_text": corrected_text,
                    "reason": reason,
                    "confidence": confidence,
                    "decision": review["decision"],
                    "final_text": review["final_text"],
                }
            )

    # ------------------------------------------------------------------
    # Summary and save
    # ------------------------------------------------------------------
    accepted = sum(1 for r in refinements if r["decision"] == "accept")
    edited = sum(1 for r in refinements if r["decision"] == "edit")
    rejected = sum(1 for r in refinements if r["decision"] == "reject")
    removals = sum(
        1
        for r in refinements
        if r["decision"] != "reject" and r["final_text"].startswith("[REMOVE]")
    )

    print(f"\n  === Summary ===")
    print(f"  Flagged: {len(flagged)}  |  Accepted: {accepted}  |  Edited: {edited}  |  Rejected: {rejected}")
    if removals:
        print(f"  Steps marked for removal: {removals}")

    if dry_run:
        print("  (dry-run: no files written)")
        return True

    meta_out = save_refined_meta(rec_dir, meta, refinements)
    log_out = save_refinement_log(rec_dir, flagged, refinements, meta)
    print(f"  Wrote: {meta_out.name}")
    print(f"  Wrote: {log_out.name}")

    return True


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def find_all_recordings(base_dir: Path) -> list[Path]:
    """Find all recording directories containing meta.json."""
    recordings = []
    if not base_dir.exists():
        return recordings
    for child in sorted(base_dir.iterdir()):
        if child.is_dir() and (child / "meta.json").exists():
            recordings.append(child)
    return recordings


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Post-process WAA demo recordings to fix annotation mistakes.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent("""\
            Examples:
              python scripts/refine_demo.py waa_recordings/04d9aeaf-.../
              python scripts/refine_demo.py --all
              python scripts/refine_demo.py --auto waa_recordings/04d9aeaf-.../
              python scripts/refine_demo.py --dry-run --all
        """),
    )
    parser.add_argument(
        "recording_dir",
        nargs="?",
        type=Path,
        help="Path to a single recording directory (containing meta.json).",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help=f"Process all recordings in {RECORDINGS_DIR}.",
    )
    parser.add_argument(
        "--auto",
        action="store_true",
        help="Non-interactive mode: auto-accept all LLM suggestions.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show suggestions without saving any files.",
    )
    parser.add_argument(
        "--model",
        type=str,
        default=DEFAULT_MODEL,
        help=f"LLM model to use (default: {DEFAULT_MODEL}).",
    )
    parser.add_argument(
        "--no-council",
        action="store_true",
        help="Disable consilium multi-model council; use single-model OpenAI only.",
    )
    parser.add_argument(
        "--recordings-dir",
        type=Path,
        default=RECORDINGS_DIR,
        help=f"Base directory for --all mode (default: {RECORDINGS_DIR}).",
    )
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if not args.recording_dir and not args.all:
        parser.error("Provide a recording directory or use --all.")

    use_council = not args.no_council
    api_key = os.environ.get("OPENAI_API_KEY")

    if args.all:
        recordings = find_all_recordings(args.recordings_dir)
        if not recordings:
            print(f"No recordings found in {args.recordings_dir}")
            return 1
        print(f"Found {len(recordings)} recording(s) in {args.recordings_dir}")
        success = 0
        for i, rec_dir in enumerate(recordings):
            print(f"\n{'=' * 70}")
            print(f"Recording {i + 1}/{len(recordings)}: {rec_dir.name}")
            print("=" * 70)
            ok = refine_recording(
                rec_dir,
                model=args.model,
                api_key=api_key,
                auto=args.auto,
                dry_run=args.dry_run,
                use_council=use_council,
            )
            if ok:
                success += 1
        print(f"\n{'=' * 70}")
        print(f"Done. {success}/{len(recordings)} recording(s) refined.")
        return 0 if success == len(recordings) else 1
    else:
        rec_dir = args.recording_dir.resolve()
        if not rec_dir.is_dir():
            print(f"ERROR: {rec_dir} is not a directory.")
            return 1
        print(f"Refining recording: {rec_dir.name}")
        ok = refine_recording(
            rec_dir,
            model=args.model,
            api_key=api_key,
            auto=args.auto,
            dry_run=args.dry_run,
            use_council=use_council,
        )
        return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
