from __future__ import annotations

import os
import smtplib
import ssl
from dataclasses import dataclass
from email.message import EmailMessage

from dotenv import load_dotenv

from pipeline.logging_config import get_logger
from pipeline.secrets import _get_secret


load_dotenv()

logger = get_logger(__name__)


SMTP_PASSWORD_SECRET_ID = "review-gmail-app-password"


@dataclass(frozen=True)
class ReviewRecipients:
    to: tuple[str, ...]
    cc: tuple[str, ...]


def _split_addresses(value: str) -> tuple[str, ...]:
    return tuple(
        address.strip()
        for address in value.split(",")
        if address.strip()
    )


def get_review_recipients() -> ReviewRecipients:
    environment = os.getenv(
        "ENVIRONMENT",
        "development",
    ).strip().lower()

    if environment in {"development", "dev", "testing", "test"}:
        to_value = os.getenv("REVIEW_DEV_TO", "")
        cc_value = os.getenv("REVIEW_DEV_CC", "")

    elif environment in {"production", "prod"}:
        to_value = os.getenv("REVIEW_PROD_TO", "")
        cc_value = os.getenv("REVIEW_PROD_CC", "")

    else:
        raise ValueError(
            f"Unsupported ENVIRONMENT: {environment!r}"
        )

    to = _split_addresses(to_value)
    cc = _split_addresses(cc_value)

    if not to:
        raise ValueError(
            "At least one review recipient is required."
        )

    return ReviewRecipients(
        to=to,
        cc=cc,
    )


def send_email(
    *,
    subject: str,
    text_body: str,
    html_body: str,
    recipients: ReviewRecipients | None = None,
) -> None:
    sender = os.getenv(
        "REVIEW_EMAIL_FROM",
        "",
    ).strip()

    if not sender:
        raise ValueError(
            "REVIEW_EMAIL_FROM is missing."
        )

    smtp_host = os.getenv(
        "REVIEW_SMTP_HOST",
        "smtp.gmail.com",
    ).strip()

    smtp_port = int(
        os.getenv(
            "REVIEW_SMTP_PORT",
            "465",
        )
    )

    if recipients is None:
        recipients = get_review_recipients()

    password = _get_secret(
        SMTP_PASSWORD_SECRET_ID
    )

    message = EmailMessage()

    message["Subject"] = subject
    message["From"] = sender
    message["To"] = ", ".join(recipients.to)

    if recipients.cc:
        message["Cc"] = ", ".join(recipients.cc)

    message.set_content(text_body)

    message.add_alternative(
        html_body,
        subtype="html",
    )

    context = ssl.create_default_context()

    logger.info(
        "[review-email] Sending message to=%s cc=%s",
        recipients.to,
        recipients.cc,
    )

    with smtplib.SMTP_SSL(
        smtp_host,
        smtp_port,
        context=context,
        timeout=30,
    ) as smtp:
        smtp.login(
            sender,
            password,
        )

        smtp.send_message(
            message,
            from_addr=sender,
            to_addrs=[
                *recipients.to,
                *recipients.cc,
            ],
        )

    logger.info(
        "[review-email] Message sent successfully"
    )