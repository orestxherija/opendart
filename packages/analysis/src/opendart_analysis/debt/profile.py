"""A company's debt securities from one periodic report: maturity ladders and issuance record.

``debt_profile`` fetches six periodic-report services concurrently for each candidate period:
five outstanding-balance tables (corporate bonds, short-term bonds, commercial paper, hybrid
securities, contingent capital securities) and the issuance record. The first candidate with
any of them is the profile's period.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from opendart_analysis.debt.issuance import ISSUANCE_SERVICE, company_names, issuance
from opendart_analysis.debt.ladders import LADDERS, build_ladder, derive
from opendart_analysis.extracts import fetch_records, gather_all, probe_attempts, sources, text
from opendart_analysis.reports import first_available

if TYPE_CHECKING:
    from collections.abc import Iterable
    from datetime import date

    from opendart_analysis.debt.issuance import Issue
    from opendart_analysis.debt.ladders import DebtFigures, Ladder, LadderSpec
    from opendart_analysis.extracts import FilingSource
    from opendart_analysis.reports import FiscalCompany, PeriodRef, PeriodicReport, ResolvedPeriod
    from opendart_analysis.upstream import FetchService

DEBT_SERVICES: Final = (*(spec.service for spec in LADDERS), ISSUANCE_SERVICE)
"""The six services a debt profile reads per period, balance tables first."""


@dataclass(frozen=True, slots=True)
class DebtTables:
    """The six debt tables of one periodic report.

    Attributes:
        balances (tuple[tuple[LadderSpec, list[object]], ...]): Balance rows per instrument,
            in ladder order; empty where the report has none.
        issues (list[object]): Issuance-record rows; empty when the report has none.
    """

    balances: tuple[tuple[LadderSpec, list[object]], ...]
    issues: list[object]

    def filing_numbers(self) -> list[str | None]:
        """List the filing number of every row.

        Returns:
            list[str | None]: Filing numbers in table order, balance tables first.
        """
        rows = [*(row for _, rows in self.balances for row in rows), *self.issues]
        return [text(row, "filing_number") for row in rows]


@dataclass(frozen=True, slots=True)
class DebtProfile:
    """Debt securities outstanding by maturity, and the issuance record, from one report.

    Attributes:
        ref (PeriodRef): Period read.
        ladder (tuple[Ladder, ...]): Instruments with a balance outstanding, in ``LADDERS``
            order.
        issues (tuple[Issue, ...]): Every issue in the record, redeemed ones included, by
            maturity.
        figures (DebtFigures): Total and the share due within a year, from the ladder.
        sources (tuple[FilingSource, ...]): Filings the rows came from.
    """

    ref: PeriodRef
    ladder: tuple[Ladder, ...]
    issues: tuple[Issue, ...]
    figures: DebtFigures
    sources: tuple[FilingSource, ...]


async def fetch_tables(
    company: FiscalCompany, ref: PeriodRef, *, fetch_service: FetchService, today: date
) -> DebtTables | None:
    """Fetch the six debt tables of one period concurrently.

    Args:
        company (FiscalCompany): Company.
        ref (PeriodRef): Fiscal year and period.
        fetch_service (FetchService): Service calls; failures propagate unchanged.
        today (date): Today in KST.

    Returns:
        DebtTables | None: The tables, or None when the source has none of them.
    """
    found = await gather_all(
        fetch_records(name, company=company, ref=ref, fetch_service=fetch_service, today=today)
        for name in DEBT_SERVICES
    )
    if all(rows is None for rows in found):
        return None
    tables = [rows or [] for rows in found]
    return DebtTables(tuple(zip(LADDERS, tables[:-1], strict=True)), tables[-1])


def assemble(
    ref: PeriodRef,
    tables: DebtTables,
    *,
    names: Iterable[str | None],
    report: PeriodicReport | None = None,
) -> DebtProfile:
    """Assemble a profile from one period's tables.

    Args:
        ref (PeriodRef): Period the tables belong to.
        tables (DebtTables): The period's tables.
        names (Iterable[str | None]): The company's names, to tell its own issues from those
            of other entities.
        report (PeriodicReport | None): Report found in the filing index, for source titles.

    Returns:
        DebtProfile: Ladder, issuance record, and derived figures.
    """
    ladder = tuple(
        entry for spec, rows in tables.balances if (entry := build_ladder(spec, rows)) is not None
    )
    return DebtProfile(
        ref=ref,
        ladder=ladder,
        issues=issuance(tables.issues, company_names(names)),
        figures=derive(ladder),
        sources=tuple(sources(tables.filing_numbers(), report)),
    )


async def debt_profile(
    company: FiscalCompany,
    resolved: ResolvedPeriod,
    *,
    names: Iterable[str | None],
    fetch_service: FetchService,
    today: date,
) -> DebtProfile | None:
    """Build a company's debt profile from the first candidate period with debt tables.

    Probes ``probe_attempts(resolved)`` candidates at most, six calls each.

    Args:
        company (FiscalCompany): Company.
        resolved (ResolvedPeriod): Candidate periods, from ``resolve_period``.
        names (Iterable[str | None]): The company's names, such as its Korean and English
            names, to tell its own issues from those of subsidiaries.
        fetch_service (FetchService): Service calls; failures propagate unchanged.
        today (date): Today in KST.

    Returns:
        DebtProfile | None: The profile, or None when no candidate has any debt table.
    """
    found = await first_available(
        resolved,
        lambda ref: fetch_tables(company, ref, fetch_service=fetch_service, today=today),
        attempts=probe_attempts(resolved),
    )
    if found is None:
        return None
    ref, tables = found
    return assemble(ref, tables, names=names, report=resolved.report)
