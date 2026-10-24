"""The query value shared by every workflow that reads one company's periodic-report data."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from opendart_analysis.domain.periods import PeriodRef
    from opendart_analysis.domain.types import ReportCode


@dataclass(frozen=True, slots=True)
class ReportQuery:
    """One company's periodic-report data for one period.

    Attributes:
        corp_code (str): 8-digit DART corporation code.
        fiscal_year (int): Fiscal-year label (``bsns_year``).
        report_code (ReportCode): Report code (``reprt_code``) of the period.
    """

    corp_code: str
    fiscal_year: int
    report_code: ReportCode

    @classmethod
    def of(cls, corp_code: str, ref: PeriodRef) -> ReportQuery:
        """Build the query for a company and period.

        Args:
            corp_code (str): 8-digit DART corporation code.
            ref (PeriodRef): Period.

        Returns:
            ReportQuery: The query.
        """
        return cls(corp_code, ref.fiscal_year, ref.report_code)
