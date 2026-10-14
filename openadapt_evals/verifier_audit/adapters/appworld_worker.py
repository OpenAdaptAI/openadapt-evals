"""AppWorld side of ``openadapt-evals audit-verifier --benchmark appworld``.

This file runs under the Python environment that has AppWorld installed, not
under openadapt-evals. AppWorld needs Python 3.11 or later and pins pydantic 1,
so the two cannot share a process. The parent sends it one task at a time and
reads one JSON file back. It imports only the standard library and AppWorld.

Nothing from AppWorld is copied here. The task data, the reference solutions
and the tests come from the user's own AppWorld root at run time
(``appworld install`` and ``appworld download data``).

Commands
--------
``probe``      print the AppWorld package and data versions.
``list``       print the task ids of one dataset split.
``reference``  run the task's shipped solution from a fresh start state,
               record its API calls, and read back its effect.
``deliver``    for each run in a list: start the task fresh, replay the run's
               API calls, read back the effect, then (when asked) call
               AppWorld's own evaluator on that state. The readback always
               comes before the evaluator call.

The effect is the typed difference between the start and end databases: the
records added, removed and updated in each changed table. It comes from
AppWorld's own model diff (``ModelCollectionPair``), the same diff the
evaluator receives, but none of the task's test assertions.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import traceback
import types
from pathlib import Path

# Flags AppWorld reserves for checking its own solutions
# (``AppWorldInitDefaults``). The shipped ``solution.py`` files rely on them.
SOLUTION_FLAGS = dict(
    add_login_shortcut=True,
    munchify_response=True,
    parse_datetimes=True,
    allow_datetime_change=True,
)


def _install_icecream_stub() -> None:
    """Some shipped solutions import ``icecream`` for debug printing only."""
    try:
        import icecream  # noqa: F401
    except ModuleNotFoundError:
        module = types.ModuleType("icecream")

        def ic(*args):
            return args[0] if len(args) == 1 else (args or None)

        ic.configureOutput = lambda *a, **k: None  # type: ignore[attr-defined]
        module.ic = ic  # type: ignore[attr-defined]
        sys.modules["icecream"] = module


def _jsonable(value):
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if hasattr(value, "isoformat"):  # dates and datetimes, as AppWorld's own log writes them
        return value.isoformat()
    return str(value)


def _record(record) -> dict:
    data = record.to_dict(keep_computed=False, humanize=False)
    return {name: (None if value is None else str(value)) for name, value in data.items()}


def _rows(collection, model_name: str) -> dict:
    app_name, class_name = model_name.split(".", 1)
    collection.reset_db_home_path()
    model = getattr(collection[app_name], class_name)
    return {record.id: _record(record) for record in model.find_all()}


def _readback(world) -> dict:
    """Effect of the run so far, as added / removed / updated records per table.

    AppWorld keeps a write counter per table that starts at zero for each
    task. Only tables with a nonzero counter can differ from the start
    state, so only those are read. Each one is read in full from the start
    state (the task's own model collection) and from the live end state,
    and the records are matched by id. Nothing here loads a new collection,
    because that resets AppWorld's in-memory database cache and would wipe
    the state the evaluator is about to grade.
    """
    start = world.task.model_collection
    end = world.models
    end.reset_db_home_path()
    counters = {name: int(value) for name, value in (end.model_hashes() or {}).items() if value}
    effect: dict = {}
    for model_name in sorted(counters):
        before = _rows(start, model_name)
        after = _rows(end, model_name)
        added = [after[i] for i in sorted(after.keys() - before.keys())]
        removed = [before[i] for i in sorted(before.keys() - after.keys())]
        updated = [
            {"before": before[i], "after": after[i]}
            for i in sorted(after.keys() & before.keys())
            if before[i] != after[i]
        ]
        if added or removed or updated:
            effect[model_name] = {"added": added, "removed": removed, "updated": updated}
    end.reset_db_home_path()
    return {"effect": effect, "write_counters": counters}


def _replay(world, calls: list[dict]) -> list[int]:
    """Send each recorded call through AppWorld's requester. Returns status codes."""
    requester = world.requester
    client = getattr(requester, "client", None)
    statuses: list[int] = []
    for call in calls:
        method = str(call.get("method", "get")).lower()
        url = str(call.get("url", ""))
        if not url.startswith(("/", "http://", "https://")):
            url = "/" + url
        data = dict(call.get("data") or {})
        low_level = getattr(requester, "_" + method, None)
        try:
            if low_level is not None:
                response = low_level(url=url, data=data, client=client, raise_on_failure=False)
                statuses.append(int(getattr(response, "status_code", 0) or 0))
            else:
                getattr(requester, method)(url, data=data, client=client, raise_on_failure=False)
                statuses.append(200)
        except Exception:  # noqa: BLE001 - a failed call is evidence, not a crash
            statuses.append(-1)
    return statuses


def _cleanup(world, root: Path, experiment: str) -> None:
    try:
        if world is not None:
            world.close()
    except Exception:  # noqa: BLE001
        pass
    shutil.rmtree(root / "experiments" / "outputs" / experiment, ignore_errors=True)


def cmd_probe(args) -> dict:
    import appworld
    from appworld import update_root

    update_root(str(args.root))
    version_file = Path(args.root) / "data" / "version.txt"
    return {
        "appworld_version": getattr(appworld, "__version__", None),
        "data_version": version_file.read_text().strip() if version_file.is_file() else None,
        "python": sys.version.split()[0],
    }


def cmd_list(args) -> dict:
    from appworld import load_task_ids, update_root

    update_root(str(args.root))
    return {"split": args.split, "task_ids": list(load_task_ids(args.split))}


def cmd_reference(args) -> dict:
    from appworld import AppWorld, update_root
    from munch import munchify

    _install_icecream_stub()
    update_root(str(args.root))
    experiment = f"oa_audit_ref_{args.task_id}_{os.getpid()}"
    out: dict = {"task_id": args.task_id, "exception": None}
    world = None
    try:
        world = AppWorld(
            task_id=args.task_id,
            experiment_name=experiment,
            raise_on_failure=False,
            ground_truth_mode="full",
            **SOLUTION_FLAGS,
        )
        gt = world.task.ground_truth
        main_user = world.models.admin.MainUser.find_one(**world.task.supervisor)
        try:
            solution = gt.solution_module()
            solution.solution(main_user, world.apis, world.requester, munchify(gt.public_data))
        except Exception as exc:  # noqa: BLE001 - the solution's failure is evidence
            out["exception"] = f"{type(exc).__name__}: {str(exc)[:400]}"
        out["calls"] = _jsonable(list(world.requester.requests))
        tasks = world.models.supervisor.Task.all()
        out["claimed_success"] = bool(tasks) and str(getattr(tasks[0], "status", "")) == "success"
        out.update(_readback(world))
        out["allowed_apps"] = list(world.task.allowed_apps)
    finally:
        _cleanup(world, Path(args.root), experiment)
    return out


def cmd_deliver(args) -> dict:
    from appworld import AppWorld, update_root

    update_root(str(args.root))
    runs = json.loads(Path(args.runs).read_text())
    results = []
    for index, run in enumerate(runs):
        experiment = f"oa_audit_run_{args.task_id}_{os.getpid()}_{index}"
        row: dict = {"run_id": run["run_id"]}
        world = None
        try:
            world = AppWorld(
                task_id=args.task_id, experiment_name=experiment, raise_on_failure=False
            )
            row["statuses"] = _replay(world, run["calls"])
            # Readback first. The verifier is called only after the effect is recorded.
            row.update(_readback(world))
            if run.get("grade", True):
                # AppWorld's evaluator reads the end state from disk. execute()
                # writes it there after every agent turn; a replay bypasses
                # execute(), so write it the same way before grading.
                world._save_state(world.output_db_home_path_on_disk)
                tracker = world.evaluate(suppress_errors=True)
                report = tracker.to_dict()
                row["verdict"] = "PASS" if report.get("success") else "FAIL"
                row["num_tests"] = report.get("num_tests")
                row["num_failed"] = len(report.get("failures") or [])
        except Exception as exc:  # noqa: BLE001
            row["error"] = f"{type(exc).__name__}: {str(exc)[:400]}"
            row["traceback"] = traceback.format_exc()[-1500:]
        finally:
            _cleanup(world, Path(args.root), experiment)
        results.append(row)
    return {"task_id": args.task_id, "runs": results}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("probe", "list", "reference", "deliver"):
        p = sub.add_parser(name)
        p.add_argument("--root", type=Path, required=True)
        p.add_argument("--out", type=Path, required=True)
        if name == "list":
            p.add_argument("--split", required=True)
        if name in ("reference", "deliver"):
            p.add_argument("--task-id", required=True)
        if name == "deliver":
            p.add_argument("--runs", type=Path, required=True)
    args = parser.parse_args(argv)
    handler = {
        "probe": cmd_probe,
        "list": cmd_list,
        "reference": cmd_reference,
        "deliver": cmd_deliver,
    }[args.command]
    try:
        payload = handler(args)
        payload["ok"] = True
    except Exception as exc:  # noqa: BLE001
        payload = {
            "ok": False,
            "error": f"{type(exc).__name__}: {str(exc)[:400]}",
            "traceback": traceback.format_exc()[-2000:],
        }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    # Keep key order: the order of a call's fields is the order the run sent them.
    args.out.write_text(json.dumps(payload, indent=1) + "\n")
    return 0 if payload["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())
