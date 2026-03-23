"""Reward: group-relative advantages + VLM milestone evaluation. No openadapt-ml imports."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def compute_group_advantages(rewards: list[float]) -> list[float]:
    """GRPO group-relative advantages: (r - mean) / (std + eps)."""
    n = len(rewards)
    if n == 0:
        return []
    mean = sum(rewards) / n
    variance = sum((r - mean) ** 2 for r in rewards) / n
    std = variance**0.5
    if std < 1e-8:
        return [0.0] * n
    return [(r - mean) / (std + 1e-8) for r in rewards]


def evaluate_milestones_screenshot(
    task_config: Any, screenshot: bytes, *, model: str = "gpt-4.1-mini",
) -> float:
    """VLM screenshot-only milestone evaluation. Returns passed/total [0,1]."""
    milestones = getattr(task_config, "milestones", [])
    sm = [m for m in milestones if m.check.check == "screenshot"]
    if not sm:
        return 0.0
    from openadapt_evals.vlm_evaluator import vlm_judge

    passed = sum(1 for m in sm if vlm_judge(screenshot, m.check.description or "", model=model)[0])
    return passed / len(sm)
