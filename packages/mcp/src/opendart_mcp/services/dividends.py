"""get_dividends: dividend history by share class from annual reports.

``opendart_analysis.dividends`` classifies the dividend table's rows, converts their units,
and chains earlier annual reports. This adapter resolves the company and the annual period,
binds the dividend table to the gateway through ``service_fetch``, and projects the history
into the output model: concise results drop par value and rows without values, and keep
labels only for rows the analysis does not recognize.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from opendart_analysis.dividends import dividend_history
from opendart_analysis.errors import AnalysisError
from opendart_analysis.extracts import checked
from opendart_mcp.core.errors import from_analysis
from opendart_mcp.core.progress import no_progress
from opendart_mcp.core.upstream import service_fetch
from opendart_mcp.models.common import SourceFiling
from opendart_mcp.models.dividends import DividendRow, DividendsResult
from opendart_mcp.services.periods import resolve_period

if TYPE_CHECKING:
    from opendart_analysis import dividends as analysis
    from opendart_mcp.core.progress import Progress
    from opendart_mcp.core.state import AppState
    from opendart_mcp.models.common import ResponseFormat


def _row(row: analysis.DividendRow, *, detailed: bool) -> DividendRow:
    """Project a dividend row into the output model.

    Args:
        row (analysis.DividendRow): Merged row.
        detailed (bool): Whether to keep the label as filed.

    Returns:
        DividendRow: Row with values by fiscal year, newest first.
    """
    return DividendRow(
        measure=row.measure,
        share_class=row.share_class,
        basis=row.basis,
        unit=row.unit,
        values_by_year={str(year): amount for year, amount in row.values.items()},
        label=row.label if detailed or row.measure == "other" else None,
    )


async def dividends(
    state: AppState,
    company: str,
    *,
    years: int = 3,
    response_format: ResponseFormat = "concise",
    progress: Progress = no_progress,
) -> DividendsResult:
    """Build a company's dividend history from its annual reports.

    Args:
        state (AppState): Server state.
        company (str): Name, stock code, or corp code.
        years (int): Fiscal years of history, newest first; three per upstream call.
        response_format (ResponseFormat): ``detailed`` adds par value, empty rows, and
            labels as filed.
        progress (Progress): Reports progress.

    Returns:
        DividendsResult: Rows by measure and share class, or an empty result with a note.
    """
    resolved_company = await state.companies.resolve(company, progress=progress)
    resolved = await resolve_period(state, resolved_company, period="FY", fiscal_year=None)
    await progress(f"Reading dividends for {resolved_company.ref.name}")
    try:
        history = await dividend_history(
            resolved_company,
            resolved,
            years=years,
            fetch_service=service_fetch(state.require_gateway),
            today=state.today(),
        )
    except AnalysisError as error:
        raise from_analysis(error) from error
    if history is None:
        note = f"OpenDART has no dividend table in {checked(resolved)}."
        return DividendsResult(company=resolved_company.ref, notes=[note], as_of=state.today())
    detailed = response_format == "detailed"
    return DividendsResult(
        company=resolved_company.ref,
        as_of=state.today(),
        source_filings=[SourceFiling.of(s.filing_number, s.title) for s in history.sources],
        notes=list(history.notes),
        fiscal_years=list(history.fiscal_years),
        rows=[
            _row(row, detailed=detailed)
            for row in history.rows
            if detailed or (row.values and row.measure != "par_value")
        ],
    )
