"""Calendar items from event records and debt maturities, with repeated dates merged.

A registration statement repeats dates of the decision it registers: a merger's record and
effective dates, an offering's subscription, payment, and maturity dates. When a statement's
item has the same action and date as an item of its decision, only the decision's item is
kept, because it carries the deal's terms and the deal's other dates, and it cites the
statement in ``details["registration_filing"]``. A statement names its decision in
``rpt_rcpn``; OpenDART gives an amended decision its latest filing number, so a statement
whose ``rpt_rcpn`` matches no decision read is paired with the decisions of the kinds it
registers on that date. A statement without ``rpt_rcpn``, such as a straight bond's, is
never paired, so another deal's date is never dropped. A debt offering's rights-exercise
window matches a convertible's conversion window or an exchangeable's exchange window.

Debt maturities from periodic reports repeat the maturity dates of bond filings read as
events. A debt maturity with the same date and face value as an event's maturity replaces
it, because the periodic report is the later filing and states whether the issue was partly
redeemed, and cites the event filing in ``details["offering_filing"]``.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from types import MappingProxyType
from typing import TYPE_CHECKING, Final

from opendart_analysis.catalog import kinds_in
from opendart_analysis.domain.identifiers import is_filing_number
from opendart_analysis.events.catalog import describe
from opendart_analysis.events.dates import ACTIONS

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence
    from datetime import date

    from opendart_analysis.domain.dates import DateWindow
    from opendart_analysis.events.catalog import EventView
    from opendart_analysis.events.records import EventRecord

type Detail = str | int | float | None
"""A value in an item's details: text, an amount in won, a count, or a percentage."""

DEBT_ACTION: Final = "debt_maturity"
"""Action of a debt maturity from periodic reports; also the calendar kind that selects them."""
DEBT_SOURCE_KIND: Final = "debt_securities"
"""Source kind of a debt maturity from periodic reports."""
DETAIL_TERMS: Final = 3
"""Key terms of the source event copied into each item's details."""
REGISTERED: Final[Mapping[str, frozenset[str]]] = MappingProxyType(
    {
        "equity_offering_registration": frozenset(
            {"rights_or_third_party_issue", "combined_paid_and_bonus_issue"}
        ),
        "depositary_receipt_registration": frozenset({"rights_or_third_party_issue"}),
        "debt_offering_registration": frozenset(
            kind
            for kind in kinds_in("convertible_and_hybrid_debt")
            if kind != "debt_offering_registration"
        ),
        "merger_registration": frozenset({"merger"}),
        "share_swap_registration": frozenset({"share_swap_or_transfer"}),
        "split_registration": frozenset({"split_off", "split_merger"}),
    }
)
"""Decision kinds that each registration statement kind registers."""
ACTION_ORDER: Final[Mapping[str, int]] = MappingProxyType(
    {code: index for index, code in enumerate(ACTIONS)}
)
"""Rank of each event action on the same date; other actions, such as DEBT_ACTION, follow."""
_WINDOWS: Final[Mapping[str, str]] = MappingProxyType(
    {
        "conversion_start": "exercise_start",
        "conversion_end": "exercise_end",
        "exchange_start": "exercise_start",
        "exchange_end": "exercise_end",
    }
)
"""Actions compared as the rights-exercise window that a debt offering statement files."""
type _Bond = tuple[date, Detail]


@dataclass(frozen=True, slots=True)
class CalendarItem:
    """One dated corporate action.

    Attributes:
        date (date): Date of the action.
        corp_code (str): DART corporation code of the company.
        action (str): Action code, such as record_date, conversion_start, or DEBT_ACTION.
        source_kind (str): Event kind the date comes from, or DEBT_SOURCE_KIND.
        filing_number (str): Filing the date comes from.
        details (Mapping[str, Detail]): The source's label (``event``), its first key terms,
            and related filings (``registration_filing``, ``offering_filing``), in order.
    """

    date: date
    corp_code: str
    action: str
    source_kind: str
    filing_number: str
    details: Mapping[str, Detail] = field(default_factory=dict)


def sort_key(item: CalendarItem, name: str) -> tuple[date, str, int, str]:
    """Order items by date, company name, action, and filing.

    Args:
        item (CalendarItem): Calendar item.
        name (str): Name of the item's company.

    Returns:
        tuple[date, str, int, str]: Sort key.
    """
    order = ACTION_ORDER.get(item.action, len(ACTION_ORDER))
    return item.date, name, order, item.filing_number


def _details(view: EventView) -> dict[str, Detail]:
    """Summarize the source event for an item.

    Args:
        view (EventView): Described event.

    Returns:
        dict[str, Detail]: The event label and its first key terms that are not flags.
    """
    terms = list(view.key_terms.items())[:DETAIL_TERMS]
    kept = {key: value for key, value in terms if not isinstance(value, bool)}
    return {"event": view.label, **kept}


def _items(corp_code: str, view: EventView, span: DateWindow) -> list[CalendarItem]:
    """Turn an event's calendar dates within the span into items.

    Args:
        corp_code (str): Company of the event.
        view (EventView): Described event.
        span (DateWindow): Dates to keep.

    Returns:
        list[CalendarItem]: Items in date order.
    """
    details = _details(view)
    return [
        CalendarItem(day, corp_code, action, view.kind, view.filing_number, details)
        for action, day in view.dates
        if ACTIONS[action].calendar and span.start <= day <= span.end
    ]


