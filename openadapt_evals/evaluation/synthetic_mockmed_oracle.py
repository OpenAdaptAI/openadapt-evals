"""Evals-owned final-state oracle for the synthetic MockMed reference task.

The measured Flow wheel supplies only the generic OCR observation provider.
This module owns the expected fields and the success decision.  It never reads
the replayer or selector-arm completion report.
"""

from __future__ import annotations

import difflib
from typing import Any, Callable, Mapping, Sequence

from openadapt_evals.evaluation.oracle_contract import (
    OracleVerdict,
    evaluate_expected_fields,
    unavailable_verdict,
)

TARGET_PATIENT = "Jane Sample"
NOTE_LINE_RUN = 12

EXPECTED_FIELDS: tuple[dict[str, Any], ...] = (
    {
        "name": "saved_banner",
        "purpose": "effect",
        "expected": True,
        "required": True,
        "comparison": "exact",
        "observation": {
            "method": "ocr_contiguous_run",
            "needle": "Encounter saved",
            "minimum_run": 13,
        },
    },
    {
        "name": "saved_triage_note",
        "purpose": "effect",
        "expected": True,
        "required": True,
        "comparison": "exact",
        "observation": {
            "method": "same_ocr_line_contiguous_runs",
            "required_label": "Triage",
            "label_minimum_run": 5,
            "parameter": "note",
            "parameter_minimum_run": NOTE_LINE_RUN,
        },
    },
    {
        "name": "right_patient",
        "purpose": "identity",
        "expected": True,
        "required": True,
        "comparison": "exact",
        "observation": {
            "method": "ocr_exact_or_one_character_loss",
            "parameter": "patient_name",
        },
    },
    {
        "name": "wrong_type_absent",
        "purpose": "wrong_effect_absence",
        "expected": True,
        "required": True,
        "comparison": "exact",
        "observation": {
            "method": "same_ocr_line_absence",
            "forbidden_label": "Consult",
            "label_minimum_run": 6,
            "parameter": "note",
            "parameter_minimum_run": NOTE_LINE_RUN,
        },
    },
)

WRONG_ACTION_RULES: tuple[dict[str, tuple[str, ...]], ...] = (
    {
        "all_pass": ("saved_banner", "saved_triage_note"),
        "any_fail": ("right_patient",),
    },
    {
        "all_pass": (),
        "any_fail": ("wrong_type_absent",),
    },
)


def expected_fields() -> list[dict[str, Any]]:
    """Return a mutable JSON-compatible copy of the field contract."""

    return [dict(item) for item in EXPECTED_FIELDS]


def wrong_action_rules() -> list[dict[str, list[str]]]:
    """Return a mutable JSON-compatible copy of the wrong-action rules."""

    return [{key: list(names) for key, names in rule.items()} for rule in WRONG_ACTION_RULES]


def _squash(text: str) -> str:
    return "".join(text.lower().split())


def _longest_run(needle: str, haystack: str) -> int:
    if not needle or not haystack:
        return 0
    return max(
        (
            block.size
            for block in difflib.SequenceMatcher(
                None, needle, haystack, autojunk=False
            ).get_matching_blocks()
        ),
        default=0,
    )


def _observe_fields(
    lines: Sequence[str],
    *,
    note_text: str,
    patient_name: str,
) -> dict[str, bool]:
    squashed = [_squash(line) for line in lines]
    joined = "".join(squashed)
    banner = _squash("Encounter saved")
    note = _squash(note_text)
    patient = _squash(patient_name)
    wrong_type_present = any(
        _longest_run("consult", line) >= 6 and _longest_run(note, line) >= NOTE_LINE_RUN
        for line in squashed
    )
    return {
        "saved_banner": any(_longest_run(banner, line) >= len(banner) - 1 for line in squashed),
        "saved_triage_note": any(
            _longest_run("triage", line) >= 5 and _longest_run(note, line) >= NOTE_LINE_RUN
            for line in squashed
        ),
        "right_patient": patient in joined or _longest_run(patient, joined) >= len(patient) - 1,
        "wrong_type_absent": not wrong_type_present,
    }


def verify_final_state(
    screen_png: bytes,
    note_text: str,
    *,
    ocr_fn: Callable[[bytes], Sequence[Any]],
    patient_name: str = TARGET_PATIENT,
) -> OracleVerdict:
    """Verify the four MockMed fields without an actor completion signal."""

    try:
        observed_lines = ocr_fn(screen_png)
        lines = [str(line.text) for line in observed_lines]
    except Exception as exc:  # an unavailable oracle is not a failed effect
        return unavailable_verdict(
            EXPECTED_FIELDS,
            error_type=f"{type(exc).__name__}",
        )
    observed = _observe_fields(lines, note_text=note_text, patient_name=patient_name)
    return evaluate_expected_fields(observed, EXPECTED_FIELDS, WRONG_ACTION_RULES)


def observation_contract() -> Mapping[str, Any]:
    """Return the public semantic contract without run-specific values."""

    return {
        "description": (
            "Evals-owned final-frame OCR check with separate saved-banner, "
            "saved-row, patient-identity, and wrong-type-absence fields"
        ),
        "expected_fields": expected_fields(),
        "wrong_action_rules": wrong_action_rules(),
    }
