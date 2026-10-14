"""A small synthetic benchmark, built in, so the audit runs in seconds with
nothing to download.

It is not a model of any real benchmark's code. It exists to show every
outcome the audit reports: two verifiers check the values of new records
but never count them (so a repeated write passes), one adds the count, and
two tasks write in ways a repeat cannot change.

Tasks
-----
``split-bill``          request each friend's share; the verifier compares a
                        receiver-to-amount map, so a second identical request
                        is invisible to it.
``split-bill-counted``  the same task; the verifier also counts the requests.
``queue-songs``         queue two songs; the verifier compares the set of
                        queued songs, so a song queued twice is invisible.
``like-songs``          like two songs; liking twice is refused by the app.
``rename-profile``      change the display name; setting it twice is a no-op.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import Any, Callable, Sequence

from openadapt_evals.verifier_audit.adapters.base import Delivery, Reference, Run
from openadapt_evals.verifier_audit.operators import DEFAULT_POLICY, Call

TOKEN = "toy-access-token"
FRIENDS = ("ana@example.com", "ben@example.com", "chen@example.com")
SONGS = (3, 4, 7, 9)


def _start_state() -> dict[str, list[dict[str, Any]]]:
    return {
        "toy.PaymentRequest": [],
        "toy.Notification": [],
        "toy.QueueEntry": [],
        "toy.Like": [],
        "toy.Profile": [{"id": 1, "display_name": "Ada"}],
        "supervisor.Task": [{"id": 1, "status": None}],
    }


class ToyApp:
    """In-memory app with an HTTP-style API. Each instance is a fresh start state."""

    def __init__(self) -> None:
        self.tables = _start_state()
        self.start = copy.deepcopy(self.tables)

    def _insert(self, table: str, record: dict[str, Any]) -> None:
        rows = self.tables[table]
        record = {"id": len(rows) + 1, **record}
        rows.append(record)

    def call(self, call: Call) -> int:
        method = str(call.get("method", "get")).lower()
        url = str(call.get("url", ""))
        data = dict(call.get("data") or {})
        if url.endswith("/auth/token"):
            return 200
        if method == "get":
            return 200
        if url.startswith("/supervisor/complete_task"):
            self.tables["supervisor.Task"][0]["status"] = data.get("status")
            return 200
        if data.get("access_token") != TOKEN:
            return 401
        if method == "post" and url == "/toy/payment_requests":
            if data.get("user_email") not in FRIENDS:
                return 422
            self._insert(
                "toy.PaymentRequest",
                {"receiver": data["user_email"], "amount": data.get("amount")},
            )
            self._insert("toy.Notification", {"to": data["user_email"], "kind": "request"})
            return 200
        if method == "post" and url == "/toy/queue":
            if data.get("song_id") not in SONGS:
                return 404
            self._insert("toy.QueueEntry", {"song_id": data["song_id"]})
            return 200
        if method == "post" and url == "/toy/likes":
            if data.get("song_id") not in SONGS:
                return 404
            if any(r["song_id"] == data["song_id"] for r in self.tables["toy.Like"]):
                return 409
            self._insert("toy.Like", {"song_id": data["song_id"]})
            return 200
        if method == "patch" and url == "/toy/profile":
            self.tables["toy.Profile"][0]["display_name"] = data.get("display_name")
            return 200
        return 404

    def effect(self) -> dict[str, dict[str, list[Any]]]:
        effect: dict[str, dict[str, list[Any]]] = {}
        for table, rows in self.tables.items():
            before = {r["id"]: r for r in self.start[table]}
            after = {r["id"]: r for r in rows}
            added = [copy.deepcopy(after[i]) for i in sorted(after.keys() - before.keys())]
            removed = [copy.deepcopy(before[i]) for i in sorted(before.keys() - after.keys())]
            updated = [
                {"before": copy.deepcopy(before[i]), "after": copy.deepcopy(after[i])}
                for i in sorted(after.keys() & before.keys())
                if before[i] != after[i]
            ]
            if added or removed or updated:
                effect[table] = {"added": added, "removed": removed, "updated": updated}
        return effect

    def new(self, table: str) -> list[dict[str, Any]]:
        start_ids = {r["id"] for r in self.start[table]}
        return [r for r in self.tables[table] if r["id"] not in start_ids]


def _signin() -> Call:
    return {
        "method": "post",
        "url": "/toy/auth/token",
        "data": {"username": "ada", "password": "pw"},
    }


def _write(method: str, url: str, **data: Any) -> Call:
    return {"method": method, "url": url, "data": {"access_token": TOKEN, **data}}


def _done() -> Call:
    return {"method": "post", "url": "/supervisor/complete_task", "data": {"status": "success"}}


SHARES = {"ana@example.com": 12.5, "ben@example.com": 20.0, "chen@example.com": 7.5}


def _split_bill_calls() -> list[Call]:
    calls = [_signin(), {"method": "get", "url": "/toy/contacts", "data": {"access_token": TOKEN}}]
    calls += [
        _write("post", "/toy/payment_requests", user_email=email, amount=amount)
        for email, amount in SHARES.items()
    ]
    return calls + [_done()]


def _check_split_bill(app: ToyApp) -> bool:
    # Compares receiver -> amount. Two identical requests map to one entry.
    got = {r["receiver"]: r["amount"] for r in app.new("toy.PaymentRequest")}
    return got == SHARES


def _check_split_bill_counted(app: ToyApp) -> bool:
    return _check_split_bill(app) and len(app.new("toy.PaymentRequest")) == len(SHARES)


def _check_queue(app: ToyApp) -> bool:
    # Compares the set of queued songs. A song queued twice is one element.
    return {r["song_id"] for r in app.new("toy.QueueEntry")} == {7, 9}


def _check_likes(app: ToyApp) -> bool:
    new = app.new("toy.Like")
    return {r["song_id"] for r in new} == {3, 4} and len(new) == 2


def _check_rename(app: ToyApp) -> bool:
    return (
        app.tables["toy.Profile"][0]["display_name"] == "Ada Lovelace"
        and not app.new("toy.PaymentRequest")
        and not app.new("toy.QueueEntry")
    )


@dataclass(frozen=True)
class ToyTask:
    calls: Callable[[], list[Call]]
    verifier: Callable[[ToyApp], bool]


TASKS: dict[str, ToyTask] = {
    "split-bill": ToyTask(_split_bill_calls, _check_split_bill),
    "split-bill-counted": ToyTask(_split_bill_calls, _check_split_bill_counted),
    "queue-songs": ToyTask(
        lambda: [
            _signin(),
            _write("post", "/toy/queue", song_id=7),
            _write("post", "/toy/queue", song_id=9),
            _done(),
        ],
        _check_queue,
    ),
    "like-songs": ToyTask(
        lambda: [
            _signin(),
            _write("post", "/toy/likes", song_id=3),
            _write("post", "/toy/likes", song_id=4),
            _done(),
        ],
        _check_likes,
    ),
    "rename-profile": ToyTask(
        lambda: [_signin(), _write("patch", "/toy/profile", display_name="Ada Lovelace"), _done()],
        _check_rename,
    ),
}


class ToyAdapter:
    name = "toy"
    ignore_fields = frozenset({"id"})
    policy = DEFAULT_POLICY

    def describe(self) -> dict[str, Any]:
        return {"name": self.name, "tasks": len(TASKS), "synthetic": True}

    def task_ids(self, split: str | None = None, limit: int | None = None) -> list[str]:
        ids = list(TASKS)
        return ids[:limit] if limit else ids

    def _task(self, task_id: str) -> ToyTask:
        if task_id not in TASKS:
            raise KeyError(f"unknown toy task {task_id!r}; choose from {', '.join(TASKS)}")
        return TASKS[task_id]

    def reference(self, task_id: str) -> Reference:
        task = self._task(task_id)
        app = ToyApp()
        calls = task.calls()
        for call in calls:
            app.call(call)
        return Reference(task_id, calls, app.effect())

    def deliver(self, task_id: str, runs: Sequence[Run]) -> list[Delivery]:
        task = self._task(task_id)
        out = []
        for run in runs:
            app = ToyApp()
            statuses = [app.call(call) for call in run.calls]
            effect = app.effect()  # read back before the verifier runs
            verdict = None
            if run.grade:
                verdict = "PASS" if task.verifier(app) else "FAIL"
            out.append(Delivery(run.run_id, effect, verdict, statuses))
        return out
