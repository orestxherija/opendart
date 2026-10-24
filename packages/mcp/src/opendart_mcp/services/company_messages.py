"""Model-facing messages for company references that do not resolve to one company.

``opendart_analysis.domain.resolver`` returns structured outcomes; these messages turn the
ambiguous, not-found, and directory-not-ready cases into error text that names this
server's tools and tells the model how to re-call.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from opendart_analysis.domain.identifiers import parse_identifier
from opendart_analysis.domain.resolver import company_label

if TYPE_CHECKING:
    from collections.abc import Sequence

    from opendart_analysis.domain.directory import Match

_CODE_HINT = "Re-call with a stock code or corp code."


def ambiguity_message(query: str, candidates: Sequence[Match], limit: int = 5) -> str:
    """Explain an ambiguous reference so the model can re-call with a code.

    Args:
        query (str): Text the caller passed.
        candidates (Sequence[Match]): Candidates in display order.
        limit (int): Maximum number of candidates to list.

    Returns:
        str: Error text naming up to ``limit`` candidates with codes and modification
            dates.
    """
    shown = "; ".join(company_label(match.record) for match in candidates[:limit])
    hidden = len(candidates) - min(len(candidates), limit)
    more = f"; and {hidden} more (call find_company to list them)" if hidden > 0 else ""
    return f"Ambiguous company {query!r}; candidates: {shown}{more}. {_CODE_HINT}"


def not_found_message(query: str) -> str:
    """Explain that no company matches a reference.

    Args:
        query (str): Text the caller passed.

    Returns:
        str: Error text suggesting ``find_company`` or a code.
    """
    identifier = parse_identifier(query)
    if identifier is None:
        return f"No company matches {query!r}. Call find_company with part of the English or Korean name, or pass a 6-digit stock code or 8-digit DART corp code."
    if identifier.kind == "filing_number":
        return f"{identifier.value} is a filing number, not a company. Pass a company name, stock code, or corp code; read_filing takes filing numbers."
    label = "corp code" if identifier.kind == "corp_code" else "stock code"
    return f"No company in the DART directory has {label} {identifier.value}. Check the code, or call find_company with the company name."


def directory_not_ready_message(
    *, elapsed_seconds: float | None = None, error: str | None = None
) -> str:
    """Explain that names cannot be resolved because the directory is not loaded.

    Args:
        elapsed_seconds (float | None): Seconds spent loading so far, when known.
        error (str | None): Last load failure, when loading failed.

    Returns:
        str: Error text with a retry hint and the corp-code workaround.
    """
    hint = "Meanwhile, pass an 8-digit DART corp code, which works without the directory."
    if error:
        return f"The company directory could not be loaded ({error}); the server retries in the background. {hint}"
    waited = f" ({int(elapsed_seconds)} s so far)" if elapsed_seconds is not None else ""
    return f"The company directory is still loading{waited}; OpenDART can take several minutes. Retry shortly. {hint}"
