"""Tests for custom YAML task configuration."""

from __future__ import annotations

import json
import os
import textwrap
from unittest.mock import MagicMock, patch

import pytest
import yaml

from openadapt_evals.task_config import Milestone, TaskCheck, TaskConfig


# ---------------------------------------------------------------------------
# YAML loading tests
# ---------------------------------------------------------------------------


class TestTaskConfigFromYaml:
    def test_minimal_yaml(self, tmp_path):
        config = tmp_path / "task.yaml"
        config.write_text(
            textwrap.dedent("""\
            name: "Open Notepad"
            evaluate:
              - check: screenshot
                description: "Notepad is open"
            """)
        )
        task = TaskConfig.from_yaml(str(config))
        assert task.name == "Open Notepad"
        assert task.id.startswith("custom-")
        assert task.domain == "desktop"
        assert task.max_steps == 15
        assert task.combine == "and"
        assert len(task.checks) == 1
        assert task.checks[0].check == "screenshot"

    def test_full_yaml(self, tmp_path):
        config = tmp_path / "task.yaml"
        config.write_text(
            textwrap.dedent("""\
            name: "Change font to Arial"
            id: custom-font-001
            domain: desktop
            max_steps: 20
            combine: or

            setup:
              - launch: "soffice --calc"
              - sleep: 3
              - execute: "powershell -c 'echo hello'"

            evaluate:
              - check: command
                run: "powershell -c 'echo Arial'"
                expect: "Arial"
                match: contains
              - check: file
                path: "C:\\\\test.txt"
                exists: true
              - check: screenshot
                description: "Font is Arial"

            milestones:
              - name: "App open"
                check: command
                run: "powershell -c 'Get-Process soffice | Measure | Select -Expand Count'"
                expect: "1"
                match: exact
            """)
        )
        task = TaskConfig.from_yaml(str(config))
        assert task.name == "Change font to Arial"
        assert task.id == "custom-font-001"
        assert task.domain == "desktop"
        assert task.max_steps == 20
        assert task.combine == "or"
        assert len(task.setup) == 3
        assert len(task.checks) == 3
        assert len(task.milestones) == 1
        assert task.milestones[0].name == "App open"

    def test_from_dir(self, tmp_path):
        for i in range(3):
            (tmp_path / f"task{i}.yaml").write_text(
                f"name: Task {i}\nevaluate:\n  - check: screenshot\n    description: ok"
            )
        (tmp_path / "readme.txt").write_text("not a yaml")

        tasks = TaskConfig.from_dir(str(tmp_path))
        assert len(tasks) == 3

    def test_from_dir_skips_invalid(self, tmp_path):
        (tmp_path / "good.yaml").write_text(
            "name: Good\nevaluate:\n  - check: screenshot\n    description: ok"
        )
        (tmp_path / "bad.yaml").write_text("not: valid: yaml: [[[")

        tasks = TaskConfig.from_dir(str(tmp_path))
        assert len(tasks) == 1


# ---------------------------------------------------------------------------
# WAA translation tests
# ---------------------------------------------------------------------------


