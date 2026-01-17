"""WAA /evaluate endpoint implementation.

This module provides the /evaluate endpoint for the Windows Agent Arena Flask server.
It calls WAA's existing evaluator logic (getters and metrics) to determine task success.

Deployment:
    This code should be added to or imported by the WAA server's main.py file.
    The WAA server runs inside the Windows VM at:
    WindowsAgentArena/src/win-arena-container/vm/setup/server/main.py

Usage (on WAA server):
    from openadapt_evals.server.evaluate_endpoint import create_evaluate_blueprint

    # Register the blueprint
    evaluate_bp = create_evaluate_blueprint(evaluators_path="/path/to/evaluators")
    app.register_blueprint(evaluate_bp)

    # Or import and call directly
    from openadapt_evals.server.evaluate_endpoint import evaluate_task_state
    result = evaluate_task_state(task_config, vm_env)

See also:
    - docs/research/waa-evaluator-integration.md for full documentation
    - WindowsAgentArena/src/win-arena-container/client/desktop_env/evaluators/
"""

from __future__ import annotations

import json
import logging
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

# Try to import Flask for blueprint creation
try:
    from flask import Blueprint, jsonify, request

    FLASK_AVAILABLE = True
except ImportError:
    FLASK_AVAILABLE = False

# WAA evaluator modules (lazy loaded when on the server)
_getters_module = None
_metrics_module = None


def _load_waa_evaluators(evaluators_path: str | None = None) -> tuple:
    """Load WAA evaluator modules.

    Args:
        evaluators_path: Path to WAA evaluators directory. If None, attempts
            to find it in standard locations.

    Returns:
        Tuple of (getters_module, metrics_module).

    Raises:
        ImportError: If evaluators cannot be loaded.
    """
    global _getters_module, _metrics_module

    if _getters_module is not None and _metrics_module is not None:
        return _getters_module, _metrics_module

    import sys

    # Standard paths to check
    search_paths = []
    if evaluators_path:
        search_paths.append(evaluators_path)

    # Common WAA installation paths
    search_paths.extend([
        "/home/azureuser/WindowsAgentArena/src/win-arena-container/client/desktop_env",
        "C:/WAA/client/desktop_env",
        "/waa/client/desktop_env",
    ])

    for path in search_paths:
        client_path = Path(path)
        evaluators_dir = client_path / "evaluators"

        if evaluators_dir.exists():
            # Add to path
            if str(client_path) not in sys.path:
                sys.path.insert(0, str(client_path))

            try:
                from evaluators import getters, metrics

                _getters_module = getters
                _metrics_module = metrics
                logger.info(f"Loaded WAA evaluators from {evaluators_dir}")
                return _getters_module, _metrics_module
            except ImportError as e:
                logger.warning(f"Failed to import evaluators from {path}: {e}")
                continue

    raise ImportError(
        "Could not load WAA evaluators. Ensure WindowsAgentArena is installed "
        f"and evaluators are available. Searched: {search_paths}"
    )


class MockEnv:
    """Minimal environment object for WAA getters.

    WAA getter functions expect an 'env' object with vm_ip attribute
    for making HTTP calls to the VM. This mock provides that interface.
    """

    def __init__(self, vm_ip: str = "localhost", port: int = 5000):
        self.vm_ip = vm_ip
        self.port = port


def get_actual_value(
    evaluator_config: dict,
    env: MockEnv | None = None,
    getters: Any | None = None,
) -> Any:
    """Get the actual value from the VM using WAA getters.

    Args:
        evaluator_config: Task evaluator configuration with 'result' spec.
        env: Environment object with vm_ip for getter calls.
        getters: WAA getters module (loaded automatically if None).

    Returns:
        The actual value retrieved from the VM.
    """
    if env is None:
        env = MockEnv()

    if getters is None:
        getters, _ = _load_waa_evaluators()

    result_spec = evaluator_config.get("result", {})
    result_type = result_spec.get("type", "vm_command_line")

    # Get the getter function
    getter_name = f"get_{result_type}"
    getter_func = getattr(getters, getter_name, None)

    if getter_func is None:
        logger.warning(f"Getter not found: {getter_name}")
        return None

    try:
        return getter_func(env, result_spec)
    except Exception as e:
        logger.error(f"Getter {getter_name} failed: {e}")
        return None


