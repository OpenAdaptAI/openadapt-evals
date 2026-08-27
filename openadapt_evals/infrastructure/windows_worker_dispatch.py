"""Atomic, one-use dispatch for a centrally authorized Windows worker task."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import subprocess
from dataclasses import asdict, dataclass
from typing import Any, Mapping

from openadapt_evals.infrastructure.windows_worker_trust import (
    PROCESS_START_IDENTITY_DOMAIN,
    AuthorizedWorkerDispatch,
    VerifiedWorkerAdmission,
    canonical_json,
)

SAFE_VALUE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/+ -]{0,255}$")
SHA256 = re.compile(r"^sha256:[a-f0-9]{64}$")
DECIMAL_ID = re.compile(r"^[1-9][0-9]*$")
TIMESTAMP = re.compile(
    r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$"
)
PROCESS_SCHEMA = "openadapt.qualification-worker-process-evidence/v1"


class WorkerDispatchError(RuntimeError):
    """The authorized task did not cross the atomic worker dispatch boundary."""


@dataclass(frozen=True)
class QualifiedProcessEvidence:
    schema_version: str
    worker_admission_sha256: str
    provider_identity_sha256: str
    worker_identity_sha256: str
    live_provider_observation_sha256: str
    run_id: str
    run_attempt: str
    start_id_sha256: str
    dispatch_id_sha256: str
    task_id_sha256: str
    task_condition_sha256: str
    capability_handle_sha256: str
    process_lease_sha256: str
    pid: int
    process_group_id: int
    process_start_ticks: str
    launched_at: str
    executable_sha256: str
    process_start_identity_sha256: str
    subset_sha256: str
    oracle_sha256: str
    container_state_sha256: str
    burn_ledger_revision: int
    burned_at: str
    ledger_readback_sha256: str


def _validate_program_value(value: str, label: str) -> str:
    if not isinstance(value, str) or SAFE_VALUE.fullmatch(value) is None:
        raise WorkerDispatchError(f"{label} is invalid")
    return value


def _parse_process(value: object) -> QualifiedProcessEvidence:
    if not isinstance(value, Mapping) or set(value) != set(
        QualifiedProcessEvidence.__dataclass_fields__
    ):
        raise WorkerDispatchError("qualified process evidence is not closed")
    try:
        process = QualifiedProcessEvidence(**value)
    except TypeError as exc:  # pragma: no cover
        raise WorkerDispatchError("qualified process evidence is invalid") from exc
    if process.schema_version != PROCESS_SCHEMA:
        raise WorkerDispatchError("qualified process evidence schema is invalid")
    for field in (
        "worker_admission_sha256",
        "provider_identity_sha256",
        "worker_identity_sha256",
        "live_provider_observation_sha256",
        "start_id_sha256",
        "dispatch_id_sha256",
        "task_id_sha256",
        "task_condition_sha256",
        "capability_handle_sha256",
        "process_lease_sha256",
        "executable_sha256",
        "process_start_identity_sha256",
        "subset_sha256",
        "oracle_sha256",
        "container_state_sha256",
        "ledger_readback_sha256",
    ):
        item = getattr(process, field)
        if not isinstance(item, str) or SHA256.fullmatch(item) is None:
            raise WorkerDispatchError(f"qualified process {field} is invalid")
    if (
        process.run_attempt != "1"
        or not isinstance(process.run_id, str)
        or DECIMAL_ID.fullmatch(process.run_id) is None
        or not isinstance(process.pid, int)
        or isinstance(process.pid, bool)
        or process.pid < 1
        or not isinstance(process.process_group_id, int)
        or isinstance(process.process_group_id, bool)
        or process.process_group_id < 1
        or not isinstance(process.process_start_ticks, str)
        or not process.process_start_ticks.isdigit()
    ):
        raise WorkerDispatchError("qualified process identity is invalid")
    if (
        not isinstance(process.burn_ledger_revision, int)
        or isinstance(process.burn_ledger_revision, bool)
        or process.burn_ledger_revision <= 0
    ):
        raise WorkerDispatchError("qualified process burn revision is invalid")
    if (
        not isinstance(process.launched_at, str)
        or TIMESTAMP.fullmatch(process.launched_at) is None
        or not isinstance(process.burned_at, str)
        or TIMESTAMP.fullmatch(process.burned_at) is None
    ):
        raise WorkerDispatchError("qualified process timestamp is invalid")
    return process


_ATOMIC_LAUNCH_PROGRAM = r"""
import base64
import datetime
import fcntl
import hashlib
import json
import os
import pathlib
import re
import subprocess
import sys
import time

