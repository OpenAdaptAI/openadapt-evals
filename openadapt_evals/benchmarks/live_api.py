"""Simple API server for live benchmark monitoring.

This module provides a Flask API endpoint that serves the benchmark_live.json
file for the viewer to poll.

Usage:
    # Start the API server
    python -m openadapt_evals.benchmarks.live_api

    # Or with custom port
    python -m openadapt_evals.benchmarks.live_api --port 5001

    # Then open viewer in browser at http://localhost:5001
"""

from __future__ import annotations

import argparse
import json
import logging
from pathlib import Path

from flask import Flask, jsonify, send_file
from flask_cors import CORS

logger = logging.getLogger(__name__)

# Create Flask app
app = Flask(__name__)
CORS(app)  # Enable CORS for local development

# Configuration
LIVE_FILE = Path("benchmark_live.json")


@app.route("/api/benchmark-live")
def get_benchmark_live():
    """Get current live benchmark status."""
    try:
        if LIVE_FILE.exists():
            with open(LIVE_FILE) as f:
                data = json.load(f)
            return jsonify(data)
        else:
            return jsonify({"status": "no_data", "message": "No live tracking data available"})
    except Exception as e:
        logger.error(f"Error reading live tracking file: {e}")
        return jsonify({"status": "error", "message": str(e)}), 500


@app.route("/")
def index():
    """Serve the benchmark viewer HTML."""
    viewer_path = Path(__file__).parent.parent.parent / "benchmark_results" / "viewer.html"

    if viewer_path.exists():
        return send_file(viewer_path)
    else:
        return """
        <html>
        <head><title>Live Benchmark Viewer</title></head>
        <body>
            <h1>Live Benchmark Viewer</h1>
            <p>No viewer.html found. Generate one with:</p>
            <pre>uv run python -m openadapt_evals.benchmarks.cli view --run-name {run_name}</pre>
            <p>Or access the API directly:</p>
            <ul>
                <li><a href="/api/benchmark-live">/api/benchmark-live</a> - Current live status</li>
            </ul>
        </body>
        </html>
        """


@app.route("/health")
def health():
    """Health check endpoint."""
    return jsonify({"status": "ok"})


def main():
    """Run the API server."""
    parser = argparse.ArgumentParser(description="Live benchmark API server")
    parser.add_argument("--port", type=int, default=5001, help="Port to run on")
    parser.add_argument("--host", type=str, default="127.0.0.1", help="Host to bind to")
    parser.add_argument("--live-file", type=str, help="Path to benchmark_live.json")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")

    args = parser.parse_args()

    # Set live file path
    global LIVE_FILE
    if args.live_file:
        LIVE_FILE = Path(args.live_file)

    # Configure logging
    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )

    logger.info(f"Starting live benchmark API server on {args.host}:{args.port}")
    logger.info(f"Monitoring file: {LIVE_FILE.absolute()}")
    logger.info(f"API endpoint: http://{args.host}:{args.port}/api/benchmark-live")

    app.run(host=args.host, port=args.port, debug=args.debug)


if __name__ == "__main__":
    main()