def get_expected_value(
    evaluator_config: dict,
    env: MockEnv | None = None,
    getters: Any | None = None,
) -> Any:
    """Get the expected value for comparison.

    The expected value can be:
    - A literal value in the config
    - A rule-based match criteria
    - Retrieved via a getter function

    Args:
        evaluator_config: Task evaluator configuration with 'expected' spec.
        env: Environment object for getter calls.
        getters: WAA getters module.

    Returns:
        The expected value or match criteria.
    """
    if env is None:
        env = MockEnv()

    if getters is None:
        getters, _ = _load_waa_evaluators()

    expected_spec = evaluator_config.get("expected", {})

    # Handle different expected value formats
    expected_type = expected_spec.get("type")

    if expected_type == "rule":
        # Rule-based matching - return the rules dict
        return expected_spec.get("rules", {})

    if expected_type == "literal" or "value" in expected_spec:
        # Direct literal value
        return expected_spec.get("value")

    if expected_type:
        # Get via getter function
        getter_name = f"get_{expected_type}"
        getter_func = getattr(getters, getter_name, None)

        if getter_func:
            try:
                return getter_func(env, expected_spec)
            except Exception as e:
                logger.error(f"Expected getter {getter_name} failed: {e}")
                return None

    # Fallback: check for direct 'expected' value
    if "expected" in evaluator_config and not isinstance(
        evaluator_config["expected"], dict
    ):
        return evaluator_config["expected"]

    return None


def run_metric(
    metric_name: str,
    actual: Any,
    expected: Any,
    options: dict | None = None,
    metrics: Any | None = None,
) -> float:
    """Run a WAA metric function to compare actual vs expected.

    Args:
        metric_name: Name of the metric function (e.g., "exact_match").
        actual: The actual value from the VM.
        expected: The expected value.
        options: Additional options to pass to the metric.
        metrics: WAA metrics module (loaded automatically if None).

    Returns:
        Score from 0.0 to 1.0.
    """
    if metrics is None:
        _, metrics = _load_waa_evaluators()

    if options is None:
        options = {}

    # Get the metric function
    metric_func = getattr(metrics, metric_name, None)

    if metric_func is None:
        # Try common fallbacks
        fallbacks = ["exact_match", "fuzzy_match"]
        for fallback in fallbacks:
            metric_func = getattr(metrics, fallback, None)
            if metric_func:
                logger.warning(
                    f"Metric '{metric_name}' not found, using '{fallback}'"
                )
                break

    if metric_func is None:
        logger.error(f"No valid metric found for '{metric_name}'")
        return 0.0

    try:
        score = metric_func(actual, expected, **options)
        return float(score)
    except Exception as e:
        logger.error(f"Metric {metric_name} failed: {e}")
        return 0.0


def evaluate_task_state(
    task_config: dict,
    env: MockEnv | None = None,
    evaluators_path: str | None = None,
) -> dict:
    """Evaluate the current VM state against task success criteria.

    This is the main evaluation function that orchestrates:
    1. Running any postconfig setup (e.g., activating windows)
    2. Getting the actual value from the VM via getters
    3. Getting the expected value
    4. Running metric comparison(s)
    5. Combining results if multiple metrics

    Args:
        task_config: Full task configuration including 'evaluator' spec.
        env: Environment object for VM access.
        evaluators_path: Path to WAA evaluators directory.

    Returns:
        Dict with evaluation results:
        {
            "success": bool,
            "score": float,  # 0.0 to 1.0
            "actual": Any,   # Truncated for response size
            "expected": Any, # Truncated for response size
            "reason": str,   # Explanation
            "metrics": list, # Per-metric results if multiple
        }
    """
    if env is None:
        env = MockEnv()

    # Load evaluators
    try:
        getters, metrics = _load_waa_evaluators(evaluators_path)
    except ImportError as e:
        return {
            "success": False,
            "score": 0.0,
            "reason": f"Failed to load evaluators: {e}",
            "error": str(e),
        }

    evaluator_config = task_config.get("evaluator", {})

    if not evaluator_config:
        return {
            "success": False,
            "score": 0.0,
            "reason": "No evaluator configuration in task",
        }

    # Handle infeasible tasks
    # If task is marked infeasible and agent reported FAIL, that's success
    if evaluator_config.get("infeasible"):
        # Check if agent's last action was a FAIL/infeasible signal
        agent_last_action = task_config.get("agent_last_action", "")
        if agent_last_action.upper() in ("FAIL", "INFEASIBLE", "IMPOSSIBLE"):
            return {
                "success": True,
                "score": 1.0,
                "reason": "Correctly identified infeasible task",
            }

    # Run postconfig if present (e.g., activate windows for inspection)
    postconfig = evaluator_config.get("postconfig", [])
    if postconfig:
        _run_postconfig(postconfig, env)

    # Get actual value from VM
    actual = get_actual_value(evaluator_config, env, getters)

    # Get expected value
    expected = get_expected_value(evaluator_config, env, getters)

    # Get metric function(s)
    func_spec = evaluator_config.get("func", "exact_match")
    options = evaluator_config.get("options", {})
    conjunction = evaluator_config.get("conj", "and")  # "and" or "or"

    # Handle single or multiple metrics
    if isinstance(func_spec, str):
        func_names = [func_spec]
    else:
        func_names = func_spec

    # Run each metric
    metric_results = []
    for func_name in func_names:
        score = run_metric(func_name, actual, expected, options, metrics)
        metric_results.append({
            "metric": func_name,
            "score": score,
            "success": score >= 1.0,
        })

    # Combine results based on conjunction
    if conjunction == "or":
        final_score = max(r["score"] for r in metric_results)
        success = any(r["success"] for r in metric_results)
    else:  # "and"
        final_score = min(r["score"] for r in metric_results)
        success = all(r["success"] for r in metric_results)

    # Truncate large values for response
    actual_str = _truncate_value(actual, max_len=500)
    expected_str = _truncate_value(expected, max_len=500)

    # Build reason string
    if success:
        reason = f"Task completed successfully (score={final_score:.2f})"
    else:
        reason = f"Task not completed (score={final_score:.2f})"
        if actual is None:
            reason += " - could not retrieve actual value"
        elif expected is None:
            reason += " - could not determine expected value"

    return {
        "success": success,
        "score": final_score,
        "actual": actual_str,
        "expected": expected_str,
        "reason": reason,
        "metrics": metric_results if len(metric_results) > 1 else None,
    }


