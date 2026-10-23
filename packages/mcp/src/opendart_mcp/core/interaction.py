"""Per-request user interaction that services use without depending on the MCP framework.

The tool layer installs a chooser for the duration of a call when the host can ask the user
to pick among ambiguous companies; company resolution consults it before giving up with a
candidate list.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterator

    from opendart_mcp.domain.directory import CorpRecord, Match

    type Chooser = Callable[[str, tuple[Match, ...]], Awaitable[CorpRecord | None]]

_CHOOSER: ContextVar[Chooser | None] = ContextVar("opendart_mcp_chooser", default=None)


def current_chooser() -> Chooser | None:
    """Return the chooser installed for the current call, if any.

    Returns:
        Chooser | None: Asks the user to pick a company, or None when the host cannot.
    """
    return _CHOOSER.get()


@contextmanager
def choosing(chooser: Chooser | None) -> Iterator[None]:
    """Install a chooser while the block runs.

    Args:
        chooser (Chooser | None): Chooser for this call; None disables asking.

    Yields:
        None: Control while the chooser is installed.
    """
    token = _CHOOSER.set(chooser)
    try:
        yield
    finally:
        _CHOOSER.reset(token)
