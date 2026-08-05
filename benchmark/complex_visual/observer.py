"""Independent read-only store observer for the complex visual campaign."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class Snapshot:
    sqlite_records: dict[str, dict[str, str]]
    csv_records: dict[str, dict[str, str]]
    actions: list[dict[str, str | int]]
    documents: dict[str, str]
    mail: dict[str, str]


def observe(root: Path) -> Snapshot:
    """Open every store through new read-only handles and return exact state."""
    with sqlite3.connect(f"file:{root / 'effects.sqlite'}?mode=ro", uri=True) as conn:
        records = {
            row[0]: {"status": row[1], "route": row[2]}
            for row in conn.execute("select record_id, status, route from records")
        }
        actions = [
            {
                "action_id": row[0],
                "record_id": row[1],
                "route": row[2],
                "attachment_count": row[3],
                "document_sha256": row[4],
            }
            for row in conn.execute(
                "select action_id, record_id, route, attachment_count, document_sha256 from actions"
            )
        ]
    with (root / "worklist.csv").open(newline="", encoding="utf-8") as stream:
        csv_records = {
            row["record_id"]: {"status": row["status"], "route": row["route"]}
            for row in csv.DictReader(stream)
        }
    documents = {
        path.stem: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted((root / "documents").glob("*.txt"))
    }
    mail = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted((root / "maildir").glob("*.eml"))
    }
    return Snapshot(records, csv_records, actions, documents, mail)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    payload = json.dumps(asdict(observe(args.root)), indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")


if __name__ == "__main__":
    main()
