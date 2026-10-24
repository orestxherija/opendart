"""get_capital_structure: share counts, treasury stock, capital changes, and use of proceeds.

Every section comes from one periodic report. The period is the first candidate whose
share-count table (``stock_totqy_sttus``) has data, since every periodic report files one;
the requested sections are then read for that period: treasury stock movements
(``tesstk_acqs_dsps_sttus``, a hierarchy of acquisition methods with subtotal and "Total"
rows), share issuances and reductions (``irds_sttus``), and planned versus actual use of
money raised by public offerings (``pssrp_cptal_use_dtls``) and private placements
(``prvsrp_cptal_use_dtls``). Tables with nothing to report arrive as rows of dashes.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from opendart_analysis.domain.identifiers import is_filing_number
from opendart_analysis.domain.normalize import clean_text, parse_amount, parse_date
from opendart_mcp.core.progress import no_progress
from opendart_mcp.models.capital import (
    CapitalChange,
    CapitalStructureResult,
    ProceedsUse,
)
from opendart_mcp.models.common import SourceFiling
from opendart_mcp.services.capital_treasury import treasury_methods, treasury_totals
from opendart_mcp.services.periods import (
    PROBE_ATTEMPTS,
    first_available,
    periodic_ttl,
    resolve_period,
)
from opendart_mcp.services.shares import (
    blank,
    fetch_share_counts,
    period_args,
    report_rows,
    share_class,
    trim,
)

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Sequence

    from opendart.models.periodic_reports import (
        IrdsSttusResponseListItem,
        PrvsrpCptalUseDtlsResponseListItem,
        PssrpCptalUseDtlsResponseListItem,
    )
    from opendart_analysis.domain.periods import PeriodRef
    from opendart_analysis.domain.types import Period
    from opendart_mcp.core.progress import Progress
    from opendart_mcp.core.state import AppState
    from opendart_mcp.models.capital import CapitalSection, ShareClassRow
    from opendart_mcp.services.companies import Company
    from opendart_mcp.services.periods import ResolvedPeriod
    from opendart_mcp.services.shares import Listing, PeriodArgs, ShareCounts

SECTIONS: Final[tuple[CapitalSection, ...]] = (
    "shares",
    "treasury_stock",
    "capital_changes",
    "use_of_proceeds",
)
"""Every section, in output order."""

# Keywords of filed issuance and reduction types, checked in order, and their English names.
_CHANGE_CATEGORIES: Final = (
    ("유상증자", "paid-in capital increase"),
    ("무상증자", "bonus issue"),
    ("주식배당", "stock dividend"),
    ("주식매수선택권", "stock option exercise"),
    ("신주인수권", "warrant exercise"),
    ("전환", "conversion"),
    ("감자", "capital reduction"),
    ("소각", "share retirement"),
    ("합병", "merger"),
    ("액면분할", "stock split"),
    ("주식분할", "stock split"),
    ("병합", "share consolidation"),
    ("교환", "share exchange"),
    ("상환", "redemption"),
)
_ALLOTMENTS: Final = (
    ("제3자배정", "third-party allotment"),
    ("주주배정", "shareholder allotment"),
    ("주주우선공모", "shareholder-priority public offering"),
    ("일반공모", "public offering"),
)
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
    found = await first_available(resolved, lambda ref: fetch_share_counts(state, company, ref))
    if found is None:
        return _empty(state, company, resolved, wanted=wanted)
    ref, counts = found
    await progress(f"Reading the {ref.label} capital tables of {company.ref.name}")
    args, reports = period_args(company, ref), state.require_gateway().sdk.periodic_reports
    ttl = periodic_ttl(state, company, ref)
    treasury, changes, public, private = await asyncio.gather(
        _rows(
            state, reports.tesstk_acqs_dsps_sttus, args, ttl=ttl, wanted="treasury_stock" in wanted
        ),
        _rows(state, reports.irds_sttus, args, ttl=ttl, wanted="capital_changes" in wanted),
        _rows(
            state, reports.pssrp_cptal_use_dtls, args, ttl=ttl, wanted="use_of_proceeds" in wanted
        ),
        _rows(
            state, reports.prvsrp_cptal_use_dtls, args, ttl=ttl, wanted="use_of_proceeds" in wanted
        ),
    )
    detailed = query.detailed
    return CapitalStructureResult(
        company=company.ref,
        as_of=state.today(),
        source_filings=_sources(counts, resolved, ref),
        notes=_notes(resolved, ref),
        fiscal_year=ref.fiscal_year,
        period=ref.period,
        period_end=ref.end_date or counts.as_of,
        sections=wanted,
        shares=_shares(counts, wanted="shares" in wanted, detailed=detailed),
        shares_note=counts.note if detailed and "shares" in wanted else None,
        treasury_stock=treasury_totals(treasury, detailed=detailed),
        treasury_stock_by_method=treasury_methods(treasury) if detailed else None,
        capital_changes=_capital_changes(changes, detailed=detailed),
        use_of_proceeds=_proceeds(public, private, detailed=detailed),
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


async def _rows[T](
    state: AppState,
    method: Callable[..., Awaitable[Listing[T]]],
    args: PeriodArgs,
    *,
    ttl: float,
    wanted: bool,
) -> list[T] | None:
    """Fetch one section's records when the section is requested.

    Args:
        state (AppState): Server state.
        method (Callable[..., Awaitable[Listing[T]]]): Bound SDK method.
        args (PeriodArgs): Company and period.
        ttl (float): Seconds to cache the answer, from ``periodic_ttl``.
        wanted (bool): Whether the section was requested.

    Returns:
        list[T] | None: Records, or None when the section was not requested.
    """
    return await report_rows(state, method, args, ttl=ttl) if wanted else None


def _sources(counts: ShareCounts, resolved: ResolvedPeriod, ref: PeriodRef) -> list[SourceFiling]:
    """Cite the periodic report.

    Args:
        counts (ShareCounts): Share counts, which carry the filing number.
        resolved (ResolvedPeriod): Period resolution, which may name the report.
        ref (PeriodRef): Period used.

    Returns:
        list[SourceFiling]: The report, when its number is well formed.
    """
    number = counts.filing_number
    if number is None or not is_filing_number(number):
        return []
    report = resolved.report
    title = report.title if report is not None and report.ref == ref else None
    return [SourceFiling.of(number, title)]


def _notes(resolved: ResolvedPeriod, ref: PeriodRef) -> list[str]:
    """Explain how the period was chosen.

    Args:
        resolved (ResolvedPeriod): Period resolution.
        ref (PeriodRef): Period used.

    Returns:
        list[str]: Notes.
    """
    notes = [resolved.note] if resolved.note else []
    if ref != resolved.candidates[0]:
        notes.append(
            f"The {resolved.candidates[0].label} report has no share-count table yet; showing {ref.label}."
        )
    return notes


def _shares(counts: ShareCounts, *, wanted: bool, detailed: bool) -> list[ShareClassRow] | None:
    """List share counts by class, then the all-classes total.

    Args:
        counts (ShareCounts): Share counts.
        wanted (bool): Whether the section was requested.
        detailed (bool): Whether to keep issuance and cancellation history.

    Returns:
        list[ShareClassRow] | None: Rows, or None when not requested.
    """
    if not wanted:
        return None
    rows = [*counts.classes, *((counts.total,) if counts.total is not None else ())]
    return rows if detailed else [trim(row, _SHARE_DETAIL) for row in rows]


def change_category(kind: str | None) -> str | None:
    """Name a filed issuance or reduction type in English.

    Args:
        kind (str | None): Type as filed, such as 유상증자(제3자배정).

    Returns:
        str | None: English name such as "paid-in capital increase (third-party
            allotment)", or None when the type is not recognized.
    """
    folded = "".join((kind or "").split())
    base = next((name for word, name in _CHANGE_CATEGORIES if word in folded), None)
    allotment = next((name for word, name in _ALLOTMENTS if word in folded), None)
    return f"{base} ({allotment})" if base is not None and allotment is not None else base


def _capital_changes(
    items: Sequence[IrdsSttusResponseListItem] | None, *, detailed: bool
) -> list[CapitalChange] | None:
    """List share issuances and reductions, newest first.

    Args:
        items (Sequence[IrdsSttusResponseListItem] | None): Upstream rows, or None when the
            section was not requested.
        detailed (bool): Whether to keep par values.

    Returns:
        list[CapitalChange] | None: Changes with a date or a share count.
    """
    if items is None:
        return None
    changes = [
        CapitalChange(
            date=parse_date(item.isu_dcrs_de),
            kind=clean_text(item.isu_dcrs_stle),
            category=change_category(item.isu_dcrs_stle),
            share_class=share_class(item.isu_dcrs_stock_knd),
            shares=parse_amount(item.isu_dcrs_qy),
            par_value=parse_amount(item.isu_dcrs_mstvdv_fval_amount) if detailed else None,
            price=parse_amount(item.isu_dcrs_mstvdv_amount),
        )
        for item in items
    ]
    kept = [change for change in changes if change.date is not None or change.shares is not None]
    return sorted(kept, key=lambda c: c.date.toordinal() if c.date else 0, reverse=True)


def _public_use(item: PssrpCptalUseDtlsResponseListItem) -> ProceedsUse:
    """Parse one public-offering use-of-proceeds row.

    Args:
        item (PssrpCptalUseDtlsResponseListItem): Upstream row.

    Returns:
        ProceedsUse: Planned and actual use.
    """
    return ProceedsUse(
        offering="public",
        kind=clean_text(item.se_nm),
        series=clean_text(item.tm),
        paid_on=parse_date(item.pay_de),
        planned_use=clean_text(item.rs_cptal_use_plan_useprps),
        planned_amount=parse_amount(item.rs_cptal_use_plan_prcure_amount),
        actual_use=clean_text(item.real_cptal_use_dtls_cn),
        actual_amount=parse_amount(item.real_cptal_use_dtls_amount),
        difference_reason=clean_text(item.dffrnc_occrrnc_resn),
        amount_paid=parse_amount(item.pay_amount),
        plan=clean_text(item.on_dclrt_cptal_use_plan),
        actual_status=clean_text(item.real_cptal_use_sttus),
    )


def _private_use(item: PrvsrpCptalUseDtlsResponseListItem) -> ProceedsUse:
    """Parse one private-placement use-of-proceeds row.

    Args:
        item (PrvsrpCptalUseDtlsResponseListItem): Upstream row.

    Returns:
        ProceedsUse: Planned and actual use.
    """
    return ProceedsUse(
        offering="private",
        kind=clean_text(item.se_nm),
        series=clean_text(item.tm),
        paid_on=parse_date(item.pay_de),
        planned_use=clean_text(item.mtrpt_cptal_use_plan_useprps),
        planned_amount=parse_amount(item.mtrpt_cptal_use_plan_prcure_amount),
        actual_use=clean_text(item.real_cptal_use_dtls_cn),
        actual_amount=parse_amount(item.real_cptal_use_dtls_amount),
        difference_reason=clean_text(item.dffrnc_occrrnc_resn),
        amount_paid=parse_amount(item.pay_amount),
        plan=clean_text(item.cptal_use_plan),
        actual_status=clean_text(item.real_cptal_use_sttus),
    )


def _proceeds(
    public: Sequence[PssrpCptalUseDtlsResponseListItem] | None,
    private: Sequence[PrvsrpCptalUseDtlsResponseListItem] | None,
    *,
    detailed: bool,
) -> list[ProceedsUse] | None:
    """List planned versus actual use of proceeds, public offerings first, in filed order.

    Args:
        public (Sequence[PssrpCptalUseDtlsResponseListItem] | None): Public-offering rows,
            or None when the section was not requested.
        private (Sequence[PrvsrpCptalUseDtlsResponseListItem] | None): Private-placement
            rows, or None when the section was not requested.
        detailed (bool): Whether to keep series numbers.

    Returns:
        list[ProceedsUse] | None: Rows with a date, an amount, or a stated use.
    """
    if public is None or private is None:
        return None
    rows = [*map(_public_use, public), *map(_private_use, private)]
    kept = [row for row in rows if not blank(row, "offering", "kind", "series")]
    return kept if detailed else [trim(row, ("series",)) for row in kept]
