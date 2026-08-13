from __future__ import annotations

import html
import os
from urllib.parse import urlencode

from pipeline.logging_config import get_logger
from review.emailer import (
    ReviewRecipients,
    get_review_recipients,
    send_email,
)


logger = get_logger(__name__)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _display_topic(topic_key: str) -> str:
    """
    Convert a topic key into a human-friendly display value.

    Example:
        psychological_evaluations
        -> Psychological Evaluations
    """
    cleaned = topic_key.strip()

    if not cleaned:
        return "Social Media Post"

    return (
        cleaned
        .replace("_", " ")
        .replace("-", " ")
        .title()
    )


def build_review_links(
    thread_id: str,
) -> tuple[str, str]:
    """
    Build the shared Approve and Reject URLs for a review request.

    The review endpoint itself is owned by the review/checkpointer
    implementation. This module only constructs the URLs that are
    placed into the notification emails.
    """
    thread_id = thread_id.strip()

    if not thread_id:
        raise ValueError(
            "thread_id cannot be blank."
        )

    base_url = os.getenv(
        "REVIEW_PUBLIC_BASE_URL",
        "",
    ).strip().rstrip("/")

    if not base_url:
        raise ValueError(
            "REVIEW_PUBLIC_BASE_URL is missing."
        )

    decision_path = os.getenv(
        "REVIEW_DECISION_PATH",
        "/review/decision",
    ).strip()

    if not decision_path.startswith("/"):
        decision_path = f"/{decision_path}"

    approve_query = urlencode(
        {
            "thread_id": thread_id,
            "decision": "approve",
        }
    )

    reject_query = urlencode(
        {
            "thread_id": thread_id,
            "decision": "reject",
        }
    )

    approve_url = (
        f"{base_url}{decision_path}?{approve_query}"
    )

    reject_url = (
        f"{base_url}{decision_path}?{reject_query}"
    )

    return approve_url, reject_url


def _build_image_html(
    image_url: str,
) -> str:
    """
    Build the HTML used to display the generated social image.

    The image must be available through an HTTP(S) URL so the
    recipient's email client can retrieve it.
    """
    image_url = image_url.strip()

    if not image_url:
        return ""

    if not image_url.startswith(
        ("https://", "http://")
    ):
        logger.warning(
            "[review-notification] image_url is not "
            "a public HTTP(S) URL; preview omitted"
        )

        return """
        <p>
            <strong>Image preview:</strong>
            unavailable.
        </p>
        """

    safe_image_url = html.escape(
        image_url,
        quote=True,
    )

    return f"""
        <div style="margin: 24px 0;">
            <p>
                <strong>Post Image</strong>
            </p>

            <img
                src="{safe_image_url}"
                alt="Social media post preview"
                style="
                    max-width: 600px;
                    width: 100%;
                    height: auto;
                    border-radius: 8px;
                "
            />
        </div>
    """


def _caption_html(
    platform: str,
    caption: str,
) -> str:
    """
    Build a reusable HTML block for one platform caption.
    """
    safe_platform = html.escape(platform)
    safe_caption = html.escape(caption)

    return f"""
        <h3>{safe_platform}</h3>

        <div
            style="
                white-space: pre-wrap;
                background: #f7f7f7;
                padding: 16px;
                border-radius: 6px;
                margin-bottom: 20px;
            "
        >{safe_caption}</div>
    """


# ---------------------------------------------------------------------------
# Initial review request
# ---------------------------------------------------------------------------


