"""Per-platform posting cadence decisions.

This module is intentionally independent of the LangGraph pipeline. Phase 5 can
call :func:`should_post_today` before a platform's publish node is executed.
"""

from datetime import date, datetime
from types import MappingProxyType
from zoneinfo import ZoneInfo


BUSINESS_TIMEZONE = "America/Phoenix"

# datetime.date.weekday() values: Monday=0 through Sunday=6.
# Change this single configuration when the business cadence changes.
POSTING_DAYS = MappingProxyType(
    {
        "linkedin": frozenset({0, 2, 4}),              # Monday, Wednesday, Friday
        "facebook": frozenset(range(7)),               # Every day
        "instagram": frozenset(range(7)),              # Every day
    }
)


def should_post_today(
    platform: str,
    today: date | datetime | None = None,
    *,
    timezone_name: str = BUSINESS_TIMEZONE,
) -> bool:
    """Return whether ``platform`` is configured to post on the given day.

    Args:
        platform: LinkedIn, Facebook, or Instagram. Matching is case-insensitive
            and surrounding whitespace is ignored.
        today: Date to evaluate. When omitted, the current date in
            ``timezone_name`` is used. An aware datetime is converted to that
            timezone before its date is evaluated.
        timezone_name: IANA timezone used for the production "today" boundary.

    Raises:
        TypeError: If ``platform`` or ``today`` has an unsupported type.
        ValueError: If the platform name is blank or unsupported.
    """
    if not isinstance(platform, str):
        raise TypeError("platform must be a string")

    normalized_platform = platform.strip().lower()
    if not normalized_platform:
        raise ValueError("platform cannot be blank")
    if normalized_platform not in POSTING_DAYS:
        supported = ", ".join(sorted(POSTING_DAYS))
        raise ValueError(
            f"Unsupported platform '{platform}'. Supported platforms: {supported}."
        )

    business_timezone = ZoneInfo(timezone_name)
    if today is None:
        posting_date = datetime.now(business_timezone).date()
    elif isinstance(today, datetime):
        if today.tzinfo is not None:
            today = today.astimezone(business_timezone)
        posting_date = today.date()
    elif isinstance(today, date):
        posting_date = today
    else:
        raise TypeError("today must be a date, datetime, or None")

    return posting_date.weekday() in POSTING_DAYS[normalized_platform]