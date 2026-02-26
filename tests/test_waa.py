"""Tests for WAA benchmark adapter."""

import pytest

from openadapt_evals import (
    BenchmarkAction,
    BenchmarkObservation,
    BenchmarkResult,
    BenchmarkTask,
    RandomAgent,
    ScriptedAgent,
    WAAMockAdapter,
    compute_metrics,
    evaluate_agent_on_benchmark,
)


class TestWAAMockAdapter:
    """Tests for WAAMockAdapter."""

    def test_list_tasks(self):
        """Test listing tasks."""
        adapter = WAAMockAdapter(num_tasks=10)
        tasks = adapter.list_tasks()
        assert len(tasks) == 10
        assert all(isinstance(t, BenchmarkTask) for t in tasks)

    def test_list_tasks_by_domain(self):
        """Test filtering tasks by domain."""
        adapter = WAAMockAdapter(num_tasks=10, domains=["browser", "notepad"])
        browser_tasks = adapter.list_tasks(domain="browser")
        assert len(browser_tasks) == 5
        assert all(t.domain == "browser" for t in browser_tasks)

    def test_load_task(self):
        """Test loading a specific task."""
        adapter = WAAMockAdapter(num_tasks=5, domains=["browser"])
        # Mock adapter uses "mock_{domain}_{number:03d}" format
        task = adapter.load_task("mock_browser_001")
        assert task.task_id == "mock_browser_001"
        assert task.domain == "browser"

    def test_load_task_not_found(self):
        """Test loading a non-existent task."""
        adapter = WAAMockAdapter(num_tasks=5)
        with pytest.raises(KeyError):
            adapter.load_task("nonexistent_task")

    def test_reset_returns_observation(self):
        """Test reset returns observation."""
        adapter = WAAMockAdapter(num_tasks=5)
        task = adapter.list_tasks()[0]
        obs = adapter.reset(task)
        assert isinstance(obs, BenchmarkObservation)
        assert obs.viewport is not None
        assert obs.accessibility_tree is not None

    def test_step_returns_observation_done_info(self):
        """Test step returns correct tuple."""
        adapter = WAAMockAdapter(num_tasks=5)
        task = adapter.list_tasks()[0]
        adapter.reset(task)

        action = BenchmarkAction(type="click", x=0.5, y=0.5)
        obs, done, info = adapter.step(action)

        assert isinstance(obs, BenchmarkObservation)
        assert isinstance(done, bool)
        assert isinstance(info, dict)

    def test_step_done_on_max_steps(self):
        """Test step returns done after max steps."""
        adapter = WAAMockAdapter(num_tasks=5)
        task = adapter.list_tasks()[0]
        adapter.reset(task)

        action = BenchmarkAction(type="click", x=0.5, y=0.5)
        for _ in range(14):
            obs, done, info = adapter.step(action)
            assert not done

        obs, done, info = adapter.step(action)
        assert done

    def test_step_done_on_done_action(self):
        """Test step returns done when action is 'done'."""
        adapter = WAAMockAdapter(num_tasks=5)
        task = adapter.list_tasks()[0]
        adapter.reset(task)

        action = BenchmarkAction(type="done")
        obs, done, info = adapter.step(action)
        assert done

    def test_evaluate_returns_result(self):
        """Test evaluate returns BenchmarkResult."""
        adapter = WAAMockAdapter(num_tasks=5)
        task = adapter.list_tasks()[0]
        adapter.reset(task)

        result = adapter.evaluate(task)
        assert isinstance(result, BenchmarkResult)
        assert result.task_id == task.task_id
        assert result.score in [0.0, 1.0]

    def test_benchmark_properties(self):
        """Test benchmark properties."""
        adapter = WAAMockAdapter()
        assert adapter.name == "waa-mock"
        assert adapter.benchmark_type == "interactive"


