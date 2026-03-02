"""Tests for shared evaluation metrics module."""

from openadapt_evals.evaluation.metrics import (
    exact_match,
    fuzzy_match,
    contains,
    boolean,
    get_metric,
)


class TestExactMatch:
    def test_equal_strings(self):
        assert exact_match("hello", "hello") == 1.0

    def test_unequal_strings(self):
        assert exact_match("hello", "world") == 0.0

    def test_whitespace_stripped(self):
        assert exact_match("hello ", " hello") == 1.0

    def test_numbers(self):
        assert exact_match(42, 42) == 1.0
        assert exact_match(42, 43) == 0.0


class TestFuzzyMatch:
    def test_exact_match_high_score(self):
        # With rapidfuzz: 1.0 (above threshold). Without: 0.8 (substring match).
        assert fuzzy_match("hello", "hello") >= 0.8

    def test_completely_different(self):
        score = fuzzy_match("abc", "xyz")
        assert score < 0.5

    def test_containment_fallback(self):
        # "world" is contained in "hello world" — should score > 0
        assert fuzzy_match("hello world", "world") > 0.0


class TestContains:
    def test_positive(self):
        assert contains("hello world", "world") == 1.0

    def test_negative(self):
        assert contains("hello world", "foo") == 0.0

    def test_case_insensitive(self):
        assert contains("Hello World", "WORLD") == 1.0


class TestBoolean:
    def test_both_truthy(self):
        assert boolean(1, True) == 1.0

    def test_both_falsy(self):
        assert boolean(0, False) == 1.0

    def test_mismatch(self):
        assert boolean(1, False) == 0.0


class TestGetMetric:
    def test_known_metric(self):
        assert get_metric("exact_match") is exact_match
        assert get_metric("fuzzy_match") is fuzzy_match
        assert get_metric("contains") is contains

    def test_unknown_returns_none(self):
        assert get_metric("nonexistent") is None
