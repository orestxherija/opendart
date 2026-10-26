"""Argument completion for prompts and resource templates.

Company names and corp codes come from the loaded company directory, listed companies first;
closed vocabularies come from the same tables the prompts and resources validate against.
Nothing is suggested while the directory loads or without a match.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, get_args

from fastmcp.server.completions import MAX_COMPLETION_VALUES
from fastmcp.server.dependencies import get_context
from mcp.types import PromptReference

from opendart_analysis.domain.categories import FILING_CATEGORIES
from opendart_analysis.domain.names import has_hangul
from opendart_analysis.domain.types import Period
from opendart_mcp.app.state import STATE_KEY
from opendart_mcp.core.state import AppState
from opendart_mcp.prompts.events import DIRECTIONS, GROUP_OF
from opendart_mcp.prompts.market import MARKETS, PEER_FOCUS, SCREEN_FOCUS

if TYPE_CHECKING:
    from collections.abc import Iterable

    from fastmcp.server.completions import CompletionHandler
    from mcp.types import CompletionArgument, CompletionContext, ResourceTemplateReference

    from opendart_analysis.domain.directory import Directory

_VOCABULARIES: Final[dict[tuple[str, str], tuple[str, ...]]] = {
    ("earnings_review", "period"): get_args(Period),
    ("pre_trade_checklist", "direction"): DIRECTIONS,
    ("filings_screen", "market"): ("KOSPI,KOSDAQ", *MARKETS),
    ("filings_screen", "focus"): tuple(SCREEN_FOCUS),
    ("peer_comparison", "focus"): tuple(PEER_FOCUS),
    ("event_impact", "event"): tuple(GROUP_OF),
}
"""Closed vocabularies of prompt arguments, by prompt and argument name."""


def _directory() -> Directory | None:
    """Return the loaded company directory of the current server, if any.

    Returns:
        Directory | None: The directory, or None outside a request or while it loads.
    """
    try:
        context = get_context()
    except RuntimeError:
        return None
    state = context.lifespan_context.get(STATE_KEY)
    return state.directory.directory if isinstance(state, AppState) else None


def matching(options: Iterable[str], value: str) -> list[str]:
    """Rank options that start with, then contain, the typed text, ignoring case.

    Args:
        options (Iterable[str]): Candidate values.
        value (str): Text typed so far.

    Returns:
        list[str]: Matching options.
    """
    folded = value.strip().casefold()
    candidates = list(options)
    prefix = [option for option in candidates if option.casefold().startswith(folded)]
    inner = [o for o in candidates if folded in o.casefold() and o not in prefix]
    return prefix + inner


def company_names(directory: Directory, value: str) -> list[str]:
    """Suggest company names, listed companies first.

    Names are Korean when the typed text contains Hangul, otherwise English when known.

    Args:
        directory (Directory): Company directory.
        value (str): Text typed so far.

    Returns:
        list[str]: Distinct names in rank order.
    """
    if not value.strip():
        return []
    matches = directory.search(value, limit=MAX_COMPLETION_VALUES)
    korean = has_hangul(value)
    ranked = sorted(matches, key=lambda match: not match.record.listed)
    names = [m.record.name if korean else m.record.display_name for m in ranked]
    return list(dict.fromkeys(names))


def _company_list(directory: Directory, value: str) -> list[str]:
    """Complete the last entry of a comma-separated company list.

    Args:
        directory (Directory): Company directory.
        value (str): List typed so far.

    Returns:
        list[str]: The whole list with each suggestion for its last entry.
    """
    head, comma, tail = value.rpartition(",")
    prefix = f"{head}{comma} " if comma else ""
    return [prefix + name for name in company_names(directory, tail)]


def _corp_codes(directory: Directory, value: str) -> list[str]:
    """Suggest corp codes for a name or code typed so far.

    Args:
        directory (Directory): Company directory.
        value (str): Name, stock code, or corp code.

    Returns:
        list[str]: Corp codes in rank order.
    """
    if not value.strip():
        return []
    return [m.record.corp_code for m in directory.search(value, limit=MAX_COMPLETION_VALUES)]


def _company_argument(name: str, value: str) -> list[str]:
    """Complete a company, companies, or corp_code argument from the directory.

    Args:
        name (str): Argument name.
        value (str): Text typed so far.

    Returns:
        list[str]: Suggestions; none while the directory loads.
    """
    directory = _directory()
    if directory is None:
        return []
    if name == "corp_code":
        return _corp_codes(directory, value)
    if name == "companies":
        return _company_list(directory, value)
    return company_names(directory, value)


async def complete(
    ref: PromptReference | ResourceTemplateReference,
    argument: CompletionArgument,
    context: CompletionContext | None,
) -> list[str] | None:
    """Suggest values for a prompt or resource template argument.

    Args:
        ref (PromptReference | ResourceTemplateReference): Prompt or template.
        argument (CompletionArgument): Argument name and the text typed so far.
        context (CompletionContext | None): Arguments already given; unused.

    Returns:
        list[str] | None: Suggestions, or None for arguments without completion.
    """
    del context
    name, value = argument.name, argument.value
    if name in {"company", "companies", "corp_code"}:
        return _company_argument(name, value)
    if isinstance(ref, PromptReference):
        options = _VOCABULARIES.get((ref.name, name))
    else:
        options = FILING_CATEGORIES if name == "category" else None
    return None if options is None else matching(options, value)


HANDLER: Final[CompletionHandler | None] = complete
"""The server's completion handler."""
