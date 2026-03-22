"""Custom task configuration supporting YAML and WAA JSON formats.

Lets users define tasks with setup commands and evaluation checks in
simple YAML files or native WAA JSON format, without forking WAA or
modifying the Docker image.  The WAA server already accepts evaluator
configs in POST /evaluate -- this module translates both formats into
that structure.

Usage:
    from openadapt_evals.task_config import TaskConfig

    # Load a single task from YAML
    task = TaskConfig.from_yaml("tasks/change-font.yaml")
    benchmark_task = task.to_benchmark_task()

    # Load a single task from WAA JSON
    task = TaskConfig.from_waa_json("examples/writer/abc123.json")

    # Load all tasks from a directory (YAML + JSON auto-detected)
    tasks = TaskConfig.from_dir("tasks/")

    # Load from a WAA examples directory tree (examples/{domain}/{id}.json)
    tasks = TaskConfig.from_waa_dir("evaluation_examples_windows/examples/")
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from openadapt_evals.adapters.base import BenchmarkTask

logger = logging.getLogger(__name__)


@dataclass
class TaskCheck:
    """A single evaluation check."""

    check: str  # "command", "file", "screenshot", "python"
    # command check
    run: str | None = None
    expect: str | None = None
    match: str = "exact"  # "exact", "contains", "regex", "fuzzy"
    # file check
    path: str | None = None
    exists: bool = True
    contains: str | None = None
    # screenshot check
    description: str | None = None
    # python check
    code: str | None = None


@dataclass
class Milestone:
    """An intermediate checkpoint for dense rewards."""

    name: str
    check: TaskCheck


@dataclass
class TaskConfig:
    """A custom task definition loaded from YAML or WAA JSON."""

    name: str
    id: str
    domain: str
    setup: list[dict[str, Any]]
    checks: list[TaskCheck]
    combine: str  # "and" | "or"
    max_steps: int
    milestones: list[Milestone]

    # Raw WAA evaluator preserved for lossless round-trip.  When present,
    # to_waa_config() emits this directly instead of re-translating checks.
    _raw_evaluator: dict[str, Any] | None = field(
        default=None, repr=False, compare=False
    )

    @classmethod
    def from_yaml(cls, path: str) -> TaskConfig:
        """Load a task config from a YAML file."""
        with open(path) as f:
            data = yaml.safe_load(f)

        task_id = data.get("id", f"custom-{uuid.uuid4().hex[:8]}")
        name = data.get("name", Path(path).stem)
        domain = data.get("domain", "desktop")
        max_steps = data.get("max_steps", 15)
        combine = data.get("combine", "and")

        # Parse setup commands
        setup = []
        for item in data.get("setup", []):
            if isinstance(item, dict):
                setup.append(item)
            else:
                setup.append({"execute": str(item)})

        # Parse evaluation checks
        checks = []
        for item in data.get("evaluate", []):
            checks.append(TaskCheck(**{k: v for k, v in item.items()}))

        # Parse milestones
        milestones = []
        for item in data.get("milestones", []):
            ms_name = item.get("name", "milestone")
            check_fields = {k: v for k, v in item.items() if k != "name"}
            milestones.append(Milestone(name=ms_name, check=TaskCheck(**check_fields)))

        return cls(
            name=name,
            id=task_id,
            domain=domain,
            setup=setup,
            checks=checks,
            combine=combine,
            max_steps=max_steps,
            milestones=milestones,
        )

    @classmethod
    def from_waa_json(cls, path: str) -> TaskConfig:
        """Load a task config from a WAA native JSON file.

        WAA JSON files live in ``evaluation_examples_windows/examples/
        {domain}/{task_id}.json`` and contain fields like ``id``,
        ``instruction``, ``config`` (setup array), and ``evaluator``.

        Common evaluator patterns (exact_match, contains, fuzzy_match with
        vm_command_line / vm_file / literal) are reverse-translated into
        :class:`TaskCheck` objects.  Evaluators that use specialised WAA
        metric functions (compare_table, compare_font_names, etc.) are
        preserved as-is for lossless round-trip via :meth:`to_waa_config`.

        Args:
            path: Path to a ``.json`` file in WAA native format.

        Returns:
            A :class:`TaskConfig` instance.
        """
        with open(path, encoding="utf-8") as f:
            data = json.load(f)

        task_id = data.get("id", Path(path).stem)
        name = data.get("instruction", data.get("task", Path(path).stem))
        domain = _infer_domain(data, path)
        max_steps = data.get("max_steps", 15)

        # --- setup -------------------------------------------------------
        setup = _parse_waa_setup(data.get("config", []))

        # --- evaluator ---------------------------------------------------
        evaluator = data.get("evaluator", {})
        checks, combine, raw_evaluator = _parse_waa_evaluator(evaluator)

        return cls(
            name=name,
            id=task_id,
            domain=domain,
            setup=setup,
            checks=checks,
            combine=combine,
            max_steps=max_steps,
            milestones=[],
            _raw_evaluator=raw_evaluator,
        )

    @classmethod
    def from_waa_dir(cls, dir_path: str) -> list[TaskConfig]:
        """Load all WAA JSON task configs from a directory tree.

        Expects the WAA layout ``{dir_path}/{domain}/{task_id}.json`` (i.e.
        the ``examples/`` directory inside ``evaluation_examples_windows``).

        Args:
            dir_path: Root of the WAA examples tree.

        Returns:
            List of :class:`TaskConfig` instances, sorted by file path.
        """
        tasks: list[TaskConfig] = []
        base = Path(dir_path)
        if not base.is_dir():
            logger.warning("WAA examples dir not found: %s", dir_path)
            return tasks

        for json_file in sorted(base.rglob("*.json")):
            try:
                tasks.append(cls.from_waa_json(str(json_file)))
            except Exception as exc:
                logger.warning("Skipping %s: %s", json_file, exc)
        return tasks

    @classmethod
    def from_dir(cls, dir_path: str) -> list[TaskConfig]:
        """Load all task configs from a directory (YAML and JSON).

        Files are auto-detected by extension:
        - ``.yaml`` / ``.yml`` -- loaded as YAML task configs
        - ``.json`` -- loaded as WAA native JSON task configs
        """
        tasks: list[TaskConfig] = []
        for fname in sorted(os.listdir(dir_path)):
            full = os.path.join(dir_path, fname)
            try:
                if fname.endswith((".yaml", ".yml")):
                    tasks.append(cls.from_yaml(full))
                elif fname.endswith(".json"):
                    tasks.append(cls.from_waa_json(full))
            except Exception as exc:
                logger.warning("Skipping %s: %s", fname, exc)
        return tasks

    def to_waa_config(self) -> dict[str, Any]:
        """Translate to WAA's native JSON format for /evaluate.

        If this TaskConfig was loaded from WAA JSON and carries a raw
        evaluator (one that uses specialised metric functions), it is
        emitted as-is for lossless round-trip.
        """
        config: dict[str, Any] = {
            "task_id": self.id,
            "instruction": self.name,
            "config": self._translate_setup(),
        }

        if self._raw_evaluator is not None:
            config["evaluator"] = self._raw_evaluator
        else:
            evaluator = self._translate_evaluator()
            if evaluator:
                config["evaluator"] = evaluator

        return config

    def to_benchmark_task(self) -> BenchmarkTask:
        """Create a BenchmarkTask for use with adapters."""
        waa_config = self.to_waa_config()
        return BenchmarkTask(
            task_id=self.id,
            instruction=self.name,
            domain=self.domain,
            time_limit_steps=self.max_steps,
            raw_config=waa_config,
            evaluation_spec=waa_config.get("evaluator"),
        )

    def _translate_setup(self) -> list[dict[str, Any]]:
        """Translate setup items to WAA config format."""
        result = []
        for item in self.setup:
            if "launch" in item:
                result.append({
                    "type": "launch",
                    "parameters": {"command": item["launch"]},
                })
            elif "open" in item:
                result.append({
                    "type": "open",
                    "parameters": {"path": item["open"]},
                })
            elif "execute" in item:
                cmd = item["execute"].strip()
                # WAA execute handler runs the command via subprocess.
                # Pass as a single string for shell execution.
                result.append({
                    "type": "execute",
                    "parameters": {"command": cmd},
                })
            elif "sleep" in item:
                result.append({
                    "type": "sleep",
                    "parameters": {"seconds": float(item["sleep"])},
                })
            elif "download" in item:
                dl = item["download"]
                result.append({
                    "type": "download",
                    "parameters": {"url": dl["url"], "path": dl["dest"]},
                })
            else:
                # Pass through raw WAA setup items
                result.append(item)
        return result

    def _translate_evaluator(self) -> dict[str, Any] | None:
        """Translate checks to WAA evaluator format."""
        # Separate server-side checks from client-side (VLM) checks
        server_checks = [c for c in self.checks if c.check != "screenshot"]
        if not server_checks:
            return None

        if len(server_checks) == 1:
            return self._translate_check(server_checks[0])

        # Multiple checks — use conjunction
        metrics = [self._translate_check(c) for c in server_checks]
        return {
            "func": [m["func"] for m in metrics],
            "result": [m["result"] for m in metrics],
            "expected": [m["expected"] for m in metrics],
            "conj": self.combine,
        }

    def _translate_check(self, check: TaskCheck) -> dict[str, Any]:
        """Translate a single check to WAA evaluator format."""
        if check.check == "command":
            match_func = {
                "exact": "exact_match",
                "contains": "contains",
                "regex": "regex_match",
                "fuzzy": "fuzzy_match",
            }.get(check.match, "exact_match")
            return {
                "func": match_func,
                "result": {
                    "type": "vm_command_line",
                    "command": check.run,
                },
                "expected": {
                    "type": "literal",
                    "value": check.expect or "",
                },
            }
        elif check.check == "file":
            if check.contains:
                return {
                    "func": "contains",
                    "result": {
                        "type": "vm_file",
                        "path": check.path,
                    },
                    "expected": {
                        "type": "literal",
                        "value": check.contains,
                    },
                }
            return {
                "func": "exact_match",
                "result": {
                    "type": "vm_command_line",
                    "command": f'python -c "import os; print(os.path.exists(r\'{check.path}\'))"',
                },
                "expected": {
                    "type": "literal",
                    "value": "True",
                },
            }
        elif check.check == "python":
            # Wrap code so it prints True/False
            escaped = check.code.replace('"', '\\"').replace("\n", "\\n")
            return {
                "func": "exact_match",
                "result": {
                    "type": "vm_command_line",
                    "command": f'python -c "{escaped}"',
                },
                "expected": {
                    "type": "literal",
                    "value": "True",
                },
            }
        else:
            raise ValueError(f"Cannot translate check type '{check.check}' to WAA format")

    def get_vlm_checks(self) -> list[TaskCheck]:
        """Return checks that need client-side VLM evaluation."""
        return [c for c in self.checks if c.check == "screenshot"]

    def evaluate_milestones(
        self,
        screenshot: bytes,
        server_url: str,
    ) -> tuple[int, int]:
        """Evaluate milestones and return (passed, total).

        Server-side milestones are evaluated via /execute_windows.
        Screenshot milestones are evaluated via VLM.
        """
        passed = 0
        total = len(self.milestones)
        if total == 0:
            return 0, 0

        for ms in self.milestones:
            try:
                if ms.check.check == "screenshot":
                    from openadapt_evals.vlm_evaluator import vlm_judge

                    success, _ = vlm_judge(screenshot, ms.check.description or "")
                    if success:
                        passed += 1
                elif ms.check.check == "command":
                    result = self._run_vm_command(ms.check.run or "", server_url)
                    if self._check_match(result, ms.check.expect or "", ms.check.match):
                        passed += 1
                else:
                    logger.warning("Milestone check type '%s' not yet supported", ms.check.check)
            except Exception as exc:
                logger.warning("Milestone '%s' evaluation failed: %s", ms.name, exc)

        logger.info("Milestones: %d/%d passed", passed, total)
        return passed, total

    @staticmethod
    def _run_vm_command(command: str, server_url: str) -> str:
        """Execute a shell command on the VM and return stdout.

        WAA's /execute_windows endpoint runs Python code via exec().
        Shell commands (PowerShell, cmd) must be wrapped in subprocess.
        """
        import requests

        # Wrap shell command in Python subprocess so /execute_windows can exec() it
        escaped = command.replace("\\", "\\\\").replace("'", "\\'")
        python_code = (
            "import subprocess; "
            f"r = subprocess.run('{escaped}', shell=True, capture_output=True, text=True); "
            "print(r.stdout.strip())"
        )

        resp = requests.post(
            f"{server_url}/execute_windows",
            json={"command": python_code},
            timeout=30,
        )
        if resp.status_code == 200:
            return resp.json().get("output", "").strip()
        return ""

    @staticmethod
    def _check_match(actual: str, expected: str, match_type: str) -> bool:
        """Check if actual matches expected using the specified method."""
        if match_type == "exact":
            return actual.strip() == expected.strip()
        elif match_type == "contains":
            return expected.strip() in actual
        elif match_type == "regex":
            import re
            return bool(re.search(expected, actual))
        elif match_type == "fuzzy":
            import difflib
            return difflib.SequenceMatcher(None, actual, expected).ratio() >= 0.8
        return False


def evaluate_milestones_screenshot(
    task_config: TaskConfig,
    screenshot: bytes,
    *,
    model: str = "gpt-4.1-mini",
) -> float:
    """Evaluate milestones using VLM screenshot checks only.

    Returns milestones_passed / total as a float [0, 1].
    Skips non-screenshot milestones (command, file checks).
    No WAA server needed -- runs entirely client-side.

    Args:
        task_config: A TaskConfig with milestones defined.
        screenshot: PNG screenshot bytes.
        model: VLM model name for screenshot evaluation.

    Returns:
        Fraction of screenshot milestones passed (0.0 to 1.0).
        Returns 0.0 if there are no screenshot milestones.
    """
    screenshot_milestones = [
        m for m in task_config.milestones if m.check.check == "screenshot"
    ]
    if not screenshot_milestones:
        return 0.0

    from openadapt_evals.vlm_evaluator import vlm_judge

    passed = 0
    for milestone in screenshot_milestones:
        success, _confidence = vlm_judge(
            screenshot, milestone.check.description or "", model=model
        )
        if success:
            passed += 1

    return passed / len(screenshot_milestones)


# ---------------------------------------------------------------------------
# WAA JSON parsing helpers (module-level to keep TaskConfig class concise)
# ---------------------------------------------------------------------------

# Metric functions that we can reverse-translate to TaskCheck.  Everything
# else is treated as a specialised WAA evaluator and preserved verbatim.
_KNOWN_SIMPLE_FUNCS = frozenset({
    "exact_match",
    "contains",
    "fuzzy_match",
    "regex_match",
})


def _infer_domain(data: dict[str, Any], path: str) -> str:
    """Best-effort domain inference from WAA JSON data or file path."""
    # Explicit field
    if data.get("domain"):
        return data["domain"]
    # related_apps hint
    apps = data.get("related_apps", [])
    if apps:
        app = apps[0].lower().replace("-", "_")
        if "calc" in app:
            return "libreoffice_calc"
        if "writer" in app:
            return "libreoffice_writer"
        return app
    # Fall back to parent directory name
    parent = Path(path).parent.name
    if parent and parent != ".":
        return parent
    return "desktop"


def _parse_waa_setup(config_array: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Reverse-translate WAA ``config`` array to YAML-style setup dicts.

    WAA format: ``[{"type": "launch", "parameters": {"command": "..."}}]``
    YAML format: ``[{"launch": "..."}]``
    """
    setup: list[dict[str, Any]] = []
    for item in config_array:
        cfg_type = item.get("type", "")
        params = item.get("parameters", {})

        if cfg_type == "launch":
            cmd = params.get("command", "")
            # command can be a list (["code"]) or a string
            if isinstance(cmd, list):
                cmd = " ".join(cmd)
            setup.append({"launch": cmd})
        elif cfg_type == "open":
            setup.append({"open": params.get("path", "")})
        elif cfg_type in ("execute", "command"):
            cmd = params.get("command", "")
            if isinstance(cmd, list):
                cmd = " ".join(cmd)
            setup.append({"execute": cmd})
        elif cfg_type == "sleep":
            setup.append({"sleep": params.get("seconds", 1)})
        elif cfg_type == "download":
            files = params.get("files", [])
            if files:
                for f in files:
                    setup.append({
                        "download": {"url": f["url"], "dest": f["path"]},
                    })
            else:
                # Single-file shorthand
                setup.append({
                    "download": {
                        "url": params.get("url", ""),
                        "dest": params.get("path", ""),
                    },
                })
        else:
            # Pass through verbatim (activate_window, verify_apps, etc.)
            setup.append(item)

    return setup


