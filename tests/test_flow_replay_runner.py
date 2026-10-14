"""Tests for the demonstrate-then-replay runner (fully mocked; no flow, no VM)."""

import sys
from pathlib import Path
from types import SimpleNamespace

from openadapt_evals.adapters.base import BenchmarkResult, BenchmarkTask
from openadapt_evals.adapters.waa.live import SyntheticTaskError
from openadapt_evals.flow.replay_runner import (
    FlowTask,
    aggregate_replay_metrics,
    load_waa_tasks,
    run_demonstrate_then_replay,
    waa_live_hooks,
)


def _fake_report(success=True, terminal="success", rungs=None, model_calls=0,
                 heal=0, n_steps=5):
    return SimpleNamespace(
        success=success,
        terminal_outcome=terminal,
        rung_counts=rungs or {"primary": n_steps},
        heal_count=heal,
        model_calls=model_calls,
        est_model_cost_usd=0.0,
        total_ms=1234.0,
        results=[object()] * n_steps,
    )


def test_healthy_replay_scored_by_waa_verifier(tmp_path):
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    tasks = [FlowTask("waa_task_1", bundle_dir=bundle)]

    def replay_fn(bundle_dir, server_url, run_dir, params):
        assert Path(bundle_dir) == bundle
        assert server_url == "http://localhost:5001"
        return _fake_report(success=True, terminal="success", model_calls=0)

    def evaluator(task_id):
        assert task_id == "waa_task_1"
        return True, None

    metrics = run_demonstrate_then_replay(
        tasks, "http://localhost:5001", tmp_path / "runs",
        replay_fn=replay_fn, evaluator=evaluator,
    )
    m = metrics[0]
    assert m.waa_verified_success is True      # ground truth, not self-report
    assert m.replay_reported_success is True
    assert m.model_calls == 0                  # ~0 model calls on healthy replay
    assert m.halted is False
    assert m.rung_fire_rate > 0


def test_halted_replay_marked_and_verifier_can_disagree(tmp_path):
    bundle = tmp_path / "b"
    bundle.mkdir()
    tasks = [FlowTask("t", bundle_dir=bundle)]

    def replay_fn(*a):
        return _fake_report(success=False, terminal="halt")

    def evaluator(task_id):
        return False, "state check failed"

    m = run_demonstrate_then_replay(
        tasks, "http://x", tmp_path / "r", replay_fn=replay_fn, evaluator=evaluator
    )[0]
    assert m.halted is True
    assert m.waa_verified_success is False
    assert m.error == "state check failed"


def test_missing_bundle_is_flagged_not_faked(tmp_path):
    tasks = [FlowTask("no_bundle", bundle_dir=tmp_path / "does_not_exist")]
    calls = []

    def replay_fn(*a):
        calls.append(a)
        return _fake_report()

    m = run_demonstrate_then_replay(
        tasks, "http://x", tmp_path / "r", replay_fn=replay_fn
    )[0]
    assert not calls                      # replay never invoked for a missing bundle
    assert "no compiled bundle" in m.error
    assert m.waa_verified_success is None


def test_replay_exception_is_isolated(tmp_path):
    b1 = tmp_path / "b1"
    b1.mkdir()
    b2 = tmp_path / "b2"
    b2.mkdir()

    def replay_fn(bundle_dir, *a):
        if Path(bundle_dir) == b1:
            raise RuntimeError("backend blew up")
        return _fake_report()

    metrics = run_demonstrate_then_replay(
        [FlowTask("bad", bundle_dir=b1), FlowTask("good", bundle_dir=b2)],
        "http://x", tmp_path / "r", replay_fn=replay_fn,
    )
    assert metrics[0].error and "backend blew up" in metrics[0].error
    assert metrics[0].halted is True
    assert metrics[1].replay_reported_success is True   # second task still ran


def test_aggregate(tmp_path):
    b = tmp_path / "b"
    b.mkdir()

    def replay_fn(*a):
        return _fake_report(success=True, model_calls=0)

    metrics = run_demonstrate_then_replay(
        [FlowTask(f"t{i}", bundle_dir=b) for i in range(3)],
        "http://x", tmp_path / "r", replay_fn=replay_fn,
        evaluator=lambda tid: (True, None),
    )
    agg = aggregate_replay_metrics(metrics)
    assert agg["num_tasks"] == 3
    assert agg["waa_verified_success"] == 3
    assert agg["waa_verified_success_rate"] == 1.0
    assert agg["total_model_calls"] == 0
    assert agg["num_halted"] == 0


def test_no_openadapt_flow_import_during_mocked_run(tmp_path):
    b = tmp_path / "b"
    b.mkdir()
    run_demonstrate_then_replay(
        [FlowTask("t", bundle_dir=b)], "http://x", tmp_path / "r",
        replay_fn=lambda *a: _fake_report(),
    )
    assert "openadapt_flow" not in sys.modules


