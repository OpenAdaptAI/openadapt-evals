"""Tests for the eval_flow_on_waa CLI (dry-run: no network, no Azure, no $)."""

import importlib.util
from pathlib import Path


_SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "eval_flow_on_waa.py"
_spec = importlib.util.spec_from_file_location("eval_flow_on_waa", _SCRIPT)
efw = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(efw)


def test_dry_run_default_returns_zero_replay_10(capsys):
    rc = efw.main(["--mode", "replay", "--tasks", "10"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "DRY-RUN" in out
    assert "COST ESTIMATE" in out
    assert "10 tasks" in out
    assert "154 tasks" in out            # full-benchmark reference always shown


def test_dry_run_full_benchmark_154(capsys):
    rc = efw.main(["--mode", "replay", "--tasks", "154", "--dry-run"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "154 tasks" in out
    assert "Pure-agent baseline" in out


def test_hybrid_dry_run_shows_fallback_cost(capsys):
    rc = efw.main(["--mode", "hybrid", "--tasks", "154", "--fallback-rate", "0.3", "--dry-run"])
    out = capsys.readouterr().out
    assert rc == 0
    assert "Agent token cost" in out
    # Hybrid pays something for fallbacks; replay would not.
    est = efw.estimate_flow_waa_cost(154, mode="hybrid", fallback_rate=0.3)
    assert est.token_cost_usd > 0


def test_guardrails_are_printed(capsys):
    efw.main(["--tasks", "10"])
    out = capsys.readouterr().out
    assert "HARD GUARDRAILS" in out
    assert "per-run cap" in out
    assert "total cap" in out


def test_json_output(capsys):
    rc = efw.main(["--tasks", "5", "--json"])
    out = capsys.readouterr().out
    assert rc == 0
    assert '"plan"' in out and '"estimates"' in out


def test_live_refuses_when_bundle_missing_without_network(capsys):
    # --live with task-ids that have no bundles must refuse BEFORE any probe,
    # so this makes no network call.
    rc = efw.main([
        "--mode", "replay", "--task-ids", "id_a,id_b",
        "--bundles", "/tmp/nonexistent_bundles_dir", "--live",
    ])
    err = capsys.readouterr().err
    assert rc == 2
    assert "no compiled bundle" in err.lower()