def _run_postconfig(postconfig: list, env: MockEnv) -> None:
    """Run postconfig commands before evaluation.

    Postconfig typically includes things like:
    - Activating specific windows
    - Waiting for operations to complete
    - Opening files for inspection

    Args:
        postconfig: List of postconfig command specs.
        env: Environment object.
    """
    import requests

    for cmd in postconfig:
        try:
            cmd_type = cmd.get("type", "")

            if cmd_type == "activate_window":
                # Send activate window command to VM
                window_name = cmd.get("name", "")
                requests.post(
                    f"http://{env.vm_ip}:{env.port}/setup/activate_window",
                    json={"name": window_name},
                    timeout=10.0,
                )

            elif cmd_type == "wait":
                import time

                time.sleep(cmd.get("seconds", 1.0))

            elif cmd_type == "execute":
                # Run a command on the VM
                command = cmd.get("command", "")
                requests.post(
                    f"http://{env.vm_ip}:{env.port}/execute_windows",
                    json={"command": command},
                    timeout=30.0,
                )

            else:
                logger.debug(f"Unknown postconfig type: {cmd_type}")

        except Exception as e:
            logger.warning(f"Postconfig command failed: {e}")


def _truncate_value(value: Any, max_len: int = 500) -> str:
    """Truncate a value for JSON response."""
    if value is None:
        return None

    s = str(value)
    if len(s) > max_len:
        return s[:max_len] + "..."
    return s


def create_evaluate_blueprint(
    evaluators_path: str | None = None,
) -> "Blueprint":
    """Create a Flask Blueprint with the /evaluate endpoint.

    This function creates a Blueprint that can be registered with the
    WAA Flask server to add evaluation capabilities.

    Args:
        evaluators_path: Path to WAA evaluators directory.

    Returns:
        Flask Blueprint with /evaluate endpoint.

    Raises:
        ImportError: If Flask is not available.

    Example:
        ```python
        from flask import Flask
        from openadapt_evals.server.evaluate_endpoint import create_evaluate_blueprint

        app = Flask(__name__)
        evaluate_bp = create_evaluate_blueprint("/path/to/evaluators")
        app.register_blueprint(evaluate_bp)
        ```
    """
    if not FLASK_AVAILABLE:
        raise ImportError("Flask is required to create the evaluate blueprint")

    bp = Blueprint("evaluate", __name__)

    @bp.route("/evaluate", methods=["POST"])
    def evaluate():
        """Evaluate current VM state against task criteria.

        Request JSON:
        {
            "evaluator": {
                "func": "exact_match",
                "result": {"type": "vm_file", "path": "..."},
                "expected": {"type": "rule", "rules": {...}}
            },
            "agent_last_action": "DONE"  # Optional
        }

        Response JSON:
        {
            "success": true/false,
            "score": 0.0-1.0,
            "actual": "...",
            "expected": "...",
            "reason": "..."
        }
        """
        task_config = request.json

        if not task_config:
            return jsonify({"error": "No task config provided"}), 400

        env = MockEnv()
        result = evaluate_task_state(task_config, env, evaluators_path)

        return jsonify(result)

    @bp.route("/evaluate/health", methods=["GET"])
    def evaluate_health():
        """Health check for evaluate endpoint."""
        try:
            _load_waa_evaluators(evaluators_path)
            return jsonify({"status": "ok", "evaluators_loaded": True})
        except ImportError as e:
            return jsonify({"status": "degraded", "error": str(e)}), 503

    return bp


# Standalone metrics implementations for when WAA evaluators are not available
# These provide basic functionality without requiring WAA


