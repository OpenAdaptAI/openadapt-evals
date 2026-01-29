"""Client-side evaluator for WAA benchmarks.

Runs WAA evaluators locally, making HTTP calls to the WAA server's /execute endpoint.
This approach follows WAA's own design pattern and eliminates the need for a sidecar service.
"""

import sys
import json
import requests
from pathlib import Path
from typing import Any, Dict, Optional
from dataclasses import dataclass, field


@dataclass
class EvaluationResult:
    """Result of evaluating a benchmark task."""
    success: bool
    score: float
    actual: Any = None
    expected: Any = None
    reason: str = ""
    metrics: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "success": self.success,
            "score": self.score,
            "actual": str(self.actual)[:500] if self.actual else None,
            "expected": str(self.expected)[:500] if self.expected else None,
            "reason": self.reason,
            "metrics": self.metrics,
        }


class EvaluatorClient:
    """Client-side evaluator that uses WAA's evaluators directly.

    This client imports WAA's evaluator modules (getters, metrics) and runs them
    locally. The getters make HTTP calls to the WAA server's /execute endpoint
    to retrieve values from the Windows VM.

    Example:
        client = EvaluatorClient()  # Auto-detects VM IP
        result = client.evaluate(task_config)
    """

    def __init__(
        self,
        vm_ip: Optional[str] = None,
        port: int = 5000,
        waa_evaluators_path: Optional[Path] = None,
        timeout: int = 30,
    ):
        """Initialize the evaluator client.

        Args:
            vm_ip: VM IP address. If None, auto-detects from multiple sources.
            port: WAA server port (default 5000).
            waa_evaluators_path: Path to WAA evaluators. If None, searches common locations.
            timeout: HTTP request timeout in seconds.
        """
        from .discovery import discover_vm_ip

        self.vm_ip = vm_ip or discover_vm_ip()
        if not self.vm_ip:
            raise ValueError(
                "Could not auto-detect VM IP. Please provide vm_ip explicitly or "
                "set WAA_VM_IP environment variable."
            )

        self.port = port
        self.timeout = timeout
        self.base_url = f"http://{self.vm_ip}:{self.port}"

        # Find and load WAA evaluators
        self._evaluators_path = waa_evaluators_path or self._find_evaluators_path()
        self._getters = None
        self._metrics = None
        self._load_evaluators()

    def _find_evaluators_path(self) -> Optional[Path]:
        """Find WAA evaluators in common locations."""
        search_paths = [
            # Relative to openadapt-ml
            Path(__file__).parent.parent.parent.parent / "openadapt-ml" / "vendor" / "WindowsAgentArena" / "src" / "win-arena-container" / "client" / "desktop_env",
            # Relative to current file in openadapt-evals
            Path(__file__).parent.parent.parent.parent / "vendor" / "WindowsAgentArena" / "src" / "win-arena-container" / "client" / "desktop_env",
            # Absolute common locations
            Path.home() / "WindowsAgentArena" / "src" / "win-arena-container" / "client" / "desktop_env",
            Path("/opt/waa/client/desktop_env"),
        ]

        for path in search_paths:
            evaluators_dir = path / "evaluators"
            if evaluators_dir.exists() and (evaluators_dir / "getters.py").exists():
                return path

        return None

    def _load_evaluators(self) -> None:
        """Load WAA evaluator modules."""
        if not self._evaluators_path:
            return

        # Add to sys.path if not already there
        path_str = str(self._evaluators_path)
        if path_str not in sys.path:
            sys.path.insert(0, path_str)

        # Also add parent for absolute imports
        parent_str = str(self._evaluators_path.parent)
        if parent_str not in sys.path:
            sys.path.insert(0, parent_str)

        try:
            from evaluators import getters, metrics
            self._getters = getters
            self._metrics = metrics
        except ImportError as e:
            # Evaluators not available, will use fallback
            pass

    def evaluate(self, task_config: Dict[str, Any]) -> EvaluationResult:
        """Evaluate a benchmark task.

        Args:
            task_config: Task configuration with 'evaluator' section containing:
                - result: Dict with 'type' specifying the getter function
                - expected: Dict with 'value' or 'rules' specifying expected result
                - func: Metric function name (default: 'exact_match')

        Returns:
            EvaluationResult with success status, score, and details.
        """
        evaluator_config = task_config.get("evaluator", {})

        if not evaluator_config:
            return EvaluationResult(
                success=False,
                score=0.0,
                reason="No evaluator configuration in task"
            )

        try:
            # Get actual value from VM
            actual = self._get_actual_value(evaluator_config)

            # Get expected value from config
            expected = self._get_expected_value(evaluator_config)

            # Run metric comparison
            score = self._run_metric(evaluator_config, actual, expected)

            return EvaluationResult(
                success=score >= 1.0,
                score=score,
                actual=actual,
                expected=expected,
                reason=f"Metric returned score {score}",
                metrics={"raw_score": score}
            )

        except Exception as e:
            return EvaluationResult(
                success=False,
                score=0.0,
                reason=f"Evaluation error: {str(e)}"
            )

    def _get_actual_value(self, evaluator_config: Dict[str, Any]) -> Any:
        """Get actual value from VM using getter function."""
        result_spec = evaluator_config.get("result", {})
        getter_type = result_spec.get("type")

        if not getter_type:
            raise ValueError("No 'type' specified in evaluator.result")

        # Create a mock env object that the getters expect
        class HttpEnv:
            def __init__(self, vm_ip: str, port: int, timeout: int):
                self.vm_ip = vm_ip
                self.port = port
                self.timeout = timeout

            def execute(self, command: str) -> Dict[str, Any]:
                """Execute command on VM via HTTP."""
                url = f"http://{self.vm_ip}:{self.port}/execute"
                try:
                    response = requests.post(
                        url,
                        json={"command": command},
                        timeout=self.timeout
                    )
                    response.raise_for_status()
                    return response.json()
                except requests.RequestException as e:
                    return {"error": str(e), "output": ""}

        env = HttpEnv(self.vm_ip, self.port, self.timeout)

        # Try WAA getter if available
        if self._getters:
            getter_func = getattr(self._getters, f"get_{getter_type}", None)
            if getter_func:
                return getter_func(env, result_spec)

        # Fallback: direct HTTP call
        return self._fallback_getter(env, getter_type, result_spec)

    def _fallback_getter(self, env: Any, getter_type: str, spec: Dict[str, Any]) -> Any:
        """Fallback getter implementation when WAA evaluators not available."""
        # Common getter types
        if getter_type == "file_content":
            path = spec.get("path", "")
            result = env.execute(f"type {path}")
            return result.get("output", "")

        elif getter_type == "registry_value":
            key = spec.get("key", "")
            value = spec.get("value", "")
            result = env.execute(f'reg query "{key}" /v "{value}"')
            return result.get("output", "")

        elif getter_type == "process_running":
            process = spec.get("process", "")
            result = env.execute(f'tasklist /FI "IMAGENAME eq {process}"')
            return process.lower() in result.get("output", "").lower()

        elif getter_type == "window_exists":
            title = spec.get("title", "")
            result = env.execute(f'powershell "Get-Process | Where-Object {{$_.MainWindowTitle -like \'*{title}*\'}}"')
            return bool(result.get("output", "").strip())

        else:
            raise ValueError(f"Unknown getter type: {getter_type}")

    def _get_expected_value(self, evaluator_config: Dict[str, Any]) -> Any:
        """Extract expected value from evaluator config."""
        expected_spec = evaluator_config.get("expected", {})

        # Direct value
        if "value" in expected_spec:
            return expected_spec["value"]

        # Rules-based
        rules = expected_spec.get("rules", {})
        if "match" in rules:
            return rules["match"]

        return None

    def _run_metric(self, evaluator_config: Dict[str, Any], actual: Any, expected: Any) -> float:
        """Run metric function to compare actual vs expected."""
        func_name = evaluator_config.get("func", "exact_match")

        # Try WAA metric if available
        if self._metrics:
            metric_func = getattr(self._metrics, func_name, None)
            if metric_func:
                try:
                    return float(metric_func(actual, expected))
                except Exception:
                    pass

        # Fallback metrics
        return self._fallback_metric(func_name, actual, expected)

    def _fallback_metric(self, func_name: str, actual: Any, expected: Any) -> float:
        """Fallback metric implementations."""
        if func_name == "exact_match":
            return 1.0 if actual == expected else 0.0

        elif func_name == "contains":
            if isinstance(actual, str) and isinstance(expected, str):
                return 1.0 if expected.lower() in actual.lower() else 0.0
            return 0.0

        elif func_name == "fuzzy_match":
            if isinstance(actual, str) and isinstance(expected, str):
                # Simple fuzzy: check if most words match
                actual_words = set(actual.lower().split())
                expected_words = set(expected.lower().split())
                if not expected_words:
                    return 0.0
                overlap = len(actual_words & expected_words)
                return overlap / len(expected_words)
            return 0.0

        elif func_name == "boolean":
            return 1.0 if bool(actual) == bool(expected) else 0.0

        else:
            # Unknown metric, default to exact match
            return 1.0 if actual == expected else 0.0

    def health_check(self) -> bool:
        """Check if WAA server is reachable."""
        try:
            response = requests.get(
                f"{self.base_url}/probe",
                timeout=5
            )
            return response.status_code == 200
        except requests.RequestException:
            return False
