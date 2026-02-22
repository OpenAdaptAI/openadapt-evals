"""Windows Agent Arena Live adapter.

This module provides a live HTTP-based adapter for WAA that connects to the
WAA Flask server running inside a Windows VM. Unlike WAAAdapter which imports
WAA's DesktopEnv locally, this adapter talks to the server remotely.

Architecture:
    The adapter uses WAA's element-based execution model:
    1. Fetch accessibility tree from /accessibility endpoint
    2. Extract element bboxes and POST to /update_computer as rects dict
    3. Agent outputs actions with target_node_id (element-based grounding)
    4. Execute via /execute_windows using computer.mouse.move_id(id) commands

    This keeps grounding authority on WAA side - we send element IDs,
    not pixel coordinates. WAA's Computer class handles the grounding.

Example:
    from openadapt_evals.adapters.waa import WAALiveAdapter, WAALiveConfig

    adapter = WAALiveAdapter(WAALiveConfig(server_url="http://vm-ip:5000"))
    agent = DemoConditionedAgent(base_agent, retriever)
    results = evaluate_agent_on_benchmark(agent, adapter, max_steps=15)
"""

from __future__ import annotations

import base64
import logging
import re
import time
from dataclasses import dataclass
from typing import Any

from openadapt_evals.adapters.base import (
    BenchmarkAction,
    BenchmarkAdapter,
    BenchmarkObservation,
    BenchmarkResult,
    BenchmarkTask,
)

logger = logging.getLogger(__name__)


# WAA task IDs are UUIDs with a domain suffix, e.g., "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx-WOS"
# Common suffixes: WOS (Windows OS), CHR (Chrome), NTP (Notepad), etc.
WAA_TASK_ID_PATTERN = re.compile(
    r'^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}(-[A-Za-z0-9]+)?$'
)

# Synthetic task ID patterns (from mock adapter or testing)
SYNTHETIC_TASK_PATTERNS = [
    re.compile(r'^(mock_)?[a-z_]+_\d+$'),  # notepad_1, mock_chrome_001
    re.compile(r'^mock_'),  # any mock_ prefix
]


def is_real_waa_task_id(task_id: str) -> bool:
    """Check if a task ID matches the real WAA UUID format.

    Real WAA task IDs are UUIDs from test_small.json or test_all.json, e.g.:
    - "a1b2c3d4-e5f6-7890-abcd-ef1234567890-WOS"
    - "12345678-1234-1234-1234-123456789012-CHR"

    Synthetic task IDs are simple patterns like:
    - "notepad_1", "chrome_2" (from mock adapter)
    - "mock_notepad_001" (explicit mock prefix)

    Args:
        task_id: Task identifier to check.

    Returns:
        True if the task ID appears to be a real WAA UUID.
    """
    return bool(WAA_TASK_ID_PATTERN.match(task_id))


def is_synthetic_task_id(task_id: str) -> bool:
    """Check if a task ID appears to be synthetic (for testing).

    Args:
        task_id: Task identifier to check.

    Returns:
        True if the task ID matches synthetic patterns.
    """
    for pattern in SYNTHETIC_TASK_PATTERNS:
        if pattern.match(task_id):
            return True
    return False


class SyntheticTaskError(ValueError):
    """Raised when a synthetic task ID is used with the live adapter."""

    def __init__(self, task_id: str):
        self.task_id = task_id
        super().__init__(
            f"Task ID '{task_id}' appears to be synthetic (for testing). "
            f"The live adapter requires real WAA task IDs (UUIDs from test_small.json or test_all.json). "
            f"\n\nTo fix this:"
            f"\n  1. Use --mock flag for testing without a Windows VM"
            f"\n  2. Or provide real WAA task IDs with --task-ids"
            f"\n  3. Or use --tasks N to select N random real tasks"
            f"\n\nExample real task ID: 'a1b2c3d4-e5f6-7890-abcd-ef1234567890-WOS'"
        )


