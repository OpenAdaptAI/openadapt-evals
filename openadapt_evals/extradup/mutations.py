"""Operators over a gold CREATE: omit, extra, dup, unsubmit, claim.

``control`` is the unmutated gold write. Mutants construct a wrong effect.
"""

from __future__ import annotations

from typing import Any

from openadapt_evals.extradup.gold import WriteSpec
from openadapt_evals.extradup.store import Screen, Store

# ExtraDup operators named in the workshop paper, plus the clean control.
OPERATORS: tuple[str, ...] = (
    "control",
    "dup",
    "extra",
    "omit",
    "unsubmit",
    "claim",
)

MUTANTS: tuple[str, ...] = tuple(op for op in OPERATORS if op != "control")


def apply(
    store: Store,
    spec: WriteSpec,
    operator: str,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], Screen]:
    """Reset, apply ``operator`` to the gold CREATE, return (before, after, screen)."""
    if operator not in OPERATORS:
        raise KeyError(f"unknown ExtraDup operator {operator!r}")
    store.reset()
    before = store.snapshot()
    fields = dict(spec.fields)
    screen = Screen()
    if operator == "unsubmit":
        # Form is filled. Nothing is posted. WorkArena W-NO-SUBMIT.
        screen = Screen(form_looks_complete=True)
    elif operator == "claim":
        # Optimistic banner / agent self-report. Nothing lands.
        screen = Screen(banner_saved=True, claimed_success=True)
    else:
        if operator == "omit":
            fields.pop(spec.omit_field, None)
        elif operator == "extra":
            fields[spec.extra_field] = spec.extra_value
        screen = store.write(fields)
        if operator == "dup":
            # Extra-NI: duplicate the non-idempotent CREATE.
            screen = store.write(fields)
    after = store.snapshot()
    return before, after, screen
