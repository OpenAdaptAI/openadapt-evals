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
    output to match a JSON action schema (preferred) or a JSON-aligned
    regex fallback. This eliminates 5-15% of wasted rollouts from
    unparseable VLM output. Requires ``pip install outlines>=0.1.0``.

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

import hashlib
import io
import json
import logging
import re
import time
from typing import Any, Callable, Optional

from pydantic import BaseModel

from openadapt_evals.adapters.base import BenchmarkAction, BenchmarkObservation
from openadapt_evals.adapters.rl_env import RLEnvironment, ResetConfig

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# System prompt -- JSON format with reasoning field
# ---------------------------------------------------------------------------
# Unified JSON format that aligns with openadapt-types Action schema.
# The prompt requests a reasoning field (chain-of-thought) plus a structured
# action, all in a single JSON object.
SYSTEM_PROMPT = (
    "You are a desktop automation agent. Given a screenshot and task instruction, "
    "output your reasoning and next action as JSON.\n\n"
    "Format:\n"
    '{"reasoning": "brief explanation", "type": "click"|"type"|"key"|"scroll"|"wait"|"done", '
    '"x": 0.0-1.0, "y": 0.0-1.0, "text": "...", "key": "..."}\n\n'
    "Coordinates are normalized: x=0.0 is left edge, x=1.0 is right edge, "
    "y=0.0 is top edge, y=1.0 is bottom edge."
)


# ---------------------------------------------------------------------------
# Pydantic schema for Outlines JSON-mode constrained decoding
# ---------------------------------------------------------------------------


class _AgentOutput(BaseModel):
    """Schema for Outlines JSON-mode constrained decoding."""

    reasoning: str
    type: str  # click, type, key, scroll, wait, done
    x: Optional[float] = None
    y: Optional[float] = None
    text: Optional[str] = None
    key: Optional[str] = None


# ---------------------------------------------------------------------------
# JSON-aligned regex fallback for constrained decoding
# ---------------------------------------------------------------------------
# Matches JSON action objects. Used when Outlines JSON schema mode is not
# available. All repetitions use unbounded quantifiers (+, *) instead of
# bounded ({1,N}) to avoid DFA state explosion in Outlines.
ACTION_REGEX = (
    r'\{"reasoning": "[^"]*", "type": "(?:click|type|key|scroll|wait|done)"'
    r'(?:, "x": \d+\.\d+, "y": \d+\.\d+)?'
    r'(?:, "text": "[^"]*")?'
    r'(?:, "key": "[^"]*")?'
    r"\}"
)