worker, container, policy_sha256, container_state_sha256 = sys.argv[1:]
payload = json.loads(sys.stdin.buffer.read())
if set(payload) != {
    'admission', 'dispatch', 'capability_base64', 'subset_base64',
    'agent', 'model', 'experiment', 'api_key_base64'
}:
    raise SystemExit('dispatch payload is not closed')
admission = payload['admission']
dispatch = payload['dispatch']
capability = base64.b64decode(payload['capability_base64'], validate=True)
api_key = base64.b64decode(payload['api_key_base64'], validate=True)
subset = base64.b64decode(payload['subset_base64'], validate=True)
if not capability or hashlib.sha256(capability).hexdigest() != dispatch['capability_handle_sha256'][7:]:
    raise SystemExit('dispatch capability differs')
if b'\x00' in api_key or b'\n' in api_key or not api_key:
    raise SystemExit('API credential is invalid')
run_id = dispatch['run_id']
root = pathlib.Path('/var/lib/openadapt/windows-burned-runs') / run_id
lock_fd = os.open(
    pathlib.Path('/var/lock') / f'openadapt-windows-{worker}.lock',
    os.O_WRONLY | os.O_CREAT,
    0o600,
)
fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
reservation = root / 'reservation.json'
container_record = root / 'container-state.sha256'
authority_record = root / 'start-authority'
if not reservation.is_file() or reservation.is_symlink():
    raise SystemExit('durable run reservation is absent')
if not container_record.is_file() or container_record.read_text(encoding='ascii').strip() != container_state_sha256:
    raise SystemExit('container generation binding differs')
expected_authority = '\n'.join([
    admission['admission_object_sha256'], admission['provider_identity_sha256'],
    admission['live_provider_observation_sha256'], admission['worker_identity_sha256'], ''
])
if not authority_record.is_file() or authority_record.read_text(encoding='ascii') != expected_authority:
    raise SystemExit('start authority binding differs')
active_policy = pathlib.Path('/run/openadapt/windows-egress.sha256')
active_rules = pathlib.Path('/run/openadapt/windows-egress-active.nft')
if not active_policy.is_file() or active_policy.read_text(encoding='ascii').strip() != policy_sha256:
    raise SystemExit('active egress policy differs')
subprocess.run(['nft', '-c', '-f', str(active_rules)], check=True)

raw_container = json.loads(subprocess.run(
    ['docker', 'inspect', container], check=True, capture_output=True, text=True
).stdout)
if not isinstance(raw_container, list) or len(raw_container) != 1:
    raise SystemExit('container inspection is not singular')
container_item = raw_container[0]
if container_item.get('State', {}).get('Running') is not True:
    raise SystemExit('qualified container is not running')
container_projection = {
    'schema_version': 'openadapt.windows-container-state/v1',
    'container_id': container_item.get('Id'),
    'name': container_item.get('Name'),
    'image': container_item.get('Image'),
    'config': container_item.get('Config'),
    'host_config': container_item.get('HostConfig'),
    'mounts': container_item.get('Mounts'),
    'network_settings': container_item.get('NetworkSettings', {}).get('Networks'),
    'graph_driver': container_item.get('GraphDriver'),
    'restart_count': container_item.get('RestartCount'),
    'host_pid': container_item.get('State', {}).get('Pid'),
    'started_at': container_item.get('State', {}).get('StartedAt'),
}
container_payload = json.dumps(
    container_projection, sort_keys=True, separators=(',', ':')
).encode('utf-8')
live_container_state = 'sha256:' + hashlib.sha256(
    b'OpenAdapt Windows qualified container state v1\0' + container_payload
).hexdigest()
if live_container_state != container_state_sha256:
    raise SystemExit('live container generation differs')

# The remote ledger is durable across reboot.  Its revision changes in the
# same host lock as the one-use dispatch claim.
ledger = pathlib.Path('/var/lib/openadapt/windows-burn-ledger')
ledger.mkdir(mode=0o700, parents=True, exist_ok=True)
revision_path = ledger / 'revision'
revision = int(revision_path.read_text(encoding='ascii').strip()) + 1 if revision_path.exists() else 1
temporary_revision = ledger / '.revision.tmp'
fd = os.open(temporary_revision, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, 'w', encoding='ascii') as stream:
    stream.write(str(revision) + '\n')
    stream.flush(); os.fsync(stream.fileno())
