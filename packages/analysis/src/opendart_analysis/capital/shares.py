"""Share counts by class from the share-count table of a periodic report.

Every periodic report has a share-count table (``stock_totqy_sttus``): per class, the
authorized shares, the shares issued and cancelled to date, the issued shares now, treasury
shares, and shares outstanding (issued minus treasury). Rows mix Korean class names such as
보통주 (common) and 우선주 (preferred) with English labels for the total and note rows
("Total", "Note"; Korean 합계, 비고), and tables with nothing to report come back as rows of
dashes. The helpers here normalize those quirks for capital structure and ownership.
"""

from __future__ import annotations

from dataclasses import dataclass, fields
from typing import TYPE_CHECKING, Final, Protocol

from opendart_analysis.domain.normalize import clean_text, parse_amount, parse_date
from opendart_analysis.extracts import fold, is_total
from opendart_analysis.extracts.fields import sum_known
from opendart_analysis.reports import ReportQuery, first_available, period_volatility

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence
    from datetime import date

    from _typeshed import DataclassInstance

    from opendart_analysis.reports import FiscalCompany, PeriodRef, ResolvedPeriod
    from opendart_analysis.upstream import Volatility

COMMON: Final = "common"
"""Normalized name of common (ordinary) shares."""
PREFERRED: Final = "preferred"
"""Normalized name of preferred shares, convertible and redeemable ones included."""
TOTAL: Final = "total"
"""Share class of the all-classes row."""

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


class ShareCountRecord(Protocol):
    """The fields of one share-count row that analysis reads."""

    @property
    def se(self) -> str | None:
        """Share class as filed, or a total or note label."""
        ...

    @property
    def isu_stock_totqy(self) -> str | None:
        """Authorized shares."""
        ...

    @property
    def now_to_isu_stock_totqy(self) -> str | None:
        """Shares issued to date."""
        ...

    @property
    def now_to_dcrs_stock_totqy(self) -> str | None:
        """Shares cancelled to date."""
        ...

    @property
    def redc(self) -> str | None:
        """Shares cancelled by capital reduction."""
        ...

    @property
    def profit_incnr(self) -> str | None:
        """Shares retired from profits."""
        ...

    @property
    def rdmstk_repy(self) -> str | None:
        """Redeemable shares redeemed."""
        ...

    @property
    def etc(self) -> str | None:
        """Shares cancelled otherwise."""
        ...

    @property
    def istc_totqy(self) -> str | None:
        """Issued shares, treasury included."""
        ...

    @property
    def tesstk_co(self) -> str | None:
        """Treasury shares."""
        ...

    @property
    def distb_stock_co(self) -> str | None:
        """Shares outstanding."""
        ...

    @property
    def stlm_dt(self) -> str | None:
        """Settlement date stated with the table."""
        ...

    @property
    def filing_number(self) -> str | None:
        """14-digit filing number of the periodic report."""
        ...


class FetchShareCounts(Protocol):
    """Fetch one company's share-count table for one period; bound by the caller."""

    async def __call__(
        self, query: ReportQuery, /, *, volatility: Volatility
    ) -> Sequence[ShareCountRecord] | None:
        """Return the share-count rows of a company's periodic report.

        Args:
            query (ReportQuery): Company and period.
            volatility (Volatility): How quickly the answer can change, for the source's cache.

        Returns:
            Sequence[ShareCountRecord] | None: Rows, or None when the source has none.
        """
        ...


@dataclass(frozen=True, slots=True)
class ShareClassCounts:
    """Share counts of one class, or of all classes, at the period end.

    Attributes:
        share_class (str): ``common``, ``preferred``, ``total``, or the class as filed.
        authorized (int | None): Authorized shares.
        issued (int | None): Issued shares, treasury included.
        treasury (int | None): Treasury shares.
        outstanding (int | None): Issued minus treasury shares.
        issued_to_date (int | None): Every share ever issued.
        decreased_to_date (int | None): Every share ever cancelled.
        capital_reduction (int | None): Shares cancelled by capital reduction.
        retired_from_profits (int | None): Shares retired from profits.
        redeemed (int | None): Redeemable shares redeemed.
        other_decrease (int | None): Shares cancelled otherwise.
    """

    share_class: str
    authorized: int | None = None
    issued: int | None = None
    treasury: int | None = None
    outstanding: int | None = None
    issued_to_date: int | None = None
    decreased_to_date: int | None = None
    capital_reduction: int | None = None
    retired_from_profits: int | None = None
    redeemed: int | None = None
    other_decrease: int | None = None


