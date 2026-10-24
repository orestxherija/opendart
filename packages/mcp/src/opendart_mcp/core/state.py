"""Server-lifetime state shared by every component call."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING

from opendart_mcp.core.errors import API_KEY_MISSING, ConfigurationError
from opendart_mcp.domain.dates import KST

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import date

    from opendart_analysis.documents.store import DocumentStore
    from opendart_mcp.core.cache import TTLCache
    from opendart_mcp.core.gateway import CacheKey, Gateway
    from opendart_mcp.core.metrics import Metrics
    from opendart_mcp.services.companies import Companies
    from opendart_mcp.services.directory import DirectoryService
    from opendart_mcp.settings import Settings


@dataclass(slots=True)
class AppState:
    """Everything a component needs beyond its arguments.

    Attributes:
        settings (Settings): Server configuration.
        gateway (Gateway | None): Upstream JSON access; None without an API key.
        cache (TTLCache[CacheKey, object]): Response cache behind the gateway.
        directory (DirectoryService): Company directory owner.
        companies (Companies): Company argument resolution.
        metrics (Metrics): Per-component usage counters shared with the middleware.
        documents (DocumentStore | None): Filing document store; None without an API key.
        clock (Callable[[], datetime]): Aware clock; injectable for tests.
        started (datetime): Server start time.
    """

    settings: Settings
    gateway: Gateway | None
    cache: TTLCache[CacheKey, object]
    directory: DirectoryService
    companies: Companies
    metrics: Metrics
    documents: DocumentStore | None = None
    clock: Callable[[], datetime] = field(default=lambda: datetime.now(KST))
    started: datetime = field(default_factory=lambda: datetime.now(KST))

    def require_gateway(self) -> Gateway:
        """Return upstream access or explain how to configure it.

        Returns:
            Gateway: Upstream access.

        Raises:
            ConfigurationError: No API key is configured.
        """
        if self.gateway is None:
            raise ConfigurationError(API_KEY_MISSING)
        return self.gateway

    def require_documents(self) -> DocumentStore:
        """Return the filing document store or explain how to configure it.

        Returns:
            DocumentStore: Document store.

        Raises:
            ConfigurationError: No API key is configured.
        """
        if self.documents is None:
            raise ConfigurationError(API_KEY_MISSING)
        return self.documents

    def today(self) -> date:
        """Today's date in Korea, which defines OpenDART's filing dates.

        Returns:
            date: Current KST date.
        """
        return self.clock().astimezone(KST).date()
