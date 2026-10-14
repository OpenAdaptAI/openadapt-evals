"""Operators: one hand-written edit to a correct run.

A run is a list of API calls, each a dict with ``method``, ``url`` and
``data``. An operator takes the reference run (one the verifier passes) and
makes exactly one edit. Each operator either returns the edited run or
refuses, with a reason, when the run gives it nothing to edit.

Postcondition operators remove or change part of the requested effect, so a
correct verifier must fail them:

``claim-only``   keep only the sign-in and claim calls, so nothing is written.
``omit``         drop the last write.
``partial``      of the most repeated write, keep only the first.
``wrong-value``  change one value in the last write.

Frame operators add an effect the task never asked for. A verifier that
checks only what must change, and not that nothing else changed, passes them:

``extra``        repeat the last write.
``extra-ni``     repeat the last write whose repeat changes the end state,
                 found by replaying each candidate repeat without calling the
                 verifier (``repeat_candidates``).

These are the operators of the Verifier-squared paper ("Verifier²: Finding
Loopholes in Verifiable Rewards"), restated for any benchmark whose runs are
API calls. They are fixed rules, not tuned or searched.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from typing import Any, Callable

Call = dict[str, Any]

POSTCONDITION_OPERATORS: tuple[str, ...] = ("claim-only", "omit", "partial", "wrong-value")
FRAME_OPERATORS: tuple[str, ...] = ("extra", "extra-ni")
OPERATORS: tuple[str, ...] = POSTCONDITION_OPERATORS + FRAME_OPERATORS

OPERATOR_CLASS: dict[str, str] = {
    **{name: "postcondition" for name in POSTCONDITION_OPERATORS},
    **{name: "frame" for name in FRAME_OPERATORS},
}

OPERATOR_DESCRIPTION: dict[str, str] = {
    "claim-only": "claim success and write nothing",
    "omit": "drop the last write",
    "partial": "keep only the first of a repeated write",
    "wrong-value": "change one value in the last write",
    "extra": "repeat the last write",
    "extra-ni": "repeat the last write whose repeat changes the end state",
}

_DIGITS = re.compile(r"\d+")


def _method(call: Call) -> str:
    return str(call.get("method", "get")).lower()


def _url(call: Call) -> str:
    return str(call.get("url", ""))


def default_is_auth(call: Call) -> bool:
    return "/auth/token" in _url(call)


def default_is_claim(call: Call) -> bool:
    return _url(call).lstrip("/").startswith("supervisor")


@dataclass(frozen=True)
class CallPolicy:
    """How a benchmark's calls are read. The defaults match AppWorld.

    ``is_auth``: the call signs in and writes nothing the task asks for.
    ``is_claim``: the call reports the task done (AppWorld's
    ``complete_task``).
    ``protected_fields``: request fields ``wrong-value`` must not touch,
    because changing them breaks the call rather than its value.
    """

    is_auth: Callable[[Call], bool] = default_is_auth
    is_claim: Callable[[Call], bool] = default_is_claim
    protected_fields: frozenset[str] = frozenset({"access_token", "username", "password"})

    def is_effectful(self, call: Call) -> bool:
        """A write the task could ask for: not a read, a sign-in or a claim."""
        return _method(call) != "get" and not self.is_auth(call) and not self.is_claim(call)


DEFAULT_POLICY = CallPolicy()


@dataclass
class Edit:
    """The result of applying one operator to a reference run."""

    operator: str
    calls: list[Call] | None
    refusal: str | None = None
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def refused(self) -> bool:
        return self.calls is None


def endpoint(call: Call) -> tuple[str, str]:
    """Method and URL with record ids replaced, so repeated writes group."""
    return (_method(call), _DIGITS.sub("{id}", _url(call)))


def _effectful_indexes(calls: list[Call], policy: CallPolicy) -> list[int]:
    return [i for i, call in enumerate(calls) if policy.is_effectful(call)]


def _wrong_value(call: Call, policy: CallPolicy) -> tuple[Call, str] | None:
    """Change one written value: the first string
    longer than three characters gets a letter appended; failing that, the
    first number goes up by one, or the first boolean flips."""
    edited = copy.deepcopy(call)
    data = edited.get("data")
    if not isinstance(data, dict):
        return None
    for name, value in data.items():
        if name in policy.protected_fields:
            continue
        if isinstance(value, str) and len(value) > 3:
            data[name] = value + ("y" if value.endswith("x") else "x")
            return edited, name
    for name, value in data.items():
        if name in policy.protected_fields:
            continue
        if isinstance(value, bool):
            data[name] = not value
            return edited, name
        if isinstance(value, (int, float)):
            data[name] = value + 1
            return edited, name
    return None


def apply_operator(calls: list[Call], operator: str, policy: CallPolicy = DEFAULT_POLICY) -> Edit:
    """Apply one operator to ``calls``. ``extra-ni`` needs ``repeat_at`` and a
    scan, so it is not handled here."""
    if operator not in OPERATORS or operator == "extra-ni":
        raise ValueError(f"apply_operator does not handle {operator!r}")
    effectful = _effectful_indexes(calls, policy)
    detail: dict[str, Any] = {"calls": len(calls), "writes": len(effectful)}
    if not effectful:
        return Edit(operator, None, "NO_WRITE", detail)

    if operator == "claim-only":
        if not any(policy.is_claim(call) for call in calls):
            return Edit(operator, None, "NO_CLAIM_CALL", detail)
        kept = [c for c in calls if policy.is_auth(c) or policy.is_claim(c)]
        detail["kept"] = len(kept)
        return Edit(operator, kept, None, detail)

    last = effectful[-1]
    if operator == "omit":
        detail["dropped"] = _url(calls[last])
        return Edit(operator, [c for i, c in enumerate(calls) if i != last], None, detail)

    if operator == "extra":
        edited = list(calls)
        edited.insert(last + 1, copy.deepcopy(calls[last]))
        detail["repeated"] = _url(calls[last])
        return Edit(operator, edited, None, detail)

    if operator == "wrong-value":
        changed = _wrong_value(calls[last], policy)
        if changed is None:
            return Edit(operator, None, "NO_CHANGEABLE_VALUE", detail)
        edited_call, field_name = changed
        detail["changed"] = {"url": _url(calls[last]), "field": field_name}
        edited = list(calls)
        edited[last] = edited_call
        return Edit(operator, edited, None, detail)

    # partial
    groups: dict[tuple[str, str], list[int]] = {}
    for i in effectful:
        groups.setdefault(endpoint(calls[i]), []).append(i)
    repeated = {key: idx for key, idx in groups.items() if len(idx) >= 2}
    if not repeated:
        return Edit(operator, None, "NO_REPEATED_WRITE", detail)
    key = max(repeated, key=lambda k: (len(repeated[k]), max(repeated[k])))
    drop = set(repeated[key][1:])
    detail["endpoint"] = key[1]
    detail["dropped"] = len(drop)
    return Edit(operator, [c for i, c in enumerate(calls) if i not in drop], None, detail)


def repeat_candidates(calls: list[Call], policy: CallPolicy = DEFAULT_POLICY) -> list[int]:
    """Indexes ``extra-ni`` may repeat: the last call to each distinct write
    endpoint, newest first."""
    last_by_endpoint: dict[tuple[str, str], int] = {}
    for i, call in enumerate(calls):
        if policy.is_effectful(call):
            last_by_endpoint[endpoint(call)] = i
    return sorted(last_by_endpoint.values(), reverse=True)


def repeat_at(calls: list[Call], index: int) -> list[Call]:
    """``calls`` with the call at ``index`` sent twice in a row."""
    edited = list(calls)
    edited.insert(index + 1, copy.deepcopy(calls[index]))
    return edited