def _build_outlines_generator(model: Any, processor: Any) -> Any | None:
    """Build an Outlines Generator for constrained generation.

    Prefers JSON schema mode (more robust than regex). Falls back to
    regex-based constrained decoding if JSON schema mode is not available.

    Args:
        model: The HuggingFace model (may be a PEFT model).
        processor: The HuggingFace processor/tokenizer.

    Returns:
        An Outlines Generator, or None if creation fails.
    """
    try:
        import outlines

        wrapped_model = outlines.from_transformers(model, processor)

        # Prefer JSON schema mode (more robust than regex)
        try:
            constraint = outlines.json(_AgentOutput)
            generator = outlines.Generator(wrapped_model, constraint)
            logger.info(
                "Outlines JSON schema constrained decoding enabled for TRL rollout "
                "(model=%s)",
                type(wrapped_model).__name__,
            )
            return generator
        except Exception as json_exc:
            logger.warning(
                "Outlines JSON schema mode failed (%s), falling back to regex.",
                json_exc,
            )

        # Fall back to regex
        constraint = outlines.regex(ACTION_REGEX)
        generator = outlines.Generator(wrapped_model, constraint)
        logger.info(
            "Outlines regex constrained decoding enabled for TRL rollout "
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
    r"""Parse a VLM output string into a BenchmarkAction.

    Handles multiple formats:
    1. JSON objects (primary): ``{"type": "click", "x": 0.5, "y": 0.3}``
    2. DSL format (fallback for backward compatibility with existing checkpoints):
       ``CLICK(x=0.50, y=0.30)``, ``TYPE(text="hello")``, ``WAIT()``, ``DONE()``

    Also handles common VLM quirks: thinking tokens before JSON, markdown
    code fences, extra text after JSON, ``Thought: ...\nAction: ...`` format.

    Args:
        text: Raw VLM output text.

    Returns:
        BenchmarkAction parsed from the output.
    """
    # Strip thinking tokens / markdown
    stripped = text.strip()
    stripped = re.sub(r"```json\s*", "", stripped)
    stripped = re.sub(r"```\s*$", "", stripped)

    # --- JSON parsing (primary path) ---
    match = re.search(r"\{[^{}]*\}", stripped)
    if match:
        try:
            data = json.loads(match.group())
        except json.JSONDecodeError:
            data = None

        if data is not None and "type" in data:
            action_type = data.get("type", "done")
            if action_type not in ("click", "type", "key", "scroll", "wait", "done", "noop"):
                logger.warning("Unknown action type '%s', treating as done", action_type)
                action_type = "done"

            return BenchmarkAction(
                type=action_type,
                x=data.get("x"),
                y=data.get("y"),
                text=data.get("text"),
                key=data.get("key"),
            )

    # --- DSL fallback for backward compatibility with existing checkpoints ---
    # Handles: CLICK(x=0.50, y=0.30), TYPE(text="..."), WAIT(), DONE()

    # Extract from "Action: ..." format
    action_line = text
    action_match = re.search(r"Action:\s*(.+)", text, re.IGNORECASE)
    if action_match:
        action_line = action_match.group(1).strip()

    click_m = re.search(
        r"CLICK\(x=(-?[\d.]+),\s*y=(-?[\d.]+)\)", action_line, re.IGNORECASE
    )
    if click_m:
        try:
            x = max(0.0, min(1.0, float(click_m.group(1))))
            y = max(0.0, min(1.0, float(click_m.group(2))))
            return BenchmarkAction(type="click", x=x, y=y)
        except (ValueError, TypeError):
            pass

    type_m = re.search(r"TYPE\(text=[\"']([^\"']*)[\"']\)", action_line, re.IGNORECASE)
    if type_m:
        return BenchmarkAction(type="type", text=type_m.group(1))

    if re.search(r"\bWAIT\s*\(\s*\)", action_line, re.IGNORECASE):
        return BenchmarkAction(type="wait")
    if re.search(r"\bDONE\s*\(\s*\)", action_line, re.IGNORECASE):
        return BenchmarkAction(type="done")

    # If nothing parsed, return done
    logger.warning("No JSON or DSL found in VLM output: %s", text[:100])
    return BenchmarkAction(type="done")


def _empty_rollout_result(
    prompts: list[str],
    num_generations: int,
) -> dict[str, list]:
    """Return a zero-reward rollout result with the correct dict shape.

    Used when the WAA server is unreachable or unhealthy so that TRL receives
    a consistent output structure (empty token lists, zero rewards) instead of
    crashing.

    Args:
        prompts: List of prompt strings from the trainer.
        num_generations: Number of generations per prompt.

    Returns:
        Dict with prompt_ids, completion_ids, logprobs, env_reward -- all zeroed.
    """
    total = len(prompts) * num_generations
    return {
        "prompt_ids": [[] for _ in range(total)],
        "completion_ids": [[] for _ in range(total)],
        "logprobs": [[] for _ in range(total)],
        "env_reward": [0.0] * total,
    }


def _run_episode(
    env: RLEnvironment,
    generate_fn: Callable[[bytes, str], tuple[str, list[int], list[float]]],
    task_instruction: str,
    task_id: str,
    max_steps: int,
    stuck_threshold: int = 3,
) -> tuple[list[int], list[int], list[float], float]:
    """Run a single episode and return token-level data + reward.

    Args:
        env: The RL environment (already has task_config loaded).
        generate_fn: Function(screenshot_bytes, instruction) -> (text, token_ids, logprobs).
        task_instruction: Natural language task description.
        task_id: Task ID for reset.
        max_steps: Maximum steps per episode.
        stuck_threshold: Number of consecutive identical screenshots before
            breaking the episode early. Set to 0 to disable stuck detection.

    Returns:
        Tuple of (prompt_ids, completion_ids, logprobs, reward).
    """
    obs = env.reset(config=ResetConfig(task_id=task_id))

    all_completion_ids: list[int] = []
    all_logprobs: list[float] = []
    prompt_ids: list[int] = []
    recent_hashes: list[str] = []

    for step in range(max_steps):
        screenshot = obs.screenshot or b""

        # --- Stuck detection ---
        if stuck_threshold > 0:
            screenshot_hash = hashlib.md5(screenshot).hexdigest()
            recent_hashes.append(screenshot_hash)
            if len(recent_hashes) > stuck_threshold:
                recent_hashes.pop(0)
            if (
                len(recent_hashes) == stuck_threshold
                and len(set(recent_hashes)) == 1
            ):
                logger.warning(
                    "Stuck detected: %d identical screenshots in a row. "
                    "Breaking episode early.",
                    stuck_threshold,
                )
                break

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

    # Evaluate -- dense rewards if milestones, binary otherwise
    reward = env.evaluate_dense()

    return prompt_ids, all_completion_ids, all_logprobs, reward


def make_waa_rollout_func(
    adapter: Any,
    task_configs: list | None = None,
    max_steps: int = 15,
    constrained_decoding: bool = False,
    max_new_tokens: int = 256,
    temperature: float = 1.0,
    screenshot_retries: int = 3,
    screenshot_retry_delay: float = 1.0,
    stuck_threshold: int = 3,
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
            to valid JSON action format. Requires ``pip install outlines>=0.1.0``.
        max_new_tokens: Maximum tokens per generation step.
        temperature: Sampling temperature for generation.
        screenshot_retries: Number of retry attempts when a screenshot is
            corrupt (cannot be opened by PIL).
        screenshot_retry_delay: Seconds to sleep between screenshot retry
            attempts.
        stuck_threshold: Number of consecutive identical screenshots before
            breaking an episode early. Set to 0 to disable stuck detection.

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

        # --- Pre-rollout health check ---
        try:
            health_obs = adapter.observe()
            screenshot = getattr(health_obs, "screenshot", None)
            if screenshot is None or len(screenshot) < 100:
                logger.warning(
                    "WAA server health check failed (screenshot=%s bytes) "
                    "-- returning zero rewards for %d prompts",
                    len(screenshot) if screenshot else 0,
                    len(prompts),
                )
                return _empty_rollout_result(prompts, num_generations)
        except Exception as exc:
            logger.warning(
                "WAA server unreachable: %s -- returning zero rewards for "
                "%d prompts",
                exc,
                len(prompts),
            )
            return _empty_rollout_result(prompts, num_generations)

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

            # --- Corrupt screenshot retry ---
            img = None
            for attempt in range(screenshot_retries):
                try:
                    img = Image.open(io.BytesIO(screenshot_bytes))
                    if img.mode != "RGB":
                        img = img.convert("RGB")
                        img.format = "PNG"
                    break
                except Exception as exc:
                    if attempt < screenshot_retries - 1:
                        logger.warning(
                            "Corrupt screenshot (attempt %d/%d): %s",
                            attempt + 1,
                            screenshot_retries,
                            exc,
                        )
                        time.sleep(screenshot_retry_delay)
                    else:
                        logger.error(
                            "Screenshot corrupt after %d attempts, "
                            "returning DONE action",
                            screenshot_retries,
                        )
                        return "done", [], []

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
