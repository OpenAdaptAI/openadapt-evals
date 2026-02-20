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
