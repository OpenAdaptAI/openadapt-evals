"""TRL-backed GRPO trainer with clean config separation.

Our TrainingConfig handles OpenAdapt-specific concerns (WAA server,
task loading, constrained decoding, callbacks). TRL's GRPOConfig
handles training concerns (learning rate, loss type, batch size).
No duplication — each config owns its domain.

Usage:
    from trl import GRPOConfig
    from openadapt_evals.training.trl_wrapper import GRPOTrainer
    from openadapt_evals.training.standalone.config import TrainingConfig

    trainer = GRPOTrainer(
        TrainingConfig(
            task_dir="tasks/",
            server_url="http://localhost:5001",
            constrained_decoding=True,
        ),
        trl_config=GRPOConfig(
            output_dir="./checkpoints",
            loss_type="dapo",
            num_generations=4,
            learning_rate=5e-6,
            bf16=True,
        ),
        on_step_complete=my_logger,
    )
    trainer.train()
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


class GRPOTrainer:
    """TRL-backed GRPO trainer.

    Args:
        config: Our TrainingConfig — WAA server, task_dir, model loading,
            constrained decoding. Handles everything OpenAdapt-specific.
        trl_config: TRL's GRPOConfig — learning rate, loss type, batch
            size, gradient accumulation, vLLM, W&B reporting. Passed
            directly to TRL with zero translation. Optional — sensible
            defaults are used if omitted.
        on_model_loaded: ``(model, processor) -> None``
        on_before_collect: ``(task_id, env) -> None``
        on_rollout_complete: ``(rollout, index) -> None``
        on_step_complete: ``(step, rollouts, metrics) -> None``
    """

    def __init__(
        self,
        config,
        *,
        trl_config=None,
        on_model_loaded=None,
        on_before_collect=None,
        on_rollout_complete=None,
        on_step_complete=None,
    ):
        self._config = config
        self._trl_config = trl_config
        self._on_model_loaded = on_model_loaded
        self._on_before_collect = on_before_collect
        self._on_rollout_complete = on_rollout_complete
        self._on_step_complete = on_step_complete

    def train(self) -> str:
        """Run GRPO training via TRL. Returns path to final checkpoint."""
        from datasets import Dataset
        from trl import GRPOConfig, GRPOTrainer as _TRLTrainer

        from openadapt_evals.task_config import TaskConfig
        from openadapt_evals.training.trl_rollout import make_waa_rollout_func

        # --- Tasks (from our config) ---
        task_configs = []
        if self._config.task_dir:
            task_configs = TaskConfig.from_dir(self._config.task_dir)

        # Filter by task_ids if specified — without this, ALL tasks from
        # task_dir end up in the TRL dataset regardless of what the user
        # requested. This was a critical bug: config had task_ids=["X"]
        # but TRL was running unrelated tasks.
        if getattr(self._config, "task_ids", None):
            allowed = set(self._config.task_ids)
            filtered = [tc for tc in task_configs if tc.id in allowed or tc.name in allowed]
            if filtered:
                task_configs = filtered
                logger.info(
                    "Filtered tasks by task_ids: %d/%d tasks selected",
                    len(filtered), len(task_configs) + len(filtered) - len(filtered),
                )
            else:
                logger.warning(
                    "task_ids=%s matched no tasks from task_dir=%s. "
                    "Available: %s. Using all tasks.",
                    self._config.task_ids, self._config.task_dir,
                    [tc.id for tc in task_configs],
                )

        if not task_configs:
            raise ValueError("No tasks. Set task_dir in TrainingConfig.")

        dataset = Dataset.from_dict({
            "prompt": [tc.name for tc in task_configs],
            "task_id": [tc.id for tc in task_configs],
        })

        # --- Model (from our config) ---
        if getattr(self._config, "use_unsloth", False):
            try:
                from unsloth import FastVisionModel
            except ImportError:
                raise ImportError(
                    "use_unsloth=True but unsloth is not installed. "
                    "Install with: pip install openadapt-evals[unsloth]"
                ) from None
            logger.info("Loading with Unsloth: %s", self._config.model_name)
            model, processor = FastVisionModel.from_pretrained(
                self._config.model_name,
                load_in_4bit=self._config.load_in_4bit,
                fast_inference=True,
                gpu_memory_utilization=0.6,
            )
            model = FastVisionModel.get_peft_model(
                model, r=self._config.lora_r, lora_alpha=self._config.lora_alpha,
                target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                                "gate_proj", "up_proj", "down_proj"],
            )
        else:
            from openadapt_evals.training.standalone.model_loader import (
                load_model_and_processor,
            )
            model, processor = load_model_and_processor(
                self._config.model_name,
                load_in_4bit=self._config.load_in_4bit,
                lora_r=self._config.lora_r,
                lora_alpha=self._config.lora_alpha,
                lora_checkpoint=getattr(self._config, "lora_checkpoint", None),
            )

        if self._on_model_loaded:
            self._on_model_loaded(model, processor)

        # --- Rollout function (from our config) ---
        from openadapt_evals.adapters.waa.live import WAALiveAdapter, WAALiveConfig
        adapter = WAALiveAdapter(WAALiveConfig(
            server_url=self._config.server_url,
            evaluate_url=getattr(self._config, "evaluate_url", None),
        ))
        rollout_func = make_waa_rollout_func(
            adapter=adapter,
            task_configs=task_configs,
            max_steps=self._config.max_steps_per_episode,
            constrained_decoding=getattr(self._config, "constrained_decoding", False),
            max_new_tokens=self._config.max_new_tokens,
            temperature=self._config.temperature,
        )

        # --- Reward ---
        def env_reward_fn(completions, **kwargs):
            return kwargs.get("env_reward", [0.0] * len(completions))

        # --- Callbacks ---
        callbacks = []

        try:
            from openadapt_evals.integrations.trl_callbacks import (
                DiagnosticsCallback,
                TelemetryCallback,
            )
            callbacks.append(TelemetryCallback())
            callbacks.append(DiagnosticsCallback())
        except ImportError:
            pass

        if any([self._on_before_collect, self._on_rollout_complete,
                self._on_step_complete]):
            try:
                from transformers import TrainerCallback

                class HookBridge(TrainerCallback):
                    def __init__(self, hooks):
                        self._hooks = hooks

                    def on_step_end(self, args, state, control, **kwargs):
                        fn = self._hooks.get("on_step_complete")
                        if fn:
                            fn(state.global_step, [], kwargs.get("metrics", {}))

                callbacks.append(HookBridge({
                    "on_before_collect": self._on_before_collect,
                    "on_rollout_complete": self._on_rollout_complete,
                    "on_step_complete": self._on_step_complete,
                }))
            except ImportError:
                pass

        # --- Weave tracing ---
        weave_project = getattr(self._config, "weave_project", "")
        if weave_project:
            try:
                from openadapt_evals.integrations.weave_integration import weave_init
                weave_init(weave_project)
            except Exception:
                pass

        # --- TRL config: use provided or build sensible defaults ---
        # CRITICAL: per_device_train_batch_size must be <= len(dataset).
        # TRL default is 8, but with 1-3 tasks the dataset is tiny.
        # If batch_size > dataset_size, TRL computes 0 steps and exits
        # with "There seems not to be a single sample in your epoch_iterator".
        n_tasks = len(task_configs)

        if self._trl_config is not None:
            trl_config = self._trl_config
            # Warn if user-provided config has batch_size > dataset
            bs = getattr(trl_config, "per_device_train_batch_size", 8)
            if bs > n_tasks:
                logger.warning(
                    "per_device_train_batch_size=%d > dataset size=%d. "
                    "TRL will compute 0 steps and exit immediately. "
                    "Set per_device_train_batch_size=%d or add more tasks.",
                    bs, n_tasks, n_tasks,
                )
        else:
            trl_config = GRPOConfig(
                output_dir=self._config.output_dir,
                num_generations=self._config.num_rollouts_per_step,
                max_completion_length=self._config.max_new_tokens,
                max_steps=self._config.num_training_steps,
                learning_rate=self._config.learning_rate,
                save_steps=self._config.save_every_steps,
                logging_steps=1,
                bf16=True,
                loss_type="grpo",
                num_train_epochs=1,
                # Match batch size to dataset: with few tasks (common in
                # RL training), the default of 8 causes 0 steps.
                per_device_train_batch_size=n_tasks,
            )

        # --- Train ---
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
            "Starting TRL GRPO: model=%s tasks=%d output=%s loss=%s",
            self._config.model_name, len(task_configs),
            trl_config.output_dir, trl_config.loss_type,
        )

        trainer.train()
        trainer.save_model(trl_config.output_dir)

        logger.info("Training complete. Checkpoint: %s", trl_config.output_dir)
        return trl_config.output_dir
