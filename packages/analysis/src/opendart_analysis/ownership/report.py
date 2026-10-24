"""Read who controls a company from one periodic report.

The period is the first candidate whose largest-shareholder table has named rows. The same
report's share counts and changes of the largest shareholder follow, and minority
shareholders come from it too, or from the prior annual report, since quarterly and
half-year reports usually omit them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from opendart_analysis.capital.shares import period_share_counts
from opendart_analysis.domain.identifiers import is_filing_number
from opendart_analysis.domain.normalize import clean_text, parse_date
from opendart_analysis.extracts import FilingSource, gather_all
from opendart_analysis.ownership.control import control_snapshot
from opendart_analysis.ownership.tables import control_changes, minority_holders
from opendart_analysis.reports import PeriodRef, ReportQuery, first_available, period_volatility

if TYPE_CHECKING:
    from collections.abc import Sequence
    from datetime import date

    from opendart_analysis.capital.shares import FetchShareCounts, ShareCounts
    from opendart_analysis.ownership.control import (
        ControlSnapshot,
        FetchLargestHolders,
        LargestHolderRecord,
    )
    from opendart_analysis.ownership.tables import (
        ControlChange,
        ControlChangeRecord,
        FetchControlChanges,
        FetchMinorityHolders,
        MinorityHolders,
    )
    from opendart_analysis.reports import FiscalCompany, ResolvedPeriod
    from opendart_analysis.upstream import Volatility

    type FoundMinority = tuple[MinorityHolders, PeriodRef, str | None]


@dataclass(frozen=True, slots=True)
class OwnershipReport:
    """Control of one company from one periodic report.

    Attributes:
        ref (PeriodRef): Period of the report.
        period_end (date | None): End of the period, or the table's settlement date.
        snapshot (ControlSnapshot): Control at the period end.
        control_changes (tuple[ControlChange, ...]): Changes of the largest shareholder,
            newest first.
        shares (ShareCounts | None): The report's share counts, when filed.
        minority_ref (PeriodRef | None): Period the minority figures come from, when found.
        sources (tuple[FilingSource, ...]): The periodic report, then the annual report the
            minority figures come from when it differs.
        notes (tuple[str, ...]): Period and minority-figure fallbacks.
    """

    ref: PeriodRef
    period_end: date | None
    snapshot: ControlSnapshot
    control_changes: tuple[ControlChange, ...]
    shares: ShareCounts | None
    minority_ref: PeriodRef | None
    sources: tuple[FilingSource, ...]
    notes: tuple[str, ...]


@dataclass(slots=True)
class _Tables:
    """The tables read for the chosen period."""

    counts: ShareCounts | None = None
    changes: Sequence[ControlChangeRecord] = ()
    minority: FoundMinority | None = None


@dataclass(frozen=True, slots=True)
class _Reader:
    """Reads one company's ownership tables."""

    company: FiscalCompany
    fetch_largest_holders: FetchLargestHolders
    fetch_share_counts: FetchShareCounts
    fetch_control_changes: FetchControlChanges
    fetch_minority_holders: FetchMinorityHolders
    today: date

    def query(self, ref: PeriodRef) -> tuple[ReportQuery, Volatility]:
        """Build one period's query and state how quickly its data can change.

        Args:
            ref (PeriodRef): Period.

        Returns:
            tuple[ReportQuery, Volatility]: Query and the period's volatility.
        """
        fye_month = self.company.fye_month
        volatility = period_volatility(ref, fye_month=fye_month, today=self.today)
        return ReportQuery.of(self.company.corp_code, ref), volatility

    async def holders(self, ref: PeriodRef) -> list[LargestHolderRecord] | None:
        """Read one period's named largest-shareholder rows.

        Args:
            ref (PeriodRef): Candidate period.

        Returns:
            list[LargestHolderRecord] | None: Named rows, or None when there are none.
        """
        query, volatility = self.query(ref)
        rows = await self.fetch_largest_holders(query, volatility=volatility)
        return [row for row in rows or () if clean_text(row.nm)] or None

    async def tables(self, ref: PeriodRef) -> _Tables:
        """Read the period's share counts, control changes, and minority figures concurrently.

        Args:
            ref (PeriodRef): Period of the snapshot.

        Returns:
            _Tables: The tables.
        """
        tables = _Tables()

        async def read_counts() -> None:
            """Read the period's share counts."""
            tables.counts = await period_share_counts(
                self.company, ref, fetch_share_counts=self.fetch_share_counts, today=self.today
            )

        async def read_changes() -> None:
            """Read the period's changes of the largest shareholder."""
            query, volatility = self.query(ref)
            tables.changes = await self.fetch_control_changes(query, volatility=volatility) or ()

        async def read_minority() -> None:
            """Read minority figures, falling back to the prior annual report."""
            tables.minority = await self.minority(ref)

        await gather_all([read_counts(), read_changes(), read_minority()])
        return tables

    async def minority(self, ref: PeriodRef) -> FoundMinority | None:
        """Read minority figures, falling back to the prior annual report.

        Quarterly and half-year reports usually omit the minority-shareholder table.

        Args:
            ref (PeriodRef): Period of the snapshot.

        Returns:
            FoundMinority | None: Figures, the period they come from, and its filing number;
                None when neither report has them.
        """
        fallback = PeriodRef(ref.fiscal_year - 1, "FY")
        for candidate in (ref,) if ref.period == "FY" else (ref, fallback):
            query, volatility = self.query(candidate)
            rows = await self.fetch_minority_holders(query, volatility=volatility)
            found = minority_holders(rows or ())
            if found is not None:
                return found[0], candidate, found[1]
        return None


