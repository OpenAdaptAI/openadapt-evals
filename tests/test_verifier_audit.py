"""Tests for openadapt_evals.verifier_audit (``openadapt-evals audit-verifier``).

Everything here runs offline against the built-in synthetic benchmark or a
fake AppWorld worker. ``test_appworld_live`` runs the real AppWorld only when
APPWORLD_PYTHON and APPWORLD_ROOT point at an installed copy.
"""

from __future__ import annotations

import json
import os
import sys
import textwrap
from pathlib import Path

import pytest

from openadapt_evals.verifier_audit import (
    OPERATORS,
    CallPolicy,
    Delivery,
    Reference,
    Run,
    apply_operator,
    audit,
    audit_task,
    compare,
    repeat_at,
    repeat_candidates,
)
from openadapt_evals.verifier_audit.adapters import appworld_bridge
from openadapt_evals.verifier_audit.adapters.appworld_bridge import AppWorldAdapter
from openadapt_evals.verifier_audit.adapters.base import SetupError
from openadapt_evals.verifier_audit.adapters.toy import TASKS, ToyAdapter
from openadapt_evals.verifier_audit.cli import main
from openadapt_evals.verifier_audit.effects import ADDS, CHANGES, REMOVES, SAME
from openadapt_evals.verifier_audit.report import render
from openadapt_evals.verifier_audit.runner import (
    CONTROL_FAILED,
    EQUIVALENT,
    FALSE_ACCEPT,
    INVALID,
    KILLED,
    NO_WRITE,
    NOT_DELIVERED,
    REFUSED,
    UNCONFIRMED,
)


def _call(method: str, url: str, **data):
    return {"method": method, "url": url, "data": data}


SIGNIN = _call("post", "/app/auth/token", username="u", password="secret")
CLAIM = _call("post", "/supervisor/complete_task", status="success")


def _run_of_writes() -> list[dict]:
    return [
        SIGNIN,
        _call("get", "/app/items", access_token="t"),
        _call("post", "/app/items", access_token="t", name="first item", qty=1),
        _call("post", "/app/items", access_token="t", name="second item", qty=2),
        _call("patch", "/app/items/17", access_token="t", qty=5),
        CLAIM,
    ]


# -- operators ---------------------------------------------------------------


def test_operator_names_match_the_paper_classes():
    assert OPERATORS == ("claim-only", "omit", "partial", "wrong-value", "extra", "extra-ni")


def test_claim_only_keeps_sign_in_and_claim():
    edit = apply_operator(_run_of_writes(), "claim-only")
    assert edit.calls == [SIGNIN, CLAIM]


def test_omit_drops_the_last_write_only():
    calls = _run_of_writes()
    edit = apply_operator(calls, "omit")
    assert edit.calls == calls[:4] + calls[5:]
    assert edit.detail["dropped"] == "/app/items/17"


def test_extra_repeats_the_last_write_in_place():
    calls = _run_of_writes()
    edit = apply_operator(calls, "extra")
    assert edit.calls == calls[:5] + [calls[4]] + calls[5:]
    assert edit.calls[5] is not calls[4]  # a copy, so later edits cannot alias


def test_partial_keeps_first_of_most_repeated_endpoint():
    calls = _run_of_writes()
    edit = apply_operator(calls, "partial")
    assert edit.calls == calls[:3] + calls[4:]
    assert edit.detail == {"calls": 6, "writes": 3, "endpoint": "/app/items", "dropped": 1}


def test_partial_refuses_without_a_repeated_write():
    edit = apply_operator([SIGNIN, _call("post", "/app/items", name="only"), CLAIM], "partial")
    assert edit.refused and edit.refusal == "NO_REPEATED_WRITE"


def test_wrong_value_changes_first_long_string_then_numbers():
    calls = [_call("post", "/app/x", access_token="secret-token", label="dinner", n=3)]
    edit = apply_operator(calls, "wrong-value")
    assert edit.calls[0]["data"] == {"access_token": "secret-token", "label": "dinnerx", "n": 3}
    numeric = apply_operator([_call("post", "/app/x", access_token="tok", n=3)], "wrong-value")
    assert numeric.calls[0]["data"]["n"] == 4
    ends_in_x = apply_operator([_call("post", "/app/x", label="inbox")], "wrong-value")
    assert ends_in_x.calls[0]["data"]["label"] == "inboxy"
    # The input run is never modified.
    assert calls[0]["data"]["label"] == "dinner"


