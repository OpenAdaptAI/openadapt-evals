"""Qwen3-VL agent for benchmark evaluation.

Uses Qwen3-VL-8B-Instruct (or fine-tuned variants) for local GUI agent
inference. Coordinates use the Qwen normalized [0, 1000] range and are
denormalized to [0, 1] for BenchmarkAction compatibility.

The prompt format is aligned with the training data produced by
``openadapt_ml.training.convert_demos`` so that fine-tuned checkpoints
see the same structure at inference time.

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

    # Fine-tuned checkpoint
    agent = Qwen3VLAgent(model_path="/path/to/finetuned/checkpoint")
"""

from __future__ import annotations

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

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DEFAULT_MODEL = "Qwen/Qwen3-VL-8B-Instruct"

# Coordinate scale used by Qwen3-VL
QWEN_COORD_SCALE = 1000

# System prompt — MUST match openadapt_ml.training.convert_demos.SYSTEM_PROMPT
SYSTEM_PROMPT = (
    "You are a GUI agent. You observe screenshots of a desktop and output "
    "exactly one action per step. Use the following action format:\n"
    "click(x=<int>, y=<int>)\n"
    "double_click(x=<int>, y=<int>)\n"
    "right_click(x=<int>, y=<int>)\n"
    'type(text="<string>")\n'
    'press(keys=["<key1>", ...])\n'
    'scroll(direction="<up|down|left|right>", amount=<int>)\n'
    "drag(from_coord=[<x1>, <y1>], to_coord=[<x2>, <y2>])\n"
    "wait()\n"
    "finished()\n\n"
    "Coordinates are in [0, 1000] range where (0,0) is top-left and "
    "(1000,1000) is bottom-right."
)

