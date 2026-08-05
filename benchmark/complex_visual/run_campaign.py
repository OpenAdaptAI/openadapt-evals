"""Run the local no-DOM complex visual workflow campaign."""

from __future__ import annotations

import base64
import hashlib
import json
import os
import statistics
import subprocess
import sys
import time
from collections import Counter, deque
from dataclasses import asdict, dataclass
from io import BytesIO
from pathlib import Path
from typing import Callable

from PIL import Image

from benchmark.complex_visual.fixture_service import (
    COLORS,
    DRIFT_COLORS,
)
from benchmark.complex_visual.observer import Observation

ROOT = Path(__file__).parent
CAMPAIGN_PATH = ROOT / "campaign.json"
TASK_PATH = ROOT / "task.json"


@dataclass(frozen=True)
class RuntimeEvidence:
    status: str
    reason: str
    delivery_uncertain: bool
    action_attempts: int
    reconnects: int
    runtime_s: float


@dataclass(frozen=True)
class Classification:
    outcome: str
    silent_incorrect_successes: int
    over_halts: int
    wrong_entity_writes: int
    duplicate_effects: int
    collateral_writes: int
    reconciled_uncertain_deliveries: int


def load_campaign() -> dict:
    return json.loads(CAMPAIGN_PATH.read_text(encoding="utf-8"))


def load_task() -> dict:
    return json.loads(TASK_PATH.read_text(encoding="utf-8"))


class FixtureClient:
    def __init__(self, root: Path, condition: str) -> None:
        environment = {
            **os.environ,
            "PYTHONPATH": os.pathsep.join(
                filter(None, (str(Path.cwd()), os.environ.get("PYTHONPATH", "")))
            ),
        }
        self.process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "benchmark.complex_visual.fixture_service",
                "--root",
                str(root),
                "--condition",
                condition,
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=environment,
        )
        self.action_attempts = 0
        self.reconnects = 0

    def request(self, operation: str, **payload: object) -> dict:
        if self.process.stdin is None or self.process.stdout is None:
            raise RuntimeError("fixture pipes are unavailable")
        if operation in {"move", "click", "type"}:
            self.action_attempts += 1
        self.process.stdin.write(json.dumps({"operation": operation, **payload}) + "\n")
        self.process.stdin.flush()
        line = self.process.stdout.readline()
        if not line:
            stderr = self.process.stderr.read() if self.process.stderr else ""
            raise RuntimeError(f"fixture exited without a response: {stderr}")
        return json.loads(line)

    def close(self) -> None:
        if self.process.poll() is None:
            self.request("close")
        self.process.wait(timeout=5)


def _rectangles(
    image: Image.Image, colors: set[tuple[int, int, int]]
) -> list[tuple[int, int, int, int]]:
    """Return exact-color connected components from pixels only."""
    pixels = image.load()
    width, height = image.size
    matching = {(x, y) for y in range(height) for x in range(width) if pixels[x, y] in colors}
    rectangles: list[tuple[int, int, int, int]] = []
    while matching:
        seed = matching.pop()
        queue = deque([seed])
        component = [seed]
        while queue:
            x, y = queue.popleft()
            for point in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
                if point in matching:
                    matching.remove(point)
                    component.append(point)
                    queue.append(point)
        xs, ys = [point[0] for point in component], [point[1] for point in component]
        rectangles.append((min(xs), min(ys), max(xs) + 1, max(ys) + 1))
    return sorted(rectangles)


def _role_rectangles(image: Image.Image, role: str) -> list[tuple[int, int, int, int]]:
    return _rectangles(image, {COLORS[role], DRIFT_COLORS[role]})


def _full_controls(image: Image.Image, role: str) -> list[tuple[int, int, int, int]]:
    # Pillow rectangle endpoints are inclusive. These are the exact public
    # fixture shapes at native and drift scale, not empirical thresholds.
    sizes = {(141, 29), (127, 26)}
    return [
        box for box in _role_rectangles(image, role) if (box[2] - box[0], box[3] - box[1]) in sizes
    ]


