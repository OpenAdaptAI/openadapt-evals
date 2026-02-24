#!/usr/bin/env python3
"""Lightweight evaluate endpoint that runs inside the WAA Docker container.

Imports WAA's evaluator modules (getters + metrics) and exposes them via Flask.
The PythonController connects to the Windows VM at 172.30.0.2:5000.

Deploy:
    docker cp evaluate_server.py winarena:/tmp/
    docker exec -d winarena python /tmp/evaluate_server.py

Then SSH tunnel: ssh -N -L 5050:localhost:5050 azureuser@<VM_IP>
"""

import json
import logging
import os
import sys
import time
import traceback
import uuid

# Add WAA paths
sys.path.insert(0, "/client")
sys.path.insert(0, "/client/desktop_env")

from flask import Flask, jsonify, request

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger("evaluate_server")

# Import WAA controller and evaluators
from controllers.python import PythonController
from evaluators import getters as getter_module
from evaluators import metrics as metric_module

# Controller pointing to Windows VM inside QEMU
controller = PythonController(vm_ip="172.30.0.2")

TASK_EXAMPLES_PATH = "/client/evaluation_examples_windows"

app = Flask(__name__)


class MockEnv:
    """Minimal env object matching what WAA getters expect."""

    def __init__(self, ctrl):
        self.controller = ctrl
        self.cache_dir = "/tmp/eval_cache"
        os.makedirs(self.cache_dir, exist_ok=True)


env = MockEnv(controller)


@app.route("/probe", methods=["GET"])
def probe():
    return jsonify({"status": "ok", "service": "evaluate_server"})


@app.route("/task/<task_id>", methods=["GET"])
def get_task(task_id):
    """Return task config by ID, searching all domains."""
    examples_dir = os.path.join(TASK_EXAMPLES_PATH, "examples")
    for domain in os.listdir(examples_dir):
        domain_dir = os.path.join(examples_dir, domain)
        if os.path.isdir(domain_dir):
            task_file = os.path.join(domain_dir, f"{task_id}.json")
            if os.path.exists(task_file):
                with open(task_file) as f:
                    return jsonify(json.load(f))
    return jsonify({"error": f"Task {task_id} not found"}), 404


# ---------------------------------------------------------------------------
# Task setup handlers — mirror WAA's SetupController logic
# ---------------------------------------------------------------------------

WAA_SERVER = "http://172.30.0.2:5000"
SETUP_CACHE = "/tmp/setup_cache"
os.makedirs(SETUP_CACHE, exist_ok=True)


def _setup_download(files, **_kwargs):
    """Download files from URLs and upload to Windows VM."""
    import requests as req
    from requests_toolbelt.multipart.encoder import MultipartEncoder

    for f in files:
        url = f["url"]
        path = f["path"]
        cache_path = os.path.join(
            SETUP_CACHE,
            f"{uuid.uuid5(uuid.NAMESPACE_URL, url)}_{os.path.basename(path)}",
        )
        if not os.path.exists(cache_path):
            for attempt in range(3):
                try:
                    resp = req.get(url, stream=True, timeout=60)
                    resp.raise_for_status()
                    with open(cache_path, "wb") as fh:
                        for chunk in resp.iter_content(chunk_size=8192):
                            if chunk:
                                fh.write(chunk)
                    logger.info(f"Downloaded {url} -> {cache_path}")
                    break
                except Exception as e:
                    logger.warning(f"Download attempt {attempt+1} failed for {url}: {e}")
                    if attempt == 2:
                        raise

        form = MultipartEncoder({
            "file_path": path,
            "file_data": (os.path.basename(path), open(cache_path, "rb")),
        })
        resp = req.post(
            f"{WAA_SERVER}/setup/upload",
            headers={"Content-Type": form.content_type},
            data=form,
            timeout=60,
        )
        if resp.status_code == 200:
            logger.info(f"Uploaded {os.path.basename(path)} -> {path}")
        else:
            logger.error(f"Upload failed ({resp.status_code}): {resp.text[:200]}")


def _setup_launch(command, shell=False, **_kwargs):
    """Launch a command on Windows."""
    import requests as req
    resp = req.post(
        f"{WAA_SERVER}/setup/launch",
        json={"command": command, "shell": shell},
        timeout=30,
    )
    if resp.status_code != 200:
        logger.error(f"Launch failed ({resp.status_code}): {resp.text[:200]}")


def _setup_sleep(seconds=1, **_kwargs):
    """Sleep for UI to settle."""
    time.sleep(seconds)


