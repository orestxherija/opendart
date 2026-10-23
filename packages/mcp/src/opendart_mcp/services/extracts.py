"""Fetch and read periodic-report extracts: one service, one company, one reporting period.

Thirty OpenDART services return tables from periodic reports, keyed by corporation code,
fiscal year, and report code. Their records are SDK models whose fields are all strings:
amounts with thousands separators, ``-`` for nothing, labels in English or Korean, total rows
mixed with data rows, and term labels such as ``제57기 (당기)`` (57th term, current) for
tables that cover three fiscal years. These helpers fetch records through the gateway, run
several fetches at once, read fields safely, and turn filing numbers into provenance.
"""

from __future__ import annotations

import asyncio
import re
from itertools import takewhile
from typing import TYPE_CHECKING, Final, cast

from opendart_mcp.domain.identifiers import is_filing_number
from opendart_mcp.domain.normalize import clean_text
from opendart_mcp.models.common import SourceFiling
from opendart_mcp.registry import sdk_method
from opendart_mcp.services.periods import PROBE_ATTEMPTS, periodic_ttl

if TYPE_CHECKING:
    from collections.abc import Awaitable, Iterable, Sequence

    from opendart_mcp.core.state import AppState
    from opendart_mcp.domain.periods import PeriodRef
    from opendart_mcp.services.companies import Company
    from opendart_mcp.services.periods import PeriodicReport, ResolvedPeriod

_TOTAL_LABELS: Final = frozenset({"합계", "계", "총계", "소계", "total", "subtotal", "sum"})
# "Not applicable" placeholders that filers write instead of leaving a cell blank.
_NOT_APPLICABLE: Final = frozenset(
    {"해당사항없음", "해당사항없습니다", "해당없음", "없음", "n/a", "na", "none", "notapplicable"}
)
# Korean 기 (term) or an English ordinal suffix, as in 57th.
_TERM_NUMBER: Final = re.compile(r"(\d{1,4})\s*(?:기|th|st|[nr]d)(?![a-z])", re.IGNORECASE)
_YEAR: Final = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")
_TERM_WORDS: Final = (
    ("전전기", 2),
    ("전기", 1),
    ("당기", 0),
    ("twoyearsprior", 2),
    ("prior", 1),
    ("previous", 1),
    ("current", 0),
)


async def fetch_response(
    state: AppState, service: str, *, company: Company, ref: PeriodRef
) -> object | None:
    """Call one periodic-report service for a company and period, through the cache.

    Answers for a period whose filing deadline has not settled are cached only briefly, so
    a report filed or corrected meanwhile is picked up; settled periods are cached a day.

    Args:
        state (AppState): Server state.
        service (str): SDK method name, such as ``alot_matter``.
        company (Company): Resolved company.
        ref (PeriodRef): Fiscal year and period.

    Returns:
        object | None: SDK response model, or None when OpenDART has no data.
    """
    gateway = state.require_gateway()
    return await gateway.call(
        periodic_ttl(state, company, ref),
        sdk_method(gateway.sdk, service),
        corporation_code=company.corp_code,
        fiscal_year=str(ref.fiscal_year),
        report_period=ref.report_code,
    )


async def fetch_records(
    state: AppState, service: str, *, company: Company, ref: PeriodRef
) -> list[object] | None:
    """Fetch one periodic-report service's ``list`` records for a company and period.

    Args:
        state (AppState): Server state.
        service (str): SDK method name.
        company (Company): Resolved company.
        ref (PeriodRef): Fiscal year and period.

    Returns:
        list[object] | None: Records, or None when OpenDART has no data.
    """
    response = await fetch_response(state, service, company=company, ref=ref)
    return None if response is None else records(response)


def records(response: object, name: str = "list") -> list[object]:
    """Read a record container from a response.

    Args:
        response (object): SDK response model.
        name (str): Container attribute: ``list``, or ``group`` for the Ver 2.0 services.

    Returns:
        list[object]: Records, empty when the container is missing.
    """
    value = getattr(response, name, None)
    return list(value) if isinstance(value, list) else []


async def gather_all[T](calls: Iterable[Awaitable[T]]) -> list[T]:
    """Await calls concurrently and return their results in order.

    Every call runs to completion so each answer reaches the cache; then the first failure,
    if any, is raised unwrapped so its actionable message survives.

    Args:
        calls (Iterable[Awaitable[T]]): Calls to await.

    Returns:
        list[T]: Results in call order.

    Raises:
        BaseException: The first failure among the calls.
    """
    results = await asyncio.gather(*calls, return_exceptions=True)
    for result in results:
        if isinstance(result, BaseException):
            raise result
    return cast("list[T]", results)


def text(record: object, name: str) -> str | None:
    """Read one string field from an SDK record.

    Args:
        record (object): SDK record model.
        name (str): Field name, as the SDK names it.

    Returns:
        str | None: The raw value, or None when the field is missing or not a string.
    """
    value = getattr(record, name, None)
    return value if isinstance(value, str) else None


