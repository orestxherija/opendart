"""KST dates, date arguments, and search windows."""

from __future__ import annotations

import zoneinfo
from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from opendart_mcp.domain import dates
from opendart_mcp.domain.dates import (
    KST,
    DateWindow,
    add_months,
    cap_to_three_months,
    month_end,
    parse_date_arg,
    parse_horizon,
    resolve_window,
    today_kst,
    within_three_months,
    yyyymmdd,
)

TODAY = date(2026, 10, 22)


def test_kst_is_utc_plus_nine():
    moment = datetime(2026, 1, 1, tzinfo=KST)
    assert moment.utcoffset() == timedelta(hours=9)


def test_kst_falls_back_without_a_zone_database(monkeypatch):
    def missing(key):
        raise zoneinfo.ZoneInfoNotFoundError(key)

    monkeypatch.setattr(dates, "ZoneInfo", missing)
    fallback = dates._korea()
    assert fallback.utcoffset(None) == timedelta(hours=9)
    assert fallback.tzname(None) == "KST"


def test_today_kst_converts_aware_times():
    assert today_kst(datetime(2026, 10, 21, 15, 0, tzinfo=UTC)) == date(2026, 10, 22)
    assert today_kst(datetime(2026, 10, 21, 14, 59, tzinfo=UTC)) == date(2026, 10, 21)
    assert today_kst(datetime(2026, 10, 22, 8, 0, tzinfo=timezone(timedelta(hours=9)))) == date(
        2026, 10, 22
    )
    assert isinstance(today_kst(), date)


def test_today_kst_rejects_naive_times():
    naive = datetime.fromisoformat("2026-10-22T08:00:00")
    with pytest.raises(ValueError, match="timezone-aware"):
        today_kst(naive)


@pytest.mark.parametrize(
    ("start", "months", "expected"),
    [
        (date(2025, 3, 31), -1, date(2025, 2, 28)),
        (date(2024, 3, 31), -1, date(2024, 2, 29)),
        (date(2025, 1, 31), 1, date(2025, 2, 28)),
        (date(2025, 12, 15), 1, date(2026, 1, 15)),
        (date(2026, 1, 15), -1, date(2025, 12, 15)),
        (date(2024, 2, 29), 12, date(2025, 2, 28)),
        (date(2025, 5, 31), -3, date(2025, 2, 28)),
    ],
)
def test_add_months_clamps_the_day(start, months, expected):
    assert add_months(start, months) == expected


def test_add_months_rejects_out_of_range_years():
    with pytest.raises(ValueError, match="out of range"):
        add_months(date(1, 1, 1), -1)
    with pytest.raises(ValueError, match="out of range"):
        add_months(date(9999, 12, 1), 1)


def test_month_end():
    assert month_end(2024, 2) == date(2024, 2, 29)
    assert month_end(2025, 12) == date(2025, 12, 31)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("2025-01-01", date(2025, 1, 1)),
        ("20250101", date(2025, 1, 1)),
        ("2025.01.01", date(2025, 1, 1)),
        ("2025.1.5.", date(2025, 1, 5)),
        ("2025/1/5", date(2025, 1, 5)),
        (" today ", TODAY),
        ("Today", TODAY),
        ("yesterday", date(2026, 10, 21)),
        ("ytd", date(2026, 1, 1)),
        ("YTD", date(2026, 1, 1)),
        ("0d", TODAY),
        ("30d", date(2026, 9, 22)),
        ("30 days", date(2026, 9, 22)),
        ("1 day", date(2026, 10, 21)),
        ("2w", date(2026, 10, 8)),
        ("2 weeks", date(2026, 10, 8)),
        ("6m", date(2026, 4, 22)),
        ("6 months", date(2026, 4, 22)),
        ("1 month", date(2026, 9, 22)),
        ("2y", date(2024, 10, 22)),
        ("1 year", date(2025, 10, 22)),
        ("3Y", date(2023, 10, 22)),
    ],
)
def test_parse_date_arg(text, expected):
    assert parse_date_arg(text, today=TODAY) == expected


def test_relative_months_clamp_the_day():
    assert parse_date_arg("1m", today=date(2025, 3, 31)) == date(2025, 2, 28)
    assert parse_date_arg("1y", today=date(2024, 2, 29)) == date(2023, 2, 28)