def test_wrong_value_flips_a_boolean_and_refuses_without_a_value():
    flipped = apply_operator(
        [_call("post", "/app/x", access_token="tok", flag=True)], "wrong-value"
    )
    assert flipped.calls[0]["data"]["flag"] is False
    edit = apply_operator([_call("post", "/app/x", access_token="tok", code="ab")], "wrong-value")
    assert edit.refused and edit.refusal == "NO_CHANGEABLE_VALUE"


def test_every_operator_refuses_a_run_without_writes():
    calls = [SIGNIN, _call("get", "/app/items"), CLAIM]
    for operator in ("claim-only", "omit", "partial", "wrong-value", "extra"):
        assert apply_operator(calls, operator).refusal == "NO_WRITE"
    assert repeat_candidates(calls) == []


def test_repeat_candidates_are_last_call_per_endpoint_newest_first():
    calls = _run_of_writes()
    assert repeat_candidates(calls) == [4, 3]
    assert repeat_at(calls, 3) == calls[:4] + [calls[3]] + calls[4:]


def test_custom_policy_decides_what_counts_as_a_claim():
    policy = CallPolicy(is_claim=lambda call: call["url"] == "/done")
    calls = [_call("post", "/write", v="value"), _call("post", "/done")]
    assert apply_operator(calls, "claim-only", policy).calls == [calls[1]]
    assert apply_operator(calls, "omit", policy).calls == [calls[1]]


# -- effects -----------------------------------------------------------------


def _effect(**tables):
    return {name: {"added": rows, "removed": [], "updated": []} for name, rows in tables.items()}


def test_compare_counts_a_duplicate_record_after_ignoring_ids():
    control = _effect(Request=[{"id": 1, "to": "a"}, {"id": 2, "to": "b"}])
    mutant = _effect(Request=[{"id": 1, "to": "a"}, {"id": 2, "to": "b"}, {"id": 3, "to": "b"}])
    diff = compare(control, mutant, ignore={"id"})
    assert diff.shape == ADDS
    assert diff.tables["Request"]["+"] == 1
    assert diff.summary() == "Request +1"


def test_compare_shapes():
    base = _effect(T=[{"v": 1}, {"v": 2}])
    assert compare(base, base).shape == SAME
    assert compare(base, _effect(T=[{"v": 1}])).shape == REMOVES
    changed = compare(base, _effect(T=[{"v": 1}, {"v": 3}]))
    assert changed.shape == CHANGES
    assert changed.tables["T"]["changed"] == 1 and changed.tables["T"]["fields"] == ["v"]
    assert "T: v changed" in changed.summary()


def test_compare_ignores_table_scoped_fields_and_noop_updates():
    control = {"T": {"added": [{"note": "a", "n": 1}], "removed": [], "updated": []}}
    mutant = {"T": {"added": [{"note": "b", "n": 1}], "removed": [], "updated": []}}
    assert compare(control, mutant, ignore={"T.note"}).same
    assert not compare(control, mutant, ignore={"U.note"}).same
    touched = {
        "T": {
            "added": [],
            "removed": [],
            "updated": [
                {"before": {"id": 1, "updated_at": "1"}, "after": {"id": 1, "updated_at": "2"}}
            ],
        }
    }
    assert compare({}, touched, ignore={"updated_at"}).same


def test_diff_never_copies_values():
    control = _effect(T=[{"secret": "alpha"}])
    mutant = _effect(T=[{"secret": "beta"}])
    text = json.dumps(compare(control, mutant).tables)
    assert "alpha" not in text and "beta" not in text


# -- runner on the synthetic benchmark ----------------------------------------


def _classes(task):
    return {run.operator: run.run_class for run in task.runs}


def test_toy_split_bill_accepts_a_repeated_request():
    task = audit_task(ToyAdapter(), "split-bill")
    assert task.status == "audited" and task.control_verdict == "PASS"
    assert _classes(task) == {
        "claim-only": KILLED,
        "omit": KILLED,
        "partial": KILLED,
        "wrong-value": KILLED,
        "extra": FALSE_ACCEPT,
        "extra-ni": FALSE_ACCEPT,
    }
    extra = next(run for run in task.runs if run.operator == "extra")
    assert extra.tables["toy.PaymentRequest"]["+"] == 1
    assert extra.tables["toy.Notification"]["+"] == 1


def test_toy_counted_verifier_kills_the_repeat():
    assert _classes(audit_task(ToyAdapter(), "split-bill-counted"))["extra"] == KILLED


