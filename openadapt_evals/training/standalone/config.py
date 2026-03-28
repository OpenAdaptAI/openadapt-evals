"""Training configuration for standalone GRPO trainer."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TrainingConfig:
    """Configuration for standalone GRPO training."""

    model_name: str = "Qwen/Qwen2.5-VL-7B-Instruct"
    load_in_4bit: bool = True
    lora_r: int = 16
    lora_alpha: int = 32
    lora_checkpoint: str | None = None
    num_rollouts_per_step: int = 8
    max_steps_per_episode: int = 15
    temperature: float = 0.7
    # Maximum tokens the model may generate per action step.
    # VRAM recommendations (Qwen2.5-VL-7B, 4-bit LoRA, single image):
    #   - L40S  48 GB  →  512 (default, sufficient for Thought + Action)
    #   - A100  80 GB  →  1024–2048
    #   - H100  80 GB  →  2048+
    # Values above 512 on ≤48 GB GPUs will likely OOM during the loss
    # backward pass.  If you see truncation warnings at runtime, increase
    # this value AND move to a larger GPU.
    max_new_tokens: int = 512

    # Vision tensor handling during the loss forward pass.
    # "exclude"    – (default) strip vision tensors; log-probs are text-only.
    #                Safe on ≤48 GB GPUs.
    # "include"    – keep vision tensors; full multimodal backward. May OOM
    #                on < 80 GB VRAM.
    # "checkpoint" – gradient-checkpoint the vision encoder to cut peak VRAM.
    vision_loss_mode: str = "exclude"

    server_url: str = "http://localhost:5001"
    task_ids: list[str] = field(default_factory=list)
    task_dir: str | None = None
    screen_size: tuple[int, int] = (1920, 1080)
    stuck_window: int = 3
    learning_rate: float = 5e-6
    num_training_steps: int = 1000
    save_every_steps: int = 50
    output_dir: str = "checkpoints/grpo"
    eval_model: str = "gpt-4.1-mini"
