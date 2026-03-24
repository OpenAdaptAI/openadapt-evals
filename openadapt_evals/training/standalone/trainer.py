"""Standalone GRPO trainer: rollout collection + training loop.

REINFORCE with group-relative advantages. Direct HTTP to WAA,
standard HF+PEFT, standalone loss math. NO openadapt-ml imports.

Usage:
    python -m openadapt_evals.training.standalone.trainer \\
        --task-dir example_tasks --server-url http://localhost:5001 \\
        --model Qwen/Qwen3.5-9B --num-steps 10 --output checkpoints/
"""

from __future__ import annotations

import argparse
import io
import logging
import time
from pathlib import Path
from typing import Any

from PIL import Image

from openadapt_evals.training.standalone.config import TrainingConfig
from openadapt_evals.training.standalone.model_loader import load_model_and_processor
from openadapt_evals.training.standalone.prompt import (
    build_agent_messages, format_action_as_text, parse_vlm_output_to_action,
)
from openadapt_evals.training.standalone.reward import (
    compute_group_advantages, evaluate_milestones_screenshot,
)
from openadapt_evals.training.standalone.waa_direct import Rollout, RolloutStep, WAADirect

logger = logging.getLogger(__name__)


def policy_gradient_loss(current_logps, old_logps, advantages, epsilon=0.2):
    """PPO-clipped policy gradient. Single-epoch: reduces to REINFORCE."""
    import torch
    ratio = torch.exp(current_logps - old_logps)
    clipped = torch.clamp(ratio, 1 - epsilon, 1 + epsilon)
    return -torch.min(ratio * advantages, clipped * advantages).mean()


