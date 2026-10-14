"""AppWorld adapter: runs each step in AppWorld's own Python environment.

AppWorld (https://github.com/StonyBrookNLP/appworld, Apache-2.0) needs Python
3.11 or later and pydantic 1, which cannot share a process with this package.
This adapter therefore runs ``appworld_worker.py`` with the interpreter you
name, one subprocess per step, and exchanges JSON files with it.

Nothing from AppWorld ships with openadapt-evals. AppWorld distributes its
task data and tests in an encrypted bundle and asks that any public
redistribution stay encrypted, so you install it and download its data
yourself, once (``SETUP``). The audit reads them from your copy at run time.

Reports keep per-table record counts and field names, not record values, so
a report can be shared without carrying AppWorld data.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Sequence

from openadapt_evals.verifier_audit.adapters.base import (
    Delivery,
    Reference,
    Run,
    SetupError,
)
from openadapt_evals.verifier_audit.operators import DEFAULT_POLICY

WORKER = Path(__file__).with_name("appworld_worker.py")

SETUP = """\
AppWorld is not set up. Set it up once (about 750 MB on disk). AppWorld needs
its own environment because it pins pydantic 1:

  uv venv --python 3.11 ~/.cache/appworld/venv
  uv pip install --python ~/.cache/appworld/venv/bin/python appworld==0.1.3.post1
  ~/.cache/appworld/venv/bin/appworld install
  ~/.cache/appworld/venv/bin/appworld download data --root ~/.cache/appworld

Then run the audit with those two paths:

  openadapt-evals audit-verifier --benchmark appworld \\
      --appworld-python ~/.cache/appworld/venv/bin/python \\
      --appworld-root ~/.cache/appworld

or set APPWORLD_PYTHON and APPWORLD_ROOT instead of passing the flags."""


class AppWorldAdapter:
    name = "appworld"
    # Fields with no task meaning: database ids and write timestamps.
    ignore_fields = frozenset({"id", "created_at", "updated_at", "record_hash"})
    policy = DEFAULT_POLICY

    def __init__(
        self,
        python: str | os.PathLike | None = None,
        root: str | os.PathLike | None = None,
        timeout: float = 1800.0,
        keep_dir: str | os.PathLike | None = None,
    ) -> None:
        python = python or os.environ.get("APPWORLD_PYTHON")
        root = root or os.environ.get("APPWORLD_ROOT")
        if not python or not root:
            raise SetupError(SETUP)
        self.python = str(Path(python).expanduser())
        self.root = Path(root).expanduser().resolve()
        if not Path(self.python).exists():
            raise SetupError(f"--appworld-python {self.python} does not exist.\n\n{SETUP}")
        if not (self.root / "data" / "tasks").is_dir():
            raise SetupError(f"{self.root} has no data/tasks directory.\n\n{SETUP}")
        self.timeout = timeout
        self.keep_dir = Path(keep_dir) if keep_dir else None
        self._info = self._call("probe", [])

    # -- worker plumbing -------------------------------------------------

    def _call(self, command: str, args: list[str], payload: Any = None) -> dict[str, Any]:
        work = Path(tempfile.mkdtemp(prefix="oa-audit-"))
        try:
            extra: list[str] = []
            if payload is not None:
                runs_path = work / "runs.json"
                runs_path.write_text(json.dumps(payload))
                extra = ["--runs", str(runs_path)]
            out = work / "out.json"
            # -P keeps the worker's directory off sys.path, so nothing next to
            # it can shadow the appworld package.
            cmd = [self.python, "-P", str(WORKER), command, "--root", str(self.root)]
            cmd += ["--out", str(out), *args, *extra]
            try:
                proc = subprocess.run(
                    cmd, capture_output=True, text=True, timeout=self.timeout, check=False
                )
            except subprocess.TimeoutExpired:
                return {"ok": False, "error": f"timed out after {self.timeout:.0f}s"}
            if not out.is_file():
                tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-5:]
                if command == "probe":
                    raise SetupError(
                        "The AppWorld worker did not start:\n  "
                        + "\n  ".join(tail)
                        + f"\n\n{SETUP}"
                    )
                return {"ok": False, "error": " | ".join(tail) or f"exit {proc.returncode}"}
            result = json.loads(out.read_text())
            if command == "probe" and not result.get("ok"):
                raise SetupError(f"AppWorld did not load: {result.get('error')}\n\n{SETUP}")
            if self.keep_dir is not None:
                self.keep_dir.mkdir(parents=True, exist_ok=True)
                tag = "_".join(a for a in args if not a.startswith("-")) or command
                shutil.copy2(out, self.keep_dir / f"{command}_{tag}.json")
            return result
        finally:
            shutil.rmtree(work, ignore_errors=True)

    # -- adapter interface ----------------------------------------------

    def describe(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "appworld_version": self._info.get("appworld_version"),
            "data_version": self._info.get("data_version"),
            "python": self._info.get("python"),
        }

    def task_ids(self, split: str | None = None, limit: int | None = None) -> list[str]:
        result = self._call("list", ["--split", split or "train"])
        if not result.get("ok"):
            raise SetupError(f"Could not list AppWorld split {split!r}: {result.get('error')}")
        ids = list(result["task_ids"])
        return ids[:limit] if limit else ids

    def reference(self, task_id: str) -> Reference:
        result = self._call("reference", ["--task-id", task_id])
        if not result.get("ok"):
            return Reference(task_id, [], {}, error=result.get("error"))
        error = result.get("exception")
        if error is None and not result.get("claimed_success"):
            error = "the shipped solution did not report success"
        return Reference(
            task_id,
            result.get("calls") or [],
            result.get("effect") or {},
            error=error,
            detail={"write_counters": result.get("write_counters")},
        )

    def deliver(self, task_id: str, runs: Sequence[Run]) -> list[Delivery]:
        payload = [{"run_id": r.run_id, "calls": r.calls, "grade": r.grade} for r in runs]
        result = self._call("deliver", ["--task-id", task_id], payload)
        if not result.get("ok"):
            return [Delivery(r.run_id, error=result.get("error")) for r in runs]
        by_id = {row["run_id"]: row for row in result.get("runs", [])}
        out = []
        for run in runs:
            row = by_id.get(run.run_id)
            if row is None:
                out.append(Delivery(run.run_id, error="the worker returned no result"))
                continue
            out.append(
                Delivery(
                    run.run_id,
                    effect=row.get("effect") or {},
                    verdict=row.get("verdict"),
                    statuses=list(row.get("statuses") or []),
                    error=row.get("error"),
                    detail={
                        "num_tests": row.get("num_tests"),
                        "num_failed": row.get("num_failed"),
                        "write_counters": row.get("write_counters"),
                    },
                )
            )
        return out
