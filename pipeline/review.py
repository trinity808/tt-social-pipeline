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
from review.notifications import send_supersede_email, send_review_followup_email

from dotenv import load_dotenv

load_dotenv()

logger = get_logger(__name__)

GCP_PROJECT_ID = os.environ["GCP_PROJECT_ID"]
db = firestore.Client(project=GCP_PROJECT_ID)

REVIEW_EXPIRY_HOURS = 48

NUDGE_THRESHOLD_HOURS = 24

PLATFORMS = ("linkedin", "facebook", "instagram")


def get_pending_review_status(thread_id: str) -> dict | None:
    """Read-only check -- never modifies anything. Used by the GET
    confirmation page to validate a link before showing the confirm
    button, without the read itself having any side effect."""
    doc_ref = db.collection("pending_reviews").document(thread_id)
    snapshot = doc_ref.get()
    if not snapshot.exists:
        return None
    return snapshot.to_dict()


def create_pending_review(thread_id: str, topic_key: str, image_url: str, draft) -> dict:
    """Creates a new pending-review record, locking in each platform's
    cadence eligibility at the moment of generation -- not re-evaluated
    later when the review is actually resolved. image_url and the three
    platform captions are stored here (not just passed to the initial
    email) so a later nudge/reminder can rebuild the notification without
    re-uploading the image or re-running the writer -- the draft object
    itself only lives in the checkpointer, which this module deliberately
    stays separate from."""
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
        "linkedin_caption": draft.linkedin.caption,
        "instagram_caption": draft.instagram.caption,
        "facebook_caption": draft.facebook.caption,
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

            if age >= timedelta(hours=NUDGE_THRESHOLD_HOURS) and not record.get("nudge_sent", False):
                missing_fields = [
                    field for field in ("linkedin_caption", "instagram_caption", "facebook_caption", "image_url")
                    if field not in record
                ]
                if missing_fields:
                    logger.warning(
                        f"pending review {doc.id} is past the nudge threshold but is missing "
                        f"{missing_fields} (created before nudge support was added) -- skipping nudge"
                    )
                else:
                    try:
                        send_review_followup_email(
                            thread_id=doc.id,
                            topic_key=record["topic_key"],
                            linkedin_caption=record["linkedin_caption"],
                            instagram_caption=record["instagram_caption"],
                            facebook_caption=record["facebook_caption"],
                            image_url=record["image_url"],
                        )
                        doc.reference.update({"nudge_sent": True})
                        logger.info(f"nudge sent for pending review {doc.id}")
                    except Exception:
                        logger.warning(f"failed to send nudge for thread {doc.id}", exc_info=True)
        else:
            doc.reference.update({"status": "superseded"})
            logger.info(
                f"pending review {doc.id} superseded after {age} "
                "-- clearing stale entry"
            )

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