async def ownership_report(  # noqa: PLR0913 - one data-access callable per table
    company: FiscalCompany,
    resolved: ResolvedPeriod,
    *,
    fetch_largest_holders: FetchLargestHolders,
    fetch_share_counts: FetchShareCounts,
    fetch_control_changes: FetchControlChanges,
    fetch_minority_holders: FetchMinorityHolders,
    today: date,
) -> OwnershipReport | None:
    """Read the control snapshot and changes of control from the newest report that has them.

    Probes at most three candidate periods for the largest-shareholder table, then reads the
    period's share counts, control changes, and minority shareholders concurrently: one call
    each, plus one for the prior annual report's minority figures when a quarterly or
    half-year report lacks them. The first failure is raised unchanged after the others
    finish.

    Args:
        company (FiscalCompany): Company the period was resolved for.
        resolved (ResolvedPeriod): Candidate periods from ``resolve_period``.
        fetch_largest_holders (FetchLargestHolders): Largest-shareholder rows of one period.
        fetch_share_counts (FetchShareCounts): Share-count rows of one period.
        fetch_control_changes (FetchControlChanges): Change-of-control rows of one period.
        fetch_minority_holders (FetchMinorityHolders): Minority-shareholder rows of one
            period.
        today (date): Today in KST, which sets each period's volatility.

    Returns:
        OwnershipReport | None: Control of the newest period with a largest-shareholder
            table, or None when no candidate report has one.
    """
    reader = _Reader(
        company,
        fetch_largest_holders,
        fetch_share_counts,
        fetch_control_changes,
        fetch_minority_holders,
        today,
    )
    found = await first_available(resolved, reader.holders)
    if found is None:
        return None
    ref, records = found
    tables = await reader.tables(ref)
    sources = _cite((), records[0].filing_number, _title(resolved, ref))
    notes: list[str] = []
    if ref != resolved.candidates[0]:
        notes.append(
            f"The {resolved.candidates[0].label} report has no ownership tables yet; showing {ref.label}."
        )
    minority, minority_ref = None, None
    if tables.minority is not None:
        minority, minority_ref, number = tables.minority
        if minority_ref != ref:
            notes.append(
                f"Minority shareholder figures come from the {minority_ref.label} annual report; quarterly and half-year reports usually omit them."
            )
            sources = _cite(sources, number, None)
    return OwnershipReport(
        ref=ref,
        period_end=ref.end_date or parse_date(records[0].stlm_dt),
        snapshot=control_snapshot(records, tables.counts, minority),
        control_changes=tuple(control_changes(tables.changes)),
        shares=tables.counts,
        minority_ref=minority_ref,
        sources=sources,
        notes=tuple(notes),
    )


def _title(resolved: ResolvedPeriod, ref: PeriodRef) -> str | None:
    """Return the periodic report's title when the filing index named it.

    Args:
        resolved (ResolvedPeriod): Period resolution.
        ref (PeriodRef): Period used.

    Returns:
        str | None: Report title, or None when unknown.
    """
    report = resolved.report
    return report.title if report is not None and report.ref == ref else None


def _cite(
    sources: tuple[FilingSource, ...], filing_number: str | None, title: str | None
) -> tuple[FilingSource, ...]:
    """Add a periodic report to the sources, once.

    Args:
        sources (tuple[FilingSource, ...]): Sources so far.
        filing_number (str | None): Filing number from the rows.
        title (str | None): Report title, when known.

    Returns:
        tuple[FilingSource, ...]: Sources with the report, when its number is well formed.
    """
    number = clean_text(filing_number)
    cited = {source.filing_number for source in sources}
    if number is None or not is_filing_number(number) or number in cited:
        return sources
    return (*sources, FilingSource(number, title))
