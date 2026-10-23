"""Share counts by class from periodic reports, and helpers for periodic-report rows.

Every periodic report has a share-count table (``stock_totqy_sttus``): per class, the
authorized shares, the shares issued and cancelled to date, the issued shares now, treasury
shares, and shares outstanding (issued minus treasury). Rows mix Korean class names such as
보통주 (common) and 우선주 (preferred) with English labels for the total and note rows
("Total", "Note"; Korean 합계, 비고), and tables with nothing to report come back as rows of
dashes. The helpers here normalize those quirks for get_ownership and get_capital_structure;
other tools can call ``shares_outstanding`` or ``latest_share_counts`` for dilution math.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Protocol, TypedDict

from opendart_mcp.core.ttl import DAY
from opendart_mcp.domain.normalize import clean_text, parse_amount, parse_date
from opendart_mcp.models.capital import ShareClassRow
from opendart_mcp.services.periods import first_available, periodic_ttl, resolve_period

if TYPE_CHECKING:
    import builtins
    from collections.abc import Awaitable, Callable, Iterable, Sequence
    from datetime import date

    from pydantic import BaseModel

    from opendart.models.periodic_reports import StockTotqySttusResponseListItem
    from opendart_mcp.core.state import AppState
    from opendart_mcp.domain.periods import PeriodRef
    from opendart_mcp.domain.types import Period, ReportCode
    from opendart_mcp.services.companies import Company

COMMON: Final = "common"
PREFERRED: Final = "preferred"
TOTAL: Final = "total"

_TOTAL_LABELS: Final = frozenset({"합계", "계", "총계", "소계", "total", "subtotal", "sum"})
_NOTE_LABELS: Final = frozenset({"비고", "note", "notes", "remark", "remarks"})
_CLASS_WORDS: Final = (
    (COMMON, ("보통", "common", "ordinary")),
    (PREFERRED, ("우선", "prefer")),
)
# Column order of the share-count table, with plain labels for its free-text note row.
_NOTE_COLUMNS: Final = (
    ("isu_stock_totqy", "authorized"),
    ("now_to_isu_stock_totqy", "issued to date"),
    ("now_to_dcrs_stock_totqy", "decreased to date"),
    ("redc", "capital reduction"),
    ("profit_incnr", "retired from profits"),
    ("rdmstk_repy", "redeemed"),
    ("etc", "other decrease"),
    ("istc_totqy", "issued"),
    ("tesstk_co", "treasury"),
    ("distb_stock_co", "outstanding"),
)


class PeriodArgs(TypedDict):
    """Keyword arguments every periodic-report SDK method takes."""

    corporation_code: str
    fiscal_year: str
    report_period: ReportCode


class Listing[T](Protocol):
    """An SDK response whose records are in ``list``."""

    @property
    def list(self) -> builtins.list[T] | None:
        """Access the response records.

        Returns:
            builtins.list[T] | None: Response records, or None when it has none.
        """
        ...


def period_args(company: Company, ref: PeriodRef) -> PeriodArgs:
    """Build the SDK arguments for one company's periodic report.

    Args:
        company (Company): Resolved company.
        ref (PeriodRef): Fiscal year and period.

    Returns:
        PeriodArgs: ``corporation_code``, ``fiscal_year``, and ``report_period``.
    """
    return {
        "corporation_code": company.corp_code,
        "fiscal_year": str(ref.fiscal_year),
        "report_period": ref.report_code,
    }


def items_of[T](response: Listing[T] | None) -> list[T]:
    """Return a response's records; a "no data" answer (None) has none.

    Args:
        response (Listing[T] | None): SDK response, or None for OpenDART status 013.

    Returns:
        list[T]: Records in upstream order.
    """
    return list(response.list or ()) if response is not None else []


async def report_rows[T](
    state: AppState,
    method: Callable[..., Awaitable[Listing[T]]],
    args: PeriodArgs,
    *,
    ttl: float = DAY,
) -> list[T]:
    """Fetch the records of one periodic-report service through the cache.

    Args:
        state (AppState): Server state.
        method (Callable[..., Awaitable[Listing[T]]]): Bound SDK method, such as
            ``gateway.sdk.periodic_reports.hyslr_sttus``.
        args (PeriodArgs): Company, fiscal year, and report code from ``period_args``.
        ttl (float): Seconds to cache the answer; pass ``periodic_ttl(state, company, ref)``
            so that a period whose filing deadline has not settled is rechecked sooner.

    Returns:
        list[T]: Records; empty when OpenDART has no data.
    """
    gateway = state.require_gateway()
    return items_of(await gateway.call(ttl, method, **args))


def _fold(text: str | None) -> str:
    """Remove whitespace and case from a label.

    Args:
        text (str | None): Raw label.

    Returns:
        str: Comparable label.
    """
    return "".join((text or "").split()).casefold()


def is_total(text: str | None) -> bool:
    """Check whether a row label marks a total or subtotal row (Total, 합계, 소계).

    Args:
        text (str | None): Row label, such as a share class or holder name.

    Returns:
        bool: True for total and subtotal labels.
    """
    return _fold(text) in _TOTAL_LABELS


def is_note(text: str | None) -> bool:
    """Check whether a row label marks a free-text note row (Note, 비고).

    Args:
        text (str | None): Row label.

    Returns:
        bool: True for note labels.
    """
    return _fold(text) in _NOTE_LABELS


def share_class(text: str | None) -> str | None:
    """Normalize a filed share-class name.

    Args:
        text (str | None): Class as filed, such as 보통주, 우선주, or 전환우선주.

    Returns:
        str | None: ``common``, ``preferred``, the cleaned filed name for other classes,
            or None when blank.
    """
    cleaned = clean_text(text)
    if cleaned is None:
        return None
    folded = cleaned.casefold()
    found = (name for name, words in _CLASS_WORDS if any(word in folded for word in words))
    return next(found, cleaned)


def sum_known(values: Iterable[int | None]) -> int | None:
    """Add the known values.

    Args:
        values (Iterable[int | None]): Values; None means unknown.

    Returns:
        int | None: The sum, or None when every value is unknown.
    """
    known = [value for value in values if value is not None]
    return sum(known) if known else None


def blank(model: BaseModel, *ignore: str) -> bool:
    """Check whether a parsed row has no values, as when upstream filed a row of dashes.

    Args:
        model (BaseModel): Parsed row.
        *ignore (str): Fields that do not count as values, such as a share class.

    Returns:
        bool: True when every other field is None.
    """
    return not model.model_dump(exclude_none=True, exclude=set(ignore))


def trim[M: BaseModel](model: M, fields: Iterable[str]) -> M:
    """Clear fields that only detailed responses carry.

    Args:
        model (M): Parsed row.
        fields (Iterable[str]): Field names to clear.

    Returns:
        M: Copy of the row with those fields set to None.
    """
    return model.model_copy(update=dict.fromkeys(fields))


@dataclass(frozen=True, slots=True)
class ShareCounts:
    """The share-count table of one periodic report.

    Attributes:
        ref (PeriodRef): Period of the report.
        filing_number (str | None): Filing number of the periodic report.
        as_of (date | None): Settlement date stated with the table.
        classes (tuple[ShareClassRow, ...]): One row per share class, in filed order.
        total (ShareClassRow | None): The all-classes row, when filed.
        note (str | None): Text of the table's note row, such as the reason for retirements.
    """

    ref: PeriodRef
    filing_number: str | None
    as_of: date | None
    classes: tuple[ShareClassRow, ...]
    total: ShareClassRow | None
    note: str | None

    @property
    def primary(self) -> ShareClassRow | None:
        """The common-share row, or the first class when none is common.

        Returns:
            ShareClassRow | None: Row of the voting class, or None without class rows.
        """
        first = self.classes[0] if self.classes else None
        return next((row for row in self.classes if row.share_class == COMMON), first)

    @property
    def issued(self) -> int | None:
        """Issued shares of all classes, treasury included.

        Returns:
            int | None: Share count, or None when not filed.
        """
        return self._all(lambda row: row.issued)

    @property
    def treasury(self) -> int | None:
        """Treasury shares of all classes.

        Returns:
            int | None: Share count, or None when not filed.
        """
        return self._all(lambda row: row.treasury)

    @property
    def outstanding(self) -> int | None:
        """Shares outstanding (issued minus treasury) of all classes.

        Returns:
            int | None: Share count, or None when not filed.
        """
        return self._all(lambda row: row.outstanding)

    def _all(self, pick: Callable[[ShareClassRow], int | None]) -> int | None:
        """Read one count from the total row, or add it up over the classes.

        Args:
            pick (Callable[[ShareClassRow], int | None]): Selects the count from a row.

        Returns:
            int | None: Count for all classes.
        """
        filed = pick(self.total) if self.total is not None else None
        return filed if filed is not None else sum_known(pick(row) for row in self.classes)


def _share_row(item: StockTotqySttusResponseListItem, name: str) -> ShareClassRow:
    """Parse one row of the share-count table.

    Args:
        item (StockTotqySttusResponseListItem): Upstream row.
        name (str): Normalized share class.

    Returns:
        ShareClassRow: Counts; dashes become None.
    """
    return ShareClassRow(
        share_class=name,
        authorized=parse_amount(item.isu_stock_totqy),
        issued=parse_amount(item.istc_totqy),
        treasury=parse_amount(item.tesstk_co),
        outstanding=parse_amount(item.distb_stock_co),
        issued_to_date=parse_amount(item.now_to_isu_stock_totqy),
        decreased_to_date=parse_amount(item.now_to_dcrs_stock_totqy),
        capital_reduction=parse_amount(item.redc),
        retired_from_profits=parse_amount(item.profit_incnr),
        redeemed=parse_amount(item.rdmstk_repy),
        other_decrease=parse_amount(item.etc),
    )


def _note_text(item: StockTotqySttusResponseListItem) -> str | None:
    """Join the filled cells of the note row with their column names.

    Args:
        item (StockTotqySttusResponseListItem): Upstream note row.

    Returns:
        str | None: Text such as "retired from profits: 자사주소각", or None when empty.
    """
    cells = item.model_dump()
    parts = [
        f"{label}: {text}"
        for column, label in _NOTE_COLUMNS
        if (text := clean_text(cells.get(column))) is not None
    ]
    return "; ".join(parts) or None


def parse_share_counts(
    items: Sequence[StockTotqySttusResponseListItem], ref: PeriodRef
) -> ShareCounts | None:
    """Normalize the share-count table of one periodic report.

    Args:
        items (Sequence[StockTotqySttusResponseListItem]): Upstream rows.
        ref (PeriodRef): Period the rows belong to.

    Returns:
        ShareCounts | None: Counts by class, or None when no row has a count.
    """
    rows = [item for item in items if not is_note(item.se)]
    parsed = [_share_row(item, TOTAL if is_total(item.se) else _class(item.se)) for item in rows]
    filled = [row for row in parsed if not blank(row, "share_class")]
    if not filled:
        return None
    note = next((_note_text(item) for item in items if is_note(item.se)), None)
    total = next((row for row in filled if row.share_class == TOTAL), None)
    classes = tuple(row for row in filled if row.share_class != TOTAL)
    first = items[0]
    return ShareCounts(
        ref, clean_text(first.filing_number), parse_date(first.stlm_dt), classes, total, note
    )


def _class(text: str | None) -> str:
    """Normalize a share class, treating a blank class as common shares.

    Args:
        text (str | None): Class as filed.

    Returns:
        str: Normalized class.
    """
    return share_class(text) or COMMON


async def fetch_share_counts(
    state: AppState, company: Company, ref: PeriodRef
) -> ShareCounts | None:
    """Fetch the share-count table of one periodic report (one upstream call).

    The answer is cached briefly until the period's filing deadline has settled, then for a
    day.

    Args:
        state (AppState): Server state.
        company (Company): Resolved company.
        ref (PeriodRef): Fiscal year and period.

    Returns:
        ShareCounts | None: Counts by class, or None when the report has none.
    """
    method = state.require_gateway().sdk.periodic_reports.stock_totqy_sttus
    ttl = periodic_ttl(state, company, ref)
    items = await report_rows(state, method, period_args(company, ref), ttl=ttl)
    return parse_share_counts(items, ref)


async def latest_share_counts(
    state: AppState, company: Company, *, period: Period = "latest", fiscal_year: int | None = None
) -> ShareCounts | None:
    """Find the share-count table of the newest periodic report that has one.

    Args:
        state (AppState): Server state.
        company (Company): Resolved company.
        period (Period): ``latest`` for any periodic report, or one period.
        fiscal_year (int | None): Fiscal year, or None for the latest.

    Returns:
        ShareCounts | None: Counts by class, or None when no candidate report has them.

    Raises:
        InvalidArgumentError: The requested period has not ended or predates 2015.
    """
    resolved = await resolve_period(state, company, period=period, fiscal_year=fiscal_year)
    found = await first_available(resolved, lambda ref: fetch_share_counts(state, company, ref))
    return found[1] if found is not None else None


async def shares_outstanding(
    state: AppState, company: Company, *, period: Period = "latest", fiscal_year: int | None = None
) -> int | None:
    """Count shares outstanding (issued minus treasury, all classes) from a periodic report.

    Args:
        state (AppState): Server state.
        company (Company): Resolved company.
        period (Period): ``latest`` for any periodic report, or one period.
        fiscal_year (int | None): Fiscal year, or None for the latest.

    Returns:
        int | None: Shares outstanding, or None when no report has a share-count table.

    Raises:
        InvalidArgumentError: The requested period has not ended or predates 2015.
    """
    counts = await latest_share_counts(state, company, period=period, fiscal_year=fiscal_year)
    return counts.outstanding if counts is not None else None
