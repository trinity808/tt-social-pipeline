import json
import os
import random
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from google.cloud import firestore

load_dotenv()

CONTENT_PATH = "content/site_content.json"
COLLECTION = "topics"
RECENCY_WINDOW_DAYS = 7

db = firestore.Client(project=os.environ["GCP_PROJECT_ID"])


def _all_topic_keys() -> list[str]:
    with open(CONTENT_PATH, "r", encoding="utf-8") as f:
        content = json.load(f)
    return list(content.keys())


def select_topic() -> str:
    """Randomly picks a topic not used in the last RECENCY_WINDOW_DAYS days.
    Falls back to the least-recently-used topic if somehow nothing is
    eligible -- shouldn't normally trigger with 12 topics and a 7-day
    window at daily cadence, but avoids a hard failure if it ever does."""
    all_keys = _all_topic_keys()
    cutoff = datetime.now(timezone.utc) - timedelta(days=RECENCY_WINDOW_DAYS)

    eligible = []
    last_used_by_key = {}

    for key in all_keys:
        doc = db.collection(COLLECTION).document(key).get()
        if not doc.exists:
            eligible.append(key)
            last_used_by_key[key] = None
            continue
        last_used = doc.to_dict().get("last_used")
        last_used_by_key[key] = last_used
        if last_used is None or last_used < cutoff:
            eligible.append(key)

    if eligible:
        return random.choice(eligible)

    oldest_key = min(
        all_keys,
        key=lambda k: last_used_by_key[k] or datetime.min.replace(tzinfo=timezone.utc),
    )
    return oldest_key


def record_topic_used(topic_key: str) -> None:
    print(f"[rotation] writing last_used for '{topic_key}'...")
    db.collection(COLLECTION).document(topic_key).set(
        {"last_used": datetime.now(timezone.utc)}
    )
    print(f"[rotation] write completed for '{topic_key}'")