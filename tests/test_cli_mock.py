"""Tests for `openadapt-evals mock` (no VM, no API key)."""

import json
import sys

from openadapt_evals.benchmarks import cli


def _run_cli(monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["openadapt-evals", *argv])
    return cli.main()


def test_mock_writes_traces_under_the_requested_run_name(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert _run_cli(monkeypatch, "mock", "--tasks", "2", "--run-name", "quickstart") == 0

    out = capsys.readouterr().out
    assert "Results saved to: benchmark_results/quickstart" in out
    summary = json.loads((tmp_path / "benchmark_results" / "quickstart" / "summary.json").read_text())
    assert summary["run_name"] == "quickstart"

    # The viewer finds the run by the same name.
    assert _run_cli(monkeypatch, "view", "--run-name", "quickstart", "--no-open") == 0
    assert (tmp_path / "benchmark_results" / "quickstart" / "viewer.html").exists()


def test_mock_honors_max_steps_with_an_output_dir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    seen = {}
    # cmd_mock imports the runner from openadapt_evals.benchmarks at call time.
    import openadapt_evals.benchmarks as benchmarks

    original = benchmarks.evaluate_agent_on_benchmark

    def spy(agent, adapter, task_ids=None, max_steps=50, parallel=1, config=None):
        seen["max_steps"] = config.max_steps
        seen["output_dir"] = config.output_dir
        return original(agent, adapter, task_ids=task_ids, config=config)

    monkeypatch.setattr(benchmarks, "evaluate_agent_on_benchmark", spy)
    rc = _run_cli(
        monkeypatch, "mock", "--tasks", "1", "--max-steps", "4",
        "--output", str(tmp_path / "out"), "--run-name", "r",
    )
    assert rc == 0
    assert seen == {"max_steps": 4, "output_dir": str(tmp_path / "out")}
    assert (tmp_path / "out" / "r" / "summary.json").exists()
