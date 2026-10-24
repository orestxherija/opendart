"""What a corporate-action calendar covers: its date window, kinds, and companies.

The window runs from today, or an earlier ``include_past`` date, to a forward ``horizon``;
both take ISO dates or durations such as 90d. Kinds are event groups or kinds from the
catalog plus ``DEBT_KIND``; only kinds whose reports carry calendar dates are read, and the
others are reported as dropped. Requests that cannot be answered raise subclasses of
``CalendarRequestError``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from opendart_analysis.calendar.items import DEBT_ACTION
from opendart_analysis.catalog import expand
from opendart_analysis.domain.dates import DateWindow, parse_date_arg, parse_horizon
from opendart_analysis.errors import AnalysisError
from opendart_analysis.events.dates import CALENDAR_KINDS

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date

    from opendart_analysis.catalog import EventKind

DEBT_KIND: Final = DEBT_ACTION
"""Calendar-only kind that selects debt maturities from periodic reports."""
DEFAULT_HORIZON: Final = "90d"
"""Horizon of a calendar that names none."""
MAX_COMPANIES: Final = 20
"""Default bound on the distinct companies one calendar reads."""
MAX_CONCURRENCY: Final = 5
"""Default bound on the event-service and filing-index calls one calendar has in flight."""


class CalendarRequestError(AnalysisError):
    """A calendar request names an invalid window, unknown kinds, or too many companies."""


class CalendarWindowError(CalendarRequestError):
    """``horizon`` or ``include_past`` is not a valid date on the right side of today.

    Attributes:
        argument (str): ``horizon`` or ``include_past``.
        value (str): The text given.
    """

    def __init__(self, message: str, *, argument: str, value: str) -> None:
        """Describe the invalid argument.

        Args:
            message (str): Safe description of the problem.
            argument (str): ``horizon`` or ``include_past``.
            value (str): The text given.
        """
        super().__init__(message)
        self.argument = argument
        self.value = value


class UnknownKindsError(CalendarRequestError):
    """A requested name is neither an event group, an event kind, nor ``DEBT_KIND``.

    Attributes:
        names (tuple[str, ...]): The names requested.
    """

    def __init__(self, message: str, *, names: tuple[str, ...]) -> None:
        """Describe the unknown names.

        Args:
            message (str): Safe description listing the valid names.
            names (tuple[str, ...]): The names requested.
        """
        super().__init__(message)
        self.names = names


class UndatedKindsError(CalendarRequestError):
    """Every requested kind reports facts without calendar dates, and debt was not requested.

    Attributes:
        kinds (tuple[EventKind, ...]): The requested kinds, in catalog order.
    """

    def __init__(self, kinds: tuple[EventKind, ...]) -> None:
        """Describe the kinds without dates.

        Args:
            kinds (tuple[EventKind, ...]): The requested kinds.
        """
        super().__init__(f"{", ".join(kinds)} reports carry no calendar dates.")
        self.kinds = kinds


class TooManyCompaniesError(CalendarRequestError):
    """A calendar names more distinct companies than its bound allows.

    Attributes:
        count (int): Distinct companies requested.
        limit (int): The bound.
    """

    def __init__(self, *, count: int, limit: int) -> None:
        """Describe the excess.

        Args:
            count (int): Distinct companies requested.
            limit (int): The bound.
        """
        super().__init__(f"A calendar covers at most {limit} companies; {count} were given.")
        self.count = count
        self.limit = limit


@dataclass(frozen=True, slots=True)
class CalendarSubject:
    """A company a calendar covers.

    Attributes:
        corp_code (str): 8-digit DART corporation code.
        name (str): Name used in progress messages and to order items on the same date.
        korean_name (str | None): Korean name, which with ``name`` tells the company's own
            debt issues from those of subsidiaries.
        fye_month (int): Fiscal year-end month, 1 to 12, for periodic-report periods.
    """

    corp_code: str
    name: str
    korean_name: str | None = None
    fye_month: int = 12

    @property
    def names(self) -> tuple[str | None, str]:
        """The company's names, Korean first.

        Returns:
            tuple[str | None, str]: Korean and other names.
        """
        return self.korean_name, self.name


@dataclass(frozen=True, slots=True)
class KindSelection:
    """What a calendar reads.

    Attributes:
        events (tuple[EventKind, ...] | None): Event kinds; None lets each company's filing
            index choose among kinds with calendar dates; empty reads no event reports.
        debt (bool): Whether to read debt maturities.
        dropped (tuple[EventKind, ...]): Requested kinds left out for having no calendar
            dates, in catalog order.
    """

    events: tuple[EventKind, ...] | None
    debt: bool
    dropped: tuple[EventKind, ...] = ()


def calendar_kinds(names: Sequence[str] | None) -> KindSelection:
    """Choose the kinds to read, keeping those whose reports have calendar dates.

    Args:
        names (Sequence[str] | None): Event groups or kinds, and ``DEBT_KIND``; None or
            empty for every kind with calendar dates and debt maturities.

    Returns:
        KindSelection: Event kinds to read, whether to read debt maturities, and the kinds
            left out.

    Raises:
        UnknownKindsError: A name is unknown.
        UndatedKindsError: No requested kind has calendar dates and debt was not requested.
    """
    if not names:
        return KindSelection(None, debt=True)
    events = [name for name in names if name != DEBT_KIND]
    debt = len(events) < len(names)
    if not events:
        return KindSelection((), debt=debt)
    try:
        selected = expand(events)
    except ValueError as error:
        message = f"{error} The calendar also accepts {DEBT_KIND}."
        raise UnknownKindsError(message, names=tuple(names)) from error
    kept = tuple(kind for kind in selected if kind in CALENDAR_KINDS)
    dropped = tuple(kind for kind in selected if kind not in CALENDAR_KINDS)
    if not kept and not debt:
        raise UndatedKindsError(dropped)
    return KindSelection(kept, debt=debt, dropped=dropped)


def _horizon(text: str, today: date) -> date:
    """Parse the forward horizon.

    Args:
        text (str): ISO date or forward duration, such as 90d.
        today (date): Today in KST.

    Returns:
        date: Last calendar date.

    Raises:
        CalendarWindowError: The horizon is invalid or in the past.
    """
    try:
        end = parse_horizon(text, today=today)
    except ValueError as error:
        message = f"horizon: {error}."
        raise CalendarWindowError(message, argument="horizon", value=text) from error
    if end < today:
        message = f"horizon ({end}) is before today ({today}); pass a forward duration such as 90d, and include_past for earlier dates."
        raise CalendarWindowError(message, argument="horizon", value=text)
    return end


def _start(text: str | None, today: date) -> date:
    """Parse include_past.

    Args:
        text (str | None): ISO date or backward duration, such as 30d; None for today.
        today (date): Today in KST.

    Returns:
        date: First calendar date.

    Raises:
        CalendarWindowError: The value is invalid or after today.
    """
    if text is None:
        return today
    try:
        start = parse_date_arg(text, today=today)
    except ValueError as error:
        message = f"include_past: {error}."
        raise CalendarWindowError(message, argument="include_past", value=text) from error
    if start > today:
        message = f"include_past ({start}) is after today ({today}); pass a past date or a duration such as 30d."
        raise CalendarWindowError(message, argument="include_past", value=text)
    return start


def calendar_window(
    horizon: str = DEFAULT_HORIZON, include_past: str | None = None, *, today: date
) -> DateWindow:
    """Resolve the calendar's dates; ``include_past`` is checked first.

    Args:
        horizon (str): Last date, as an ISO date or a forward duration such as 90d or 1y.
        include_past (str | None): First date when earlier than today, as an ISO date or a
            backward duration such as 30d; None starts today.
        today (date): Today in KST.

    Returns:
        DateWindow: From the first date to the horizon.

    Raises:
        CalendarWindowError: An argument is invalid or on the wrong side of today.
    """
    start = _start(include_past, today)
    return DateWindow(start, _horizon(horizon, today))