class TestWaaTranslation:
    def _make_task(self, **kwargs) -> TaskConfig:
        defaults = {
            "name": "Test task",
            "id": "test-001",
            "domain": "desktop",
            "setup": [],
            "checks": [],
            "combine": "and",
            "max_steps": 15,
            "milestones": [],
        }
        defaults.update(kwargs)
        return TaskConfig(**defaults)

    def test_command_check_to_waa(self):
        task = self._make_task(
            checks=[
                TaskCheck(check="command", run="echo hello", expect="hello", match="exact")
            ]
        )
        waa = task.to_waa_config()
        evaluator = waa["evaluator"]
        assert evaluator["func"] == "exact_match"
        assert evaluator["result"]["type"] == "vm_command_line"
        assert evaluator["result"]["command"] == "echo hello"
        assert evaluator["expected"]["value"] == "hello"

    def test_contains_match(self):
        task = self._make_task(
            checks=[
                TaskCheck(check="command", run="echo hello world", expect="hello", match="contains")
            ]
        )
        evaluator = task.to_waa_config()["evaluator"]
        assert evaluator["func"] == "contains"

    def test_file_exists_check(self):
        task = self._make_task(
            checks=[
                TaskCheck(check="file", path="C:\\test.txt", exists=True)
            ]
        )
        evaluator = task.to_waa_config()["evaluator"]
        assert evaluator["func"] == "exact_match"
        assert "vm_command_line" in evaluator["result"]["type"]

    def test_file_contains_check(self):
        task = self._make_task(
            checks=[
                TaskCheck(check="file", path="C:\\test.txt", contains="expected content")
            ]
        )
        evaluator = task.to_waa_config()["evaluator"]
        assert evaluator["func"] == "contains"
        assert evaluator["result"]["type"] == "vm_file"

    def test_python_check(self):
        task = self._make_task(
            checks=[
                TaskCheck(check="python", code="print(1 + 1 == 2)")
            ]
        )
        evaluator = task.to_waa_config()["evaluator"]
        assert evaluator["func"] == "exact_match"
        assert evaluator["expected"]["value"] == "True"

    def test_screenshot_only_no_server_evaluator(self):
        task = self._make_task(
            checks=[
                TaskCheck(check="screenshot", description="Notepad is open")
            ]
        )
        waa = task.to_waa_config()
        assert "evaluator" not in waa

    def test_multiple_server_checks_use_conjunction(self):
        task = self._make_task(
            checks=[
                TaskCheck(check="command", run="echo a", expect="a"),
                TaskCheck(check="command", run="echo b", expect="b"),
            ],
            combine="and",
        )
        evaluator = task.to_waa_config()["evaluator"]
        assert isinstance(evaluator["func"], list)
        assert len(evaluator["func"]) == 2
        assert evaluator["conj"] == "and"

    def test_vlm_checks_separated(self):
        task = self._make_task(
            checks=[
                TaskCheck(check="command", run="echo ok", expect="ok"),
                TaskCheck(check="screenshot", description="Looks good"),
            ]
        )
        vlm_checks = task.get_vlm_checks()
        assert len(vlm_checks) == 1
        assert vlm_checks[0].description == "Looks good"

    def test_setup_translation(self):
        task = self._make_task(
            setup=[
                {"launch": "notepad.exe"},
                {"sleep": 2},
                {"download": {"url": "http://example.com/f.txt", "dest": "C:\\f.txt"}},
            ]
        )
        waa = task.to_waa_config()
        config = waa["config"]
        assert config[0]["type"] == "launch"
        assert config[1]["type"] == "sleep"
        assert config[2]["type"] == "download"


# ---------------------------------------------------------------------------
# BenchmarkTask conversion
# ---------------------------------------------------------------------------


class TestBenchmarkTaskConversion:
    def test_to_benchmark_task(self):
        task = TaskConfig(
            name="Test",
            id="test-001",
            domain="desktop",
            setup=[{"launch": "notepad.exe"}],
            checks=[TaskCheck(check="command", run="echo ok", expect="ok")],
            combine="and",
            max_steps=10,
            milestones=[],
        )
        bt = task.to_benchmark_task()
        assert bt.task_id == "test-001"
        assert bt.instruction == "Test"
        assert bt.domain == "desktop"
        assert bt.time_limit_steps == 10
        assert bt.evaluation_spec is not None


# ---------------------------------------------------------------------------
# Milestone evaluation
# ---------------------------------------------------------------------------


