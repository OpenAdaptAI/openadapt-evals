from __future__ import annotations

import base64
import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from openadapt_evals.infrastructure.pool import (
    WAA_START_SCRIPT_TEMPLATE,
    WINDOWS_EGRESS_BOOTSTRAP_SCRIPT,
    PoolManager,
)
from openadapt_evals.infrastructure.windows_pool_isolation import (
    EGRESS_PROOF_SCHEMA,
    EGRESS_SCHEMA,
    MAX_GATE_AGE,
    RESET_SCHEMA,
    WORKER_IDENTITY_SCHEMA,
    EgressProof,
    ResetProof,
    WindowsPoolIsolationError,
    WindowsPoolIsolationManager,
    build_block_all_batch,
    build_nft_batch,
    egress_policy_sha256,
    reset_proof_sha256,
    validate_egress_policy,
    validate_reset_proof,
    validate_worker_identity,
    worker_identity_sha256,
)

NOW = datetime(2026, 8, 27, 18, 0, tzinfo=timezone.utc)


def _identity(**overrides):
    public_key = "ssh-ed25519 " + base64.b64encode(b"k" * 32).decode()
    value = {
        "schema_version": WORKER_IDENTITY_SCHEMA,
        "provider": "azure",
        "provider_account_id": "subscription-123",
        "resource_id": "/subscriptions/123/resourceGroups/oa/providers/Microsoft.Compute/virtualMachines/waa-pool-00",
        "instance_id": "waa-pool-00-instance",
        "ssh_host": "192.0.2.10",
        "ssh_host_public_key": public_key,
        "ssh_host_key_sha256": "sha256:" + hashlib.sha256(public_key.encode()).hexdigest(),
        "admitted_image_sha256": "sha256:" + "b" * 64,
        "admitted_runtime_sha256": "sha256:" + "c" * 64,
        "host_bindings_sha256": "sha256:" + "a" * 64,
        "tls_bindings_sha256": "sha256:" + "d" * 64,
    }
    value.update(overrides)
    return validate_worker_identity(value)


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


def _reset_proof(identity=None, **overrides):
    identity = identity or _identity()
    value = {
        "schema_version": RESET_SCHEMA,
        "worker": "waa-pool-00",
        "run_id": "run-123",
        "baseline_sha256": "b" * 64,
        "container_state": "stopped",
        "worker_identity_sha256": worker_identity_sha256(identity),
        "admitted_image_sha256": identity.admitted_image_sha256,
        "admitted_runtime_sha256": identity.admitted_runtime_sha256,
        "host_bindings_sha256": identity.host_bindings_sha256,
        "tls_bindings_sha256": identity.tls_bindings_sha256,
        "issued_at": "2026-08-27T18:00:00Z",
        "expires_at": "2026-08-27T18:05:00Z",
    }
    value.update(overrides)
    return ResetProof(**value)


def _egress_proof(identity=None, reset=None, **overrides):
    identity = identity or _identity()
    reset = reset or _reset_proof(identity)
    value = {
        "schema_version": EGRESS_PROOF_SCHEMA,
        "worker": "waa-pool-00",
        "run_id": "run-123",
        "policy_sha256": egress_policy_sha256(_policy()),
        "reset_proof_sha256": reset_proof_sha256(reset),
        "worker_identity_sha256": worker_identity_sha256(identity),
        "host_bindings_sha256": identity.host_bindings_sha256,
        "tls_bindings_sha256": identity.tls_bindings_sha256,
        "conntrack_drained": True,
        "issued_at": "2026-08-27T18:00:00Z",
        "expires_at": "2026-08-27T18:05:00Z",
    }
    value.update(overrides)
    return EgressProof(**value)


def _manager(identity=None):
    return WindowsPoolIsolationManager(
        ssh_host="192.0.2.10",
        ssh_user="azureuser",
        worker="waa-pool-00",
        identity=identity or _identity(),
    )


def test_egress_policy_is_closed_unique_sorted_and_domain_bound():
    policy = _policy()
    assert validate_egress_policy(policy) == policy
    assert len(egress_policy_sha256(policy)) == 64
    assert egress_policy_sha256(_policy(allowed_ipv4=["10.20.30.41"])) != (
        egress_policy_sha256(policy)
    )
    with pytest.raises(WindowsPoolIsolationError, match="closed"):
        validate_egress_policy({**policy, "hidden": True})


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "224.0.0.1",
        "10.0.0.0/24",
        "169.254.169.254",
        "168.63.129.16",
        "100.100.100.200",
        "fe80::1",
        "fd00:ec2::254",
    ],
)
def test_egress_policy_rejects_unsafe_or_metadata_targets(address):
    key = "allowed_ipv6" if ":" in address else "allowed_ipv4"
    with pytest.raises(WindowsPoolIsolationError):
        validate_egress_policy(_policy(**{key: [address]}))