class TestEvaluationRunner:
    """Tests for evaluation runner with mock adapter."""

    def test_evaluate_with_random_agent(self):
        """Test running evaluation with RandomAgent."""
        adapter = WAAMockAdapter(num_tasks=5)
        agent = RandomAgent(seed=42)

        results = evaluate_agent_on_benchmark(agent, adapter, max_steps=10)

        assert len(results) == 5
        assert all(isinstance(r, BenchmarkResult) for r in results)

    def test_evaluate_specific_tasks(self):
        """Test evaluating specific tasks."""
        adapter = WAAMockAdapter(num_tasks=10, domains=["browser", "notepad"])
        agent = RandomAgent(seed=42)

        # Mock adapter uses "mock_{domain}_{number:03d}" format
        results = evaluate_agent_on_benchmark(
            agent, adapter, task_ids=["mock_browser_001", "mock_browser_002"], max_steps=10
        )

        assert len(results) == 2
        assert results[0].task_id == "mock_browser_001"
        assert results[1].task_id == "mock_browser_002"

    def test_evaluate_with_scripted_agent(self):
        """Test running evaluation with ScriptedAgent."""
        adapter = WAAMockAdapter(num_tasks=3)

        # Create script that clicks then says done
        actions = [
            BenchmarkAction(type="click", x=0.5, y=0.5),
            BenchmarkAction(type="type", text="hello"),
            BenchmarkAction(type="done"),
        ]
        agent = ScriptedAgent(actions=actions)

        results = evaluate_agent_on_benchmark(agent, adapter, max_steps=10)

        assert len(results) == 3


class TestComputeMetrics:
    """Tests for compute_metrics function."""

    def test_compute_metrics_empty(self):
        """Test metrics with empty results."""
        metrics = compute_metrics([])
        assert metrics["num_tasks"] == 0
        assert metrics["success_rate"] == 0.0

    def test_compute_metrics_all_success(self):
        """Test metrics with all successful tasks."""
        results = [
            BenchmarkResult(task_id=f"task_{i}", success=True, score=1.0, num_steps=5)
            for i in range(3)
        ]
        metrics = compute_metrics(results)
        assert metrics["num_tasks"] == 3
        assert metrics["success_rate"] == 1.0
        assert metrics["avg_score"] == 1.0

    def test_compute_metrics_all_fail(self):
        """Test metrics with all failed tasks."""
        results = [
            BenchmarkResult(task_id=f"task_{i}", success=False, score=0.0, num_steps=10)
            for i in range(3)
        ]
        metrics = compute_metrics(results)
        assert metrics["num_tasks"] == 3
        assert metrics["success_rate"] == 0.0
        assert metrics["avg_score"] == 0.0

    def test_compute_metrics_partial_success(self):
        """Test metrics with partial success."""
        results = [
            BenchmarkResult(task_id="task_1", success=True, score=1.0, num_steps=5),
            BenchmarkResult(task_id="task_2", success=False, score=0.0, num_steps=10),
            BenchmarkResult(task_id="task_3", success=True, score=1.0, num_steps=3),
            BenchmarkResult(task_id="task_4", success=False, score=0.0, num_steps=8),
        ]
        metrics = compute_metrics(results)
        assert metrics["num_tasks"] == 4
        assert metrics["success_rate"] == 0.5
        assert metrics["success_count"] == 2
        assert metrics["fail_count"] == 2


# ---------------------------------------------------------------------------
# XML Accessibility Tree Parsing
# ---------------------------------------------------------------------------