def test_toy_idempotent_repeat_is_equivalent_and_extra_ni_refuses():
    task = audit_task(ToyAdapter(), "like-songs")
    classes = _classes(task)
    assert classes["extra"] == EQUIVALENT
    assert classes["extra-ni"] == REFUSED
    refused = next(run for run in task.runs if run.operator == "extra-ni")
    assert refused.reason == "ALL_REPEATS_IDEMPOTENT"


def test_toy_full_audit_counts():
    result = audit(ToyAdapter(), list(TASKS))
    accepts = sorted((run.task_id, run.operator) for run in result.false_accepts)
    assert accepts == [
        ("queue-songs", "extra"),
        ("queue-songs", "extra-ni"),
        ("split-bill", "extra"),
        ("split-bill", "extra-ni"),
    ]
    table = result.by_operator()
    for operator in ("claim-only", "omit", "wrong-value"):
        assert table[operator][KILLED] == len(TASKS)
    assert table["partial"][REFUSED] == 1
    summary = result.to_dict()["summary"]
    assert summary["tasks_with_false_accept"] == 2 and summary["false_accepts"] == 4
    text = render(result)
    assert "split-bill" in text and "toy.QueueEntry +1" in text


def test_ignore_fields_cannot_hide_an_extra_record():
    result = audit(
        ToyAdapter(), ["queue-songs"], ["extra"], ignore_fields=["toy.QueueEntry.song_id"]
    )
    # The repeated entry is still one record more than the reference run made.
    assert [r.run_class for r in result.tasks[0].runs] == [FALSE_ACCEPT]


class _ScriptedAdapter:
    """Adapter whose deliveries are scripted, to reach every class."""

    name = "scripted"
    ignore_fields = frozenset({"id"})
    policy = CallPolicy()

    def __init__(self, control_verdict="PASS", control_effect=None, mutant=None, calls=None):
        self.control_verdict = control_verdict
        self.control_effect = (
            control_effect if control_effect is not None else _effect(T=[{"v": 1}])
        )
        self.mutant = mutant or {}
        self.calls = calls if calls is not None else [SIGNIN, _call("post", "/t", v="value"), CLAIM]
        self.graded: list[str] = []

    def describe(self):
        return {"name": self.name}

    def task_ids(self, split=None, limit=None):
        return ["t1"]

    def reference(self, task_id):
        return Reference(task_id, self.calls, _effect(T=[{"v": 1}]))

    def deliver(self, task_id, runs):
        out = []
        for run in runs:
            if run.grade:
                self.graded.append(run.run_id)
            if run.run_id == "control" or run.run_id.startswith("scan"):
                out.append(
                    Delivery(
                        run.run_id,
                        self.control_effect,
                        self.control_verdict if run.grade else None,
                        [200],
                    )
                )
            else:
                out.append(self.mutant.get(run.run_id, Delivery(run.run_id, {}, "FAIL", [200])))
        return out


def test_failed_control_makes_mutants_invalid():
    adapter = _ScriptedAdapter(control_verdict="FAIL")
    task = audit_task(adapter, "t1", ["omit"])
    assert task.status == CONTROL_FAILED
    assert _classes(task) == {"omit": INVALID}


def test_control_must_reproduce_the_reference_effect():
    adapter = _ScriptedAdapter(control_effect=_effect(T=[{"v": 2}]))
    task = audit_task(adapter, "t1", ["omit"])
    assert task.status == CONTROL_FAILED and "reproduce" in task.reason


def test_crashed_calls_make_a_pass_unconfirmed_and_errors_not_delivered():
    adapter = _ScriptedAdapter(
        mutant={
            "omit": Delivery("omit", {}, "PASS", [200, -1]),
            "extra": Delivery("extra", error="boom"),
        }
    )
    task = audit_task(adapter, "t1", ["omit", "extra"])
    assert _classes(task) == {"omit": UNCONFIRMED, "extra": NOT_DELIVERED}


def test_ignore_fields_makes_a_free_field_change_equivalent():
    changed = Delivery("wrong-value", _effect(T=[{"v": 1, "note": "x"}]), "PASS", [200])
    adapter = _ScriptedAdapter(mutant={"wrong-value": changed})
    assert _classes(audit_task(adapter, "t1", ["wrong-value"])) == {"wrong-value": FALSE_ACCEPT}
    task = audit_task(adapter, "t1", ["wrong-value"], ignore_fields=["T.note"])
    assert _classes(task) == {"wrong-value": EQUIVALENT}