def fold(value: str | None) -> str:
    """Fold a label for matching: no whitespace, case-folded.

    Args:
        value (str | None): Label.

    Returns:
        str: Folded label; empty for None.
    """
    return "".join((value or "").split()).casefold()


def is_total(value: str | None) -> bool:
    """Tell whether a row label marks a total, such as 합계, 계, or Total.

    Args:
        value (str | None): Row label.

    Returns:
        bool: True for total and subtotal labels.
    """
    return fold(value) in _TOTAL_LABELS


def filed_text(value: str | None) -> str | None:
    """Clean free text and drop dashes and "not applicable" placeholders.

    Args:
        value (str | None): Raw field.

    Returns:
        str | None: Text with single spaces, or None.
    """
    cleaned = clean_text(value)
    if cleaned is None or fold(cleaned).rstrip(".") in _NOT_APPLICABLE:
        return None
    return cleaned


def probe_attempts(resolved: ResolvedPeriod) -> int:
    """Choose how many candidate periods to probe for data.

    A periodic report found in the filing index settles the period, so only that period is
    read, under each fiscal-year label it may have: with a non-December year end, OpenDART
    may label the year by the year it ends or the year it starts, and ``resolve_period``
    lists the second label right after the report's. Periods guessed from filing deadlines
    are probed like other components.

    Args:
        resolved (ResolvedPeriod): Candidates from ``resolve_period``.

    Returns:
        int: The number of leading candidates for the filed report's period, one per
            fiscal-year label, or the shared probe limit without a report.
    """
    report = resolved.report
    if report is None:
        return PROBE_ATTEMPTS
    end = report.ref.end_date
    labels = takewhile(
        lambda ref: ref.period == report.ref.period and end is not None and ref.end_date == end,
        resolved.candidates,
    )
    return min(max(sum(1 for _ in labels), 1), PROBE_ATTEMPTS)


def checked(resolved: ResolvedPeriod) -> str:
    """Name the report, or the periods probed, for notes that report missing data.

    Args:
        resolved (ResolvedPeriod): Candidates from ``resolve_period``.

    Returns:
        str: The report title in quotes, or period labels such as "FY2025, FY2024".
    """
    if resolved.report is not None:
        return f'"{resolved.report.title}"'
    return ", ".join(ref.label for ref in resolved.candidates[: probe_attempts(resolved)])


def sources(
    numbers: Iterable[str | None], report: PeriodicReport | None = None
) -> list[SourceFiling]:
    """Describe the filings that records came from, in order of first appearance.

    Args:
        numbers (Iterable[str | None]): Filing numbers from records; invalid ones are skipped.
        report (PeriodicReport | None): Report found in the filing index, for its title.

    Returns:
        list[SourceFiling]: Provenance entries.
    """
    unique = dict.fromkeys(n.strip() for n in numbers if n and is_filing_number(n.strip()))
    return [
        SourceFiling.of(n, report.title if report and report.filing_number == n else None)
        for n in unique
    ]


def term_ages(labels: Sequence[str | None]) -> list[int]:
    """Number each row's fiscal term back from the newest: 0 current, 1 prior, and so on.

    Rows carry labels such as ``제57기 (당기)`` or ``2025``. Years, or else term numbers,
    decide when every label has one (filers sometimes mislabel older terms as 당기,
    current); otherwise the words 당기, 전기, and 전전기 (current, prior, two years prior)
    decide, and failing both, the order in which labels first appear. Blank labels continue
    the previous row's term.

    Args:
        labels (Sequence[str | None]): Term label of each row, in row order.

    Returns:
        list[int]: Age of each row's term in fiscal years.
    """
    filled: list[str] = []
    for label in labels:
        filled.append(clean_text(label) or (filled[-1] if filled else ""))
    for pattern in (_YEAR, _TERM_NUMBER):
        numbers = [_number(pattern, label) for label in filled]
        known = [n for n in numbers if n is not None]
        if filled and len(known) == len(filled):
            return [max(known) - n for n in known]
    words = [_term_word(label) for label in filled]
    if all(word is not None for word in words):
        return [word or 0 for word in words]
    order = list(dict.fromkeys(filled))
    return [order.index(label) for label in filled]


def _number(pattern: re.Pattern[str], label: str) -> int | None:
    """Read a fiscal year or term number from a term label.

    Args:
        pattern (re.Pattern[str]): Pattern whose first group is the number.
        label (str): Term label.

    Returns:
        int | None: The number, or None when the label has none.
    """
    match = pattern.search(label)
    return int(match.group(1)) if match else None


def _term_word(label: str) -> int | None:
    """Read a term's age from words such as 전기 (prior term).

    Args:
        label (str): Term label.

    Returns:
        int | None: Age in fiscal years, or None when no word matches.
    """
    folded = fold(label)
    return next((age for word, age in _TERM_WORDS if word in folded), None)
