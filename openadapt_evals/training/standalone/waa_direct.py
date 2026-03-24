"""WAADirect: minimal HTTP client for WAA. No adapter layer, no openadapt-ml imports."""

from __future__ import annotations

import hashlib
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import requests

from openadapt_evals.training.standalone.prompt import SimpleAction

logger = logging.getLogger(__name__)

# Default retry parameters for screenshot
SCREENSHOT_MAX_RETRIES = 3
SCREENSHOT_RETRY_DELAY = 2.0  # seconds


@dataclass
class RolloutStep:
    """Single step in a rollout trajectory."""

    screenshot: bytes
    action: SimpleAction
    raw_text: str = ""
    reward: float = 0.0


@dataclass
class Rollout:
    """Complete episode rollout with reward."""

    task_id: str
    instruction: str = ""
    steps: list[RolloutStep] = field(default_factory=list)
    reward: float = 0.0


class WAADirect:
    """Direct HTTP client for WAA Flask server. Screenshot/click/type/key.

    WAA API contract (from WAA Flask server main.py):
      GET  /screenshot       -> raw PNG bytes (Content-Type: image/png)
      POST /execute_windows  -> exec(command, {'computer': computer, 'human': human})
           Payload: {"command": "<python code>"}
           The command is Python code executed via exec() with pyautogui available.
           Do NOT wrap in ``python -c "..."`` -- send bare Python statements.
    """

    def __init__(self, server_url: str = "http://localhost:5001",
                 screen_size: tuple[int, int] = (1920, 1080)) -> None:
        self.server_url = server_url.rstrip("/")
        self.screen_size = screen_size
        self._session = requests.Session()

    def screenshot(self, max_retries: int = SCREENSHOT_MAX_RETRIES,
                   retry_delay: float = SCREENSHOT_RETRY_DELAY) -> bytes:
        """Take a fresh screenshot. Returns raw PNG bytes.

        WAA's /screenshot endpoint returns raw PNG via Flask's send_file(),
        NOT base64-encoded JSON. Read resp.content, not resp.json().
        """
        last_exc: Exception | None = None
        for attempt in range(1, max_retries + 1):
            try:
                resp = self._session.get(
                    f"{self.server_url}/screenshot", timeout=30,
                )
                if resp.status_code != 200:
                    raise RuntimeError(
                        f"Screenshot HTTP {resp.status_code}: {resp.text[:200]}"
                    )
                png_bytes = resp.content
                if len(png_bytes) < 100:
                    raise RuntimeError(
                        f"Screenshot too small ({len(png_bytes)} bytes) -- "
                        "server may not be ready"
                    )
                return png_bytes
            except Exception as e:
                last_exc = e
                logger.warning(
                    "Screenshot attempt %d/%d failed: %s",
                    attempt, max_retries, e,
                )
                if attempt < max_retries:
                    time.sleep(retry_delay)
        raise RuntimeError(
            f"Screenshot failed after {max_retries} attempts"
        ) from last_exc

    def execute_action(self, action: SimpleAction) -> dict[str, Any]:
        """Execute action on VM via /execute_windows.

        WAA's /execute_windows does ``exec(command, {'computer': ..., 'human': ...})``.
        The command must be bare Python code -- NOT wrapped in ``python -c "..."``.
        pyautogui is available via import inside the exec'd code.
        """
        if action.type == "click":
            x, y = int(action.x or 0), int(action.y or 0)
            cmd = f"import pyautogui; pyautogui.click({x}, {y})"
        elif action.type == "double_click":
            x, y = int(action.x or 0), int(action.y or 0)
            cmd = f"import pyautogui; pyautogui.doubleClick({x}, {y})"
        elif action.type == "right_click":
            x, y = int(action.x or 0), int(action.y or 0)
            cmd = f"import pyautogui; pyautogui.rightClick({x}, {y})"
        elif action.type == "type":
            text = (action.text or "").replace("\\", "\\\\").replace("'", "\\'")
            x, y = int(action.x or 0), int(action.y or 0)
            # Click target first, then type (matches WAALiveAdapter pattern)
            cmd = (
                f"import pyautogui; import time; "
                f"pyautogui.click({x}, {y}); "
                f"time.sleep(0.2); "
                f"pyautogui.typewrite('{text}', interval=0.05)"
            )
        elif action.type == "key":
            key = action.key or "enter"
            cmd = f"import pyautogui; pyautogui.press('{key}')"
        elif action.type == "scroll":
            x, y = int(action.x or 0), int(action.y or 0)
            cmd = f"import pyautogui; pyautogui.scroll(-3, x={x}, y={y})"
        elif action.type == "wait":
            time.sleep(2)
            return {"status": "ok", "action": "wait"}
        elif action.type == "done":
            return {"status": "ok", "action": "done"}
        else:
            return {"status": "error", "message": f"Unknown action type: {action.type}"}

        resp = self._session.post(
            f"{self.server_url}/execute_windows", json={"command": cmd}, timeout=30,
        )
        if resp.status_code != 200:
            logger.warning("Execute failed: %d %s", resp.status_code, resp.text[:200])
            return {"status": "error", "code": resp.status_code}
        return resp.json()

    def setup_task(self, task_config: dict[str, Any]) -> bool:
        """Run task setup commands on the VM."""
        for entry in task_config.get("config", []):
            etype = entry.get("type", "")
            params = entry.get("parameters", {})
            if etype == "sleep":
                time.sleep(params.get("seconds", 5))
            elif etype in ("execute", "command", "launch"):
                cmd = params.get("command", "")
                if cmd:
                    try:
                        self._session.post(
                            f"{self.server_url}/execute_windows",
                            json={"command": cmd}, timeout=120,
                        )
                    except requests.RequestException as e:
                        logger.warning("Setup error: %s", e)
            elif etype == "open" and params.get("path"):
                try:
                    self._session.post(
                        f"{self.server_url}/execute_windows",
                        json={"command": f'start "" "{params["path"]}"'}, timeout=120,
                    )
                except requests.RequestException as e:
                    logger.warning("Open failed: %s", e)
        time.sleep(2)
        return True

    def is_stuck(self, recent: list[bytes], window: int = 3) -> bool:
        """True if last N screenshots are identical."""
        if len(recent) < window:
            return False
        hashes = [hashlib.md5(s).hexdigest() for s in recent[-window:]]
        return len(set(hashes)) == 1

    def probe(self, timeout: float = 10.0) -> dict[str, Any]:
        """Health-check the WAA server. Returns status dict.

        Attempts a screenshot to verify the full pipeline (not just HTTP).
        """
        result: dict[str, Any] = {"reachable": False, "screenshot_ok": False}
        try:
            resp = self._session.get(
                f"{self.server_url}/screenshot", timeout=timeout,
            )
            result["reachable"] = True
            result["status_code"] = resp.status_code
            if resp.status_code == 200:
                result["screenshot_ok"] = len(resp.content) > 100
                result["screenshot_bytes"] = len(resp.content)
        except requests.RequestException as e:
            result["error"] = str(e)
        return result

    def health_check(self) -> bool:
        """True if WAA server responds with a valid screenshot."""
        return self.probe().get("screenshot_ok", False)