def test_scan_makes_no_verifier_call():
    adapter = _ScriptedAdapter()
    audit_task(adapter, "t1", ["extra-ni"])
    assert all(not run_id.startswith("scan") for run_id in adapter.graded)


def test_read_only_task_is_skipped_without_delivery():
    adapter = _ScriptedAdapter(calls=[SIGNIN, _call("get", "/t"), CLAIM])
    task = audit_task(adapter, "t1")
    assert task.status == NO_WRITE and task.runs == []
    assert adapter.graded == []


def test_reference_error_is_reported_not_raised():
    class Broken(_ScriptedAdapter):
        def reference(self, task_id):
            raise RuntimeError("no solution")

    task = audit_task(Broken(), "t1")
    assert task.status == "no-reference" and "no solution" in task.reason


def test_adapter_that_raises_on_delivery_does_not_end_the_audit():
    class Raising(_ScriptedAdapter):
        def deliver(self, task_id, runs):
            raise RuntimeError("server down")

    task = audit_task(Raising(), "t1")
    assert task.status == CONTROL_FAILED and "server down" in task.reason
    classes = _classes(task)
    assert classes["extra-ni"] == REFUSED
    assert {c for op, c in classes.items() if op != "extra-ni" and c != REFUSED} == {NOT_DELIVERED}


def test_parallel_jobs_keep_task_order():
    result = audit(ToyAdapter(), list(TASKS), jobs=3)
    assert [task.task_id for task in result.tasks] == list(TASKS)


# -- command line ---------------------------------------------------------------


def test_cli_toy_exits_1_on_false_accept_and_writes_json(tmp_path, capsys):
    out = tmp_path / "report.json"
    assert main(["--benchmark", "toy", "--out", str(out)]) == 1
    report = json.loads(out.read_text())
    assert report["schema"] == "openadapt-evals/verifier-audit/v1"
    assert report["summary"]["false_accepts"] == 4
    assert "The verifier passed 4 edited run(s)" in capsys.readouterr().out


def test_cli_exit_zero_and_operator_subset(capsys):
    assert main(["--benchmark", "toy", "--operators", "omit,claim-only", "--exit-zero"]) == 0
    assert main(["--benchmark", "toy", "--operators", "omit", "--tasks", "split-bill"]) == 0
    assert main(["--benchmark", "toy", "--operators", "nope"]) == 2


def test_cli_json_output(capsys):
    main(["--benchmark", "toy", "--tasks", "like-songs", "--json"])
    report = json.loads(capsys.readouterr().out)
    assert report["summary"]["false_accepts"] == 0