# ---------------------------------------------------------------------------
# Compiled regex patterns for action parsing
# ---------------------------------------------------------------------------

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
    r'type\s*\(\s*text\s*=\s*"((?:[^"\\]|\\.)*)"\s*\)',
    re.IGNORECASE,
)
_RE_PRESS = re.compile(
    r"press\s*\(\s*keys\s*=\s*\[([^\]]*)\]\s*\)",
    re.IGNORECASE,
)
_RE_SCROLL = re.compile(
    r'scroll\s*\(\s*direction\s*=\s*"(\w+)"\s*'
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


# ---------------------------------------------------------------------------
# Action parsing (standalone, used by both agent and tests)
# ---------------------------------------------------------------------------


def _denorm_coord(x_qwen: int, y_qwen: int) -> tuple[float, float]:
    """Denormalize coordinates from Qwen [0, 1000] to [0, 1].

    Args:
        x_qwen: X coordinate in [0, 1000] range.
        y_qwen: Y coordinate in [0, 1000] range.

    Returns:
        Tuple of (x_norm, y_norm) in [0, 1] range.
    """
    return x_qwen / QWEN_COORD_SCALE, y_qwen / QWEN_COORD_SCALE


def _extract_action_string(response: str) -> str | None:
    """Extract the action string from model response, stripping think blocks.

    Args:
        response: Raw model response text.

    Returns:
        Action string (e.g. ``"click(x=500, y=300)"``) or None.
    """
    # Strip <think>...</think> blocks
    text = _RE_THINK.sub("", response).strip()
    if not text:
        return None

    # Take the first line that looks like a known action
    for line in text.splitlines():
        line = line.strip()
        if line and re.match(
            r"(click|left_click|double_click|right_click|type|press"
            r"|scroll|drag|wait|finished)\s*\(",
            line,
            re.IGNORECASE,
        ):
            return line

    # Fallback: return entire stripped text
    return text if text else None


def parse_qwen_action(
    response: str,
    viewport: tuple[int, int] | None = None,
) -> BenchmarkAction:
    """Parse Qwen3-VL action output into BenchmarkAction.

    Handles all action formats from the SYSTEM_PROMPT. Coordinates are
    denormalized from [0, 1000] to [0, 1] for BenchmarkAction. The
    original Qwen-scale coordinates are preserved in ``raw_action``.

    Args:
        response: Raw model output text (may include ``<think>`` blocks).
        viewport: Optional ``(width, height)`` of the viewport (stored in
            ``raw_action`` but not used for coordinate conversion since
            denormalization targets [0, 1] independent of viewport).

    Returns:
        Parsed BenchmarkAction with coordinates in [0, 1] range.
    """
    raw: dict[str, Any] = {"response": response}
    if viewport:
        raw["viewport"] = viewport

    # Extract and store thinking content
    think_match = _RE_THINK.search(response)
    if think_match:
        raw["thinking"] = think_match.group(1).strip()

    # Get the action string (stripping think blocks)
    action_str = _extract_action_string(response)
    if action_str:
        raw["action_string"] = action_str
    else:
        raw["parse_error"] = "No action found in response"
        return BenchmarkAction(type="done", raw_action=raw)

    # --- finished() ---
    if _RE_FINISHED.search(action_str):
        return BenchmarkAction(type="done", raw_action=raw)

    # --- wait() ---
    if _RE_WAIT.search(action_str):
        raw["is_wait"] = True
        return BenchmarkAction(type="done", raw_action=raw)

    # --- double_click(x=<int>, y=<int>) --- (check before click)
    m = _RE_DOUBLE_CLICK.search(action_str)
    if m:
        x_q, y_q = int(m.group(1)), int(m.group(2))
        x_n, y_n = _denorm_coord(x_q, y_q)
        raw["click_variant"] = "double_click"
        raw["qwen_coords"] = {"x": x_q, "y": y_q}
        return BenchmarkAction(
            type="click", x=x_n, y=y_n, raw_action=raw
        )

    # --- right_click(x=<int>, y=<int>) --- (check before click)
    m = _RE_RIGHT_CLICK.search(action_str)
    if m:
        x_q, y_q = int(m.group(1)), int(m.group(2))
        x_n, y_n = _denorm_coord(x_q, y_q)
        raw["click_variant"] = "right_click"
        raw["qwen_coords"] = {"x": x_q, "y": y_q}
        return BenchmarkAction(
            type="click", x=x_n, y=y_n, raw_action=raw
        )

    # --- click(x=<int>, y=<int>) ---
    m = _RE_CLICK.search(action_str)
    if m:
        x_q, y_q = int(m.group(1)), int(m.group(2))
        x_n, y_n = _denorm_coord(x_q, y_q)
        raw["qwen_coords"] = {"x": x_q, "y": y_q}
        return BenchmarkAction(
            type="click", x=x_n, y=y_n, raw_action=raw
        )

    # --- type(text="<string>") ---
    m = _RE_TYPE.search(action_str)
    if m:
        text = m.group(1).replace('\\"', '"').replace("\\\\", "\\")
        return BenchmarkAction(type="type", text=text, raw_action=raw)

    # --- press(keys=["<key1>", ...]) ---
    m = _RE_PRESS.search(action_str)
    if m:
        keys_str = m.group(1)
        keys = [k.strip().strip("\"'") for k in keys_str.split(",") if k.strip()]
        if len(keys) == 1:
            return BenchmarkAction(type="key", key=keys[0], raw_action=raw)
        elif len(keys) > 1:
            return BenchmarkAction(
                type="key", key=keys[-1], modifiers=keys[:-1], raw_action=raw
            )
        raw["parse_error"] = "Empty keys list in press()"
        return BenchmarkAction(type="done", raw_action=raw)

    # --- scroll(direction="<dir>", amount=<int>) ---
    m = _RE_SCROLL.search(action_str)
    if m:
        direction = m.group(1).lower()
        amount = int(m.group(2)) if m.group(2) else 3
        return BenchmarkAction(
            type="scroll",
            scroll_direction=direction,
            scroll_amount=float(amount),
            raw_action=raw,
        )

    # --- drag(from_coord=[<x1>, <y1>], to_coord=[<x2>, <y2>]) ---
    m = _RE_DRAG.search(action_str)
    if m:
        fx, fy = int(m.group(1)), int(m.group(2))
        tx, ty = int(m.group(3)), int(m.group(4))
        fx_n, fy_n = _denorm_coord(fx, fy)
        tx_n, ty_n = _denorm_coord(tx, ty)
        raw["qwen_coords"] = {
            "from": {"x": fx, "y": fy},
            "to": {"x": tx, "y": ty},
        }
        return BenchmarkAction(
            type="drag",
            x=fx_n, y=fy_n,
            end_x=tx_n, end_y=ty_n,
            raw_action=raw,
        )

    # Unknown action format
    raw["parse_error"] = f"Unknown action format: {action_str}"
    return BenchmarkAction(type="done", raw_action=raw)


# ---------------------------------------------------------------------------
# Agent class
# ---------------------------------------------------------------------------


class Qwen3VLAgent(BenchmarkAgent):
    """Agent using Qwen3-VL for local GUI agent inference.

    Loads the model via HuggingFace transformers and runs inference locally.
    Coordinates use the Qwen normalized [0, 1000] range internally and are
    converted to [0, 1] for BenchmarkAction output.

    The prompt format matches ``openadapt_ml.training.convert_demos`` so
    fine-tuned checkpoints see the same structure at inference time.

    Args:
        model_path: HuggingFace model ID or local checkpoint path.
            Defaults to ``Qwen/Qwen3-VL-8B-Instruct``.
        demo: Optional demonstration text for demo-conditioned inference.
            Included at every step (not just step 0) following the
            pattern established by ApiAgent.
        use_thinking: Enable thinking mode with ``<think>`` blocks.
        device: Torch device (``"cuda"``, ``"cpu"``, ``"auto"``).
        max_new_tokens: Maximum tokens to generate per step.
        torch_dtype: Torch dtype string (``"auto"``, ``"float16"``, ``"bfloat16"``).
        min_pixels: Minimum image pixels for Qwen3-VL processor.
        max_pixels: Maximum image pixels for Qwen3-VL processor.
    """

    def __init__(
        self,
        model_path: str | None = None,
        demo: str | None = None,
        use_thinking: bool = False,
        device: str = "auto",
        max_new_tokens: int = 512,
        torch_dtype: str = "auto",
        min_pixels: int = 256 * 28 * 28,
        max_pixels: int = 1280 * 28 * 28,
    ):
        self.model_path = model_path or DEFAULT_MODEL
        self.demo = demo
        self.use_thinking = use_thinking
        self.device = device
        self.max_new_tokens = max_new_tokens
        self.torch_dtype = torch_dtype
        self.min_pixels = min_pixels
        self.max_pixels = max_pixels

        # State across steps within an episode
        self._previous_actions: list[str] = []
        self._step_count = 0

        # Lazy-loaded model and processor
        self._model = None
        self._processor = None

        logger.info(
            f"Qwen3VLAgent initialized: model={self.model_path}, "
            f"thinking={self.use_thinking}, device={self.device}"
        )
        if self.demo:
            logger.info(f"Demo provided ({len(self.demo)} chars)")

    def _load_model(self) -> None:
        """Lazy-load model and processor on first inference call.

        Raises:
            RuntimeError: If transformers/torch is not installed or model
                loading fails.
        """
        if self._model is not None:
            return

        try:
            import torch
            from transformers import AutoProcessor
        except ImportError as e:
            raise RuntimeError(
                "Qwen3VLAgent requires transformers and torch. "
                "Install with: pip install transformers torch"
            ) from e

        # Resolve torch dtype
        dtype_map = {
            "auto": "auto",
            "float16": torch.float16,
            "fp16": torch.float16,
            "bfloat16": torch.bfloat16,
            "bf16": torch.bfloat16,
            "float32": torch.float32,
            "fp32": torch.float32,
        }
        resolved_dtype = dtype_map.get(self.torch_dtype, "auto")

        logger.info(f"Loading model: {self.model_path}")

        # Qwen3-VL uses the same architecture class as Qwen2.5-VL in
        # current transformers versions. Try AutoModelForVision2Seq first
        # (more generic), then fall back to the specific class.
        try:
            from transformers import AutoModelForVision2Seq

            self._model = AutoModelForVision2Seq.from_pretrained(
                self.model_path,
                torch_dtype=resolved_dtype,
                device_map=self.device,
            )
        except Exception:
            from transformers import Qwen2_5_VLForConditionalGeneration

            self._model = Qwen2_5_VLForConditionalGeneration.from_pretrained(
                self.model_path,
                torch_dtype=resolved_dtype,
                device_map=self.device,
            )

        self._processor = AutoProcessor.from_pretrained(
            self.model_path,
            min_pixels=self.min_pixels,
            max_pixels=self.max_pixels,
        )

        logger.info("Model loaded successfully")

    def reset(self) -> None:
        """Reset agent state between episodes.

        Note: demo is NOT reset -- it persists across resets if set.
        """
        self._step_count = 0
        self._previous_actions = []
        logger.debug("Qwen3VLAgent reset")

    def act(
        self,
        observation: BenchmarkObservation,
        task: BenchmarkTask,
        history: list[tuple[BenchmarkObservation, BenchmarkAction]] | None = None,
    ) -> BenchmarkAction:
        """Given observation and task, return next action.

        Builds a prompt matching the training format from convert_demos,
        runs Qwen3-VL inference, and parses the output into a
        BenchmarkAction with coordinates denormalized to [0, 1].

        Args:
            observation: Current observation from the environment.
            task: Task being performed.
            history: Optional list of previous (observation, action) pairs.

        Returns:
            BenchmarkAction to execute.
        """
        self._load_model()
        self._step_count += 1

        # Get screenshot as PIL Image
        image = self._get_image(observation)
        if image is None:
            logger.error("No screenshot available in observation")
            return BenchmarkAction(
                type="done", raw_action={"error": "no_screenshot"}
            )

        # Build user content (aligned with convert_demos training format)
        user_content = self._build_prompt(task.instruction)

        # Build chat messages and run inference
        messages = self._build_messages(user_content)
        try:
            response_text = self._run_inference(messages, image)
        except Exception as e:
            logger.error(f"Inference failed: {e}")
            return BenchmarkAction(
                type="done", raw_action={"error": f"inference_failed: {e}"}
            )

        logger.info(f"Step {self._step_count} raw response: {response_text!r}")

        # Parse the response into a BenchmarkAction (with denormalization)
        action = parse_qwen_action(response_text, observation.viewport)

        # Track the parsed action string for history in next prompt
        action_str = _extract_action_string(response_text)
        if action_str:
            self._previous_actions.append(action_str)

        # Annotate raw_action with step number
        if action.raw_action is None:
            action.raw_action = {}
        action.raw_action["step"] = self._step_count

        return action

    def _build_prompt(self, instruction: str) -> str:
        """Build the user-turn text, aligned with convert_demos.convert_step.

        The format matches the training data exactly::

            <image>
            Instruction: {instruction}

            Previous actions:
              Step 0: {action}
              Step 1: {action}

            First reason about what you see in <think>...</think> tags,
            then output exactly one action.

        When a demo is provided, it is injected after the instruction
        and before the previous actions (demo-conditioned inference).

        Args:
            instruction: Task instruction text.

        Returns:
            User content string.
        """
        parts = ["<image>"]
        parts.append(f"Instruction: {instruction}")

        # Demo injection (included at every step, not just step 0)
        if self.demo:
            parts.append("")
            parts.append(
                "Demonstration (follow this pattern):\n"
                f"{self.demo}"
            )

        # Previous actions
        if self._previous_actions:
            parts.append("")
            parts.append("Previous actions:")
            for i, act in enumerate(self._previous_actions):
                parts.append(f"  Step {i}: {act}")

        # Tail instruction
        parts.append("")
        if self.use_thinking:
            parts.append(
                "First reason about what you see in <think>...</think> "
                "tags, then output exactly one action."
            )
        else:
            parts.append("Output exactly one action.")

        return "\n".join(parts)

    def _build_messages(
        self, user_content: str
    ) -> list[dict[str, Any]]:
        """Build chat messages for the Qwen3-VL processor.

        Args:
            user_content: User message content string (from ``_build_prompt``).

        Returns:
            List of message dicts for ``apply_chat_template``.
        """
        return [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "image"},
                    {"type": "text", "text": user_content},
                ],
            },
        ]

    def _get_image(self, observation: BenchmarkObservation):
        """Extract PIL Image from observation.

        Args:
            observation: Current observation.

        Returns:
            PIL.Image.Image or None.
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

        try:
            return Image.open(BytesIO(screenshot_bytes)).convert("RGB")
        except Exception as e:
            logger.warning(f"Failed to open screenshot: {e}")
            return None

    def _run_inference(
        self,
        messages: list[dict[str, Any]],
        image: Any,
    ) -> str:
        """Run model inference with the given messages and image.

        Args:
            messages: Chat messages (system + user with image placeholder).
            image: PIL Image for the current screenshot.

        Returns:
            Generated text response.
        """
        import torch

        # Apply chat template to get the full prompt text
        text = self._processor.apply_chat_template(
            messages, tokenize=False, add_generation_prompt=True
        )

        # Process inputs (image + text)
        # The processor handles image embedding via the message format
        inputs = self._processor(
            text=[text],
            images=[image],
            padding=True,
            return_tensors="pt",
        )

        # Move to model device
        device = next(self._model.parameters()).device
        inputs = inputs.to(device)

        # Generate
        with torch.no_grad():
            output_ids = self._model.generate(
                **inputs,
                max_new_tokens=self.max_new_tokens,
            )

        # Decode only the generated tokens (trim prompt)
        input_len = inputs["input_ids"].shape[1]
        generated_ids = output_ids[:, input_len:]
        response = self._processor.batch_decode(
            generated_ids,
            skip_special_tokens=True,
            clean_up_tokenization_spaces=False,
        )[0]

        return response.strip()

    def set_demo(self, demo: str) -> None:
        """Set or update the demonstration trajectory.

        Allows setting the demo after initialization, useful for
        dynamic demo retrieval.

        Args:
            demo: Demonstration text to include at every step.
        """
        self.demo = demo
        logger.info(f"Demo set ({len(demo)} chars) - persists across all steps")
