from __future__ import annotations

import os
from urllib.parse import urlencode


def build_review_links(
    review_id: str,
) -> tuple[str, str]:
    base_url = os.getenv(
        "REVIEW_PUBLIC_BASE_URL",
        "",
    ).strip().rstrip("/")

    if not base_url:
        raise ValueError(
            "REVIEW_PUBLIC_BASE_URL is missing."
        )

    if not review_id.strip():
        raise ValueError("review_id cannot be blank.")

    approve_query = urlencode(
        {
            "review_id": review_id,
            "decision": "approve",
        }
    )

    reject_query = urlencode(
        {
            "review_id": review_id,
            "decision": "reject",
        }
    )

    approve_url = (
        f"{base_url}/review/decision?{approve_query}"
    )
    reject_url = (
        f"{base_url}/review/decision?{reject_query}"
    )

    return approve_url, reject_url