@dataclass(frozen=True, slots=True)
class ShareCounts:
    """The share-count table of one periodic report.

    Attributes:
        ref (PeriodRef): Period of the report.
        filing_number (str | None): Filing number of the periodic report.
        as_of (date | None): Settlement date stated with the table.
        classes (tuple[ShareClassCounts, ...]): One row per share class, in filed order.
        total (ShareClassCounts | None): The all-classes row, when filed.
        note (str | None): Text of the table's note row, such as the reason for retirements.
    """

    ref: PeriodRef
    filing_number: str | None
    as_of: date | None
    classes: tuple[ShareClassCounts, ...]
    total: ShareClassCounts | None
    note: str | None

    @property
    def primary(self) -> ShareClassCounts | None:
        """The common-share row, or the first class when none is common.

        Returns:
            ShareClassCounts | None: Row of the voting class, or None without class rows.
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

    def _all(self, pick: Callable[[ShareClassCounts], int | None]) -> int | None:
        """Read one count from the total row, or add it up over the classes.

        Args:
            pick (Callable[[ShareClassCounts], int | None]): Selects the count from a row.

        Returns:
            int | None: Count for all classes.
        """
        filed = pick(self.total) if self.total is not None else None
        return filed if filed is not None else sum_known(pick(row) for row in self.classes)


def is_note(text: str | None) -> bool:
    """Check whether a row label marks a free-text note row (Note, 비고).

    Args:
        text (str | None): Row label.

    Returns:
        bool: True for note labels.
    """
    return fold(text) in _NOTE_LABELS


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


def is_blank(row: DataclassInstance, *ignore: str) -> bool:
    """Check whether a parsed row has no values, as when upstream filed a row of dashes.

    Args:
        row (DataclassInstance): Parsed row.
        *ignore (str): Fields that do not count as values, such as a share class.

    Returns:
        bool: True when every other field is None.
    """
    names = (field.name for field in fields(row))
    return all(getattr(row, name) is None for name in names if name not in ignore)


def _share_row(record: ShareCountRecord, name: str) -> ShareClassCounts:
    """Parse one row of the share-count table.

    Args:
        record (ShareCountRecord): Upstream row.
        name (str): Normalized share class.

    Returns:
        ShareClassCounts: Counts; dashes become None.
    """
    return ShareClassCounts(
        share_class=name,
        authorized=parse_amount(record.isu_stock_totqy),
        issued=parse_amount(record.istc_totqy),
        treasury=parse_amount(record.tesstk_co),
        outstanding=parse_amount(record.distb_stock_co),
        issued_to_date=parse_amount(record.now_to_isu_stock_totqy),
        decreased_to_date=parse_amount(record.now_to_dcrs_stock_totqy),
        capital_reduction=parse_amount(record.redc),
        retired_from_profits=parse_amount(record.profit_incnr),
        redeemed=parse_amount(record.rdmstk_repy),
        other_decrease=parse_amount(record.etc),
    )


def _note_text(record: ShareCountRecord) -> str | None:
    """Join the filled cells of the note row with their column names.

    Args:
        record (ShareCountRecord): Upstream note row.

    Returns:
        str | None: Text such as "retired from profits: 자사주소각", or None when empty.
    """
    parts = [
        f"{label}: {text}"
        for column, label in _NOTE_COLUMNS
        if (text := clean_text(getattr(record, column))) is not None
    ]
    return "; ".join(parts) or None


def parse_share_counts(records: Sequence[ShareCountRecord], ref: PeriodRef) -> ShareCounts | None:
    """Normalize the share-count table of one periodic report.

    A blank share class counts as common shares.

    Args:
        records (Sequence[ShareCountRecord]): Upstream rows, in filed order.
        ref (PeriodRef): Period the rows belong to.

    Returns:
        ShareCounts | None: Counts by class, or None when no row has a count.
    """
    rows = [record for record in records if not is_note(record.se)]
    parsed = [_share_row(row, TOTAL if is_total(row.se) else _class(row.se)) for row in rows]
    filled = [row for row in parsed if not is_blank(row, "share_class")]
    if not filled:
        return None
    note = next((_note_text(record) for record in records if is_note(record.se)), None)
    total = next((row for row in filled if row.share_class == TOTAL), None)
    classes = tuple(row for row in filled if row.share_class != TOTAL)
    first = records[0]
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


async def period_share_counts(
    company: FiscalCompany, ref: PeriodRef, *, fetch_share_counts: FetchShareCounts, today: date
) -> ShareCounts | None:
    """Fetch and normalize the share-count table of one periodic report, in one call.

    Args:
        company (FiscalCompany): Company.
        ref (PeriodRef): Period.
        fetch_share_counts (FetchShareCounts): Share-count rows; asked with
            ``period_volatility``.
        today (date): Today in KST, which sets the period's volatility.

    Returns:
        ShareCounts | None: Counts by class, or None when the report has none.
    """
    volatility = period_volatility(ref, fye_month=company.fye_month, today=today)
    rows = await fetch_share_counts(ReportQuery.of(company.corp_code, ref), volatility=volatility)
    return parse_share_counts(rows or (), ref)


async def latest_share_counts(
    company: FiscalCompany,
    resolved: ResolvedPeriod,
    *,
    fetch_share_counts: FetchShareCounts,
    today: date,
) -> ShareCounts | None:
    """Find the share-count table of the newest candidate period that has one.

    Probes at most three candidate periods, one call each. ``outstanding`` gives the shares
    outstanding of all classes, for per-share and dilution calculations.

    Args:
        company (FiscalCompany): Company the period was resolved for.
        resolved (ResolvedPeriod): Candidate periods from ``resolve_period``.
        fetch_share_counts (FetchShareCounts): Share-count rows of one period.
        today (date): Today in KST, which sets each period's volatility.

    Returns:
        ShareCounts | None: Counts of the newest period with a table, or None.
    """
    found = await first_available(
        resolved,
        lambda ref: period_share_counts(
            company, ref, fetch_share_counts=fetch_share_counts, today=today
        ),
    )
    return None if found is None else found[1]