class TestMilestones:
    def test_milestone_command_check(self):
        task = TaskConfig(
            name="Test",
            id="test-001",
            domain="desktop",
            setup=[],
            checks=[],
            combine="and",
            max_steps=15,
            milestones=[
                Milestone(
                    name="App open",
                    check=TaskCheck(check="command", run="echo 1", expect="1", match="exact"),
                ),
                Milestone(
                    name="File saved",
                    check=TaskCheck(check="command", run="echo 0", expect="1", match="exact"),
                ),
            ],
        )

        with patch.object(TaskConfig, "_run_vm_command") as mock_cmd:
            mock_cmd.side_effect = ["1", "0"]
            passed, total = task.evaluate_milestones(b"fake-screenshot", "http://localhost:5001")

        assert total == 2
        assert passed == 1  # first matches, second doesn't

    @patch("openadapt_evals.vlm_evaluator.vlm_judge")
    def test_milestone_screenshot_check(self, mock_vlm):
        mock_vlm.return_value = (True, 0.95)

        task = TaskConfig(
            name="Test",
            id="test-001",
            domain="desktop",
            setup=[],
            checks=[],
            combine="and",
            max_steps=15,
            milestones=[
                Milestone(
                    name="App visible",
                    check=TaskCheck(check="screenshot", description="Notepad is open"),
                ),
            ],
        )

        passed, total = task.evaluate_milestones(b"fake-screenshot", "http://localhost:5001")
        assert total == 1
        assert passed == 1
        mock_vlm.assert_called_once()

    def test_no_milestones(self):
        task = TaskConfig(
            name="Test",
            id="test-001",
            domain="desktop",
            setup=[],
            checks=[],
            combine="and",
            max_steps=15,
            milestones=[],
        )
        passed, total = task.evaluate_milestones(b"fake", "http://localhost:5001")
        assert passed == 0
        assert total == 0


# ---------------------------------------------------------------------------
# VLM evaluator tests
# ---------------------------------------------------------------------------


class TestVlmEvaluator:
    @patch("openadapt_evals.vlm.vlm_call")
    def test_vlm_judge_yes(self, mock_vlm):
        mock_vlm.return_value = '{"verdict": "YES", "confidence": 0.95, "explanation": "Font is Arial"}'
        from openadapt_evals.vlm_evaluator import vlm_judge

        success, confidence = vlm_judge(b"fake-png", "Font is Arial")
        assert success is True
        assert confidence == 0.95

    @patch("openadapt_evals.vlm.vlm_call")
    def test_vlm_judge_no(self, mock_vlm):
        mock_vlm.return_value = '{"verdict": "NO", "confidence": 0.8, "explanation": "Font is Times"}'
        from openadapt_evals.vlm_evaluator import vlm_judge

        success, confidence = vlm_judge(b"fake-png", "Font is Arial")
        assert success is False
        assert confidence == 0.8

    @patch("openadapt_evals.vlm.vlm_call")
    def test_vlm_judge_bad_json_fallback(self, mock_vlm):
        mock_vlm.return_value = "YES, the font looks like Arial to me."
        from openadapt_evals.vlm_evaluator import vlm_judge

        success, confidence = vlm_judge(b"fake-png", "Font is Arial")
        assert success is True
        assert confidence == 0.5  # fallback confidence

    @patch("openadapt_evals.vlm.vlm_call")
    def test_vlm_judge_no_fallback(self, mock_vlm):
        mock_vlm.return_value = "NO, I don't see that."
        from openadapt_evals.vlm_evaluator import vlm_judge

        success, confidence = vlm_judge(b"fake-png", "Font is Arial")
        assert success is False


# ---------------------------------------------------------------------------
# Example YAML files load correctly
# ---------------------------------------------------------------------------


class TestExampleTasks:
    def test_load_example_tasks(self):
        example_dir = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "example_tasks"
        )
        if not os.path.isdir(example_dir):
            pytest.skip("example_tasks/ not found")

        tasks = TaskConfig.from_dir(example_dir)
        assert len(tasks) >= 1
        for task in tasks:
            assert task.name
            assert task.id
            bt = task.to_benchmark_task()
            assert bt.task_id == task.id
