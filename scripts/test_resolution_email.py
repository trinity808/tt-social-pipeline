from __future__ import annotations

import sys

from review.notifications import send_resolution_email


THREAD_ID = "test-resolution-001"
TOPIC_KEY = "psychological_evaluations"


def main() -> None:
    if len(sys.argv) not in {2, 3}:
        print(
            "Usage:\n"
            "  python -m scripts.test_resolution_email "
            "<approve|reject> [resolver_email]"
        )
        raise SystemExit(1)

    decision = sys.argv[1].strip().lower()

    resolver_email = (
        sys.argv[2].strip()
        if len(sys.argv) == 3
        else None
    )

    if decision not in {"approve", "reject"}:
        print(
            "Decision must be either 'approve' or 'reject'."
        )
        raise SystemExit(1)

    print()
    print("Testing review resolution notification")
    print("--------------------------------------")
    print(f"Decision: {decision}")
    print(
        f"Resolved by: "
        f"{resolver_email or 'Not provided'}"
    )
    print()

    send_resolution_email(
        thread_id=THREAD_ID,
        topic_key=TOPIC_KEY,
        decision=decision,
        resolved_by_email=resolver_email,
    )

    print()
    print(
        f"{decision.upper()} notification sent successfully."
    )

    if resolver_email:
        print(
            "The resolver was excluded from the notification."
        )
    else:
        print(
            "No resolver email was provided, so the resolution "
            "notification was sent using the default recipients."
        )


if __name__ == "__main__":
    main()