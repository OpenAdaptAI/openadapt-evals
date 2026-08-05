"""Three-window headed Tk fixture for the complex visual campaign."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sqlite3
import tkinter as tk
from pathlib import Path

WINDOWS = {
    "inbox": (20, 30),
    "worklist": (440, 30),
    "editor": (860, 30),
}
WINDOW_SIZE = (390, 560)

GLYPHS = {
    "identity": ("1000001", "0100010", "0010100", "0001000", "0010100", "0100010", "1000001"),
    "wrong_identity": ("1111111", "1000001", "1011101", "1010101", "1011101", "1000001", "1111111"),
    "priority_high": ("0001000", "0011100", "0111110", "1111111", "0011100", "0011100", "0011100"),
    "attachment": ("1111000", "1000100", "1011110", "1010010", "1011110", "1000000", "1111110"),
    "row_task": ("1111110", "1000010", "1011010", "1011010", "1011010", "1000010", "1111110"),
    "urgent": ("1000001", "1000001", "1000001", "1000001", "1000001", "0100010", "0011100"),
    "normal": ("1000001", "1100001", "1010001", "1001001", "1000101", "1000011", "1000001"),
    "field": ("1111111", "1000001", "1000001", "1000001", "1000001", "1000001", "1111111"),
    "save": ("1111111", "1000001", "1011101", "1010101", "1011101", "1000001", "1111111"),
    "commit": ("0011100", "0100010", "1000001", "1000000", "1000001", "0100010", "0011100"),
    "focus": ("1111111", "1000000", "1011110", "1010000", "1010000", "1000000", "1000000"),
}


class Fixture:
    def __init__(self, root_path: Path, condition: str, ready_path: Path) -> None:
        self.root_path = root_path
        self.condition = condition
        self.ready_path = ready_path
        self.scale = 1.08 if condition == "display_drift" else 1.0
        self.glyph_unit = 3 if condition == "display_drift" else 2
        self.attachments_done: set[int] = set()
        self.rows_done: set[int] = set()
        self.route = ""
        self.document_text = ""
        self.draft_saved = False
        self.active_record = "REC-001"
        self.focused_window = "inbox"
        self.commit_fault_armed = False
        self.heartbeat = False
        self.regions: dict[str, list[list[int]]] = {}
        self.centers: dict[str, list[list[int]]] = {}
        self.root_path.mkdir(parents=True, exist_ok=True)
        self._initialize_stores()
        self.inbox = tk.Tk(className="OpenAdaptInbox")
        self.worklist = tk.Toplevel(self.inbox, class_="OpenAdaptWorklist")
        self.editor = tk.Toplevel(self.inbox, class_="OpenAdaptEditor")
        self.windows = {"inbox": self.inbox, "worklist": self.worklist, "editor": self.editor}
        self.canvases: dict[str, tk.Canvas] = {}
        for name, window in self.windows.items():
            x, y = WINDOWS[name]
            window.overrideredirect(True)
            window.geometry(f"{WINDOW_SIZE[0]}x{WINDOW_SIZE[1]}+{x}+{y}")
            canvas = tk.Canvas(
                window, width=WINDOW_SIZE[0], height=WINDOW_SIZE[1], highlightthickness=0
            )
            canvas.pack(fill="both", expand=True)
            canvas.bind("<FocusIn>", lambda event, selected=name: self._claim_focus(selected))
            self.canvases[name] = canvas
        self.canvases["editor"].bind("<Key>", self._on_key)
        self._draw_all()
        self.inbox.after(200, self._publish_ready)

    def _initialize_stores(self) -> None:
        with sqlite3.connect(self.root_path / "effects.sqlite") as conn:
            conn.execute(
                "create table records (record_id text primary key, status text, route text)"
            )
            conn.execute(
                "create table actions (action_id text, record_id text, route text, attachment_count integer, document_sha256 text)"
            )
            conn.executemany(
                "insert into records values (?, ?, ?)",
                (("REC-001", "pending", ""), ("REC-999", "pending", "")),
            )
        with (self.root_path / "worklist.csv").open("w", newline="", encoding="utf-8") as stream:
            csv.writer(stream).writerows(
                (
                    ("record_id", "status", "route"),
                    ("REC-001", "pending", ""),
                    ("REC-999", "pending", ""),
                )
            )
        (self.root_path / "maildir").mkdir()
        (self.root_path / "documents").mkdir()

    def _event(self, event: str, **details: object) -> None:
        with (self.root_path / "fixture_events.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"event": event, **details}, sort_keys=True) + "\n")

    def _publish_ready(self) -> None:
        payload = {
            "regions": self.regions,
            "centers": self.centers,
            "windows": {
                name: [x, y, x + WINDOW_SIZE[0], y + WINDOW_SIZE[1]]
                for name, (x, y) in WINDOWS.items()
            },
        }
        self.ready_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )

    def _claim_focus(self, name: str) -> None:
        if self.focused_window != name:
            self.focused_window = name
            self._event("focus", window=name)
            self._draw_all()

    def _glyph(
        self, canvas: tk.Canvas, name: str, x: int, y: int, tag: str, *, partial: bool = False
    ) -> tuple[int, int, int, int]:
        pattern = GLYPHS[name]
        unit = self.glyph_unit
        rows = len(pattern) // 2 if partial else len(pattern)
        for row, bits in enumerate(pattern[:rows]):
            for column, bit in enumerate(bits):
                if bit == "1":
                    canvas.create_rectangle(
                        x + column * unit,
                        y + row * unit,
                        x + (column + 1) * unit - 1,
                        y + (row + 1) * unit - 1,
                        fill="#111111",
                        outline="",
                        tags=(tag,),
                    )
        return (x - 2, y - 2, x + len(pattern[0]) * unit + 2, y + len(pattern) * unit + 2)

    def _control(
        self,
        window: str,
        evidence_id: str,
        x: int,
        y: int,
        label: str,
        callback,
        *,
        glyph: str | None = None,
        partial: bool = False,
    ) -> None:
        canvas = self.canvases[window]
        x, y = round(x * self.scale), round(y * self.scale)
        width, height = round(150 * self.scale), round(42 * self.scale)
        tag = f"control:{evidence_id}:{len(self.centers.get(evidence_id, []))}"
        canvas.create_rectangle(
            x, y, x + width, y + height, fill="#e8edf2", outline="#334155", width=2, tags=(tag,)
        )
        glyph_name = glyph or evidence_id
        region = self._glyph(canvas, glyph_name, x + 10, y + 12, tag, partial=partial)
        canvas.create_text(
            x + 42, y + height // 2, text=label, anchor="w", fill="#111111", tags=(tag,)
        )
        canvas.tag_bind(
            tag,
            "<Button-1>",
            lambda event, selected=window, action=callback: self._activate(selected, action),
        )
        if evidence_id == "commit":
            canvas.tag_bind(tag, "<Enter>", self._arm_commit_fault)
        wx, wy = WINDOWS[window]
        absolute = [region[0] + wx, region[1] + wy, region[2] + wx, region[3] + wy]
        self.regions.setdefault(evidence_id, []).append(absolute)
        self.centers.setdefault(evidence_id, []).append([wx + x + width // 2, wy + y + height // 2])

    def _marker(
        self,
        window: str,
        evidence_id: str,
        x: int,
        y: int,
        *,
        glyph: str | None = None,
        partial: bool = False,
    ) -> None:
        canvas = self.canvases[window]
        x, y = round(x * self.scale), round(y * self.scale)
        region = self._glyph(
            canvas, glyph or evidence_id, x, y, f"marker:{evidence_id}", partial=partial
        )
        wx, wy = WINDOWS[window]
        self.regions.setdefault(evidence_id, []).append(
            [region[0] + wx, region[1] + wy, region[2] + wx, region[3] + wy]
        )

    def _activate(self, window: str, callback) -> None:
        self.windows[window].focus_force()
        self.canvases[window].focus_set()
        self._claim_focus(window)
        callback()

    def _draw_all(self) -> None:
        self.regions, self.centers = {}, {}
        theme = "#d7dce2" if self.condition == "display_drift" else "#f8fafc"
        for name, canvas in self.canvases.items():
            canvas.delete("all")
            canvas.configure(background=theme)
            canvas.create_text(
                18,
                18,
                text={"inbox": "Inbox", "worklist": "Worklist", "editor": "Document editor"}[name],
                anchor="nw",
                font=("TkDefaultFont", 18, "bold"),
                fill="#111111",
            )
            canvas.create_rectangle(
                2,
                2,
                WINDOW_SIZE[0] - 3,
                WINDOW_SIZE[1] - 3,
                outline="#2563eb" if self.focused_window == name else "#94a3b8",
                width=4,
            )
        self._draw_inbox()
        self._draw_worklist()
        self._draw_editor()
        self._publish_ready()

    def _draw_inbox(self) -> None:
        canvas = self.canvases["inbox"]
        canvas.create_text(20, 70, text="Synthetic request REC-001", anchor="w", fill="#111111")
        self._marker("inbox", "inbox_identity", 24, 94, glyph="identity")
        self._marker("inbox", "priority_high", 72, 94)
        for index, y in enumerate((145, 210)):
            if index not in self.attachments_done:
                self._control(
                    "inbox",
                    "attachment",
                    35,
                    y,
                    f"Attachment {index + 1}",
                    lambda selected=index: self._attachment(selected),
                )

    def _draw_worklist(self) -> None:
        canvas = self.canvases["worklist"]
        canvas.create_text(20, 70, text="CSV worklist", anchor="w", fill="#111111")
        self._marker("worklist", "worklist_identity", 24, 94, glyph="identity")
        for index, y in enumerate((145, 210)):
            if index not in self.rows_done:
                self._control(
                    "worklist",
                    "row_task",
                    35,
                    y,
                    f"Worklist row {index + 1}",
                    lambda selected=index: self._row(selected),
                )
        if len(self.rows_done) == 2:
            self._control(
                "worklist", "urgent", 35, 300, "Route urgent", lambda: self._route("urgent")
            )
            self._control(
                "worklist", "normal", 200, 300, "Route normal", lambda: self._route("normal")
            )

    def _draw_editor(self) -> None:
        canvas = self.canvases["editor"]
        canvas.create_text(20, 70, text="Document for active record", anchor="w", fill="#111111")
        identity = "wrong_identity" if self.active_record != "REC-001" else "identity"
        self._marker("editor", "editor_identity", 24, 94, glyph=identity)
        if self.focused_window == "editor":
            self._marker("editor", "focus", 72, 94)
        self._control(
            "editor", "field", 30, 135, self.document_text[:26] or "Document body", self._field
        )
        if not self.draft_saved:
            self._control("editor", "save", 35, 240, "Save draft", self._save)
        else:
            partial = self.condition == "partial_render"
            self._control("editor", "commit", 35, 330, "Commit", self._commit, partial=partial)
            if self.condition == "ambiguity":
                self._control("editor", "commit", 200, 330, "Commit", self._commit)
        if self.heartbeat:
            canvas.create_rectangle(350, 100, 360, 110, fill="#dc2626", outline="")

    def _attachment(self, index: int) -> None:
        self.attachments_done.add(index)
        self._event("attachment_processed", index=index)
        self._draw_all()

    def _row(self, index: int) -> None:
        self.rows_done.add(index)
        self._event("row_processed", index=index)
        self._draw_all()
        if self.condition == "reconnect" and len(self.rows_done) == 1:
            self.worklist.withdraw()
            self._event("window_disconnected", window="worklist")
            self.inbox.after(350, self._restore_worklist)

    def _restore_worklist(self) -> None:
        self.worklist.deiconify()
        self.worklist.lift()
        self._event("window_reconnected", window="worklist")

    def _route(self, route: str) -> None:
        self.route = route
        self._event("route_selected", route=route)
        self._draw_all()

    def _field(self) -> None:
        self.canvases["editor"].focus_set()
        self._event("field_focused")

    def _on_key(self, event: tk.Event) -> None:
        if event.char and event.char.isprintable():
            self.document_text += event.char
            self._draw_all()

    def _save(self) -> None:
        if self.document_text:
            self.draft_saved = True
            self._event("draft_saved")
            self._draw_all()

    def _arm_commit_fault(self, event: tk.Event) -> None:
        del event
        if self.commit_fault_armed:
            return
        self.commit_fault_armed = True
        if self.condition == "wrong_entity":
            self.active_record = "REC-999"
            self.inbox.after(25, self._draw_all)
        elif self.condition == "focus_theft":
            self.inbox.after(25, self._steal_focus)
        elif self.condition == "stale_frame":
            self.inbox.after(25, self._pulse)

    def _steal_focus(self) -> None:
        self.inbox.focus_force()
        self.canvases["inbox"].focus_set()
        self._claim_focus("inbox")
        self._event("focus_stolen", window="inbox")

    def _pulse(self) -> None:
        self.heartbeat = not self.heartbeat
        self._draw_all()
        if self.commit_fault_armed:
            self.inbox.after(70, self._pulse)

    def _commit(self) -> None:
        record_id = self.active_record
        document = self.root_path / "documents" / f"{record_id}.txt"
        document.write_text(self.document_text + "\n", encoding="utf-8")
        digest = hashlib.sha256(document.read_bytes()).hexdigest()
        with sqlite3.connect(self.root_path / "effects.sqlite") as conn:
            conn.execute(
                "update records set status = 'complete', route = ? where record_id = ?",
                (self.route, record_id),
            )
            conn.execute(
                "insert into actions values (?, ?, ?, ?, ?)",
                (f"ACT-{record_id}", record_id, self.route, len(self.attachments_done), digest),
            )
        rows = [("record_id", "status", "route")]
        for current in ("REC-001", "REC-999"):
            rows.append(
                (
                    current,
                    "complete" if current == record_id else "pending",
                    self.route if current == record_id else "",
                )
            )
        with (self.root_path / "worklist.csv").open("w", newline="", encoding="utf-8") as stream:
            csv.writer(stream).writerows(rows)
        (self.root_path / "maildir" / f"ACT-{record_id}.eml").write_text(
            f"Record: {record_id}\nRoute: {self.route}\n", encoding="utf-8"
        )
        self._event("committed", record_id=record_id)

    def run(self) -> None:
        self.inbox.mainloop()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--condition", required=True)
    parser.add_argument("--ready", type=Path, required=True)
    args = parser.parse_args()
    Fixture(args.root, args.condition, args.ready).run()


if __name__ == "__main__":
    main()
