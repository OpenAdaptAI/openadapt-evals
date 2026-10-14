"""Tests for the eval_flow_on_waa --live replay path (fakes only: no VM, no $)."""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from openadapt_evals.adapters.base import BenchmarkResult, BenchmarkTask
from openadapt_evals.adapters.waa import live as waa_live
from openadapt_evals.flow import replay_runner

_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "eval_flow_on_waa.py"
_spec = importlib.util.spec_from_file_location("eval_flow_on_waa_live", _SCRIPT)
efw = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(efw)

TASK_ID = "04d9aeaf-7bed-4024-bedb-e10e6f00eb7f-WOS"


class _FakeAdapter:
    instances: list["_FakeAdapter"] = []
    evaluator_spec: dict | None = {"func": "compare_text_file"}
    verdict = BenchmarkResult(task_id=TASK_ID, success=False, score=0.0, reason="wrong text")

    def __init__(self, config):
        self.config = config
        self.calls: list[str] = []
        self.closed = False
        _FakeAdapter.instances.append(self)

    def load_task(self, task_id):
        self.calls.append(f"load:{task_id}")
        config = {"instruction": "Type hello and save"}
        if self.evaluator_spec is not None:
            config["evaluator"] = self.evaluator_spec
        return BenchmarkTask(
            task_id=task_id,
            instruction=config["instruction"],
            domain="notepad",
            raw_config=config,
            evaluation_spec=config.get("evaluator"),
        )

    def reset(self, task):
        self.calls.append(f"reset:{task.task_id}")

    def evaluate(self, task):
        self.calls.append(f"evaluate:{task.task_id}")
        return self.verdict

    def close(self):
        self.closed = True


@pytest.fixture
def live_fakes(tmp_path, monkeypatch):
    import requests

    _FakeAdapter.instances = []
    monkeypatch.setattr(_FakeAdapter, "evaluator_spec", {"func": "compare_text_file"})
    probes = []

    def fake_get(url, timeout=None):
        probes.append(url)
        return SimpleNamespace(raise_for_status=lambda: None)

    replays = []

    def fake_replay(bundle_dir, server_url, run_dir, params):
        replays.append((Path(bundle_dir).name, server_url))
        return SimpleNamespace(
            success=True,
            terminal_outcome="success",
            rung_counts={"primary": 3},
            heal_count=0,
            model_calls=0,
            est_model_cost_usd=0.0,
            results=[object()] * 3,
        )

    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setattr(waa_live, "WAALiveAdapter", _FakeAdapter)
    monkeypatch.setattr(replay_runner, "_default_replay_fn", fake_replay)

    bundles = tmp_path / "bundles"
    (bundles / TASK_ID).mkdir(parents=True)
    (bundles / TASK_ID / "workflow.json").write_text("{}")
    return SimpleNamespace(bundles=bundles, probes=probes, replays=replays)


def _argv(fakes, tmp_path, *extra):
    return [
        "--mode", "replay", "--task-ids", TASK_ID,
        "--bundles", str(fakes.bundles), "--run-root", str(tmp_path / "out"),
        "--server-url", "http://waa:5001", "--evaluate-url", "http://waa:5050",
        "--live", *extra,
    ]


def test_live_replay_is_scored_by_waa_evaluator(tmp_path, live_fakes, capsys):
    rc = efw.main(_argv(live_fakes, tmp_path))
    assert rc == 0

    (adapter,) = _FakeAdapter.instances
    assert adapter.config.server_url == "http://waa:5001"
    assert adapter.config.evaluate_url == "http://waa:5050"
    # Setup runs before the replay and the evaluator runs after it.
    assert adapter.calls == [f"load:{TASK_ID}", f"reset:{TASK_ID}", f"evaluate:{TASK_ID}"]
    assert live_fakes.replays == [(TASK_ID, "http://waa:5001")]
    assert adapter.closed

    results = json.loads((tmp_path / "out" / "results.json").read_text())
    # The replay reported success; WAA's evaluator said no, and its verdict counts.
    (task,) = results["tasks"]
    assert task["replay_reported_success"] is True
    assert task["waa_verified_success"] is False
    assert task["error"] == "wrong text"
    assert results["summary"]["waa_verified_num_scored"] == 1
    assert results["summary"]["waa_verified_success_rate"] == 0.0
    assert results["ledger"]["spent_usd"] == 0.0


def test_live_replay_refuses_tasks_without_an_evaluator_spec(
    tmp_path, live_fakes, monkeypatch, capsys
):
    monkeypatch.setattr(_FakeAdapter, "evaluator_spec", None)
    rc = efw.main(_argv(live_fakes, tmp_path))
    err = capsys.readouterr().err
    assert rc == 2
    assert "cannot be scored by WAA's evaluator" in err
    assert "no WAA evaluator spec found" in err
    assert live_fakes.replays == []
    assert not (tmp_path / "out" / "results.json").exists()


def test_hybrid_live_is_refused_before_any_network(tmp_path, live_fakes, capsys):
    rc = efw.main(
        ["--mode", "hybrid", "--task-ids", TASK_ID, "--bundles", str(live_fakes.bundles),
         "--live"]
    )
    err = capsys.readouterr().err
    assert rc == 3
    assert "estimate-only" in err
    assert live_fakes.probes == []
    assert _FakeAdapter.instances == []
