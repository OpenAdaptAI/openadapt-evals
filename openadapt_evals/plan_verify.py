"""VLM-based step verification for demo-conditioned plan execution.

Provides functions to verify whether individual plan steps, plan progress,
and overall goals have been achieved, by sending screenshots to a cheap VLM
and parsing structured JSON responses.

All verification functions gracefully degrade to "unclear" on VLM failure,
ensuring that the calling controller never crashes due to verification issues.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class VerificationResult:
    """Result of a VLM-based verification check.

    Attributes:
        status: One of ``"verified"``, ``"not_verified"``, or ``"unclear"``.
        confidence: Float between 0.0 and 1.0 indicating VLM confidence.
        explanation: Human-readable reasoning from the VLM.
        raw_response: Full VLM response text, useful for debugging.
    """

    status: str  # "verified", "not_verified", "unclear"
    confidence: float  # 0.0 to 1.0
    explanation: str  # VLM's reasoning
    raw_response: str  # Full VLM response for debugging

    _VALID_STATUSES = frozenset({"verified", "not_verified", "unclear"})

    def __post_init__(self) -> None:
        if self.status not in self._VALID_STATUSES:
            raise ValueError(
                f"Invalid status {self.status!r}; "
                f"must be one of {sorted(self._VALID_STATUSES)}"
            )
        self.confidence = max(0.0, min(1.0, float(self.confidence)))


# ---------------------------------------------------------------------------
# Defaults
# ---------------------------------------------------------------------------

_DEFAULT_MODEL = "gpt-4.1-mini"
_DEFAULT_PROVIDER = "openai"
_DEFAULT_TIMEOUT = 30  # seconds


# ---------------------------------------------------------------------------
# Prompts
# ---------------------------------------------------------------------------

_VERIFY_STEP_SYSTEM = (
    "You are a precise visual verification assistant. "
    "You examine screenshots and determine whether an expected condition is met. "
    "Always respond with valid JSON."
)

_VERIFY_STEP_PROMPT = """\
Look at the screenshot and determine whether the following expectation is met:

EXPECTATION: {expect_text}

Instructions:
1. Describe what you observe in the screenshot that is relevant to the expectation.
2. Compare your observations against the expectation.
3. Decide whether the expectation is met.

Respond with ONLY a JSON object in this exact format (no other text):
{{
  "status": "verified" | "not_verified" | "unclear",
  "confidence": <float between 0.0 and 1.0>,
  "explanation": "<your reasoning>"
}}

Use "verified" if the expectation is clearly met.
Use "not_verified" if the expectation is clearly NOT met.
Use "unclear" if you cannot determine from the screenshot.
"""

_VERIFY_PLAN_PROGRESS_SYSTEM = (
    "You are a precise visual verification assistant. "
    "You examine screenshots and assess plan progress. "
    "Always respond with valid JSON."
)

_VERIFY_PLAN_PROGRESS_PROMPT = """\
Below is a numbered plan of steps. The agent is currently on step {current_step_idx}.
Look at the screenshot and determine which steps appear to have been completed.

PLAN:
{plan_text}

Instructions:
1. Examine the screenshot carefully.
2. For each step, assess whether its expected outcome is visible in the screenshot.
3. Identify which steps appear completed and which step should be executed next.

Respond with ONLY a JSON object in this exact format (no other text):
{{
  "completed_steps": [<list of 0-indexed step numbers that appear done>],
  "current_step": <0-indexed step number to execute next>,
  "confidence": <float between 0.0 and 1.0>
}}
"""

_VERIFY_GOAL_SYSTEM = (
    "You are a precise visual verification assistant. "
    "You examine screenshots and determine whether a high-level goal has been achieved. "
    "Always respond with valid JSON."
)

_VERIFY_GOAL_PROMPT = """\
Look at the screenshot and determine whether the following goal has been fully achieved:

GOAL: {goal_text}

Instructions:
1. Describe the current state visible in the screenshot.
2. Compare the current state against the goal.
3. Decide whether the goal is fully achieved.

