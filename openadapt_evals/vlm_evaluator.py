"""VLM-based screenshot evaluation for custom task checks.

Uses a vision-language model to judge whether a screenshot shows
that a condition is met. This is less precise than programmatic
checks but much easier to define — users write one sentence instead
of PowerShell commands.

Usage:
    from openadapt_evals.vlm_evaluator import vlm_judge

    success, confidence = vlm_judge(
        screenshot_bytes,
        "Cell A1 shows text formatted in Arial font",
    )
"""

from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

_JUDGE_PROMPT = """\
Look at this screenshot carefully.

Does this screenshot show that the following condition is met?

Condition: {description}

Important context: Windows 11 applications may look different from their classic \
versions. For example, Notepad in Windows 11 has a modern UI with tabs, a \
dark/light theme, and rounded corners — it no longer has the classic menu bar \
or title-bar icon. It is still Notepad. Similarly, other built-in Windows apps \
(Calculator, Paint, Settings, etc.) have been redesigned with modern styling. \
Judge based on functionality and content, not on visual appearance matching \
a specific OS version.

Respond in this exact JSON format:
{{"verdict": "YES" or "NO", "confidence": 0.0 to 1.0, "explanation": "brief reason"}}

Respond with ONLY the JSON object."""


def vlm_judge(
    screenshot: bytes,
    description: str,
    model: str = "gpt-4.1-mini",
    provider: str = "openai",
) -> tuple[bool, float]:
    """Judge whether a screenshot satisfies a condition.

    Args:
        screenshot: PNG screenshot bytes.
        description: Natural language condition to check.
        model: VLM model name.
        provider: VLM provider ("openai" or "anthropic").

    Returns:
        Tuple of (success: bool, confidence: float).
    """
    from openadapt_evals.vlm import vlm_call

    prompt = _JUDGE_PROMPT.format(description=description)
    response = vlm_call(
        prompt,
        images=[screenshot],
        model=model,
        provider=provider,
        max_tokens=256,
        temperature=0.1,
    )

    try:
        import re

        match = re.search(r"\{[^}]+\}", response, re.DOTALL)
        if match:
            data = json.loads(match.group())
        else:
            data = json.loads(response)

        verdict = str(data.get("verdict", "NO")).upper().startswith("Y")
        confidence = float(data.get("confidence", 0.5))
        explanation = data.get("explanation", "")
        logger.info(
            "VLM judge: %s (confidence=%.2f) — %s",
            "PASS" if verdict else "FAIL",
            confidence,
            explanation[:80],
        )
        return verdict, confidence

    except (json.JSONDecodeError, ValueError, KeyError):
        # Fallback: check if response starts with YES
        verdict = response.strip().upper().startswith("YES")
        logger.warning("VLM judge JSON parse failed, fallback: %s", verdict)
        return verdict, 0.5
