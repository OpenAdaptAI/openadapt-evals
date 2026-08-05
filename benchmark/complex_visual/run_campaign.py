"""Evidence-driven headed complex visual workflow campaign."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import statistics
import subprocess
import sys
import time
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable

import numpy as np
from PIL import Image

from benchmark.complex_visual.observer import Snapshot
from benchmark.complex_visual.x11 import DeliveryAcknowledgementLost, X11Session

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
    under_halts: int
    wrong_entity_writes: int
    duplicate_effects: int
    collateral_writes: int
    reconciled_uncertain_deliveries: int


def load_campaign() -> dict:
    return json.loads(CAMPAIGN_PATH.read_text(encoding="utf-8"))


def load_task() -> dict:
    return json.loads(TASK_PATH.read_text(encoding="utf-8"))


class FixtureProcess:
    def __init__(self, root: Path, condition: str) -> None:
        self.ready_path = root / "fixture_ready.json"
        self.stderr_path = root / "fixture_stderr.log"
        self.stderr_stream = self.stderr_path.open("w", encoding="utf-8")
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
                "--ready",
                str(self.ready_path),
            ],
            stdout=subprocess.DEVNULL,
            stderr=self.stderr_stream,
            env=environment,
        )

    def wait_ready(self, timeout: float = 5.0) -> dict:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                self.stderr_stream.flush()
                raise RuntimeError(self.stderr_path.read_text(encoding="utf-8"))
            if self.ready_path.is_file():
                try:
                    return json.loads(self.ready_path.read_text(encoding="utf-8"))
                except json.JSONDecodeError:
                    pass
            time.sleep(0.03)
        raise TimeoutError("headed fixture did not become ready")

    def ready(self) -> dict:
        return json.loads(self.ready_path.read_text(encoding="utf-8"))

    def close(self) -> None:
        if self.process.poll() is None:
            self.process.terminate()
            self.process.wait(timeout=5)
        self.stderr_stream.close()


def _threshold(image: Image.Image) -> int:
    values = np.asarray(image.convert("L"), dtype=np.uint8)
    return (int(values.min()) + int(values.max())) // 2


def _crop_evidence(
    evidence_dir: Path,
    evidence_id: str,
    frame: Image.Image,
    region: list[int],
    source_frame: Path,
    window_region: list[int],
) -> dict:
    crop = frame.crop(tuple(region))
    crop_path = evidence_dir / "templates" / f"{evidence_id}.png"
    crop_path.parent.mkdir(parents=True, exist_ok=True)
    crop.save(crop_path, format="PNG")
    return {
        "path": crop_path.relative_to(evidence_dir).as_posix(),
        "source_frame": source_frame.relative_to(evidence_dir).as_posix(),
        "source_frame_sha256": hashlib.sha256(source_frame.read_bytes()).hexdigest(),
        "source_region": region,
        "search_region": window_region,
        "luminance_threshold": _threshold(crop),
    }


def _capture_source(
    x11: X11Session, evidence_dir: Path, index: int, label: str
) -> tuple[Image.Image, Path]:
    path = evidence_dir / "source_frames" / f"{index:03d}_{label}.png"
    return x11.capture(path), path


def record_demonstration(evidence_dir: Path) -> dict:
    """Create retained screenshot evidence through real X pointer and key input."""
    evidence_dir.mkdir(parents=True, exist_ok=True)
    runtime_root = evidence_dir / "authoring_fixture"
    runtime_root.mkdir()
    fixture = FixtureProcess(runtime_root, "healthy")
    x11 = X11Session()
    trace: list[dict] = []
    templates: dict[str, dict] = {}
    try:
        ready = fixture.wait_ready()
        frame, frame_path = _capture_source(x11, evidence_dir, 1, "initial_windows")
        window_for = {
            "inbox_identity": "inbox",
            "priority_high": "inbox",
            "attachment": "inbox",
            "worklist_identity": "worklist",
            "row_task": "worklist",
            "editor_identity": "editor",
            "field": "editor",
            "save": "editor",
        }
        for evidence_id, window in window_for.items():
            templates[evidence_id] = _crop_evidence(
                evidence_dir,
                evidence_id,
                frame,
                ready["regions"][evidence_id][0],
                frame_path,
                ready["windows"][window],
            )
        for evidence_id, expected_count in (("attachment", 2), ("row_task", 2)):
            centers = list(ready["centers"][evidence_id])
            if len(centers) != expected_count:
                raise RuntimeError(
                    f"authoring fixture did not expose {expected_count} {evidence_id} controls"
                )
            for x, y in centers:
                x11.click(x, y)
                trace.append({"operation": "click", "evidence_id": evidence_id, "x": x, "y": y})
        time.sleep(0.1)
        ready = fixture.ready()
        frame, frame_path = _capture_source(x11, evidence_dir, 2, "branch_controls")
        for evidence_id in ("urgent", "normal"):
            templates[evidence_id] = _crop_evidence(
                evidence_dir,
                evidence_id,
                frame,
                ready["regions"][evidence_id][0],
                frame_path,
                ready["windows"]["worklist"],
            )
        x, y = ready["centers"]["urgent"][0]
        x11.click(x, y)
        trace.append({"operation": "click", "evidence_id": "urgent", "x": x, "y": y})
        x, y = ready["centers"]["field"][0]
        x11.click(x, y)
        trace.append({"operation": "click", "evidence_id": "field", "x": x, "y": y})
        task = load_task()
        text = task["expected_document_text"].removesuffix("\n")
        x11.type_text(text)
        trace.append({"operation": "type", "character_count": len(text)})
        time.sleep(0.1)
        ready = fixture.ready()
        focused, focused_path = _capture_source(x11, evidence_dir, 3, "editor_focused")
        templates["focus"] = _crop_evidence(
            evidence_dir,
            "focus",
            focused,
            ready["regions"]["focus"][0],
            focused_path,
            ready["windows"]["editor"],
        )
        x, y = ready["centers"]["save"][0]
        x11.click(x, y)
        trace.append({"operation": "click", "evidence_id": "save", "x": x, "y": y})
        time.sleep(0.1)
        ready = fixture.ready()
        commit_frame, commit_path = _capture_source(x11, evidence_dir, 4, "commit_ready")
        templates["commit"] = _crop_evidence(
            evidence_dir,
            "commit",
            commit_frame,
            ready["regions"]["commit"][0],
            commit_path,
            ready["windows"]["editor"],
        )
    finally:
        fixture.close()
    manifest = {
        "schema_version": "openadapt.visual-evidence.v1",
        "templates": templates,
        "matching": {"pixel_spacings": [2, 3], "threshold_source": "retained_crop_range_midpoint"},
    }
    (evidence_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (evidence_dir / "event_trace.json").write_text(
        json.dumps(trace, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


class EvidenceResolver:
    """Resolve targets from retained bitmap crops without fixture role or color data."""

    def __init__(self, evidence_dir: Path) -> None:
        self.evidence_dir = evidence_dir
        self.manifest = json.loads((evidence_dir / "manifest.json").read_text(encoding="utf-8"))
        self.patterns: dict[str, np.ndarray] = {}
        for evidence_id, item in self.manifest["templates"].items():
            crop = Image.open(evidence_dir / item["path"]).convert("L")
            dark = np.asarray(crop) <= item["luminance_threshold"]
            ys, xs = np.where(dark)
            unique_xs, unique_ys = sorted(set(xs.tolist())), sorted(set(ys.tolist()))
            differences = [
                right - left
                for values in (unique_xs, unique_ys)
                for left, right in zip(values, values[1:])
                if right - left > 1
            ]
            spacing = math.gcd(*differences)
            pattern = np.zeros(
                ((ys.max() - ys.min()) // spacing + 1, (xs.max() - xs.min()) // spacing + 1),
                dtype=bool,
            )
            for x, y in zip(xs, ys):
                pattern[(y - ys.min()) // spacing, (x - xs.min()) // spacing] = True
            self.patterns[evidence_id] = pattern

    @staticmethod
    def _expanded(pattern: np.ndarray, spacing: int) -> np.ndarray:
        ink = np.zeros(
            (
                (pattern.shape[0] - 1) * spacing + spacing - 1,
                (pattern.shape[1] - 1) * spacing + spacing - 1,
            ),
            dtype=bool,
        )
        block = spacing - 1
        for y, x in np.argwhere(pattern):
            ink[y * spacing : y * spacing + block, x * spacing : x * spacing + block] = True
        return np.pad(ink, 1, constant_values=False)

    def resolve(self, image: Image.Image, evidence_id: str) -> list[tuple[int, int, int, int]]:
        item = self.manifest["templates"][evidence_id]
        left, top, right, bottom = item["search_region"]
        screen = np.asarray(image.convert("L")) <= item["luminance_threshold"]
        region = screen[top:bottom, left:right]
        dark_points = {(int(x), int(y)) for y, x in np.argwhere(region)}
        matches: list[tuple[int, int, int, int]] = []
        for spacing in self.manifest["matching"]["pixel_spacings"]:
            target = self._expanded(self.patterns[evidence_id], spacing)
            target_points = [(int(x), int(y)) for y, x in np.argwhere(target)]
            anchors = (target_points[0], target_points[len(target_points) // 2], target_points[-1])
            candidates: set[tuple[int, int]] | None = None
            for anchor_x, anchor_y in anchors:
                origins = {(x - anchor_x, y - anchor_y) for x, y in dark_points}
                candidates = origins if candidates is None else candidates & origins
            for x, y in candidates or set():
                height, width = target.shape
                if x < 0 or y < 0 or x + width > region.shape[1] or y + height > region.shape[0]:
                    continue
                if np.array_equal(region[y : y + height, x : x + width], target):
                    matches.append((left + x, top + y, left + x + width, top + y + height))
        return sorted(set(matches))


class PixelActor:
    def __init__(self, root: Path, evidence_dir: Path, condition: str) -> None:
        self.root = root
        self.frames = root / "frames"
        self.frames.mkdir()
        self.condition = condition
        self.x11 = X11Session()
        self.resolver = EvidenceResolver(evidence_dir)
        self.events: list[dict] = []
        self.capture_index = 0
        self.action_attempts = 0
        self.reconnects = 0

    def capture(self, label: str) -> tuple[Image.Image, str]:
        self.capture_index += 1
        path = self.frames / f"{self.capture_index:03d}_{label}.png"
        image = self.x11.capture(path)
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        self.events.append(
            {
                "operation": "capture",
                "label": label,
                "path": path.relative_to(self.root).as_posix(),
                "frame_sha256": digest,
            }
        )
        return image, digest

    @staticmethod
    def _center(box: tuple[int, int, int, int]) -> tuple[int, int]:
        return ((box[0] + box[2]) // 2, (box[1] + box[3]) // 2)

    def _click_match(self, evidence_id: str, box: tuple[int, int, int, int]) -> tuple[bool, str]:
        x, y = self._center(box)
        self.x11.move(x, y)
        self.action_attempts += 1
        self.events.append({"operation": "move", "evidence_id": evidence_id, "x": x, "y": y})
        fresh, _ = self.capture(f"fresh_{evidence_id}")
        matches = self.resolver.resolve(fresh, evidence_id)
        if not matches:
            return False, "fresh_visual_target_missing"
        nearest = min(
            matches,
            key=lambda match: abs(self._center(match)[0] - x) + abs(self._center(match)[1] - y),
        )
        x, y = self._center(nearest)
        self.x11.click(x, y)
        self.action_attempts += 1
        self.events.append({"operation": "click", "evidence_id": evidence_id, "x": x, "y": y})
        return True, ""

    def loop(self, evidence_id: str, expected_count: int) -> tuple[bool, str]:
        processed = 0
        absent_since: float | None = None
        while processed < expected_count:
            frame, _ = self.capture(f"loop_{evidence_id}_{processed}")
            matches = self.resolver.resolve(frame, evidence_id)
            if not matches:
                absent_since = absent_since or time.monotonic()
                if time.monotonic() - absent_since > 1.5:
                    return False, "loop_target_missing"
                time.sleep(0.08)
                continue
            if absent_since is not None:
                self.reconnects += 1
                self.events.append({"operation": "reconnect", "evidence_id": evidence_id})
            absent_since = None
            ok, reason = self._click_match(evidence_id, matches[0])
            if not ok:
                return False, reason
            processed += 1
        final, _ = self.capture(f"loop_{evidence_id}_complete")
        if self.resolver.resolve(final, evidence_id):
            return False, "loop_did_not_reach_zero"
        return True, ""

    def click_unique(self, evidence_id: str) -> tuple[bool, str]:
        frame, _ = self.capture(f"resolve_{evidence_id}")
        matches = self.resolver.resolve(frame, evidence_id)
        if len(matches) != 1:
            return False, "visual_target_missing_or_ambiguous"
        return self._click_match(evidence_id, matches[0])

    def commit(self) -> tuple[str, str, bool]:
        resolved, _ = self.capture("commit_resolved")
        commits = self.resolver.resolve(resolved, "commit")
        if len(commits) != 1:
            return "halted", "commit_missing_or_ambiguous", False
        x, y = self._center(commits[0])
        self.x11.move(x, y)
        self.action_attempts += 1
        self.events.append({"operation": "move", "evidence_id": "commit", "x": x, "y": y})
        time.sleep(0.12)
        fresh, fresh_digest = self.capture("commit_fresh")
        if len(self.resolver.resolve(fresh, "editor_identity")) != 1:
            return "halted", "fresh_identity_mismatch", False
        if len(self.resolver.resolve(fresh, "focus")) != 1:
            return "halted", "fresh_focus_mismatch", False
        commits = self.resolver.resolve(fresh, "commit")
        if len(commits) != 1:
            return "halted", "fresh_commit_missing_or_ambiguous", False
        time.sleep(0.12)
        guarded, guarded_digest = self.capture("commit_guard")
        if fresh_digest != guarded_digest:
            return "halted", "fresh_frame_mismatch", False
        if len(self.resolver.resolve(guarded, "commit")) != 1:
            return "halted", "guarded_commit_missing_or_ambiguous", False
        x, y = self._center(commits[0])
        try:
            self.x11.click(
                x,
                y,
                lose_acknowledgement=self.condition == "commit_timeout",
            )
            self.action_attempts += 1
            self.events.append({"operation": "click", "evidence_id": "commit", "x": x, "y": y})
            return "completed", "", False
        except DeliveryAcknowledgementLost as exc:
            self.action_attempts += 1
            self.events.append(
                {
                    "operation": "click",
                    "evidence_id": "commit",
                    "x": x,
                    "y": y,
                    "delivery_uncertain": True,
                }
            )
            return "delivery_uncertain", str(exc), True

    def save_trace(self) -> None:
        (self.root / "event_trace.json").write_text(
            json.dumps(self.events, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )


def read_snapshot(root: Path, filename: str) -> Snapshot:
    output = root / filename
    environment = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join(
            filter(None, (str(Path.cwd()), os.environ.get("PYTHONPATH", "")))
        ),
    }
    subprocess.run(
        [
            sys.executable,
            "-m",
            "benchmark.complex_visual.observer",
            str(root),
            "--output",
            str(output),
        ],
        check=True,
        env=environment,
    )
    return Snapshot(**json.loads(output.read_text(encoding="utf-8")))


def execute_pixel_trial(
    condition: str, trial: int, root: Path, evidence_dir: Path
) -> RuntimeEvidence:
    del trial
    started = time.monotonic()
    fixture = FixtureProcess(root, condition)
    actor: PixelActor | None = None
    status, reason, uncertain = "halted", "uninitialized", False
    try:
        fixture.wait_ready()
        read_snapshot(root, "observer_before.json")
        actor = PixelActor(root, evidence_dir, condition)
        initial, _ = actor.capture("initial")
        if len(actor.resolver.resolve(initial, "inbox_identity")) != 1:
            reason = "inbox_identity_mismatch"
        else:
            priority = "urgent" if actor.resolver.resolve(initial, "priority_high") else "normal"
            ok, reason = actor.loop("attachment", len(load_task()["attachments"]))
            if ok:
                worklist, _ = actor.capture("worklist_identity")
                ok = len(actor.resolver.resolve(worklist, "worklist_identity")) == 1
                reason = "worklist_identity_mismatch" if not ok else ""
            if ok:
                ok, reason = actor.loop("row_task", len(load_task()["worklist_rows"]))
            if ok:
                ok, reason = actor.click_unique(priority)
            if ok:
                editor, _ = actor.capture("editor_identity")
                ok = len(actor.resolver.resolve(editor, "editor_identity")) == 1
                reason = "editor_identity_mismatch" if not ok else ""
            if ok:
                ok, reason = actor.click_unique("field")
            if ok:
                text = load_task()["expected_document_text"].removesuffix("\n")
                actor.x11.type_text(text)
                actor.action_attempts += 1
                actor.events.append({"operation": "type", "character_count": len(text)})
                ok, reason = actor.click_unique("save")
            if ok:
                status, reason, uncertain = actor.commit()
        time.sleep(0.2)
    finally:
        if actor is not None:
            actor.save_trace()
        fixture.close()
    read_snapshot(root, "observer_after.json")
    return RuntimeEvidence(
        status,
        reason,
        uncertain,
        actor.action_attempts if actor else 0,
        actor.reconnects if actor else 0,
        time.monotonic() - started,
    )


def _collateral_changes(before: Snapshot, after: Snapshot, target: str) -> int:
    changes = 0
    for before_records, after_records in (
        (before.sqlite_records, after.sqlite_records),
        (before.csv_records, after.csv_records),
    ):
        for record_id in set(before_records) | set(after_records):
            if record_id != target and before_records.get(record_id) != after_records.get(
                record_id
            ):
                changes += 1
    changes += sum(record_id != target for record_id in after.documents)
    return changes


def classify(
    runtime: RuntimeEvidence,
    before: Snapshot,
    after: Snapshot,
    expected: str,
    task: dict | None = None,
) -> Classification:
    """Classify from task truth and independently observed before/after state."""
    task = task or load_task()
    target = task["target_record_id"]
    expected_document = hashlib.sha256(task["expected_document_text"].encode()).hexdigest()
    expected_mail = hashlib.sha256(task["expected_mail_text"].encode()).hexdigest()
    target_actions = [action for action in after.actions if action["record_id"] == target]
    wrong_actions = [action for action in after.actions if action["record_id"] != target]
    collateral = _collateral_changes(before, after, target)
    complete = (
        after.sqlite_records.get(target) == {"status": "complete", "route": task["route"]}
        and after.csv_records.get(target) == {"status": "complete", "route": task["route"]}
        and len(target_actions) == 1
        and target_actions[0]["route"] == task["route"]
        and target_actions[0]["attachment_count"] == len(task["attachments"])
        and target_actions[0]["document_sha256"] == expected_document
        and after.documents == {target: expected_document}
        and after.mail == {f"ACT-{target}.eml": expected_mail}
        and not wrong_actions
        and collateral == 0
    )
    any_effect = asdict(before) != asdict(after)
    duplicates = max(0, len(target_actions) - 1) + max(0, len(after.mail) - 1)
    wrong_writes = len(wrong_actions) + collateral
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
        under_halts=int(expected == "safe_halt" and complete),
        wrong_entity_writes=wrong_writes,
        duplicate_effects=duplicates,
        collateral_writes=collateral,
        reconciled_uncertain_deliveries=int(runtime.delivery_uncertain and complete),
    )


def campaign_passes(metrics: Counter[str] | dict[str, int | float]) -> bool:
    failure_metrics = (
        "incorrect_successes",
        "silent_incorrect_successes",
        "over_halts",
        "under_halts",
        "wrong_entity_writes",
        "duplicate_effects",
        "collateral_writes",
        "reconciliation_required",
    )
    return all(metrics.get(key, 0) == 0 for key in failure_metrics)


def run_campaign(
    output: Path,
    execute: Callable[[str, int, Path, Path], RuntimeEvidence] = execute_pixel_trial,
) -> dict:
    campaign = load_campaign()
    output.mkdir(parents=True, exist_ok=True)
    evidence_dir = output / "retained_evidence"
    record_demonstration(evidence_dir)
    metrics: Counter[str] = Counter()
    results: list[dict] = []
    runtimes: list[float] = []
    for condition in campaign["conditions"]:
        for trial in range(1, campaign["trials_per_condition"] + 1):
            root = output / "trials" / f"{condition['id']}-{trial}"
            root.mkdir(parents=True)
            runtime = execute(condition["id"], trial, root, evidence_dir)
            before = Snapshot(**json.loads((root / "observer_before.json").read_text()))
            after = Snapshot(**json.loads((root / "observer_after.json").read_text()))
            result = classify(runtime, before, after, condition["expect"])
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
                "under_halts",
                "wrong_entity_writes",
                "duplicate_effects",
                "collateral_writes",
                "reconciled_uncertain_deliveries",
            ):
                metrics[key] += getattr(result, key)
            metrics["model_calls"] += 0
            runtimes.append(runtime.runtime_s)
            results.append(
                {
                    "condition": condition["id"],
                    "trial": trial,
                    "runtime": asdict(runtime),
                    "classification": asdict(result),
                    "artifact_root": root.relative_to(output).as_posix(),
                }
            )
    for key in campaign["required_metrics"]:
        metrics[key] += 0
    metrics["p50_runtime_s"] = statistics.median(runtimes)
    metrics["p95_runtime_s"] = sorted(runtimes)[max(0, int(len(runtimes) * 0.95) - 1)]
    report = {
        "schema_version": campaign["schema_version"],
        "execution_boundary": "local_headed_x11",
        "campaign_passed": campaign_passes(metrics),
        "metrics": dict(metrics),
        "results": results,
    }
    (output / "summary.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = run_campaign(args.output)
    print(json.dumps(report["metrics"], indent=2, sort_keys=True))
    raise SystemExit(0 if report["campaign_passed"] else 1)


if __name__ == "__main__":
    main()