Respond with ONLY a JSON object in this exact format (no other text):
{{
  "status": "verified" | "not_verified" | "unclear",
  "confidence": <float between 0.0 and 1.0>,
  "explanation": "<your reasoning>"
}}

Use "verified" only if the goal is FULLY achieved (not partially).
Use "not_verified" if the goal is not yet complete.
Use "unclear" if you cannot determine from the screenshot.
"""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _parse_verification_result(
    raw_response: str,
) -> VerificationResult:
    """Parse a VLM response into a VerificationResult.

    Falls back to ``"unclear"`` if the response cannot be parsed or contains
    invalid values.
    """
    from openadapt_evals.vlm import extract_json

    parsed = extract_json(raw_response)
    if parsed is None or not isinstance(parsed, dict):
        logger.warning(
            "Could not parse VLM response as JSON; falling back to unclear"
        )
        return VerificationResult(
            status="unclear",
            confidence=0.0,
            explanation="Failed to parse VLM response as JSON.",
            raw_response=raw_response,
        )

    status = parsed.get("status", "unclear")
    if status not in VerificationResult._VALID_STATUSES:
        logger.warning(
            "Invalid status %r in VLM response; falling back to unclear",
            status,
        )
        status = "unclear"

    try:
        confidence = float(parsed.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0

    explanation = str(parsed.get("explanation", ""))

    return VerificationResult(
        status=status,
        confidence=confidence,
        explanation=explanation,
        raw_response=raw_response,
    )


def _format_plan_steps(plan_steps: list[str]) -> str:
    """Format plan steps into a numbered list for the prompt."""
    lines = []
    for i, step in enumerate(plan_steps):
        lines.append(f"{i}. {step}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def verify_step(
    screenshot_bytes: bytes,
    expect_text: str,
    *,
    model: str = _DEFAULT_MODEL,
    provider: str = _DEFAULT_PROVIDER,
    timeout: int = _DEFAULT_TIMEOUT,
) -> VerificationResult:
    """Verify whether a single plan step's expectation is met.

    Sends the screenshot and expectation text to a VLM, then parses
    the structured JSON response into a :class:`VerificationResult`.

    Args:
        screenshot_bytes: Raw PNG bytes of the current screen.
        expect_text: The ``[Expect]`` text for the plan step.
        model: VLM model name (default: ``gpt-4.1-mini``).
        provider: VLM provider (default: ``"openai"``).
        timeout: Request timeout in seconds (default: 30).

    Returns:
        A :class:`VerificationResult` with the verification outcome.
        Falls back to ``"unclear"`` on any VLM or parsing failure.
    """
    from openadapt_evals.vlm import vlm_call

    prompt = _VERIFY_STEP_PROMPT.format(expect_text=expect_text)

    try:
        raw_response = vlm_call(
            prompt,
            images=[screenshot_bytes],
            system=_VERIFY_STEP_SYSTEM,
            model=model,
            max_tokens=512,
            temperature=0.1,
            timeout=timeout,
            provider=provider,
        )
    except Exception as exc:
        logger.error("VLM call failed during verify_step: %s", exc)
        return VerificationResult(
            status="unclear",
            confidence=0.0,
            explanation=f"VLM call failed: {exc}",
            raw_response="",
        )

    result = _parse_verification_result(raw_response)
    logger.info(
        "verify_step: status=%s confidence=%.2f explanation=%s",
        result.status,
        result.confidence,
        result.explanation,
    )
    return result


def verify_plan_progress(
    screenshot_bytes: bytes,
    plan_steps: list[str],
    current_step_idx: int,
    *,
    model: str = _DEFAULT_MODEL,
    provider: str = _DEFAULT_PROVIDER,
    timeout: int = _DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """Estimate which plan steps appear complete based on a screenshot.

    Sends the screenshot and full plan to a VLM, asking it to identify
    which steps look completed and what the next step should be.

    Args:
        screenshot_bytes: Raw PNG bytes of the current screen.
        plan_steps: List of plan step descriptions.
        current_step_idx: The 0-indexed step the agent believes it is on.
        model: VLM model name (default: ``gpt-4.1-mini``).
        provider: VLM provider (default: ``"openai"``).
        timeout: Request timeout in seconds (default: 30).

    Returns:
        A dict with keys:
        - ``"completed_steps"``: list of 0-indexed step numbers that
          appear done.
        - ``"current_step"``: 0-indexed step number to execute next.
        - ``"confidence"``: float between 0.0 and 1.0.

        Falls back to a conservative estimate on any failure.
    """
    from openadapt_evals.vlm import vlm_call, extract_json

    plan_text = _format_plan_steps(plan_steps)
    prompt = _VERIFY_PLAN_PROGRESS_PROMPT.format(
        current_step_idx=current_step_idx,
        plan_text=plan_text,
    )

    fallback = {
        "completed_steps": list(range(current_step_idx)),
        "current_step": current_step_idx,
        "confidence": 0.0,
    }

    try:
        raw_response = vlm_call(
            prompt,
            images=[screenshot_bytes],
            system=_VERIFY_PLAN_PROGRESS_SYSTEM,
            model=model,
            max_tokens=512,
            temperature=0.1,
            timeout=timeout,
            provider=provider,
        )
    except Exception as exc:
        logger.error("VLM call failed during verify_plan_progress: %s", exc)
        return fallback

    parsed = extract_json(raw_response)
    if parsed is None or not isinstance(parsed, dict):
        logger.warning(
            "Could not parse VLM response for plan progress; using fallback"
        )
        return fallback

    # Validate and sanitize the parsed response
    completed_steps = parsed.get("completed_steps", [])
    if not isinstance(completed_steps, list):
        completed_steps = []
    # Ensure all entries are valid step indices
    completed_steps = [
        s for s in completed_steps
        if isinstance(s, int) and 0 <= s < len(plan_steps)
    ]

    current_step = parsed.get("current_step", current_step_idx)
    if not isinstance(current_step, int) or not (
        0 <= current_step <= len(plan_steps)
    ):
        current_step = current_step_idx

    try:
        confidence = float(parsed.get("confidence", 0.0))
        confidence = max(0.0, min(1.0, confidence))
    except (TypeError, ValueError):
        confidence = 0.0

    result = {
        "completed_steps": completed_steps,
        "current_step": current_step,
        "confidence": confidence,
    }

    logger.info(
        "verify_plan_progress: completed=%s current=%d confidence=%.2f",
        result["completed_steps"],
        result["current_step"],
        result["confidence"],
    )
    return result


def verify_goal_completion(
    screenshot_bytes: bytes,
    goal_text: str,
    *,
    model: str = _DEFAULT_MODEL,
    provider: str = _DEFAULT_PROVIDER,
    timeout: int = _DEFAULT_TIMEOUT,
) -> VerificationResult:
    """Verify whether the overall goal has been achieved.

    Sends the screenshot and goal text to a VLM for a high-level
    completion check. This is used as the final gate before accepting
    ``"done"`` from the agent.

    Args:
        screenshot_bytes: Raw PNG bytes of the current screen.
        goal_text: The high-level goal statement.
        model: VLM model name (default: ``gpt-4.1-mini``).
        provider: VLM provider (default: ``"openai"``).
        timeout: Request timeout in seconds (default: 30).

    Returns:
        A :class:`VerificationResult` with the verification outcome.
        Falls back to ``"unclear"`` on any VLM or parsing failure.
    """
    from openadapt_evals.vlm import vlm_call

    prompt = _VERIFY_GOAL_PROMPT.format(goal_text=goal_text)

    try:
        raw_response = vlm_call(
            prompt,
            images=[screenshot_bytes],
            system=_VERIFY_GOAL_SYSTEM,
            model=model,
            max_tokens=512,
            temperature=0.1,
            timeout=timeout,
            provider=provider,
        )
    except Exception as exc:
        logger.error("VLM call failed during verify_goal_completion: %s", exc)
        return VerificationResult(
            status="unclear",
            confidence=0.0,
            explanation=f"VLM call failed: {exc}",
            raw_response="",
        )

    result = _parse_verification_result(raw_response)
    logger.info(
        "verify_goal_completion: status=%s confidence=%.2f explanation=%s",
        result.status,
        result.confidence,
        result.explanation,
    )
    return result
