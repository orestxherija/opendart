"""get_governance: audit, board, executives, pay, and employees from periodic reports."""

from __future__ import annotations

from typing import Annotated

from fastmcp import Context
from fastmcp.dependencies import CurrentContext, Depends
from fastmcp.tools import tool
from pydantic import Field

from opendart_mcp.app.annotations import READ_ONLY
from opendart_mcp.app.params import CompanyArg, FiscalYearArg, PeriodArg, ResponseFormatArg
from opendart_mcp.app.progress import Reporter
from opendart_mcp.app.state import get_state
from opendart_mcp.app.views import markdown_view
from opendart_mcp.core.state import AppState
from opendart_mcp.models.governance import GovernanceResult, GovernanceSection
from opendart_mcp.render.governance import render_governance
from opendart_mcp.services.governance import DEFAULT_SECTIONS, GovernanceQuery, governance


@tool(
    name="get_governance",
    version="1.0.0",
    title="Audit and governance",
    tags={"governance"},
    annotations=READ_ONLY,
)
@markdown_view(render_governance)
async def get_governance(
    *,
    company: CompanyArg,
    sections: Annotated[
        tuple[GovernanceSection, ...],
        Field(min_length=1, max_length=5, description="Sections to include; each costs calls."),
    ] = DEFAULT_SECTIONS,
    fiscal_year: FiscalYearArg = None,
    period: PeriodArg = "FY",
    response_format: ResponseFormatArg = "concise",
    state: AppState = Depends(get_state),
    ctx: Context = CurrentContext(),
) -> GovernanceResult:
    """Get audit and governance facts that change a risk assessment, from a periodic report.

    Sections: audit (auditor, opinion, emphasis of matter, key audit matters, audit and
    non-audit fees), board (size, outside directors, changes), executives (registered
    officers, roles, terms), compensation (approved ceiling, pay by director type, people
    paid KRW 500 million or more, unregistered executives), and employees (headcount,
    tenure, salaries). Only requested sections are fetched; the default is audit and board.
    Flags mark a modified opinion, going-concern language, and an auditor change from the
    prior year. Names, titles, and audit-report text are Korean as filed. Shareholders and
    insider trades are in get_ownership.

    Args:
        company (CompanyArg): Company to analyze.
        sections (tuple[GovernanceSection, ...]): Sections to include.
        fiscal_year (FiscalYearArg): Fiscal year of the period.
        period (PeriodArg): Reporting period; annual reports carry the full audit opinion.
        response_format (ResponseFormatArg): Level of detail.
        state (AppState): Server state, injected.
        ctx (Context): Request context, injected.

    Returns:
        GovernanceResult: Governance and audit facts from the requested periodic report.

    Raises:
        ServerError: A configuration, argument, directory, upstream, or
            deadline failure prevents completion.
    """
    query = GovernanceQuery(
        sections=sections,
        fiscal_year=fiscal_year,
        period=period,
        response_format=response_format,
    )
    return await governance(state, company, query, progress=Reporter(ctx))


TOOLS = (get_governance,)