class StandaloneMetrics:
    """Standalone metric implementations.

    These are fallback implementations that can be used when WAA's
    evaluators are not available (e.g., for testing or standalone use).
    """

    @staticmethod
    def exact_match(result: Any, expected: Any, **options) -> float:
        """Exact string/value match."""
        if result == expected:
            return 1.0
        # Try string comparison
        if str(result).strip() == str(expected).strip():
            return 1.0
        return 0.0

    @staticmethod
    def fuzzy_match(result: Any, expected: Any, threshold: float = 0.8, **options) -> float:
        """Fuzzy string matching."""
        try:
            from rapidfuzz import fuzz

            score = fuzz.ratio(str(result), str(expected)) / 100.0
            return 1.0 if score >= threshold else score
        except ImportError:
            # Fallback to simple containment check
            result_str = str(result).lower()
            expected_str = str(expected).lower()
            if expected_str in result_str or result_str in expected_str:
                return 0.8
            return 0.0

    @staticmethod
    def contains(result: Any, expected: Any, **options) -> float:
        """Check if result contains expected."""
        result_str = str(result).lower()
        expected_str = str(expected).lower()
        return 1.0 if expected_str in result_str else 0.0

    @staticmethod
    def file_exists(result: Any, expected: Any, **options) -> float:
        """Check if file exists."""
        path = result if result else expected
        if path and Path(path).exists():
            return 1.0
        return 0.0


class StandaloneGetters:
    """Standalone getter implementations for basic evaluation.

    These provide basic file and command output retrieval without
    requiring the full WAA evaluator infrastructure.
    """

    def __init__(self, server_url: str = "http://localhost:5000"):
        self.server_url = server_url

    def get_vm_file(self, env: MockEnv, config: dict) -> str | None:
        """Get file contents from VM."""
        import requests

        path = config.get("path", "")
        try:
            resp = requests.post(
                f"{self.server_url}/execute_windows",
                json={"command": f"Get-Content -Path '{path}'", "shell": "powershell"},
                timeout=30.0,
            )
            if resp.status_code == 200:
                return resp.json().get("output", "")
        except Exception as e:
            logger.error(f"Failed to get file {path}: {e}")
        return None

    def get_vm_command_line(self, env: MockEnv, config: dict) -> str | None:
        """Execute command on VM and return output."""
        import requests

        command = config.get("command", "")
        shell = config.get("shell", "powershell")

        try:
            resp = requests.post(
                f"{self.server_url}/execute_windows",
                json={"command": command, "shell": shell},
                timeout=60.0,
            )
            if resp.status_code == 200:
                return resp.json().get("output", "")
        except Exception as e:
            logger.error(f"Failed to run command: {e}")
        return None


def create_standalone_evaluator(
    server_url: str = "http://localhost:5000",
) -> Callable[[dict], dict]:
    """Create a standalone evaluator function.

    This creates an evaluator that uses standalone implementations
    of basic getters and metrics, useful when WAA evaluators are
    not available.

    Args:
        server_url: URL of the WAA server for VM access.

    Returns:
        Callable that takes task_config and returns evaluation result.

    Example:
        ```python
        evaluate = create_standalone_evaluator("http://vm:5000")
        result = evaluate(task_config)
        print(f"Success: {result['success']}")
        ```
    """
    getters = StandaloneGetters(server_url)
    metrics = StandaloneMetrics()

    def evaluate(task_config: dict) -> dict:
        evaluator_config = task_config.get("evaluator", {})

        if not evaluator_config:
            return {
                "success": False,
                "score": 0.0,
                "reason": "No evaluator configuration",
            }

        # Get result spec
        result_spec = evaluator_config.get("result", {})
        result_type = result_spec.get("type", "vm_command_line")

        # Get actual value
        getter_name = f"get_{result_type}"
        getter_func = getattr(getters, getter_name, None)

        actual = None
        if getter_func:
            try:
                actual = getter_func(MockEnv(), result_spec)
            except Exception as e:
                logger.error(f"Getter failed: {e}")

        # Get expected value
        expected_spec = evaluator_config.get("expected", {})
        if expected_spec.get("type") == "rule":
            expected = expected_spec.get("rules", {}).get("match")
        else:
            expected = expected_spec.get("value")

        # Run metric
        func_name = evaluator_config.get("func", "exact_match")
        metric_func = getattr(metrics, func_name, metrics.exact_match)

        try:
            score = metric_func(actual, expected)
        except Exception as e:
            logger.error(f"Metric failed: {e}")
            score = 0.0

        success = score >= 1.0

        return {
            "success": success,
            "score": float(score),
            "actual": _truncate_value(actual),
            "expected": _truncate_value(expected),
            "reason": "Standalone evaluation",
        }

    return evaluate
