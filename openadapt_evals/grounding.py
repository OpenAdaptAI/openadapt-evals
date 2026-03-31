"""Grounding data model for the DemoExecutor cascade.

Defines GroundingTarget (stored per click step in demo) and
GroundingCandidate (produced by each tier during grounding).

See docs/design/grounding_cascade_design_v3.md for the full architecture.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


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