def _link(record: EventRecord) -> str | None:
    """Read the decision filing that a registration statement names.

    Args:
        record (EventRecord): Event rows.

    Returns:
        str | None: The decision's filing number from ``rpt_rcpn``, or None for other
            reports and for statements that name none.
    """
    number = record.raw("rpt_rcpn") if record.kind in REGISTERED else None
    return number if number is not None and is_filing_number(number) else None


def _key(item: CalendarItem) -> tuple[str, date]:
    """Key an item by its date and action, conversion and exchange windows as exercise.

    Args:
        item (CalendarItem): Calendar item.

    Returns:
        tuple[str, date]: Comparable action and date.
    """
    return _WINDOWS.get(item.action, item.action), item.date


def _cite(item: CalendarItem, key: str, number: str | None) -> CalendarItem:
    """Add a related filing to an item's details.

    Args:
        item (CalendarItem): Calendar item.
        key (str): Detail key, such as registration_filing.
        number (str | None): Filing number; None leaves the item as it is.

    Returns:
        CalendarItem: The item, with the filing cited.
    """
    if number is None:
        return item
    return replace(item, details={**item.details, key: number})


def _repeated(
    items: Sequence[CalendarItem], candidates: Sequence[int], *, kind: str, link: str
) -> list[int]:
    """Find the decision items that a registration statement's item repeats.

    Args:
        items (Sequence[CalendarItem]): Every event item.
        candidates (Sequence[int]): Indexes of decision items with the same key.
        kind (str): Registration statement kind.
        link (str): Decision filing number that the statement names.

    Returns:
        list[int]: The decision named by filing number, else every candidate of a kind
            the statement registers.
    """
    exact = [index for index in candidates if items[index].filing_number == link]
    return exact or [index for index in candidates if items[index].source_kind in REGISTERED[kind]]


def _merge_registrations(
    items: Sequence[CalendarItem], links: Mapping[str, str]
) -> list[CalendarItem]:
    """Drop statement items that repeat their decision's, citing the statement there.

    Args:
        items (Sequence[CalendarItem]): Event items.
        links (Mapping[str, str]): Statement filing number to the decision it names.

    Returns:
        list[CalendarItem]: Items without the repeats; a decision item repeated by exactly
            one candidate statement item cites it.
    """
    decisions: dict[tuple[str, date], list[int]] = {}
    for index, item in enumerate(items):
        if item.source_kind not in REGISTERED:
            decisions.setdefault(_key(item), []).append(index)
    dropped: set[int] = set()
    cited: dict[int, str] = {}
    for index, item in enumerate(items):
        link = links.get(item.filing_number)
        if link is None or item.source_kind not in REGISTERED:
            continue
        found = _repeated(items, decisions.get(_key(item), []), kind=item.source_kind, link=link)
        if found:
            dropped.add(index)
        if len(found) == 1:
            cited.setdefault(found[0], item.filing_number)
    return [
        _cite(item, "registration_filing", cited.get(index))
        for index, item in enumerate(items)
        if index not in dropped
    ]


def event_items(
    corp_code: str, records: Sequence[EventRecord], span: DateWindow
) -> list[CalendarItem]:
    """Turn a company's event records into calendar items within a span.

    Only actions that ``ACTIONS`` marks as calendar dates become items; facts such as a
    lawsuit's filing date do not.

    Args:
        corp_code (str): Company of the records.
        records (Sequence[EventRecord]): Event records.
        span (DateWindow): Dates to keep.

    Returns:
        list[CalendarItem]: Items in record order, without registration statements'
            repeats of their decisions' dates.
    """
    items = [item for record in records for item in _items(corp_code, describe(record), span)]
    links = {record.filing_number: link for record in records if (link := _link(record))}
    return _merge_registrations(items, links)


def _bond(item: CalendarItem) -> _Bond:
    """Identify a bond by maturity date and face value.

    Args:
        item (CalendarItem): Maturity item.

    Returns:
        tuple[date, Detail]: Date and face value; None when the value is unknown.
    """
    return item.date, item.details.get("face_value")


def merge_maturities(
    items: Sequence[CalendarItem], debt: Iterable[CalendarItem]
) -> list[CalendarItem]:
    """Add debt maturities, each replacing event maturities of the same bond.

    Args:
        items (Sequence[CalendarItem]): Event items.
        debt (Iterable[CalendarItem]): Debt maturity items from periodic reports.

    Returns:
        list[CalendarItem]: Event items without the replaced maturities, then the debt
            items, each citing the event filing it replaced.
    """
    maturities = list(debt)
    bonds = {_bond(item) for item in maturities if item.details.get("face_value") is not None}
    replaced: dict[_Bond, str] = {}
    kept: list[CalendarItem] = []
    for item in items:
        if item.action == "maturity" and _bond(item) in bonds:
            replaced.setdefault(_bond(item), item.filing_number)
        else:
            kept.append(item)
    cited = (_cite(item, "offering_filing", replaced.get(_bond(item))) for item in maturities)
    return [*kept, *cited]
