"""Grounding data model and text anchoring for the DemoExecutor cascade.

Defines GroundingTarget (stored per click step in demo) and
GroundingCandidate (produced by each tier during grounding).

Also provides text anchoring (Phase 5 / Tier 1.5a):
- ``run_ocr``: extract text from a screenshot via pytesseract (optional dep).
- ``ground_by_text``: generate grounding candidates by matching OCR text
  against a GroundingTarget description.

See docs/design/grounding_cascade_design_v3.md for the full architecture.
"""

from __future__ import annotations

import logging
import math
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

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
                if f in ("crop_bbox", "click_offset", "region_changed") and isinstance(
                    val, list
                ):
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
# Phase 5 / Tier 1.5a: Text anchoring -- OCR-based candidate generation
# ---------------------------------------------------------------------------


def run_ocr(screenshot: bytes) -> list[dict]:
    """Run OCR on a screenshot, returning text with bounding boxes.

    Uses ``pytesseract`` if available (optional dependency).  When
    pytesseract is not installed, returns an empty list so that the
    caller can gracefully fall back to VLM grounding.

    Args:
        screenshot: PNG bytes of the current screen.

    Returns:
        List of dicts, each with keys:
        - ``"text"`` (str): detected text string.
        - ``"bbox"`` (list[int]): ``[x1, y1, x2, y2]`` in pixels.
        - ``"confidence"`` (float): 0.0 -- 1.0 OCR confidence.
    """
    try:
        import pytesseract  # type: ignore[import-untyped]
        from PIL import Image  # type: ignore[import-untyped]
    except ImportError:
        logger.debug("pytesseract or Pillow not installed -- OCR unavailable")
        return []

    import io

    try:
        img = Image.open(io.BytesIO(screenshot))
        data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT)
    except Exception:
        logger.warning("pytesseract OCR failed", exc_info=True)
        return []

    results: list[dict] = []
    for i, text in enumerate(data["text"]):
        text = text.strip()
        if not text or len(text) < 2:
            continue
        conf = data["conf"][i]
        # pytesseract returns -1 for unreliable entries
        if isinstance(conf, (int, float)) and conf < 0:
            continue
        x = data["left"][i]
        y = data["top"][i]
        w = data["width"][i]
        h = data["height"][i]
        results.append(
            {
                "text": text,
                "bbox": [x, y, x + w, y + h],
                "confidence": (
                    float(conf) / 100.0 if isinstance(conf, (int, float)) else 0.0
                ),
            }
        )
    return results


def _char_overlap_ratio(a: str, b: str) -> float:
    """Compute character-level overlap ratio between two strings.

    Returns the ratio of shared characters to the length of the shorter
    string, giving a simple fuzzy-match score in [0.0, 1.0].
    """
    if not a or not b:
        return 0.0
    a_lower = a.lower()
    b_lower = b.lower()
    counter_a = Counter(a_lower)
    counter_b = Counter(b_lower)
    shared = sum((counter_a & counter_b).values())
    return shared / min(len(a_lower), len(b_lower))


def _bbox_center(bbox: list[int] | tuple[int, ...]) -> tuple[int, int]:
    """Return the center point of a bounding box ``[x1, y1, x2, y2]``."""
    x1, y1, x2, y2 = bbox
    return ((x1 + x2) // 2, (y1 + y2) // 2)


def _bbox_distance(
    a: list[int] | tuple[int, ...],
    b: list[int] | tuple[int, ...],
) -> float:
    """Euclidean distance between the centers of two bounding boxes."""
    cx_a, cy_a = _bbox_center(a)
    cx_b, cy_b = _bbox_center(b)
    return math.sqrt((cx_a - cx_b) ** 2 + (cy_a - cy_b) ** 2)


_NEARBY_TEXT_BOOST = 0.05
_NEARBY_TEXT_DISTANCE_PX = 100
_MAX_CANDIDATES = 5


def ground_by_text(
    screenshot: bytes,
    target: GroundingTarget,
    ocr_results: list[dict] | None = None,
) -> list[GroundingCandidate]:
    """Generate grounding candidates by matching target text against OCR.

    This is **Tier 1.5a** -- cheap ($0, <100 ms), runs *before* VLM
    grounding.

    Matching tiers (highest to lowest):
    - Exact match: ``local_score = 0.95``
    - Case-insensitive exact match: ``local_score = 0.90``
    - Substring (target description contains OCR text or vice versa):
      ``local_score = 0.70``
    - Fuzzy match (>80 % character overlap): ``local_score = 0.50``

    When ``target.nearby_text`` is set, candidates that have matching
    nearby-text elements within ~100 px receive a small score boost for
    spatial consistency.

    Args:
        screenshot: Current screenshot PNG bytes (used only if
            *ocr_results* is ``None`` to run OCR).
        target: :class:`GroundingTarget` with ``description``,
            ``nearby_text``, etc.
        ocr_results: Pre-computed OCR results as
            ``list[{"text": str, "bbox": [x1,y1,x2,y2]}]``.
            If ``None``, :func:`run_ocr` is called on the screenshot.

    Returns:
        Up to 5 :class:`GroundingCandidate` objects sorted by
        ``local_score`` (highest first).
    """
    if not target.description:
        return []

    if ocr_results is None:
        ocr_results = run_ocr(screenshot)

    if not ocr_results:
        return []

    desc = target.description
    candidates: list[GroundingCandidate] = []

    for item in ocr_results:
        ocr_text = item.get("text", "").strip()
        if not ocr_text:
            continue
        bbox = item.get("bbox")
        if not bbox or len(bbox) != 4:
            continue

        score: float | None = None

        # 1. Exact match
        if ocr_text == desc:
            score = 0.95
        # 2. Case-insensitive exact match
        elif ocr_text.lower() == desc.lower():
            score = 0.90
        # 3. Substring match (either direction)
        elif desc.lower() in ocr_text.lower() or ocr_text.lower() in desc.lower():
            score = 0.70
        # 4. Fuzzy match (>80% character overlap)
        else:
            overlap = _char_overlap_ratio(ocr_text, desc)
            if overlap > 0.80:
                score = 0.50

        if score is None:
            continue

        center = _bbox_center(bbox)
        candidates.append(
            GroundingCandidate(
                source="ocr",
                point=center,
                bbox=tuple(bbox),  # type: ignore[arg-type]
                local_score=score,
                matched_text=ocr_text,
            )
        )

    # Nearby-text spatial consistency boost
    if target.nearby_text and candidates:
        for cand in candidates:
            for nearby in target.nearby_text:
                for item in ocr_results:
                    item_text = item.get("text", "").strip()
                    item_bbox = item.get("bbox")
                    if not item_text or not item_bbox or len(item_bbox) != 4:
                        continue
                    if nearby.lower() in item_text.lower():
                        dist = _bbox_distance(
                            cand.bbox,  # type: ignore[arg-type]
                            item_bbox,
                        )
                        if dist <= _NEARBY_TEXT_DISTANCE_PX:
                            cand.local_score = min(
                                1.0, cand.local_score + _NEARBY_TEXT_BOOST
                            )
                            break

    # Sort by local_score descending, return top N
    candidates.sort(key=lambda c: c.local_score, reverse=True)
    return candidates[:_MAX_CANDIDATES]
