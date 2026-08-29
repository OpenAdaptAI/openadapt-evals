"""Two checkers, one honest.

``sor_check`` reads the system of record: ``|new(M)| = |spec(M)|``, every
spec field present, no extra field. Gold for a mutant is FAIL.

``field_inclusion_check`` asks only whether each spec field-value appears
in some record. It ignores extra records and extra fields. That is the
WorkArena form monitor / AppWorld C_allow inclusion checker.

``visual_only_check`` believes the banner, the filled form, or the agent's
claim. A Seal that hashes a screenshot is this checker.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from openadapt_evals.extradup.gold import WriteSpec
from openadapt_evals.extradup.store import Screen


@dataclass(frozen=True)
class CheckResult:
    verdict: str
    reasons: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return self.verdict == "PASS"


def new_records(
    before: list[dict[str, Any]], after: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """``new(M)``: rows whose ``id`` was not in the pre-state."""
    before_ids = {row["id"] for row in before}
    return [row for row in after if row["id"] not in before_ids]


def sor_check(
    spec: WriteSpec,
    before: list[dict[str, Any]],
    after: list[dict[str, Any]],
) -> CheckResult:
    """Independent SoR read. Duplicate-CREATE dies on cardinality."""
    added = new_records(before, after)
    reasons: list[str] = []
    if len(added) != spec.expected_new:
        reasons.append(
            f"|new(M)|={len(added)} != |spec(M)|={spec.expected_new}"
        )
    for row in added:
        extras = set(row) - spec.allowed_fields
        if extras:
            reasons.append("extra field(s): " + ", ".join(sorted(extras)))
        for key, value in spec.fields.items():
            if row.get(key) != value:
                reasons.append(f"missing or wrong {key}={value!r}")
    if reasons:
        return CheckResult("FAIL", tuple(reasons))
    return CheckResult("PASS")


def field_inclusion_check(
    spec: WriteSpec,
    after: list[dict[str, Any]],
) -> CheckResult:
    """PASS iff every spec field-value appears in at least one record.

    Extra records and extra fields are invisible. This is the checker a
    Seal must not ship as production VERIFIED.
    """
    missing: list[str] = []
    for key, value in spec.fields.items():
        if not any(row.get(key) == value for row in after):
            missing.append(f"{key}={value!r}")
    if missing:
        return CheckResult("FAIL", tuple(f"spec field absent: {item}" for item in missing))
    return CheckResult("PASS")


def visual_only_check(screen: Screen) -> CheckResult:
    """PASS iff the untrusted witness says the write happened."""
    if screen.looks_done():
        return CheckResult("PASS")
    return CheckResult("FAIL", ("screen does not look done",))