def _setup_execute(command, shell=False, **_kwargs):
    """Execute a command on Windows."""
    import requests as req
    resp = req.post(
        f"{WAA_SERVER}/setup/execute",
        json={"command": command, "shell": shell},
        timeout=60,
    )
    if resp.status_code != 200:
        logger.error(f"Execute failed ({resp.status_code}): {resp.text[:200]}")


def _setup_open(path, **_kwargs):
    """Open a file on Windows."""
    import requests as req
    resp = req.post(
        f"{WAA_SERVER}/setup/open_file",
        json={"path": path},
        timeout=30,
    )
    if resp.status_code != 200:
        logger.error(f"Open failed ({resp.status_code}): {resp.text[:200]}")


def _setup_activate_window(window_name, strict=False, by_class=False, **_kwargs):
    """Activate a window by name."""
    import requests as req
    resp = req.post(
        f"{WAA_SERVER}/setup/activate_window",
        json={"window_name": window_name, "strict": strict, "by_class": by_class},
        timeout=10,
    )
    if resp.status_code != 200:
        logger.error(f"Activate window failed ({resp.status_code}): {resp.text[:200]}")


def _setup_close_all(**_kwargs):
    """Close all windows."""
    import requests as req
    resp = req.post(f"{WAA_SERVER}/setup/close_all", json={}, timeout=30)
    if resp.status_code != 200:
        logger.error(f"Close all failed ({resp.status_code}): {resp.text[:200]}")


def _setup_create_folder(path, **_kwargs):
    """Create a folder on Windows."""
    import requests as req
    resp = req.post(
        f"{WAA_SERVER}/setup/create_folder",
        json={"path": path},
        timeout=30,
    )
    if resp.status_code != 200:
        logger.error(f"Create folder failed ({resp.status_code}): {resp.text[:200]}")


def _setup_create_file(path, content="", **_kwargs):
    """Create a file on Windows."""
    import requests as req
    resp = req.post(
        f"{WAA_SERVER}/setup/create_file",
        json={"path": path, "content": content},
        timeout=30,
    )
    if resp.status_code != 200:
        logger.error(f"Create file failed ({resp.status_code}): {resp.text[:200]}")


def _setup_clear_task_files(**_kwargs):
    """Clear task files from previous run."""
    import requests as req
    resp = req.post(
        f"{WAA_SERVER}/setup/clear_task_files",
        json={},
        timeout=30,
    )
    if resp.status_code != 200:
        logger.warning(f"Clear task files failed ({resp.status_code})")


SETUP_HANDLERS = {
    "download": _setup_download,
    "launch": _setup_launch,
    "sleep": _setup_sleep,
    "execute": _setup_execute,
    "command": _setup_execute,
    "open": _setup_open,
    "activate_window": _setup_activate_window,
    "close_all": _setup_close_all,
    "create_folder": _setup_create_folder,
    "create_file": _setup_create_file,
    "clear_task_files": _setup_clear_task_files,
}


@app.route("/setup", methods=["POST"])
def run_setup():
    """Execute task setup config array (mirrors WAA SetupController)."""
    config = request.json.get("config", [])
    results = []
    for cfg in config:
        cfg_type = cfg.get("type", "")
        params = cfg.get("parameters", {})
        try:
            handler = SETUP_HANDLERS.get(cfg_type)
            if handler:
                handler(**params)
                logger.info(f"Setup {cfg_type}: ok")
                results.append({"type": cfg_type, "status": "ok"})
            else:
                logger.warning(f"Unknown setup type: {cfg_type}")
                results.append({"type": cfg_type, "status": "skipped"})
        except Exception as e:
            logger.error(f"Setup {cfg_type} failed: {e}")
            traceback.print_exc()
            results.append({"type": cfg_type, "status": "error", "error": str(e)})
    return jsonify({"status": "ok", "results": results})


