"""Tests for openadapt_evals.plan_verify — VLM-based step verification."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from openadapt_evals.plan_verify import (
    VerificationResult,
    _parse_verification_result,
    verify_goal_completion,
    verify_plan_progress,
    verify_step,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FAKE_SCREENSHOT = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100  # minimal PNG-ish bytes


# ---------------------------------------------------------------------------
# VerificationResult dataclass
# ---------------------------------------------------------------------------


class TestVerificationResult:
    """Tests for VerificationResult creation and validation."""

    def test_create_verified(self):
        r = VerificationResult(
            status="verified",
            confidence=0.95,
            explanation="Cell A1 contains 'Year'",
            raw_response='{"status":"verified","confidence":0.95}',
        )
        assert r.status == "verified"
        assert r.confidence == 0.95
        assert "Year" in r.explanation

    def test_create_not_verified(self):
        r = VerificationResult(
            status="not_verified",
            confidence=0.8,
            explanation="Cell A1 is empty",
            raw_response="{}",
        )
        assert r.status == "not_verified"
        assert r.confidence == 0.8

    def test_create_unclear(self):
        r = VerificationResult(
            status="unclear",
            confidence=0.3,
            explanation="Cannot determine",
            raw_response="",
        )
        assert r.status == "unclear"

    def test_invalid_status_raises(self):
        with pytest.raises(ValueError, match="Invalid status"):
            VerificationResult(
                status="maybe",
                confidence=0.5,
                explanation="",
                raw_response="",
            )

    def test_confidence_clamped_high(self):
        r = VerificationResult(
            status="verified",
            confidence=1.5,
            explanation="",
            raw_response="",
        )
        assert r.confidence == 1.0

    def test_confidence_clamped_low(self):
        r = VerificationResult(
            status="verified",
            confidence=-0.3,
            explanation="",
            raw_response="",
        )
        assert r.confidence == 0.0


# ---------------------------------------------------------------------------
# _parse_verification_result
# ---------------------------------------------------------------------------


class TestParseVerificationResult:
    """Tests for the internal JSON response parser."""

    def test_valid_json(self):
        raw = json.dumps({
            "status": "verified",
            "confidence": 0.92,
            "explanation": "The header 'Year' is visible in A1.",
        })
        result = _parse_verification_result(raw)
        assert result.status == "verified"
        assert result.confidence == pytest.approx(0.92)
        assert "Year" in result.explanation
        assert result.raw_response == raw

    def test_json_in_code_fence(self):
        raw = (
            "Here is my analysis:\n"
            "```json\n"
            '{"status": "not_verified", "confidence": 0.6, '
            '"explanation": "The cell is empty."}\n'
            "```\n"
            "That is my answer."
        )
        result = _parse_verification_result(raw)
        assert result.status == "not_verified"
        assert result.confidence == pytest.approx(0.6)

    def test_malformed_json_falls_back(self):
        raw = "I cannot parse this {broken json"
        result = _parse_verification_result(raw)
        assert result.status == "unclear"
        assert result.confidence == 0.0
        assert "Failed to parse" in result.explanation

    def test_invalid_status_falls_back(self):
        raw = json.dumps({
            "status": "probably",
            "confidence": 0.5,
            "explanation": "Not sure",
        })
        result = _parse_verification_result(raw)
        assert result.status == "unclear"

    def test_missing_confidence_defaults_zero(self):
        raw = json.dumps({
            "status": "verified",
            "explanation": "Looks good",
        })
        result = _parse_verification_result(raw)
        assert result.status == "verified"
        assert result.confidence == 0.0

    def test_non_dict_json_falls_back(self):
        raw = json.dumps(["verified", 0.9, "looks good"])
        result = _parse_verification_result(raw)
        assert result.status == "unclear"
        assert result.confidence == 0.0


# ---------------------------------------------------------------------------
# verify_step
# ---------------------------------------------------------------------------


class TestVerifyStep:
    """Tests for verify_step with mocked vlm_call."""

    @patch("openadapt_evals.vlm.vlm_call")
    def test_verified_response(self, mock_vlm_call):
        mock_vlm_call.return_value = json.dumps({
            "status": "verified",
            "confidence": 0.95,
            "explanation": "The text 'Year' is visible in cell A1.",
        })

        result = verify_step(
            FAKE_SCREENSHOT,
            'The text "Year" should appear in cell A1.',
        )

        assert result.status == "verified"
        assert result.confidence == pytest.approx(0.95)
        assert "Year" in result.explanation
        mock_vlm_call.assert_called_once()

        # Check that the call used the right parameters
        call_kwargs = mock_vlm_call.call_args
        assert call_kwargs.kwargs["images"] == [FAKE_SCREENSHOT]
        assert call_kwargs.kwargs["model"] == "gpt-4.1-mini"
        assert call_kwargs.kwargs["provider"] == "openai"

    @patch("openadapt_evals.vlm.vlm_call")
    def test_not_verified_response(self, mock_vlm_call):
        mock_vlm_call.return_value = json.dumps({
            "status": "not_verified",
            "confidence": 0.85,
            "explanation": "Cell A1 is empty; no text is visible.",
        })

        result = verify_step(FAKE_SCREENSHOT, "Cell A1 should contain text.")
        assert result.status == "not_verified"
        assert result.confidence == pytest.approx(0.85)

    @patch("openadapt_evals.vlm.vlm_call")
    def test_malformed_vlm_response(self, mock_vlm_call):
        mock_vlm_call.return_value = "Sorry, I cannot process this image."

        result = verify_step(FAKE_SCREENSHOT, "Some expectation")
        assert result.status == "unclear"
        assert result.confidence == 0.0
        assert "Failed to parse" in result.explanation

    @patch("openadapt_evals.vlm.vlm_call")
    def test_vlm_exception_returns_unclear(self, mock_vlm_call):
        mock_vlm_call.side_effect = RuntimeError("API timeout")

        result = verify_step(FAKE_SCREENSHOT, "Some expectation")
        assert result.status == "unclear"
        assert result.confidence == 0.0
        assert "API timeout" in result.explanation
        assert result.raw_response == ""

    @patch("openadapt_evals.vlm.vlm_call")
    def test_custom_model_and_provider(self, mock_vlm_call):
        mock_vlm_call.return_value = json.dumps({
            "status": "verified",
            "confidence": 0.9,
            "explanation": "OK",
        })

        verify_step(
            FAKE_SCREENSHOT,
            "Test",
            model="claude-sonnet-4-20250514",
            provider="anthropic",
            timeout=60,
        )

        call_kwargs = mock_vlm_call.call_args.kwargs
        assert call_kwargs["model"] == "claude-sonnet-4-20250514"
        assert call_kwargs["provider"] == "anthropic"
        assert call_kwargs["timeout"] == 60

    @patch("openadapt_evals.vlm.vlm_call")
    def test_json_in_code_fence_response(self, mock_vlm_call):
        mock_vlm_call.return_value = (
            "Based on my analysis:\n"
            "```json\n"
            '{"status": "verified", "confidence": 0.88, '
            '"explanation": "Header is present."}\n'
            "```"
        )

        result = verify_step(FAKE_SCREENSHOT, "Header should be present.")
        assert result.status == "verified"
        assert result.confidence == pytest.approx(0.88)


# ---------------------------------------------------------------------------
# verify_plan_progress
# ---------------------------------------------------------------------------


class TestVerifyPlanProgress:
    """Tests for verify_plan_progress with mocked vlm_call."""

    PLAN_STEPS = [
        "Create a new sheet",
        "Type 'Year' in A1",
        "Type 'CA changes' in B1",
        "Type 'FA changes' in C1",
        "Type 'OA changes' in D1",
    ]

    @patch("openadapt_evals.vlm.vlm_call")
    def test_normal_progress(self, mock_vlm_call):
        mock_vlm_call.return_value = json.dumps({
            "completed_steps": [0, 1, 2],
            "current_step": 3,
            "confidence": 0.9,
        })

        result = verify_plan_progress(
            FAKE_SCREENSHOT, self.PLAN_STEPS, current_step_idx=2
        )

        assert result["completed_steps"] == [0, 1, 2]
        assert result["current_step"] == 3
        assert result["confidence"] == pytest.approx(0.9)

    @patch("openadapt_evals.vlm.vlm_call")
    def test_all_steps_completed(self, mock_vlm_call):
        mock_vlm_call.return_value = json.dumps({
            "completed_steps": [0, 1, 2, 3, 4],
            "current_step": 5,
            "confidence": 0.95,
        })

        result = verify_plan_progress(
            FAKE_SCREENSHOT, self.PLAN_STEPS, current_step_idx=4
        )

        assert result["completed_steps"] == [0, 1, 2, 3, 4]
        # current_step == len(plan_steps) is allowed (means "done")
        assert result["current_step"] == 5
        assert result["confidence"] == pytest.approx(0.95)

    @patch("openadapt_evals.vlm.vlm_call")
    def test_malformed_response_returns_fallback(self, mock_vlm_call):
        mock_vlm_call.return_value = "I cannot determine the progress."

        result = verify_plan_progress(
            FAKE_SCREENSHOT, self.PLAN_STEPS, current_step_idx=2
        )

        # Fallback: completed_steps = range(current_step_idx)
        assert result["completed_steps"] == [0, 1]
        assert result["current_step"] == 2
        assert result["confidence"] == 0.0

    @patch("openadapt_evals.vlm.vlm_call")
    def test_vlm_exception_returns_fallback(self, mock_vlm_call):
        mock_vlm_call.side_effect = ConnectionError("Network down")

        result = verify_plan_progress(
            FAKE_SCREENSHOT, self.PLAN_STEPS, current_step_idx=3
        )

        assert result["completed_steps"] == [0, 1, 2]
        assert result["current_step"] == 3
        assert result["confidence"] == 0.0

    @patch("openadapt_evals.vlm.vlm_call")
    def test_invalid_step_indices_filtered(self, mock_vlm_call):
        mock_vlm_call.return_value = json.dumps({
            "completed_steps": [0, 1, 99, -1, "bad"],
            "current_step": 2,
            "confidence": 0.7,
        })

        result = verify_plan_progress(
            FAKE_SCREENSHOT, self.PLAN_STEPS, current_step_idx=2
        )

        # Only valid indices (0 and 1) should remain
        assert result["completed_steps"] == [0, 1]
        assert result["current_step"] == 2

    @patch("openadapt_evals.vlm.vlm_call")
    def test_invalid_current_step_uses_fallback(self, mock_vlm_call):
        mock_vlm_call.return_value = json.dumps({
            "completed_steps": [0, 1],
            "current_step": -5,
            "confidence": 0.6,
        })

        result = verify_plan_progress(
            FAKE_SCREENSHOT, self.PLAN_STEPS, current_step_idx=2
        )

        # Invalid current_step falls back to provided current_step_idx
        assert result["current_step"] == 2

    @patch("openadapt_evals.vlm.vlm_call")
    def test_custom_model_and_provider(self, mock_vlm_call):
        mock_vlm_call.return_value = json.dumps({
            "completed_steps": [0],
            "current_step": 1,
            "confidence": 0.8,
        })

        verify_plan_progress(
            FAKE_SCREENSHOT,
            self.PLAN_STEPS,
            current_step_idx=1,
            model="gpt-4o",
            provider="openai",
            timeout=45,
        )

        call_kwargs = mock_vlm_call.call_args.kwargs
        assert call_kwargs["model"] == "gpt-4o"
        assert call_kwargs["timeout"] == 45


# ---------------------------------------------------------------------------
# verify_goal_completion
# ---------------------------------------------------------------------------


class TestVerifyGoalCompletion:
    """Tests for verify_goal_completion with mocked vlm_call."""

    GOAL = (
        "In a new sheet with 4 headers 'Year', 'CA changes', 'FA changes', "
        "and 'OA changes', calculate the annual changes."
    )

    @patch("openadapt_evals.vlm.vlm_call")
    def test_goal_verified(self, mock_vlm_call):
        mock_vlm_call.return_value = json.dumps({
            "status": "verified",
            "confidence": 0.92,
            "explanation": "All four headers and calculated values are visible.",
        })

        result = verify_goal_completion(FAKE_SCREENSHOT, self.GOAL)
        assert result.status == "verified"
        assert result.confidence == pytest.approx(0.92)
        assert "headers" in result.explanation

    @patch("openadapt_evals.vlm.vlm_call")
    def test_goal_not_verified(self, mock_vlm_call):
        mock_vlm_call.return_value = json.dumps({
            "status": "not_verified",
            "confidence": 0.88,
            "explanation": "Only headers are visible but no calculated values.",
        })

        result = verify_goal_completion(FAKE_SCREENSHOT, self.GOAL)
        assert result.status == "not_verified"

    @patch("openadapt_evals.vlm.vlm_call")
    def test_vlm_exception_returns_unclear(self, mock_vlm_call):
        mock_vlm_call.side_effect = TimeoutError("Request timed out")

        result = verify_goal_completion(FAKE_SCREENSHOT, self.GOAL)
        assert result.status == "unclear"
        assert result.confidence == 0.0
        assert "timed out" in result.explanation

    @patch("openadapt_evals.vlm.vlm_call")
    def test_malformed_response_returns_unclear(self, mock_vlm_call):
        mock_vlm_call.return_value = "The goal seems partially done."

        result = verify_goal_completion(FAKE_SCREENSHOT, self.GOAL)
        assert result.status == "unclear"
        assert result.confidence == 0.0

    @patch("openadapt_evals.vlm.vlm_call")
    def test_custom_model(self, mock_vlm_call):
        mock_vlm_call.return_value = json.dumps({
            "status": "verified",
            "confidence": 0.9,
            "explanation": "Done.",
        })

        verify_goal_completion(
            FAKE_SCREENSHOT,
            self.GOAL,
            model="claude-sonnet-4-20250514",
            provider="anthropic",
            timeout=60,
        )

        call_kwargs = mock_vlm_call.call_args.kwargs
        assert call_kwargs["model"] == "claude-sonnet-4-20250514"
        assert call_kwargs["provider"] == "anthropic"
        assert call_kwargs["timeout"] == 60

    @patch("openadapt_evals.vlm.vlm_call")
    def test_prompt_contains_goal_text(self, mock_vlm_call):
        mock_vlm_call.return_value = json.dumps({
            "status": "verified",
            "confidence": 0.9,
            "explanation": "Done.",
        })

        verify_goal_completion(FAKE_SCREENSHOT, self.GOAL)

        # The prompt (first positional arg) should contain the goal text
        prompt_arg = mock_vlm_call.call_args.args[0]
        assert self.GOAL in prompt_arg
