"""The MockMed reward proof is deterministic and complete under its seed schedule."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from openadapt_evals.reward import proof
from openadapt_evals.reward.devsigner import verify_signature
from tests.reward_fixtures import HAS_SCOPE

DOCS = Path(__file__).resolve().parents[1] / "docs" / "reward"
COMMITTED_JSON = DOCS / "proof_2026-09-01.json"


@pytest.fixture(scope="module")
def run() -> proof.ProofRun:
    return proof.run_proof()


def _strip_versions(payload: dict) -> dict:
    return {key: value for key, value in payload.items() if key != "versions"}


def test_run_is_deterministic(run: proof.ProofRun) -> None:
    again = proof.run_proof()
    assert proof.to_json(run) == proof.to_json(again)
    assert run.certificate.signature == again.certificate.signature


def test_table_has_every_condition_and_three_trials(run: proof.ProofRun) -> None:
    cells = {(row["condition"], row["reward"]) for row in run.table}
    assert cells == {(c, r) for c in proof.CONDITIONS for r in proof.REWARDS}
    assert set(proof.OPERATORS) <= set(proof.CONDITIONS)
    assert all(row["trials"] >= proof.MIN_TRIALS for row in run.table)
    assert len(run.seeds) >= proof.MIN_TRIALS


def test_visual_pays_every_mutant_and_certified_refuses(run: proof.ProofRun) -> None:
    by_cell = {(row["condition"], row["reward"]): row for row in run.table}
    for family in ("dup", "extra", "omit", "unsubmit", "claim"):
        visual = by_cell[(family, proof.VISUAL)]
        certified = by_cell[(family, proof.CERTIFIED)]
        assert visual["silent_incorrect_success_rate"] == 1.0
        assert certified["silent_incorrect_success_rate"] == 0.0
        assert visual["certified"] is False
        assert visual["calibration_scope"] is None
    control = by_cell[("control", proof.CERTIFIED)]
    assert control["over_refusal_rate"] == 0.0
    assert control["unscored"] == 0


def test_outage_is_unscored_never_zero(run: proof.ProofRun) -> None:
    outage = [
        run.scored[(proof.ORACLE_OUTAGE, trial, proof.CERTIFIED)] for trial in range(run.trials)
    ]
    assert all(item.unscored for item in outage)
    assert all(item.scalar is None for item in outage)
    assert all(item.outcome.value == "failed_platform" for item in outage)
    row = next(
        r
        for r in run.table
        if r["condition"] == proof.ORACLE_OUTAGE and r["reward"] == proof.CERTIFIED
    )
    assert row["unscored"] == run.trials
    assert row["paid"] == 0 and row["over_refusal_rate"] == 0.0


@pytest.mark.skipif(not HAS_SCOPE, reason="installed openadapt-types has no calibration_scope")
def test_certified_reward_is_certified_with_synthetic_scope(run: proof.ProofRun) -> None:
    for row in run.table:
        if row["reward"] == proof.CERTIFIED:
            assert row["certified"] is True
            assert row["calibration_scope"] == "synthetic"


def test_certificate_epsilon_is_the_clopper_pearson_bound(run: proof.ProofRun) -> None:
    cal = run.calibration
    n = cal["gold_fail_trials"]
    assert n == 5 * run.trials
    assert cal["false_accepts"][proof.VISUAL] == n
    assert cal["false_accepts"][proof.CERTIFIED] == 0
    assert cal["clopper_pearson_upper_95"][proof.VISUAL] == 1.0
    expected = round(1.0 - 0.05 ** (1.0 / n), 6)
    assert cal["clopper_pearson_upper_95"][proof.CERTIFIED] == pytest.approx(expected, abs=1e-6)
    assert run.certificate.epsilon == cal["clopper_pearson_upper_95"][proof.CERTIFIED]


def test_clopper_pearson_known_values() -> None:
    assert proof.clopper_pearson_upper(15, 15) == 1.0
    assert proof.clopper_pearson_upper(0, 15) == pytest.approx(1 - 0.05 ** (1 / 15), abs=1e-6)
    assert proof.clopper_pearson_upper(1, 20) == pytest.approx(0.216, abs=2e-3)
    assert proof.clopper_pearson_upper(0, 261) == pytest.approx(0.0114, abs=2e-4)
    with pytest.raises(ValueError):
        proof.clopper_pearson_upper(3, 2)


def test_expiry_check_drops_certification_and_logs(run: proof.ProofRun) -> None:
    check = run.expiry_check
    assert check["policy_update"] == run.certificate.expires_at_policy_update
    assert check["receipts_checked"] == run.trials
    assert check["certified_after_expiry"] == 0
    assert check["expiry_warnings_logged"] == run.trials


def test_receipts_and_certificate_verify_against_the_recorded_key(run: proof.ProofRun) -> None:
    from base64 import b64decode

    key = b64decode(run.public_key_b64)
    assert verify_signature(run.certificate, key)
    assert all(verify_signature(receipt, key) for receipt in run.receipts.values())


def test_cli_writes_json_and_markdown(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    json_path = tmp_path / "proof.json"
    md_path = tmp_path / "proof.md"
    assert (
        proof.main(["--json", str(json_path), "--markdown", str(md_path), "--date", "2026-09-01"])
        == 0
    )
    payload = json.loads(json_path.read_text())
    assert payload["proof"] == proof.PROOF_NAME
    assert len(payload["rollouts"]) == len(proof.CONDITIONS) * proof.MIN_TRIALS
    text = md_path.read_text()
    assert "| condition | gold | reward |" in text
    assert "Clopper-Pearson" in text
    assert "—" not in text
    assert "| condition |" in capsys.readouterr().out


def test_committed_proof_matches_a_fresh_run(run: proof.ProofRun) -> None:
    """The evidence in docs/reward is the output of this code at this seed schedule."""

    assert COMMITTED_JSON.exists(), (
        "run python -m openadapt_evals.reward.proof --json docs/reward/proof_<date>.json"
    )
    committed = json.loads(COMMITTED_JSON.read_text())
    assert _strip_versions(committed) == _strip_versions(proof.to_json(run))
