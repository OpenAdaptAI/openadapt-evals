"""Clean reset and host-enforced egress for dedicated Windows pool workers."""

from __future__ import annotations

import hashlib
import ipaddress
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from openadapt_evals.infrastructure.azure_vm import SSH_OPTS

EGRESS_SCHEMA = "openadapt.windows-host-egress/v1"
RESET_SCHEMA = "openadapt.windows-pool-reset/v1"
EGRESS_DOMAIN = b"openadapt-windows-host-egress-v1\0"
SAFE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
HEX64 = re.compile(r"^[a-f0-9]{64}$")


class WindowsPoolIsolationError(RuntimeError):
    """The worker cannot prove a clean reset or an enforced egress policy."""


def canonical_json(value: object) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def egress_policy_sha256(value: object) -> str:
    policy = validate_egress_policy(value)
    return hashlib.sha256(EGRESS_DOMAIN + canonical_json(policy)).hexdigest()


def validate_egress_policy(value: object) -> Mapping[str, Any]:
    keys = {
        "schema_version",
        "run_id",
        "allowed_ipv4",
        "allowed_ipv6",
        "host_bindings_sha256",
    }
    if not isinstance(value, Mapping) or set(value) != keys:
        raise WindowsPoolIsolationError("egress policy is not a closed object")
    if value["schema_version"] != EGRESS_SCHEMA:
        raise WindowsPoolIsolationError("egress policy schema is invalid")
    run_id = value["run_id"]
    if not isinstance(run_id, str) or SAFE_NAME.fullmatch(run_id) is None:
        raise WindowsPoolIsolationError("egress run id is invalid")
    host_bindings = value["host_bindings_sha256"]
    if not isinstance(host_bindings, str) or HEX64.fullmatch(host_bindings) is None:
        raise WindowsPoolIsolationError("egress host binding digest is invalid")
    for key, family in (("allowed_ipv4", 4), ("allowed_ipv6", 6)):
        addresses = value[key]
        if (
            not isinstance(addresses, list)
            or addresses != sorted(addresses)
            or len(addresses) != len(set(addresses))
        ):
            raise WindowsPoolIsolationError(f"{key} must be unique and sorted")
        for raw in addresses:
            try:
                address = ipaddress.ip_address(raw)
            except ValueError as exc:
                raise WindowsPoolIsolationError(f"{key} contains an invalid address") from exc
            if (
                address.version != family
                or address.is_unspecified
                or address.is_multicast
                or address.is_loopback
            ):
                raise WindowsPoolIsolationError(f"{key} contains an unsafe address")
    return value


def load_egress_policy(path: Path) -> Mapping[str, Any]:
    try:
        if path.is_symlink() or not path.is_file():
            raise WindowsPoolIsolationError("egress policy is not a regular file")
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WindowsPoolIsolationError("egress policy cannot be read") from exc
    return validate_egress_policy(value)


def _safe_name(value: str, label: str) -> str:
    if SAFE_NAME.fullmatch(value) is None:
        raise WindowsPoolIsolationError(f"{label} is invalid")
    return value


def _nft_table(worker: str) -> str:
    _safe_name(worker, "worker name")
    # Each pool worker has one dedicated Linux VM host. A fixed name lets the
    # boot-time service restore the last fail-closed policy before Docker starts.
    return "oa_windows"


def build_nft_batch(
    worker: str,
    policy: Mapping[str, Any],
    *,
    bridge_interface: str = "docker0",
) -> str:
    """Return one atomic nftables transaction for a dedicated worker host."""

    _safe_name(worker, "worker name")
    _safe_name(bridge_interface, "bridge interface")
    parsed = validate_egress_policy(policy)
    table = _nft_table(worker)
    lines = [
        f"flush chain inet {table} forward",
        (
            f'add rule inet {table} forward iifname "{bridge_interface}" '
            f'ct state established,related accept comment "{parsed["run_id"]}"'
        ),
    ]
    for address in parsed["allowed_ipv4"]:
        lines.append(
            f'add rule inet {table} forward iifname "{bridge_interface}" ip daddr {address} accept'
        )
    for address in parsed["allowed_ipv6"]:
        lines.append(
            f'add rule inet {table} forward iifname "{bridge_interface}" ip6 daddr {address} accept'
        )
    # The worker VM is dedicated to one Windows guest. The final forward-chain
    # drop prevents the guest and its NET_ADMIN container from bypassing the
    # exact allow-list. DNS is not opened. The runner must supply reviewed host
    # bindings inside the guest and bind their digest in the policy.
    lines.append(f'add rule inet {table} forward iifname "{bridge_interface}" counter drop')
    return "\n".join(lines) + "\n"


