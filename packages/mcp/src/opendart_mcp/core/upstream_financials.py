"""Bind the data access of ``opendart_analysis.financials`` to the gateway.

Like ``core.upstream``, each factory returns a callable that reaches the gateway only when
called, so a keyless server raises the "configure the API key" error at the first upstream
call, and maps the workflow's volatility to a cache lifetime with ``core.ttl.lifetime``. The
gateway arguments are the ones the services used before the workflows moved, so cache keys
and requests are unchanged. Return annotations name the analysis Protocols, so the type check
proves that the SDK's records satisfy them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, cast

from opendart_analysis.domain.dates import yyyymmdd
from opendart_mcp.core.ttl import lifetime

if TYPE_CHECKING:
    from collections.abc import Callable, Sequence

    from opendart_analysis.financials import (
        DisclosureQuery,
        FetchFullStatements,
        FetchIndicators,
        FetchInvestments,
        FetchMajorAccounts,
        FetchPeerAccounts,
        FetchPeerIndicators,
        IndicatorQuery,
        IndicatorRecord,
        InvestmentRecord,
        MajorAccountRecord,
        PeerAccountRecord,
        PeerIndicatorQuery,
        PeerQuery,
        ReportQuery,
        SearchDisclosures,
        StatementQuery,
        StatementRecord,
    )
    from opendart_analysis.upstream import FilingRecord, Volatility
    from opendart_mcp.core.gateway import Gateway

    type GatewayFactory = Callable[[], Gateway]


def major_accounts_fetch(gateway: GatewayFactory) -> FetchMajorAccounts:
    """Read major accounts with ``financial_statements.fnltt_singl_acnt``.

    Args:
        gateway (GatewayFactory): Returns the gateway or raises the configuration error,
            such as ``state.require_gateway``.

    Returns:
        FetchMajorAccounts: Major-account access for analysis workflows.
    """

    async def fetch_major_accounts(
        query: ReportQuery, /, *, volatility: Volatility
    ) -> Sequence[MajorAccountRecord] | None:
        """Read one company's major accounts for one period, both bases.

        Args:
            query (ReportQuery): Company and period.
            volatility (Volatility): How quickly the answer can change.

        Returns:
            Sequence[MajorAccountRecord] | None: SDK rows, or None for OpenDART status 013.
        """
        upstream = gateway()
        response = await upstream.call(
            lifetime(volatility),
            upstream.sdk.financial_statements.fnltt_singl_acnt,
            corporation_code=query.corp_code,
            fiscal_year=str(query.fiscal_year),
            report_period=query.report_code,
        )
        return None if response is None else response.list

    return fetch_major_accounts


def full_statements_fetch(gateway: GatewayFactory) -> FetchFullStatements:
    """Read full statements with ``financial_statements.fnltt_singl_acnt_all``.

    Args:
        gateway (GatewayFactory): Returns the gateway or raises the configuration error.

    Returns:
        FetchFullStatements: Full-statement access for analysis workflows.
    """

    async def fetch_full_statements(
        query: StatementQuery, /, *, volatility: Volatility
    ) -> Sequence[StatementRecord] | None:
        """Read one company's full statements for one period and basis.

        Args:
            query (StatementQuery): Company, period, and basis.
            volatility (Volatility): How quickly the answer can change.

        Returns:
            Sequence[StatementRecord] | None: SDK rows, or None for OpenDART status 013.
        """
        upstream = gateway()
        response = await upstream.call(
            lifetime(volatility),
            upstream.sdk.financial_statements.fnltt_singl_acnt_all,
            corporation_code=query.corp_code,
            fiscal_year=str(query.fiscal_year),
            report_period=query.report_code,
            statement_scope=query.scope,
        )
        return None if response is None else response.list

    return fetch_full_statements


def peer_accounts_fetch(gateway: GatewayFactory) -> FetchPeerAccounts:
    """Read several companies' major accounts with ``financial_statements.fnltt_multi_acnt``.

    Args:
        gateway (GatewayFactory): Returns the gateway or raises the configuration error.

    Returns:
        FetchPeerAccounts: Multi-company major-account access for analysis workflows.
    """

    async def fetch_peer_accounts(
        query: PeerQuery, /, *, volatility: Volatility
    ) -> Sequence[PeerAccountRecord] | None:
        """Read several companies' major accounts for one period.

        Args:
            query (PeerQuery): Companies and period.
            volatility (Volatility): How quickly the answer can change.

        Returns:
            Sequence[PeerAccountRecord] | None: SDK rows, which keep the undocumented
                ``corp_code`` as an extra field, or None for OpenDART status 013.
        """
        upstream = gateway()
        response = await upstream.call(
            lifetime(volatility),
            upstream.sdk.financial_statements.fnltt_multi_acnt,
            corporation_codes=list(query.corp_codes),
            fiscal_year=str(query.fiscal_year),
            report_period=query.report_code,
        )
        return None if response is None else response.list

    return fetch_peer_accounts


def indicators_fetch(gateway: GatewayFactory) -> FetchIndicators:
    """Read one company's indicators with ``financial_statements.fnltt_singl_indx``.

    Args:
        gateway (GatewayFactory): Returns the gateway or raises the configuration error.

    Returns:
        FetchIndicators: Indicator access for analysis workflows.
    """

    async def fetch_indicators(
        query: IndicatorQuery, /, *, volatility: Volatility
    ) -> Sequence[IndicatorRecord] | None:
        """Read one indicator category of one company for one period.

        Args:
            query (IndicatorQuery): Company, period, and category.
            volatility (Volatility): How quickly the answer can change.

        Returns:
            Sequence[IndicatorRecord] | None: SDK rows, or None for OpenDART status 013.
        """
        upstream = gateway()
        response = await upstream.call(
            lifetime(volatility),
            upstream.sdk.financial_statements.fnltt_singl_indx,
            corporation_code=query.corp_code,
            fiscal_year=str(query.fiscal_year),
            report_period=query.report_code,
            indicator_category_code=query.category,
        )
        return None if response is None else response.list

    return fetch_indicators


def peer_indicators_fetch(gateway: GatewayFactory) -> FetchPeerIndicators:
    """Read several companies' indicators with ``financial_statements.fnltt_cmpny_indx``.

    Args:
        gateway (GatewayFactory): Returns the gateway or raises the configuration error.

    Returns:
        FetchPeerIndicators: Multi-company indicator access for analysis workflows.
    """

    async def fetch_peer_indicators(
        query: PeerIndicatorQuery, /, *, volatility: Volatility
    ) -> Sequence[IndicatorRecord] | None:
        """Read one indicator category of several companies for one period.

        Args:
            query (PeerIndicatorQuery): Companies, period, and category.
            volatility (Volatility): How quickly the answer can change.

        Returns:
            Sequence[IndicatorRecord] | None: SDK rows, or None for OpenDART status 013.
        """
        upstream = gateway()
        response = await upstream.call(
            lifetime(volatility),
            upstream.sdk.financial_statements.fnltt_cmpny_indx,
            corporation_codes=list(query.corp_codes),
            fiscal_year=str(query.fiscal_year),
            report_period=query.report_code,
            indicator_category_code=query.category,
        )
        return None if response is None else response.list

    return fetch_peer_indicators


def investments_fetch(gateway: GatewayFactory) -> FetchInvestments:
    """Read investments in other companies with ``periodic_reports.otr_cpr_invstmnt_sttus``.

    Args:
        gateway (GatewayFactory): Returns the gateway or raises the configuration error.

    Returns:
        FetchInvestments: Equity-investment access for analysis workflows.
    """

    async def fetch_investments(
        query: ReportQuery, /, *, volatility: Volatility
    ) -> Sequence[InvestmentRecord] | None:
        """Read one company's investee rows for one period.

        Args:
            query (ReportQuery): Company and period.
            volatility (Volatility): How quickly the answer can change.

        Returns:
            Sequence[InvestmentRecord] | None: SDK rows, or None for OpenDART status 013.
        """
        upstream = gateway()
        response = await upstream.call(
            lifetime(volatility),
            upstream.sdk.periodic_reports.otr_cpr_invstmnt_sttus,
            corporation_code=query.corp_code,
            fiscal_year=str(query.fiscal_year),
            report_period=query.report_code,
        )
        return None if response is None else response.list

    return fetch_investments


def disclosure_search(gateway: GatewayFactory) -> SearchDisclosures:
    """Search final filings of one subtype with ``disclosures.search``.

    Args:
        gateway (GatewayFactory): Returns the gateway or raises the configuration error.

    Returns:
        SearchDisclosures: Subtype search for analysis workflows.
    """

    async def search_disclosures(
        query: DisclosureQuery, /, *, volatility: Volatility
    ) -> Sequence[FilingRecord] | None:
        """Read one page of a company's final filings of one subtype, newest first.

        The disclosure type is omitted: OpenDART filters by subtype only without it.

        Args:
            query (DisclosureQuery): Company, filing-date window, and subtype.
            volatility (Volatility): How quickly the answer can change.

        Returns:
            Sequence[FilingRecord] | None: SDK list records, or None for OpenDART status 013.
        """
        upstream = gateway()
        response = await upstream.call(
            lifetime(volatility),
            upstream.sdk.disclosures.search,
            corporation_code=query.corp_code,
            filing_start_date=yyyymmdd(query.start),
            filing_end_date=yyyymmdd(query.end),
            final_reports_only="Y",
            # Subtypes are text in analysis; the SDK types them as a literal.
            disclosure_subcategory=cast("Any", query.subtype),
            page_size=query.limit,
        )
        return None if response is None else response.list

    return search_disclosures
