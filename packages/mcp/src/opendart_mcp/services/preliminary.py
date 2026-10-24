"""A company's latest preliminary (unaudited) quarterly results, from KRX fair disclosures.

``opendart_analysis.financials.latest_preliminary`` finds the newest disclosure, opens it,
and parses it; this adapter binds the filing search to the gateway and opening a filing to
the document store, with the foreground download wait and progress heartbeats.
``get_financials(view="preliminary")`` builds on :func:`latest_preliminary`.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from opendart_analysis.financials import latest_preliminary as find_latest
from opendart_mcp.core.progress import no_progress
from opendart_mcp.core.upstream_financials import disclosure_search
from opendart_mcp.models.common import SourceFiling
from opendart_mcp.models.preliminary import PreliminaryResult
from opendart_mcp.services.documents import (
    DocumentUnavailableError,
    UnknownFilingError,
    load_filing,
    wait_seconds,
)

if TYPE_CHECKING:
    from opendart_analysis.documents import ParsedFiling
    from opendart_analysis.financials import OpenFiling
    from opendart_mcp.core.progress import Progress
    from opendart_mcp.core.state import AppState
    from opendart_mcp.services.companies import Company


def _filing_opener(state: AppState, progress: Progress) -> OpenFiling:
    """Bind opening a filing to the document store with the foreground wait.

    Args:
        state (AppState): Server state.
        progress (Progress): Receives download heartbeats.

    Returns:
        OpenFiling: Opens one filing, or answers None when it is unknown or unreadable.
    """

    async def open_filing(filing_number: str, /) -> ParsedFiling | None:
        """Download and parse one filing, or take it from the cache.

        Args:
            filing_number (str): 14-digit filing number.

        Returns:
            ParsedFiling | None: The filing, or None when it is unknown or cannot be read.

        Raises:
            StillRunningError: The download outlived the foreground wait.
        """
        wait_s = wait_seconds(state, background=False)
        try:
            return await load_filing(state, filing_number, wait_s=wait_s, progress=progress)
        except UnknownFilingError, DocumentUnavailableError:
            return None

    return open_filing


async def latest_preliminary(
    state: AppState, company: Company, *, progress: Progress = no_progress
) -> PreliminaryResult | None:
    """Find and parse the company's newest preliminary-earnings fair disclosure.

    Looks back 120 days and opens at most three disclosures, newest first (see
    ``opendart_analysis.financials.latest_preliminary``).

    Args:
        state (AppState): Server state.
        company (Company): Resolved company.
        progress (Progress): Receives a message per disclosure opened and while downloading.

    Returns:
        PreliminaryResult | None: The figures and their source filing, or None when the
            company published no readable preliminary results in the last 120 days.

    Raises:
        StillRunningError: A download outlived the foreground wait; retry shortly.
        UpstreamError: OpenDART failed, for example with the daily quota exhausted.
    """
    found = await find_latest(
        company,
        search_disclosures=disclosure_search(state.require_gateway),
        open_filing=_filing_opener(state, progress),
        today=state.today(),
        progress=progress,
    )
    if found is None:
        return None
    source = SourceFiling.of(found.filing_number, found.title)
    return PreliminaryResult(earnings=found.earnings, source=source, notes=list(found.notes))