def _capture(client: FixtureClient) -> tuple[Image.Image, str, int]:
    response = client.request("capture")
    if not response["accepted"] and response["reason"] == "session_disconnected":
        reconnect = client.request("reconnect")
        if not reconnect["accepted"]:
            raise RuntimeError("fixture reconnect failed")
        client.reconnects += 1
        response = client.request("capture")
    payload = base64.b64decode(response["png_base64"])
    assert hashlib.sha256(payload).hexdigest() == response["frame_sha256"]
    return (
        Image.open(BytesIO(payload)).convert("RGB"),
        response["frame_sha256"],
        response["session_generation"],
    )


def _center(box: tuple[int, int, int, int]) -> tuple[int, int]:
    return ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2)


def _click_one(client: FixtureClient, role: str) -> tuple[bool, str]:
    image, digest, _ = _capture(client)
    controls = _full_controls(image, role)
    if len(controls) != 1:
        return False, "visual_target_missing_or_ambiguous"
    x, y = _center(controls[0])
    moved = client.request("move", x=x, y=y, expected_frame_sha256=digest)
    if not moved["accepted"]:
        return False, moved["reason"]
    fresh, fresh_digest, _ = _capture(client)
    controls = _full_controls(fresh, role)
    if len(controls) != 1:
        return False, "fresh_visual_target_missing_or_ambiguous"
    x, y = _center(controls[0])
    clicked = client.request("click", x=x, y=y, expected_frame_sha256=fresh_digest)
    return clicked["accepted"], clicked.get("reason", "")


def _loop_controls(client: FixtureClient, role: str) -> tuple[bool, str]:
    """Process all visible controls and prove that the loop reached zero."""
    while True:
        image, digest, _ = _capture(client)
        controls = _full_controls(image, role)
        if not controls:
            return True, ""
        x, y = _center(controls[0])
        moved = client.request("move", x=x, y=y, expected_frame_sha256=digest)
        if not moved["accepted"]:
            return False, moved["reason"]
        fresh, fresh_digest, _ = _capture(client)
        fresh_controls = _full_controls(fresh, role)
        if not fresh_controls:
            return False, "loop_target_disappeared"
        x, y = _center(fresh_controls[0])
        clicked = client.request("click", x=x, y=y, expected_frame_sha256=fresh_digest)
        if not clicked["accepted"]:
            return False, clicked.get("reason", "click_rejected")