def test_setup_runs_before_each_replay(tmp_path):
    b = tmp_path / "b"
    b.mkdir()
    events = []

    def setup_fn(task_id):
        events.append(("setup", task_id))

    def replay_fn(*a):
        events.append(("replay",))
        return _fake_report()

    def evaluator(task_id):
        events.append(("evaluate", task_id))
        return True, None

    run_demonstrate_then_replay(
        [FlowTask("t1", bundle_dir=b), FlowTask("t2", bundle_dir=b)],
        "http://x", tmp_path / "r",
        replay_fn=replay_fn, setup_fn=setup_fn, evaluator=evaluator,
    )
    assert events == [
        ("setup", "t1"), ("replay",), ("evaluate", "t1"),
        ("setup", "t2"), ("replay",), ("evaluate", "t2"),
    ]


def test_failed_setup_skips_replay_and_scoring(tmp_path):
    b = tmp_path / "b"
    b.mkdir()
    replays = []
    evaluated = []

    def setup_fn(task_id):
        if task_id == "bad":
            raise RuntimeError("app did not open")

    def replay_fn(*a):
        replays.append(a)
        return _fake_report()

    def evaluator(task_id):
        evaluated.append(task_id)
        return True, None

    metrics = run_demonstrate_then_replay(
        [FlowTask("bad", bundle_dir=b), FlowTask("good", bundle_dir=b)],
        "http://x", tmp_path / "r",
        replay_fn=replay_fn, setup_fn=setup_fn, evaluator=evaluator,
    )
    assert metrics[0].error == "task setup failed: app did not open"
    assert metrics[0].waa_verified_success is None   # unscored, not a failure
    assert len(replays) == 1
    assert evaluated == ["good"]
    agg = aggregate_replay_metrics(metrics)
    assert agg["waa_verified_num_scored"] == 1
    assert agg["waa_verified_success_rate"] == 1.0


class _FakeWAAAdapter:
    """Stands in for WAALiveAdapter: load_task, reset, evaluate."""

    def __init__(self, configs, results):
        self.configs = configs
        self.results = results
        self.reset_calls = []
        self.evaluate_calls = []

    def load_task(self, task_id):
        if task_id.startswith("notepad_"):
            raise SyntheticTaskError(task_id)
        config = self.configs.get(task_id)
        if config is None:
            return BenchmarkTask(task_id=task_id, instruction="?", domain="unknown")
        return BenchmarkTask(
            task_id=task_id,
            instruction=config["instruction"],
            domain="notepad",
            raw_config=config,
            evaluation_spec=config.get("evaluator"),
        )

    def reset(self, task):
        self.reset_calls.append(task.task_id)

    def evaluate(self, task):
        self.evaluate_calls.append(task.task_id)
        return self.results[task.task_id]


_CONFIG = {"instruction": "Save the file", "evaluator": {"func": "compare_text_file"}}


def test_load_waa_tasks_reports_unscorable_ids():
    adapter = _FakeWAAAdapter({"real-1": _CONFIG}, {})
    tasks, problems = load_waa_tasks(adapter, ["real-1", "notepad_1", "no-config"])
    assert list(tasks) == ["real-1"]
    assert len(problems) == 2
    assert problems[0].startswith("notepad_1: Task ID 'notepad_1' appears to be synthetic")
    assert "\n" not in problems[0]
    assert problems[1].startswith("no-config: no WAA evaluator spec found")


def test_waa_live_hooks_score_with_waa_evaluator(tmp_path):
    configs = {"pass-1": _CONFIG, "fail-1": _CONFIG, "down-1": _CONFIG}
    results = {
        "pass-1": BenchmarkResult(task_id="pass-1", success=True, score=1.0),
        "fail-1": BenchmarkResult(
            task_id="fail-1", success=False, score=0.0, reason="file not saved"
        ),
        "down-1": BenchmarkResult(
            task_id="down-1", success=False, score=0.0,
            reason="Evaluation failed: HTTP 500", error_type="infrastructure",
        ),
    }
    adapter = _FakeWAAAdapter(configs, results)
    tasks, problems = load_waa_tasks(adapter, list(configs))
    assert problems == []
    setup_fn, evaluator = waa_live_hooks(adapter, tasks)
    b = tmp_path / "b"
    b.mkdir()

    metrics = run_demonstrate_then_replay(
        [FlowTask(tid, bundle_dir=b) for tid in configs],
        "http://x", tmp_path / "r",
        replay_fn=lambda *a: _fake_report(success=True),
        setup_fn=setup_fn, evaluator=evaluator,
    )
    assert adapter.reset_calls == ["pass-1", "fail-1", "down-1"]
    assert adapter.evaluate_calls == ["pass-1", "fail-1", "down-1"]
    by_id = {m.task_id: m for m in metrics}
    assert by_id["pass-1"].waa_verified_success is True
    # The replayer said success; WAA's evaluator disagreed and wins.
    assert by_id["fail-1"].replay_reported_success is True
    assert by_id["fail-1"].waa_verified_success is False
    assert by_id["fail-1"].error == "file not saved"
    # An evaluator outage is unscored, not a 0.
    assert by_id["down-1"].waa_verified_success is None
    assert by_id["down-1"].error == "Evaluation failed: HTTP 500"
    agg = aggregate_replay_metrics(metrics)
    assert agg["waa_verified_num_scored"] == 2
    assert agg["waa_verified_success_rate"] == 0.5
