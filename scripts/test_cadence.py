from datetime import date, datetime, timezone

import pytest

from pipeline.cadence import POSTING_DAYS, should_post_today


@pytest.mark.parametrize(
    ("platform", "posting_date", "expected"),
    [
        ("linkedin", date(2026, 8, 3), True),    # Monday
        ("linkedin", date(2026, 8, 4), False),   # Tuesday
        ("linkedin", date(2026, 8, 5), True),    # Wednesday
        ("linkedin", date(2026, 8, 6), False),   # Thursday
        ("linkedin", date(2026, 8, 7), True),    # Friday
        ("linkedin", date(2026, 8, 8), False),   # Saturday
        ("linkedin", date(2026, 8, 9), False),   # Sunday
        ("facebook", date(2026, 8, 3), True),    # Monday
        ("facebook", date(2026, 8, 8), True),    # Saturday
        ("facebook", date(2026, 8, 9), True),    # Sunday
        ("instagram", date(2026, 8, 3), True),   # Monday
        ("instagram", date(2026, 8, 8), True),   # Saturday
        ("instagram", date(2026, 8, 9), True),   # Sunday
    ],
)
def test_should_post_today_uses_platform_cadence(
    platform: str,
    posting_date: date,
    expected: bool,
) -> None:
    assert should_post_today(platform, posting_date) is expected


def test_platform_matching_is_case_insensitive_and_trimmed() -> None:
    assert should_post_today("  LinkedIn  ", date(2026, 8, 3)) is True
    assert should_post_today("  FACEBOOK  ", date(2026, 8, 9)) is True
    assert should_post_today(" Instagram ", date(2026, 8, 9)) is True


def test_aware_datetime_is_converted_to_business_timezone() -> None:
    # August 4 at 1:00 a.m. UTC is still Monday evening in Phoenix.
    utc_time = datetime(2026, 8, 4, 1, 0, tzinfo=timezone.utc)

    assert should_post_today("linkedin", utc_time) is True
    assert should_post_today("facebook", utc_time) is True
    assert should_post_today("instagram", utc_time) is True


@pytest.mark.parametrize("platform", ["", "   ", "tiktok"])
def test_blank_or_unsupported_platform_raises_value_error(
    platform: str,
) -> None:
    with pytest.raises(ValueError):
        should_post_today(platform, date(2026, 8, 4))


def test_non_string_platform_raises_type_error() -> None:
    with pytest.raises(TypeError):
        should_post_today(
            None,
            date(2026, 8, 4),
        )  # type: ignore[arg-type]


def test_invalid_today_type_raises_type_error() -> None:
    with pytest.raises(TypeError):
        should_post_today(
            "linkedin",
            "2026-08-04",
        )  # type: ignore[arg-type]


def test_posting_days_configuration_is_read_only() -> None:
    with pytest.raises(TypeError):
        POSTING_DAYS["linkedin"] = frozenset({0})  # type: ignore[index]