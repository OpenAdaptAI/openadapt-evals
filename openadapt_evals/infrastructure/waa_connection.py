"""WAAConnection: auto-recovering SSH tunnel for WAA servers.

Manages an SSH tunnel as a subprocess with a background watchdog thread
that monitors health and automatically reconnects when the tunnel drops.

Usage:
    from openadapt_evals.infrastructure.waa_connection import WAAConnection

    with WAAConnection(vm_ip="172.173.66.131") as conn:
        conn.ensure_healthy()
        # Use http://localhost:5001 for WAA API calls
"""

from __future__ import annotations

import logging
import subprocess
import threading
import time

import requests

logger = logging.getLogger(__name__)


class WAAConnection:
    """Auto-recovering SSH tunnel connection to a WAA server.

    Starts an SSH tunnel subprocess and runs a daemon watchdog thread that
    periodically health-checks the tunnel via the WAA /screenshot endpoint.
    If the tunnel drops, the watchdog kills the old process and starts a new one.

    Thread-safe: the watchdog runs in a daemon thread and coordinates with
    the main thread via a threading.Lock.
    """

    def __init__(
        self,
        vm_ip: str,
        username: str = "azureuser",
        local_port: int = 5001,
        remote_port: int = 5000,
        eval_local_port: int = 5050,
        eval_remote_port: int = 5050,
        health_check_interval: int = 30,
        max_retries: int = 5,
        retry_delay: int = 5,
    ):
        self.vm_ip = vm_ip
        self.username = username
        self.local_port = local_port
        self.remote_port = remote_port
        self.eval_local_port = eval_local_port
        self.eval_remote_port = eval_remote_port
        self.health_check_interval = health_check_interval
        self.max_retries = max_retries
        self.retry_delay = retry_delay

        self._proc: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._watchdog_thread: threading.Thread | None = None

    # ------------------------------------------------------------------
    # SSH tunnel lifecycle
    # ------------------------------------------------------------------

    def _build_ssh_cmd(self) -> list[str]:
        return [
            "ssh", "-N",
            "-L", f"{self.local_port}:localhost:{self.remote_port}",
            "-L", f"{self.eval_local_port}:localhost:{self.eval_remote_port}",
            "-o", "StrictHostKeyChecking=no",
            "-o", "UserKnownHostsFile=/dev/null",
            "-o", "ServerAliveInterval=30",
            "-o", "ServerAliveCountMax=3",
            f"{self.username}@{self.vm_ip}",
        ]

    def _start_tunnel(self) -> None:
        cmd = self._build_ssh_cmd()
        logger.info("Starting SSH tunnel to %s@%s", self.username, self.vm_ip)
        self._proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            start_new_session=True,
        )
        # Give the tunnel a moment to establish
        time.sleep(1.0)
        if self._proc.poll() is not None:
            stderr = self._proc.stderr.read().decode() if self._proc.stderr else ""
            logger.error("SSH tunnel exited immediately: %s", stderr[:200])
            self._proc = None
        else:
            logger.info(
                "SSH tunnel up: localhost:%d -> %s:%d, localhost:%d -> %s:%d",
                self.local_port, self.vm_ip, self.remote_port,
                self.eval_local_port, self.vm_ip, self.eval_remote_port,
            )

    def _kill_tunnel(self) -> None:
        if self._proc is not None:
            logger.info("Killing SSH tunnel (pid=%d)", self._proc.pid)
            try:
                self._proc.terminate()
                self._proc.wait(timeout=5)
            except (ProcessLookupError, subprocess.TimeoutExpired):
                try:
                    self._proc.kill()
                except ProcessLookupError:
                    pass
            self._proc = None

    # ------------------------------------------------------------------
    # Health checking
    # ------------------------------------------------------------------

    def _is_healthy(self) -> bool:
        try:
            resp = requests.get(
                f"http://localhost:{self.local_port}/screenshot", timeout=10
            )
            return resp.status_code == 200
        except requests.RequestException:
            return False

    def _reconnect(self) -> bool:
        """Kill and restart the tunnel. Returns True if healthy after restart."""
        self._kill_tunnel()
        time.sleep(1)
        self._start_tunnel()
        if self._proc is None:
            return False
        return self._is_healthy()

    # ------------------------------------------------------------------
    # Watchdog
    # ------------------------------------------------------------------

    def _watchdog_loop(self) -> None:
        while not self._stop_event.is_set():
            self._stop_event.wait(self.health_check_interval)
            if self._stop_event.is_set():
                break
            with self._lock:
                if not self._is_healthy():
                    logger.warning("Health check failed, reconnecting tunnel")
                    self._reconnect()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Start the SSH tunnel and watchdog thread."""
        with self._lock:
            self._start_tunnel()
        self._stop_event.clear()
        self._watchdog_thread = threading.Thread(
            target=self._watchdog_loop, daemon=True
        )
        self._watchdog_thread.start()

    def close(self) -> None:
        """Stop the watchdog and kill the SSH tunnel."""
        self._stop_event.set()
        if self._watchdog_thread is not None:
            self._watchdog_thread.join(timeout=5)
            self._watchdog_thread = None
        with self._lock:
            self._kill_tunnel()
        logger.info("WAAConnection closed")

    def ensure_healthy(self) -> None:
        """Block until the tunnel is healthy or raise after max retries."""
        for attempt in range(1, self.max_retries + 1):
            with self._lock:
                if self._is_healthy():
                    logger.info("Tunnel healthy")
                    return
                logger.warning(
                    "Tunnel unhealthy (attempt %d/%d), reconnecting",
                    attempt, self.max_retries,
                )
                self._reconnect()
            if self._is_healthy():
                logger.info("Tunnel recovered on attempt %d", attempt)
                return
            time.sleep(self.retry_delay)
        raise ConnectionError(
            f"WAA tunnel not healthy after {self.max_retries} retries"
        )

    # ------------------------------------------------------------------
    # Context manager
    # ------------------------------------------------------------------

    def __enter__(self) -> WAAConnection:
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.close()
