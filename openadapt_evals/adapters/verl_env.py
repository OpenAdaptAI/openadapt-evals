"""VAGEN/verl-agent environment adapter for openadapt-evals.

Wraps RLEnvironment to implement VAGEN's GymImageEnv protocol, enabling
desktop GUI automation training with verl-agent's multi-turn VLM RL pipeline
(GiGPO, GRPO, PPO, etc.).

The adapter translates between:
    - openadapt-evals: BenchmarkObservation (PNG bytes + a11y tree)
    - VAGEN/verl: {"obs_str": "...", "multi_modal_input": {"<image>": [PIL.Image]}}

Dependencies:
    - openadapt-evals (always required)
    - vagen (optional; a vendored copy of the GymImageEnv ABC is used
      as fallback when the full vagen package is not installed)

Usage with VAGEN training:
    Register in env_registry.yaml:
        env_registry:
            WAADesktop: openadapt_evals.adapters.verl_env.WAADesktopEnv

    Training config:
        envs:
            - name: WAADesktop
              n_envs: 8
              data_source: waa
              seed: [1, 100, 1]
              max_turns: 15
              response_length_per_turn: 512
              config:
                server_url: "http://localhost:5001"
                task_id: "<WAA_UUID>"

Usage standalone (without VAGEN):
    from openadapt_evals.adapters.verl_env import WAADesktopEnv

    env = WAADesktopEnv({"server_url": "http://localhost:5001", "task_id": "..."})
    obs, info = await env.reset(seed=42)
    obs, reward, done, info = await env.step("CLICK(x=0.50, y=0.30)")
"""

from __future__ import annotations

import asyncio
import io
import logging
import re
from typing import Any

from openadapt_evals.adapters.base import BenchmarkAction, BenchmarkObservation
from openadapt_evals.adapters.rl_env import RLEnvironment

logger = logging.getLogger(__name__)

# Try importing PIL (required for image conversion)
try:
    from PIL import Image
except ImportError:
    Image = None  # type: ignore[misc, assignment]

# Import VAGEN's GymImageEnv base class.
# Prefer the real vagen package; fall back to our vendored copy.
try:
    from vagen.envs.gym_image_env import GymImageEnv as _GymImageEnvBase
except ImportError:
    from openadapt_evals.adapters._vendored.gym_image_env import (
        GymImageEnv as _GymImageEnvBase,
    )

# --- Action parsing (matches openadapt-ml trainer DSL) ---

_ACTION_PATTERN = re.compile(
    r"(CLICK|TYPE|SCROLL|KEY|WAIT|DONE|DRAG)\((.*?)\)", re.DOTALL
)


def _parse_action_str(action_str: str) -> BenchmarkAction:
    """Parse a VLM action string into a BenchmarkAction.

    Supports the same DSL as the openadapt-ml GRPO trainer:
        CLICK(x=0.50, y=0.30)
        TYPE(text="hello world")
        KEY(key="enter")
        SCROLL(x=0.50, y=0.50, direction="down")
        DRAG(x=0.20, y=0.30, end_x=0.80, end_y=0.70)
        WAIT()
        DONE()
    """
    match = _ACTION_PATTERN.search(action_str)
    if not match:
        logger.warning("Could not parse action: %s", action_str[:100])
        return BenchmarkAction(type="done")

    cmd = match.group(1)
    args_str = match.group(2)

    # Extract key=value pairs
    kwargs: dict[str, str] = {}
    for kv in re.finditer(r'(\w+)\s*=\s*(?:"((?:[^"\\]|\\.)*)"|([^\s,)]+))', args_str):
        key = kv.group(1)
        kwargs[key] = kv.group(2) if kv.group(2) is not None else kv.group(3)

    if cmd == "CLICK":
        return BenchmarkAction(
            type="click",
            x=float(kwargs.get("x", 0.5)),
            y=float(kwargs.get("y", 0.5)),
        )
    elif cmd == "TYPE":
        return BenchmarkAction(type="type", text=kwargs.get("text", ""))
    elif cmd == "KEY":
        return BenchmarkAction(type="key", key=kwargs.get("key", "enter"))
    elif cmd == "SCROLL":
        return BenchmarkAction(
            type="scroll",
            x=float(kwargs.get("x", 0.5)),
            y=float(kwargs.get("y", 0.5)),
            scroll_direction=kwargs.get("direction", "down"),
        )
    elif cmd == "WAIT":
        return BenchmarkAction(type="wait")
    elif cmd == "DONE":
        return BenchmarkAction(type="done")
    elif cmd == "DRAG":
        return BenchmarkAction(
            type="drag",
            x=float(kwargs.get("x", 0.5)),
            y=float(kwargs.get("y", 0.5)),
            end_x=float(kwargs["end_x"]) if "end_x" in kwargs else None,
            end_y=float(kwargs["end_y"]) if "end_y" in kwargs else None,
        )
    else:
        return BenchmarkAction(type="done")


