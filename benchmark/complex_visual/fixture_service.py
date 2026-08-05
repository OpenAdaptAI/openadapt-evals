"""No-DOM pixel fixture for the complex visual workflow campaign.

The service renders three application windows into PNG frames.  Its protocol
accepts only screenshots and pointer or keyboard input.  It does not expose a
DOM, accessibility tree, control name, or application state to the actor.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sqlite3
import sys
from dataclasses import dataclass, field
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw

WIDTH, HEIGHT = 800, 500
CONTROL_SIZE = (140, 28)
DRIFT_CONTROL_SIZE = (126, 25)

COLORS = {
    "background": (235, 239, 244),
    "panel": (255, 255, 255),
    "title": (32, 43, 61),
    "tab_inbox": (64, 111, 190),
    "tab_worklist": (65, 145, 104),
    "tab_editor": (139, 92, 190),
    "attachment": (39, 133, 170),
    "row_task": (205, 117, 31),
    "urgent": (192, 57, 43),
    "normal": (48, 120, 185),
    "field": (222, 228, 235),
    "save": (103, 82, 164),
    "commit": (27, 145, 85),
    "target_entity": (17, 118, 74),
    "wrong_entity": (188, 58, 52),
    "priority_high": (239, 139, 42),
    "priority_normal": (73, 132, 187),
    "pointer": (10, 10, 10),
}

DRIFT_COLORS = {
    key: tuple(
        min(255, channel + (17 if index % 2 == 0 else -13)) for index, channel in enumerate(value)
    )
    for key, value in COLORS.items()
}


@dataclass
class Fixture:
    root: Path
    condition: str
    active_window: str = "inbox"
    pointer: tuple[int, int] = (5, 5)
    connected: bool = True
    session_generation: int = 1
    attachments_done: set[int] = field(default_factory=set)
    rows_done: set[int] = field(default_factory=set)
    route: str | None = None
    field_focused: bool = False
    typed_text: str = ""
    draft_saved: bool = False
    editor_ready_captures: int = 0
    pending_focus_theft: bool = False
    pending_stale_frame: bool = False
    committed: bool = False

    def __post_init__(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        self._initialize_stores()

    @property
    def palette(self) -> dict[str, tuple[int, int, int]]:
        return DRIFT_COLORS if self.condition == "display_drift" else COLORS

    @property
    def scale(self) -> float:
        return 0.9 if self.condition == "display_drift" else 1.0

    def box(self, x: int, y: int, width: int, height: int) -> tuple[int, int, int, int]:
        scale = self.scale
        left, top = round(x * scale), round(y * scale)
        return (left, top, left + round(width * scale), top + round(height * scale))

    def _initialize_stores(self) -> None:
        with sqlite3.connect(self.root / "effects.sqlite") as conn:
            conn.execute("create table records (record_id text primary key, status text)")
            conn.execute(
                "create table actions (action_id text, record_id text, route text, attachment_count integer, document_sha256 text)"
            )
            conn.executemany(
                "insert into records values (?, ?)",
                (("REC-001", "pending"), ("REC-999", "pending")),
            )
        with (self.root / "worklist.csv").open("w", newline="", encoding="utf-8") as stream:
            csv.writer(stream).writerows(
                (
                    ("record_id", "status", "route"),
                    ("REC-001", "pending", ""),
                    ("REC-999", "pending", ""),
                )
            )
        (self.root / "maildir").mkdir()
        (self.root / "documents").mkdir()

    def _audit(self, operation: str, **details: object) -> None:
        event = {"operation": operation, "active_window": self.active_window, **details}
        with (self.root / "interaction.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, sort_keys=True) + "\n")

    def _draw_button(
        self, draw: ImageDraw.ImageDraw, role: str, box: tuple[int, int, int, int], label: str
    ) -> None:
        draw.rectangle(box, fill=self.palette[role])
        draw.text((box[0] + 6, box[1] + 6), label, fill=(255, 255, 255))

    def render(self, *, count_capture: bool = False) -> Image.Image:
        if count_capture and self.active_window == "editor" and self.draft_saved:
            self.editor_ready_captures += 1
        image = Image.new("RGB", (WIDTH, HEIGHT), self.palette["background"])
        draw = ImageDraw.Draw(image)
        draw.rectangle(
            self.box(20, 15, 760, 460),
            fill=self.palette["panel"],
            outline=self.palette["title"],
            width=2,
        )
        for role, label, x, window in (
            ("tab_inbox", "Inbox", 40, "inbox"),
            ("tab_worklist", "Worklist", 205, "worklist"),
            ("tab_editor", "Document editor", 370, "editor"),
        ):
            box = self.box(x, 35, *CONTROL_SIZE)
            self._draw_button(draw, role, box, label)
            if self.active_window == window:
                draw.rectangle(box, outline=(255, 255, 255), width=3)
        if self.active_window == "inbox":
            self._render_inbox(draw)
        elif self.active_window == "worklist":
            self._render_worklist(draw)
        else:
            self._render_editor(draw)
        px, py = self.pointer
        draw.polygon(
            ((px, py), (px + 9, py + 18), (px + 4, py + 13), (px, py + 18)),
            fill=self.palette["pointer"],
        )
        return image

    def _render_inbox(self, draw: ImageDraw.ImageDraw) -> None:
        draw.text((50, 105), "Synthetic request REC-001", fill=self.palette["title"])
        draw.rectangle(self.box(50, 130, 24, 18), fill=self.palette["target_entity"])
        draw.rectangle(self.box(100, 130, 24, 18), fill=self.palette["priority_high"])
        for index, x in enumerate((80, 260)):
            if index not in self.attachments_done:
                self._draw_button(
                    draw, "attachment", self.box(x, 205, *CONTROL_SIZE), f"Attachment {index + 1}"
                )

    def _render_worklist(self, draw: ImageDraw.ImageDraw) -> None:
        draw.text((50, 105), "Synthetic CSV worklist", fill=self.palette["title"])
        draw.rectangle(self.box(50, 135, 24, 18), fill=self.palette["target_entity"])
        for index, y in enumerate((185, 245)):
            if index not in self.rows_done:
                self._draw_button(
                    draw, "row_task", self.box(90, y, *CONTROL_SIZE), f"Row {index + 1}"
                )
        if len(self.rows_done) == 2:
            self._draw_button(draw, "urgent", self.box(430, 185, *CONTROL_SIZE), "Route urgent")
            self._draw_button(draw, "normal", self.box(430, 245, *CONTROL_SIZE), "Route normal")

    def _render_editor(self, draw: ImageDraw.ImageDraw) -> None:
        draw.text((50, 105), "Synthetic document", fill=self.palette["title"])
        identity_role = (
            "wrong_entity"
            if self.condition == "wrong_entity" and self.editor_ready_captures >= 2
            else "target_entity"
        )
        draw.rectangle(self.box(50, 135, 24, 18), fill=self.palette[identity_role])
        field_box = self.box(70, 185, 480, 90)
        draw.rectangle(field_box, fill=self.palette["field"], outline=self.palette["title"])
        draw.text(
            (field_box[0] + 8, field_box[1] + 8), self.typed_text[:58], fill=self.palette["title"]
        )
        if not self.draft_saved:
            self._draw_button(draw, "save", self.box(80, 325, *CONTROL_SIZE), "Save draft")
            return
        commit_box = self.box(430, 325, *CONTROL_SIZE)
        fault_visible = self.editor_ready_captures >= 2
        if self.condition == "partial_render" and fault_visible:
            partial = (
                commit_box[0],
                commit_box[1],
                commit_box[2],
                commit_box[1] + max(1, (commit_box[3] - commit_box[1]) // 2),
            )
            self._draw_button(draw, "commit", partial, "Commit")
        else:
            self._draw_button(draw, "commit", commit_box, "Commit")
        if self.condition == "ambiguity" and fault_visible:
            self._draw_button(draw, "commit", self.box(430, 380, *CONTROL_SIZE), "Commit")

    def capture(self) -> dict:
        if not self.connected:
            self._audit("capture", accepted=False, reason="session_disconnected")
            return {"accepted": False, "reason": "session_disconnected"}
        image = self.render(count_capture=True)
        if self.active_window == "editor" and self.draft_saved and self.editor_ready_captures >= 2:
            self.pending_focus_theft = self.condition == "focus_theft"
            self.pending_stale_frame = self.condition == "stale_frame"
        stream = BytesIO()
        image.save(stream, format="PNG")
        payload = stream.getvalue()
        digest = hashlib.sha256(payload).hexdigest()
        self._audit("capture", accepted=True, frame_sha256=digest)
        import base64

        return {
            "accepted": True,
            "png_base64": base64.b64encode(payload).decode("ascii"),
            "frame_sha256": digest,
            "session_generation": self.session_generation,
        }

    def _current_digest(self) -> str:
        stream = BytesIO()
        self.render().save(stream, format="PNG")
        return hashlib.sha256(stream.getvalue()).hexdigest()

    @staticmethod
    def _inside(x: int, y: int, box: tuple[int, int, int, int]) -> bool:
        return box[0] <= x < box[2] and box[1] <= y < box[3]

    def move(self, x: int, y: int, expected_frame_sha256: str) -> dict:
        if not self.connected or expected_frame_sha256 != self._current_digest():
            self._audit("move", accepted=False, x=x, y=y, reason="stale_frame")
            return {"accepted": False, "reason": "stale_frame"}
        self.pointer = (x, y)
        self._audit("move", accepted=True, x=x, y=y)
        return {"accepted": True}

    def click(self, x: int, y: int, expected_frame_sha256: str) -> dict:
        if self.pending_focus_theft:
            self.active_window = "inbox"
            self.pending_focus_theft = False
        if self.pending_stale_frame:
            self.pointer = (self.pointer[0] + 1, self.pointer[1])
            self.pending_stale_frame = False
        if not self.connected or expected_frame_sha256 != self._current_digest():
            self._audit("click", accepted=False, x=x, y=y, reason="fresh_frame_mismatch")
            return {"accepted": False, "reason": "fresh_frame_mismatch"}
        for role, tab_x, window in (
            ("tab_inbox", 40, "inbox"),
            ("tab_worklist", 205, "worklist"),
            ("tab_editor", 370, "editor"),
        ):
            if self._inside(x, y, self.box(tab_x, 35, *CONTROL_SIZE)):
                del role
                self.active_window = window
                self._audit("click", accepted=True, x=x, y=y, effect="window_switch")
                return {"accepted": True}
        response = self._click_active(x, y)
        self._audit("click", x=x, y=y, **response)
        return response

    def _click_active(self, x: int, y: int) -> dict:
        if self.active_window == "inbox":
            for index, control_x in enumerate((80, 260)):
                if index not in self.attachments_done and self._inside(
                    x, y, self.box(control_x, 205, *CONTROL_SIZE)
                ):
                    self.attachments_done.add(index)
                    return {"accepted": True, "effect": "attachment_processed"}
        elif self.active_window == "worklist":
            for index, control_y in enumerate((185, 245)):
                if index not in self.rows_done and self._inside(
                    x, y, self.box(90, control_y, *CONTROL_SIZE)
                ):
                    self.rows_done.add(index)
                    if self.condition == "reconnect" and len(self.rows_done) == 1:
                        self.connected = False
                    return {"accepted": True, "effect": "row_processed"}
            if len(self.rows_done) == 2:
                for route, role, route_y in (("urgent", "urgent", 185), ("normal", "normal", 245)):
                    if self._inside(x, y, self.box(430, route_y, *CONTROL_SIZE)):
                        del role
                        self.route = route
                        return {"accepted": True, "effect": "route_selected"}
        else:
            if self._inside(x, y, self.box(70, 185, 480, 90)):
                self.field_focused = True
                return {"accepted": True, "effect": "field_focused"}
            if not self.draft_saved and self._inside(x, y, self.box(80, 325, *CONTROL_SIZE)):
                if self.typed_text:
                    self.draft_saved = True
                    return {"accepted": True, "effect": "draft_saved"}
            if self.draft_saved and self._inside(x, y, self.box(430, 325, *CONTROL_SIZE)):
                self._commit()
                if self.condition == "commit_timeout":
                    return {
                        "accepted": False,
                        "reason": "acknowledgement_lost",
                        "delivery_uncertain": True,
                    }
                return {"accepted": True, "effect": "committed"}
        return {"accepted": False, "reason": "no_control_at_point"}

    def type_text(self, text: str, expected_frame_sha256: str) -> dict:
        if (
            not self.connected
            or expected_frame_sha256 != self._current_digest()
            or not self.field_focused
        ):
            self._audit("type", accepted=False, reason="input_guard_failed")
            return {"accepted": False, "reason": "input_guard_failed"}
        self.typed_text += text
        self._audit("type", accepted=True, character_count=len(text))
        return {"accepted": True}

    def reconnect(self) -> dict:
        self.connected = True
        self.session_generation += 1
        self._audit("reconnect", accepted=True, session_generation=self.session_generation)
        return {"accepted": True, "session_generation": self.session_generation}

    def _commit(self) -> None:
        if self.committed:
            return
        record_id = "REC-001"
        document = self.root / "documents" / f"{record_id}.txt"
        document.write_text(self.typed_text + "\n", encoding="utf-8")
        digest = hashlib.sha256(document.read_bytes()).hexdigest()
        with sqlite3.connect(self.root / "effects.sqlite") as conn:
            conn.execute("update records set status = 'complete' where record_id = ?", (record_id,))
            conn.execute(
                "insert into actions values (?, ?, ?, ?, ?)",
                ("ACT-001", record_id, self.route, len(self.attachments_done), digest),
            )
        rows = [
            ("record_id", "status", "route"),
            ("REC-001", "complete", self.route or ""),
            ("REC-999", "pending", ""),
        ]
        with (self.root / "worklist.csv").open("w", newline="", encoding="utf-8") as stream:
            csv.writer(stream).writerows(rows)
        (self.root / "maildir" / "ACT-001.eml").write_text(
            f"Record: {record_id}\nRoute: {self.route}\n", encoding="utf-8"
        )
        self.committed = True


def serve(root: Path, condition: str) -> None:
    fixture = Fixture(root, condition)
    for line in sys.stdin:
        request = json.loads(line)
        operation = request["operation"]
        if operation == "capture":
            response = fixture.capture()
        elif operation == "move":
            response = fixture.move(request["x"], request["y"], request["expected_frame_sha256"])
        elif operation == "click":
            response = fixture.click(request["x"], request["y"], request["expected_frame_sha256"])
        elif operation == "type":
            response = fixture.type_text(request["text"], request["expected_frame_sha256"])
        elif operation == "reconnect":
            response = fixture.reconnect()
        elif operation == "close":
            response = {"accepted": True}
            print(json.dumps(response), flush=True)
            break
        else:
            response = {"accepted": False, "reason": "unknown_operation"}
        print(json.dumps(response), flush=True)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--condition", required=True)
    args = parser.parse_args()
    serve(args.root, args.condition)


if __name__ == "__main__":
    main()
