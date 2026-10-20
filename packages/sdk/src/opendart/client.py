"""Public async SDK client. Each instance owns and closes one reusable HTTP pool."""

from __future__ import annotations

from types import TracebackType
from typing import Self

import httpx2

from opendart._transport import Transport
from opendart.resources.disclosures import Disclosures
from opendart.resources.equity_disclosures import EquityDisclosures
from opendart.resources.financial_statements import FinancialStatements
from opendart.resources.major_issues import MajorIssues
from opendart.resources.periodic_reports import PeriodicReports
from opendart.resources.securities_registration import SecuritiesRegistration
from opendart.settings import OpenDartSettings, get_settings


class OpenDart:
    """Asynchronous English OpenDART client with an owned HTTP pool.

    Use as an async context manager or await aclose() to release connections.

    Attributes:
        disclosures (Disclosures): Operations for disclosures.
        equity_disclosures (EquityDisclosures): Operations for equity disclosures.
        financial_statements (FinancialStatements): Operations for financial
            statements.
        major_issues (MajorIssues): Operations for major issues.
        periodic_reports (PeriodicReports): Operations for periodic reports.
        securities_registration (SecuritiesRegistration): Operations for securities
            registration.
    """

    def __init__(
        self,
        settings: OpenDartSettings | None = None,
        *,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        """Create the shared HTTP pool and bind every API resource.

        Args:
            settings (OpenDartSettings | None): Explicit upstream configuration. None uses
                get_settings().api.
            transport (httpx2.AsyncBaseTransport | None): Optional HTTP transport, typically a
                mock for tests. None uses the default transport. The client owns and closes it.

        Raises:
            pydantic.ValidationError: Implicitly loaded settings are missing or invalid.
            pydantic_settings.SettingsError: Implicit environment configuration cannot be
                parsed.
        """
        self._transport = Transport(settings or get_settings().api, transport=transport)
        self.disclosures = Disclosures(self._transport)
        self.equity_disclosures = EquityDisclosures(self._transport)
        self.financial_statements = FinancialStatements(self._transport)
        self.major_issues = MajorIssues(self._transport)
        self.periodic_reports = PeriodicReports(self._transport)
        self.securities_registration = SecuritiesRegistration(self._transport)

    @property
    def is_closed(self) -> bool:
        """Report whether the owned HTTP pool has been closed.

        Returns:
            bool: True after the underlying HTTP client closes.
        """
        return self._transport.http.is_closed

    async def aclose(self) -> None:
        """Close the owned HTTP pool and release its connections."""
        await self._transport.http.aclose()

    async def __aenter__(self) -> Self:
        """Enter the HTTP client's context and return this SDK client.

        Returns:
            Self: This client with its HTTP pool entered.

        Raises:
            RuntimeError: The underlying client is already open or has been closed.
        """
        await self._transport.http.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Exit the HTTP client's context and release its connections.

        Exceptions from the context body are not suppressed.

        Args:
            exc_type (type[BaseException] | None): Exception type from the context body, or
                None.
            exc (BaseException | None): Exception from the context body, or None.
            traceback (TracebackType | None): Traceback associated with the exception, or None.
        """
        await self._transport.http.__aexit__(exc_type, exc, traceback)
