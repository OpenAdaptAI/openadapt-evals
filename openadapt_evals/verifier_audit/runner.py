"""Run the audit: edit correct runs, deliver them, read back, then grade.

For each task:

1. Get the reference run from the adapter. A task whose reference writes
   nothing is skipped: no operator can apply to it.
2. Apply every operator. An operator that cannot apply is recorded as
   refused, with its reason.
3. For ``extra-ni``, replay each candidate repeat without calling the
   verifier and keep the newest one whose end state differs from the
   unedited replay. If no repeat changes anything, ``extra-ni`` is refused.
4. Deliver the unedited reference run (the control) and every mutant, each
   from a fresh start state. The adapter reads the end state back before it
   calls the verifier.
5. Check the control: the verifier must pass it and its end state must match
   the reference run's. If not, the task's mutants are invalid.
6. Give each mutant exactly one class (``RUN_CLASSES``).

No step calls a model, and no step looks at a verdict to decide what to run.
"""

from __future__ import annotations

import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Sequence

from openadapt_evals.verifier_audit.adapters.base import (
    BenchmarkAdapter,
    Delivery,
    Run,
)
from openadapt_evals.verifier_audit.effects import compare
from openadapt_evals.verifier_audit.operators import (
    OPERATOR_CLASS,
    OPERATORS,
    apply_operator,
    repeat_at,
    repeat_candidates,
)

FALSE_ACCEPT = "false-accept"
KILLED = "killed"
EQUIVALENT = "equivalent"
UNCONFIRMED = "unconfirmed"
REFUSED = "refused"
NOT_DELIVERED = "not-delivered"
INVALID = "invalid"

#: Every mutant gets exactly one of these.
RUN_CLASSES: dict[str, str] = {
    FALSE_ACCEPT: "the verifier passed it and the end state differs from the reference run's",
    KILLED: "the verifier failed it",
    EQUIVALENT: "the verifier passed it and the end state matches the reference run's, "
    "so the pass is correct",
    UNCONFIRMED: "the verifier passed it, the end state differs, but a call raised during "
    "delivery, so the difference may not come from the edit",
    REFUSED: "the operator had nothing to edit in this task",
    NOT_DELIVERED: "delivery or grading raised an error",
    INVALID: "the task's control failed, so its mutants say nothing",
}

#: Task statuses.
AUDITED = "audited"
NO_WRITE = "no-write"
NO_REFERENCE = "no-reference"
CONTROL_FAILED = "control-failed"


@dataclass
class RunResult:
    task_id: str
    operator: str
    run_class: str
    verdict: str | None = None
    shape: str | None = None
    tables: dict[str, dict[str, Any]] = field(default_factory=dict)
    reason: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def operator_class(self) -> str:
        return OPERATOR_CLASS[self.operator]


@dataclass
class TaskResult:
    task_id: str
    status: str
    reason: str | None = None
    seconds: float = 0.0
    control_verdict: str | None = None
    runs: list[RunResult] = field(default_factory=list)

    @property
    def false_accepts(self) -> list[RunResult]:
        return [run for run in self.runs if run.run_class == FALSE_ACCEPT]


def _pass_class(control: Delivery, mutant: Delivery, ignore: frozenset[str]) -> RunResult:
    diff = compare(control.effect, mutant.effect, ignore)
    if diff.same:
        return RunResult("", "", EQUIVALENT, "PASS", diff.shape, diff.tables)
    if mutant.crashed_calls > control.crashed_calls:
        return RunResult(
            "",
            "",
            UNCONFIRMED,
            "PASS",
            diff.shape,
            diff.tables,
            reason=f"{mutant.crashed_calls} call(s) raised during delivery",
        )
    return RunResult("", "", FALSE_ACCEPT, "PASS", diff.shape, diff.tables)


def _classify(
    task_id: str,
    operator: str,
    control: Delivery,
    mutant: Delivery,
    control_ok: bool,
    ignore: frozenset[str],
) -> RunResult:
    if mutant.error or mutant.verdict not in ("PASS", "FAIL"):
        result = RunResult(task_id, operator, NOT_DELIVERED, reason=mutant.error or "no verdict")
    elif not control_ok:
        result = RunResult(task_id, operator, INVALID, mutant.verdict, reason="control failed")
    elif mutant.verdict == "FAIL":
        diff = compare(control.effect, mutant.effect, ignore)
        result = RunResult(task_id, operator, KILLED, "FAIL", diff.shape, diff.tables)
    else:
        result = _pass_class(control, mutant, ignore)
    result.task_id = task_id
    result.operator = operator
    return result


