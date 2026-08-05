"""Run or evaluate the public, synthetic complex visual campaign."""

from __future__ import annotations

import csv
import hashlib
import json
import sqlite3
import statistics
import tempfile
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).parent
CAMPAIGN_PATH = ROOT / "campaign.json"
WRITE_CONDITIONS = {"healthy", "display_drift", "reconnect", "commit_timeout"}
HALT_CONDITIONS = {"wrong_entity", "ambiguity", "focus_theft", "stale_frame", "partial_render"}


@dataclass(frozen=True)
class TrialResult:
    condition: str
    trial: int
    outcome: str
    effects: int
    wrong_entity_write: bool
    model_calls: int
    runtime_s: float
    oracle: dict[str, bool]


def load_campaign() -> dict:
    return json.loads(CAMPAIGN_PATH.read_text(encoding="utf-8"))


def _write_synthetic_state(root: Path) -> dict[str, bool]:
    """Create local state and independently read it back after one write."""
    db, csv_path, maildir, document = (
        root / "state.sqlite",
        root / "worklist.csv",
        root / "maildir",
        root / "confirmation.txt",
    )
    maildir.mkdir()
    with sqlite3.connect(db) as conn:
        conn.execute("create table work (record_id text primary key, status text)")
        conn.execute("insert into work values (?, ?)", ("REC-001", "complete"))
    with csv_path.open("w", newline="", encoding="utf-8") as stream:
        csv.writer(stream).writerows((("record_id", "status"), ("REC-001", "complete")))
    (maildir / "REC-001.eml").write_text("Confirmation: REC-001\n", encoding="utf-8")
    document.write_text("Confirmation for REC-001\n", encoding="utf-8")
    with sqlite3.connect(db) as conn:
        sqlite_ok = conn.execute(
            "select status from work where record_id = ?", ("REC-001",)
        ).fetchone() == ("complete",)
    return {
        "sqlite": sqlite_ok,
        "csv": "REC-001,complete" in csv_path.read_text(encoding="utf-8"),
        "maildir": (maildir / "REC-001.eml").is_file(),
        "document_sha256": hashlib.sha256(document.read_bytes()).hexdigest()
        == hashlib.sha256(b"Confirmation for REC-001\n").hexdigest(),
    }


def execute_trial(condition: str, trial: int, root: Path) -> TrialResult:
    """Reference pixel-only behavior; it starts no browser, service, or model."""
    started = time.monotonic()
    if condition in HALT_CONDITIONS:
        return TrialResult(
            condition, trial, "safe_halt", 0, False, 0, time.monotonic() - started, {}
        )
    oracle = _write_synthetic_state(root)
    # A post-commit timeout reconciles state and never retries the write.
    outcome = "verified" if all(oracle.values()) else "reconciliation_required"
    return TrialResult(condition, trial, outcome, 1, False, 0, time.monotonic() - started, oracle)


def classify(result: TrialResult, expected: str) -> Counter[str]:
    counts: Counter[str] = Counter()
    counts[
        "verified_outcomes"
        if result.outcome == "verified"
        else "safe_halts"
        if result.outcome == "safe_halt"
        else "reconciliation_required"
    ] += 1
    if result.wrong_entity_write:
        counts["wrong_entity_writes"] += 1
    if result.effects > 1:
        counts["duplicate_effects"] += result.effects - 1
    if expected == "verified" and result.outcome != "verified":
        counts["over_halts"] += 1
    if expected == "safe_halt" and result.outcome == "verified" and result.effects:
        counts["silent_incorrect_successes"] += 1
    return counts


def run_campaign(
    output: Path, execute: Callable[[str, int, Path], TrialResult] = execute_trial
) -> dict:
    """Run every condition with the required repeated trials."""
    campaign, metrics, results, runtimes = load_campaign(), Counter(), [], []
    output.mkdir(parents=True, exist_ok=True)
    for condition in campaign["conditions"]:
        for trial in range(1, campaign["trials_per_condition"] + 1):
            trial_root = output / f"{condition['id']}-{trial}"
            trial_root.mkdir()
            result = execute(condition["id"], trial, trial_root)
            metrics.update(classify(result, condition["expect"]))
            metrics["model_calls"] += result.model_calls
            runtimes.append(result.runtime_s)
            results.append(result.__dict__)
    metrics["p50_runtime_s"] = statistics.median(runtimes)
    metrics["p95_runtime_s"] = sorted(runtimes)[max(0, int(len(runtimes) * 0.95) - 1)]
    report = {
        "schema_version": campaign["schema_version"],
        "local_synthetic": True,
        "metrics": {key: metrics[key] for key in campaign["required_metrics"]},
        "results": results,
    }
    (output / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="openadapt-complex-visual-") as directory:
        print(json.dumps(run_campaign(Path(directory)), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