def test_block_all_and_replacement_never_preserve_an_old_established_flow():
    allowed = build_nft_batch("waa-pool-00", _policy())
    blocked = build_block_all_batch("waa-pool-00", "run-123")
    assert "ct state established,related accept" not in blocked
    return_rules = [line for line in allowed.splitlines() if "ct state" in line]
    assert return_rules
    assert all(" saddr " in line and 'oifname "docker0"' in line for line in return_rules)
    assert " daddr " not in blocked
    assert blocked.rstrip().endswith("counter drop")


def test_worker_bootstrap_restores_block_all_and_conntrack_before_docker():
    script = WINDOWS_EGRESS_BOOTSTRAP_SCRIPT
    assert 'iifname "docker0" counter drop' in script
    assert "conntrack nftables" in script
    assert "nft -c -f /etc/openadapt/windows-egress.nft" in script
    assert "policy drop" in script
    assert "Before=network-pre.target docker.service" in script
    assert "windows-run-gates -mindepth 1 -maxdepth 1" in script


def test_worker_identity_pins_host_key_image_runtime_host_and_tls_bindings():
    identity = _identity()
    assert worker_identity_sha256(identity).startswith("sha256:")
    with pytest.raises(WindowsPoolIsolationError, match="host key digest"):
        _identity(ssh_host_key_sha256="sha256:" + "0" * 64)
    with pytest.raises(WindowsPoolIsolationError, match="SSH host differs"):
        WindowsPoolIsolationManager(
            ssh_host="192.0.2.11",
            ssh_user="azureuser",
            worker="waa-pool-00",
            identity=identity,
        )


def test_reset_blocks_egress_first_and_returns_identity_bound_fresh_proof():
    remote = {
        "schema_version": RESET_SCHEMA,
        "worker": "waa-pool-00",
        "run_id": "run-123",
        "baseline_sha256": "b" * 64,
        "container_state": "stopped",
    }
    calls = []

    def _run(argv, **kwargs):
        calls.append((argv, kwargs))
        stdout = b""
        if kwargs.get("input") and b"openadapt-windows-baseline-manifest" in kwargs["input"]:
            stdout = json.dumps(remote).encode()
        return subprocess.CompletedProcess(argv, 0, stdout=stdout, stderr=b"")

    with (
        patch("openadapt_evals.infrastructure.windows_pool_isolation._now", return_value=NOW),
        patch("subprocess.run", side_effect=_run),
    ):
        proof = _manager().reset(run_id="run-123", baseline_sha256="b" * 64)
    validate_reset_proof(
        proof,
        worker="waa-pool-00",
        run_id="run-123",
        identity=_identity(),
        now=NOW,
    )
    assert proof.admitted_image_sha256 == _identity().admitted_image_sha256
    assert any("StrictHostKeyChecking=yes" in call[0] for call in calls)
    persist_program = next(
        argument
        for argv, _ in calls
        for argument in argv
        if isinstance(argument, str) and "conntrack" in argument
    )
    assert persist_program.count("conntrack', '-F") == 2
    reset_script = next(
        kwargs["input"].decode()
        for _, kwargs in calls
        if kwargs.get("input") and b"openadapt-windows-baseline-manifest" in kwargs["input"]
    )
    assert "windows-last-guest-addresses" in reset_script
    reset_gate_script = next(
        kwargs["input"].decode()
        for _, kwargs in calls
        if kwargs.get("input") and b"reset_gate/proof.sha256" in kwargs["input"]
    )
    assert 'reset_gate="$gate_root/${run_id}.reset"' in reset_gate_script
    assert "flock -n 9" in reset_gate_script
    assert reset_proof_sha256(proof) in next(
        argument for argv, _ in calls for argument in argv if argument == reset_proof_sha256(proof)
    )


def test_reset_proof_refuses_expiry_identity_drift_and_run_reuse():
    proof = _reset_proof()
    with pytest.raises(WindowsPoolIsolationError, match="stale"):
        validate_reset_proof(
            proof,
            worker="waa-pool-00",
            run_id="run-123",
            identity=_identity(),
            now=NOW + MAX_GATE_AGE,
        )
    with pytest.raises(WindowsPoolIsolationError, match="run_id differs"):
        validate_reset_proof(
            proof,
            worker="waa-pool-00",
            run_id="run-456",
            identity=_identity(),
            now=NOW,
        )
    with pytest.raises(WindowsPoolIsolationError, match="worker_identity_sha256"):
        validate_reset_proof(
            proof,
            worker="waa-pool-00",
            run_id="run-123",
            identity=_identity(resource_id="/other/instance"),
            now=NOW,
        )


