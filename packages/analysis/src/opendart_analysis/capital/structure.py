"""Read a company's capital structure from one periodic report.

The period is the first candidate whose share-count table has data, since every periodic
report files one; the requested sections are then read for that period: treasury stock
movements, share issuances and reductions, and the use of money raised by public offerings
and private placements.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal

from opendart_analysis.capital.changes import capital_changes, proceeds_uses
from opendart_analysis.capital.shares import latest_share_counts
from opendart_analysis.capital.treasury import treasury_methods, treasury_totals
from opendart_analysis.domain.identifiers import is_filing_number
from opendart_analysis.errors import NotConfiguredError
from opendart_analysis.extracts import FilingSource, gather_all
from opendart_analysis.reports import ReportQuery, period_volatility

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence
    from datetime import date

    from opendart_analysis.capital.changes import (
        CapitalChange,
        CapitalChangeRecord,
        FetchCapitalChanges,
        FetchPrivateProceeds,
        FetchPublicProceeds,
        PrivateProceedsRecord,
        ProceedsUse,
        PublicProceedsRecord,
    )
    from opendart_analysis.capital.shares import FetchShareCounts, ShareCounts
    from opendart_analysis.capital.treasury import (
        FetchTreasuryStock,
        TreasuryMovement,
        TreasuryRecord,
    )
    from opendart_analysis.reports import FiscalCompany, PeriodRef, ResolvedPeriod
    from opendart_analysis.upstream import Volatility

type Section = Literal["shares", "treasury_stock", "capital_changes", "use_of_proceeds"]
"""Parts of a capital structure: share counts are always read, since they settle the period."""

type Progress = Callable[[str], Awaitable[None]]
"""Receives progress messages."""

SECTIONS: Final[tuple[Section, ...]] = (
    "shares",
    "treasury_stock",
    "capital_changes",
    "use_of_proceeds",
)
"""Every section, in reading order."""


@dataclass(frozen=True, slots=True)
class CapitalStructure:
    """Share capital of one company from one periodic report.

    Section fields are None when the section was not requested, and empty when the report
    has nothing to report.

    Attributes:
        ref (PeriodRef): Period of the report.
        period_end (date | None): End of the period, or the share-count table's date.
        sections (tuple[Section, ...]): Requested sections, in ``SECTIONS`` order.
        shares (ShareCounts): Share counts by class; read for every request.
        treasury_stock (tuple[TreasuryMovement, ...] | None): Treasury shares by class.
        treasury_stock_by_method (tuple[TreasuryMovement, ...] | None): Treasury movements by
            acquisition method.
        capital_changes (tuple[CapitalChange, ...] | None): Issuances and reductions, newest
            first.
        use_of_proceeds (tuple[ProceedsUse, ...] | None): Planned versus actual use of money
            raised, public offerings first.
        sources (tuple[FilingSource, ...]): The periodic report, when its number is valid.
        notes (tuple[str, ...]): How the period was chosen.
    """

    ref: PeriodRef
    period_end: date | None
    sections: tuple[Section, ...]
    shares: ShareCounts
    treasury_stock: tuple[TreasuryMovement, ...] | None
    treasury_stock_by_method: tuple[TreasuryMovement, ...] | None
    capital_changes: tuple[CapitalChange, ...] | None
    use_of_proceeds: tuple[ProceedsUse, ...] | None
    sources: tuple[FilingSource, ...]
    notes: tuple[str, ...]


async def capital_structure(  # noqa: PLR0913 - one data-access callable per section
    company: FiscalCompany,
    resolved: ResolvedPeriod,
    *,
    sections: Sequence[Section] = SECTIONS,
    fetch_share_counts: FetchShareCounts,
    fetch_treasury_stock: FetchTreasuryStock | None = None,
    fetch_capital_changes: FetchCapitalChanges | None = None,
    fetch_public_proceeds: FetchPublicProceeds | None = None,
    fetch_private_proceeds: FetchPrivateProceeds | None = None,
    today: date,
    progress: Progress | None = None,
) -> CapitalStructure | None:
    """Read share capital sections from the newest candidate report with share counts.

    Probes at most three candidate periods for the share-count table, then reads each
    requested section of that period concurrently, one call per table (two for the use of
    proceeds). The first failure is raised unchanged after the other calls finish.

    Args:
        company (FiscalCompany): Company the period was resolved for.
        resolved (ResolvedPeriod): Candidate periods from ``resolve_period``.
        sections (Sequence[Section]): Sections to read; share counts are always read.
        fetch_share_counts (FetchShareCounts): Share-count rows of one period.
        fetch_treasury_stock (FetchTreasuryStock | None): Treasury-stock rows; needed for
            ``treasury_stock``.
        fetch_capital_changes (FetchCapitalChanges | None): Issuance and reduction rows;
            needed for ``capital_changes``.
        fetch_public_proceeds (FetchPublicProceeds | None): Public-offering proceeds rows;
            needed for ``use_of_proceeds``.
        fetch_private_proceeds (FetchPrivateProceeds | None): Private-placement proceeds
            rows; needed for ``use_of_proceeds``.
        today (date): Today in KST, which sets each period's volatility.
        progress (Progress | None): Receives a message when the period is settled.

    Returns:
        CapitalStructure | None: The sections, or None when no candidate report has a
            share-count table.

    Raises:
        NotConfiguredError: A requested section's data access is missing.
    """
    wanted = tuple(section for section in SECTIONS if section in sections)
    access = _Access(
        treasury=_needed(
            fetch_treasury_stock, "fetch_treasury_stock", wanted="treasury_stock" in wanted
        ),
        changes=_needed(
            fetch_capital_changes, "fetch_capital_changes", wanted="capital_changes" in wanted
        ),
        public=_needed(
            fetch_public_proceeds, "fetch_public_proceeds", wanted="use_of_proceeds" in wanted
        ),
        private=_needed(
            fetch_private_proceeds, "fetch_private_proceeds", wanted="use_of_proceeds" in wanted
        ),
    )
    counts = await latest_share_counts(
        company, resolved, fetch_share_counts=fetch_share_counts, today=today
    )
    if counts is None:
        return None
    ref = counts.ref
    if progress is not None:
        await progress(f"Reading the {ref.label} capital tables")
    rows = await access.read(
        ReportQuery.of(company.corp_code, ref),
        volatility=period_volatility(ref, fye_month=company.fye_month, today=today),
    )
    return CapitalStructure(
        ref=ref,
        period_end=ref.end_date or counts.as_of,
        sections=wanted,
        shares=counts,
        treasury_stock=_map(treasury_totals, rows.treasury),
        treasury_stock_by_method=_map(treasury_methods, rows.treasury),
        capital_changes=_map(capital_changes, rows.changes),
        use_of_proceeds=(
            tuple(proceeds_uses(rows.public, rows.private))
            if rows.public is not None and rows.private is not None
            else None
        ),
        sources=_sources(counts, resolved),
        notes=_notes(resolved, ref),
    )


@dataclass(slots=True)
class _Rows:
    """The rows of the requested sections; None for sections not requested."""

    treasury: Sequence[TreasuryRecord] | None = None
    changes: Sequence[CapitalChangeRecord] | None = None
    public: Sequence[PublicProceedsRecord] | None = None
    private: Sequence[PrivateProceedsRecord] | None = None


@dataclass(frozen=True, slots=True)
class _Access:
    """Data access for the requested sections; None for sections not requested."""

    treasury: FetchTreasuryStock | None
    changes: FetchCapitalChanges | None
    public: FetchPublicProceeds | None
    private: FetchPrivateProceeds | None

    async def read(self, query: ReportQuery, *, volatility: Volatility) -> _Rows:
        """Read the requested sections' rows concurrently, one call per table.

        Args:
            query (ReportQuery): Company and period.
            volatility (Volatility): The period's volatility.

        Returns:
            _Rows: Rows, empty when the source has none.
        """
        rows = _Rows()

        async def read_treasury() -> None:
            """Read the treasury-stock rows, when requested."""
            rows.treasury = await _rows(self.treasury, query, volatility)

        async def read_changes() -> None:
            """Read the issuance and reduction rows, when requested."""
            rows.changes = await _rows(self.changes, query, volatility)

        async def read_public() -> None:
            """Read the public-offering proceeds rows, when requested."""
            rows.public = await _rows(self.public, query, volatility)

        async def read_private() -> None:
            """Read the private-placement proceeds rows, when requested."""
            rows.private = await _rows(self.private, query, volatility)

        await gather_all([read_treasury(), read_changes(), read_public(), read_private()])
        return rows


def _needed[F](fetch: F | None, name: str, *, wanted: bool) -> F | None:
    """Check that a requested section's data access was supplied.

    Args:
        fetch (F | None): Data access callable, if supplied.
        name (str): Its parameter name.
        wanted (bool): Whether its section was requested.

    Returns:
        F | None: The callable when its section was requested, else None.

    Raises:
        NotConfiguredError: The section was requested without its data access.
    """
    if not wanted:
        return None
    if fetch is None:
        message = f"Reading this capital section needs {name}."
        raise NotConfiguredError(message, dependency=name)
    return fetch


async def _rows[R](
    fetch: Callable[..., Awaitable[Sequence[R] | None]] | None,
    query: ReportQuery,
    volatility: Volatility,
) -> Sequence[R] | None:
    """Fetch one section's rows when it was requested.

    Args:
        fetch (Callable[..., Awaitable[Sequence[R] | None]] | None): Data access, or None
            when the section was not requested.
        query (ReportQuery): Company and period.
        volatility (Volatility): The period's volatility.

    Returns:
        Sequence[R] | None: Rows, empty when the source has none; None when not requested.
    """
    if fetch is None:
        return None
    return await fetch(query, volatility=volatility) or ()


def _map[R, T](
    parse: Callable[[Sequence[R]], list[T]], rows: Sequence[R] | None
) -> tuple[T, ...] | None:
    """Parse a requested section's rows.

    Args:
        parse (Callable[[Sequence[R]], list[T]]): Section parser.
        rows (Sequence[R] | None): Rows, or None when the section was not requested.

    Returns:
        tuple[T, ...] | None: Parsed rows, or None when not requested.
    """
    return None if rows is None else tuple(parse(rows))


def _sources(counts: ShareCounts, resolved: ResolvedPeriod) -> tuple[FilingSource, ...]:
    """Cite the periodic report, titled when the filing index found it for this period.

    Args:
        counts (ShareCounts): Share counts, which carry the filing number.
        resolved (ResolvedPeriod): Period resolution, which may name the report.

    Returns:
        tuple[FilingSource, ...]: The report, when its number is well formed.
    """
    number = counts.filing_number
    if number is None or not is_filing_number(number):
        return ()
    report = resolved.report
    title = report.title if report is not None and report.ref == counts.ref else None
    return (FilingSource(number, title),)


def _notes(resolved: ResolvedPeriod, ref: PeriodRef) -> tuple[str, ...]:
    """Explain a fallback from the best candidate period.

    Args:
        resolved (ResolvedPeriod): Period resolution.
        ref (PeriodRef): Period used.

    Returns:
        tuple[str, ...]: Notes.
    """
    first = resolved.candidates[0]
    if ref == first:
        return ()
    return (f"The {first.label} report has no share-count table yet; showing {ref.label}.",)
