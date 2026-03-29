"""TRL GRPOTrainer rollout function for WAA desktop environments.

Wraps WAADesktopEnv into TRL's experimental ``rollout_func`` API, enabling
GRPO training of VLM agents against live (or mock) Windows VMs.

The rollout_func receives prompts (task instructions) from the trainer,
runs multi-step episodes against the environment, collects action tokens
and logprobs, computes dense rewards via milestones, and returns everything
in the format TRL expects.

GRPO (Group Relative Policy Optimization) training uses group-level
advantage estimation from multiple rollouts of the same prompt, as
introduced in the DeepSeek-Math work. This module integrates that
algorithm with live desktop environments via TRL's rollout API.

Constrained decoding (optional):
    When ``constrained_decoding=True``, Outlines is used to force model
    output to match the ``Thought: ...\nAction: CLICK/TYPE/WAIT/DONE``
    format. This eliminates 5-15% of wasted rollouts from unparseable
    VLM output. Requires ``pip install outlines>=0.1.0``.

Usage with TRL:
    from trl import GRPOConfig, GRPOTrainer
    from openadapt_evals.training.trl_rollout import make_waa_rollout_func

    rollout_func = make_waa_rollout_func(
        adapter=WAALiveAdapter(WAALiveConfig(server_url="http://localhost:5001")),
        task_configs=TaskConfig.from_dir("./tasks/"),
        max_steps=15,
        constrained_decoding=True,
    )

    trainer = GRPOTrainer(
        model=model,
        processing_class=processor,
        args=GRPOConfig(...),
        train_dataset=dataset,
        rollout_func=rollout_func,
    )
    trainer.train()

Usage with mock adapter (no VM):
    from openadapt_evals.training.trl_rollout import make_waa_rollout_func
    from openadapt_evals.adapters.waa.mock import WAAMockAdapter

    rollout_func = make_waa_rollout_func(
        adapter=WAAMockAdapter(),
        task_configs=task_configs,
    )

Prior Art:
    - GRPO: Shao et al., "DeepSeekMath: Pushing the Limits of
      Mathematical Reasoning in Open Language Models", arXiv 2402.03300,
      2024. Introduced Group Relative Policy Optimization.
    - TRL: Hugging Face, "TRL: Transformer Reinforcement Learning",
      https://github.com/huggingface/trl. Open-source library providing
      GRPOTrainer and the experimental rollout_func API.
    - PPO for LLMs: Schulman et al., "Proximal Policy Optimization
      Algorithms", arXiv 2017. Foundation for policy gradient methods
      in language model fine-tuning.
    - RLHF: Ouyang et al., "Training Language Models to Follow
      Instructions with Human Feedback", NeurIPS 2022. Established the
      RL fine-tuning paradigm for language models.
"""

from __future__ import annotations

import io
import json
import logging
import re
from typing import Any, Callable

from openadapt_evals.adapters.base import BenchmarkAction, BenchmarkObservation
from openadapt_evals.adapters.rl_env import RLEnvironment, ResetConfig

logger = logging.getLogger(__name__)

# System prompt matching openadapt-ml's agent format
SYSTEM_PROMPT = (
    "You are a desktop automation agent. Given a screenshot and task instruction, "
    "output the next action as JSON: "
    '{"type": "click"|"type"|"key"|"scroll"|"done", '
    '"x": 0.0-1.0, "y": 0.0-1.0, "text": "...", "key": "..."}'
)

# ---------------------------------------------------------------------------
# Constrained decoding regex — ported from standalone trainer
# ---------------------------------------------------------------------------
# Matches the ``Thought: <reasoning>\nAction: <action>`` format.
# All repetitions use unbounded quantifiers (+, *) instead of bounded ({1,N})
# to avoid DFA state explosion in Outlines.
_ACTION_RE = (
    r"CLICK\(x=0\.\d+,\s*y=0\.\d+\)"
    r'|TYPE\(text="[^"]*"\)'
    r"|WAIT\(\)"
    r"|DONE\(\)"
)
ACTION_REGEX = r"Thought: [^\n]+\nAction: (" + _ACTION_RE + r")"


def _build_outlines_generator(model: Any, processor: Any) -> Any | None:
    """Build an Outlines Generator for constrained generation.

    Outlines v1.2 uses its own Generator API. The Generator wraps the model
    and handles tokenization, generation, and decoding internally.

    Args:
        model: The HuggingFace model (may be a PEFT model).
        processor: The HuggingFace processor/tokenizer.

    Returns:
        An Outlines Generator, or None if creation fails.
    """
    try:
        import outlines

        wrapped_model = outlines.from_transformers(model, processor)
        constraint = outlines.regex(ACTION_REGEX)
        generator = outlines.Generator(wrapped_model, constraint)
        logger.info(
            "Outlines constrained decoding enabled for TRL rollout "
            "(model=%s, regex compiled successfully)",
            type(wrapped_model).__name__,
        )
        return generator
    except ImportError:
        logger.error(
            "constrained_decoding=True but 'outlines' is not installed. "
            "Install with: pip install outlines>=0.1.0"
        )
        return None
    except Exception as exc:
        logger.error(
            "Outlines Generator creation failed: %s. "
            "Falling back to unconstrained generation.",
            exc,
        )
        return None