def send_review_email(
    thread_id: str,
    topic_key: str,
    linkedin_caption: str,
    instagram_caption: str,
    facebook_caption: str,
    image_url: str,
) -> None:
    """
    Send the initial human-review request.

    This is the public function intended to be called by the
    LangGraph send_for_review node.

    The caller decides WHEN the post needs review and provides
    the post data.

    This function handles HOW the review notification is
    formatted and sent.
    """
    approve_url, reject_url = build_review_links(
        thread_id
    )

    recipients = get_review_recipients()

    topic_display = _display_topic(
        topic_key
    )

    subject = (
        "[TT Social Review] "
        f"Approval needed — {topic_display}"
    )

    # ------------------------------------------------------------------
    # Plain-text fallback
    # ------------------------------------------------------------------

    text_body = f"""
A new Trinity Tree social media post is ready for review.

Topic:
{topic_display}


LINKEDIN
--------------------------------------------------
{linkedin_caption}


INSTAGRAM
--------------------------------------------------
{instagram_caption}


FACEBOOK
--------------------------------------------------
{facebook_caption}


IMAGE
--------------------------------------------------
{image_url or "No image URL provided."}


APPROVE POST
{approve_url}


REJECT POST
{reject_url}


Only one review decision is required.

The review window is 48 hours.

Approval confirms the content only. Actual publishing remains
subject to each platform's posting cadence.

Once the post has been approved or rejected, later review
attempts should be treated as already resolved.

Thread ID: {thread_id}
""".strip()

    # ------------------------------------------------------------------
    # HTML version
    # ------------------------------------------------------------------

    safe_topic = html.escape(
        topic_display
    )

    safe_thread_id = html.escape(
        thread_id
    )

    safe_approve_url = html.escape(
        approve_url,
        quote=True,
    )

    safe_reject_url = html.escape(
        reject_url,
        quote=True,
    )

    image_html = _build_image_html(
        image_url
    )

    linkedin_html = _caption_html(
        "LinkedIn",
        linkedin_caption,
    )

    instagram_html = _caption_html(
        "Instagram",
        instagram_caption,
    )

    facebook_html = _caption_html(
        "Facebook",
        facebook_caption,
    )

    html_body = f"""
    <!DOCTYPE html>
    <html>
    <body
        style="
            font-family: Arial, Helvetica, sans-serif;
            line-height: 1.6;
            color: #222222;
            max-width: 700px;
            margin: 0 auto;
            padding: 24px;
        "
    >

        <h2 style="margin-bottom: 8px;">
            Trinity Tree Social Review
        </h2>

        <p>
            A new social media post is ready for review.
        </p>

        <p>
            <strong>Topic:</strong>
            {safe_topic}
        </p>

        {image_html}

        <hr>

        {linkedin_html}

        {instagram_html}

        {facebook_html}

        <div
            style="
                margin-top: 32px;
                margin-bottom: 32px;
            "
        >
            <a
                href="{safe_approve_url}"
                style="
                    display: inline-block;
                    padding: 12px 22px;
                    margin-right: 12px;
                    background: #2e7d32;
                    color: #ffffff;
                    text-decoration: none;
                    border-radius: 5px;
                    font-weight: bold;
                "
            >
                Approve Post
            </a>

            <a
                href="{safe_reject_url}"
                style="
                    display: inline-block;
                    padding: 12px 22px;
                    background: #b71c1c;
                    color: #ffffff;
                    text-decoration: none;
                    border-radius: 5px;
                    font-weight: bold;
                "
            >
                Reject Post
            </a>
        </div>

        <p>
            <strong>Review window:</strong>
            48 hours
        </p>

        <p>
            Only one review decision is required.
        </p>

        <p>
            Approval confirms the content only.
            Actual publishing remains subject to each
            platform's posting cadence.
        </p>

        <p>
            Once the post has been approved or rejected,
            later review attempts should be treated as
            already resolved.
        </p>

        <hr>

        <p
            style="
                font-size: 12px;
                color: #666666;
            "
        >
            Review thread: {safe_thread_id}
        </p>

    </body>
    </html>
    """

    logger.info(
        "[review-notification] Preparing initial "
        "review email thread_id=%s topic=%s",
        thread_id,
        topic_key,
    )

    send_email(
        subject=subject,
        text_body=text_body,
        html_body=html_body,
        recipients=recipients,
    )

    logger.info(
        "[review-notification] Initial review "
        "email sent thread_id=%s",
        thread_id,
    )


# ---------------------------------------------------------------------------
# 24-hour pending reminder
# ---------------------------------------------------------------------------


