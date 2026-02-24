"""Qwen3-VL agent for benchmark evaluation.

Uses Qwen3-VL-8B-Instruct (or fine-tuned variants) for local GUI agent
inference. Coordinates use the Qwen normalized [0, 1000] range and are
denormalized to [0, 1] for BenchmarkAction compatibility.

Action space (Qwen3-VL format):
    click(x=500, y=300)
    double_click(x=500, y=300)
    right_click(x=500, y=300)
    type(text="hello world")
    press(keys=["ctrl", "c"])
    scroll(direction="up", amount=3)
    drag(from_coord=[200, 300], to_coord=[800, 500])
    wait()
    finished()

Usage:
    from openadapt_evals.agents import Qwen3VLAgent

    agent = Qwen3VLAgent()
    action = agent.act(observation, task)

    # With demo conditioning
    agent = Qwen3VLAgent(demo="Step 0: click(x=450, y=950)...")
"""

from __future__ import annotations

import base64
import logging
import re
from io import BytesIO
from pathlib import Path
from typing import Any

from openadapt_evals.adapters.base import (
    BenchmarkAction,
    BenchmarkObservation,
    BenchmarkTask,
)
from openadapt_evals.agents.base import BenchmarkAgent

logger = logging.getLogger("openadapt_evals.agents.qwen3vl")

DEFAULT_MODEL = "Qwen/Qwen3-VL-8B-Instruct"

SYSTEM_PROMPT = (
    "You are a GUI agent. You observe screenshots of a desktop and output "
    "exactly one action per step. Use the following action format:\n"
    "click(x=<int>, y=<int>)\n"
    "double_click(x=<int>, y=<int>)\n"
    "right_click(x=<int>, y=<int>)\n"
    "type(text=\"<string>\")\n"
    "press(keys=[\"<key1>\", ...])\n"
    "scroll(direction=\"<up|down|left|right>\", amount=<int>)\n"
    "drag(from_coord=[<x1>, <y1>], to_coord=[<x2>, <y2>])\n"
    "wait()\n"
    "finished()\n\n"
    "Coordinates are in [0, 1000] range where (0,0) is top-left and "
    "(1000,1000) is bottom-right."
)

# Regex patterns for parsing Qwen3-VL action output
_RE_CLICK = re.compile(
    r"(?:click|left_click)\s*\(\s*x\s*=\s*(\d+)\s*,\s*y\s*=\s*(\d+)\s*\)",
    re.IGNORECASE,
)
_RE_DOUBLE_CLICK = re.compile(
    r"double_click\s*\(\s*x\s*=\s*(\d+)\s*,\s*y\s*=\s*(\d+)\s*\)",
    re.IGNORECASE,
)
_RE_RIGHT_CLICK = re.compile(
    r"right_click\s*\(\s*x\s*=\s*(\d+)\s*,\s*y\s*=\s*(\d+)\s*\)",
    re.IGNORECASE,
)
_RE_TYPE = re.compile(
    r"type\s*\(\s*text\s*=\s*[\"'](.+?)[\"']\s*\)",
    re.IGNORECASE,
)
_RE_PRESS = re.compile(
    r"press\s*\(\s*keys\s*=\s*\[([^\]]+)\]\s*\)",
    re.IGNORECASE,
)
_RE_SCROLL = re.compile(
    r"scroll\s*\(\s*direction\s*=\s*[\"'](\w+)[\"']\s*"
    r"(?:,\s*amount\s*=\s*(\d+)\s*)?\)",
    re.IGNORECASE,
)
_RE_DRAG = re.compile(
    r"drag\s*\(\s*from_coord\s*=\s*\[\s*(\d+)\s*,\s*(\d+)\s*\]\s*,"
    r"\s*to_coord\s*=\s*\[\s*(\d+)\s*,\s*(\d+)\s*\]\s*\)",
    re.IGNORECASE,
)
_RE_WAIT = re.compile(r"wait\s*\(\s*\)", re.IGNORECASE)
_RE_FINISHED = re.compile(r"finished\s*\(\s*\)", re.IGNORECASE)
_RE_THINK = re.compile(r"<think>(.*?)</think>", re.DOTALL)


