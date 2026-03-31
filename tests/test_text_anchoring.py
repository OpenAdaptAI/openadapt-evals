"""Tests for Tier 1.5a text anchoring (OCR-based grounding).

All tests use pre-computed mock OCR results -- no pytesseract required.
"""

from __future__ import annotations

import sys
from unittest.mock import patch

import pytest

from openadapt_evals.grounding import (
    GroundingCandidate,
    GroundingTarget,
    ground_by_text,
    run_ocr,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_ocr_results(*entries: tuple[str, list[int]]) -> list[dict]:
    """Build mock OCR results from (text, bbox) pairs."""
    return [
        {"text": text, "bbox": bbox, "confidence": 0.95}
        for text, bbox in entries
    ]


DUMMY_SCREENSHOT = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100  # fake PNG header


# ---------------------------------------------------------------------------
# ground_by_text tests
# ---------------------------------------------------------------------------


class TestGroundByTextExactMatch:
    """Exact text match should produce local_score = 0.95."""

    def test_exact_match(self):
        target = GroundingTarget(description="Save")
        ocr = _make_ocr_results(("Save", [100, 200, 160, 230]))
        candidates = ground_by_text(DUMMY_SCREENSHOT, target, ocr_results=ocr)

        assert len(candidates) == 1
        assert candidates[0].local_score == 0.95
        assert candidates[0].matched_text == "Save"
        assert candidates[0].source == "ocr"
        # Center of [100, 200, 160, 230] = (130, 215)
        assert candidates[0].point == (130, 215)
        assert candidates[0].bbox == (100, 200, 160, 230)


class TestGroundByTextCaseInsensitive:
    """Case-insensitive exact match should produce local_score = 0.90."""

    def test_case_insensitive_match(self):
        target = GroundingTarget(description="Save")
        ocr = _make_ocr_results(("save", [100, 200, 160, 230]))
        candidates = ground_by_text(DUMMY_SCREENSHOT, target, ocr_results=ocr)

        assert len(candidates) == 1
        assert candidates[0].local_score == 0.90
        assert candidates[0].matched_text == "save"

    def test_case_insensitive_match_upper(self):
        target = GroundingTarget(description="save")
        ocr = _make_ocr_results(("SAVE", [100, 200, 160, 230]))
        candidates = ground_by_text(DUMMY_SCREENSHOT, target, ocr_results=ocr)

        assert len(candidates) == 1
        assert candidates[0].local_score == 0.90


class TestGroundByTextSubstring:
    """Substring match should produce local_score = 0.70."""

    def test_description_contains_ocr_text(self):
        target = GroundingTarget(description="Save button")
        ocr = _make_ocr_results(("Save", [100, 200, 160, 230]))
        candidates = ground_by_text(DUMMY_SCREENSHOT, target, ocr_results=ocr)

        assert len(candidates) == 1
        assert candidates[0].local_score == 0.70

    def test_ocr_text_contains_description(self):
        target = GroundingTarget(description="Save")
        ocr = _make_ocr_results(("Save As...", [100, 200, 200, 230]))
        candidates = ground_by_text(DUMMY_SCREENSHOT, target, ocr_results=ocr)

        assert len(candidates) == 1
        assert candidates[0].local_score == 0.70


class TestGroundByTextNoMatch:
    """No match should return empty list."""

    def test_no_match(self):
        target = GroundingTarget(description="Delete")
        ocr = _make_ocr_results(
            ("Save", [100, 200, 160, 230]),
            ("Open", [200, 200, 260, 230]),
        )
        candidates = ground_by_text(DUMMY_SCREENSHOT, target, ocr_results=ocr)
        assert candidates == []

    def test_empty_description(self):
        target = GroundingTarget(description="")
        ocr = _make_ocr_results(("Save", [100, 200, 160, 230]))
        candidates = ground_by_text(DUMMY_SCREENSHOT, target, ocr_results=ocr)
        assert candidates == []

    def test_empty_ocr_results(self):
        target = GroundingTarget(description="Save")
        candidates = ground_by_text(DUMMY_SCREENSHOT, target, ocr_results=[])
        assert candidates == []


class TestGroundByTextNearbyTextBoost:
    """Candidates near expected text should get boosted score."""

    def test_nearby_text_boost(self):
        target = GroundingTarget(
            description="OK",
            nearby_text=["Cancel"],
        )
        # "OK" at (130, 215), "Cancel" at (210, 215) -- within 100px
        ocr = _make_ocr_results(
            ("OK", [100, 200, 160, 230]),
            ("Cancel", [170, 200, 250, 230]),
        )
        candidates = ground_by_text(DUMMY_SCREENSHOT, target, ocr_results=ocr)

        # "OK" should get an exact-match score (0.95) + nearby boost (0.05)
        ok_candidates = [c for c in candidates if c.matched_text == "OK"]
        assert len(ok_candidates) == 1
        assert ok_candidates[0].local_score == 1.0  # 0.95 + 0.05 capped at 1.0

    def test_no_nearby_text_no_boost(self):
        target = GroundingTarget(
            description="OK",
            nearby_text=["Cancel"],
        )
        # "OK" at (130, 215), "Cancel" far away at (820, 795) -- > 100px
        ocr = _make_ocr_results(
            ("OK", [100, 200, 160, 230]),
            ("Cancel", [780, 780, 860, 810]),
        )
        candidates = ground_by_text(DUMMY_SCREENSHOT, target, ocr_results=ocr)

        ok_candidates = [c for c in candidates if c.matched_text == "OK"]
        assert len(ok_candidates) == 1
        # No boost -- distance too large
        assert ok_candidates[0].local_score == 0.95


class TestGroundByTextSorted:
    """Candidates should be sorted by local_score descending."""

    def test_sorted_by_score(self):
        target = GroundingTarget(description="Save")
        ocr = _make_ocr_results(
            ("save", [100, 200, 160, 230]),  # case-insensitive = 0.90
            ("Save", [300, 200, 360, 230]),  # exact = 0.95
            ("Save button", [500, 200, 620, 230]),  # substring = 0.70
        )
        candidates = ground_by_text(DUMMY_SCREENSHOT, target, ocr_results=ocr)

        assert len(candidates) == 3
        assert candidates[0].local_score == 0.95  # exact
        assert candidates[1].local_score == 0.90  # case-insensitive
        assert candidates[2].local_score == 0.70  # substring

    def test_max_5_candidates(self):
        target = GroundingTarget(description="Item")
        # 7 OCR results all containing "Item" (substring)
        ocr = _make_ocr_results(
            *[
                (f"Item {i}", [i * 100, 100, i * 100 + 80, 130])
                for i in range(7)
            ]
        )
        candidates = ground_by_text(DUMMY_SCREENSHOT, target, ocr_results=ocr)
        assert len(candidates) <= 5


class TestGroundByTextFuzzyMatch:
    """Fuzzy match (>80% character overlap) should give 0.50."""

    def test_fuzzy_match(self):
        target = GroundingTarget(description="Settings")
        # "Settingz" has 7/8 overlap = 87.5% > 80%
        ocr = _make_ocr_results(("Settingz", [100, 200, 200, 230]))
        candidates = ground_by_text(DUMMY_SCREENSHOT, target, ocr_results=ocr)

        assert len(candidates) == 1
        assert candidates[0].local_score == 0.50

    def test_no_fuzzy_below_threshold(self):
        target = GroundingTarget(description="Settings")
        # "Abcdefgh" has very low overlap
        ocr = _make_ocr_results(("Abcdefgh", [100, 200, 200, 230]))
        candidates = ground_by_text(DUMMY_SCREENSHOT, target, ocr_results=ocr)

        assert candidates == []


# ---------------------------------------------------------------------------
# run_ocr tests
# ---------------------------------------------------------------------------


class TestRunOcrNoPytesseract:
    """run_ocr should return empty list when pytesseract is not installed."""

    def test_returns_empty_without_pytesseract(self):
        # Simulate pytesseract not being installed
        with patch.dict(sys.modules, {"pytesseract": None}):
            result = run_ocr(DUMMY_SCREENSHOT)
            assert result == []


class TestGroundByTextWithMockOcr:
    """ground_by_text with pre-computed OCR results (no pytesseract needed)."""

    def test_full_pipeline_with_mock_ocr(self):
        """Simulate a realistic UI with multiple text elements."""
        target = GroundingTarget(
            description="Clear browsing data",
            nearby_text=["Privacy", "Security"],
        )
        ocr = _make_ocr_results(
            ("Privacy", [50, 100, 150, 130]),
            ("Security", [50, 140, 160, 170]),
            ("Clear browsing data", [200, 300, 400, 330]),
            ("Downloads", [200, 350, 350, 380]),
            ("History", [200, 400, 300, 430]),
        )

        candidates = ground_by_text(DUMMY_SCREENSHOT, target, ocr_results=ocr)

        assert len(candidates) >= 1
        best = candidates[0]
        assert best.matched_text == "Clear browsing data"
        assert best.local_score >= 0.95
        assert best.source == "ocr"

    def test_none_ocr_results_calls_run_ocr(self):
        """When ocr_results is None, ground_by_text should call run_ocr."""
        target = GroundingTarget(description="Save")

        with patch(
            "openadapt_evals.grounding.run_ocr",
            return_value=_make_ocr_results(("Save", [100, 200, 160, 230])),
        ) as mock_ocr:
            candidates = ground_by_text(
                DUMMY_SCREENSHOT, target, ocr_results=None
            )

        mock_ocr.assert_called_once_with(DUMMY_SCREENSHOT)
        assert len(candidates) == 1
        assert candidates[0].matched_text == "Save"


# ---------------------------------------------------------------------------
# DemoExecutor integration tests
# ---------------------------------------------------------------------------


class TestDemoExecutorTextAnchoring:
    """Test that DemoExecutor tries Tier 1.5a before VLM grounder."""

    def test_text_anchoring_skips_vlm_on_high_confidence(self):
        """High-confidence OCR match should bypass VLM grounder."""
        from openadapt_evals.adapters.base import BenchmarkObservation
        from openadapt_evals.agents.demo_executor import DemoExecutor
        from openadapt_evals.demo_library import DemoStep

        executor = DemoExecutor(grounder_model="gpt-4.1-mini")

        # Create a 1x1 white PNG for screenshot dimension detection
        import io

        from PIL import Image

        img = Image.new("RGB", (1920, 1080), color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        screenshot_bytes = buf.getvalue()

        obs = BenchmarkObservation(screenshot=screenshot_bytes)
        step = DemoStep(
            step_index=0,
            screenshot_path="",
            action_type="click",
            action_description="click Save button",
            target_description="Save",
            action_value="",
            description="Save",
        )

        # Mock run_ocr to return a high-confidence match
        mock_ocr = _make_ocr_results(("Save", [100, 200, 160, 230]))
        with patch(
            "openadapt_evals.agents.demo_executor.run_ocr",
            return_value=mock_ocr,
        ):
            action = executor._execute_step(step, obs)

        assert action is not None
        assert action.type == "click"
        # Should have used OCR coordinates, not VLM
        raw = action.raw_action or {}
        assert raw.get("tier") == 1.5
        assert raw.get("ocr_matched_text") == "Save"

    def test_text_anchoring_falls_through_on_low_confidence(self):
        """Low-confidence OCR match should fall through to VLM grounder."""
        from openadapt_evals.adapters.base import (
            BenchmarkAction,
            BenchmarkObservation,
        )
        from openadapt_evals.agents.demo_executor import DemoExecutor
        from openadapt_evals.demo_library import DemoStep

        executor = DemoExecutor(grounder_model="gpt-4.1-mini")

        obs = BenchmarkObservation(screenshot=DUMMY_SCREENSHOT)
        step = DemoStep(
            step_index=0,
            screenshot_path="",
            action_type="click",
            action_description="click the submit form",
            target_description="Submit",
            action_value="",
            description="Submit",
        )

        # Mock run_ocr with no matching text
        with patch(
            "openadapt_evals.agents.demo_executor.run_ocr",
            return_value=[],
        ):
            # Mock the VLM grounder to avoid real API calls
            with patch.object(
                executor,
                "_ground_click",
                return_value=BenchmarkAction(
                    type="click", x=0.5, y=0.5
                ),
            ) as mock_vlm:
                action = executor._execute_step(step, obs)

        # Should have fallen through to VLM
        mock_vlm.assert_called_once()
        assert action is not None
        assert action.type == "click"