class GRPOTrainer:
    """Standalone GRPO trainer with direct WAA HTTP integration."""

    def __init__(self, config: TrainingConfig) -> None:
        self._config = config
        self._model: Any = None
        self._processor: Any = None
        self._optimizer: Any = None
        self._env: WAADirect | None = None
        self._task_configs: dict[str, Any] = {}

    def _load_task_configs(self) -> None:
        """Load TaskConfig YAMLs from task_dir."""
        if not self._config.task_dir:
            return
        from openadapt_evals.task_config import TaskConfig
        task_dir = Path(self._config.task_dir)
        if not task_dir.exists():
            logger.warning("Task dir not found: %s", task_dir)
            return
        for tc in TaskConfig.from_dir(str(task_dir)):
            self._task_configs[tc.id] = tc
            if not self._config.task_ids:
                self._config.task_ids.append(tc.id)
        logger.info("Loaded %d task configs from %s", len(self._task_configs), task_dir)

    def _collect_rollout(self, task_id: str, instruction: str) -> Rollout:
        """Collect one rollout: screenshot -> generate -> execute loop."""
        import torch
        assert self._env is not None
        rollout = Rollout(task_id=task_id, instruction=instruction)
        recent: list[bytes] = []

        for step_idx in range(self._config.max_steps_per_episode):
            # screenshot() already has built-in retry (3 attempts by default)
            try:
                screenshot = self._env.screenshot()
            except Exception as e:
                logger.warning(
                    "Screenshot failed at step %d after retries: %s", step_idx, e,
                )
                break
            recent.append(screenshot)
            if self._env.is_stuck(recent, window=self._config.stuck_window):
                logger.info("Stuck at step %d", step_idx)
                break

            image = Image.open(io.BytesIO(screenshot)).convert("RGB")
            messages = build_agent_messages(instruction, include_image=True)
            if hasattr(self._processor, "apply_chat_template"):
                text_input = self._processor.apply_chat_template(
                    messages, tokenize=False, add_generation_prompt=True)
            else:
                text_input = messages[-1]["content"]

            inputs = self._processor(text=[text_input], images=[image], return_tensors="pt")
            inputs = {k: v.to(self._model.device) for k, v in inputs.items()}
            with torch.no_grad():
                outputs = self._model.generate(
                    **inputs, max_new_tokens=self._config.max_new_tokens,
                    temperature=self._config.temperature, do_sample=True)
            decoded = self._processor.decode(
                outputs[0][inputs["input_ids"].shape[1]:], skip_special_tokens=True)
            gen_len = outputs[0].shape[0] - inputs["input_ids"].shape[1]
            if gen_len >= self._config.max_new_tokens - 1:
                logger.warning("Hit max_new_tokens=%d -- output may be truncated.", self._config.max_new_tokens)

            action = parse_vlm_output_to_action(decoded, screen_size=self._config.screen_size)
            rollout.steps.append(RolloutStep(screenshot=screenshot, action=action, raw_text=decoded))
            if action.type == "done":
                break
            self._env.execute_action(action)
            time.sleep(0.5)

        # Fresh screenshot for evaluation
        tc = self._task_configs.get(task_id)
        if tc and getattr(tc, "milestones", None):
            try:
                rollout.reward = evaluate_milestones_screenshot(
                    tc, self._env.screenshot(), model=self._config.eval_model)
            except Exception as e:
                logger.warning("Milestone eval failed: %s", e)
        return rollout

    def _collect_group(self, task_id: str) -> list[Rollout]:
        """Collect N rollouts for one GRPO gradient step."""
        assert self._env is not None

        # Pre-rollout health check: verify WAA is responsive before committing
        # to a full group of rollouts (avoids wasting time on a dead server).
        probe = self._env.probe()
        if not probe.get("screenshot_ok"):
            logger.error(
                "Pre-rollout health check FAILED for task %s: %s — "
                "skipping group (returning empty rollouts)",
                task_id, probe,
            )
            return []

        tc = self._task_configs.get(task_id)
        instruction = getattr(tc, "name", "") or task_id if tc else task_id
        if tc and self._env:
            raw_config = getattr(tc, "raw_config", {})
            if raw_config:
                self._env.setup_task(raw_config)

        rollouts = []
        for i in range(self._config.num_rollouts_per_step):
            logger.info("Rollout %d/%d for %s", i + 1, self._config.num_rollouts_per_step, task_id)
            r = self._collect_rollout(task_id, instruction)
            rollouts.append(r)
            logger.info("Rollout %d: %d steps, reward=%.2f", i + 1, len(r.steps), r.reward)
        return rollouts

    def _compute_rollout_loss(self, rollout: Rollout, advantage: float, scale: float) -> float:
        """Compute GRPO loss for one rollout. Per-step backward to avoid OOM."""
        import torch
        device = next(self._model.parameters()).device
        valid = [s for s in rollout.steps if s.screenshot]
        if not valid:
            return 0.0
        total, n = 0.0, len(valid)

        for step in valid:
            try:
                image = Image.open(io.BytesIO(step.screenshot)).convert("RGB")
            except Exception:
                continue
            messages = build_agent_messages(rollout.instruction, include_image=True)
            action_text = step.raw_text or format_action_as_text(step.action, self._config.screen_size)

            if hasattr(self._processor, "apply_chat_template"):
                text_input = self._processor.apply_chat_template(
                    messages, tokenize=False, add_generation_prompt=True)
            else:
                text_input = messages[-1]["content"]

            prompt_inputs = self._processor(text=[text_input], images=[image], return_tensors="pt")
            prompt_len = prompt_inputs["input_ids"].shape[1]
            inner_tok = getattr(self._processor, "tokenizer", self._processor)
            action_ids = inner_tok(action_text, return_tensors="pt", add_special_tokens=False)["input_ids"]
            if action_ids.shape[1] <= 0:
                continue

            full_ids = torch.cat([prompt_inputs["input_ids"], action_ids.to(prompt_inputs["input_ids"].device)], dim=1)
            full_inputs = dict(prompt_inputs)
            full_inputs["input_ids"] = full_ids
            full_inputs["attention_mask"] = torch.ones_like(full_ids)
            full_inputs = {k: v.to(device) for k, v in full_inputs.items()}

            outputs = self._model(**full_inputs)
            al = outputs.logits[:, prompt_len - 1: prompt_len - 1 + action_ids.shape[1], :]
            lp = torch.nn.functional.log_softmax(al, dim=-1)
            tlp = lp.gather(2, full_ids[:, prompt_len: prompt_len + action_ids.shape[1]].unsqueeze(-1).to(device)).squeeze(-1)
            slp = tlp.sum()
            adv = torch.tensor(advantage, device=device, dtype=slp.dtype)
            loss = policy_gradient_loss(slp.unsqueeze(0), slp.detach().unsqueeze(0), adv.unsqueeze(0))
            (loss * scale / n).backward()
            total += loss.detach().item()
        return total / max(n, 1)

    def _training_step(self, rollouts: list[Rollout]) -> dict[str, float]:
        """Single GRPO gradient step."""
        import torch
        rewards = [r.reward for r in rollouts]
        advantages = compute_group_advantages(rewards)
        reward_mean = sum(rewards) / len(rewards) if rewards else 0.0
        valid = [(r, a) for r, a in zip(rollouts, advantages) if abs(a) >= 1e-8]
        if not valid:
            return {"reward_mean": reward_mean, "loss": 0.0, "skipped": True}

        self._optimizer.zero_grad()
        n = len(valid)
        total = sum(self._compute_rollout_loss(r, a, 1.0 / n) for r, a in valid)
        torch.nn.utils.clip_grad_norm_(
            [p for p in self._model.parameters() if p.requires_grad], max_norm=1.0)
        self._optimizer.step()
        return {"reward_mean": reward_mean, "loss": total / max(n, 1),
                "skipped": False, "num_rollouts": len(rollouts), "num_gradient_terms": n}

    def _save_checkpoint(self, step: int) -> str:
        ckpt = Path(self._config.output_dir) / f"step_{step}"
        ckpt.mkdir(parents=True, exist_ok=True)
        self._model.save_pretrained(str(ckpt))
        logger.info("Saved checkpoint to %s", ckpt)
        return str(ckpt)

    def train(self) -> str:
        """Run GRPO training loop. Returns path to final checkpoint."""
        import torch
        self._load_task_configs()
        if not self._config.task_ids:
            raise ValueError("No task IDs. Provide --task-dir with YAML configs or set task_ids.")

        logger.info("Starting standalone GRPO | model=%s tasks=%s steps=%d rollouts/step=%d max_tokens=%d",
                     self._config.model_name, self._config.task_ids,
                     self._config.num_training_steps, self._config.num_rollouts_per_step,
                     self._config.max_new_tokens)

        self._model, self._processor = load_model_and_processor(
            self._config.model_name, load_in_4bit=self._config.load_in_4bit,
            lora_r=self._config.lora_r, lora_alpha=self._config.lora_alpha,
            lora_checkpoint=self._config.lora_checkpoint)
        self._optimizer = torch.optim.AdamW(
            [p for p in self._model.parameters() if p.requires_grad], lr=self._config.learning_rate)
        self._env = WAADirect(server_url=self._config.server_url, screen_size=self._config.screen_size)
        if not self._env.health_check():
            raise ConnectionError(f"WAA server not reachable at {self._config.server_url}")

        Path(self._config.output_dir).mkdir(parents=True, exist_ok=True)
        t0 = time.time()
        for step in range(self._config.num_training_steps):
            ts = time.time()
            task_id = self._config.task_ids[step % len(self._config.task_ids)]
            self._model.eval()
            rollouts = self._collect_group(task_id)
            self._model.train()
            if not rollouts:
                logger.warning(
                    "Step %d/%d: no rollouts collected (server may be down), skipping.",
                    step + 1, self._config.num_training_steps,
                )
                continue
            m = self._training_step(rollouts)
            m.update({"step": step, "task_id": task_id, "elapsed": time.time() - t0, "step_time": time.time() - ts})
            logger.info("Step %d/%d: reward=%.2f loss=%.4f time=%.1fs",
                        step + 1, self._config.num_training_steps, m.get("reward_mean", 0), m.get("loss", 0), m["step_time"])
            if (step + 1) % self._config.save_every_steps == 0:
                self._save_checkpoint(step + 1)

        self._save_checkpoint(self._config.num_training_steps)
        final = str(Path(self._config.output_dir) / f"step_{self._config.num_training_steps}")
        logger.info("Training complete. Final checkpoint: %s", final)
        return final


def main() -> None:
    """CLI entry point."""
    p = argparse.ArgumentParser(description="Standalone GRPO trainer for WAA")
    p.add_argument("--task-dir", required=True, help="Directory of TaskConfig YAMLs")
    p.add_argument("--server-url", default="http://localhost:5001")
    p.add_argument("--model", default="Qwen/Qwen2.5-VL-7B-Instruct")
    p.add_argument("--lora-checkpoint", default=None)
    p.add_argument("--num-steps", type=int, default=10)
    p.add_argument("--num-rollouts", type=int, default=8)
    p.add_argument("--output", default="checkpoints/grpo")
    p.add_argument("--no-4bit", action="store_true")
    p.add_argument("--eval-model", default="gpt-4.1-mini")
    a = p.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    config = TrainingConfig(
        model_name=a.model, load_in_4bit=not a.no_4bit, lora_checkpoint=a.lora_checkpoint,
        server_url=a.server_url, task_dir=a.task_dir, num_training_steps=a.num_steps,
        num_rollouts_per_step=a.num_rollouts, output_dir=a.output, eval_model=a.eval_model)
    GRPOTrainer(config).train()


if __name__ == "__main__":
    main()
