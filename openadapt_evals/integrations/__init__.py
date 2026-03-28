"""Integrations with external services.

This module provides integrations with:
- Weights & Biases (wandb) for experiment tracking and report generation
- W&B callback functions for the standalone GRPO trainer
"""

from openadapt_evals.integrations.wandb_logger import WandbLogger
from openadapt_evals.integrations.wandb_callbacks import (
    wandb_model_loaded,
    wandb_rollout_logger,
    wandb_step_logger,
)
from openadapt_evals.integrations.fixtures import (
    generate_noise_data,
    generate_best_case_data,
    generate_worst_case_data,
    generate_median_case_data,
    Scenario,
)

# Import report generator (may fail if wandb reports API not available)
try:
    from openadapt_evals.integrations.wandb_reports import (
        WandbReportGenerator,
        generate_standard_report,
        generate_demo_report,
    )
    _REPORTS_AVAILABLE = True
except ImportError:
    WandbReportGenerator = None
    generate_standard_report = None
    generate_demo_report = None
    _REPORTS_AVAILABLE = False

__all__ = [
    "WandbLogger",
    "WandbReportGenerator",
    "wandb_model_loaded",
    "wandb_rollout_logger",
    "wandb_step_logger",
    "generate_noise_data",
    "generate_best_case_data",
    "generate_worst_case_data",
    "generate_median_case_data",
    "generate_standard_report",
    "generate_demo_report",
    "Scenario",
]