def _scan_repeats(
    adapter: BenchmarkAdapter, task_id: str, calls: list, ignore: frozenset[str]
) -> tuple[int | None, str | None, dict[str, Any]]:
    """Find the newest repeat that changes the end state. No verifier call."""
    candidates = repeat_candidates(calls, adapter.policy)
    if not candidates:
        return None, "NO_WRITE", {}
    runs = [Run("scan-control", list(calls), grade=False)]
    runs += [Run(f"scan-repeat-{i}", repeat_at(calls, i), grade=False) for i in candidates]
    try:
        deliveries = adapter.deliver(task_id, runs)
    except Exception as exc:  # noqa: BLE001 - a broken scan refuses extra-ni only
        return None, "SCAN_FAILED", {"error": f"{type(exc).__name__}: {exc}"}
    control = deliveries[0]
    if control.error:
        return None, "SCAN_FAILED", {"error": control.error}
    tested = []
    for index, delivery in zip(candidates, deliveries[1:]):
        if delivery.error:
            tested.append({"index": index, "error": delivery.error})
            continue
        changes = not compare(control.effect, delivery.effect, ignore).same
        tested.append({"index": index, "changes_state": changes})
        if changes:
            return index, None, {"tested": tested, "repeated": calls[index].get("url")}
    return None, "ALL_REPEATS_IDEMPOTENT", {"tested": tested}


def audit_task(
    adapter: BenchmarkAdapter,
    task_id: str,
    operators: Sequence[str] = OPERATORS,
    ignore_fields: Sequence[str] = (),
) -> TaskResult:
    """Audit one task. ``ignore_fields`` adds to the adapter's own list of
    fields with no task meaning (``field`` or ``table.field``)."""
    started = time.monotonic()
    ignore = frozenset(adapter.ignore_fields) | frozenset(ignore_fields)
    task = TaskResult(task_id, AUDITED)
    try:
        reference = adapter.reference(task_id)
    except Exception as exc:  # noqa: BLE001 - one task's failure must not end the audit
        reference = None
        task.status, task.reason = NO_REFERENCE, f"{type(exc).__name__}: {exc}"
    if reference is not None and (reference.error or not reference.calls):
        task.status, task.reason = (
            NO_REFERENCE,
            reference.error or "the reference run made no calls",
        )
    if task.status != AUDITED:
        task.seconds = round(time.monotonic() - started, 1)
        return task
    calls = reference.calls
    if not any(adapter.policy.is_effectful(call) for call in calls):
        task.status, task.reason = NO_WRITE, "the reference run writes nothing"
        task.seconds = round(time.monotonic() - started, 1)
        return task

    runs = [Run("control", list(calls))]
    for operator in operators:
        if operator == "extra-ni":
            index, refusal, detail = _scan_repeats(adapter, task_id, calls, ignore)
            if index is None:
                task.runs.append(
                    RunResult(task_id, operator, REFUSED, reason=refusal, detail=detail)
                )
                continue
            runs.append(Run(operator, repeat_at(calls, index)))
            task.runs.append(RunResult(task_id, operator, NOT_DELIVERED, detail=detail))
            continue
        edit = apply_operator(calls, operator, adapter.policy)
        if edit.refused:
            task.runs.append(
                RunResult(task_id, operator, REFUSED, reason=edit.refusal, detail=edit.detail)
            )
            continue
        runs.append(Run(operator, edit.calls))
        task.runs.append(RunResult(task_id, operator, NOT_DELIVERED, detail=edit.detail))

    try:
        deliveries = {d.run_id: d for d in adapter.deliver(task_id, runs)}
    except Exception as exc:  # noqa: BLE001 - one task's failure must not end the audit
        error = f"{type(exc).__name__}: {exc}"
        deliveries = {run.run_id: Delivery(run.run_id, error=error) for run in runs}
    control = deliveries.get("control") or Delivery("control", error="not returned")
    task.control_verdict = control.verdict
    control_ok = (
        not control.error
        and control.verdict == "PASS"
        and compare(reference.effect, control.effect, ignore).same
    )
    if not control_ok:
        task.status = CONTROL_FAILED
        if control.error:
            task.reason = f"control not delivered: {control.error}"
        elif control.verdict != "PASS":
            task.reason = f"the verifier gave the unedited reference run {control.verdict}"
        else:
            task.reason = "replaying the reference run did not reproduce its end state"

    for position, result in enumerate(task.runs):
        if result.run_class == REFUSED:
            continue
        mutant = deliveries.get(result.operator) or Delivery(result.operator, error="not returned")
        classified = _classify(task_id, result.operator, control, mutant, control_ok, ignore)
        grading = {
            key: mutant.detail[key]
            for key in ("num_tests", "num_failed")
            if mutant.detail.get(key) is not None
        }
        classified.detail = {**result.detail, **grading}
        task.runs[position] = classified
    task.seconds = round(time.monotonic() - started, 1)
    return task


