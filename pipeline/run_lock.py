"""
Prevents overlapping pipeline runs. Cloud Run's gunicorn config allows up
to 8 concurrent threads on one instance -- without this guard, two
overlapping /run requests (a network retry, an accidental double-request,
Cloud Scheduler's own retry behavior) each independently execute the full
pipeline, doubling API cost and racing on Firestore's rotation write.
"""

from datetime import datetime, timedelta, timezone
import os

from google.cloud import firestore

from pipeline.logging_config import get_logger

logger = get_logger(__name__)

GCP_PROJECT_ID = os.environ["GCP_PROJECT_ID"]
db = firestore.Client(project=GCP_PROJECT_ID)
RUN_LOCK_DOC = db.collection("pipeline_state").document("run_lock")

# A crashed run that never releases its lock shouldn't block forever --
# treat anything older than this as stale and let a new run proceed.
STALE_LOCK_MINUTES = 10


def acquire_run_lock() -> bool:
    """Atomically checks and acquires the run lock. Returns True if
    acquired (safe to proceed), False if another run is already active."""

    @firestore.transactional
    def _try_acquire(transaction):
        snapshot = RUN_LOCK_DOC.get(transaction=transaction)
        now = datetime.now(timezone.utc)

        if snapshot.exists:
            data = snapshot.to_dict()
            started_at = data.get("started_at")
            is_stale = started_at is None or (now - started_at) > timedelta(minutes=STALE_LOCK_MINUTES)
            if data.get("status") == "running" and not is_stale:
                return False

        transaction.set(RUN_LOCK_DOC, {"status": "running", "started_at": now})
        return True

    acquired = _try_acquire(db.transaction())

    if not acquired:
        logger.warning("pipeline run rejected -- another run is already in progress")

    return acquired


def release_run_lock() -> None:
    RUN_LOCK_DOC.set({"status": "idle"})