def build_block_all_batch(worker: str, run_id: str, *, bridge_interface: str = "docker0") -> str:
    return build_nft_batch(
        worker,
        {
            "schema_version": EGRESS_SCHEMA,
            "run_id": run_id,
            "allowed_ipv4": [],
            "allowed_ipv6": [],
            "host_bindings_sha256": "0" * 64,
        },
        bridge_interface=bridge_interface,
    )


RESET_SCRIPT = r"""
set -euo pipefail
worker="$1"
run_id="$2"
storage="$3"
baseline="$4"
expected="$5"
container="$6"
lock="/var/lock/openadapt-windows-${worker}.lock"
exec 9>"$lock"
flock -n 9
test -d "$baseline"
test ! -L "$baseline"
test ! -L "$storage"
manifest="$baseline/openadapt-windows-baseline-manifest.json"
test -f "$manifest"
test ! -L "$manifest"
actual="$(sha256sum "$manifest" | cut -d' ' -f1)"
test "$actual" = "$expected"
verify_baseline() {
python3 - "$1" <<'PY'
import hashlib
import json
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
manifest_path = root / "openadapt-windows-baseline-manifest.json"
manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
if set(manifest) != {"schema_version", "artifacts"}:
    raise SystemExit("baseline manifest is not closed")
if manifest["schema_version"] != "openadapt.windows-baseline-manifest/v1":
    raise SystemExit("baseline manifest schema is invalid")
artifacts = manifest["artifacts"]
if not isinstance(artifacts, list) or not artifacts:
    raise SystemExit("baseline artifact inventory is empty")
prior = ""
declared = set()
for item in artifacts:
    if not isinstance(item, dict) or set(item) != {"path", "size_bytes", "sha256"}:
        raise SystemExit("baseline artifact is not closed")
    relative = item["path"]
    path = pathlib.PurePosixPath(relative) if isinstance(relative, str) else None
    if path is None or path.is_absolute() or ".." in path.parts or relative <= prior:
        raise SystemExit("baseline artifact path is invalid")
    candidate = root.joinpath(*path.parts)
    if candidate.is_symlink() or not candidate.is_file():
        raise SystemExit("baseline artifact is not a regular file")
    payload = candidate.read_bytes()
    if len(payload) != item["size_bytes"] or hashlib.sha256(payload).hexdigest() != item["sha256"]:
        raise SystemExit("baseline artifact digest differs")
    declared.add(relative)
    prior = relative
actual = set()
for path in root.rglob("*"):
    if path.is_symlink():
        raise SystemExit("baseline contains a symbolic link")
    if path.is_dir():
        continue
    if not path.is_file():
        raise SystemExit("baseline contains a non-regular artifact")
    if path != manifest_path:
        actual.add(path.relative_to(root).as_posix())
if actual != declared:
    raise SystemExit("baseline artifact inventory is incomplete")
PY
}
verify_baseline "$baseline"
docker rm -f "$container" >/dev/null 2>&1 || true
parent="$(dirname "$storage")"
stage="${parent}/.openadapt-reset-${run_id}"
prior="${parent}/.openadapt-prior-${run_id}"
test ! -e "$stage"
test ! -e "$prior"
mkdir -m 0700 "$stage"
cp -a --reflink=auto "$baseline"/. "$stage"/
stage_actual="$(sha256sum "$stage/openadapt-windows-baseline-manifest.json" | cut -d' ' -f1)"
test "$stage_actual" = "$expected"
verify_baseline "$stage"
if test -e "$storage"; then mv "$storage" "$prior"; fi
mv "$stage" "$storage"
if test -e "$prior"; then rm -rf --one-file-system "$prior"; fi
printf '{"schema_version":"openadapt.windows-pool-reset/v1","worker":"%s","run_id":"%s","baseline_sha256":"%s","container_state":"stopped"}\n' "$worker" "$run_id" "$expected"
""".strip()


@dataclass(frozen=True)
class ResetProof:
    schema_version: str
    worker: str
    run_id: str
    baseline_sha256: str
    container_state: str


