"""Read-only, independently initialized observer for benchmark effects."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class Observation:
    target_action_count: int
    wrong_entity_action_count: int
    target_status: str
    wrong_entity_status: str
    target_csv_status: str
    wrong_entity_csv_status: str
    target_route: str
    target_csv_route: str
    attachment_count: int
    action_document_sha256_ok: bool
    document_ok: bool
    mail_count: int
    mail_ok: bool
    collateral_write_count: int
    persisted_effect_count: int


def observe(root: Path) -> Observation:
    """Open each store afresh and compare it with the immutable task truth."""
    truth = json.loads((root / "ground_truth.json").read_text(encoding="utf-8"))
    target, wrong = truth["target_record_id"], truth["other_record_id"]
    with sqlite3.connect(f"file:{root / 'effects.sqlite'}?mode=ro", uri=True) as conn:
        actions = conn.execute(
            "select record_id, route, attachment_count, document_sha256 from actions"
        ).fetchall()
        records = dict(conn.execute("select record_id, status from records").fetchall())
    with (root / "worklist.csv").open(newline="", encoding="utf-8") as stream:
        csv_rows = {row["record_id"]: row for row in csv.DictReader(stream)}
    documents = list((root / "documents").glob("*.txt"))
    target_document = root / "documents" / f"{target}.txt"
    expected_document_sha256 = hashlib.sha256(
        truth["expected_document_text"].encode("utf-8")
    ).hexdigest()
    document_ok = (
        target_document.is_file()
        and hashlib.sha256(target_document.read_bytes()).hexdigest() == expected_document_sha256
    )
    messages = list((root / "maildir").glob("*.eml"))
    target_actions = [row for row in actions if row[0] == target]
    wrong_actions = [row for row in actions if row[0] != target]
    selected = target_actions[0] if target_actions else (None, "", 0, "")
    mail_ok = (
        len(messages) == 1
        and messages[0].read_text(encoding="utf-8") == truth["expected_mail_text"]
    )
    collateral = sum(
        record_id != wrong or status != "pending"
        for record_id, status in records.items()
        if record_id != target
    )
    collateral += sum(
        record_id != wrong or row.get("status") != "pending"
        for record_id, row in csv_rows.items()
        if record_id != target
    )
    collateral += sum(path.stem != target for path in documents)
    changed_records = sum(status != "pending" for status in records.values())
    changed_csv_rows = sum(row.get("status") != "pending" for row in csv_rows.values())
    persisted_effect_count = len(actions) + len(messages) + len(documents)
    persisted_effect_count += changed_records + changed_csv_rows
    return Observation(
        target_action_count=len(target_actions),
        wrong_entity_action_count=len(wrong_actions),
        target_status=records.get(target, "missing"),
        wrong_entity_status=records.get(wrong, "missing"),
        target_csv_status=csv_rows.get(target, {}).get("status", "missing"),
        wrong_entity_csv_status=csv_rows.get(wrong, {}).get("status", "missing"),
        target_route=selected[1] or "",
        target_csv_route=csv_rows.get(target, {}).get("route", "missing"),
        attachment_count=int(selected[2] or 0),
        action_document_sha256_ok=selected[3] == expected_document_sha256,
        document_ok=document_ok,
        mail_count=len(messages),
        mail_ok=mail_ok,
        collateral_write_count=collateral,
        persisted_effect_count=persisted_effect_count,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    print(json.dumps(asdict(observe(args.root)), sort_keys=True))


if __name__ == "__main__":
    main()