def _parse_waa_evaluator(
    evaluator: dict[str, Any],
) -> tuple[list[TaskCheck], str, dict[str, Any] | None]:
    """Reverse-translate a WAA evaluator dict to TaskCheck list.

    Returns:
        (checks, combine, raw_evaluator)
        ``raw_evaluator`` is non-None when the evaluator uses specialised
        WAA metric functions that cannot be represented as TaskCheck objects.
    """
    if not evaluator:
        return [], "and", None

    func_spec = evaluator.get("func", "exact_match")
    result_spec = evaluator.get("result", {})
    expected_spec = evaluator.get("expected", {})
    conj = evaluator.get("conj", "and")

    # Multi-metric evaluator (list of funcs)
    if isinstance(func_spec, list):
        results = result_spec if isinstance(result_spec, list) else [result_spec]
        expecteds = expected_spec if isinstance(expected_spec, list) else [expected_spec]

        # Check if ALL funcs are simple/known
        all_simple = all(fn in _KNOWN_SIMPLE_FUNCS for fn in func_spec)
        if not all_simple:
            return [], conj, evaluator

        checks = []
        for i, fn in enumerate(func_spec):
            r = results[i] if i < len(results) else {}
            e = expecteds[i] if i < len(expecteds) else {}
            check = _reverse_translate_single(fn, r, e)
            if check is None:
                # Fall back to raw evaluator
                return [], conj, evaluator
            checks.append(check)
        return checks, conj, None

    # Single-metric evaluator
    if func_spec not in _KNOWN_SIMPLE_FUNCS:
        return [], conj, evaluator

    check = _reverse_translate_single(func_spec, result_spec, expected_spec)
    if check is None:
        return [], conj, evaluator
    return [check], conj, None


