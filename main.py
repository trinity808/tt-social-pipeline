"""
Cloud Run entrypoint. Cloud Scheduler triggers POST /run on a schedule;
GET / is a lightweight health check that doesn't run the pipeline.

Local testing: python main.py (uses Flask's dev server, port from $PORT
or 8080). Actual deployment runs this under gunicorn instead -- see the
Dockerfile/deploy command, not this file's __main__ block.
"""

import os
import uuid

from flask import Flask, jsonify, request

from pipeline.graph import build_graph
from pipeline.logging_config import get_logger
from pipeline.run_lock import acquire_run_lock, release_run_lock
from pipeline.review import resolve_pending_review, get_pending_review_status, check_and_resolve_stale_review
from review.notifications import send_resolution_email

from langgraph.types import Command

app = Flask(__name__)
logger = get_logger(__name__)

SERVICE_ROLE = os.getenv("SERVICE_ROLE", "private")

@app.route("/", methods=["GET"])
def health_check():
    return jsonify({"status": "ok"}), 200


@app.route("/run", methods=["POST"])
def run_pipeline():
    if SERVICE_ROLE != "private":
        return jsonify({"status": "forbidden"}), 403

    if not acquire_run_lock():
        return jsonify({"status": "skipped", "reason": "another run is already in progress"}), 409

    thread_id = str(uuid.uuid4())
    logger.info(f"pipeline run triggered (thread {thread_id})")

    try:
        graph = build_graph()
        result = graph.invoke({}, config={"configurable": {"thread_id": thread_id}})
    except Exception as e:
        logger.exception(f"pipeline run FAILED: {e}")
        return jsonify({"status": "failed", "error": str(e)}), 500
    finally:
        release_run_lock()

    if "__interrupt__" in result:
        logger.info(f"pipeline run paused for review (thread {thread_id})")
        return jsonify({
            "status": "awaiting_review",
            "thread_id": thread_id,
            "topic_key": result.get("topic_key"),
        }), 200
    
    logger.info(f"pipeline run completed for topic '{result.get('topic_key')}'")

    return jsonify({
        "status": "completed",
        "thread_id": thread_id,
        "topic_key": result.get("topic_key"),
        "retries_used": result.get("retry_count", 0),
        "image_path": result.get("image_path"),
    }), 200


@app.route("/review", methods=["GET"])
def review_confirm_page():
    thread_id = request.args.get("thread_id")
    decision = request.args.get("decision")

    if not thread_id or decision not in ("approved", "rejected"):
        return "Invalid review link.", 400

    record = get_pending_review_status(thread_id)

    if record is None or record.get("status") != "pending":
        return "<h2>This review link is invalid or has already been actioned.</h2>", 409

    topic_display = record.get("topic_key", "").replace("_", " ").title()
    decision_label = "Approve" if decision == "approved" else "Reject"

    return f"""
    <!DOCTYPE html>
    <html>
    <body style="font-family: Arial, sans-serif; max-width: 500px; margin: 60px auto; text-align: center;">
        <h2>Confirm your decision</h2>
        <p>Topic: <strong>{topic_display}</strong></p>
        <p>You are about to <strong>{decision_label}</strong> this post.</p>
        <form method="POST" action="/review/confirm" onsubmit="document.getElementById('btn').disabled=true; document.getElementById('btn').innerText='Processing... this may take up to a minute';">
            <input type="hidden" name="thread_id" value="{thread_id}">
            <input type="hidden" name="decision" value="{decision}">
            <button id="btn" type="submit" style="padding: 12px 24px; font-size: 16px;">
                Confirm {decision_label}
            </button>
        </form>
    </body>
    </html>
    """

@app.route("/review/confirm", methods=["POST"])
def review_confirm_action():
    thread_id = request.form.get("thread_id")
    decision = request.form.get("decision")

    if not thread_id or decision not in ("approved", "rejected"):
        return jsonify({"status": "invalid_request"}), 400

    record = resolve_pending_review(thread_id, decision)

    if record is None:
        logger.warning(f"review confirmation for thread {thread_id} was invalid or already actioned")
        return jsonify({"status": "already_actioned_or_invalid"}), 409

    logger.info(f"resuming thread {thread_id} with decision: {decision}")

    try:
        graph = build_graph()
        result = graph.invoke(Command(resume=decision), config={"configurable": {"thread_id": thread_id}})
    except Exception as e:
        logger.exception(f"failed to resume thread {thread_id}: {e}")
        return jsonify({"status": "failed", "error": str(e)}), 500

    logger.info(f"review for thread {thread_id} resolved as {decision}")

    try:
        send_resolution_email(
            thread_id=thread_id,
            topic_key=result.get("topic_key", ""),
            decision=decision,
        )
    except Exception as e:
        logger.warning(f"resolution email failed to send for thread {thread_id}: {e}")

    topic_display = record.get("topic_key", "").replace("_", " ").title()
    decision_label = "Approve" if decision == "approved" else "Reject"
    
    return f"""
    <!DOCTYPE html>
    <html>
    <body style="font-family: Arial, sans-serif; max-width: 500px; margin: 60px auto; text-align: center;">
        <h2>Decision recorded</h2>
        <p>Topic: <strong>{topic_display}</strong></p>
        <p>Your decision to <strong>{decision_label}</strong> this post has been recorded.</p>
    </body>
    </html>
    """

@app.route("/check-pending-reviews", methods=["POST"])
def check_pending_reviews_endpoint():
    if SERVICE_ROLE != "private":
        return jsonify({"status": "forbidden"}), 403

    try:
        result = check_and_resolve_stale_review()
    except Exception as e:
        logger.exception(f"check_pending_reviews failed: {e}")
        return jsonify({"status": "failed", "error": str(e)}), 500

    if result == "proceed":
        logger.info("nothing pending -- triggering fresh content generation")
        return run_pipeline()

    return jsonify({"status": "ok", "check_result": result}), 200

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)