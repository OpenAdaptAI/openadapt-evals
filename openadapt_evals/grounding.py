"""Grounding data model and state verification for the DemoExecutor cascade.

Defines GroundingTarget (stored per click step in demo) and
GroundingCandidate (produced by each tier during grounding).

Also provides state-narrowing functions (Phase 4 of the cascade):
- ``check_state_preconditions``: verify the screen matches expectations
  before grounding a click.
- ``verify_transition``: verify the expected state change occurred after
  clicking.

See docs/design/grounding_cascade_design_v3.md for the full architecture.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)


@dataclass
class GroundingTarget:
    """Rich target representation stored per click step in a demo.

    This is the core data model that enables every tier in the cascade.
    Without it, each tier infers from a weak description string.
    """

    # What the target is
    description: str = ""
    target_type: str = ""  # "button" | "icon" | "checkbox" | "tab" | "text_field"

    # Visual evidence (from demo screenshot)
    crop_path: str = ""  # relative path to PNG crop of target element
    crop_bbox: tuple[int, int, int, int] | None = None  # [x1,y1,x2,y2] in demo frame
    click_offset: tuple[int, int] | None = None  # click point relative to crop top-left

    # Text context
    nearby_text: list[str] = field(default_factory=list)
    window_title: str = ""
    surrounding_labels: list[str] = field(default_factory=list)

    # Transition evidence (file references)
    screenshot_before_path: str = ""
    screenshot_after_path: str = ""

    # Structured transition expectations (machine-checkable)
    disappearance_text: list[str] = field(default_factory=list)
    appearance_text: list[str] = field(default_factory=list)
    window_title_change: str | None = None
    region_changed: tuple[int, int, int, int] | None = None
    modal_toggled: bool | None = None

    # Human-readable (logging/debugging)
    expected_change: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Serialize for demo JSON storage."""
        d: dict[str, Any] = {}
        for k, v in self.__dict__.items():
            if v is not None and v != "" and v != [] and v != ():
                d[k] = v
        return d

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> GroundingTarget:
        """Deserialize from demo JSON."""
        kwargs = {}
        for f in cls.__dataclass_fields__:
            if f in data:
                val = data[f]
                # Convert lists to tuples for bbox fields
                if f in ("crop_bbox", "click_offset", "region_changed") and isinstance(val, list):
                    val = tuple(val)
                kwargs[f] = val
        return cls(**kwargs)


@dataclass
class GroundingCandidate:
    """A candidate click location produced by a grounding tier.

    All tiers normalize their output into this type. Selection logic
    operates on a list of candidates, not on tier-specific return types.
    """

    source: str  # "a11y" | "ocr" | "clip" | "ui_venus" | "gpt54"
    point: tuple[int, int]  # (x, y) pixel coordinates
    bbox: tuple[int, int, int, int] | None = None
    local_score: float = 0.0  # tier-local confidence (not comparable across tiers)
    matched_text: str | None = None
    reasoning: str | None = None
    spatial_score: float | None = None  # consistency with demo position
    visual_verify_score: float | None = None  # crop resemblance to target
    accepted: bool = False


# ---------------------------------------------------------------------------
# Phase 4: State narrowing -- pre-click and post-click verification
# ---------------------------------------------------------------------------


def _text_present(
    query: str,
    ocr_results: list[dict],
    case_sensitive: bool = False,
) -> bool:
    """Check whether *query* appears in any OCR result text.

    Args:
        query: Text to search for.
        ocr_results: List of dicts with at least a ``"text"`` key.
        case_sensitive: Whether the comparison is case-sensitive.

    Returns:
        ``True`` if *query* is a substring of any OCR result text.
    """
    if not case_sensitive:
        query = query.lower()
    for item in ocr_results:
        text = item.get("text", "")
        if not case_sensitive:
            text = text.lower()
        if query in text:
            return True
    return False


