"""Regression tests: EvaluatorClient must not render a failure as a result.

The reported defect: ``_load_evaluators`` swallowed ``ImportError``, so a broken
WAA evaluators install and a healthy one produced the same client, and every
later run was silently scored by the built-in fallback evaluator. PR #275 added
a ``logger.warning`` and returned the same fallback-configured client, which is
the same bug with better documentation -- a caller still could not tell.

Each test here fails against the pre-fix (log-only) implementation.
"""

from __future__ import annotations

import builtins
from pathlib import Path

import pytest
import requests

from openadapt_evals.evaluation.client import (
    EvaluationError,
    EvaluationResult,
    EvaluatorClient,
    EvaluatorsUnavailableError,
)


@pytest.fixture
def broken_evaluators(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A WAA evaluators tree that is present on disk but raises on import.

    This is the *broken install* case, which is what must be distinguishable
    from the legitimately-absent optional case.
    """
    desktop_env = tmp_path / "desktop_env"
    evaluators = desktop_env / "evaluators"
    evaluators.mkdir(parents=True)
    (evaluators / "__init__.py").write_text("")
    (evaluators / "getters.py").write_text("")

    real_import = builtins.__import__

    def _raising_import(name, *args, **kwargs):
        if name == "evaluators":
            raise ImportError("cannot import name 'getters' from 'evaluators'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _raising_import)
    return desktop_env


def test_broken_evaluators_install_raises_instead_of_silently_falling_back(
    broken_evaluators: Path,
) -> None:
    """A present-but-unimportable evaluators package must not construct a client.

    Pre-fix this returned a perfectly usable client whose every result was
    fallback-scored, with nothing in the object or in any result recording it.
    """
    with pytest.raises(EvaluatorsUnavailableError) as excinfo:
        EvaluatorClient(vm_ip="10.0.0.1", waa_evaluators_path=broken_evaluators)

    message = str(excinfo.value)
    assert "not importable" in message
    assert "the install is broken, not absent" in message
    assert str(broken_evaluators) in message


def test_missing_evaluators_reports_absent_not_broken(tmp_path: Path) -> None:
    """The absent case must be reported differently from the broken case."""
    with pytest.raises(EvaluatorsUnavailableError) as excinfo:
        EvaluatorClient(vm_ip="10.0.0.1", waa_evaluators_path=tmp_path / "nope")

    message = str(excinfo.value)
    assert "not importable" in message or "not found" in message
    # Distinguishable from the broken-install wording.
    assert "the install is broken, not absent" not in message


def test_deliberate_fallback_is_opt_in_and_stamped_on_every_result(
    broken_evaluators: Path,
) -> None:
    """Opting into fallback scoring is allowed, but never invisible."""
    client = EvaluatorClient(
        vm_ip="10.0.0.1",
        waa_evaluators_path=broken_evaluators,
        require_waa_evaluators=False,
    )

    assert client.evaluator_source == "fallback"
    assert client.evaluators_error is not None

    result = client.evaluate({})
    assert result.evaluator_source == "fallback"


def test_unreachable_vm_is_not_a_measured_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """An unreachable backend must not be published as a legitimate 0.0."""
    client = EvaluatorClient(
        vm_ip="10.0.0.1",
        waa_evaluators_path=tmp_path,
        require_waa_evaluators=False,
    )

    def _refuse(*_args, **_kwargs):
        raise requests.ConnectionError("connection refused")

    monkeypatch.setattr(requests, "post", _refuse)

    result = client.evaluate(
        {
            "evaluator": {
                "result": {"type": "file_content", "path": "C:/out.txt"},
                "expected": {"value": "hello"},
                "func": "exact_match",
            }
        }
    )

    assert result.score == 0.0
    assert result.success is False
    # The point of the fix: score 0.0 here is NOT a measurement.
    assert result.scored is False
    assert result.error_type == "infrastructure"
    assert result.to_dict()["scored"] is False


def test_vm_reported_command_error_is_not_an_empty_measurement(
    tmp_path: Path,
) -> None:
    """A getter whose command failed must not be scored as empty output."""
    client = EvaluatorClient(
        vm_ip="10.0.0.1",
        waa_evaluators_path=tmp_path,
        require_waa_evaluators=False,
    )

    with pytest.raises(EvaluationError):
        client._require_output({"error": "WinError 5", "output": ""}, "file_content")


def test_unknown_metric_name_is_not_silently_scored_with_exact_match(
    tmp_path: Path,
) -> None:
    """Substituting a different metric publishes a number nobody requested."""
    client = EvaluatorClient(
        vm_ip="10.0.0.1",
        waa_evaluators_path=tmp_path,
        require_waa_evaluators=False,
    )

    with pytest.raises(EvaluationError):
        client._fallback_metric("check_csv_content", "a", "a")


def test_known_metric_still_scores_normally(tmp_path: Path) -> None:
    """The fix must not break the healthy path."""
    client = EvaluatorClient(
        vm_ip="10.0.0.1",
        waa_evaluators_path=tmp_path,
        require_waa_evaluators=False,
    )

    assert client._fallback_metric("exact_match", "a", "a") == 1.0
    assert client._fallback_metric("exact_match", "a", "b") == 0.0


def test_missing_evaluator_config_is_flagged_not_scored(tmp_path: Path) -> None:
    """A task with no evaluator spec was never measured."""
    client = EvaluatorClient(
        vm_ip="10.0.0.1",
        waa_evaluators_path=tmp_path,
        require_waa_evaluators=False,
    )

    result = client.evaluate({})
    assert isinstance(result, EvaluationResult)
    assert result.scored is False
    assert result.error_type == "evaluation"
