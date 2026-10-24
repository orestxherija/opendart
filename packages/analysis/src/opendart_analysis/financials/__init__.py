"""Financial statements, indicators, equity investments, preliminary earnings, and peers.

Workflows take a company, a resolved period where one applies (from
``opendart_analysis.reports.resolve_period``), and the upstream operations they need as
keyword-only callables, following ``opendart_analysis.upstream``:

    resolved = await resolve_period(
        company, period="latest", fiscal_year=None, search_filings=search, today=today
    )
    history = await major_accounts(
        company, resolved, request=HistoryRequest(), fetch_major_accounts=fetch, today=today
    )

Amounts stay as filed, in the report's currency (normally won); derived metrics and
indicators are percentages. Quarterly income lines hold three-month amounts with year-to-date
amounts alongside. Every workflow bounds its upstream calls: at most three candidate periods,
``MAX_REPORTS`` chained reports, and ``MAX_PEERS`` companies per comparison.

Modules: ``accounts`` (key-account vocabulary), ``statements`` (rows into lines by period,
restatement merging), ``derived`` (growth, margins, leverage), ``specs`` (statement reading
order), and one module per workflow. Importing this package starts nothing.
"""

from __future__ import annotations

from opendart_analysis.financials.access import (
    MAX_PEERS,
    FetchFullStatements,
    FetchMajorAccounts,
    FetchPeerAccounts,
    MajorAccountRecord,
    PeerAccountRecord,
    PeerQuery,
    StatementQuery,
    StatementRecord,
    StatementScope,
)
from opendart_analysis.financials.chain import MAX_REPORTS, Progress
from opendart_analysis.financials.history import (
    HistoryRequest,
    StatementHistory,
    StatementRequest,
    financial_statement,
    major_accounts,
)
from opendart_analysis.financials.indicators import (
    CATEGORIES,
    KEY_INDICATORS,
    PERCENT_NOTE,
    FetchIndicators,
    FetchPeerIndicators,
    IndicatorCategory,
    IndicatorQuery,
    IndicatorRecord,
    IndicatorValue,
    IndicatorsUnavailableError,
    PeerIndicatorQuery,
    company_indicators,
    indicator_history,
    peer_indicators,
)
from opendart_analysis.financials.investments import (
    FetchInvestments,
    Holding,
    Holdings,
    InvestmentRecord,
    fetch_holdings,
    latest_holdings,
)
from opendart_analysis.financials.peers import (
    Peer,
    PeerCompany,
    PeerComparison,
    PeerMetrics,
    PeerRequest,
    PeerValues,
    compare_peers,
)
from opendart_analysis.financials.preliminary import (
    DisclosureQuery,
    OpenFiling,
    PreliminaryRelease,
    SearchDisclosures,
    latest_preliminary,
)
from opendart_analysis.financials.quarters import Quarter, QuarterLines, quarter_lines
from opendart_analysis.financials.specs import (
    STATEMENTS,
    FullStatement,
    StatementKind,
    StatementSpec,
)
from opendart_analysis.financials.statements import (
    Line,
    Number,
    Report,
    StatementBasis,
    ValueKind,
)
from opendart_analysis.reports.query import ReportQuery

__all__ = [
    "CATEGORIES",
    "KEY_INDICATORS",
    "MAX_PEERS",
    "MAX_REPORTS",
    "PERCENT_NOTE",
    "STATEMENTS",
    "DisclosureQuery",
    "FetchFullStatements",
    "FetchIndicators",
    "FetchInvestments",
    "FetchMajorAccounts",
    "FetchPeerAccounts",
    "FetchPeerIndicators",
    "FullStatement",
    "HistoryRequest",
    "Holding",
    "Holdings",
    "IndicatorCategory",
    "IndicatorQuery",
    "IndicatorRecord",
    "IndicatorValue",
    "IndicatorsUnavailableError",
    "InvestmentRecord",
    "Line",
    "MajorAccountRecord",
    "Number",
    "OpenFiling",
    "Peer",
    "PeerAccountRecord",
    "PeerCompany",
    "PeerComparison",
    "PeerIndicatorQuery",
    "PeerMetrics",
    "PeerQuery",
    "PeerRequest",
    "PeerValues",
    "PreliminaryRelease",
    "Progress",
    "Quarter",
    "QuarterLines",
    "Report",
    "ReportQuery",
    "SearchDisclosures",
    "StatementBasis",
    "StatementHistory",
    "StatementKind",
    "StatementQuery",
    "StatementRecord",
    "StatementRequest",
    "StatementScope",
    "StatementSpec",
    "ValueKind",
    "company_indicators",
    "compare_peers",
    "fetch_holdings",
    "financial_statement",
    "indicator_history",
    "latest_holdings",
    "latest_preliminary",
    "major_accounts",
    "peer_indicators",
    "quarter_lines",
]
