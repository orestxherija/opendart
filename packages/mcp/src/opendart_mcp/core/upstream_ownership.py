"""Bind the data access of ``opendart_analysis.ownership`` and ``capital`` to the gateway.

Like ``core.upstream``, each factory returns a callable that reaches the gateway only when
called, so a keyless server raises the "configure the API key" error at the first upstream
call, and maps the workflow's volatility to a cache lifetime with ``core.ttl.lifetime``. The
gateway arguments are the ones the services used before the workflows moved, so cache keys
and requests are unchanged. Return annotations name the analysis Protocols, so the type check
proves that the SDK's records satisfy them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

from opendart_mcp.core.ttl import lifetime

if TYPE_CHECKING:
    import builtins
    from collections.abc import Awaitable, Callable, Sequence

    from opendart import OpenDART
    from opendart_analysis.capital import (
        FetchCapitalChanges,
        FetchPrivateProceeds,
        FetchPublicProceeds,
        FetchShareCounts,
        FetchTreasuryStock,
    )
    from opendart_analysis.ownership import (
        FetchControlChanges,
        FetchInsiderHoldings,
        FetchLargestHolders,
        FetchMajorHoldings,
        FetchMinorityHolders,
        HoldingQuery,
    )
    from opendart_analysis.reports import ReportQuery
    from opendart_analysis.upstream import Volatility
    from opendart_mcp.core.gateway import Gateway

    type GatewayFactory = Callable[[], Gateway]


class _Listing[T](Protocol):
    """An SDK response whose records are in ``list``."""

    @property
    def list(self) -> builtins.list[T] | None:
        """Access the response records.

        Returns:
            builtins.list[T] | None: Response records, or None when it has none.
        """
        ...


class _FetchReport[T](Protocol):
    """Rows of one periodic-report service for a company and period."""

    async def __call__(
        self, query: ReportQuery, /, *, volatility: Volatility
    ) -> Sequence[T] | None:
        """Return the rows.

        Args:
            query (ReportQuery): Company and period.
            volatility (Volatility): How quickly the answer can change.

        Returns:
            Sequence[T] | None: SDK rows, or None for OpenDART status 013.
        """
        ...


class _FetchHoldings[T](Protocol):
    """Rows of one holding-report service for a company."""

    async def __call__(
        self, query: HoldingQuery, /, *, volatility: Volatility
    ) -> Sequence[T] | None:
        """Return the rows.

        Args:
            query (HoldingQuery): Company.
            volatility (Volatility): How quickly the answer can change.

        Returns:
            Sequence[T] | None: SDK rows, or None for OpenDART status 013.
        """
        ...


type _Method[T] = Callable[[OpenDART], Callable[..., Awaitable[_Listing[T]]]]


def _report[T](gateway: GatewayFactory, method: _Method[T]) -> _FetchReport[T]:
    """Read one periodic-report service with the company's period arguments.

    Args:
        gateway (GatewayFactory): Returns the gateway or raises the configuration error,
            such as ``state.require_gateway``.
        method (_Method[T]): Picks the bound SDK method from the client.

    Returns:
        _FetchReport[T]: Row access for analysis workflows.
    """

    async def fetch(query: ReportQuery, /, *, volatility: Volatility) -> Sequence[T] | None:
        """Read one company's rows for one period.

        Args:
            query (ReportQuery): Company and period.
            volatility (Volatility): How quickly the answer can change.

        Returns:
            Sequence[T] | None: SDK rows, or None for OpenDART status 013.
        """
        upstream = gateway()
        response = await upstream.call(
            lifetime(volatility),
            method(upstream.sdk),
            corporation_code=query.corp_code,
            fiscal_year=str(query.fiscal_year),
            report_period=query.report_code,
        )
        return None if response is None else response.list

    return fetch


def _holdings[T](gateway: GatewayFactory, method: _Method[T]) -> _FetchHoldings[T]:
    """Read one holding-report service, which takes only the company.

    Args:
        gateway (GatewayFactory): Returns the gateway or raises the configuration error.
        method (_Method[T]): Picks the bound SDK method from the client.

    Returns:
        _FetchHoldings[T]: Row access for analysis workflows.
    """

    async def fetch(query: HoldingQuery, /, *, volatility: Volatility) -> Sequence[T] | None:
        """Read one company's reports.

        Args:
            query (HoldingQuery): Company.
            volatility (Volatility): How quickly the answer can change.

        Returns:
            Sequence[T] | None: SDK rows, or None for OpenDART status 013.
        """
        upstream = gateway()
        response = await upstream.call(
            lifetime(volatility), method(upstream.sdk), corporation_code=query.corp_code
        )
        return None if response is None else response.list

    return fetch


def largest_holders_fetch(gateway: GatewayFactory) -> FetchLargestHolders:
    """Read the largest shareholder and related parties with ``hyslr_sttus``.

    Args:
        gateway (GatewayFactory): Returns the gateway or raises the configuration error.

    Returns:
        FetchLargestHolders: Largest-shareholder access for analysis workflows.
    """
    return _report(gateway, lambda sdk: sdk.periodic_reports.hyslr_sttus)


def control_changes_fetch(gateway: GatewayFactory) -> FetchControlChanges:
    """Read changes of the largest shareholder with ``hyslr_chg_sttus``.

    Args:
        gateway (GatewayFactory): Returns the gateway or raises the configuration error.

    Returns:
        FetchControlChanges: Change-of-control access for analysis workflows.
    """
    return _report(gateway, lambda sdk: sdk.periodic_reports.hyslr_chg_sttus)


def minority_holders_fetch(gateway: GatewayFactory) -> FetchMinorityHolders:
    """Read minority shareholders with ``mrhl_sttus``.

    Args:
        gateway (GatewayFactory): Returns the gateway or raises the configuration error.

    Returns:
        FetchMinorityHolders: Minority-shareholder access for analysis workflows.
    """
    return _report(gateway, lambda sdk: sdk.periodic_reports.mrhl_sttus)


def share_counts_fetch(gateway: GatewayFactory) -> FetchShareCounts:
    """Read share counts by class with ``stock_totqy_sttus``.

    Args:
        gateway (GatewayFactory): Returns the gateway or raises the configuration error.

    Returns:
        FetchShareCounts: Share-count access for analysis workflows.
    """
    return _report(gateway, lambda sdk: sdk.periodic_reports.stock_totqy_sttus)


def treasury_stock_fetch(gateway: GatewayFactory) -> FetchTreasuryStock:
    """Read treasury stock movements with ``tesstk_acqs_dsps_sttus``.

    Args:
        gateway (GatewayFactory): Returns the gateway or raises the configuration error.

    Returns:
        FetchTreasuryStock: Treasury-stock access for analysis workflows.
    """
    return _report(gateway, lambda sdk: sdk.periodic_reports.tesstk_acqs_dsps_sttus)


def capital_changes_fetch(gateway: GatewayFactory) -> FetchCapitalChanges:
    """Read share issuances and reductions with ``irds_sttus``.

    Args:
        gateway (GatewayFactory): Returns the gateway or raises the configuration error.

    Returns:
        FetchCapitalChanges: Capital-change access for analysis workflows.
    """
    return _report(gateway, lambda sdk: sdk.periodic_reports.irds_sttus)


def public_proceeds_fetch(gateway: GatewayFactory) -> FetchPublicProceeds:
    """Read the use of public-offering proceeds with ``pssrp_cptal_use_dtls``.

    Args:
        gateway (GatewayFactory): Returns the gateway or raises the configuration error.

    Returns:
        FetchPublicProceeds: Public-offering proceeds access for analysis workflows.
    """
    return _report(gateway, lambda sdk: sdk.periodic_reports.pssrp_cptal_use_dtls)


def private_proceeds_fetch(gateway: GatewayFactory) -> FetchPrivateProceeds:
    """Read the use of private-placement proceeds with ``prvsrp_cptal_use_dtls``.

    Args:
        gateway (GatewayFactory): Returns the gateway or raises the configuration error.

    Returns:
        FetchPrivateProceeds: Private-placement proceeds access for analysis workflows.
    """
    return _report(gateway, lambda sdk: sdk.periodic_reports.prvsrp_cptal_use_dtls)


def major_holdings_fetch(gateway: GatewayFactory) -> FetchMajorHoldings:
    """Read 5% holder reports with ``equity_disclosures.majorstock``.

    Args:
        gateway (GatewayFactory): Returns the gateway or raises the configuration error.

    Returns:
        FetchMajorHoldings: 5% holder report access for analysis workflows.
    """
    return _holdings(gateway, lambda sdk: sdk.equity_disclosures.majorstock)


def insider_holdings_fetch(gateway: GatewayFactory) -> FetchInsiderHoldings:
    """Read executive and major-shareholder reports with ``equity_disclosures.elestock``.

    Args:
        gateway (GatewayFactory): Returns the gateway or raises the configuration error.

    Returns:
        FetchInsiderHoldings: Insider report access for analysis workflows.
    """
    return _holdings(gateway, lambda sdk: sdk.equity_disclosures.elestock)
