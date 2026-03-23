"""WAADirect: minimal HTTP client for WAA. No adapter layer, no openadapt-ml imports."""

from __future__ import annotations

import base64
import hashlib
import logging
import time
from dataclasses import dataclass, field
from typing import Any

import requests

from openadapt_evals.training.standalone.prompt import SimpleAction

logger = logging.getLogger(__name__)


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
    """Direct HTTP client for WAA Flask server. Screenshot/click/type/key."""

    def __init__(self, server_url: str = "http://localhost:5001",
                 screen_size: tuple[int, int] = (1920, 1080)) -> None:
        self.server_url = server_url.rstrip("/")
        self.screen_size = screen_size
        self._session = requests.Session()

    def screenshot(self) -> bytes:
        """Take a fresh screenshot. Returns PNG bytes."""
        resp = self._session.get(f"{self.server_url}/screenshot", timeout=30)
        if resp.status_code != 200:
            raise RuntimeError(f"Screenshot failed: {resp.status_code}")
        data = resp.json()
        img_b64 = data.get("screenshot", data.get("image", ""))
        if not img_b64:
            raise RuntimeError("No screenshot data in response")
        return base64.b64decode(img_b64)

    def execute_action(self, action: SimpleAction) -> dict[str, Any]:
        """Execute action on VM via /execute_windows."""
        if action.type == "click":
            x, y = int(action.x or 0), int(action.y or 0)
            cmd = f'python -c "import pyautogui; pyautogui.click({x}, {y})"'
        elif action.type == "type":
            text = (action.text or "").replace('"', '\\"')
            cmd = f'python -c "import pyautogui; pyautogui.typewrite(\'{text}\', interval=0.05)"'
        elif action.type == "key":
            cmd = f'python -c "import pyautogui; pyautogui.press(\'{action.key or "enter"}\')"'
        elif action.type == "wait":
            time.sleep(2)
            return {"status": "ok", "action": "wait"}
        elif action.type == "done":
            return {"status": "ok", "action": "done"}
        else:
            return {"status": "error", "message": f"Unknown: {action.type}"}

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

    def health_check(self) -> bool:
        """True if WAA server responds."""
        try:
            return self._session.get(f"{self.server_url}/screenshot", timeout=10).status_code == 200
        except requests.RequestException:
            return False