def _obs_to_pil(obs: BenchmarkObservation) -> Image.Image | None:
    """Convert BenchmarkObservation screenshot bytes to PIL Image."""
    if Image is None:
        raise ImportError("Pillow is required: pip install Pillow")
    if obs.screenshot:
        return Image.open(io.BytesIO(obs.screenshot))
    return None


def _build_obs_dict(
    obs: BenchmarkObservation,
    prefix: str = "Current desktop state:",
) -> dict[str, Any]:
    """Build a VAGEN-compatible observation dict from BenchmarkObservation."""
    img = _obs_to_pil(obs)
    result: dict[str, Any] = {}
    if img is not None:
        result["obs_str"] = f"{prefix}\n<image>"
        result["multi_modal_input"] = {"<image>": [img]}
    else:
        # Text-only fallback (a11y tree)
        a11y_text = str(obs.accessibility_tree) if obs.accessibility_tree else "No observation available."
        result["obs_str"] = f"{prefix}\n{a11y_text}"
    return result


# --- System prompt (matches openadapt-ml trainer) ---

SYSTEM_PROMPT = (
    "You are a desktop automation agent. You can see the screen and interact "
    "using these actions:\n"
    "  CLICK(x=<frac>, y=<frac>) - click at normalized coordinates (0.0-1.0)\n"
    "  TYPE(text=\"<text>\") - type text\n"
    "  KEY(key=\"<name>\") - press a key (enter, tab, escape, ctrl+a, etc.)\n"
    "  SCROLL(x=<frac>, y=<frac>, direction=\"up\"|\"down\") - scroll\n"
    "  DRAG(x=<frac>, y=<frac>, end_x=<frac>, end_y=<frac>) - drag\n"
    "  WAIT() - wait for the screen to update\n"
    "  DONE() - task is complete\n"
    "\n"
    "Respond with exactly one action per turn."
)


# --- Main environment class ---


