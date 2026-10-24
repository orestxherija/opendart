"""The escape hatch: search OpenDART's service catalog and call any JSON service directly.

Every upstream service is already served by a topical tool, so both operations are a last
resort; catalog entries name the covering tool. Calls go through the gateway like every
other upstream request, and their records come back labeled and normalized.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from opendart_mcp.core.errors import InvalidArgumentError
from opendart_mcp.core.progress import no_progress
from opendart_mcp.core.ttl import DAY, FILINGS, HOUR
from opendart_mcp.models.common import NextCall, Pagination
from opendart_mcp.models.services import (
    ServiceCallResult,
    ServiceInfo,
    ServiceListResult,
    ServiceParam,
)
from opendart_mcp.registry import EVENT_KINDS, sdk_method, search_services, service, services
from opendart_mcp.services.catalog_params import Converter, accepts, bind
from opendart_mcp.services.catalog_records import (
    flatten,
    source_filings,
    tables,
    upstream_paging,
)

if TYPE_CHECKING:
    from opendart_mcp.core.progress import Progress
    from opendart_mcp.core.state import AppState
    from opendart_mcp.models.common import ResponseFormat
    from opendart_mcp.models.services import ParamValue
    from opendart_mcp.registry import ServiceSpec

_TTL: Final[dict[str, float]] = {
    "disclosures": FILINGS,
    "equity_disclosures": HOUR,
    "financial_statements": DAY,
    "major_issues": HOUR,
    "periodic_reports": DAY,
    "securities_registration": HOUR,
}
ARCHIVE_TOOLS: Final[dict[str, str]] = {
    "document": "read_filing",
    "corporation_codes": "find_company",
    "fnltt_xbrl": "get_financials",
}
"""Services that return ZIP archives, which call_service cannot read, and the tool to use."""

_TOOL_SERVICES: Final[dict[str, tuple[str, ...]]] = {
    "search_filings": ("search",),
    "get_company_profile": ("company",),
    "get_financials": (
        "fnltt_singl_acnt",
        "fnltt_singl_acnt_all",
        "fnltt_singl_indx",
        "otr_cpr_invstmnt_sttus",
    ),
    "compare_companies": ("fnltt_multi_acnt", "fnltt_cmpny_indx"),
    "get_capital_structure": (
        "stock_totqy_sttus",
        "tesstk_acqs_dsps_sttus",
        "irds_sttus",
        "pssrp_cptal_use_dtls",
        "prvsrp_cptal_use_dtls",
    ),
    "get_ownership": ("hyslr_sttus", "hyslr_chg_sttus", "mrhl_sttus", "majorstock", "elestock"),
    "get_debt_profile": (
        "cprnd_nrdmp_blce",
        "srtpd_psndbt_nrdmp_blce",
        "entrprs_bil_scrits_nrdmp_blce",
        "new_capl_scrits_nrdmp_blce",
        "cndl_capl_scrits_nrdmp_blce",
        "det_scrits_isu_acmslt",
    ),
    "get_dividends": ("alot_matter",),
    "get_governance": (
        "accnut_adtor_nm_nd_adt_opinion",
        "adt_servc_cncls_sttus",
        "accnut_adtor_non_adt_servc_cncls_sttus",
        "outcmpny_drctr_nd_change_sttus",
        "exctv_sttus",
        "emp_sttus",
        "unrst_exctv_mendng_sttus",
        "hmv_audit_all_sttus",
        "hmv_audit_indvdl_by_sttus",
        "hmv_audit_indvdl_by_sttus_v2",
        "indvdl_by_pay",
        "indvdl_by_pay_v2",
        "drctr_adt_all_mendng_sttus_gmtsck_confm_amount",
        "drctr_adt_all_mendng_sttus_mendng_pymntamt_ty_cl",
    ),
}
COVERAGE: Final[dict[str, str]] = {
    **{spec.service: f"get_corporate_events (kind {kind})" for kind, spec in EVENT_KINDS.items()},
    **{name: tool for tool, names in _TOOL_SERVICES.items() for name in names},
    **ARCHIVE_TOOLS,
}
"""The tool that already serves each upstream service, by SDK method name."""


@dataclass(frozen=True, slots=True)
class Page:
    """Which rows of a response to return.

    Attributes:
        number (int): 1-based page number.
        size (int): Rows per page.
    """

    number: int = 1
    size: int = 20


def _info(spec: ServiceSpec) -> ServiceInfo:
    """Describe a service for list_services.

    Args:
        spec (ServiceSpec): Service.

    Returns:
        ServiceInfo: Catalog entry.
    """
    params = [
        ServiceParam(name=p.name, wire=p.wire, required=p.required, accepts=accepts(spec, p))
        for p in spec.params
    ]
    return ServiceInfo(
        service=spec.name,
        title=spec.title,
        description=spec.description,
        params=params,
        covered_by=COVERAGE.get(spec.name),
    )


def list_services(state: AppState, query: str | None, *, limit: int = 10) -> ServiceListResult:
    """Search the services call_service can call.

    Args:
        state (AppState): Server state.
        query (str | None): Keywords; None or blank lists every service in catalog order.
        limit (int): Maximum services to return.

    Returns:
        ServiceListResult: Matching services, best first.
    """
    text = (query or "").strip()
    found = search_services(text, limit=len(services())) if text else services()
    usable = [spec for spec in found if not spec.archive]
    notes = []
    if not usable:
        notes.append(
            f"No service matches '{text}'. Try broader words such as dividend, shareholder, bond, or audit, or omit the query to list every service."
        )
    return ServiceListResult(
        query=text or None,
        total=len(usable),
        services=[_info(spec) for spec in usable[:limit]],
        as_of=state.today(),
        notes=notes,
    )


def _resolve_service(name: str) -> ServiceSpec:
    """Find a service that call_service can call.

    Args:
        name (str): SDK method name, API ID, or endpoint path.

    Returns:
        ServiceSpec: The service.

    Raises:
        InvalidArgumentError: The service is unknown or returns an archive.
    """
    try:
        spec = service(name)
    except KeyError as error:
        message = f"{error.args[0]}. Call list_services to search the catalog."
        raise InvalidArgumentError(message) from error
    if spec.archive:
        message = f"{spec.name} returns a ZIP archive, which call_service cannot read; use {ARCHIVE_TOOLS[spec.name]} instead."
        raise InvalidArgumentError(message)
    return spec


def _pagination(
    spec: ServiceSpec,
    sent: dict[str, ParamValue],
    total: int,
    *,
    page: Page,
    response_format: ResponseFormat,
) -> Pagination:
    """Describe the page of rows returned, with the call for the next one.

    Args:
        spec (ServiceSpec): Service.
        sent (dict[str, ParamValue]): Upstream parameters sent.
        total (int): Rows in the whole response.
        page (Page): Page returned.
        response_format (ResponseFormat): Requested format, repeated in the next call.

    Returns:
        Pagination: Paging fields.
    """
    has_more = page.number * page.size < total
    arguments = {
        "service": spec.name,
        "params": sent,
        "response_format": response_format,
        "limit": page.size,
        "page": page.number + 1,
    }
    next_call = (
        NextCall.model_validate({"tool": "call_service", "arguments": arguments})
        if has_more
        else None
    )
    return Pagination(
        total=total, page=page.number, limit=page.size, has_more=has_more, next_call=next_call
    )


async def call_service(
    state: AppState,
    name: str,
    params: dict[str, ParamValue] | None = None,
    *,
    response_format: ResponseFormat = "concise",
    page: Page | None = None,
    progress: Progress = no_progress,
) -> ServiceCallResult:
    """Call one upstream service with converted parameters and normalize its records.

    Args:
        state (AppState): Server state.
        name (str): SDK method name, API ID, or endpoint path.
        params (dict[str, ParamValue] | None): Values by SDK name, upstream name, or alias.
        response_format (ResponseFormat): concise or detailed.
        page (Page | None): Rows to return; None returns the first 20.
        progress (Progress): Reports company resolution and the upstream call.

    Returns:
        ServiceCallResult: Labeled, normalized records.
    """
    spec = _resolve_service(name)
    bound = bind(spec, params or {})
    gateway = state.require_gateway()
    converter = Converter(spec, state, progress)
    kwargs = {p.name: await converter.value(p, value) for p, value in bound.values()}
    sent = {p.wire: kwargs[p.name] for p, _ in bound.values()}
    await progress(f"Calling {spec.name}")
    response = await gateway.call(_TTL[spec.resource], sdk_method(gateway.sdk, spec), **kwargs)
    rows, page = flatten(response), page or Page()
    shown = rows[(page.number - 1) * page.size : page.number * page.size]
    notes = [*converter.notes, *filter(None, [upstream_paging(response)])]
    if response is None:
        notes.append("OpenDART has no data for these parameters (status 013).")
    return ServiceCallResult(
        service=spec.name,
        title=spec.title,
        params=sent,
        tables=tables(spec, shown, detailed=response_format == "detailed"),
        pagination=_pagination(spec, sent, len(rows), page=page, response_format=response_format),
        source_filings=source_filings(shown),
        notes=notes,
        as_of=state.today(),
    )
