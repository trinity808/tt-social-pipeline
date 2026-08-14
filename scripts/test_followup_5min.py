from __future__ import annotations

import time
from pathlib import Path

from review.notifications import (
    send_review_email,
    send_review_followup_email,
)


# ---------------------------------------------------------------------------
# Temporary local test configuration
# ---------------------------------------------------------------------------

FOLLOWUP_DELAY_SECONDS = 5 * 60

# Creating this file while the script is waiting simulates
# somebody approving the review.
APPROVAL_FLAG = Path("/tmp/tt-social-review-approved")


THREAD_ID = "test-followup-5min-001"
TOPIC_KEY = "psychological_evaluations"

LINKEDIN_CAPTION = (
    "TEST LinkedIn caption. "
    "This post is being used to test the review workflow."
)

INSTAGRAM_CAPTION = (
    "TEST Instagram caption. "
    "This post is being used to test the review workflow."
)

FACEBOOK_CAPTION = (
    "TEST Facebook caption. "
    "This post is being used to test the review workflow."
)

# Your teammate's real GCP URL can replace this later.
IMAGE_URL = ""


def main() -> None:
    # Remove an old approval flag from a previous test.
    if APPROVAL_FLAG.exists():
        APPROVAL_FLAG.unlink()

    print("Sending initial review email...")

    send_review_email(
        thread_id=THREAD_ID,
        topic_key=TOPIC_KEY,
        linkedin_caption=LINKEDIN_CAPTION,
        instagram_caption=INSTAGRAM_CAPTION,
        facebook_caption=FACEBOOK_CAPTION,
        image_url=IMAGE_URL,
    )

    print("Initial review email sent.")
    print()
    print("Waiting 5 minutes...")
    print()
    print(
        "To simulate APPROVAL before 5 minutes, "
        "open another terminal and run:"
    )
    print()
    print(
        "touch /tmp/tt-social-review-approved"
    )
    print()
    print(
        "If you do nothing, a follow-up email "
        "will be sent after 5 minutes."
    )

    time.sleep(FOLLOWUP_DELAY_SECONDS)

    # ------------------------------------------------------------------
    # Simulated review-state check
    # ------------------------------------------------------------------

    if APPROVAL_FLAG.exists():
        print()
        print("Review was approved.")
        print("No follow-up email will be sent.")

        APPROVAL_FLAG.unlink()

        return

    # ------------------------------------------------------------------
    # Still pending -> send reminder
    # ------------------------------------------------------------------

    print()
    print(
        "Review is still pending after 5 minutes."
    )
    print("Sending follow-up email...")

    send_review_followup_email(
        thread_id=THREAD_ID,
        topic_key=TOPIC_KEY,
        linkedin_caption=LINKEDIN_CAPTION,
        instagram_caption=INSTAGRAM_CAPTION,
        facebook_caption=FACEBOOK_CAPTION,
        image_url=IMAGE_URL,
    )

    print(
        "Follow-up email sent successfully."
    )


if __name__ == "__main__":
    main()