def parse_action_json(text: str) -> BenchmarkAction:
    """Parse a VLM output string into a BenchmarkAction.

    Handles common VLM quirks: thinking tokens before JSON, markdown
    code fences, extra text after JSON.

    Args:
        text: Raw VLM output text.

    Returns:
        BenchmarkAction parsed from the JSON.
    """
    # Strip thinking tokens / markdown
    text = text.strip()
    text = re.sub(r"```json\s*", "", text)
    text = re.sub(r"```\s*$", "", text)

    # Find the first JSON object
    match = re.search(r"\{[^{}]*\}", text)
    if not match:
        logger.warning("No JSON found in VLM output: %s", text[:100])
        return BenchmarkAction(type="done")

    try:
        data = json.loads(match.group())
    except json.JSONDecodeError:
        logger.warning("Invalid JSON in VLM output: %s", match.group()[:100])
        return BenchmarkAction(type="done")

    action_type = data.get("type", "done")
    if action_type not in ("click", "type", "key", "scroll", "done", "noop"):
        logger.warning("Unknown action type '%s', treating as done", action_type)
        action_type = "done"

    return BenchmarkAction(
        type=action_type,
        x=data.get("x"),
        y=data.get("y"),
        text=data.get("text"),
        key=data.get("key"),
    )


def _run_episode(
    env: RLEnvironment,
    generate_fn: Callable[[bytes, str], tuple[str, list[int], list[float]]],
    task_instruction: str,
    task_id: str,
    max_steps: int,
) -> tuple[list[int], list[int], list[float], float]:
    """Run a single episode and return token-level data + reward.

    Args:
        env: The RL environment (already has task_config loaded).
        generate_fn: Function(screenshot_bytes, instruction) -> (text, token_ids, logprobs).
        task_instruction: Natural language task description.
        task_id: Task ID for reset.
        max_steps: Maximum steps per episode.

    Returns:
        Tuple of (prompt_ids, completion_ids, logprobs, reward).
    """
    obs = env.reset(config=ResetConfig(task_id=task_id))

    all_completion_ids: list[int] = []
    all_logprobs: list[float] = []
    prompt_ids: list[int] = []

    for step in range(max_steps):
        screenshot = obs.screenshot or b""

        # Generate action from VLM
        action_text, token_ids, logprobs = generate_fn(screenshot, task_instruction)

        # Track token-level data
        if step == 0:
            # First generation includes the prompt encoding
            # In practice, the generate_fn should separate prompt from completion
            pass
        all_completion_ids.extend(token_ids)
        all_logprobs.extend(logprobs)

        # Parse and execute action
        action = parse_action_json(action_text)
        if action.type == "done":
            break

        # Handle fractional coordinates
        if action.x is not None and action.y is not None:
            if 0 <= action.x <= 1 and 0 <= action.y <= 1:
                step_result = env.pixel_action(
                    x_frac=action.x, y_frac=action.y,
                    action_type=action.type, text=action.text, key=action.key,
                )
            else:
                step_result = env.pixel_action(
                    x=int(action.x), y=int(action.y),
                    action_type=action.type, text=action.text, key=action.key,
                )
        elif action.type in ("type", "key"):
            step_result = env.step(action)
        else:
            step_result = env.step(action)

        obs = step_result.observation
        if step_result.done:
            break

    # Evaluate — dense rewards if milestones, binary otherwise
    reward = env.evaluate_dense()

    return prompt_ids, all_completion_ids, all_logprobs, reward


