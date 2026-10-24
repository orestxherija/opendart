"""Shared plumbing for get_financials views: the table a view returns and its provenance.

``opendart_analysis.financials`` finds the newest period with data and chains earlier
reports; a view lays the result out as a ``Table``, cites its filings, and explains an empty
result.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from opendart_analysis.domain.identifiers import is_filing_number
from opendart_mcp.models.common import SourceFiling

if TYPE_CHECKING:
    from collections.abc import Iterable

    from opendart_mcp.models.financials import (
        EquityInvestment,
        PeriodColumn,
        StatementBasis,
        StatementRow,
    )
    from opendart_mcp.services.periods import PeriodicReport, ResolvedPeriod


@dataclass(slots=True)
class Table:
    """What a view returns: the table and its provenance.

    Attributes:
        periods (list[PeriodColumn]): Columns, latest first.
        rows (list[StatementRow]): Rows aligned with the columns.
        notes (list[str]): Fallbacks, coverage gaps, and formulas.
        filings (list[SourceFiling]): Filings the table comes from.
        basis (StatementBasis | None): Statements used, where a basis applies.
        currency (str): Currency of the amounts.
        derived (dict[str, float]): Metrics computed in code.
        investments (list[EquityInvestment] | None): Holdings (equity_investments view).
    """

    periods: list[PeriodColumn] = field(default_factory=list)
    rows: list[StatementRow] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    filings: list[SourceFiling] = field(default_factory=list)
    basis: StatementBasis | None = None
    currency: str = "KRW"
    derived: dict[str, float] = field(default_factory=dict)
    investments: list[EquityInvestment] | None = None


def sources(filings: Iterable[str], report: PeriodicReport | None) -> list[SourceFiling]:
    """Cite filings, titling the one that defined the requested period.

    Malformed filing numbers are skipped rather than failing the whole result.

    Args:
        filings (Iterable[str]): Filing numbers.
        report (PeriodicReport | None): Periodic report found in the filing index.

    Returns:
        list[SourceFiling]: Provenance entries.
    """
    titles = {report.filing_number: report.title} if report is not None else {}
    numbers = (number.strip() for number in filings)
    return [
        SourceFiling.of(number, titles.get(number))
        for number in dict.fromkeys(numbers)
        if is_filing_number(number)
    ]


def no_data(resolved: ResolvedPeriod, what: str) -> str:
    """Explain an empty result.

    Args:
        resolved (ResolvedPeriod): Candidate periods that were probed.
        what (str): What was looked for, such as "financial statements".

    Returns:
        str: Note naming the periods tried.
    """
    tried = ", ".join(ref.label for ref in resolved.candidates[:3]) or "the requested period"
    return f"OpenDART has no {what} for {tried}: the report may not be filed yet, or the company is not covered (financial companies and small filers often lack XBRL data)."