class WindowsPoolIsolationManager:
    """Apply reset and egress controls through one worker's SSH boundary."""

    def __init__(
        self,
        *,
        ssh_host: str,
        ssh_user: str,
        worker: str,
        container: str = "winarena",
        storage_dir: str = "/home/azureuser/waa-storage",
        baseline_dir: str = "/home/azureuser/openadapt-windows-baseline",
        bridge_interface: str = "docker0",
    ) -> None:
        self.ssh_host = ssh_host
        self.ssh_user = _safe_name(ssh_user, "SSH user")
        self.worker = _safe_name(worker, "worker name")
        self.container = _safe_name(container, "container name")
        self.storage_dir = storage_dir
        self.baseline_dir = baseline_dir
        self.bridge_interface = _safe_name(bridge_interface, "bridge interface")
        for path in (storage_dir, baseline_dir):
            if not path.startswith("/") or ".." in Path(path).parts:
                raise WindowsPoolIsolationError("isolation path is invalid")

    def _ssh(
        self,
        remote_command: Sequence[str],
        *,
        input_bytes: bytes | None = None,
        timeout_seconds: int = 300,
    ) -> subprocess.CompletedProcess[bytes]:
        process = subprocess.run(
            [
                "ssh",
                *SSH_OPTS,
                f"{self.ssh_user}@{self.ssh_host}",
                *remote_command,
            ],
            input=input_bytes,
            capture_output=True,
            timeout=timeout_seconds,
        )
        if process.returncode != 0:
            detail = process.stderr.decode("utf-8", errors="replace").strip()[-500:]
            raise WindowsPoolIsolationError(f"worker isolation command failed: {detail}")
        return process

    def _ensure_boundary(self) -> None:
        """Create the dedicated nftables hook before any run can start."""

        table = _nft_table(self.worker)
        try:
            self._ssh(["sudo", "nft", "list", "table", "inet", table])
        except WindowsPoolIsolationError:
            self._ssh(["sudo", "nft", "add", "table", "inet", table])
        try:
            self._ssh(["sudo", "nft", "list", "chain", "inet", table, "forward"])
        except WindowsPoolIsolationError:
            self._ssh(
                [
                    "sudo",
                    "nft",
                    "add",
                    "chain",
                    "inet",
                    table,
                    "forward",
                    "{ type filter hook forward priority -50; policy accept; }",
                ]
            )

    def _persist_and_apply(self, batch: str) -> None:
        """Store the checked policy for boot and apply the same bytes now."""

        program = """
import os
import pathlib
import subprocess
import sys
import tempfile

target = pathlib.Path('/etc/openadapt/windows-egress.nft')
target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
payload = sys.stdin.buffer.read()
if not payload or len(payload) > 1048576:
    raise SystemExit('invalid nft policy size')
fd, temporary = tempfile.mkstemp(prefix='.windows-egress.', dir=target.parent)
try:
    os.fchmod(fd, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(payload)
        stream.flush()
        os.fsync(stream.fileno())
    subprocess.run(['nft', '-c', '-f', temporary], check=True)
    subprocess.run(['nft', '-f', temporary], check=True)
    os.replace(temporary, target)
    directory = os.open(target.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
finally:
    try:
        os.unlink(temporary)
    except FileNotFoundError:
        pass
""".strip()
        self._ensure_boundary()
        self._ssh(
            ["sudo", "python3", "-c", program],
            input_bytes=batch.encode(),
        )

    def block_all(self, run_id: str) -> str:
        """Install the fail-closed boundary before reset or guest startup."""

        run_id = _safe_name(run_id, "run id")
        batch = build_block_all_batch(
            self.worker,
            run_id,
            bridge_interface=self.bridge_interface,
        )
        self._persist_and_apply(batch)
        return egress_policy_sha256(
            {
                "schema_version": EGRESS_SCHEMA,
                "run_id": run_id,
                "allowed_ipv4": [],
                "allowed_ipv6": [],
                "host_bindings_sha256": "0" * 64,
            }
        )

    def reset(self, *, run_id: str, baseline_sha256: str) -> ResetProof:
        """Restore the exact baseline and leave the guest container stopped."""

        run_id = _safe_name(run_id, "run id")
        if HEX64.fullmatch(baseline_sha256) is None:
            raise WindowsPoolIsolationError("baseline digest is invalid")
        self.block_all(run_id)
        process = self._ssh(
            [
                "sudo",
                "bash",
                "-s",
                "--",
                self.worker,
                run_id,
                self.storage_dir,
                self.baseline_dir,
                baseline_sha256,
                self.container,
            ],
            input_bytes=(RESET_SCRIPT + "\n").encode(),
            timeout_seconds=15 * 60,
        )
        try:
            value = json.loads(process.stdout)
            proof = ResetProof(**value)
        except (json.JSONDecodeError, TypeError) as exc:
            raise WindowsPoolIsolationError("reset proof is invalid") from exc
        if (
            proof.schema_version != RESET_SCHEMA
            or proof.worker != self.worker
            or proof.run_id != run_id
            or proof.baseline_sha256 != baseline_sha256
            or proof.container_state != "stopped"
        ):
            raise WindowsPoolIsolationError("reset proof differs from the request")
        return proof

    def apply_egress(self, policy: Mapping[str, Any]) -> str:
        """Atomically replace block-all with one exact IP allow-list."""

        parsed = validate_egress_policy(policy)
        batch = build_nft_batch(
            self.worker,
            parsed,
            bridge_interface=self.bridge_interface,
        )
        self._persist_and_apply(batch)
        return egress_policy_sha256(parsed)