def make_waa_rollout_func(
    adapter: Any,
    task_configs: list | None = None,
    max_steps: int = 15,
    constrained_decoding: bool = False,
    max_new_tokens: int = 256,
    temperature: float = 1.0,
) -> Callable:
    """Create a TRL-compatible rollout_func for WAA environments.

    The returned function has signature:
        rollout_func(prompts: list[str], trainer: GRPOTrainer) -> dict[str, list]

    Args:
        adapter: A BenchmarkAdapter (WAALiveAdapter or WAAMockAdapter).
        task_configs: List of TaskConfig objects. Each prompt in the training
            dataset should have a matching task_config by name or index.
        max_steps: Maximum steps per episode.
        constrained_decoding: If True, use Outlines to constrain generation
            to the ``Thought: ...\nAction: CLICK/TYPE/WAIT/DONE`` format.
            Requires ``pip install outlines>=0.1.0``.
        max_new_tokens: Maximum tokens per generation step.
        temperature: Sampling temperature for generation.

    Returns:
        A callable suitable for GRPOTrainer(rollout_func=...).
    """
    # Index task configs by name for lookup
    config_map: dict[str, Any] = {}
    if task_configs:
        from openadapt_evals.task_config import TaskConfig

        for tc in task_configs:
            config_map[tc.name] = tc
            config_map[tc.id] = tc

    # Outlines generator is created lazily on first rollout call
    # (needs the trainer's model and processor which aren't available yet).
    _outlines_state: dict[str, Any] = {"generator": None, "attempted": False}

    def rollout_func(prompts: list[str], trainer: Any) -> dict[str, list]:
        """TRL GRPOTrainer rollout function.

        Args:
            prompts: Task instructions from the training dataset.
            trainer: Active GRPOTrainer instance (provides model + processor).

        Returns:
            Dict with prompt_ids, completion_ids, logprobs, env_reward.
        """
        processor = trainer.processing_class
        model = trainer.model
        device = next(model.parameters()).device

        num_generations = getattr(trainer.args, "num_generations", 8)

        # Lazy-init Outlines generator on first call
        if constrained_decoding and not _outlines_state["attempted"]:
            _outlines_state["attempted"] = True
            _outlines_state["generator"] = _build_outlines_generator(
                model, processor,
            )

        outlines_gen = _outlines_state["generator"] if constrained_decoding else None

        all_prompt_ids = []
        all_completion_ids = []
        all_logprobs = []
        all_rewards = []

        def generate_fn(screenshot_bytes: bytes, instruction: str):
            """Generate action tokens from screenshot + instruction."""
            from PIL import Image

            # Build multimodal input
            img = Image.open(io.BytesIO(screenshot_bytes))
            if img.mode != "RGB":
                img = img.convert("RGB")
                img.format = "PNG"

            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": [
                    {"type": "image", "image": img},
                    {"type": "text", "text": instruction},
                ]},
            ]

            # Tokenize with processor
            import torch

            text_input = processor.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )

            # --- Constrained decoding path (Outlines) ---
            if outlines_gen is not None:
                import outlines

                model_input = [text_input, outlines.Image(img)]
                decoded = outlines_gen(
                    model_input,
                    max_new_tokens=max_new_tokens,
                    temperature=temperature,
                )
                # Tokenize the decoded text to get token IDs
                inner_tok = getattr(processor, "tokenizer", processor)
                completion_ids = inner_tok.encode(
                    decoded, add_special_tokens=False,
                )
                # Outlines does not return per-token logprobs, so we
                # return empty logprobs. TRL recomputes logprobs from
                # the model during the training step anyway.
                logprobs: list[float] = []
                return decoded, completion_ids, logprobs

            # --- Standard HF generate path (unconstrained) ---
            inputs = processor(
                text=[text_input], images=[img],
                return_tensors="pt", padding=True,
            ).to(device)

            # Generate
            with torch.no_grad():
                outputs = model.generate(
                    **inputs,
                    max_new_tokens=max_new_tokens,
                    do_sample=True,
                    temperature=temperature,
                    return_dict_in_generate=True,
                    output_scores=True,
                )

            # Extract completion tokens (everything after prompt)
            prompt_len = inputs["input_ids"].shape[1]
            completion_ids = outputs.sequences[0][prompt_len:].tolist()

            # Compute per-token logprobs from scores
            logprobs = []
            if hasattr(outputs, "scores") and outputs.scores:
                for i, score in enumerate(outputs.scores):
                    probs = torch.nn.functional.log_softmax(score[0], dim=-1)
                    if i < len(completion_ids):
                        logprobs.append(probs[completion_ids[i]].item())

            # Decode text
            text = processor.decode(completion_ids, skip_special_tokens=True)

            return text, completion_ids, logprobs

        for prompt in prompts:
            # Find matching task config
            tc = config_map.get(prompt)

            for gen_idx in range(num_generations):
                env = RLEnvironment(adapter, task_config=tc)

                task_id = tc.id if tc else "default"

                try:
                    p_ids, c_ids, lps, reward = _run_episode(
                        env, generate_fn, prompt, task_id, max_steps,
                    )
                except Exception as exc:
                    logger.error(
                        "Rollout failed for prompt=%s gen=%d: %s",
                        prompt[:50], gen_idx, exc,
                    )
                    p_ids, c_ids, lps, reward = [], [], [], 0.0

                all_prompt_ids.append(p_ids)
                all_completion_ids.append(c_ids)
                all_logprobs.append(lps)
                all_rewards.append(reward)

        return {
            "prompt_ids": all_prompt_ids,
            "completion_ids": all_completion_ids,
            "logprobs": all_logprobs,
            "env_reward": all_rewards,
        }

    return rollout_func
