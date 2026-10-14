"""Effects: what a run changed, and how two effects differ.

An effect maps a table name to the records the run added, removed and
updated::

    {"venmo.PaymentRequest": {"added": [{...}], "removed": [], "updated": [
        {"before": {...}, "after": {...}}]}}

Two effects are compared as multisets of records after dropping the fields
that carry no task meaning (ids, timestamps). A second identical record
counts, so a duplicated write shows up even when its content is correct.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Iterable

Effect = dict[str, dict[str, list[Any]]]

#: How a mutant's effect relates to the control's.
SAME = "same"  # equal after dropping the ignored fields
ADDS = "adds"  # everything the control did, plus more
REMOVES = "removes"  # part of what the control did, and nothing else
CHANGES = "changes"  # some of each


def _strip(record: Any, ignore: frozenset[str], table: str = "") -> Any:
    """Drop ignored fields. An entry is a field name (any table) or
    ``table.field`` (that table only)."""
    if not isinstance(record, dict):
        return record
    return {
        k: v for k, v in sorted(record.items()) if k not in ignore and f"{table}.{k}" not in ignore
    }


def _items(effect: Effect, ignore: frozenset[str]) -> Iterable[tuple[str, str, str]]:
    for table in sorted(effect or {}):
        changes = effect[table] or {}
        for kind in ("added", "removed"):
            for record in changes.get(kind) or []:
                yield table, kind, json.dumps(_strip(record, ignore, table), sort_keys=True)
        for record in changes.get("updated") or []:
            before = _strip(record.get("before", {}), ignore, table)
            after = _strip(record.get("after", {}), ignore, table)
            if before == after:
                # Only ignored fields changed: no task-relevant update.
                continue
            yield table, "updated", json.dumps([before, after], sort_keys=True)


def normalize(effect: Effect, ignore: Iterable[str] = ()) -> Counter:
    """The effect as a multiset of (table, kind, record) with ``ignore`` dropped."""
    return Counter(_items(effect, frozenset(ignore)))


@dataclass
class EffectDiff:
    """How a mutant's effect differs from the control's.

    ``tables`` maps each table that differs to counts and field names:
    ``"+"`` records the mutant has and the control lacks, ``"-"`` the
    reverse, ``"changed"`` records present in both but with different
    values, and ``"fields"`` the names of the fields that differ in those.
    Values are never copied into the diff, so a report can be shared.
    """

    shape: str
    tables: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def same(self) -> bool:
        return self.shape == SAME

    def summary(self) -> str:
        return summarize(self.tables)


def summarize(tables: dict[str, dict[str, Any]]) -> str:
    """One line per diff, such as ``venmo.PaymentRequest +1`` or
    ``spotify.MusicPlayer: song_ids changed``."""
    if not tables:
        return "same end state as the reference run"
    parts = []
    for table, counts in sorted(tables.items()):
        if counts.get("changed"):
            fields = ", ".join(counts.get("fields") or []) or "values"
            parts.append(f"{table}: {fields} changed")
        if counts.get("+"):
            parts.append(f"{table} +{counts['+']}")
        if counts.get("-"):
            parts.append(f"{table} -{counts['-']}")
    return ", ".join(parts)


def _final(kind: str, record: Any) -> dict:
    """The record as it ends up: for an update, its after-image."""
    if kind == "updated" and isinstance(record, list) and len(record) == 2:
        return record[1] if isinstance(record[1], dict) else {}
    return record if isinstance(record, dict) else {}


def _differing(a: dict, b: dict) -> set[str]:
    return {key for key in set(a) | set(b) if a.get(key) != b.get(key)}


def compare(control: Effect, mutant: Effect, ignore: Iterable[str] = ()) -> EffectDiff:
    """Compare a mutant's effect with the control's, record by record."""
    ignore = frozenset(ignore)
    a = normalize(control, ignore)
    b = normalize(mutant, ignore)
    more = b - a
    less = a - b
    if not more and not less:
        return EffectDiff(SAME)
    shape = ADDS if not less else REMOVES if not more else CHANGES

    tables: dict[str, dict[str, Any]] = {}
    unmatched_less: dict[tuple[str, str], list[dict]] = {}
    for (table, kind, record), n in less.items():
        unmatched_less.setdefault((table, kind), []).extend([_final(kind, json.loads(record))] * n)
    for (table, kind, record), n in sorted(more.items()):
        entry = tables.setdefault(table, {"+": 0, "-": 0, "changed": 0, "fields": set()})
        mine = _final(kind, json.loads(record))
        for _ in range(n):
            pool = unmatched_less.get((table, kind)) or []
            if pool:
                # Pair with the closest record the control has and the mutant lacks.
                best = min(range(len(pool)), key=lambda i: len(_differing(mine, pool[i])))
                entry["changed"] += 1
                entry["fields"] |= _differing(mine, pool.pop(best))
            else:
                entry["+"] += 1
    for (table, _kind), pool in unmatched_less.items():
        if pool:
            entry = tables.setdefault(table, {"+": 0, "-": 0, "changed": 0, "fields": set()})
            entry["-"] += len(pool)
    for entry in tables.values():
        entry["fields"] = sorted(entry["fields"])
    return EffectDiff(shape=shape, tables=tables)