def parse_qwen_action(response: str) -> BenchmarkAction:
    """Parse a Qwen3-VL action string into BenchmarkAction.

    Coordinates remain in [0, 1000] range — caller must denormalize.

    Args:
        response: Raw model output text.

    Returns:
        BenchmarkAction with coordinates in [0, 1000] range.
    """
    raw: dict[str, Any] = {"response": response}

    # Strip think blocks
    think_match = _RE_THINK.search(response)
    if think_match:
        raw["thinking"] = think_match.group(1).strip()
        response = _RE_THINK.sub("", response).strip()

    # finished()
    if _RE_FINISHED.search(response):
        return BenchmarkAction(type="done", raw_action=raw)

    # wait()
    if _RE_WAIT.search(response):
        raw["is_wait"] = True
        return BenchmarkAction(type="done", raw_action=raw)

    # double_click (check before click)
    m = _RE_DOUBLE_CLICK.search(response)
    if m:
        raw["click_variant"] = "double_click"
        return BenchmarkAction(
            type="click",
            x=float(m.group(1)),
            y=float(m.group(2)),
            raw_action=raw,
        )

    # right_click (check before click)
    m = _RE_RIGHT_CLICK.search(response)
    if m:
        raw["click_variant"] = "right_click"
        return BenchmarkAction(
            type="click",
            x=float(m.group(1)),
            y=float(m.group(2)),
            raw_action=raw,
        )

    # click
    m = _RE_CLICK.search(response)
    if m:
        return BenchmarkAction(
            type="click",
            x=float(m.group(1)),
            y=float(m.group(2)),
            raw_action=raw,
        )

    # type
    m = _RE_TYPE.search(response)
    if m:
        return BenchmarkAction(type="type", text=m.group(1), raw_action=raw)

    # press
    m = _RE_PRESS.search(response)
    if m:
        keys_str = m.group(1)
        keys = [k.strip().strip("\"'") for k in keys_str.split(",")]
        if len(keys) == 1:
            return BenchmarkAction(type="key", key=keys[0], raw_action=raw)
        return BenchmarkAction(
            type="key",
            key=keys[-1],
            modifiers=keys[:-1],
            raw_action=raw,
        )

    # scroll
    m = _RE_SCROLL.search(response)
    if m:
        direction = m.group(1).lower()
        amount = int(m.group(2)) if m.group(2) else 3
        return BenchmarkAction(
            type="scroll",
            scroll_direction=direction,
            scroll_amount=float(amount),
            raw_action=raw,
        )

    # drag
    m = _RE_DRAG.search(response)
    if m:
        return BenchmarkAction(
            type="drag",
            x=float(m.group(1)),
            y=float(m.group(2)),
            end_x=float(m.group(3)),
            end_y=float(m.group(4)),
            raw_action=raw,
        )

    # Could not parse
    raw["parse_error"] = "No action pattern found"
    return BenchmarkAction(type="done", raw_action=raw)


def denormalize_action(
    action: BenchmarkAction, viewport: tuple[int, int]
) -> BenchmarkAction:
    """Convert coordinates from [0, 1000] to normalized [0, 1].

    Args:
        action: Action with coordinates in [0, 1000] range.
        viewport: (width, height) of the display.

    Returns:
        New BenchmarkAction with coordinates in [0, 1] range.
    """
    x = action.x / 1000.0 if action.x is not None else None
    y = action.y / 1000.0 if action.y is not None else None
    end_x = action.end_x / 1000.0 if action.end_x is not None else None
    end_y = action.end_y / 1000.0 if action.end_y is not None else None

    return BenchmarkAction(
        type=action.type,
        x=x,
        y=y,
        end_x=end_x,
        end_y=end_y,
        text=action.text,
        key=action.key,
        modifiers=action.modifiers,
        scroll_direction=action.scroll_direction,
        scroll_amount=action.scroll_amount,
        target_node_id=action.target_node_id,
        target_bbox=action.target_bbox,
        target_role=action.target_role,
        target_name=action.target_name,
        answer=action.answer,
        raw_action=action.raw_action,
    )


