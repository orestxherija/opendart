"""Binding analysis data access and failures to the server's cache policy and errors."""

from __future__ import annotations

import pytest

from opendart_analysis.errors import (
    AnalysisError,
    DataSourceError,
    MissingDataError,
    NotConfiguredError,
)
from opendart_analysis.reports import PeriodUnavailableError
from opendart_mcp.core.errors import (
    ConfigurationError,
    InvalidArgumentError,
    UpstreamError,
    from_analysis,
)
from opendart_mcp.core.ttl import DAY, FILINGS, HOUR, lifetime
from opendart_mcp.core.upstream import service_fetch


@pytest.mark.parametrize(
    ("volatility", "seconds"), [("low", DAY), ("medium", HOUR), ("high", FILINGS)]
)
def test_volatility_maps_to_the_existing_lifetimes(volatility, seconds):
    assert lifetime(volatility) == seconds


@pytest.mark.parametrize(
    ("error", "expected"),
    [
        (PeriodUnavailableError("Q3", 2030), InvalidArgumentError),
        (MissingDataError("No data."), InvalidArgumentError),
        (AnalysisError("Unusable request."), InvalidArgumentError),
        (DataSourceError("The source failed.", operation="search"), UpstreamError),
        (NotConfiguredError("No search.", dependency="search_filings"), ConfigurationError),
    ],
)
def test_analysis_failures_become_server_errors_with_their_message(error, expected):
    translated = from_analysis(error)
    assert type(translated) is expected
    assert str(translated) == str(error)


class _Gateway:
    """Records gateway calls and answers each with a fixed response."""

    def __init__(self, sdk: object, response: object) -> None:
        self.sdk = sdk
        self.response = response
        self.calls: list[tuple[float, object, dict[str, object]]] = []

    async def call(self, ttl: float, method: object, **kwargs: object) -> object:
        self.calls.append((ttl, method, kwargs))
        return self.response


@pytest.mark.anyio
async def test_service_fetch_binds_the_catalog_name_to_the_sdk_method_and_lifetime(sdk):
    gateway = _Gateway(sdk, response=None)
    fetch = service_fetch(lambda: gateway)

    answer = await fetch(
        "alot_matter",
        volatility="medium",
        corporation_code="00126380",
        fiscal_year="2025",
        report_period="11011",
    )

    assert answer is None
    [(ttl, method, kwargs)] = gateway.calls
    assert ttl == HOUR
    assert method == sdk.periodic_reports.alot_matter
    assert kwargs == {
        "corporation_code": "00126380",
        "fiscal_year": "2025",
        "report_period": "11011",
    }
