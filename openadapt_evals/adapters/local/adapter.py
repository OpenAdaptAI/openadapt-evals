"""Local desktop adapter for benchmark evaluation.

This adapter runs on the LOCAL machine using `mss` for screenshots and
`pynput` for mouse/keyboard input. No VM or remote server is required.

Platform notes:
- macOS: Requires Accessibility permission for pynput. mss returns
  physical (Retina) pixels; pynput uses logical points. The adapter
  handles the coordinate scaling automatically.
- Linux/Windows: Coordinates are typically 1:1 between mss and pynput.

Example:
    ```python
    from openadapt_evals.adapters.local import LocalAdapter

    with LocalAdapter(action_delay=0.5) as adapter:
        task = adapter.list_tasks()[0]
        obs = adapter.reset(task)
        obs, done, info = adapter.step(BenchmarkAction(type="click", x=100, y=200))
    ```
"""

from __future__ import annotations

import io
import logging
import platform
import time
from typing import Any

from openadapt_evals.adapters.base import (
    BenchmarkAction,
    BenchmarkAdapter,
    BenchmarkObservation,
    BenchmarkResult,
    BenchmarkTask,
)

logger = logging.getLogger(__name__)


def _get_display_scale_factor() -> float:
    """Detect the HiDPI / Retina scale factor for the primary display.

    On macOS Retina displays, ``mss`` captures at physical pixel resolution
    while ``pynput`` operates in logical points. This function returns the
    ratio (physical / logical) so callers can convert between the two
    coordinate systems.

    Returns:
        Scale factor (e.g. 2.0 on Retina, 1.0 on standard displays).
    """
    if platform.system() != "Darwin":
        return 1.0

    try:
        import mss

        with mss.mss() as sct:
            monitor = sct.monitors[1]  # primary monitor
            physical_width = monitor["width"]

        # Quartz gives us the logical width
        from Quartz import CGDisplayBounds, CGMainDisplayID  # type: ignore[import-not-found]

        main_display = CGMainDisplayID()
        bounds = CGDisplayBounds(main_display)
        logical_width = int(bounds.size.width)

        if logical_width > 0:
            return physical_width / logical_width
    except Exception:
        logger.debug("Could not detect display scale factor, defaulting to 1.0")

    return 1.0


