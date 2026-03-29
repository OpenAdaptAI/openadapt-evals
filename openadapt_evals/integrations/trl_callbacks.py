"""TRL TrainerCallback implementations for telemetry and Weave tracing.

Provides callbacks that integrate with TRL's GRPOTrainer to automatically
track training events via our telemetry system and optionally log to Weave.

Usage::

    from trl import GRPOConfig, GRPOTrainer
    from openadapt_evals.integrations.trl_callbacks import TelemetryCallback

    trainer = GRPOTrainer(
        model=model,
        args=config,
        callbacks=[TelemetryCallback(model_name="Qwen/Qwen2.5-VL-7B-Instruct")],
        ...
    )
    trainer.train()
"""

from __future__ import annotations

import logging
import time
from typing import Any

logger = logging.getLogger(__name__)


class TelemetryCallback:
    """TRL TrainerCallback that emits telemetry events for training lifecycle.

    Calls our telemetry functions at key training milestones:
    - ``on_train_begin`` -> ``track_training_run(phase="start", ...)``
    - ``on_step_end``    -> ``track_training_step(step=..., reward_mean=..., loss=...)``
    - ``on_save``        -> ``track_checkpoint_saved(step=...)``
    - ``on_train_end``   -> ``track_training_run(phase="completed", ...)``

    Inherits from ``transformers.TrainerCallback`` at runtime so it can be
    passed directly to TRL's ``GRPOTrainer(callbacks=[...])``.

    All telemetry calls are wrapped in try/except so failures never interrupt
    training.
    """

    def __init__(
        self,
        model_name: str | None = None,
        task_count: int | None = None,
        constrained_decoding: bool = False,
        vision_loss_mode: str | None = None,
    ) -> None:
        self.model_name = model_name
        self.task_count = task_count
        self.constrained_decoding = constrained_decoding
        self.vision_loss_mode = vision_loss_mode
        self._train_start_time: float | None = None

    def on_train_begin(
        self,
        args: Any,
        state: Any,
        control: Any,
        **kwargs: Any,
    ) -> None:
        """Called at the start of training."""
        self._train_start_time = time.time()
        try:
            from openadapt_evals.telemetry import track_training_run

            num_steps = getattr(args, "max_steps", None)
            num_rollouts = getattr(args, "num_generations", None)
            track_training_run(
                phase="start",
                model_name=self.model_name,
                num_steps=num_steps,
                num_rollouts_per_step=num_rollouts,
                task_count=self.task_count,
                constrained_decoding=self.constrained_decoding,
                vision_loss_mode=self.vision_loss_mode,
            )
            logger.debug("Telemetry: training_run start emitted")
        except Exception as exc:
            logger.debug("Telemetry on_train_begin failed: %s", exc)

    def on_step_end(
        self,
        args: Any,
        state: Any,
        control: Any,
        **kwargs: Any,
    ) -> None:
        """Called at the end of each training step."""
        try:
            from openadapt_evals.telemetry import track_training_step

            # TRL logs metrics in state.log_history
            reward_mean = None
            loss = None
            if state.log_history:
                last_log = state.log_history[-1]
                reward_mean = last_log.get("reward", last_log.get("reward_mean"))
                loss = last_log.get("loss")

            track_training_step(
                step=state.global_step,
                reward_mean=reward_mean,
                loss=loss,
            )
        except Exception as exc:
            logger.debug("Telemetry on_step_end failed: %s", exc)

    def on_save(
        self,
        args: Any,
        state: Any,
        control: Any,
        **kwargs: Any,
    ) -> None:
        """Called when a checkpoint is saved."""
        try:
            from openadapt_evals.telemetry import track_checkpoint_saved

            track_checkpoint_saved(step=state.global_step)
            logger.debug("Telemetry: checkpoint_saved at step %d", state.global_step)
        except Exception as exc:
            logger.debug("Telemetry on_save failed: %s", exc)

    def on_train_end(
        self,
        args: Any,
        state: Any,
        control: Any,
        **kwargs: Any,
    ) -> None:
        """Called at the end of training."""
        try:
            from openadapt_evals.telemetry import track_training_run

            duration = None
            if self._train_start_time is not None:
                duration = time.time() - self._train_start_time

            # Extract final reward from last log entry
            reward_mean = None
            loss = None
            if state.log_history:
                last_log = state.log_history[-1]
                reward_mean = last_log.get("reward", last_log.get("reward_mean"))
                loss = last_log.get("loss")

            track_training_run(
                phase="completed",
                model_name=self.model_name,
                num_steps=state.global_step,
                duration_seconds=duration,
                reward_mean=reward_mean,
                loss=loss,
            )
            logger.debug("Telemetry: training_run completed emitted")
        except Exception as exc:
            logger.debug("Telemetry on_train_end failed: %s", exc)


# Register as a TrainerCallback subclass at import time so TRL recognizes it.
# If transformers is not installed, the class still works as a plain object
# (the callback methods are called by name, not by inheritance check in recent
# TRL versions).
try:
    from transformers import TrainerCallback as _TrainerCallback

    # Dynamically add TrainerCallback as a base class
    TelemetryCallback.__bases__ = (_TrainerCallback,) + TelemetryCallback.__bases__
except ImportError:
    logger.debug(
        "transformers not installed; TelemetryCallback will work as a "
        "duck-typed callback but won't inherit from TrainerCallback"
    )