def test_apply_egress_binds_reset_identity_host_tls_and_drains_conntrack():
    reset = _reset_proof()
    completed = subprocess.CompletedProcess([], 0, stdout=b"", stderr=b"")
    with (
        patch("openadapt_evals.infrastructure.windows_pool_isolation._now", return_value=NOW),
        patch("subprocess.run", return_value=completed) as run,
    ):
        proof = _manager().apply_egress(_policy(), reset_proof=reset)
    assert proof.policy_sha256 == egress_policy_sha256(_policy())
    assert proof.reset_proof_sha256 == reset_proof_sha256(reset)
    assert proof.conntrack_drained is True
    sent = next(
        call.kwargs["input"].decode()
        for call in run.call_args_list
        if call.kwargs.get("input") and b"flush chain" in call.kwargs["input"]
    )
    assert sent == build_nft_batch("waa-pool-00", _policy())
    remote_program = next(
        argument
        for call in run.call_args_list
        for argument in call.args[0]
        if isinstance(argument, str) and "gate_created" in argument
    )
    assert "fcntl.LOCK_EX | fcntl.LOCK_NB" in remote_program
    assert "os.O_CREAT | os.O_EXCL" in remote_program
    assert "guest is not stopped" in remote_program
    assert "remote reset proof differs" in remote_program
    assert "reset proof already consumed" in remote_program
    assert "os.replace(reset_gate, reset_consumed_gate)" in remote_program
    assert remote_program.count("['conntrack', '-F']") == 2
    assert "guest conntrack state remains after drain" in remote_program
    assert "/run/openadapt/windows-egress-active.nft" in remote_program


def test_start_gate_consumes_once_and_checks_exact_policy_image_and_bindings():
    reset = _reset_proof()
    egress = _egress_proof(reset=reset)
    starts = 0

    def _run(argv, **kwargs):
        nonlocal starts
        if kwargs.get("input") and b"windows-run-gates" in kwargs["input"]:
            starts += 1
            return subprocess.CompletedProcess(
                argv,
                0 if starts == 1 else 1,
                stdout=b"",
                stderr=b"already consumed" if starts > 1 else b"",
            )
        return subprocess.CompletedProcess(argv, 0, stdout=b"", stderr=b"")

    manager = _manager()
    with (
        patch("openadapt_evals.infrastructure.windows_pool_isolation._now", return_value=NOW),
        patch("subprocess.run", side_effect=_run),
    ):
        proof = manager.start(
            policy=_policy(),
            reset_proof=reset,
            egress_proof=egress,
            start_script="echo STARTED",
        )
        assert proof.one_use_consumed is True
        with pytest.raises(WindowsPoolIsolationError, match="already consumed"):
            manager.start(
                policy=_policy(),
                reset_proof=reset,
                egress_proof=egress,
                start_script="echo STARTED",
            )


def test_start_command_uses_the_admitted_image_digest_instead_of_a_mutable_tag():
    rendered = WAA_START_SCRIPT_TEMPLATE.format(
        home_dir="/home/azureuser",
        ssh_username="azureuser",
        admitted_image="sha256:" + "b" * 64,
    )
    assert "waa-auto:latest" not in rendered
    assert "sha256:" + "b" * 64 in rendered


def test_benchmark_dispatch_refuses_a_responsive_legacy_worker():
    worker = SimpleNamespace(
        waa_ready=True,
        status="ready",
        qualified_run_id=None,
        qualified_worker_identity_sha256=None,
        qualified_egress_policy_sha256=None,
        qualified_start_proof_sha256=None,
    )
    manager = object.__new__(PoolManager)
    manager.registry = SimpleNamespace(get_pool=lambda: SimpleNamespace(workers=[worker]))
    with pytest.raises(RuntimeError, match="No qualified workers"):
        manager.run(api_key="test-only")


def test_oa_vm_cli_exposes_the_three_step_qualified_start():
    result = subprocess.run(
        [sys.executable, "-m", "openadapt_evals.benchmarks.vm_cli", "--help"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "pool-reset" in result.stdout
    assert "pool-egress" in result.stdout
    assert "pool-start" in result.stdout

    auto_help = subprocess.run(
        [sys.executable, "-m", "openadapt_evals.benchmarks.vm_cli", "pool-auto", "--help"],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert auto_help.returncode == 0, auto_help.stderr
    assert "--qualification-dir" in auto_help.stdout
    assert "--run-evidence-dir" in auto_help.stdout
    assert "--baseline-sha256" in auto_help.stdout
