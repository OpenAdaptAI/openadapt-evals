"""Client-side evaluation module for WAA benchmarks.

This module provides client-side evaluation without requiring a sidecar service.
The evaluators run locally, making HTTP calls to the WAA server's /execute endpoint.

Example usage:
    from openadapt_evals.evaluation import EvaluatorClient, discover_vm_ip

    # Auto-detect VM IP
    vm_ip = discover_vm_ip()

    # Or create client with auto-detection
    client = EvaluatorClient()  # Auto-detects IP
    client = EvaluatorClient(vm_ip="20.127.64.200")  # Explicit IP

    # Evaluate a task
    result = client.evaluate(task_config)
    print(f"Success: {result.success}, Score: {result.score}")
"""

from .discovery import VMIPDiscovery, DiscoveryMethod, discover_vm_ip
from .client import EvaluatorClient, EvaluationResult

__all__ = [
    "VMIPDiscovery",
    "DiscoveryMethod",
    "discover_vm_ip",
    "EvaluatorClient",
    "EvaluationResult",
]
