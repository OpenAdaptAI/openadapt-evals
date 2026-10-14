"""Plain-text report for the terminal."""

from __future__ import annotations

from openadapt_evals.verifier_audit.effects import summarize
from openadapt_evals.verifier_audit.operators import OPERATOR_CLASS
from openadapt_evals.verifier_audit.runner import (
    AUDITED,
    EQUIVALENT,
    FALSE_ACCEPT,
    INVALID,
    KILLED,
    NOT_DELIVERED,
    REFUSED,
    UNCONFIRMED,
    AuditResult,
)

_COLUMNS = (
    ("killed", KILLED),
    ("false accept", FALSE_ACCEPT),
    ("equivalent", EQUIVALENT),
    ("unconfirmed", UNCONFIRMED),
    ("refused", REFUSED),
    ("error", NOT_DELIVERED),
    ("invalid", INVALID),
)


def _table(rows: list[list[str]]) -> list[str]:
    widths = [max(len(row[i]) for row in rows) for i in range(len(rows[0]))]
    lines = []
    for n, row in enumerate(rows):
        cells = [
            cell.ljust(widths[i]) if i < 2 or not cell.isdigit() else cell.rjust(widths[i])
            for i, cell in enumerate(row)
        ]
        lines.append("  " + "  ".join(cells).rstrip())
        if n == 0:
            lines.append("  " + "  ".join("-" * w for w in widths))
    return lines


def render(result: AuditResult) -> str:
    name = result.benchmark.get("name", "benchmark")
    audited = [t for t in result.tasks if t.status == AUDITED]
    lines = [
        f"Verifier audit: {name}, {len(result.tasks)} task(s), "
        f"{len(audited)} audited, {result.seconds:.0f}s",
        "",
    ]

    accepts = result.false_accepts
    if accepts:
        lines.append(f"The verifier passed {len(accepts)} edited run(s) whose end state is wrong:")
        rows = [["task", "operator", "end state compared with the reference run"]]
        for run in accepts:
            rows.append([run.task_id, run.operator, summarize(run.tables)])
        lines.extend(_table(rows))
    else:
        lines.append("No confirmed false accepts in these tasks.")
    lines.append("")

    rows = [["operator", "class", "runs", *[label for label, _ in _COLUMNS]]]
    table = result.by_operator()
    for operator in result.operators:
        counts = table[operator]
        runs = sum(counts[key] for _, key in _COLUMNS if key != REFUSED)
        rows.append(
            [operator, OPERATOR_CLASS[operator], str(runs)]
            + [str(counts[key]) for _, key in _COLUMNS]
        )
    lines.append("Per operator (each edited run counted once; operators are not pooled):")
    lines.extend(_table(rows))

    skipped = [t for t in result.tasks if t.status != AUDITED]
    if skipped:
        lines.append("")
        lines.append(f"{len(skipped)} task(s) not audited:")
        for task in skipped:
            lines.append(f"  {task.task_id}: {task.status} ({task.reason})")
    lines.append("")
    lines.append("false accept: the verifier passed the edited run, and the end state (read")
    lines.append("  back before grading) differs from the reference run's.")
    lines.append("equivalent: the edit left the end state unchanged, so the pass is correct.")
    return "\n".join(lines)
