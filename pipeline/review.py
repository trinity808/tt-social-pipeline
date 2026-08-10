"""
Manages pending-review records in Firestore. This is separate from
LangGraph's own checkpointer -- the checkpointer only persists graph
execution state (what value a variable had, where paused). This module
tracks the human-facing review lifecycle (pending/approved/rejected) and
the per-platform cadence eligibility, locked in at generation time per the
Phase 5 design, not re-evaluated whenever a review is actually resolved.
"""

from datetime import datetime, timezone
import os

from google.cloud import firestore

from pipeline.cadence import should_post_today
from pipeline.logging_config import get_logger

logger = get_logger(__name__)

GCP_PROJECT_ID = os.environ["GCP_PROJECT_ID"]
db = firestore.Client(project=GCP_PROJECT_ID)

PLATFORMS = ("linkedin", "facebook", "instagram")


def create_pending_review(thread_id: str, topic_key: str) -> dict:
    """Creates a new pending-review record. Cadence eligibility is checked
    and locked in right now, at generation time -- a later, possibly
    delayed approval honors this locked-in value, not whatever's true on
    whatever day the approval actually happens."""
    cadence_eligibility = {
        platform: should_post_today(platform) for platform in PLATFORMS
    }

    record = {
        "thread_id": thread_id,
        "topic_key": topic_key,
        "status": "pending",
        "generated_at": datetime.now(timezone.utc),
        "cadence_eligibility": cadence_eligibility,
    }

    db.collection("pending_reviews").document(thread_id).set(record)
    logger.info(f"pending review created for thread {thread_id}, topic '{topic_key}'")

    return record