@pytest.mark.parametrize(
    "text",
    [
        "",
        "soon",
        "30",
        "30x",
        "-30d",
        "2025-13-01",
        "2025-02-30",
        "20251301",
        "2025-01",
        "100000d",
        "101y",
    ],
)
def test_parse_date_arg_rejects_other_forms(text):
    with pytest.raises(ValueError, match="Invalid date") as error:
        parse_date_arg(text, today=TODAY)
    assert "30d, 2w, 6m, or 2y" in str(error.value)


def test_parse_date_arg_explains_impossible_dates():
    with pytest.raises(ValueError, match="day 30 must be in range"):
        parse_date_arg("2025-02-30", today=TODAY)


def test_long_durations_are_rejected():
    with pytest.raises(ValueError, match="limited to 100 years"):
        parse_date_arg("1300m", today=TODAY)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("90d", date(2027, 1, 20)),
        ("2w", date(2026, 11, 5)),
        ("3m", date(2027, 1, 22)),
        ("1y", date(2027, 10, 22)),
        ("today", TODAY),
        ("2026-12-31", date(2026, 12, 31)),
    ],
)
def test_parse_horizon_counts_forward(text, expected):
    assert parse_horizon(text, today=TODAY) == expected


def test_parse_horizon_clamps_and_rejects():
    assert parse_horizon("1m", today=date(2026, 1, 31)) == date(2026, 2, 28)
    with pytest.raises(ValueError, match="Invalid date 'ytd'"):
        parse_horizon("ytd", today=TODAY)


def test_date_window():
    window = DateWindow(date(2026, 10, 1), date(2026, 10, 22))
    assert window.days == 22
    assert DateWindow(TODAY, TODAY).days == 1
    with pytest.raises(ValueError, match="starts"):
        DateWindow(date(2026, 10, 23), TODAY)


def test_resolve_window_defaults():
    window = resolve_window(None, None, today=TODAY, default_since="90d")
    assert window == DateWindow(date(2026, 7, 24), TODAY)


def test_resolve_window_counts_since_back_from_until():
    window = resolve_window("90d", "2024-12-31", today=TODAY, default_since="30d")
    assert window == DateWindow(date(2024, 10, 2), date(2024, 12, 31))
    assert resolve_window(None, "2024-12-31", today=TODAY, default_since="1y").start == date(
        2023, 12, 31
    )


def test_resolve_window_with_absolute_and_relative_until():
    window = resolve_window("2026-01-01", "7d", today=TODAY, default_since="90d")
    assert window == DateWindow(date(2026, 1, 1), date(2026, 10, 15))


def test_resolve_window_rejects_inverted_bounds():
    with pytest.raises(ValueError, match=r"since \(2026-10-23\) is after until \(2026-10-22\)"):
        resolve_window("2026-10-23", None, today=TODAY, default_since="90d")
    with pytest.raises(ValueError, match="Invalid date"):
        resolve_window("whenever", None, today=TODAY, default_since="90d")


@pytest.mark.parametrize(
    ("start", "end", "expected"),
    [
        (date(2026, 7, 22), date(2026, 10, 22), True),
        (date(2026, 7, 21), date(2026, 10, 22), False),
        (date(2025, 12, 1), date(2026, 3, 1), True),
        (date(2026, 2, 28), date(2026, 5, 31), True),
        (date(2026, 2, 27), date(2026, 5, 31), False),
    ],
)
def test_within_three_months(start, end, expected):
    assert within_three_months(DateWindow(start, end)) is expected


def test_three_months_span_89_to_92_days():
    spans = set()
    day = date(2024, 1, 1)
    while day < date(2027, 1, 1):
        capped = cap_to_three_months(resolve_window(None, None, today=day, default_since="1y"))
        assert within_three_months(capped)
        assert not within_three_months(DateWindow(capped.start - timedelta(days=1), capped.end))
        spans.add(capped.days - 1)
        day += timedelta(days=1)
    assert spans == {89, 90, 91, 92}


def test_ninety_days_can_exceed_three_months():
    window = resolve_window(None, None, today=date(2025, 5, 1), default_since="90d")
    assert window.start == date(2025, 1, 31)
    assert not within_three_months(window)
    assert cap_to_three_months(window) == DateWindow(date(2025, 2, 1), date(2025, 5, 1))
    fitting = DateWindow(date(2025, 3, 1), date(2025, 5, 1))
    assert cap_to_three_months(fitting) is fitting


def test_yyyymmdd():
    assert yyyymmdd(date(2025, 1, 5)) == "20250105"
    assert yyyymmdd(date(5, 1, 5)) == "00050105"
