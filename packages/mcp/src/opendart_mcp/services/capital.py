"""get_capital_structure: share counts, treasury stock, capital changes, and use of proceeds.

``opendart_analysis.capital`` reads every section from one periodic report: the period is the
first candidate whose share-count table (``stock_totqy_sttus``) has data, since every periodic
report files one; the requested sections are then read for that period: treasury stock
movements (``tesstk_acqs_dsps_sttus``), share issuances and reductions (``irds_sttus``), and
planned versus actual use of money raised by public offerings (``pssrp_cptal_use_dtls``) and
private placements (``prvsrp_cptal_use_dtls``). This adapter binds the tables to the gateway
and shows the sections as the output model; concise results drop detail fields.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Final

from opendart_analysis.capital import capital_structure as read_capital_structure
from opendart_analysis.reports import PROBE_ATTEMPTS
from opendart_mcp.core.progress import no_progress
from opendart_mcp.core.upstream_ownership import (
    capital_changes_fetch,
    private_proceeds_fetch,
    public_proceeds_fetch,
    share_counts_fetch,
    treasury_stock_fetch,
)
from opendart_mcp.models.capital import (
    CapitalChange,
    CapitalStructureResult,
    ProceedsUse,
    ShareClassRow,
    TreasuryMovement,
)
from opendart_mcp.models.common import SourceFiling
from opendart_mcp.services.periods import resolve_period

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from _typeshed import DataclassInstance
    from pydantic import BaseModel

    from opendart_analysis import capital
    from opendart_analysis.domain.types import Period
    from opendart_analysis.reports import ResolvedPeriod
    from opendart_mcp.core.progress import Progress
    from opendart_mcp.core.state import AppState
    from opendart_mcp.models.capital import CapitalSection
    from opendart_mcp.services.companies import Company

SECTIONS: Final[tuple[CapitalSection, ...]] = (
    "shares",
    "treasury_stock",
    "capital_changes",
    "use_of_proceeds",
)
"""Every section, in output order."""

_SHARE_DETAIL: Final = (
    "issued_to_date",
    "decreased_to_date",
    "capital_reduction",
    "retired_from_profits",
    "redeemed",
    "other_decrease",
)


@dataclass(frozen=True, slots=True)
class CapitalQuery:
    """Arguments of get_capital_structure.

    Attributes:
        company (str): Name, stock code, or corp code.
        sections (tuple[CapitalSection, ...]): Sections to return.
        period (Period): Periodic report to read.
        fiscal_year (int | None): Fiscal year, or None for the latest.
        detailed (bool): Whether to return every labeled field.
    """

    company: str
    sections: tuple[CapitalSection, ...] = SECTIONS
    period: Period = "latest"
    fiscal_year: int | None = None
    detailed: bool = False


async def capital_structure(
    state: AppState, query: CapitalQuery, *, progress: Progress = no_progress
) -> CapitalStructureResult:
    """Read share capital sections from one periodic report.

    Args:
        state (AppState): Server state.
        query (CapitalQuery): Tool arguments.
        progress (Progress): Reports progress while the directory loads and data arrives.

    Returns:
        CapitalStructureResult: Requested sections; empty with a note when no report has data.

    Raises:
        InvalidArgumentError: The requested period has not ended or predates 2015.
    """
    company = await state.companies.resolve(query.company, progress=progress)
    wanted = [section for section in SECTIONS if section in query.sections]
    resolved = await resolve_period(
        state, company, period=query.period, fiscal_year=query.fiscal_year
    )

    async def report(message: str) -> None:
        """Name the company in a progress message.

        Args:
            message (str): Message from the workflow.
        """
        await progress(f"{message} of {company.ref.name}")

    found = await read_capital_structure(
        company,
        resolved,
        sections=wanted,
        fetch_share_counts=share_counts_fetch(state.require_gateway),
        fetch_treasury_stock=treasury_stock_fetch(state.require_gateway),
        fetch_capital_changes=capital_changes_fetch(state.require_gateway),
        fetch_public_proceeds=public_proceeds_fetch(state.require_gateway),
        fetch_private_proceeds=private_proceeds_fetch(state.require_gateway),
        today=state.today(),
        progress=report,
    )
    if found is None:
        return _empty(state, company, resolved, wanted=wanted)
    detailed = query.detailed
    ref = found.ref
    return CapitalStructureResult(
        company=company.ref,
        as_of=state.today(),
        source_filings=[SourceFiling.of(s.filing_number, s.title) for s in found.sources],
        notes=[*([resolved.note] if resolved.note else []), *found.notes],
        fiscal_year=ref.fiscal_year,
        period=ref.period,
        period_end=found.period_end,
        sections=wanted,
        shares=_shares(found.shares, wanted="shares" in wanted, detailed=detailed),
        shares_note=found.shares.note if detailed and "shares" in wanted else None,
        treasury_stock=_shown(
            TreasuryMovement, found.treasury_stock, () if detailed else ("note",)
        ),
        treasury_stock_by_method=(
            _shown(TreasuryMovement, found.treasury_stock_by_method, ()) if detailed else None
        ),
        capital_changes=_shown(
            CapitalChange, found.capital_changes, () if detailed else ("par_value",)
        ),
        use_of_proceeds=_shown(ProceedsUse, found.use_of_proceeds, () if detailed else ("series",)),
    )


def _empty(
    state: AppState, company: Company, resolved: ResolvedPeriod, *, wanted: list[CapitalSection]
) -> CapitalStructureResult:
    """Build the result for a company without periodic-report data.

    Args:
        state (AppState): Server state.
        company (Company): Resolved company.
        resolved (ResolvedPeriod): Candidates that were tried.
        wanted (list[CapitalSection]): Requested sections.

    Returns:
        CapitalStructureResult: Empty requested sections and a note.
    """
    tried = ", ".join(ref.label for ref in resolved.candidates[:PROBE_ATTEMPTS])
    notes = [resolved.note] if resolved.note else []
    notes.append(
        f"No periodic report for {tried} has a share-count table; unlisted and newly listed companies may not file one."
    )
    return CapitalStructureResult(
        company=company.ref,
        as_of=state.today(),
        notes=notes,
        sections=wanted,
        shares=[] if "shares" in wanted else None,
        treasury_stock=[] if "treasury_stock" in wanted else None,
        capital_changes=[] if "capital_changes" in wanted else None,
        use_of_proceeds=[] if "use_of_proceeds" in wanted else None,
    )


def _shares(
    counts: capital.ShareCounts, *, wanted: bool, detailed: bool
) -> list[ShareClassRow] | None:
    """List share counts by class, then the all-classes total.

    Args:
        counts (capital.ShareCounts): Share counts.
        wanted (bool): Whether the section was requested.
        detailed (bool): Whether to keep issuance and cancellation history.

    Returns:
        list[ShareClassRow] | None: Rows, or None when not requested.
    """
    if not wanted:
        return None
    rows = [*counts.classes, *((counts.total,) if counts.total is not None else ())]
    return _shown(ShareClassRow, rows, () if detailed else _SHARE_DETAIL)


def _shown[M: BaseModel](
    model: type[M], rows: Iterable[DataclassInstance] | None, hidden: Sequence[str]
) -> list[M] | None:
    """Show a section's rows as output models without the fields a concise result hides.

    Args:
        model (type[M]): Output model.
        rows (Iterable[DataclassInstance] | None): Rows, or None when not requested.
        hidden (Sequence[str]): Fields to leave out.

    Returns:
        list[M] | None: Output rows, or None when not requested.
    """
    if rows is None:
        return None
    return [model(**(asdict(row) | dict.fromkeys(hidden))) for row in rows]
