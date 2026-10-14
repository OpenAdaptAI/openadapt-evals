"""The interface a benchmark implements to be audited.

An adapter does four things, none of which involve a model:

1. ``reference``: produce a correct run for a task (the benchmark's own
   solution, recorded as a list of API calls) and its effect.
2. ``deliver``: replay runs, each from a fresh start state, read the end
   state back, and only then call the benchmark's own verifier, unmodified.
3. Say which fields carry no task meaning (``ignore_fields``: ids,
   timestamps) so effects can be compared.
4. Say how to read its calls (``policy``: which calls sign in, which claim
   success, which fields an edit must not touch).

The readback must not use the verifier's assertions. It may read the same
database the verifier reads.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol, Sequence, runtime_checkable

from openadapt_evals.verifier_audit.effects import Effect
from openadapt_evals.verifier_audit.operators import Call, CallPolicy


class SetupError(RuntimeError):
    """The benchmark is not installed or not reachable. The message says how
    to set it up."""


@dataclass
class Reference:
    """A correct run for one task, and what it changed."""

    task_id: str
    calls: list[Call]
    effect: Effect
    error: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass
class Run:
    """One run to deliver. ``grade=False`` reads the effect back without
    calling the verifier (the repeat scan uses this)."""

    run_id: str
    calls: list[Call]
    grade: bool = True


@dataclass
class Delivery:
    """What happened when one run was delivered from a fresh start state.

    ``verdict`` is ``"PASS"`` or ``"FAIL"`` from the benchmark's own
    verifier, or ``None`` when the run was not graded or grading failed.
    ``statuses`` holds one status per call: an HTTP-style code, or -1 when
    the call raised instead of returning.
    """

    run_id: str
    effect: Effect = field(default_factory=dict)
    verdict: str | None = None
    statuses: list[int] = field(default_factory=list)
    error: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def crashed_calls(self) -> int:
        return sum(1 for status in self.statuses if status == -1)


@runtime_checkable
class BenchmarkAdapter(Protocol):
    name: str
    ignore_fields: frozenset[str]
    policy: CallPolicy

    def describe(self) -> dict[str, Any]:
        """Versions and settings to record in the report."""

    def task_ids(self, split: str | None, limit: int | None) -> list[str]:
        """Task ids to audit when the user names none."""

    def reference(self, task_id: str) -> Reference:
        """Run the task's own solution from a fresh start state."""

    def deliver(self, task_id: str, runs: Sequence[Run]) -> list[Delivery]:
        """Deliver each run from a fresh start state; one Delivery per run, in order."""
