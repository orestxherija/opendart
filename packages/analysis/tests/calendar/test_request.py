"""What a calendar covers: its window, kinds, lookback windows, and companies."""

from __future__ import annotations

import datetime as dt

import pytest

from opendart_analysis.calendar import (
    DEBT_KIND,
    LONG_KINDS,
    RECENT_KINDS,
    CalendarRequestError,
    CalendarSubject,
    CalendarWindowError,
    KindSelection,
    Reads,
    UndatedKindsError,
    UnknownKindsError,
    calendar_kinds,
    calendar_window,
)
from opendart_analysis.domain.dates import DateWindow
from opendart_analysis.errors import AnalysisError
from opendart_analysis.events import CALENDAR_KINDS

TODAY = dt.date(2026, 10, 22)


def test_the_window_runs_from_today_or_include_past_to_the_horizon():
    assert calendar_window(today=TODAY) == DateWindow(TODAY, dt.date(2027, 1, 20))
    assert calendar_window("2027-03-01", "30d", today=TODAY) == DateWindow(
        dt.date(2026, 9, 22), dt.date(2027, 3, 1)
    )
    assert calendar_window("today", today=TODAY) == DateWindow(TODAY, TODAY)


@pytest.mark.parametrize(
    ("horizon", "include_past", "argument", "message"),
    [
        ("soon", None, "horizon", "horizon: Invalid date 'soon'"),
        ("2026-01-01", None, "horizon", "horizon (2026-01-01) is before today (2026-10-22)"),
        ("90d", "lately", "include_past", "include_past: Invalid date 'lately'"),
        ("90d", "2027-01-01", "include_past", "include_past (2027-01-01) is after today"),
        ("soon", "lately", "include_past", "include_past: "),
    ],
)
def test_invalid_windows_name_the_argument(horizon, include_past, argument, message):
    with pytest.raises(CalendarWindowError) as caught:
        calendar_window(horizon, include_past, today=TODAY)
    assert caught.value.argument == argument
    assert str(caught.value).startswith(message)
    assert isinstance(caught.value, CalendarRequestError)
    assert isinstance(caught.value, AnalysisError)


def test_no_kinds_reads_every_dated_kind_and_debt():
    assert calendar_kinds(None) == KindSelection(None, debt=True)
    assert calendar_kinds([]) == KindSelection(None, debt=True)


def test_debt_alone_reads_no_event_reports():
    assert calendar_kinds([DEBT_KIND]) == KindSelection((), debt=True)


def test_kinds_without_dates_are_dropped_and_listed():
    selection = calendar_kinds(["merger", "lawsuit", DEBT_KIND])
    assert selection == KindSelection(("merger",), debt=True, dropped=("lawsuit",))


def test_groups_expand_to_their_dated_kinds():
    selection = calendar_kinds(["convertible_and_hybrid_debt"])
    assert set(selection.events or ()) == set(LONG_KINDS)
    assert not selection.debt


def test_unknown_names_list_the_valid_ones_and_debt():
    with pytest.raises(UnknownKindsError) as caught:
        calendar_kinds(["cb", DEBT_KIND])
    assert str(caught.value).startswith("Unknown event categories: cb.")
    assert str(caught.value).endswith(f"The calendar also accepts {DEBT_KIND}.")
    assert caught.value.names == ("cb", DEBT_KIND)


def test_only_undated_kinds_is_an_error():
    with pytest.raises(UndatedKindsError) as caught:
        calendar_kinds(["lawsuit"])
    assert caught.value.kinds == ("lawsuit",)
    assert str(caught.value) == "lawsuit reports carry no calendar dates."


def test_reads_look_back_a_year_and_three_years_for_bonds_not_before_2015():
    reads = Reads.before(TODAY, today=TODAY, kinds=None)
    assert reads.recent == DateWindow(dt.date(2025, 10, 22), TODAY)
    assert reads.extended == DateWindow(dt.date(2023, 10, 22), TODAY)
    early = Reads.before(dt.date(2016, 6, 1), today=TODAY, kinds=None)
    assert (early.recent.start, early.extended.start) == (dt.date(2015, 6, 1), dt.date(2015, 1, 1))


@pytest.mark.parametrize(
    ("kinds", "recent", "bonds"),
    [
        (None, True, True),
        ((), False, False),
        (("merger",), True, False),
        (("convertible_bond",), False, True),
        (("merger", "convertible_bond"), True, True),
    ],
)
def test_reads_say_which_windows_they_use(kinds, recent, bonds):
    reads = Reads.before(TODAY, today=TODAY, kinds=kinds)
    assert (reads.reads_recent, reads.reads_bonds) == (recent, bonds)


def test_long_and_recent_kinds_split_the_dated_kinds():
    assert LONG_KINDS | RECENT_KINDS == CALENDAR_KINDS
    assert not LONG_KINDS & RECENT_KINDS
    assert "convertible_bond" in LONG_KINDS


def test_a_subject_lists_its_names_korean_first():
    subject = CalendarSubject("00126380", "Samsung Electronics", korean_name="삼성전자")
    assert subject.names == ("삼성전자", "Samsung Electronics")
    assert subject.fye_month == 12