class Qwen3VLAgent(BenchmarkAgent):
    """Agent using Qwen3-VL for local GUI agent inference.

    Loads the model via transformers and runs inference locally.
    Coordinates use the Qwen normalized [0, 1000] range internally
    and are converted to [0, 1] for BenchmarkAction output.

    Args:
        model_path: HuggingFace model ID or local checkpoint path.
        demo: Optional demonstration text for demo-conditioned inference.
        use_thinking: Enable thinking mode with <think> blocks.
        device: Torch device ('cuda', 'cpu', 'auto').
        max_new_tokens: Maximum tokens to generate per step.
    """

    def __init__(
        self,
        model_path: str | None = None,
        demo: str | None = None,
        use_thinking: bool = False,
        device: str = "auto",
        max_new_tokens: int = 512,
    ):
        self.model_path = model_path or DEFAULT_MODEL
        self.demo = demo
        self.use_thinking = use_thinking
        self.device = device
        self.max_new_tokens = max_new_tokens

        self._model = None
        self._processor = None
        self._step_count = 0
        self._action_history: list[str] = []

        logger.info(
            f"Qwen3VLAgent initialized: model={self.model_path}, "
            f"thinking={self.use_thinking}, device={self.device}"
        )
        if self.demo:
            logger.info(f"Demo provided ({len(self.demo)} chars)")

    def _load_model(self) -> None:
        """Lazy-load model and processor on first use."""
        if self._model is not None:
            return

        try:
            from transformers import AutoProcessor, Qwen2_5_VLForConditionalGeneration
        except ImportError:
            raise RuntimeError(
                "transformers package required. "
                "Install with: pip install transformers torch"
            )

        logger.info(f"Loading model: {self.model_path}")

        # Qwen3-VL uses the same architecture class as Qwen2.5-VL in transformers
        # The class may be Qwen2_5_VLForConditionalGeneration or
        # AutoModelForVision2Seq depending on transformers version
        try:
            from transformers import AutoModelForVision2Seq

            self._model = AutoModelForVision2Seq.from_pretrained(
                self.model_path,
                torch_dtype="auto",
                device_map=self.device,
            )
        except Exception:
            self._model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
                self.model_path,
                torch_dtype="auto",
                device_map=self.device,
            )

        self._processor = AutoProcessor.from_pretrained(self.model_path)
        logger.info("Model loaded successfully")

    def reset(self) -> None:
        """Reset agent state between episodes."""
        self._step_count = 0
        self._action_history = []

    def act(
        self,
        observation: BenchmarkObservation,
        task: BenchmarkTask,
        history: list[tuple[BenchmarkObservation, BenchmarkAction]] | None = None,
    ) -> BenchmarkAction:
        """Given observation and task, return next action.

        Args:
            observation: Current observation from the environment.
            task: Task being performed.
            history: Optional list of previous (observation, action) pairs.

        Returns:
            Action to execute with coordinates in [0, 1] range.
        """
        self._load_model()
        self._step_count += 1

        prompt = self._build_prompt(observation, task, history)
        image = self._get_image(observation)
        response = self._run_inference(prompt, image)

        logger.debug(f"Step {self._step_count} response: {response}")

        action = parse_qwen_action(response)

        # Track action history for next prompt
        self._action_history.append(response.strip())

        # Denormalize coordinates from [0, 1000] to [0, 1]
        viewport = observation.viewport or (1280, 720)
        if action.type in ("click", "drag") and action.x is not None:
            action = denormalize_action(action, viewport)

        return action

    def _build_prompt(
        self,
        observation: BenchmarkObservation,
        task: BenchmarkTask,
        history: list[tuple[BenchmarkObservation, BenchmarkAction]] | None = None,
    ) -> str:
        """Build the user turn text for inference.

        The format is aligned with the training data produced by
        convert_demos.py so the model sees the same structure at
        training and inference time. The system prompt is added
        separately in _run_inference().

        Args:
            observation: Current observation.
            task: Current task.
            history: Optional action history.

        Returns:
            Formatted user turn string.
        """
        parts = []

        # Demo injection (inference-only; not present in training data)
        if self.demo:
            parts.append(
                "Here is a demonstration of a similar completed task:\n"
            )
            parts.append(self.demo)
            parts.append("")
            parts.append("Now complete this task:")

        parts.append(f"Instruction: {task.instruction}")

        # Action history
        if self._action_history:
            parts.append("")
            parts.append("Previous actions:")
            for i, act_str in enumerate(self._action_history):
                parts.append(f"  Step {i}: {act_str}")

        parts.append("")
        if self.use_thinking:
            parts.append(
                "First reason about what you see in <think>...</think> "
                "tags, then output exactly one action."
            )
        else:
            parts.append("Output exactly one action.")

        return "\n".join(parts)

    def _get_image(self, observation: BenchmarkObservation):
        """Extract PIL Image from observation.

        Args:
            observation: Current observation.

        Returns:
            PIL Image or None.
        """
        from PIL import Image

        screenshot_bytes = observation.screenshot
        if screenshot_bytes is None and observation.screenshot_path:
            try:
                screenshot_bytes = Path(observation.screenshot_path).read_bytes()
            except (FileNotFoundError, OSError):
                pass

        if screenshot_bytes is None:
            return None

        return Image.open(BytesIO(screenshot_bytes)).convert("RGB")

    def _run_inference(self, prompt: str, image) -> str:
        """Run model inference.

        Args:
            prompt: User turn text (from _build_prompt).
            image: PIL Image or None.

        Returns:
            Generated text response.
        """
        # Build messages in the Qwen VL chat format with system role
        content: list[dict[str, Any]] = []
        if image is not None:
            content.append({"type": "image", "image": image})
        content.append({"type": "text", "text": prompt})

        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": content},
        ]

        text = self._processor.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )

        if image is not None:
            from qwen_vl_utils import process_vision_info

            image_inputs, video_inputs = process_vision_info(messages)
            inputs = self._processor(
                text=[text],
                images=image_inputs,
                videos=video_inputs,
                padding=True,
                return_tensors="pt",
            )
        else:
            inputs = self._processor(
                text=[text],
                padding=True,
                return_tensors="pt",
            )

        inputs = inputs.to(self._model.device)

        generated_ids = self._model.generate(
            **inputs,
            max_new_tokens=self.max_new_tokens,
        )

        # Trim prompt tokens from output
        generated_ids_trimmed = [
            out_ids[len(in_ids):]
            for in_ids, out_ids in zip(inputs.input_ids, generated_ids)
        ]

        output = self._processor.batch_decode(
            generated_ids_trimmed,
            skip_special_tokens=True,
            clean_up_tokenization_spaces=False,
        )

        return output[0] if output else ""