@dataclass
class AuditResult:
    benchmark: dict[str, Any]
    operators: list[str]
    ignore_fields: list[str]
    tasks: list[TaskResult]
    seconds: float

    @property
    def false_accepts(self) -> list[RunResult]:
        return [run for task in self.tasks for run in task.false_accepts]

    def by_operator(self) -> dict[str, dict[str, int]]:
        table: dict[str, dict[str, int]] = {
            op: {name: 0 for name in RUN_CLASSES} for op in self.operators
        }
        for task in self.tasks:
            for run in task.runs:
                table[run.operator][run.run_class] += 1
        return table

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": "openadapt-evals/verifier-audit/v1",
            "benchmark": self.benchmark,
            "operators": [{"name": op, "class": OPERATOR_CLASS[op]} for op in self.operators],
            "ignore_fields": self.ignore_fields,
            "run_classes": RUN_CLASSES,
            "seconds": self.seconds,
            "summary": {
                "tasks": len(self.tasks),
                "tasks_audited": sum(1 for t in self.tasks if t.status == AUDITED),
                "tasks_with_false_accept": sum(1 for t in self.tasks if t.false_accepts),
                "false_accepts": len(self.false_accepts),
                "by_operator": self.by_operator(),
            },
            "tasks": [asdict(task) for task in self.tasks],
        }


def audit(
    adapter: BenchmarkAdapter,
    task_ids: Sequence[str],
    operators: Sequence[str] = OPERATORS,
    jobs: int = 1,
    progress: Callable[[int, int, TaskResult], None] | None = None,
    ignore_fields: Sequence[str] = (),
) -> AuditResult:
    """Audit ``task_ids`` with ``operators``. Tasks run in parallel when
    ``jobs > 1``; each adapter call still starts from a fresh state."""
    unknown = [op for op in operators if op not in OPERATORS]
    if unknown:
        raise ValueError(f"unknown operator(s): {', '.join(unknown)}")
    started = time.monotonic()
    results: list[TaskResult | None] = [None] * len(task_ids)
    lock = threading.Lock()
    done = 0

    def one(position: int) -> None:
        nonlocal done
        result = audit_task(adapter, task_ids[position], operators, ignore_fields)
        with lock:
            results[position] = result
            done += 1
            if progress is not None:
                progress(done, len(task_ids), result)

    if jobs <= 1:
        for position in range(len(task_ids)):
            one(position)
    else:
        with ThreadPoolExecutor(max_workers=jobs) as pool:
            list(pool.map(one, range(len(task_ids))))
    return AuditResult(
        benchmark=adapter.describe(),
        operators=list(operators),
        ignore_fields=sorted(set(adapter.ignore_fields) | set(ignore_fields)),
        tasks=[r for r in results if r is not None],
        seconds=round(time.monotonic() - started, 1),
    )


def print_progress(done: int, total: int, task: TaskResult) -> None:
    if task.status != AUDITED:
        note = f"{task.status}: {task.reason}"
    elif task.false_accepts:
        names = ", ".join(run.operator for run in task.false_accepts)
        note = f"FALSE ACCEPT ({names})"
    else:
        note = "no false accept"
    print(f"[{done}/{total}] {task.task_id}: {note} ({task.seconds:.0f}s)", file=sys.stderr)
