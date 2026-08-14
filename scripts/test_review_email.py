from review.emailer import send_review_email

from unittest.mock import patch

import pytest

from review.emailer import (
    build_review_links,
    get_review_recipients,
)


def test_build_review_links(monkeypatch):
    monkeypatch.setenv(
        "REVIEW_PUBLIC_BASE_URL",
        "https://example.com",
    )

    approve, reject = build_review_links(
        "thread-123"
    )

    assert (
        approve
        == "https://example.com/review/decision"
        "?thread_id=thread-123&decision=approve"
    )

    assert (
        reject
        == "https://example.com/review/decision"
        "?thread_id=thread-123&decision=reject"
    )


def test_development_recipients(monkeypatch):
    monkeypatch.setenv(
        "ENVIRONMENT",
        "development",
    )
    monkeypatch.setenv(
        "REVIEW_DEV_TO",
        "primary@example.com",
    )
    monkeypatch.setenv(
        "REVIEW_DEV_CC",
        "secondary@example.com",
    )

    recipients = get_review_recipients()

    assert recipients.to == (
        "primary@example.com",
    )

    assert recipients.cc == (
        "secondary@example.com",
    )


def test_production_recipients(monkeypatch):
    monkeypatch.setenv(
        "ENVIRONMENT",
        "production",
    )
    monkeypatch.setenv(
        "REVIEW_PROD_TO",
        "prod-primary@example.com",
    )
    monkeypatch.setenv(
        "REVIEW_PROD_CC",
        "prod-secondary@example.com",
    )

    recipients = get_review_recipients()

    assert recipients.to == (
        "prod-primary@example.com",
    )

    assert recipients.cc == (
        "prod-secondary@example.com",
    )


def test_invalid_environment(monkeypatch):
    monkeypatch.setenv(
        "ENVIRONMENT",
        "something-wrong",
    )

    with pytest.raises(
        ValueError,
        match="Unsupported ENVIRONMENT",
    ):
        get_review_recipients()


def test_blank_thread_id(monkeypatch):
    monkeypatch.setenv(
        "REVIEW_PUBLIC_BASE_URL",
        "https://example.com",
    )

    with pytest.raises(
        ValueError,
        match="thread_id cannot be blank",
    ):
        build_review_links("")
        
def main() -> None:
    send_review_email(
        thread_id="test-thread-123",
        topic_key="psychological_evaluations",
        linkedin_caption=(
            "Test LinkedIn caption for Trinity Tree. "
            "This is only a development review email."
        ),
        instagram_caption=(
            "Test Instagram caption for Trinity Tree. "
            "#TestOnly"
        ),
        facebook_caption=(
            "Test Facebook caption for Trinity Tree. "
            "This post is not intended for publication."
        ),
        image_url="",
    )

    print("Review email sent successfully.")


if __name__ == "__main__":
    main()