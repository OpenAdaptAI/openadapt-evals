"""Shared metric implementations for evaluation.

Single source of truth for metric functions used by both the client-side
evaluator (evaluation/client.py) and the server-side evaluate endpoint
(server/evaluate_endpoint.py).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def exact_match(result: Any, expected: Any, **options) -> float:
    """Exact string/value match."""
    if result == expected:
        return 1.0
    if str(result).strip() == str(expected).strip():
        return 1.0
    return 0.0


def fuzzy_match(
    result: Any, expected: Any, threshold: float = 0.8, **options
) -> float:
    """Fuzzy string matching using rapidfuzz (character-level Levenshtein).

    Falls back to substring containment when rapidfuzz is not installed.
    """
    try:
        from rapidfuzz import fuzz

        score = fuzz.ratio(str(result), str(expected)) / 100.0
        return 1.0 if score >= threshold else score
    except ImportError:
        result_str = str(result).lower()
        expected_str = str(expected).lower()
        if expected_str in result_str or result_str in expected_str:
            return 0.8
        return 0.0


def contains(result: Any, expected: Any, **options) -> float:
    """Check if result contains expected (case-insensitive)."""
    result_str = str(result).lower()
    expected_str = str(expected).lower()
    return 1.0 if expected_str in result_str else 0.0


def boolean(result: Any, expected: Any, **options) -> float:
    """Boolean equality check."""
    return 1.0 if bool(result) == bool(expected) else 0.0


def file_exists(result: Any, expected: Any, **options) -> float:
    """Check if file exists."""
    path = result if result else expected
    if path and Path(path).exists():
        return 1.0
    return 0.0


def get_metric(name: str):
    """Look up a metric function by name. Returns None if not found."""
    return _METRICS.get(name)


_METRICS = {
    "exact_match": exact_match,
    "fuzzy_match": fuzzy_match,
    "contains": contains,
    "boolean": boolean,
    "file_exists": file_exists,
}
