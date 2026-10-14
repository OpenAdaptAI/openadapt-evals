"""Audit a benchmark's verifier: which wrong side effects does it accept?

Take a correct run, make one hand-written edit (drop a write, change a
value, repeat a write), replay it from a fresh start state, read the end
state back, and only then ask the benchmark's own verifier. An edit the
verifier passes although the end state differs from the correct run's is a
confirmed false accept.

Command line::

    openadapt-evals audit-verifier --benchmark toy
    openadapt-evals audit-verifier --benchmark appworld --tasks 22cc237_1

Python::

    from openadapt_evals.verifier_audit import audit
    from openadapt_evals.verifier_audit.adapters.toy import ToyAdapter

    result = audit(ToyAdapter(), ["split-bill"])
    print([run.operator for run in result.false_accepts])

This is the method of "Verifier²: Finding Loopholes in Verifiable Rewards".
It ships the mechanism only: the operators, the delivery and readback loop,
and the classification. Benchmark code and data are installed by the user
and read at run time.
"""

from openadapt_evals.verifier_audit.adapters.base import (
    BenchmarkAdapter,
    Delivery,
    Reference,
    Run,
    SetupError,
)
from openadapt_evals.verifier_audit.effects import EffectDiff, compare, normalize
from openadapt_evals.verifier_audit.operators import (
    FRAME_OPERATORS,
    OPERATORS,
    POSTCONDITION_OPERATORS,
    CallPolicy,
    Edit,
    apply_operator,
    repeat_at,
    repeat_candidates,
)
from openadapt_evals.verifier_audit.runner import (
    RUN_CLASSES,
    AuditResult,
    RunResult,
    TaskResult,
    audit,
    audit_task,
)

__all__ = [
    "FRAME_OPERATORS",
    "OPERATORS",
    "POSTCONDITION_OPERATORS",
    "RUN_CLASSES",
    "AuditResult",
    "BenchmarkAdapter",
    "CallPolicy",
    "Delivery",
    "Edit",
    "EffectDiff",
    "Reference",
    "Run",
    "RunResult",
    "SetupError",
    "TaskResult",
    "apply_operator",
    "audit",
    "audit_task",
    "compare",
    "normalize",
    "repeat_at",
    "repeat_candidates",
]