class TestParseXmlA11yTree:
    """Tests for _parse_xml_a11y_tree in the live adapter."""

    def test_basic_xml(self):
        from openadapt_evals.adapters.waa.live import _parse_xml_a11y_tree

        xml = (
            '<Window Name="Notepad" AutomationId="NotepadWindow"'
            ' BoundingRectangle="0,0,1920,1200">'
            '<Edit Name="Text Editor" AutomationId="15"'
            ' BoundingRectangle="0,40,1920,1170"/>'
            "</Window>"
        )
        result = _parse_xml_a11y_tree(xml)
        assert result is not None
        assert result["role"] == "Window"
        assert result["name"] == "Notepad"
        assert result["id"] == "NotepadWindow"
        assert result["BoundingRectangle"] == "0,0,1920,1200"
        assert len(result["children"]) == 1
        child = result["children"][0]
        assert child["role"] == "Edit"
        assert child["name"] == "Text Editor"
        assert child["id"] == "15"

    def test_nested_xml(self):
        from openadapt_evals.adapters.waa.live import _parse_xml_a11y_tree

        xml = (
            '<Window Name="App" AutomationId="app1">'
            '<Pane Name="Toolbar">'
            '<Button Name="Save" AutomationId="saveBtn"'
            ' BoundingRectangle="10,10,60,40"/>'
            '<Button Name="Open" AutomationId="openBtn"'
            ' BoundingRectangle="70,10,120,40"/>'
            "</Pane>"
            "</Window>"
        )
        result = _parse_xml_a11y_tree(xml)
        assert result["children"][0]["role"] == "Pane"
        buttons = result["children"][0]["children"]
        assert len(buttons) == 2
        assert buttons[0]["id"] == "saveBtn"
        assert buttons[1]["id"] == "openBtn"
        assert buttons[0]["BoundingRectangle"] == "10,10,60,40"

    def test_invalid_xml_returns_none(self):
        from openadapt_evals.adapters.waa.live import _parse_xml_a11y_tree

        result = _parse_xml_a11y_tree("not valid xml <><>")
        assert result is None

    def test_empty_string_returns_none(self):
        from openadapt_evals.adapters.waa.live import _parse_xml_a11y_tree

        result = _parse_xml_a11y_tree("")
        assert result is None

    def test_runtime_id_fallback(self):
        from openadapt_evals.adapters.waa.live import _parse_xml_a11y_tree

        xml = '<Button Name="OK" RuntimeId="42" BoundingRectangle="100,100,200,140"/>'
        result = _parse_xml_a11y_tree(xml)
        assert result["id"] == "42"

    def test_no_id_element(self):
        from openadapt_evals.adapters.waa.live import _parse_xml_a11y_tree

        xml = '<Pane Name="Content"/>'
        result = _parse_xml_a11y_tree(xml)
        assert result is not None
        # Name is used as fallback ID when AutomationId/RuntimeId are absent
        assert result["id"] == "Content"
        assert result["name"] == "Content"

    def test_atspi_format_parsing(self):
        """AT-SPI format with lowercase name and cp:screencoord/cp:size."""
        from openadapt_evals.adapters.waa.live import _parse_xml_a11y_tree

        xml = (
            '<desktop xmlns:cp="uri:deskat:component.at-spi.gnome.org"'
            ' xmlns:st="uri:deskat:state.at-spi.gnome.org">'
            '<togglebutton name="Start" st:enabled="true" st:visible="true"'
            ' cp:screencoord="(418, 672)" cp:size="(45, 48)"/>'
            '<togglebutton name="Search" st:enabled="true" st:visible="true"'
            ' cp:screencoord="(465, 680)" cp:size="(220, 32)"/>'
            '</desktop>'
        )
        result = _parse_xml_a11y_tree(xml)
        assert result is not None
        assert len(result["children"]) == 2
        start = result["children"][0]
        assert start["name"] == "Start"
        assert start["id"] == "Start"
        assert start["BoundingRectangle"] == "418,672,463,720"
        search = result["children"][1]
        assert search["name"] == "Search"
        assert search["id"] == "Search"
        assert search["BoundingRectangle"] == "465,680,685,712"

    def test_atspi_rect_extraction(self):
        """AT-SPI XML should produce usable rects for element grounding."""
        from openadapt_evals.adapters.waa.live import WAALiveAdapter, WAALiveConfig

        xml = (
            '<desktop xmlns:cp="uri:deskat:component.at-spi.gnome.org">'
            '<togglebutton name="Start"'
            ' cp:screencoord="(418, 672)" cp:size="(45, 48)"/>'
            '<togglebutton name="Search"'
            ' cp:screencoord="(465, 680)" cp:size="(220, 32)"/>'
            '</desktop>'
        )
        adapter = WAALiveAdapter.__new__(WAALiveAdapter)
        adapter.config = WAALiveConfig()
        adapter._current_rects = {}

        rects = adapter._extract_rects_from_a11y(xml)
        assert "Start" in rects
        assert rects["Start"] == [418, 672, 463, 720]
        assert "Search" in rects
        assert rects["Search"] == [465, 680, 685, 712]

    def test_xml_rect_extraction_integration(self):
        """XML a11y tree should produce usable rects via _extract_rects_from_a11y."""
        from openadapt_evals.adapters.waa.live import WAALiveAdapter, WAALiveConfig

        xml = (
            '<Window Name="App" AutomationId="win1" BoundingRectangle="0,0,1920,1200">'
            '<Button Name="Submit" AutomationId="submitBtn"'
            ' BoundingRectangle="400,100,500,140"/>'
            "</Window>"
        )
        # Create adapter (won't connect to server)
        adapter = WAALiveAdapter.__new__(WAALiveAdapter)
        adapter.config = WAALiveConfig()
        adapter._current_rects = {}

        rects = adapter._extract_rects_from_a11y(xml)
        assert "submitBtn" in rects
        # BoundingRectangle "400,100,500,140" → [400, 100, 500, 140]
        assert rects["submitBtn"] == [400, 100, 500, 140]