def _reverse_translate_single(
    func: str,
    result_spec: dict[str, Any],
    expected_spec: dict[str, Any],
) -> TaskCheck | None:
    """Reverse-translate a single WAA metric to a TaskCheck.

    Returns None if the pattern is not recognised.
    """
    result_type = result_spec.get("type", "")
    expected_type = expected_spec.get("type", "")

    # WAA func name -> our match name
    match_name = {
        "exact_match": "exact",
        "contains": "contains",
        "fuzzy_match": "fuzzy",
        "regex_match": "regex",
    }.get(func, "exact")

    # Pattern: vm_command_line + literal -> "command" check
    if result_type == "vm_command_line" and expected_type == "literal":
        return TaskCheck(
            check="command",
            run=result_spec.get("command", ""),
            expect=expected_spec.get("value", ""),
            match=match_name,
        )

    # Pattern: vm_file + literal -> "file" check (contains or content match)
    if result_type == "vm_file" and expected_type == "literal":
        file_path = result_spec.get("path", "")
        expected_value = expected_spec.get("value", "")
        if func == "contains":
            return TaskCheck(
                check="file",
                path=file_path,
                contains=expected_value,
            )
        return TaskCheck(
            check="command",
            run=f'type "{file_path}"',
            expect=expected_value,
            match=match_name,
        )

    # Pattern: vm_command_line + no expected type -> command check
    if result_type == "vm_command_line" and not expected_type:
        return TaskCheck(
            check="command",
            run=result_spec.get("command", ""),
            expect=expected_spec.get("value", expected_spec.get("expected", "")),
            match=match_name,
        )

    return None