@app.route("/evaluate", methods=["POST"])
def evaluate():
    """Evaluate current VM state against task criteria."""
    task_config = request.json
    if not task_config:
        return jsonify({"error": "No task config"}), 400

    evaluator_config = task_config.get("evaluator", {})
    if not evaluator_config:
        return jsonify({"success": False, "score": 0.0, "reason": "No evaluator config"})

    try:
        # Run postconfig (activate windows, sleep, open files)
        for cmd in evaluator_config.get("postconfig", []):
            _run_postconfig_cmd(cmd)

        # Get function spec
        func_spec = evaluator_config.get("func", "exact_match")
        result_spec = evaluator_config.get("result", {})
        expected_spec = evaluator_config.get("expected", {})

        # Handle list-type evaluators (multiple metrics)
        if isinstance(func_spec, list):
            results = result_spec if isinstance(result_spec, list) else [result_spec]
            expecteds = expected_spec if isinstance(expected_spec, list) else [expected_spec]
            scores = []

            for i, fn in enumerate(func_spec):
                r = results[i] if i < len(results) else {}
                e = expecteds[i] if i < len(expecteds) else {}
                actual = _get_actual(r)
                expected = _get_expected(e)
                score = _run_metric(fn, actual, expected)
                logger.info(f"  Metric {fn}: actual={repr(actual)[:200]}, expected={repr(expected)[:200]}, score={score}")
                scores.append(score)

            conj = evaluator_config.get("conj", "and")
            final_score = min(scores) if conj != "or" else max(scores)
        else:
            actual = _get_actual(result_spec)
            expected = _get_expected(expected_spec)
            final_score = _run_metric(func_spec, actual, expected)
            logger.info(f"  Metric {func_spec}: actual={repr(actual)[:200]}, expected={repr(expected)[:200]}, score={final_score}")

        success = float(final_score) >= 1.0
        return jsonify({
            "success": success,
            "score": float(final_score),
            "reason": f"Score: {final_score:.2f}",
        })
    except Exception as e:
        logger.exception("Evaluation error")
        return jsonify({
            "success": False,
            "score": 0.0,
            "reason": f"Error: {e}",
            "traceback": traceback.format_exc(),
        }), 500


def _run_postconfig_cmd(cmd):
    """Run a postconfig command (activate window, sleep, open file)."""
    cmd_type = cmd.get("type", "")
    params = cmd.get("parameters", {})

    if cmd_type == "sleep":
        time.sleep(params.get("seconds", 1))
    elif cmd_type == "activate_window":
        window_name = params.get("window_name", params.get("name", ""))
        strict = params.get("strict", False)
        try:
            import requests as req
            req.post(
                "http://172.30.0.2:5000/setup/activate_window",
                json={"window_name": window_name, "strict": strict},
                timeout=10,
            )
        except Exception as e:
            logger.warning(f"activate_window failed: {e}")
    elif cmd_type == "open":
        path = params.get("path", "")
        try:
            controller.execute_shell_command(f'start "" "{path}"')
        except Exception as e:
            logger.warning(f"open failed: {e}")
    else:
        logger.debug(f"Unknown postconfig type: {cmd_type}")


def _get_actual(result_spec):
    """Run a getter to get the actual value from the VM."""
    result_type = result_spec.get("type", "")
    getter_name = f"get_{result_type}"
    getter_func = getattr(getter_module, getter_name, None)
    if getter_func is None:
        logger.error(f"Getter not found: {getter_name}")
        return None
    try:
        val = getter_func(env, result_spec)
        logger.info(f"Getter {getter_name} returned: {repr(val)[:200]}")
        return val
    except Exception as e:
        logger.error(f"Getter {getter_name} failed: {e}")
        traceback.print_exc()
        return None


def _get_expected(expected_spec):
    """Get the expected value for comparison."""
    exp_type = expected_spec.get("type", "")

    if exp_type == "rule":
        return expected_spec.get("rules", {})

    if exp_type == "cloud_file":
        # Download expected file from URL
        getter_func = getattr(getter_module, "get_cloud_file", None)
        if getter_func:
            try:
                return getter_func(env, expected_spec)
            except Exception as e:
                logger.error(f"get_cloud_file failed: {e}")
                return None

    if "value" in expected_spec:
        return expected_spec["value"]

    # Try as a getter
    if exp_type:
        getter_name = f"get_{exp_type}"
        getter_func = getattr(getter_module, getter_name, None)
        if getter_func:
            try:
                return getter_func(env, expected_spec)
            except Exception as e:
                logger.error(f"Expected getter {getter_name} failed: {e}")
                return None

    return expected_spec.get("expected")


def _run_metric(func_name, actual, expected):
    """Run a metric function."""
    metric_func = getattr(metric_module, func_name, None)
    if metric_func is None:
        logger.error(f"Metric not found: {func_name}")
        return 0.0
    try:
        score = metric_func(actual, expected)
        return float(score)
    except Exception as e:
        logger.error(f"Metric {func_name} failed: {e}")
        traceback.print_exc()
        return 0.0


if __name__ == "__main__":
    logger.info("Starting evaluate server on port 5050")
    logger.info(f"WAA evaluators loaded from /client/desktop_env/evaluators/")
    logger.info(f"Controller pointing to 172.30.0.2:5000")
    app.run(host="0.0.0.0", port=5050, debug=False)
