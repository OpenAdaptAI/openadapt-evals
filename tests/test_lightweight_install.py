"""Guardrail tests for Phase 0b: openadapt-ml as optional dependency.

These tests verify that the core openadapt-evals functionality works
WITHOUT openadapt-ml installed. They define the desired post-refactor
behavior and should be run AFTER making openadapt-ml optional.

Run with: pytest tests/test_lightweight_install.py -v
"""

from __future__ import annotations

import importlib
import sys
from unittest import mock

import pytest


def _hide_openadapt_ml():
    """Context manager that makes openadapt_ml unimportable."""
    # Block the import by inserting a finder that raises ImportError
    class _BlockML:
        def find_module(self, name, path=None):
            if name == "openadapt_ml" or name.startswith("openadapt_ml."):
                return self
            return None

        def load_module(self, name):
            raise ImportError(f"Simulated: {name} not installed (lightweight mode)")

    return _BlockML()


# ---------------------------------------------------------------------------
# Core modules must import without openadapt-ml
# ---------------------------------------------------------------------------


class TestCoreImportsWithoutML:
    """Verify that core modules import cleanly without openadapt-ml."""

    @pytest.fixture(autouse=True)
    def block_ml(self):
        """Block openadapt_ml imports for every test in this class."""
        blocker = _hide_openadapt_ml()
        sys.meta_path.insert(0, blocker)
        # Clear any cached openadapt_ml modules
        to_remove = [k for k in sys.modules if k.startswith("openadapt_ml")]
        for k in to_remove:
            del sys.modules[k]
        yield
        sys.meta_path.remove(blocker)

    def test_standalone_trainer_imports(self):
        """The standalone trainer has zero openadapt-ml imports."""
        mod = importlib.import_module("openadapt_evals.training.standalone.trainer")
        assert hasattr(mod, "GRPOTrainer")

    def test_standalone_config_imports(self):
        mod = importlib.import_module("openadapt_evals.training.standalone.config")
        assert hasattr(mod, "TrainingConfig")

    def test_standalone_prompt_imports(self):
        mod = importlib.import_module("openadapt_evals.training.standalone.prompt")
        assert hasattr(mod, "SYSTEM_PROMPT")

    def test_demo_executor_imports(self):
        mod = importlib.import_module("openadapt_evals.agents.demo_executor")
        assert hasattr(mod, "DemoExecutor")

    def test_demo_library_imports(self):
        mod = importlib.import_module("openadapt_evals.demo_library")
        assert hasattr(mod, "DemoLibrary")

    def test_task_config_imports(self):
        mod = importlib.import_module("openadapt_evals.task_config")
        assert hasattr(mod, "TaskConfig")

    def test_telemetry_imports(self):
        """Telemetry should not depend on openadapt-ml."""
        mod = importlib.import_module("openadapt_evals.telemetry")
        assert hasattr(mod, "capture_event")

    def test_waa_connection_imports(self):
        mod = importlib.import_module(
            "openadapt_evals.infrastructure.waa_connection"
        )
        assert hasattr(mod, "WAAConnection")

    def test_rl_env_imports(self):
        mod = importlib.import_module("openadapt_evals.adapters.rl_env")
        assert hasattr(mod, "RLEnvironment")

    def test_benchmark_action_imports(self):
        mod = importlib.import_module("openadapt_evals.adapters.base")
        assert hasattr(mod, "BenchmarkAction")


# ---------------------------------------------------------------------------
# ML-dependent modules degrade gracefully
# ---------------------------------------------------------------------------


class TestMLDependentModulesDegrade:
    """Modules that use openadapt-ml should degrade, not crash."""

    @pytest.fixture(autouse=True)
    def block_ml(self):
        blocker = _hide_openadapt_ml()
        sys.meta_path.insert(0, blocker)
        to_remove = [k for k in sys.modules if k.startswith("openadapt_ml")]
        for k in to_remove:
            del sys.modules[k]
        yield
        sys.meta_path.remove(blocker)

    def test_baseline_agent_importable(self):
        """BaselineAgent uses try/except — should import without crash."""
        mod = importlib.import_module("openadapt_evals.agents.baseline_agent")
        assert hasattr(mod, "BaselineAgent")

    def test_trace_export_importable(self):
        """trace_export has top-level openadapt_ml import — must be guarded."""
        # This test will FAIL until we add try/except to trace_export.py
        try:
            importlib.import_module("openadapt_evals.benchmarks.trace_export")
        except ImportError as e:
            if "openadapt_ml" in str(e):
                pytest.fail(
                    f"trace_export.py crashes without openadapt-ml: {e}. "
                    f"Needs try/except guard around openadapt_ml.schema import."
                )
            raise

    def test_policy_agent_importable(self):
        """PolicyAgent uses lazy import in method body."""
        mod = importlib.import_module("openadapt_evals.agents.policy_agent")
        assert hasattr(mod, "PolicyAgent")


# ---------------------------------------------------------------------------
# The client's exact import pattern must work
# ---------------------------------------------------------------------------


class TestClientImportPattern:
    """Verify the exact imports the client uses in grpo_clean_run.py."""

    def test_grpo_trainer_import(self):
        from openadapt_evals.training.standalone.trainer import GRPOTrainer
        assert callable(GRPOTrainer)

    def test_training_config_import(self):
        from openadapt_evals.training.standalone.config import TrainingConfig
        assert callable(TrainingConfig)

    def test_waa_connection_import(self):
        from openadapt_evals.infrastructure import WAAConnection
        assert callable(WAAConnection)

    def test_wandb_callbacks_import(self):
        from openadapt_evals.integrations.wandb_callbacks import (
            wandb_model_loaded,
            wandb_rollout_logger,
            wandb_step_logger,
        )
        assert callable(wandb_model_loaded)
        assert callable(wandb_rollout_logger)
        assert callable(wandb_step_logger)

    def test_task_config_import(self):
        from openadapt_evals.task_config import TaskConfig
        assert callable(TaskConfig.from_yaml)

    def test_demo_library_import(self):
        from openadapt_evals.demo_library import DemoLibrary
        assert callable(DemoLibrary)

    def test_benchmark_action_import(self):
        from openadapt_evals.adapters.base import BenchmarkAction
        assert callable(BenchmarkAction)
