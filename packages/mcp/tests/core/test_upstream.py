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
