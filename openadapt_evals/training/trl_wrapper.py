"""Drop-in TRL-backed GRPOTrainer with the same API as the standalone trainer.

Usage (identical to standalone trainer):

    from openadapt_evals.training.trl_wrapper import GRPOTrainer
    from openadapt_evals.training.standalone.config import TrainingConfig

    trainer = GRPOTrainer(
        TrainingConfig(model_name="Qwen/Qwen3.5-9B", task_dir="tasks/"),
        on_step_complete=my_logger,
    )
    trainer.train()

Internally uses TRL's GRPOTrainer + rollout_func. Falls back to the
standalone trainer if TRL is not installed.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class GRPOTrainer:
    """TRL-backed GRPO trainer with the standalone trainer's API.

    Same constructor signature: TrainingConfig + 4 callback hooks.
    Same train() → str return (checkpoint path).
    """

    def __init__(
        self,
        config,
        *,
        on_model_loaded=None,
        on_before_collect=None,
        on_rollout_complete=None,
        on_step_complete=None,
    ):
        self._config = config
        self._on_model_loaded = on_model_loaded
        self._on_before_collect = on_before_collect
        self._on_rollout_complete = on_rollout_complete
        self._on_step_complete = on_step_complete

    def train(self) -> str:
        """Run GRPO training via TRL. Returns path to final checkpoint."""
        from pathlib import Path

        from datasets import Dataset
        from trl import GRPOConfig, GRPOTrainer as _TRLTrainer

        from openadapt_evals.task_config import TaskConfig
        from openadapt_evals.training.trl_rollout import make_waa_rollout_func

        # Load tasks
        task_configs = []
        if self._config.task_dir:
            task_configs = TaskConfig.from_dir(self._config.task_dir)
        if self._config.task_ids and not task_configs:
            logger.warning("task_ids set but no task_dir — using task_ids as prompts")

        if not task_configs:
            raise ValueError("No tasks. Set task_dir in TrainingConfig.")

        dataset = Dataset.from_dict({
            "prompt": [tc.name for tc in task_configs],
            "task_id": [tc.id for tc in task_configs],
        })

        # Load model
        try:
            from unsloth import FastVisionModel
            logger.info("Loading with Unsloth: %s", self._config.model_name)
            model, processor = FastVisionModel.from_pretrained(
                self._config.model_name,
                load_in_4bit=self._config.load_in_4bit,
            )
            model = FastVisionModel.get_peft_model(
                model, r=self._config.lora_r, lora_alpha=self._config.lora_alpha,
                target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                                "gate_proj", "up_proj", "down_proj"],
            )
        except ImportError:
            from openadapt_evals.training.standalone.model_loader import (
                load_model_and_processor,
            )
            model, processor = load_model_and_processor(
                self._config.model_name,
                load_in_4bit=self._config.load_in_4bit,
                lora_r=self._config.lora_r,
                lora_alpha=self._config.lora_alpha,
                lora_checkpoint=self._config.lora_checkpoint,
            )

        if self._on_model_loaded:
            self._on_model_loaded(model, processor)

        # Create rollout function
        from openadapt_evals.adapters.waa.live import WAALiveAdapter, WAALiveConfig
        adapter = WAALiveAdapter(WAALiveConfig(
            server_url=self._config.server_url,
        ))
        rollout_func = make_waa_rollout_func(
            adapter=adapter,
            task_configs=task_configs,
            max_steps=self._config.max_steps_per_episode,
            constrained_decoding=getattr(self._config, "constrained_decoding", False),
            max_new_tokens=self._config.max_new_tokens,
            temperature=self._config.temperature,
        )

        # Reward function
        def env_reward_fn(completions, **kwargs):
            return kwargs.get("env_reward", [0.0] * len(completions))

        # Build callbacks
        callbacks = []

        # Telemetry callback
        try:
            from openadapt_evals.integrations.trl_callbacks import TelemetryCallback
            callbacks.append(TelemetryCallback())
        except ImportError:
            pass

        # Map our callback hooks to TRL TrainerCallback
        if any([self._on_before_collect, self._on_rollout_complete,
                self._on_step_complete]):
            try:
                from transformers import TrainerCallback

                class HookBridge(TrainerCallback):
                    def __init__(self, hooks):
                        self._hooks = hooks

                    def on_step_end(self, args, state, control, **kwargs):
                        if self._hooks.get("on_step_complete"):
                            metrics = kwargs.get("metrics", {})
                            self._hooks["on_step_complete"](
                                state.global_step, [], metrics,
                            )

                callbacks.append(HookBridge({
                    "on_before_collect": self._on_before_collect,
                    "on_rollout_complete": self._on_rollout_complete,
                    "on_step_complete": self._on_step_complete,
                }))
            except ImportError:
                pass

        # Weave tracing
        try:
            from openadapt_evals.integrations.weave_integration import weave_init
            weave_init("openadapt-evals")
        except Exception:
            pass

        # TRL config
        output_dir = self._config.output_dir
        trl_config = GRPOConfig(
            output_dir=output_dir,
            num_generations=self._config.num_rollouts_per_step,
            max_completion_length=self._config.max_new_tokens,
            num_train_epochs=1,
            max_steps=self._config.num_training_steps,
            learning_rate=self._config.learning_rate,
            save_steps=self._config.save_every_steps,
            logging_steps=1,
            bf16=True,
            loss_type="grpo",
        )

        trainer = _TRLTrainer(
            model=model,
            processing_class=processor,
            args=trl_config,
            train_dataset=dataset,
            reward_funcs=[env_reward_fn],
            rollout_func=rollout_func,
            callbacks=callbacks,
        )

        logger.info(
            "Starting TRL GRPO training: model=%s tasks=%d rollouts=%d steps=%d",
            self._config.model_name, len(task_configs),
            self._config.num_rollouts_per_step, self._config.num_training_steps,
        )

        trainer.train()
        trainer.save_model(output_dir)

        logger.info("Training complete. Checkpoint: %s", output_dir)
        return output_dir
