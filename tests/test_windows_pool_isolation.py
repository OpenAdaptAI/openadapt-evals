from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from openadapt_evals.infrastructure.pool import WINDOWS_EGRESS_BOOTSTRAP_SCRIPT
from openadapt_evals.infrastructure.windows_pool_isolation import (
    EGRESS_SCHEMA,
    RESET_SCRIPT,
    WindowsPoolIsolationError,
    WindowsPoolIsolationManager,
    build_nft_batch,
    egress_policy_sha256,
    load_egress_policy,
    validate_egress_policy,
)


def _policy(**overrides):
    value = {
        "schema_version": EGRESS_SCHEMA,
        "run_id": "run-123",
        "allowed_ipv4": ["10.20.30.40", "198.51.100.10"],
        "allowed_ipv6": ["2001:db8::10"],
        "host_bindings_sha256": "a" * 64,
    }
    value.update(overrides)
    return value


def test_egress_policy_is_closed_unique_sorted_and_domain_bound():
    policy = _policy()
    assert validate_egress_policy(policy) == policy
    assert len(egress_policy_sha256(policy)) == 64
    changed = _policy(allowed_ipv4=["10.20.30.41"])
    assert egress_policy_sha256(changed) != egress_policy_sha256(policy)
    with pytest.raises(WindowsPoolIsolationError, match="closed"):
        validate_egress_policy({**policy, "hidden": True})
    with pytest.raises(WindowsPoolIsolationError, match="unique and sorted"):
        validate_egress_policy(_policy(allowed_ipv4=["10.0.0.2", "10.0.0.1"]))


def test_egress_policy_rejects_loopback_multicast_and_cidr():
    for address in ("127.0.0.1", "224.0.0.1", "10.0.0.0/24"):
        with pytest.raises(WindowsPoolIsolationError):
            validate_egress_policy(_policy(allowed_ipv4=[address]))


def test_policy_loader_refuses_symlink(tmp_path: Path):
    real = tmp_path / "policy.json"
    real.write_text(json.dumps(_policy()), encoding="utf-8")
    link = tmp_path / "link.json"
    link.symlink_to(real)
    with pytest.raises(WindowsPoolIsolationError, match="regular file"):
        load_egress_policy(link)


def test_nft_batch_is_one_fail_closed_transaction_without_dns():
    batch = build_nft_batch("waa-pool-00", _policy())
    assert batch.startswith("flush chain inet oa_")
    assert 'iifname "docker0"' in batch
    assert "ct state established,related accept" in batch
    assert "ip daddr 10.20.30.40 accept" in batch
    assert "ip6 daddr 2001:db8::10 accept" in batch
    assert batch.rstrip().endswith("counter drop")
    assert " dport 53 " not in batch


def test_worker_bootstrap_restores_block_all_before_docker():
    script = WINDOWS_EGRESS_BOOTSTRAP_SCRIPT
    assert 'iifname "docker0" counter drop' in script
    assert "nft -c -f /etc/openadapt/windows-egress.nft" in script
    assert "nft -f /etc/openadapt/windows-egress.nft" in script
    assert "DefaultDependencies=no" in script
    assert "Before=network-pre.target docker.service" in script
    assert "systemctl enable openadapt-windows-egress.service" in script


def test_reset_rejects_symbolic_links_and_non_regular_artifacts():
    assert "baseline contains a symbolic link" in RESET_SCRIPT
    assert "baseline contains a non-regular artifact" in RESET_SCRIPT


def test_reset_blocks_egress_first_and_returns_exact_proof():
    proof = {
        "schema_version": "openadapt.windows-pool-reset/v1",
        "worker": "waa-pool-00",
        "run_id": "run-123",
        "baseline_sha256": "b" * 64,
        "container_state": "stopped",
    }
    calls = []

    def _run(argv, **kwargs):
        calls.append((argv, kwargs))
        stdout = json.dumps(proof).encode() if "bash" in argv else b""
        return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr=b"")

    manager = WindowsPoolIsolationManager(
        ssh_host="192.0.2.10",
        ssh_user="azureuser",
        worker="waa-pool-00",
    )
    with patch("subprocess.run", side_effect=_run):
        result = manager.reset(run_id="run-123", baseline_sha256="b" * 64)
    assert result.worker == "waa-pool-00"
    assert calls[0][0][-5:-2] == ["nft", "list", "table"]
    assert calls[1][0][-6:-3] == ["nft", "list", "chain"]
    assert calls[2][0][-3:-1] == ["python3", "-c"]
    assert "windows-egress.nft" in calls[2][0][-1]
    reset_argv = calls[3][0]
    reset_start = reset_argv.index("sudo")
    assert reset_argv[reset_start : reset_start + 4] == ["sudo", "bash", "-s", "--"]
    reset_script = calls[3][1]["input"].decode()
    assert "docker rm -f" in reset_script
    assert "openadapt-windows-baseline-manifest.json" in reset_script
    assert "baseline artifact inventory is incomplete" in reset_script


def test_apply_egress_sends_the_exact_atomic_nft_batch():
    manager = WindowsPoolIsolationManager(
        ssh_host="192.0.2.10",
        ssh_user="azureuser",
        worker="waa-pool-00",
    )
    completed = subprocess.CompletedProcess([], 0, stdout=b"", stderr=b"")
    with patch("subprocess.run", return_value=completed) as run:
        digest = manager.apply_egress(_policy())
    assert digest == egress_policy_sha256(_policy())
    sent = run.call_args_list[-1].kwargs["input"].decode()
    assert sent == build_nft_batch("waa-pool-00", _policy())


def test_oa_vm_cli_exposes_reset_and_egress_commands():
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "openadapt_evals.benchmarks.vm_cli",
            "--help",
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "pool-reset" in result.stdout
    assert "pool-egress" in result.stdout
