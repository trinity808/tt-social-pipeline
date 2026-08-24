"""
Manages pending-review records in Firestore. This is separate from
LangGraph's own checkpointer -- the checkpointer only persists graph
execution state (what value a variable had, where paused). This module
tracks the human-facing review lifecycle (pending/approved/rejected) and
the per-platform cadence eligibility, locked in at generation time per the
Phase 5 design, not re-evaluated whenever a review is actually resolved.
"""

from datetime import datetime, timedelta, timezone
import os

from google.cloud import firestore

from pipeline.cadence import should_post_today
from pipeline.logging_config import get_logger
from review.notifications import send_supersede_email

from dotenv import load_dotenv

load_dotenv()

logger = get_logger(__name__)

GCP_PROJECT_ID = os.environ["GCP_PROJECT_ID"]
db = firestore.Client(project=GCP_PROJECT_ID)

REVIEW_EXPIRY_HOURS = 48

PLATFORMS = ("linkedin", "facebook", "instagram")


def create_pending_review(thread_id: str, topic_key: str, image_url: str) -> dict:
    """Creates a new pending-review record, locking in each platform's
    cadence eligibility at the moment of generation -- not re-evaluated
    later when the review is actually resolved. image_url is stored here
    (not just passed to the email) so a later nudge/reminder can retrieve
    it without re-uploading -- the local image file may not even exist
    anymore by then, given Cloud Run's ephemeral filesystem."""
    cadence_eligibility = {
        platform: should_post_today(platform) for platform in PLATFORMS
    }

    record = {
        "thread_id": thread_id,
        "topic_key": topic_key,
        "status": "pending",
        "generated_at": datetime.now(timezone.utc),
        "cadence_eligibility": cadence_eligibility,
        "image_url": image_url,
    }

    db.collection("pending_reviews").document(thread_id).set(record)
    logger.info(f"pending review created for thread {thread_id}, topic '{topic_key}'")

    return record


def resolve_pending_review(thread_id: str, decision: str) -> dict | None:
    """Atomically checks a review is still pending and marks it resolved
    in one transaction -- same race-condition fix as run_lock.py, applied
    here to the confirmed 'first click wins' requirement. Returns the
    record if this call resolved it; returns None if it was invalid or
    already resolved by an earlier call -- callers must treat None as
    'don't touch the graph at all', per the resume_unknown lesson."""

    @firestore.transactional
    def _try_resolve(transaction):
        doc_ref = db.collection("pending_reviews").document(thread_id)
        snapshot = doc_ref.get(transaction=transaction)

        if not snapshot.exists:
            return None

        record = snapshot.to_dict()
        if record.get("status") != "pending":
            return None

        transaction.update(doc_ref, {
            "status": decision,
            "resolved_at": datetime.now(timezone.utc),
        })
        return record

    return _try_resolve(db.transaction())

def check_and_resolve_stale_review() -> str:
    pending_docs = list(
        db.collection("pending_reviews").where("status", "==", "pending").stream()
    )

    if not pending_docs:
        return "proceed"

    now = datetime.now(timezone.utc)
    any_still_valid = False

    for doc in pending_docs:
        record = doc.to_dict()
        age = now - record["generated_at"]

        if age < timedelta(hours=REVIEW_EXPIRY_HOURS):
            any_still_valid = True
            logger.info(f"pending review {doc.id} still within expiry window -- skipping this run")
        else:
            doc.reference.update({"status": "superseded"})

            try:
                send_supersede_email(
                    thread_id=doc.id,
                    topic_key=record["topic_key"],
                )
            except Exception:
                logger.warning(
                    "Failed to send supersede email for thread %s",
                    doc.id,
                    exc_info=True,
                )

    return "skip" if any_still_valid else "proceed"