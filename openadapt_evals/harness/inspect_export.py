"""Serialize meta-benchmark rows to an Inspect eval-log (``.eval``) JSON.

Inspect (the UK AISI eval framework, ``inspect_ai``) has a widely-used log
viewer + leaderboard. This module makes a meta-benchmark run PORTABLE to that
ecosystem by writing a subset of the Inspect eval-log schema -- WITHOUT adopting
Inspect as the runtime (no ``inspect_ai`` dependency, no Inspect ``Task`` /
``Solver`` / ``Scorer``). We keep our own :class:`Environment` + :func:`run_meta`
runtime and only borrow the log format on the way out.

The emitted document is a plain dict (JSON-serializable). Each meta row becomes
one Inspect ``sample`` with a boolean-mapped score (``"C"`` correct / ``"I"``
incorrect) and our full row under ``metadata`` so the round-trip is lossless.
:func:`from_inspect_eval_log` reconstructs the rows for tests / re-import.
"""

from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Inspect's canonical value for a correct/incorrect boolean score.
_CORRECT = "C"
_INCORRECT = "I"

_SCHEMA_VERSION = 2  # Inspect eval-log major version this subset targets.


def _row_to_dict(row: Any) -> dict:
    if is_dataclass(row) and not isinstance(row, type):
        as_dict = getattr(row, "as_dict", None)
        return as_dict() if callable(as_dict) else asdict(row)
    if isinstance(row, dict):
        return dict(row)
    raise TypeError(f"cannot serialize row of type {type(row).__name__}")


def to_inspect_eval_log(
    rows: "list[Any]",
    *,
    task_name: str = "openadapt-meta-benchmark",
    model: str = "openadapt-flow/compiled",
    created: str | None = None,
) -> dict:
    """Build an Inspect eval-log dict from meta-benchmark rows.

    Args:
        rows: :class:`MetaMetricsRow` objects (or their dicts).
        task_name: Inspect ``eval.task`` name.
        model: Inspect ``eval.model`` label.
        created: ISO timestamp (defaults to now, UTC).

    Returns:
        A dict conforming to the Inspect eval-log subset. Serialize with
        :func:`json.dumps` or :func:`write_inspect_eval_log`.
    """
    created = created or datetime.now(timezone.utc).isoformat()
    dict_rows = [_row_to_dict(r) for r in rows]

    samples = []
    for i, r in enumerate(dict_rows):
        success = bool(r.get("replay_success", False))
        samples.append(
            {
                "id": r.get("task_id", f"sample_{i}"),
                "epoch": 1,
                "input": r.get("task_id", ""),
                "target": _CORRECT,
                "scores": {
                    "meta_verifier": {
                        "value": _CORRECT if success else _INCORRECT,
                        "answer": str(r.get("effect_verdict") or r.get("verifier_source") or ""),
                        "explanation": r.get("error") or "",
                        "metadata": {
                            "env": r.get("env"),
                            "mode": r.get("mode"),
                            "model_calls": r.get("model_calls"),
                            "structural_rung_rate": r.get("structural_rung_rate"),
                            "wall_ms": r.get("wall_ms"),
                            "cost_usd": r.get("cost_usd"),
                        },
                    }
                },
                # Full lossless row so from_inspect_eval_log round-trips.
                "metadata": r,
            }
        )

    total = len(samples)
    correct = sum(1 for s in samples if s["scores"]["meta_verifier"]["value"] == _CORRECT)

    return {
        "version": _SCHEMA_VERSION,
        "status": "success",
        "eval": {
            "task": task_name,
            "model": model,
            "created": created,
            "dataset": {"name": task_name, "samples": total},
        },
        "results": {
            "total_samples": total,
            "completed_samples": total,
            "scores": [
                {
                    "name": "meta_verifier",
                    "scorer": "meta_verifier",
                    "metrics": {
                        "accuracy": {
                            "name": "accuracy",
                            "value": (correct / total) if total else 0.0,
                        }
                    },
                }
            ],
        },
        "samples": samples,
    }


def from_inspect_eval_log(doc: dict) -> "list[dict]":
    """Reconstruct meta-benchmark row dicts from an Inspect eval-log dict.

    Prefers the lossless ``metadata`` payload written by
    :func:`to_inspect_eval_log`; falls back to reconstructing from the score
    value + score metadata for logs produced elsewhere.
    """
    rows: list[dict] = []
    for sample in doc.get("samples", []):
        meta = sample.get("metadata")
        if isinstance(meta, dict) and "replay_success" in meta:
            rows.append(dict(meta))
            continue
        score = sample.get("scores", {}).get("meta_verifier", {})
        smeta = score.get("metadata", {})
        rows.append(
            {
                "task_id": sample.get("id"),
                "env": smeta.get("env"),
                "mode": smeta.get("mode"),
                "replay_success": score.get("value") == _CORRECT,
                "effect_verdict": score.get("answer") or None,
                "model_calls": smeta.get("model_calls"),
                "structural_rung_rate": smeta.get("structural_rung_rate"),
                "wall_ms": smeta.get("wall_ms"),
                "cost_usd": smeta.get("cost_usd"),
                "error": score.get("explanation") or None,
            }
        )
    return rows


def write_inspect_eval_log(rows: "list[Any]", path: Path | str, **kwargs: Any) -> Path:
    """Write rows to ``path`` as Inspect eval-log JSON; return the path.

    ``.eval`` files are ZIP archives in Inspect proper; this writes the JSON
    document (``.eval.json`` recommended) that the log tooling also reads.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = to_inspect_eval_log(rows, **kwargs)
    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    return path


__all__ = [
    "to_inspect_eval_log",
    "from_inspect_eval_log",
    "write_inspect_eval_log",
]
