"""Prompt construction and VLM output parsing for GRPO training.

Copies SYSTEM_PROMPT from openadapt-ml next_action.py so GRPO
operates in the same prompt distribution as SFT. NO openadapt-ml imports.
"""

from __future__ import annotations

import json as _json
import logging
import re
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)
DEFAULT_SCREEN_SIZE: tuple[int, int] = (1920, 1080)

# Copied from openadapt_ml.datasets.next_action.SYSTEM_PROMPT
SYSTEM_PROMPT = (
    "You are a GUI automation agent. Given a screenshot and a user goal, "
    "predict the single next action.\n\n"
    "COORDINATE SYSTEM:\n"
    "- x=0.0 is the LEFT edge, x=1.0 is the RIGHT edge\n"
    "- y=0.0 is the TOP edge, y=1.0 is the BOTTOM edge\n"
    "- To click the CENTER of an element, estimate its center position "
    "as a fraction of screen width/height\n"
    "- Example: An element in the middle of the screen would be "
    "approximately x=0.5, y=0.5\n\n"
    "ALLOWED ACTIONS (use exactly this format):\n"
    "- CLICK(x=0.XX, y=0.XX)  \u2192 click at normalized coordinates\n"
    '- TYPE(text="...")     \u2192 type text into the currently focused field\n'
    "- WAIT()                 \u2192 wait for UI to update\n"
    "- DONE()                 \u2192 task is complete\n\n"
    "RESPONSE FORMAT (required):\n"
    "Thought: [Brief reasoning: what element to interact with and why]\n"
    "Action: [Exactly one action, e.g., CLICK(x=0.35, y=0.42)]\n\n"
    "IMPORTANT: Output coordinates with 2 decimal places. "
    "Estimate the center of target elements."
)


@dataclass
class SimpleAction:
    """Lightweight action (no openadapt-ml dependency)."""

    type: str = "done"
    x: float | None = None
    y: float | None = None
    text: str | None = None
    key: str | None = None


def build_agent_messages(
    instruction: str, *, include_image: bool = False, action_history: str = "",
) -> list[dict]:
    """Build chat messages matching the SFT prompt format."""
    history_text = f"{action_history}\n" if action_history else ""
    text_content = (
        f"Goal: {instruction}\n\n{history_text}"
        "Look at the screenshot and determine the NEXT action.\n\n"
        "Thought: [what element to interact with and why]\n"
        'Action: [CLICK(x=..., y=...) or TYPE(text="...") or WAIT() or DONE()]'
    )
    if include_image:
        user_content: Any = [
            {"type": "image"},
            {"type": "text", "text": text_content},
        ]
    else:
        user_content = text_content
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_content},
    ]


def parse_vlm_output_to_action(
    text: str, screen_size: tuple[int, int] = DEFAULT_SCREEN_SIZE,
) -> SimpleAction:
    """Parse VLM output to SimpleAction. Supports Thought/Action, bare DSL, and JSON."""
    text = text.strip()
    width, height = screen_size
    logger.debug("Parsing VLM output (%d chars): %.200s", len(text), text)

    # Extract from "Action: ..." format
    action_match = re.search(r"Action:\s*(.+)", text, re.IGNORECASE)
    if action_match:
        text = action_match.group(1).strip()

    # JSON: {"action_type": "click", "coordinate": [x, y]}
    json_match = re.search(r'\{[^}]*"action_type"[^}]*\}', text)
    if json_match:
        try:
            d = _json.loads(json_match.group())
            atype = d.get("action_type", "").lower()
            coord = d.get("coordinate", d.get("coords", []))
            if atype == "click" and len(coord) >= 2:
                xv, yv = float(coord[0]), float(coord[1])
                if xv <= 1.0 and yv <= 1.0:
                    xv, yv = xv * width, yv * height
                return SimpleAction(type="click", x=int(xv), y=int(yv))
            if atype == "type":
                return SimpleAction(type="type", text=d.get("text", ""))
            if atype in ("done", "wait"):
                return SimpleAction(type=atype)
        except Exception:
            pass

    # CLICK(x=..., y=...)
    m = re.search(r"CLICK\(x=(-?[\d.]+),\s*y=(-?[\d.]+)\)", text, re.IGNORECASE)
    if m:
        try:
            xf = max(0.0, min(1.0, float(m.group(1))))
            yf = max(0.0, min(1.0, float(m.group(2))))
            return SimpleAction(type="click", x=int(xf * width), y=int(yf * height))
        except (ValueError, OverflowError):
            logger.warning("Malformed CLICK coords: x=%s y=%s", m.group(1), m.group(2))

    # TYPE(text="...")
    m = re.search(r"""TYPE\(text=["']([^"'\\]*(?:\\.[^"'\\]*)*)["']\)""", text, re.IGNORECASE)
    if m:
        t = m.group(1).replace("\\\\", "\\").replace('\\"', '"').replace("\\'", "'")
        return SimpleAction(type="type", text=t)

    if re.search(r"\bWAIT\s*\(\s*\)", text, re.IGNORECASE):
        return SimpleAction(type="wait")
    if re.search(r"\bDONE\s*\(\s*\)", text, re.IGNORECASE):
        return SimpleAction(type="done")

    logger.warning("Could not parse VLM output: %s. Defaulting to DONE.", text)
    return SimpleAction(type="done")


def format_action_as_text(
    action: SimpleAction, screen_size: tuple[int, int] = DEFAULT_SCREEN_SIZE,
) -> str:
    """Convert SimpleAction to DSL text for log-prob computation."""
    width, height = screen_size
    if action.type == "click":
        xf = (action.x or 0) / width if width > 0 else 0.0
        yf = (action.y or 0) / height if height > 0 else 0.0
        return f"CLICK(x={xf:.2f}, y={yf:.2f})"
    if action.type == "type":
        escaped = (action.text or "").replace("\\", "\\\\").replace('"', '\\"')
        return f'TYPE(text="{escaped}")'
    if action.type == "wait":
        return "WAIT()"
    return "DONE()"