def check_state_preconditions(
    screenshot: bytes,
    target: GroundingTarget,
    ocr_fn: Callable[[bytes], list[dict]] | None = None,
) -> tuple[bool, str]:
    """Check if the current screen state matches the demo's expectations.

    This is the "state narrowing" step that runs *before* candidate
    generation.  It is cheaper to detect "wrong screen" than to ground
    on it -- see the Phase 4 rationale in
    ``docs/design/grounding_cascade_design_v3.md``.

    Args:
        screenshot: Current screenshot PNG bytes.
        target: :class:`GroundingTarget` with ``window_title``,
            ``nearby_text``, ``surrounding_labels``, etc.
        ocr_fn: Optional OCR function that accepts PNG bytes and returns
            ``list[dict]`` where each dict has at least a ``"text"`` key
            (and optionally ``"bbox"``).  When *None*, precondition
            checks that require OCR are skipped gracefully.

    Returns:
        ``(preconditions_met, reason)`` -- ``True`` if safe to proceed
        with grounding, ``False`` with a human-readable reason string if
        state recovery is needed.
    """
    has_expectations = bool(
        target.window_title
        or target.nearby_text
        or target.surrounding_labels
    )

    # No text expectations on this target -- nothing to check.
    if not has_expectations:
        return True, "no text preconditions defined on target"

    # OCR unavailable -- skip gracefully (Phase 5 adds real OCR).
    if ocr_fn is None:
        return True, "no OCR available, skipping precondition check"

    ocr_results = ocr_fn(screenshot)

    # 1. Window title check
    if target.window_title:
        if not _text_present(target.window_title, ocr_results):
            return (
                False,
                f"window title mismatch: expected {target.window_title!r}",
            )

    # 2. Nearby text -- require at least half to be present
    if target.nearby_text:
        found = sum(
            1 for t in target.nearby_text if _text_present(t, ocr_results)
        )
        threshold = max(1, len(target.nearby_text) // 2)
        if found < threshold:
            return (
                False,
                f"nearby text mismatch: found {found}/{len(target.nearby_text)}"
                f" (need >= {threshold})",
            )

    # 3. Surrounding labels -- require at least half to be present
    if target.surrounding_labels:
        found = sum(
            1
            for t in target.surrounding_labels
            if _text_present(t, ocr_results)
        )
        threshold = max(1, len(target.surrounding_labels) // 2)
        if found < threshold:
            return (
                False,
                f"surrounding labels mismatch: found "
                f"{found}/{len(target.surrounding_labels)}"
                f" (need >= {threshold})",
            )

    return True, "preconditions met"


def verify_transition(
    screenshot_after: bytes,
    target: GroundingTarget,
    ocr_fn: Callable[[bytes], list[dict]] | None = None,
) -> tuple[bool, str]:
    """Verify that the click produced the expected state change.

    Uses structured transition expectations from :class:`GroundingTarget`:

    - ``disappearance_text``: text that should *no longer* be visible.
    - ``appearance_text``: text that should *now* be visible.
    - ``window_title_change``: expected new window title.
    - ``modal_toggled``: whether a modal appeared/disappeared (deferred
      until a modal-detection backend is available).

    Args:
        screenshot_after: Screenshot PNG bytes taken after the click.
        target: :class:`GroundingTarget` with structured transition
            expectations.
        ocr_fn: Optional OCR function (same contract as
            :func:`check_state_preconditions`).  When *None*, checks
            that require OCR are skipped gracefully.

    Returns:
        ``(verified, reason)`` -- ``True`` if the transition looks
        correct, ``False`` with a human-readable reason if it looks
        wrong.
    """
    has_expectations = bool(
        target.disappearance_text
        or target.appearance_text
        or target.window_title_change is not None
        or target.modal_toggled is not None
    )

    # No structured transition expectations -- nothing to verify.
    if not has_expectations:
        return True, "no transition expectations defined on target"

    # OCR unavailable -- skip gracefully.
    if ocr_fn is None:
        return True, "no OCR available, skipping transition verification"

    ocr_results = ocr_fn(screenshot_after)

    # 1. Disappearance check -- text should have vanished.
    if target.disappearance_text:
        for text in target.disappearance_text:
            if _text_present(text, ocr_results):
                return (
                    False,
                    f"disappearance_text still present: {text!r}",
                )

    # 2. Appearance check -- text should now be visible.
    if target.appearance_text:
        for text in target.appearance_text:
            if not _text_present(text, ocr_results):
                return (
                    False,
                    f"appearance_text not found: {text!r}",
                )

    # 3. Window title change
    if target.window_title_change is not None:
        if not _text_present(target.window_title_change, ocr_results):
            return (
                False,
                f"window title change not detected: "
                f"expected {target.window_title_change!r}",
            )

    # 4. Modal toggled -- deferred (requires modal detection backend).
    #    Log for observability but do not fail.
    if target.modal_toggled is not None:
        logger.debug(
            "modal_toggled=%s expectation set but no modal detection "
            "backend available -- skipping",
            target.modal_toggled,
        )

    return True, "transition verified"
