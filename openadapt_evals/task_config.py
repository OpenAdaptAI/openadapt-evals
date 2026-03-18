"""YAML-based custom task configuration.

Lets users define tasks with setup commands and evaluation checks in
simple YAML files, without forking WAA or modifying the Docker image.
The WAA server already accepts evaluator configs in POST /evaluate —
this module translates YAML into that format.

Usage:
    from openadapt_evals.task_config import TaskConfig

    # Load a single task
    task = TaskConfig.from_yaml("tasks/change-font.yaml")
    benchmark_task = task.to_benchmark_task()

    # Load all tasks from a directory
    tasks = TaskConfig.from_dir("tasks/")
"""

from __future__ import annotations

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
    """A custom task definition loaded from YAML."""

    name: str
    id: str
    domain: str
    setup: list[dict[str, Any]]
    checks: list[TaskCheck]
    combine: str  # "and" | "or"
    max_steps: int
    milestones: list[Milestone]

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
            ms_name = item.pop("name", "milestone")
            milestones.append(Milestone(name=ms_name, check=TaskCheck(**item)))

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
    def from_dir(cls, dir_path: str) -> list[TaskConfig]:
        """Load all YAML task configs from a directory."""
        tasks = []
        for fname in sorted(os.listdir(dir_path)):
            if fname.endswith((".yaml", ".yml")):
                try:
                    tasks.append(cls.from_yaml(os.path.join(dir_path, fname)))
                except Exception as exc:
                    logger.warning("Skipping %s: %s", fname, exc)
        return tasks

    def to_waa_config(self) -> dict[str, Any]:
        """Translate to WAA's native JSON format for /evaluate."""
        config = {
            "task_id": self.id,
            "instruction": self.name,
            "config": self._translate_setup(),
        }

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
                "func": "file_exists",
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
        """Execute a command on the VM and return stdout."""
        import requests

        resp = requests.post(
            f"{server_url}/execute_windows",
            json={"command": f'python -c "{command}"'},
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