def send_review_followup_email(
    thread_id: str,
    topic_key: str,
    linkedin_caption: str,
    instagram_caption: str,
    facebook_caption: str,
    image_url: str,
) -> None:
    """
    Send a reminder when a review has remained pending for 24 hours.

    IMPORTANT:
    This function does NOT determine whether 24 hours have passed.

    The caller must first determine that:
        1. The review is still pending.
        2. At least 24 hours have passed.
        3. A reminder should be sent.

    This function only formats and sends the reminder.
    """
    approve_url, reject_url = build_review_links(
        thread_id
    )

    recipients = get_review_recipients()

    topic_display = _display_topic(
        topic_key
    )

    subject = (
        "[TT Social Review] Reminder — "
        f"Approval still needed — {topic_display}"
    )

    # ------------------------------------------------------------------
    # Plain-text fallback
    # ------------------------------------------------------------------

    text_body = f"""
This is a reminder that a Trinity Tree social media post is still
waiting for review.

The original review request was sent at least 24 hours ago and
no decision has been recorded.

Topic:
{topic_display}


LINKEDIN
--------------------------------------------------
{linkedin_caption}


INSTAGRAM
--------------------------------------------------
{instagram_caption}


FACEBOOK
--------------------------------------------------
{facebook_caption}


IMAGE
--------------------------------------------------
{image_url or "No image URL provided."}


APPROVE POST
{approve_url}


REJECT POST
{reject_url}


Only one review decision is required.

Approval confirms the content only. Actual publishing remains
subject to each platform's posting cadence.

Thread ID: {thread_id}
""".strip()

    # ------------------------------------------------------------------
    # HTML version
    # ------------------------------------------------------------------

    safe_topic = html.escape(
        topic_display
    )

    safe_thread_id = html.escape(
        thread_id
    )

    safe_approve_url = html.escape(
        approve_url,
        quote=True,
    )

    safe_reject_url = html.escape(
        reject_url,
        quote=True,
    )

    image_html = _build_image_html(
        image_url
    )

    linkedin_html = _caption_html(
        "LinkedIn",
        linkedin_caption,
    )

    instagram_html = _caption_html(
        "Instagram",
        instagram_caption,
    )

    facebook_html = _caption_html(
        "Facebook",
        facebook_caption,
    )

    html_body = f"""
    <!DOCTYPE html>
    <html>
    <body
        style="
            font-family: Arial, Helvetica, sans-serif;
            line-height: 1.6;
            color: #222222;
            max-width: 700px;
            margin: 0 auto;
            padding: 24px;
        "
    >

        <h2>
            Trinity Tree Social Review Reminder
        </h2>

        <p>
            This social media post is still waiting
            for review.
        </p>

        <p>
            The original request was sent at least
            <strong>24 hours ago</strong> and no
            decision has been recorded.
        </p>

        <p>
            <strong>Topic:</strong>
            {safe_topic}
        </p>

        {image_html}

        <hr>

        {linkedin_html}

        {instagram_html}

        {facebook_html}

        <div
            style="
                margin-top: 32px;
                margin-bottom: 32px;
            "
        >
            <a
                href="{safe_approve_url}"
                style="
                    display: inline-block;
                    padding: 12px 22px;
                    margin-right: 12px;
                    background: #2e7d32;
                    color: #ffffff;
                    text-decoration: none;
                    border-radius: 5px;
                    font-weight: bold;
                "
            >
                Approve Post
            </a>

            <a
                href="{safe_reject_url}"
                style="
                    display: inline-block;
                    padding: 12px 22px;
                    background: #b71c1c;
                    color: #ffffff;
                    text-decoration: none;
                    border-radius: 5px;
                    font-weight: bold;
                "
            >
                Reject Post
            </a>
        </div>

        <p>
            Only one review decision is required.
        </p>

        <p>
            Approval confirms the content only.
            Actual publishing remains subject to
            each platform's posting cadence.
        </p>

        <hr>

        <p
            style="
                font-size: 12px;
                color: #666666;
            "
        >
            Review thread: {safe_thread_id}
        </p>

    </body>
    </html>
    """

    logger.info(
        "[review-notification] Preparing 24-hour "
        "follow-up thread_id=%s topic=%s",
        thread_id,
        topic_key,
    )

    send_email(
        subject=subject,
        text_body=text_body,
        html_body=html_body,
        recipients=recipients,
    )

    logger.info(
        "[review-notification] 24-hour follow-up "
        "sent thread_id=%s",
        thread_id,
    )


# ---------------------------------------------------------------------------
# Resolution notification
# ---------------------------------------------------------------------------