os.replace(temporary_revision, revision_path)
burned_at = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec='seconds').replace('+00:00', 'Z')
dispatch_path = root / 'dispatch.json'
fd = os.open(dispatch_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
dispatch_bytes = json.dumps(dispatch, sort_keys=True, separators=(',', ':')).encode('utf-8') + b'\n'
with os.fdopen(fd, 'wb') as stream:
    stream.write(dispatch_bytes); stream.flush(); os.fsync(stream.fileno())
burn_record = {
    'dispatch_id_sha256': dispatch['dispatch_id_sha256'],
    'capability_handle_sha256': dispatch['capability_handle_sha256'],
    'burn_ledger_revision': revision,
    'burned_at': burned_at,
}
burn_bytes = json.dumps(burn_record, sort_keys=True, separators=(',', ':')).encode('utf-8') + b'\n'
fd = os.open(root / 'burn.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
with os.fdopen(fd, 'wb') as stream:
    stream.write(burn_bytes); stream.flush(); os.fsync(stream.fileno())
directory_fd = os.open(root, os.O_RDONLY)
try: os.fsync(directory_fd)
finally: os.close(directory_fd)
ledger_readback = 'sha256:' + hashlib.sha256(
    revision_path.read_bytes() + dispatch_path.read_bytes() + (root / 'burn.json').read_bytes()
).hexdigest()

# Every guest write occurs after the durable one-use claim and while the same
# host lock remains held.  A failure leaves the identity burned.
subset_digest = 'sha256:' + hashlib.sha256(subset).hexdigest()
guest_root = f'/tmp/openadapt-qualified/{run_id}'
try:
    subset_object = json.loads(subset)
except json.JSONDecodeError as exc:
    raise SystemExit('task subset is invalid') from exc
if (
    not isinstance(subset_object, dict) or len(subset_object) != 1 or
    not all(isinstance(key, str) and re.fullmatch(r'[A-Za-z0-9._-]+', key)
            for key in subset_object)
):
    raise SystemExit('task subset is invalid')
domain, task_ids = next(iter(subset_object.items()))
if (
    not isinstance(task_ids, list) or len(task_ids) != 1 or
    not isinstance(task_ids[0], str) or
    re.fullmatch(r'[A-Za-z0-9._-]+', task_ids[0]) is None
):
    raise SystemExit('task subset is invalid')
task_id = task_ids[0]
oracle_source = (
    f'/client/evaluation_examples_windows/examples/{domain}/{task_id}.json'
)
oracle_result = subprocess.run(
    ['docker', 'exec', container, 'cat', oracle_source],
    check=True, capture_output=True,
)
oracle_object = json.loads(oracle_result.stdout)
if not isinstance(oracle_object, dict) or not oracle_object:
    raise SystemExit('task oracle is invalid')
oracle_bytes = json.dumps(
    oracle_object, sort_keys=True, separators=(',', ':')
).encode('utf-8') + b'\n'
oracle_sha256 = 'sha256:' + hashlib.sha256(oracle_bytes).hexdigest()
fd = os.open(root / 'oracle.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
with os.fdopen(fd, 'wb') as stream:
    stream.write(oracle_bytes); stream.flush(); os.fsync(stream.fileno())
subprocess.run(['docker', 'exec', container, 'mkdir', '-m', '0700', '-p', guest_root], check=True)
subprocess.run(
    ['docker', 'exec', '-i', container, 'tee', f'{guest_root}/subset.json'],
    input=subset,
    check=True,
    stdout=subprocess.DEVNULL,
)
actual_subset = subprocess.run(
    ['docker', 'exec', container, 'sha256sum', f'{guest_root}/subset.json'],
    check=True, capture_output=True, text=True,
).stdout.split()[0]
if actual_subset != subset_digest[7:]:
    raise SystemExit('guest subset readback differs')
launch_script = r'''set -euo pipefail
IFS= read -r OPENAI_API_KEY
export OPENAI_API_KEY
root="$1"; agent="$2"; model="$3"; experiment="$4"; run_id="$5"
executable="$(command -v bash)"
executable_sha256="sha256:$(sha256sum "$executable" | cut -d' ' -f1)"
launched_at="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
setsid bash -c '
  set +e
  cd /client
  python -u run.py --agent "$1" --model "$2" --exp_name "$3" \
    --worker_id 0 --num_workers 1 --emulator_ip 172.30.0.2 \
    --test_all_meta_path "$4" > "$5/log" 2>&1
  code=$?
  printf "%s\n" "$code" > "$5/exit"
  exit "$code"
' -- "$agent" "$model" "$experiment" "$root/subset.json" "$root" &
pid=$!
pgid="$(ps -o pgid= -p "$pid" | tr -d ' ')"
start_ticks="$(sed -E 's/.*\) //' "/proc/$pid/stat" | awk '{print $20}')"
printf '{"pid":%s,"process_group_id":%s,"start_ticks":"%s","launched_at":"%s","executable_sha256":"%s"}\n' \
  "$pid" "$pgid" "$start_ticks" "$launched_at" "$executable_sha256"
'''
launched = subprocess.run(
    ['docker', 'exec', '-i', container, 'bash', '-c', launch_script, '--', guest_root,
     payload['agent'], payload['model'], payload['experiment'], run_id],
    input=api_key + b'\n',
    check=True, capture_output=True,
)
try:
    process = json.loads(launched.stdout.splitlines()[-1])
except (IndexError, json.JSONDecodeError) as exc:
    raise SystemExit('qualified process launch evidence is invalid') from exc
process_projection = {
    'provider_identity_sha256': dispatch['provider_identity_sha256'],
    'worker_identity_sha256': dispatch['worker_identity_sha256'],
    'run_id': run_id, 'run_attempt': '1',
    'start_id_sha256': dispatch['start_id_sha256'],
    'dispatch_id_sha256': dispatch['dispatch_id_sha256'],
    'pid': process['pid'], 'process_group_id': process['process_group_id'],
    'process_start_ticks': process['start_ticks'],
    'launched_at': process['launched_at'],
    'executable_sha256': process['executable_sha256'],
}
process_start = 'sha256:' + hashlib.sha256(
    b'OpenAdapt qualification worker process start v1\0' +
    json.dumps(process_projection, sort_keys=True, separators=(',', ':')).encode('utf-8')
).hexdigest()
evidence = {
    'schema_version': 'openadapt.qualification-worker-process-evidence/v1',
    'worker_admission_sha256': dispatch['worker_admission_sha256'],
    'provider_identity_sha256': dispatch['provider_identity_sha256'],
    'worker_identity_sha256': dispatch['worker_identity_sha256'],
    'live_provider_observation_sha256': dispatch['live_provider_observation_sha256'],
    'run_id': run_id, 'run_attempt': '1',
    'start_id_sha256': dispatch['start_id_sha256'],
    'dispatch_id_sha256': dispatch['dispatch_id_sha256'],
    'task_id_sha256': dispatch['task_id_sha256'],
    'task_condition_sha256': dispatch['task_condition_sha256'],
    'capability_handle_sha256': dispatch['capability_handle_sha256'],
    'process_lease_sha256': dispatch['process_lease_sha256'],
    'pid': process['pid'], 'process_group_id': process['process_group_id'],
    'process_start_ticks': process['start_ticks'],
    'launched_at': process['launched_at'],
    'executable_sha256': process['executable_sha256'],
    'process_start_identity_sha256': process_start,
    'subset_sha256': subset_digest,
    'oracle_sha256': oracle_sha256,
    'container_state_sha256': container_state_sha256,
    'burn_ledger_revision': revision, 'burned_at': burned_at,
    'ledger_readback_sha256': ledger_readback,
}
process_bytes = json.dumps(evidence, sort_keys=True, separators=(',', ':')).encode('utf-8') + b'\n'
fd = os.open(root / 'process.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
with os.fdopen(fd, 'wb') as stream:
    stream.write(process_bytes); stream.flush(); os.fsync(stream.fileno())
print(json.dumps(evidence, sort_keys=True, separators=(',', ':')))
"""


def launch_authorized_process(
    manager: Any,
    *,
    admission: VerifiedWorkerAdmission,
    dispatch: AuthorizedWorkerDispatch,
    policy_sha256: str,
    container_state_sha256: str,
    agent: str,
    model: str,
    experiment: str,
    subset: bytes,
    api_key: str,
) -> QualifiedProcessEvidence:
    """Consume one capability and start its exact process in one host lock."""

    for value, label in ((agent, "agent"), (model, "model"), (experiment, "experiment")):
        _validate_program_value(value, label)
    if not isinstance(subset, bytes) or not subset or len(subset) > 1_048_576:
        raise WorkerDispatchError("task subset is invalid")
    if not isinstance(api_key, str) or not api_key or "\n" in api_key or "\x00" in api_key:
        raise WorkerDispatchError("API credential is invalid")
    payload = {
        "admission": dict(admission.object),
        "dispatch": dict(dispatch.object),
        "capability_base64": base64.b64encode(dispatch.capability).decode("ascii"),
        "subset_base64": base64.b64encode(subset).decode("ascii"),
        "agent": agent,
        "model": model,
        "experiment": experiment,
        "api_key_base64": base64.b64encode(api_key.encode("utf-8")).decode("ascii"),
    }
    result: subprocess.CompletedProcess[bytes] = manager._ssh(
        [
            "sudo",
            "python3",
            "-c",
            _ATOMIC_LAUNCH_PROGRAM,
            manager.worker,
            manager.container,
            policy_sha256,
            container_state_sha256,
        ],
        input_bytes=canonical_json(payload),
        timeout_seconds=300,
    )
    try:
        process = _parse_process(json.loads(result.stdout.splitlines()[-1]))
    except (IndexError, json.JSONDecodeError) as exc:
        raise WorkerDispatchError("qualified process evidence is invalid") from exc
    expected = {
        "worker_admission_sha256": admission.object["admission_object_sha256"],
        "provider_identity_sha256": dispatch.object["provider_identity_sha256"],
        "worker_identity_sha256": dispatch.object["worker_identity_sha256"],
        "live_provider_observation_sha256": dispatch.object[
            "live_provider_observation_sha256"
        ],
        "run_id": dispatch.object["run_id"],
        "start_id_sha256": dispatch.object["start_id_sha256"],
        "dispatch_id_sha256": dispatch.object["dispatch_id_sha256"],
        "task_id_sha256": dispatch.object["task_id_sha256"],
        "task_condition_sha256": dispatch.object["task_condition_sha256"],
        "capability_handle_sha256": dispatch.object["capability_handle_sha256"],
        "process_lease_sha256": dispatch.object["process_lease_sha256"],
        "container_state_sha256": container_state_sha256,
    }
    if any(getattr(process, key) != expected_value for key, expected_value in expected.items()):
        raise WorkerDispatchError("qualified process binding differs")
    if process.subset_sha256 != "sha256:" + hashlib.sha256(subset).hexdigest():
        raise WorkerDispatchError("qualified process subset binding differs")
    process_projection = {
        "provider_identity_sha256": process.provider_identity_sha256,
        "worker_identity_sha256": process.worker_identity_sha256,
        "run_id": process.run_id,
        "run_attempt": process.run_attempt,
        "start_id_sha256": process.start_id_sha256,
        "dispatch_id_sha256": process.dispatch_id_sha256,
        "pid": process.pid,
        "process_group_id": process.process_group_id,
        "process_start_ticks": process.process_start_ticks,
        "launched_at": process.launched_at,
        "executable_sha256": process.executable_sha256,
    }
    expected_process_start = "sha256:" + hashlib.sha256(
        PROCESS_START_IDENTITY_DOMAIN + canonical_json(process_projection)
    ).hexdigest()
    if process.process_start_identity_sha256 != expected_process_start:
        raise WorkerDispatchError("qualified process start identity differs")
    return process


_READ_PROCESS_PROGRAM = r"""
import hashlib
import json
import os
import pathlib
import fcntl
import subprocess
import sys

container, run_id, expected_process, expected_container = sys.argv[1:]
root = pathlib.Path('/var/lib/openadapt/windows-burned-runs') / run_id
lock_fd = os.open(
    pathlib.Path('/var/lock') / f'openadapt-windows-terminal-{run_id}.lock',
    os.O_WRONLY | os.O_CREAT,
    0o600,
)
fcntl.flock(lock_fd, fcntl.LOCK_EX)
process_path = root / 'process.json'
if not process_path.is_file() or process_path.is_symlink():
    raise SystemExit('process evidence is absent')
process_bytes = process_path.read_bytes()
if hashlib.sha256(process_bytes).hexdigest() != expected_process:
    raise SystemExit('process evidence readback differs')
process = json.loads(process_bytes)
raw_container = json.loads(subprocess.run(
    ['docker', 'inspect', container], check=True, capture_output=True, text=True
).stdout)
if not isinstance(raw_container, list) or len(raw_container) != 1:
    raise SystemExit('container inspection is not singular')
container_item = raw_container[0]
container_projection = {
    'schema_version': 'openadapt.windows-container-state/v1',
    'container_id': container_item.get('Id'),
    'name': container_item.get('Name'),
    'image': container_item.get('Image'),
    'config': container_item.get('Config'),
    'host_config': container_item.get('HostConfig'),
    'mounts': container_item.get('Mounts'),
    'network_settings': container_item.get('NetworkSettings', {}).get('Networks'),
    'graph_driver': container_item.get('GraphDriver'),
    'restart_count': container_item.get('RestartCount'),
    'host_pid': container_item.get('State', {}).get('Pid'),
    'started_at': container_item.get('State', {}).get('StartedAt'),
}
container_payload = json.dumps(
    container_projection, sort_keys=True, separators=(',', ':')
).encode('utf-8')
container_sha256 = 'sha256:' + hashlib.sha256(
    b'OpenAdapt Windows qualified container state v1\0' + container_payload
).hexdigest()
if container_sha256 != expected_container:
    raise SystemExit('live container generation differs')
guest_root = f'/tmp/openadapt-qualified/{run_id}'
stat = subprocess.run(
    ['docker', 'exec', container, 'cat', f"/proc/{process['pid']}/stat"],
    capture_output=True, text=True,
)
close = stat.stdout.rfind(') ')
stat_fields = stat.stdout[close + 2:].split() if close >= 0 else []
actual_executable = subprocess.run(
    [
        'docker', 'exec', container, 'bash', '-c',
        'sha256sum "$(readlink -f "/proc/$1/exe")" | cut -d" " -f1',
        '--', str(process['pid']),
    ],
    capture_output=True, text=True,
)
alive = (
    stat.returncode == 0 and len(stat_fields) >= 20 and
    stat_fields[2] == str(process['process_group_id']) and
    stat_fields[19] == process['process_start_ticks'] and
    actual_executable.returncode == 0 and
    'sha256:' + actual_executable.stdout.strip() == process['executable_sha256']
)
if alive:
    print(json.dumps({'state': 'RUNNING'}, sort_keys=True, separators=(',', ':')))
    raise SystemExit(0)
exit_result = subprocess.run(
    ['docker', 'exec', container, 'cat', f'{guest_root}/exit'],
    capture_output=True, text=True,
)
log_result = subprocess.run(
    ['docker', 'exec', container, 'cat', f'{guest_root}/log'],
    check=True, capture_output=True,
)
exit_raw = exit_result.stdout.strip()
exit_code = int(exit_raw) if exit_result.returncode == 0 and exit_raw.lstrip('-').isdigit() else None
if exit_code is None:
    print(json.dumps({
        'state': 'UNCERTAIN',
        'exit_code': None,
        'log_sha256': 'sha256:' + hashlib.sha256(log_result.stdout).hexdigest(),
        'log_size_bytes': len(log_result.stdout),
        'process': process,
    }, sort_keys=True, separators=(',', ':')))
    raise SystemExit(0)
oracle_path = root / 'oracle.json'
if not oracle_path.is_file() or oracle_path.is_symlink():
    raise SystemExit('task oracle is absent')
oracle_bytes = oracle_path.read_bytes()
if 'sha256:' + hashlib.sha256(oracle_bytes).hexdigest() != process['oracle_sha256']:
    raise SystemExit('task oracle readback differs')
result_path = root / 'oracle-result.json'
if not result_path.exists():
    evaluated = subprocess.run(
        [
            'docker', 'exec', '-i', container, 'curl', '--fail-with-body',
            '--silent', '--show-error', '--max-time', '300',
            '-H', 'Content-Type: application/json', '--data-binary', '@-',
            'http://127.0.0.1:5050/evaluate',
        ],
        input=oracle_bytes,
        check=True,
        capture_output=True,
    )
    result_object = json.loads(evaluated.stdout)
    if (
        not isinstance(result_object, dict) or
        set(result_object) != {'success', 'score', 'reason'} or
        type(result_object['success']) is not bool or
        not isinstance(result_object['score'], (int, float)) or
        isinstance(result_object['score'], bool) or
        not 0.0 <= float(result_object['score']) <= 1.0 or
        not isinstance(result_object['reason'], str)
    ):
        raise SystemExit('task oracle result is invalid')
    result_bytes = json.dumps(
        result_object, sort_keys=True, separators=(',', ':')
    ).encode('utf-8') + b'\n'
    fd = os.open(result_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o400)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(result_bytes); stream.flush(); os.fsync(stream.fileno())
result_bytes = result_path.read_bytes()
result_object = json.loads(result_bytes)
print(json.dumps({
    'state': 'TERMINAL',
    'exit_code': exit_code,
    'oracle_sha256': process['oracle_sha256'],
    'result_sha256': 'sha256:' + hashlib.sha256(result_bytes).hexdigest(),
    'oracle_success': result_object['success'],
    'oracle_score': float(result_object['score']),
    'log_sha256': 'sha256:' + hashlib.sha256(log_result.stdout).hexdigest(),
    'log_size_bytes': len(log_result.stdout),
    'process': process,
}, sort_keys=True, separators=(',', ':')))
"""


def read_process_terminal(manager: Any, process: QualifiedProcessEvidence) -> Mapping[str, Any]:
    """Read exact process/log state without converting exit zero to success."""

    process_bytes = canonical_json(asdict(process)) + b"\n"
    expected = hashlib.sha256(process_bytes).hexdigest()
    result = manager._ssh(
        [
            "sudo",
            "python3",
            "-c",
            _READ_PROCESS_PROGRAM,
            manager.container,
            process.run_id,
            expected,
            process.container_state_sha256,
        ]
    )
    try:
        value = json.loads(result.stdout.splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        raise WorkerDispatchError("qualified terminal readback is invalid") from exc
    if not isinstance(value, Mapping) or value.get("state") not in {
        "RUNNING",
        "TERMINAL",
        "UNCERTAIN",
    }:
        raise WorkerDispatchError("qualified terminal readback is invalid")
    state = value["state"]
    expected_keys = {
        "RUNNING": {"state"},
        "UNCERTAIN": {
            "state",
            "exit_code",
            "log_sha256",
            "log_size_bytes",
            "process",
        },
        "TERMINAL": {
            "state",
            "exit_code",
            "oracle_sha256",
            "result_sha256",
            "oracle_success",
            "oracle_score",
            "log_sha256",
            "log_size_bytes",
            "process",
        },
    }[state]
    if set(value) != expected_keys:
        raise WorkerDispatchError("qualified terminal readback is not closed")
    if state != "RUNNING":
        if value["process"] != asdict(process):
            raise WorkerDispatchError("qualified terminal process binding differs")
        if not isinstance(value["log_sha256"], str) or SHA256.fullmatch(
            value["log_sha256"]
        ) is None:
            raise WorkerDispatchError("qualified terminal log digest is invalid")
        if (
            not isinstance(value["log_size_bytes"], int)
            or isinstance(value["log_size_bytes"], bool)
            or value["log_size_bytes"] < 0
        ):
            raise WorkerDispatchError("qualified terminal log size is invalid")
    if state == "TERMINAL":
        if not isinstance(value["exit_code"], int) or isinstance(
            value["exit_code"], bool
        ):
            raise WorkerDispatchError("qualified terminal exit code is invalid")
        if value["oracle_sha256"] != process.oracle_sha256:
            raise WorkerDispatchError("qualified terminal oracle binding differs")
        if not isinstance(value["result_sha256"], str) or SHA256.fullmatch(
            value["result_sha256"]
        ) is None:
            raise WorkerDispatchError("qualified terminal result digest is invalid")
        if type(value["oracle_success"]) is not bool:
            raise WorkerDispatchError("qualified terminal oracle verdict is invalid")
        if (
            not isinstance(value["oracle_score"], (int, float))
            or isinstance(value["oracle_score"], bool)
            or not 0.0 <= float(value["oracle_score"]) <= 1.0
        ):
            raise WorkerDispatchError("qualified terminal oracle score is invalid")
    return value


_INTERRUPT_PROCESS_PROGRAM = r"""
import hashlib
import json
import pathlib
import subprocess
import sys
import time

container, run_id, expected_process = sys.argv[1:]
root = pathlib.Path('/var/lib/openadapt/windows-burned-runs') / run_id
process_path = root / 'process.json'
if not process_path.is_file() or process_path.is_symlink():
    raise SystemExit('process evidence is absent')
process_bytes = process_path.read_bytes()
if hashlib.sha256(process_bytes).hexdigest() != expected_process:
    raise SystemExit('process evidence readback differs')
process = json.loads(process_bytes)
group_program = r'''import glob,hashlib,json,os,pathlib
members=[]
for path in glob.glob('/proc/[0-9]*/stat'):
    try:
        raw=pathlib.Path(path).read_text()
        close=raw.rfind(') ')
        fields=raw[close+2:].split() if close >= 0 else []
        if len(fields) >= 20:
            members.append({
                'pid': int(path.split('/')[2]),
                'process_group_id': int(fields[2]),
                'process_start_ticks': fields[19],
                'executable_sha256': 'sha256:' + hashlib.sha256(
                    pathlib.Path(os.path.realpath(path.replace('/stat', '/exe'))).read_bytes()
                ).hexdigest(),
            })
    except (OSError,ValueError):
        pass
print(json.dumps(members,sort_keys=True,separators=(',',':')))'''

def group_members():
    result = subprocess.run(
        ['docker', 'exec', container, 'python3', '-c', group_program],
        check=True, capture_output=True, text=True,
    )
    rows = json.loads(result.stdout)
    return [row for row in rows if row['process_group_id'] == process['process_group_id']]

members = group_members()
leader = [row for row in members if row['pid'] == process['pid']]
leader_matches = (
    len(leader) == 1 and
    leader[0]['process_start_ticks'] == process['process_start_ticks'] and
    leader[0]['executable_sha256'] == process['executable_sha256']
)
if leader_matches:
    subprocess.run(
        [
            'docker', 'exec', container, 'bash', '-c',
            'kill -TERM -- -"$1"', '--', str(process['process_group_id']),
        ],
        check=False,
    )
    for _ in range(50):
        if not group_members():
            break
        time.sleep(0.1)
    if group_members():
        subprocess.run(
            [
                'docker', 'exec', container, 'bash', '-c',
                'kill -KILL -- -"$1"', '--', str(process['process_group_id']),
            ],
            check=False,
        )
        for _ in range(50):
            if not group_members():
                break
            time.sleep(0.1)
remaining = group_members()
print(json.dumps({
    'state': 'INTERRUPTED_PROVEN' if not remaining else 'INTERRUPT_UNCERTAIN',
    'leader_identity_matched': leader_matches,
    'process_group_absent': not remaining,
    'remaining_member_count': len(remaining),
    'process': process,
}, sort_keys=True, separators=(',', ':')))
"""


def interrupt_process(
    manager: Any,
    process: QualifiedProcessEvidence,
) -> Mapping[str, Any]:
    """Stop the exact process group or return retained uncertain evidence."""

    process_bytes = canonical_json(asdict(process)) + b"\n"
    expected = hashlib.sha256(process_bytes).hexdigest()
    result = manager._ssh(
        [
            "sudo",
            "python3",
            "-c",
            _INTERRUPT_PROCESS_PROGRAM,
            manager.container,
            process.run_id,
            expected,
        ],
        timeout_seconds=30,
    )
    try:
        value = json.loads(result.stdout.splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        raise WorkerDispatchError("qualified interrupt evidence is invalid") from exc
    if not isinstance(value, Mapping) or set(value) != {
        "state",
        "leader_identity_matched",
        "process_group_absent",
        "remaining_member_count",
        "process",
    }:
        raise WorkerDispatchError("qualified interrupt evidence is not closed")
    if value["state"] not in {"INTERRUPTED_PROVEN", "INTERRUPT_UNCERTAIN"}:
        raise WorkerDispatchError("qualified interrupt state is invalid")
    if type(value["leader_identity_matched"]) is not bool or type(
        value["process_group_absent"]
    ) is not bool:
        raise WorkerDispatchError("qualified interrupt proof is invalid")
    if (
        not isinstance(value["remaining_member_count"], int)
        or isinstance(value["remaining_member_count"], bool)
        or value["remaining_member_count"] < 0
    ):
        raise WorkerDispatchError("qualified interrupt member count is invalid")
    if value["process"] != asdict(process):
        raise WorkerDispatchError("qualified interrupt process binding differs")
    if (value["remaining_member_count"] == 0) != value["process_group_absent"]:
        raise WorkerDispatchError("qualified interrupt absence proof differs")
    if (value["state"] == "INTERRUPTED_PROVEN") != value["process_group_absent"]:
        raise WorkerDispatchError("qualified interrupt terminal proof differs")
    return value