class LocalAdapter(BenchmarkAdapter):
    """Adapter for local desktop automation. No VM required.

    Uses ``mss`` for screen capture and ``pynput`` for mouse/keyboard
    control. Coordinates passed to :meth:`step` are expected in **pixel**
    units matching the screenshot resolution (physical pixels). The adapter
    converts to logical points internally when needed (macOS Retina).

    Args:
        action_delay: Seconds to wait after each action (default 0.5).
        monitor_index: Which monitor to capture (1 = primary).
    """

    def __init__(
        self,
        action_delay: float = 0.5,
        monitor_index: int = 1,
    ):
        self._action_delay = action_delay
        self._monitor_index = monitor_index
        self._scale: float | None = None
        self._current_task: BenchmarkTask | None = None
        self._step_count = 0

    # ------------------------------------------------------------------
    # BenchmarkAdapter properties
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return "local"

    @property
    def benchmark_type(self) -> str:
        return "interactive"

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_scale(self) -> float:
        """Lazily compute and cache the display scale factor."""
        if self._scale is None:
            self._scale = _get_display_scale_factor()
            if self._scale != 1.0:
                logger.info("HiDPI detected: scale factor = %.1f", self._scale)
        return self._scale

    def _to_logical(self, x: float, y: float) -> tuple[float, float]:
        """Convert physical pixel coordinates to logical points."""
        s = self._ensure_scale()
        return x / s, y / s

    # ------------------------------------------------------------------
    # Observation
    # ------------------------------------------------------------------

    def observe(self) -> BenchmarkObservation:
        """Capture a screenshot of the local screen.

        Returns:
            :class:`BenchmarkObservation` with PNG screenshot bytes and
            viewport dimensions in physical pixels.
        """
        import mss  # type: ignore[import-untyped]

        with mss.mss() as sct:
            monitor = sct.monitors[self._monitor_index]
            img = sct.grab(monitor)

            # Convert BGRA raw data to PNG via Pillow
            from PIL import Image  # type: ignore[import-untyped]

            pil_img = Image.frombytes("RGB", img.size, img.bgra, "raw", "BGRX")
            buf = io.BytesIO()
            pil_img.save(buf, format="PNG")
            png_bytes = buf.getvalue()

            return BenchmarkObservation(
                screenshot=png_bytes,
                viewport=(monitor["width"], monitor["height"]),
            )

    # ------------------------------------------------------------------
    # BenchmarkAdapter interface
    # ------------------------------------------------------------------

    def list_tasks(self, domain: str | None = None) -> list[BenchmarkTask]:
        """Return an empty task list (local adapter has no predefined tasks)."""
        return []

    def load_task(self, task_id: str) -> BenchmarkTask:
        """Load a task by ID.

        For the local adapter, callers construct tasks directly; this
        method exists only for interface compliance.

        Raises:
            KeyError: Always, since local adapter has no task registry.
        """
        raise KeyError(
            f"LocalAdapter has no task registry. "
            f"Construct a BenchmarkTask directly instead of loading '{task_id}'."
        )

    def reset(self, task: BenchmarkTask) -> BenchmarkObservation:
        """Reset for a new task.

        On the local machine the user is responsible for setting up the
        initial application state. This method simply records the task
        and takes a fresh screenshot.

        Args:
            task: The task to run.

        Returns:
            Initial observation (screenshot of current screen).
        """
        self._current_task = task
        self._step_count = 0
        logger.info("LocalAdapter reset for task: %s", task.task_id)
        return self.observe()

    def step(
        self, action: BenchmarkAction
    ) -> tuple[BenchmarkObservation, bool, dict[str, Any]]:
        """Execute an action on the local machine and return a new observation.

        Supported action types:
        - ``click``: Move mouse to (x, y) and click.
        - ``double_click``: Move mouse to (x, y) and double-click.
        - ``right_click``: Move mouse to (x, y) and right-click.
        - ``type``: Type text string.
        - ``key``: Press a single key, optionally with modifiers.
        - ``scroll``: Scroll in a direction.
        - ``drag``: Drag from (x, y) to (end_x, end_y).
        - ``done``: Signal task completion (no-op).

        Args:
            action: The action to execute.

        Returns:
            Tuple of (observation, done, info).
        """
        self._step_count += 1
        done = action.type in ("done", "error")

        try:
            self._execute_action(action)
        except Exception as e:
            logger.error("Failed to execute action %s: %s", action.type, e)
            return self.observe(), True, {"step": self._step_count, "error": str(e)}

        if self._action_delay > 0 and not done:
            time.sleep(self._action_delay)

        obs = self.observe()
        return obs, done, {"step": self._step_count}

    def evaluate(self, task: BenchmarkTask) -> BenchmarkResult:
        """Placeholder evaluation.

        Local adapter does not have built-in evaluation logic. Use
        task-specific evaluators or a VLM judge externally.

        Returns:
            :class:`BenchmarkResult` with score 0.0 and a note that
            evaluation is not implemented for the local adapter.
        """
        return BenchmarkResult(
            task_id=task.task_id,
            success=False,
            score=0.0,
            num_steps=self._step_count,
            reason="LocalAdapter does not implement built-in evaluation. "
            "Use an external evaluator or VLM judge.",
        )

    # ------------------------------------------------------------------
    # Action execution
    # ------------------------------------------------------------------

    def _execute_action(self, action: BenchmarkAction) -> None:
        """Dispatch and execute a single action via pynput."""
        action_type = action.type

        if action_type in ("click", "double_click", "right_click"):
            self._do_click(action)
        elif action_type == "type":
            self._do_type(action)
        elif action_type == "key":
            self._do_key(action)
        elif action_type == "scroll":
            self._do_scroll(action)
        elif action_type == "drag":
            self._do_drag(action)
        elif action_type in ("done", "wait", "error"):
            pass  # No-op
        else:
            logger.warning("Unknown action type: %s", action_type)

    def _do_click(self, action: BenchmarkAction) -> None:
        """Execute a mouse click action."""
        from pynput.mouse import Button, Controller as MouseController  # type: ignore[import-untyped]

        mouse = MouseController()
        x = action.x if action.x is not None else 0
        y = action.y if action.y is not None else 0
        lx, ly = self._to_logical(x, y)
        mouse.position = (lx, ly)

        if action.type == "double_click":
            mouse.click(Button.left, 2)
        elif action.type == "right_click":
            mouse.click(Button.right, 1)
        else:
            mouse.click(Button.left, 1)

    def _do_type(self, action: BenchmarkAction) -> None:
        """Execute a text typing action."""
        from pynput.keyboard import Controller as KbdController  # type: ignore[import-untyped]

        kbd = KbdController()
        text = action.text or ""
        kbd.type(text)

    def _do_key(self, action: BenchmarkAction) -> None:
        """Execute a key press action, optionally with modifiers."""
        from pynput.keyboard import Controller as KbdController, Key  # type: ignore[import-untyped]

        kbd = KbdController()
        key_name = action.key or ""
        modifiers = action.modifiers or []

        # Resolve the key
        resolved_key = self._resolve_key(key_name)

        # Press modifiers
        held_modifiers = []
        for mod in modifiers:
            mod_key = self._resolve_key(mod)
            kbd.press(mod_key)
            held_modifiers.append(mod_key)

        # Press and release the main key
        kbd.press(resolved_key)
        kbd.release(resolved_key)

        # Release modifiers in reverse order
        for mod_key in reversed(held_modifiers):
            kbd.release(mod_key)

    def _do_scroll(self, action: BenchmarkAction) -> None:
        """Execute a scroll action."""
        from pynput.mouse import Controller as MouseController  # type: ignore[import-untyped]

        mouse = MouseController()
        amount = int(action.scroll_amount or 3)
        direction = action.scroll_direction or "down"

        # pynput scroll: positive dy = scroll up, negative = scroll down
        if direction == "up":
            mouse.scroll(0, amount)
        elif direction == "down":
            mouse.scroll(0, -amount)
        elif direction == "left":
            mouse.scroll(-amount, 0)
        elif direction == "right":
            mouse.scroll(amount, 0)

    def _do_drag(self, action: BenchmarkAction) -> None:
        """Execute a drag action."""
        from pynput.mouse import Button, Controller as MouseController  # type: ignore[import-untyped]

        mouse = MouseController()

        start_x = action.x if action.x is not None else 0
        start_y = action.y if action.y is not None else 0
        end_x = action.end_x if action.end_x is not None else start_x
        end_y = action.end_y if action.end_y is not None else start_y

        sx, sy = self._to_logical(start_x, start_y)
        ex, ey = self._to_logical(end_x, end_y)

        mouse.position = (sx, sy)
        mouse.press(Button.left)
        # Smooth drag with small steps
        steps = 20
        for i in range(1, steps + 1):
            t = i / steps
            ix = sx + (ex - sx) * t
            iy = sy + (ey - sy) * t
            mouse.position = (ix, iy)
            time.sleep(0.01)
        mouse.release(Button.left)

    @staticmethod
    def _resolve_key(key_name: str):
        """Resolve a key name string to a pynput Key enum or character.

        Handles common key names like "enter", "tab", "ctrl", "shift",
        "alt", "cmd", "space", "backspace", "delete", "escape", etc.
        Single characters are returned as-is.
        """
        from pynput.keyboard import Key  # type: ignore[import-untyped]

        key_map = {
            "enter": Key.enter,
            "return": Key.enter,
            "tab": Key.tab,
            "space": Key.space,
            "backspace": Key.backspace,
            "delete": Key.delete,
            "escape": Key.esc,
            "esc": Key.esc,
            "up": Key.up,
            "down": Key.down,
            "left": Key.left,
            "right": Key.right,
            "home": Key.home,
            "end": Key.end,
            "page_up": Key.page_up,
            "page_down": Key.page_down,
            "ctrl": Key.ctrl_l,
            "ctrl_l": Key.ctrl_l,
            "ctrl_r": Key.ctrl_r,
            "shift": Key.shift_l,
            "shift_l": Key.shift_l,
            "shift_r": Key.shift_r,
            "alt": Key.alt_l,
            "alt_l": Key.alt_l,
            "alt_r": Key.alt_r,
            "cmd": Key.cmd,
            "command": Key.cmd,
            "super": Key.cmd,
            "f1": Key.f1,
            "f2": Key.f2,
            "f3": Key.f3,
            "f4": Key.f4,
            "f5": Key.f5,
            "f6": Key.f6,
            "f7": Key.f7,
            "f8": Key.f8,
            "f9": Key.f9,
            "f10": Key.f10,
            "f11": Key.f11,
            "f12": Key.f12,
            "caps_lock": Key.caps_lock,
        }

        # Key.insert is not available on all platforms (e.g. macOS)
        if hasattr(Key, "insert"):
            key_map["insert"] = Key.insert

        normalized = key_name.strip().lower()
        if normalized in key_map:
            return key_map[normalized]

        # Single character keys
        if len(key_name) == 1:
            return key_name

        logger.warning("Unrecognized key name '%s', passing as literal", key_name)
        return key_name