@dataclass
class WAALiveConfig:
    """Configuration for WAALiveAdapter.

    Attributes:
        server_url: URL of WAA Flask server (e.g., "http://172.171.112.41:5000").
        evaluate_url: URL of evaluate server (e.g., "http://localhost:5050").
            If None, defaults to server_url. The evaluate server runs on the
            Docker Linux side (port 5050) and has access to WAA evaluator modules.
        a11y_backend: Accessibility backend ("uia" or "win32").
        screen_width: Screen width in pixels.
        screen_height: Screen height in pixels.
        max_steps: Default maximum steps per task.
        action_delay: Delay after actions in seconds (for UI to settle).
        timeout: Request timeout in seconds.
        waa_examples_path: Path to WAA evaluation_examples_windows directory
            for loading task configs with evaluator specs. If not set, tasks
            are loaded from server or created as minimal placeholders.
    """

    server_url: str = "http://localhost:5000"
    evaluate_url: str | None = None
    a11y_backend: str = "uia"
    screen_width: int = 1920
    screen_height: int = 1200
    max_steps: int = 15
    action_delay: float = 0.5
    timeout: float = 90.0
    waa_examples_path: str | None = None


class WAALiveAdapter(BenchmarkAdapter):
    """Live WAA adapter that connects to WAA Flask server over HTTP.

    Unlike WAAAdapter which imports WAA's DesktopEnv locally, this adapter
    talks to the WAA server remotely via HTTP. This enables:
    - Running DemoConditionedAgent from local machine
    - Using our own VLM (Claude/GPT) instead of WAA's built-in navi agent
    - Injecting demos into prompts before each action

    Args:
        config: WAALiveConfig with server URL and settings.
    """

    def __init__(self, config: WAALiveConfig | None = None):
        self.config = config or WAALiveConfig()
        self._current_task: BenchmarkTask | None = None
        self._step_count = 0
        self._current_a11y: dict | None = None
        self._current_rects: dict[str, list[int]] = {}  # element_id -> [l, t, r, b]
        self._current_screenshot: bytes | None = None
        self._actions: list[BenchmarkAction] = []
        self._actual_screen_size: tuple[int, int] | None = None

    @property
    def name(self) -> str:
        """Benchmark name."""
        return "waa-live"

    @property
    def benchmark_type(self) -> str:
        """Benchmark type (interactive)."""
        return "interactive"

    @property
    def supports_parallel(self) -> bool:
        """Whether parallel execution is supported."""
        return False  # Single VM for now

    def check_connection(self) -> bool:
        """Check if WAA server is reachable.

        Returns:
            True if server responds to /probe endpoint.
        """
        try:
            import requests
            resp = requests.get(
                f"{self.config.server_url}/probe",
                timeout=5.0
            )
            return resp.status_code == 200
        except Exception:
            return False

    def list_tasks(self, domain: str | None = None) -> list[BenchmarkTask]:
        """List available WAA tasks.

        For live adapter, tasks are typically loaded on-demand.
        Returns empty list - use load_task() directly.
        """
        return []

    def load_task(self, task_id: str) -> BenchmarkTask:
        """Load a specific task by ID.

        Attempts to load the full task config with evaluator specification
        from multiple sources:
        1. WAA server's /task/<task_id> endpoint (if available)
        2. Local WAA examples directory (if waa_examples_path is set)
        3. Creates minimal task as fallback

        Args:
            task_id: Task identifier. Must be a real WAA UUID
                (e.g., "a1b2c3d4-e5f6-7890-abcd-ef1234567890-WOS").

        Returns:
            BenchmarkTask object with evaluator config if available.

        Raises:
            SyntheticTaskError: If task_id appears to be synthetic (e.g., "notepad_1").
                Use WAAMockAdapter for synthetic/testing tasks.
        """
        # Validate that this is a real WAA task ID, not a synthetic one
        if is_synthetic_task_id(task_id):
            raise SyntheticTaskError(task_id)

        import requests

        # Try to load from evaluate server first (has /task/<id> endpoint
        # that reads task configs from WAA's evaluation_examples_windows/)
        evaluate_base = self.config.evaluate_url or self.config.server_url
        for base_url in [evaluate_base, self.config.server_url]:
            try:
                resp = requests.get(
                    f"{base_url}/task/{task_id}",
                    timeout=10.0,
                )
                if resp.status_code == 200:
                    config = resp.json()
                    return self._create_task_from_config(task_id, config)
            except Exception:
                continue

        # Try to load from local WAA examples directory
        if hasattr(self.config, "waa_examples_path") and self.config.waa_examples_path:
            task = self._load_task_from_disk(task_id, self.config.waa_examples_path)
            if task:
                return task

        # Fallback: create minimal task
        logger.warning(
            f"Could not load full task config for {task_id}. "
            "Evaluation will use fallback heuristics. "
            "Set waa_examples_path or deploy /task endpoint for proper evaluation."
        )
        return BenchmarkTask(
            task_id=task_id,
            instruction=f"Task {task_id}",
            domain=task_id.split("_")[0] if "_" in task_id else "unknown",
            time_limit_steps=self.config.max_steps,
        )

    def load_task_from_json(self, task_id: str, config: dict) -> BenchmarkTask:
        """Load a task from a JSON config dict.

        Use this to pass in task configs directly without server/disk lookup.

        Args:
            task_id: Task identifier.
            config: Full task configuration including evaluator spec.

        Returns:
            BenchmarkTask with evaluator config.
        """
        return self._create_task_from_config(task_id, config)

    def _create_task_from_config(self, task_id: str, config: dict) -> BenchmarkTask:
        """Create BenchmarkTask from WAA JSON config.

        Args:
            task_id: Task identifier.
            config: WAA task configuration dict.

        Returns:
            BenchmarkTask with raw_config containing evaluator spec.
        """
        # Parse domain from task_id if not in config
        domain = config.get("domain")
        if not domain:
            domain = task_id.split("_")[0] if "_" in task_id else "unknown"

        return BenchmarkTask(
            task_id=task_id,
            instruction=config.get("instruction", config.get("task", f"Task {task_id}")),
            domain=domain,
            initial_state_ref=config.get("snapshot"),
            time_limit_steps=config.get("max_steps", self.config.max_steps),
            raw_config=config,  # Includes evaluator spec
            evaluation_spec=config.get("evaluator"),
        )

    def _load_task_from_disk(self, task_id: str, base_path: str) -> BenchmarkTask | None:
        """Load task from WAA examples directory on disk.

        Args:
            task_id: Task identifier (e.g., "notepad_1" or "notepad_abc123-def").
            base_path: Path to WAA evaluation_examples_windows directory.

        Returns:
            BenchmarkTask or None if not found.
        """
        import json
        from pathlib import Path

        base = Path(base_path)

        # Parse task_id to get domain and task file name
        # Format: domain_taskname or domain_uuid
        parts = task_id.split("_", 1)
        if len(parts) < 2:
            return None

        domain = parts[0]
        task_name = parts[1]

        # Try different file locations
        candidates = [
            base / "examples" / domain / f"{task_name}.json",
            base / domain / f"{task_name}.json",
            base / "examples" / domain / f"{task_id}.json",
        ]

        for task_file in candidates:
            if task_file.exists():
                try:
                    with open(task_file, encoding="utf-8") as f:
                        config = json.load(f)
                    logger.info(f"Loaded task config from {task_file}")
                    return self._create_task_from_config(task_id, config)
                except Exception as e:
                    logger.warning(f"Failed to load {task_file}: {e}")

        return None

    def reset(self, task: BenchmarkTask) -> BenchmarkObservation:
        """Reset environment to task's initial state.

        Args:
            task: Task to initialize.

        Returns:
            Initial observation (screenshot + accessibility tree).

        Raises:
            RuntimeError: If server is not reachable.
        """
        if not self.check_connection():
            raise RuntimeError(
                f"Cannot connect to WAA server at {self.config.server_url}. "
                f"Ensure Windows VM is running and server is started."
            )

        self._current_task = task
        self._step_count = 0
        self._actions = []

        import requests

        # Try to close all windows for clean state
        try:
            requests.post(
                f"{self.config.server_url}/setup/close_all",
                timeout=30.0
            )
            logger.info("Closed all windows for clean state")
        except Exception as e:
            logger.warning(f"Failed to close windows: {e}")

        # If task has setup commands in raw_config, execute them
        if task.raw_config:
            self._run_task_setup(task.raw_config)

        # Delay for UI to settle after setup (WAA uses 5s)
        time.sleep(5.0)

        return self._get_observation()

    def step(
        self, action: BenchmarkAction
    ) -> tuple[BenchmarkObservation, bool, dict[str, Any]]:
        """Execute action and return new observation.

        Uses element-based grounding via WAA's Computer class. Click actions
        are translated to computer.mouse.move_id(id) commands that WAA executes
        using the rects we POSTed to /update_computer.

        Args:
            action: Action to execute.

        Returns:
            Tuple of (observation, done, info).
        """
        import requests

        self._step_count += 1
        self._actions.append(action)

        # Translate action to element-based command for WAA's Computer
        command = self._translate_action(action)

        # Execute command via /execute_windows (has access to computer object)
        if command:
            try:
                resp = requests.post(
                    f"{self.config.server_url}/execute_windows",
                    json={"command": command},
                    timeout=self.config.timeout
                )
                if resp.status_code != 200:
                    logger.error(f"Execute failed ({resp.status_code}): {resp.text}")
                else:
                    result = resp.json()
                    if result.get("stderr"):
                        logger.warning(f"Command stderr: {result['stderr']}")
                    logger.debug(f"Executed: {command}")
            except Exception as e:
                logger.error(f"Execute request failed: {e}")

        # Wait for UI to settle
        time.sleep(self.config.action_delay)

        # Check if done
        done = (
            action.type == "done" or
            self._step_count >= self.config.max_steps
        )

        obs = self._get_observation()
        info = {
            "step": self._step_count,
            "command": command,
        }

        return obs, done, info

    def evaluate(self, task: BenchmarkTask) -> BenchmarkResult:
        """Evaluate current state against task success criteria.

        Calls the /evaluate endpoint on the WAA server which runs WAA's
        native evaluators (getters + metrics) to determine task success.

        If the task has an evaluator config in raw_config, it's sent to
        the server. If the /evaluate endpoint is not available, falls back
        to a simple heuristic based on actions taken.

        Args:
            task: Task to evaluate.

        Returns:
            BenchmarkResult with success/score.
        """
        import requests

        # Build evaluation request
        eval_request = {}

        # Include evaluator config from task if available
        if task.raw_config:
            eval_request = task.raw_config.copy()

        # Add agent's last action for infeasible task detection
        if self._actions:
            last_action = self._actions[-1]
            if last_action.type == "done":
                eval_request["agent_last_action"] = "DONE"
            elif last_action.answer:
                eval_request["agent_last_action"] = last_action.answer

        # Determine evaluate URL: prefer dedicated evaluate server (port 5050),
        # fall back to WAA server's /evaluate endpoint
        evaluate_base = self.config.evaluate_url or self.config.server_url
        evaluate_endpoint = f"{evaluate_base}/evaluate"

        # Try the /evaluate endpoint
        try:
            resp = requests.post(
                evaluate_endpoint,
                json=eval_request,
                timeout=self.config.timeout,
            )

            if resp.status_code == 200:
                result = resp.json()
                return BenchmarkResult(
                    task_id=task.task_id,
                    success=result.get("success", False),
                    score=result.get("score", 0.0),
                    num_steps=self._step_count,
                    reason=result.get("reason"),
                )

            elif resp.status_code == 404 or (
                resp.status_code == 500 and "404 Not Found" in resp.text
            ):
                logger.warning(
                    f"/evaluate endpoint not found at {evaluate_endpoint}. "
                    "Ensure the evaluate server is running on port 5050."
                )
                return self._evaluate_fallback(task)

            else:
                logger.error(
                    f"Evaluation request failed ({resp.status_code}): {resp.text}"
                )
                return BenchmarkResult(
                    task_id=task.task_id,
                    success=False,
                    score=0.0,
                    num_steps=self._step_count,
                    reason=f"Evaluation failed: HTTP {resp.status_code}",
                )

        except requests.Timeout:
            logger.error("Evaluation request timed out")
            return BenchmarkResult(
                task_id=task.task_id,
                success=False,
                score=0.0,
                num_steps=self._step_count,
                reason="Evaluation timed out",
            )

        except requests.RequestException as e:
            logger.error(f"Evaluation request error: {e}")
            return self._evaluate_fallback(task)

    def _evaluate_fallback(self, task: BenchmarkTask) -> BenchmarkResult:
        """Fallback when proper evaluation unavailable - returns failure.

        This method explicitly fails instead of providing fake heuristic scores.
        Proper evaluation requires either:
        1. WAA server with /evaluate endpoint deployed
        2. Task configs with evaluator specs (set waa_examples_path)
        3. Real WAA task IDs (UUIDs from test_small.json/test_all.json)

        Args:
            task: Task to evaluate.

        Returns:
            BenchmarkResult with success=False and score=0.0.
        """
        # Check if task has evaluator config
        has_evaluator = bool(
            task.raw_config and task.raw_config.get("evaluator")
        )

        if has_evaluator:
            reason = (
                "Evaluation unavailable: WAA /evaluate endpoint not deployed. "
                "Task has evaluator config but server cannot run it."
            )
        else:
            reason = (
                "Evaluation unavailable: task config missing evaluator spec. "
                "Set waa_examples_path in config or use real WAA task IDs "
                "(UUIDs from test_small.json/test_all.json, not synthetic IDs like 'notepad_1')."
            )

        logger.error(reason)

        return BenchmarkResult(
            task_id=task.task_id,
            success=False,
            score=0.0,
            num_steps=self._step_count,
            reason=reason,
        )

    def close(self) -> None:
        """Clean up resources."""
        self._current_task = None
        self._current_a11y = None
        self._actions = []

    def _get_observation(self) -> BenchmarkObservation:
        """Fetch current observation from WAA server.

        Also extracts element rects from a11y tree and updates WAA's Computer
        so element-based grounding works for subsequent actions.

        Returns:
            BenchmarkObservation with screenshot and accessibility tree.
        """
        import requests

        screenshot = None
        a11y_tree = None

        # Get screenshot
        try:
            resp = requests.get(
                f"{self.config.server_url}/screenshot",
                timeout=30.0
            )
            if resp.status_code == 200:
                screenshot = resp.content
                self._current_screenshot = screenshot
                # Detect actual screen dimensions from screenshot
                try:
                    from io import BytesIO
                    from PIL import Image
                    img = Image.open(BytesIO(screenshot))
                    self._actual_screen_size = img.size
                except Exception:
                    pass
                logger.debug(f"Got screenshot: {len(screenshot)} bytes")
            else:
                logger.warning(f"Screenshot request failed: {resp.status_code}")
        except Exception as e:
            logger.error(f"Screenshot request error: {e}")

        # Get accessibility tree
        try:
            resp = requests.get(
                f"{self.config.server_url}/accessibility",
                params={"backend": self.config.a11y_backend},
                timeout=30.0
            )
            if resp.status_code == 200:
                result = resp.json()
                # Handle both dict response with "AT" key and direct string/dict response
                if isinstance(result, dict):
                    a11y_tree = result.get("AT", result)  # Use "AT" if present, else use whole dict
                else:
                    a11y_tree = result  # String (XML) or other format
                self._current_a11y = a11y_tree
                # Extract rects for element-based grounding
                self._current_rects = self._extract_rects_from_a11y(a11y_tree)
                logger.debug("Got accessibility tree with %d elements", len(self._current_rects))
            else:
                logger.warning(f"A11y request failed: {resp.status_code}")
        except Exception as e:
            logger.error(f"A11y request error: {e}")

        # Update WAA's Computer with current rects for element grounding
        if self._current_rects:
            self._update_waa_computer()

        return BenchmarkObservation(
            screenshot=screenshot,
            viewport=self._actual_screen_size or (self.config.screen_width, self.config.screen_height),
            accessibility_tree=a11y_tree,
            window_title=self._extract_window_title(a11y_tree),
        )

    def _extract_window_title(self, a11y_tree: dict | str | None) -> str | None:
        """Extract window title from accessibility tree."""
        if not a11y_tree:
            return None
        # Handle XML string - can't extract title easily
        if isinstance(a11y_tree, str):
            return None
        # Try common field names
        for key in ["Name", "name", "title", "Title"]:
            if key in a11y_tree:
                return a11y_tree[key]
        return None

    def _extract_rects_from_a11y(self, a11y_tree: dict | None) -> dict[str, list[int]]:
        """Extract element ID -> bounding box mapping from accessibility tree.

        This produces the `rects` dict that WAA's Computer class expects.
        The rects are then POSTed to /update_computer so WAA can handle grounding.

        Args:
            a11y_tree: Accessibility tree from /accessibility endpoint.

        Returns:
            Dict mapping element IDs to [left, top, right, bottom] bounding boxes.
        """
        rects: dict[str, list[int]] = {}

        def visit(node: dict) -> None:
            # Get element ID
            elem_id = None
            for id_field in ["id", "Id", "ID", "AutomationId"]:
                if id_field in node and node[id_field]:
                    elem_id = str(node[id_field])
                    break

            # Get bounding box
            bbox = None
            for bbox_field in ["bbox", "BoundingRectangle", "Rect", "rect"]:
                if bbox_field in node:
                    bbox = node[bbox_field]
                    break

            # Store if we have both ID and bbox
            if elem_id is not None and bbox is not None:
                # Normalize bbox to [left, top, right, bottom]
                if isinstance(bbox, list) and len(bbox) == 4:
                    # Could be [l, t, r, b] or [l, t, w, h] - assume [l, t, r, b]
                    rects[elem_id] = [int(x) for x in bbox]
                elif isinstance(bbox, dict):
                    x = bbox.get("x", 0)
                    y = bbox.get("y", 0)
                    w = bbox.get("width", 0)
                    h = bbox.get("height", 0)
                    rects[elem_id] = [x, y, x + w, y + h]
                elif isinstance(bbox, str):
                    parts = [int(p) for p in bbox.split(",")]
                    if len(parts) == 4:
                        rects[elem_id] = parts

            # Visit children
            for child_field in ["children", "Children"]:
                children = node.get(child_field, [])
                if isinstance(children, list):
                    for child in children:
                        if isinstance(child, dict):
                            visit(child)

        if a11y_tree:
            # Handle case where a11y_tree is XML string (WAA returns XML)
            if isinstance(a11y_tree, str):
                # TODO: Parse XML to dict if needed for element grounding
                logger.debug("A11y tree is XML string, skipping rect extraction")
                return rects
            visit(a11y_tree)

        logger.debug(f"Extracted {len(rects)} element rects from a11y tree")
        return rects

    def _update_waa_computer(self) -> None:
        """POST current rects and screenshot to WAA's /update_computer endpoint.

        This syncs WAA's Computer object with our current element state,
        allowing computer.mouse.move_id(id) to work correctly.
        """
        import requests

        if not self._current_rects:
            logger.warning("No rects to update - skipping /update_computer")
            return

        # Encode screenshot as base64
        screenshot_b64 = ""
        if self._current_screenshot:
            screenshot_b64 = base64.b64encode(self._current_screenshot).decode("utf-8")

        # Window rect (full screen for now)
        screen_w, screen_h = self._actual_screen_size or (self.config.screen_width, self.config.screen_height)
        window_rect = [0, 0, screen_w, screen_h]

        payload = {
            "rects": self._current_rects,
            "window_rect": window_rect,
            "screenshot": screenshot_b64,
            "scale": [1.0, 1.0],
        }

        try:
            resp = requests.post(
                f"{self.config.server_url}/update_computer",
                json=payload,
                timeout=30.0
            )
            if resp.status_code == 200:
                logger.debug("Updated WAA computer with %d rects", len(self._current_rects))
            else:
                logger.warning(f"update_computer failed: {resp.status_code} - {resp.text}")
        except Exception as e:
            logger.error(f"update_computer request error: {e}")

    def _run_task_setup(self, raw_config: dict) -> None:
        """Run task setup commands from raw_config.

        WAA tasks use a 'config' array of {type, parameters} objects specifying
        preconditions (file downloads, app launches, sleeps). We POST this array
        to the evaluate server's /setup endpoint which processes each entry.

        Args:
            raw_config: Task configuration with setup commands.
        """
        config = raw_config.get("config", [])
        if not config:
            return

        import requests

        evaluate_base = self.config.evaluate_url or self.config.server_url
        try:
            resp = requests.post(
                f"{evaluate_base}/setup",
                json={"config": config},
                timeout=120.0,
            )
            if resp.status_code == 200:
                results = resp.json().get("results", [])
                for r in results:
                    status = r.get("status", "unknown")
                    logger.info(f"Setup {r.get('type')}: {status}")
            else:
                logger.error(
                    f"Setup failed: {resp.status_code} {resp.text[:200]}"
                )
        except Exception as e:
            logger.error(f"Setup request failed: {e}")

    def _translate_action(self, action: BenchmarkAction) -> str | None:
        """Translate BenchmarkAction to element-based command for WAA's Computer.

        Uses WAA's Computer class via /execute_windows endpoint. Click actions
        use computer.mouse.move_id(id) for element-based grounding - the actual
        coordinates are resolved by WAA's Computer class using the rects we
        POSTed to /update_computer.

        Args:
            action: The action to translate.

        Returns:
            Python command string to execute via /execute_windows endpoint,
            or None for actions that don't need execution.
        """
        if action.type == "done":
            return None

        if action.type == "wait":
            return "import time; time.sleep(1)"

        if action.type == "click":
            return self._translate_click_action(action, "single_click")

        if action.type == "double_click":
            return self._translate_click_action(action, "double_click")

        if action.type == "right_click":
            return self._translate_click_action(action, "right_click")

        if action.type == "type":
            text = action.text or ""
            # Escape special characters
            text = text.replace("\\", "\\\\").replace("'", "\\'")
            # Use pyautogui for typing (no grounding needed)
            return f"import pyautogui; pyautogui.write('{text}', interval=0.02)"

        if action.type == "key":
            return self._translate_key_action(action)

        if action.type == "scroll":
            direction = action.scroll_direction or "down"
            # pyautogui.scroll(clicks) - positive is up, negative is down
            clicks = 3 if direction == "up" else -3
            return f"import pyautogui; pyautogui.scroll({clicks})"

        if action.type == "drag":
            # Get start position
            start_x, start_y = 0, 0
            if action.target_node_id is not None:
                elem_id = str(action.target_node_id)
                if elem_id in self._current_rects:
                    rect = self._current_rects[elem_id]
                    start_x = (rect[0] + rect[2]) // 2
                    start_y = (rect[1] + rect[3]) // 2
            elif action.x is not None and action.y is not None:
                screen_w, screen_h = self._actual_screen_size or (self.config.screen_width, self.config.screen_height)
                start_x = action.x if not isinstance(action.x, float) or action.x > 1 else int(action.x * screen_w)
                start_y = action.y if not isinstance(action.y, float) or action.y > 1 else int(action.y * screen_h)

            # Get end position
            screen_w, screen_h = self._actual_screen_size or (self.config.screen_width, self.config.screen_height)
            end_x = action.end_x or 0
            end_y = action.end_y or 0
            if isinstance(end_x, float) and 0 <= end_x <= 1:
                end_x = int(end_x * screen_w)
            if isinstance(end_y, float) and 0 <= end_y <= 1:
                end_y = int(end_y * screen_h)

            return f"import pyautogui; pyautogui.moveTo({int(start_x)}, {int(start_y)}); pyautogui.drag({int(end_x - start_x)}, {int(end_y - start_y)}, duration=0.5)"

        logger.warning(f"Unknown action type: {action.type}")
        return None

    def _translate_click_action(self, action: BenchmarkAction, click_method: str) -> str:
        """Translate click-type action to pyautogui command.

        Args:
            action: The click action.
            click_method: "single_click", "double_click", or "right_click".

        Returns:
            Python command string using pyautogui for direct control.
        """
        # Map click method to pyautogui function
        pyautogui_method = {
            "single_click": "click",
            "double_click": "doubleClick",
            "right_click": "rightClick",
        }.get(click_method, "click")

        # Prefer element ID for grounding (SoM mode)
        if action.target_node_id is not None:
            elem_id = str(action.target_node_id)
            if elem_id in self._current_rects:
                # Get center of element bounding box
                rect = self._current_rects[elem_id]
                cx = (rect[0] + rect[2]) // 2
                cy = (rect[1] + rect[3]) // 2
                return f"import pyautogui; pyautogui.{pyautogui_method}({cx}, {cy})"
            else:
                logger.warning(f"Element ID '{elem_id}' not found in rects, falling back to coordinates")

        # Fallback: use coordinates if provided
        x = action.x if action.x is not None else 0
        y = action.y if action.y is not None else 0

        # Convert normalized coordinates to pixels
        screen_w, screen_h = self._actual_screen_size or (self.config.screen_width, self.config.screen_height)
        if isinstance(x, float) and 0 <= x <= 1:
            x = int(x * screen_w)
        if isinstance(y, float) and 0 <= y <= 1:
            y = int(y * screen_h)

        return f"import pyautogui; pyautogui.{pyautogui_method}({int(x)}, {int(y)})"

    def _translate_key_action(self, action: BenchmarkAction) -> str:
        """Translate key press action using pyautogui (no grounding needed)."""
        key = action.key or ""

        # Map common key names to pyautogui names
        key_map = {
            "Enter": "enter",
            "Return": "enter",
            "Tab": "tab",
            "Escape": "escape",
            "Esc": "escape",
            "Backspace": "backspace",
            "Delete": "delete",
            "Del": "delete",
            "Space": "space",
            "Up": "up",
            "Down": "down",
            "Left": "left",
            "Right": "right",
            "Home": "home",
            "End": "end",
            "PageUp": "pageup",
            "PageDown": "pagedown",
            "F1": "f1", "F2": "f2", "F3": "f3", "F4": "f4",
            "F5": "f5", "F6": "f6", "F7": "f7", "F8": "f8",
            "F9": "f9", "F10": "f10", "F11": "f11", "F12": "f12",
        }
        key = key_map.get(key, key.lower())

        # Handle modifiers with hotkey
        if action.modifiers:
            mods = [m.lower() for m in action.modifiers]
            mod_map = {"control": "ctrl", "command": "win", "meta": "win"}
            mods = [mod_map.get(m, m) for m in mods]
            all_keys = mods + [key]
            keys_str = ", ".join(f"'{k}'" for k in all_keys)
            return f"import pyautogui; pyautogui.hotkey({keys_str})"

        return f"import pyautogui; pyautogui.press('{key}')"
