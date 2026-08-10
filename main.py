"""
Cloud Run entrypoint. Cloud Scheduler triggers POST /run on a schedule;
GET / is a lightweight health check that doesn't run the pipeline.

Local testing: python main.py (uses Flask's dev server, port from $PORT
or 8080). Actual deployment runs this under gunicorn instead -- see the
Dockerfile/deploy command, not this file's __main__ block.
"""

import os

from flask import Flask, jsonify

from pipeline.graph import build_graph
from pipeline.logging_config import get_logger
from pipeline.run_lock import acquire_run_lock, release_run_lock

app = Flask(__name__)
logger = get_logger(__name__)


@app.route("/", methods=["GET"])
def health_check():
    return jsonify({"status": "ok"}), 200


@app.route("/run", methods=["POST"])
def run_pipeline():
    if not acquire_run_lock():
        return jsonify({"status": "skipped", "reason": "another run is already in progress"}), 409

    logger.info("pipeline run triggered")

    try:
        graph = build_graph()
        result = graph.invoke({})
    except Exception as e:
        logger.exception(f"pipeline run FAILED: {e}")
        return jsonify({"status": "failed", "error": str(e)}), 500
    finally:
        release_run_lock()

    logger.info(f"pipeline run completed for topic '{result.get('topic_key')}'")

    return jsonify({
        "status": "completed",
        "topic_key": result.get("topic_key"),
        "retries_used": result.get("retry_count", 0),
        "image_path": result.get("image_path"),
    }), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)