def execute_pixel_trial(condition: str, trial: int, root: Path) -> RuntimeEvidence:
    del trial
    started = time.monotonic()
    client = FixtureClient(root, condition)
    task = load_task()
    status, reason, uncertain = "halted", "uninitialized", False
    try:
        inbox, _, _ = _capture(client)
        if len(_role_rectangles(inbox, "target_entity")) != 1:
            reason = "inbox_identity_not_unique"
            return RuntimeEvidence(
                status,
                reason,
                uncertain,
                client.action_attempts,
                client.reconnects,
                time.monotonic() - started,
            )
        priority = "urgent" if _role_rectangles(inbox, "priority_high") else "normal"
        ok, reason = _loop_controls(client, "attachment")
        if not ok:
            return RuntimeEvidence(
                status,
                reason,
                uncertain,
                client.action_attempts,
                client.reconnects,
                time.monotonic() - started,
            )
        ok, reason = _click_one(client, "tab_worklist")
        if not ok:
            return RuntimeEvidence(
                status,
                reason,
                uncertain,
                client.action_attempts,
                client.reconnects,
                time.monotonic() - started,
            )
        worklist, _, _ = _capture(client)
        if len(_role_rectangles(worklist, "target_entity")) != 1:
            reason = "worklist_identity_not_unique"
            return RuntimeEvidence(
                status,
                reason,
                uncertain,
                client.action_attempts,
                client.reconnects,
                time.monotonic() - started,
            )
        ok, reason = _loop_controls(client, "row_task")
        if not ok:
            return RuntimeEvidence(
                status,
                reason,
                uncertain,
                client.action_attempts,
                client.reconnects,
                time.monotonic() - started,
            )
        ok, reason = _click_one(client, priority)
        if not ok:
            return RuntimeEvidence(
                status,
                reason,
                uncertain,
                client.action_attempts,
                client.reconnects,
                time.monotonic() - started,
            )
        ok, reason = _click_one(client, "tab_editor")
        if not ok:
            return RuntimeEvidence(
                status,
                reason,
                uncertain,
                client.action_attempts,
                client.reconnects,
                time.monotonic() - started,
            )
        editor, digest, _ = _capture(client)
        fields = _role_rectangles(editor, "field")
        if len(fields) != 1:
            reason = "document_field_not_unique"
            return RuntimeEvidence(
                status,
                reason,
                uncertain,
                client.action_attempts,
                client.reconnects,
                time.monotonic() - started,
            )
        x, y = _center(fields[0])
        moved = client.request("move", x=x, y=y, expected_frame_sha256=digest)
        if not moved["accepted"]:
            reason = moved["reason"]
            return RuntimeEvidence(
                status,
                reason,
                uncertain,
                client.action_attempts,
                client.reconnects,
                time.monotonic() - started,
            )
        fresh, fresh_digest, _ = _capture(client)
        x, y = _center(_role_rectangles(fresh, "field")[0])
        clicked = client.request("click", x=x, y=y, expected_frame_sha256=fresh_digest)
        if not clicked["accepted"]:
            reason = clicked["reason"]
            return RuntimeEvidence(
                status,
                reason,
                uncertain,
                client.action_attempts,
                client.reconnects,
                time.monotonic() - started,
            )
        typed_frame, typed_digest, _ = _capture(client)
        del typed_frame
        typed = client.request(
            "type",
            text=task["expected_document_text"].removesuffix("\n"),
            expected_frame_sha256=typed_digest,
        )
        if not typed["accepted"]:
            reason = typed["reason"]
            return RuntimeEvidence(
                status,
                reason,
                uncertain,
                client.action_attempts,
                client.reconnects,
                time.monotonic() - started,
            )
        ok, reason = _click_one(client, "save")
        if not ok:
            return RuntimeEvidence(
                status,
                reason,
                uncertain,
                client.action_attempts,
                client.reconnects,
                time.monotonic() - started,
            )

        resolved, resolved_digest, _ = _capture(client)
        if (
            len(_role_rectangles(resolved, "target_entity")) != 1
            or len(_full_controls(resolved, "commit")) != 1
        ):
            reason = "commit_resolution_failed"
            return RuntimeEvidence(
                status,
                reason,
                uncertain,
                client.action_attempts,
                client.reconnects,
                time.monotonic() - started,
            )
        commit = _full_controls(resolved, "commit")[0]
        x, y = _center(commit)
        moved = client.request("move", x=x, y=y, expected_frame_sha256=resolved_digest)
        if not moved["accepted"]:
            reason = moved["reason"]
            return RuntimeEvidence(
                status,
                reason,
                uncertain,
                client.action_attempts,
                client.reconnects,
                time.monotonic() - started,
            )
        fresh, fresh_digest, _ = _capture(client)
        if len(_role_rectangles(fresh, "target_entity")) != 1:
            reason = "fresh_identity_mismatch"
            return RuntimeEvidence(
                status,
                reason,
                uncertain,
                client.action_attempts,
                client.reconnects,
                time.monotonic() - started,
            )
        commits = _full_controls(fresh, "commit")
        if len(commits) != 1:
            reason = "fresh_commit_missing_or_ambiguous"
            return RuntimeEvidence(
                status,
                reason,
                uncertain,
                client.action_attempts,
                client.reconnects,
                time.monotonic() - started,
            )
        x, y = _center(commits[0])
        clicked = client.request("click", x=x, y=y, expected_frame_sha256=fresh_digest)
        uncertain = bool(clicked.get("delivery_uncertain"))
        if uncertain:
            status, reason = "delivery_uncertain", clicked["reason"]
        elif clicked["accepted"]:
            status, reason = "completed", ""
        else:
            status, reason = "halted", clicked.get("reason", "commit_rejected")
        return RuntimeEvidence(
            status,
            reason,
            uncertain,
            client.action_attempts,
            client.reconnects,
            time.monotonic() - started,
        )
    finally:
        client.close()


def read_observation(root: Path) -> Observation:
    """Run the oracle in a separate process with new read-only store handles."""
    environment = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(
            filter(None, (str(Path.cwd()), os.environ.get("PYTHONPATH", "")))
        ),
    }
    process = subprocess.run(
        [sys.executable, "-m", "benchmark.complex_visual.observer", str(root)],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )
    return Observation(**json.loads(process.stdout))