def send_resolution_email(
    *,
    thread_id: str,
    topic_key: str,
    decision: str,
    resolved_by_email: str | None = None,
) -> None:
    """
    Send a notification after a review has been resolved.

    Supported decisions:
        approve
        approved
        reject
        rejected

    If resolved_by_email is supplied, that reviewer is removed
    from the notification recipients so the follow-up is sent
    only to the non-clicking reviewer.

    If the resolver identity is unavailable, both configured
    reviewers receive the resolution notification.
    """
    normalized_decision = (
        decision.strip().lower()
    )

    if normalized_decision in {
        "approve",
        "approved",
    }:
        decision_label = "APPROVED"

        decision_message = (
            "The social media post has been approved."
        )

        detail_message = (
            "Publishing will still occur only for "
            "platforms that are eligible according "
            "to their posting cadence."
        )

    elif normalized_decision in {
        "reject",
        "rejected",
    }:
        decision_label = "REJECTED"

        decision_message = (
            "The social media post has been rejected."
        )

        detail_message = (
            "The rejected post will not be published."
        )

    else:
        raise ValueError(
            "decision must be 'approve', 'approved', "
            "'reject', or 'rejected'."
        )

    recipients = get_review_recipients()

    if resolved_by_email:
        recipients = _exclude_resolver(
            recipients=recipients,
            resolved_by_email=resolved_by_email,
            thread_id=thread_id,
        )

        if recipients is None:
            return

    topic_display = _display_topic(
        topic_key
    )

    subject = (
        "[TT Social Review] "
        f"{decision_label} — {topic_display}"
    )

    # ------------------------------------------------------------------
    # Plain-text fallback
    # ------------------------------------------------------------------

    text_body = f"""
The Trinity Tree social media review has been resolved.

Topic:
{topic_display}

Status:
{decision_label}

{decision_message}

{detail_message}

No further review action is required.

Thread ID: {thread_id}
""".strip()

    # ------------------------------------------------------------------
    # HTML version
    # ------------------------------------------------------------------

    safe_topic = html.escape(
        topic_display
    )

    safe_thread_id = html.escape(
        thread_id
    )

    safe_decision_message = html.escape(
        decision_message
    )

    safe_detail_message = html.escape(
        detail_message
    )

    html_body = f"""
    <!DOCTYPE html>
    <html>
    <body
        style="
            font-family: Arial, Helvetica, sans-serif;
            line-height: 1.6;
            color: #222222;
            max-width: 700px;
            margin: 0 auto;
            padding: 24px;
        "
    >

        <h2>
            Social Review {decision_label}
        </h2>

        <p>
            <strong>Topic:</strong>
            {safe_topic}
        </p>

        <p>
            <strong>Status:</strong>
            {decision_label}
        </p>

        <p>
            {safe_decision_message}
        </p>

        <p>
            {safe_detail_message}
        </p>

        <p>
            <strong>
                No further review action is required.
            </strong>
        </p>

        <hr>

        <p
            style="
                font-size: 12px;
                color: #666666;
            "
        >
            Review thread: {safe_thread_id}
        </p>

    </body>
    </html>
    """

    logger.info(
        "[review-notification] Preparing resolution "
        "email thread_id=%s decision=%s",
        thread_id,
        decision_label,
    )

    send_email(
        subject=subject,
        text_body=text_body,
        html_body=html_body,
        recipients=recipients,
    )

    logger.info(
        "[review-notification] Resolution email sent "
        "thread_id=%s decision=%s",
        thread_id,
        decision_label,
    )


def _exclude_resolver(
    *,
    recipients: ReviewRecipients,
    resolved_by_email: str,
    thread_id: str,
) -> ReviewRecipients | None:
    """
    Remove the reviewer who clicked Approve/Reject so the
    resolution notification goes to the non-clicking reviewer.

    If the resolver was the primary To recipient and only the
    CC recipient remains, the remaining recipient is promoted
    to To.
    """
    resolver = (
        resolved_by_email
        .strip()
        .lower()
    )

    if not resolver:
        return recipients

    remaining_to = tuple(
        address
        for address in recipients.to
        if address.lower() != resolver
    )

    remaining_cc = tuple(
        address
        for address in recipients.cc
        if address.lower() != resolver
    )

    if remaining_to:
        return ReviewRecipients(
            to=remaining_to,
            cc=remaining_cc,
        )

    if remaining_cc:
        return ReviewRecipients(
            to=(remaining_cc[0],),
            cc=remaining_cc[1:],
        )

    logger.info(
        "[review-notification] No remaining reviewer "
        "to notify thread_id=%s",
        thread_id,
    )

    return None