def test_cli_custom_adapter_by_module_path(tmp_path, monkeypatch, capsys):
    module = tmp_path / "my_bench_adapter.py"
    module.write_text(
        "from openadapt_evals.verifier_audit.adapters.toy import ToyAdapter\n"
        "class MyAdapter(ToyAdapter):\n    name = 'mine'\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    assert main(["--benchmark", "my_bench_adapter:MyAdapter", "--tasks", "queue-songs"]) == 1
    assert "Verifier audit: mine" in capsys.readouterr().out


def test_cli_unknown_benchmark_or_adapter_exits_2(capsys):
    assert main(["--benchmark", "nope"]) == 2
    assert main(["--benchmark", "no_such_module_xyz:Adapter"]) == 2
    assert "cannot load adapter" in capsys.readouterr().err


def test_cli_appworld_without_setup_prints_setup_and_exits_2(monkeypatch, capsys):
    monkeypatch.delenv("APPWORLD_PYTHON", raising=False)
    monkeypatch.delenv("APPWORLD_ROOT", raising=False)
    assert main(["--benchmark", "appworld"]) == 2
    err = capsys.readouterr().err
    assert "appworld download data" in err and "--appworld-python" in err


def test_legacy_cli_registers_audit_verifier(monkeypatch):
    from openadapt_evals.benchmarks import cli as legacy

    monkeypatch.setattr(
        sys,
        "argv",
        ["openadapt-evals", "audit-verifier", "--benchmark", "toy", "--tasks", "like-songs"],
    )
    assert legacy.main() == 0


# -- AppWorld bridge with a fake worker -------------------------------------------

FAKE_WORKER = textwrap.dedent(
    """
    import json, sys
    args = sys.argv[1:]
    command = args[0]
    out = args[args.index("--out") + 1]
    def effect(n):
        return {"venmo.PaymentRequest": {"added": [{"id": i, "to": "a"} for i in range(n)],
                "removed": [], "updated": []}}
    if command == "probe":
        payload = {"ok": True, "appworld_version": "0.0.fake", "data_version": "0", "python": "3.11"}
    elif command == "list":
        payload = {"ok": True, "task_ids": ["t_1", "t_2", "t_3"]}
    elif command == "reference":
        calls = [{"method": "post", "url": "/venmo/auth/token", "data": {}},
                 {"method": "post", "url": "/venmo/payment_requests", "data": {"user_email": "a@b.c", "amount": 5}},
                 {"method": "post", "url": "/supervisor/message", "data": {"status": "success"}}]
        payload = {"ok": True, "calls": calls, "effect": effect(1), "claimed_success": True,
                   "exception": None, "write_counters": {}}
    else:
        runs = json.load(open(args[args.index("--runs") + 1]))
        rows = []
        for run in runs:
            n = sum(1 for c in run["calls"] if c["url"] == "/venmo/payment_requests")
            row = {"run_id": run["run_id"], "statuses": [200] * len(run["calls"]),
                   "effect": effect(n), "write_counters": {}}
            if run.get("grade", True):
                row["verdict"] = "PASS" if n >= 1 else "FAIL"  # never counts
                row["num_tests"], row["num_failed"] = 2, 0 if n >= 1 else 1
            rows.append(row)
        payload = {"ok": True, "task_id": "t", "runs": rows}
    json.dump(payload, open(out, "w"))
    """
)


@pytest.fixture
def fake_appworld(tmp_path, monkeypatch):
    worker = tmp_path / "fake_worker.py"
    worker.write_text(FAKE_WORKER)
    monkeypatch.setattr(appworld_bridge, "WORKER", worker)
    root = tmp_path / "root"
    (root / "data" / "tasks").mkdir(parents=True)
    return AppWorldAdapter(python=sys.executable, root=root)


def test_bridge_round_trip_with_fake_worker(fake_appworld):
    assert fake_appworld.describe()["appworld_version"] == "0.0.fake"
    assert fake_appworld.task_ids("train", 2) == ["t_1", "t_2"]
    task = audit_task(fake_appworld, "t_1")
    classes = _classes(task)
    assert classes["extra"] == FALSE_ACCEPT and classes["extra-ni"] == FALSE_ACCEPT
    assert classes["omit"] == KILLED and classes["partial"] == REFUSED
    extra = next(run for run in task.runs if run.operator == "extra")
    assert extra.detail["num_tests"] == 2


def test_bridge_rejects_a_root_without_data(tmp_path):
    with pytest.raises(SetupError, match="no data/tasks"):
        AppWorldAdapter(python=sys.executable, root=tmp_path)


def test_bridge_reports_a_worker_that_cannot_import_appworld(tmp_path):
    root = tmp_path / "root"
    (root / "data" / "tasks").mkdir(parents=True)
    # The real worker under an interpreter without AppWorld: probe fails cleanly.
    try:
        import appworld  # noqa: F401

        pytest.skip("AppWorld is importable here")
    except ImportError:
        pass
    with pytest.raises(SetupError, match="AppWorld did not load"):
        AppWorldAdapter(python=sys.executable, root=root)


def test_worker_imports_only_the_standard_library_at_module_level():
    source = Path(appworld_bridge.WORKER).read_text()
    top_level = [line for line in source.splitlines() if line.startswith(("import ", "from "))]
    allowed = {
        "argparse",
        "json",
        "os",
        "shutil",
        "sys",
        "traceback",
        "types",
        "__future__",
        "pathlib",
    }
    for line in top_level:
        module = line.split()[1].split(".")[0]
        assert module in allowed, line


# -- real AppWorld (opt-in) -------------------------------------------------------


@pytest.mark.skipif(
    not (os.environ.get("APPWORLD_PYTHON") and os.environ.get("APPWORLD_ROOT")),
    reason="set APPWORLD_PYTHON and APPWORLD_ROOT to run against an installed AppWorld",
)
def test_appworld_live_reproduces_the_duplicate_payment_request():
    adapter = AppWorldAdapter()
    task = audit_task(adapter, "22cc237_1")
    classes = _classes(task)
    assert task.control_verdict == "PASS"
    assert classes["extra"] == FALSE_ACCEPT
    assert classes["omit"] == KILLED and classes["claim-only"] == KILLED
    extra = next(run for run in task.runs if run.operator == "extra")
    assert extra.tables["venmo.PaymentRequest"]["+"] == 1


def test_run_dataclass_defaults():
    assert Run("x", []).grade is True