def classify(runtime: RuntimeEvidence, observed: Observation, expected: str) -> Classification:
    """Derive the outcome only from independent effects and runtime delivery state."""
    complete = (
        observed.target_action_count == 1
        and observed.target_status == "complete"
        and observed.target_csv_status == "complete"
        and observed.wrong_entity_status == "pending"
        and observed.wrong_entity_csv_status == "pending"
        and observed.target_route == "urgent"
        and observed.target_csv_route == "urgent"
        and observed.attachment_count == 2
        and observed.action_document_sha256_ok
        and observed.document_ok
        and observed.mail_count == 1
        and observed.mail_ok
        and observed.collateral_write_count == 0
        and observed.wrong_entity_action_count == 0
    )
    any_effect = observed.persisted_effect_count > 0
    duplicates = max(0, observed.target_action_count - 1) + max(0, observed.mail_count - 1)
    wrong_writes = (
        observed.wrong_entity_action_count
        + (observed.wrong_entity_status != "pending")
        + (observed.wrong_entity_csv_status != "pending")
    )
    if runtime.delivery_uncertain:
        outcome = "verified" if complete else "reconciliation_required"
    elif runtime.status == "completed" and complete:
        outcome = "verified"
    elif runtime.status == "halted" and not any_effect:
        outcome = "safe_halt"
    else:
        outcome = "incorrect_success"
    permits_verified = expected in {
        "verified",
        "verified_or_safe_halt",
        "verified_or_reconciliation_required",
    }
    permits_halt = expected in {"safe_halt", "verified_or_safe_halt"}
    return Classification(
        outcome=outcome,
        silent_incorrect_successes=int(runtime.status == "completed" and not complete),
        over_halts=int(outcome == "safe_halt" and permits_verified and not permits_halt),
        wrong_entity_writes=int(wrong_writes),
        duplicate_effects=duplicates,
        collateral_writes=observed.collateral_write_count,
        reconciled_uncertain_deliveries=int(runtime.delivery_uncertain and complete),
    )


def _write_truth(root: Path) -> None:
    truth = load_task()
    (root / "ground_truth.json").write_text(
        json.dumps(truth, sort_keys=True) + "\n", encoding="utf-8"
    )


def run_campaign(
    output: Path, execute: Callable[[str, int, Path], RuntimeEvidence] = execute_pixel_trial
) -> dict:
    campaign = load_campaign()
    metrics: Counter[str] = Counter()
    results, runtimes = [], []
    output.mkdir(parents=True, exist_ok=True)
    for condition in campaign["conditions"]:
        for trial in range(1, campaign["trials_per_condition"] + 1):
            root = output / f"{condition['id']}-{trial}"
            root.mkdir()
            _write_truth(root)
            runtime = execute(condition["id"], trial, root)
            observed = read_observation(root)
            result = classify(runtime, observed, condition["expect"])
            outcome_metric = {
                "verified": "verified_outcomes",
                "safe_halt": "safe_halts",
                "reconciliation_required": "reconciliation_required",
                "incorrect_success": "incorrect_successes",
            }[result.outcome]
            metrics[outcome_metric] += 1
            for key in (
                "silent_incorrect_successes",
                "over_halts",
                "wrong_entity_writes",
                "duplicate_effects",
                "collateral_writes",
                "reconciled_uncertain_deliveries",
            ):
                metrics[key] += getattr(result, key)
            metrics["model_calls"] += 0
            runtimes.append(runtime.runtime_s)
            transcript = [
                json.loads(line)
                for line in (root / "interaction.jsonl").read_text(encoding="utf-8").splitlines()
            ]
            results.append(
                {
                    "condition": condition["id"],
                    "trial": trial,
                    "runtime": asdict(runtime),
                    "observation": asdict(observed),
                    "classification": asdict(result),
                    "interaction": transcript,
                }
            )
    for key in campaign["required_metrics"]:
        metrics[key] += 0
    metrics["p50_runtime_s"] = statistics.median(runtimes)
    metrics["p95_runtime_s"] = sorted(runtimes)[max(0, int(len(runtimes) * 0.95) - 1)]
    report = {
        "schema_version": campaign["schema_version"],
        "execution_boundary": "local_no_dom_pixel_fixture",
        "metrics": dict(metrics),
        "results": results,
    }
    (output / "report.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report


def main() -> None:
    import tempfile

    with tempfile.TemporaryDirectory(prefix="openadapt-complex-visual-") as directory:
        report = run_campaign(Path(directory))
        print(json.dumps(report["metrics"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