class WAADesktopEnv(_GymImageEnvBase):
    """VAGEN-compatible environment for WAA desktop automation.

    Implements the GymImageEnv protocol (async reset/step/close/system_prompt)
    so it can be used directly with VAGEN's agent loop and training pipeline.

    The environment wraps openadapt-evals' RLEnvironment, which in turn wraps
    WAALiveAdapter for remote VM interaction.

    Config keys (passed via env_config dict):
        server_url: WAA server URL (default: "http://localhost:5001")
        task_id: WAA task UUID to train on
        max_steps: Max steps per episode (default: 15)
        evaluate_at_done: Whether to call WAA evaluator at episode end (default: True)
        action_type: How coordinates are specified: "fractional" (0-1) or "pixel"
    """

    def __init__(self, env_config: dict[str, Any]) -> None:
        super().__init__(env_config)
        self.config = env_config
        self._server_url = env_config.get("server_url", "http://localhost:5001")
        self._task_id = env_config.get("task_id")
        self._max_steps = env_config.get("max_steps", 15)
        self._evaluate_at_done = env_config.get("evaluate_at_done", True)
        self._use_fractional = env_config.get("action_type", "fractional") == "fractional"

        # Lazy initialization — adapter created on first reset()
        self._rl_env: RLEnvironment | None = None
        self._step_count = 0

    def _ensure_env(self) -> RLEnvironment:
        """Create the RLEnvironment on first use (lazy init)."""
        if self._rl_env is not None:
            return self._rl_env

        from openadapt_evals.adapters.waa.live import WAALiveAdapter, WAALiveConfig

        adapter = WAALiveAdapter(
            WAALiveConfig(server_url=self._server_url)
        )
        self._rl_env = RLEnvironment(adapter, default_task_id=self._task_id)
        return self._rl_env

    async def health_check(self) -> dict[str, Any]:
        """Check environment health status.

        Returns a dict with:
            status: "ready" | "busy" | "needs_recovery" | "not_initialized"
            server_url: The WAA server URL
            step_count: Current step count in episode

        Use this from a pool controller to decide whether to send work
        to this environment or retire/restart it.
        """
        if self._rl_env is None:
            return {"status": "not_initialized", "server_url": self._server_url}

        adapter = self._rl_env.adapter
        # Check if the WAA server is reachable
        try:
            check_fn = getattr(adapter, "check_connection", None)
            reachable = await asyncio.to_thread(check_fn) if check_fn else True
        except Exception:
            reachable = False

        if not reachable:
            return {
                "status": "needs_recovery",
                "server_url": self._server_url,
                "step_count": self._step_count,
            }

        status = "busy" if self._step_count > 0 and not self._rl_env.done else "ready"
        return {
            "status": status,
            "server_url": self._server_url,
            "step_count": self._step_count,
        }

    async def close(self) -> None:
        """Release resources."""
        if self._rl_env is not None:
            self._rl_env.adapter.close()
            self._rl_env = None

    async def system_prompt(self) -> dict[str, Any]:
        """Return the system-level prompt for the VLM agent."""
        return {"obs_str": SYSTEM_PROMPT}

    async def reset(self, seed: int) -> tuple[dict[str, Any], dict[str, Any]]:
        """Reset environment and return initial observation.

        Args:
            seed: Random seed. Currently unused (WAA tasks are deterministic
                given setup commands), but required by the VAGEN protocol.

        Returns:
            (obs_dict, info_dict) where obs_dict contains "obs_str" and
            optionally "multi_modal_input" with PIL images.
        """
        env = self._ensure_env()
        self._step_count = 0

        # Run reset in a thread to avoid blocking the async event loop
        obs = await asyncio.to_thread(env.reset)

        obs_dict = _build_obs_dict(obs, prefix="Desktop initial state:")
        info: dict[str, Any] = {
            "task_id": self._task_id,
            "screen_size": env.screen_size,
        }
        return obs_dict, info

    async def step(
        self, action_str: str
    ) -> tuple[dict[str, Any], float, bool, dict[str, Any]]:
        """Execute one action and return (obs, reward, done, info).

        Args:
            action_str: Raw LLM output string. Parsed into a BenchmarkAction
                using the standard action DSL (CLICK, TYPE, KEY, etc.).

        Returns:
            Tuple of (obs_dict, reward, done, info).
            - reward is 0.0 during the episode; evaluator score at the end
            - done is True when DONE() is called, step limit reached, or stuck
        """
        env = self._ensure_env()
        self._step_count += 1

        # Parse the LLM output into a BenchmarkAction
        action = _parse_action_str(action_str)

        # Handle fractional → pixel coordinate conversion.
        # When _use_fractional is True, all coordinates from the parser are
        # fractions (0.0-1.0). We convert unconditionally rather than checking
        # value ranges, since pixel values 0 and 1 would be ambiguous.
        if self._use_fractional and action.type in ("click", "scroll", "drag"):
            w, h = env.screen_size
            if action.x is not None:
                action.x = int(action.x * w)
            if action.y is not None:
                action.y = int(action.y * h)
            if action.end_x is not None:
                action.end_x = int(action.end_x * w)
            if action.end_y is not None:
                action.end_y = int(action.end_y * h)

        # Execute action in a thread
        rollout_step = await asyncio.to_thread(env.step, action)

        # Check step limit
        done = rollout_step.done or self._step_count >= self._max_steps

        # Compute reward
        reward = 0.0
        info: dict[str, Any] = rollout_step.info
        # Action is valid if it was explicitly parsed (not the fallback for unparseable input)
        info["is_action_valid"] = _ACTION_PATTERN.search(action_str) is not None

        if done and self._evaluate_at_done:
            try:
                reward = await asyncio.to_thread(env.evaluate)
                info["success"] = reward > 0.5
            except Exception:
                logger.exception("Evaluation failed")
                info["success"] = False
        elif done:
            info["success"] = False

        obs_dict = _build_obs_dict(
            rollout_step.observation,
            prefix=f"After action (step {self._step_count}):",
        )

        return obs_dict, reward, done, info
