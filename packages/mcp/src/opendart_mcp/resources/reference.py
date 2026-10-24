"""Reference resources: vocabulary, filing categories, and event kinds.

Each document is generated from the tables the tools themselves use (the vocabulary types,
the filing category table, and the event registry), so it cannot drift from what the tools
accept. Reference content is static for the life of the process.
"""

from __future__ import annotations

import json
from functools import cache
from typing import TYPE_CHECKING, Final, get_args

from fastmcp.resources import resource

from opendart_analysis.catalog import EVENT_GROUPS, EVENT_KINDS
from opendart_analysis.domain.categories import CATEGORY_INFO
from opendart_analysis.domain.periods import (
    FILING_DEADLINE_DAYS,
    FIRST_FISCAL_YEAR,
    FIRST_INDICATOR_YEAR,
    PERIOD_LABELS,
    REPORT_CODES,
)
from opendart_analysis.domain.types import Market, MarketFilter, Unit
from opendart_analysis.domain.units import unit_label
from opendart_mcp.app.annotations import FOR_ASSISTANT
from opendart_mcp.events import CALENDAR_KINDS, PRESENTATIONS
from opendart_mcp.render.markdown import join, table

if TYPE_CHECKING:
    from collections.abc import Mapping

    from opendart_analysis.catalog import EventGroup, EventKindSpec
    from opendart_analysis.domain.types import Basis
    from opendart_mcp.models.common import ResponseFormat

BASIS_MEANINGS: Final[Mapping[Basis, str]] = {
    "auto": "Consolidated statements when filed, otherwise separate ones, with a note.",
    "consolidated": "The group, including subsidiaries (CFS).",
    "separate": "The parent company alone (OFS); many KOSDAQ companies file only these.",
}
UNIT_MEANINGS: Final[Mapping[Unit, str]] = {
    "million_krw": "Default; one decimal place.",
    "billion_krw": "One decimal place.",
    "krw": "Exact integers.",
}
FORMAT_MEANINGS: Final[Mapping[ResponseFormat, str]] = {
    "concise": "Decision-relevant fields; text results are compact tables.",
    "detailed": "Every labeled field, plus the raw upstream strings.",
}
GROUP_MEANINGS: Final[Mapping[EventGroup, str]] = {
    "capital_raise": "Rights and third-party share issues, bonus issues, equity registrations.",
    "convertible_and_hybrid_debt": "Convertible, warrant, exchangeable, and contingent bonds.",
    "buyback": "Treasury stock acquisitions, disposals, and trust contracts.",
    "capital_reduction": "Capital reductions.",
    "mna_and_restructuring": "Mergers, splits, share swaps, and business transfers.",
    "asset_and_investment_deals": "Purchases and sales of shares, bonds, and tangible assets.",
    "distress_and_legal": "Defaults, rehabilitation, creditor workouts, suspensions, lawsuits.",
    "overseas_listing": "Listings and delistings on foreign exchanges.",
}
_COMPANIES: Final = (
    "`company` accepts a name in English or Korean (legal suffixes such as Co., Ltd. are "
    + "ignored), a 6-character stock code (`005930`, `A005930`, `005930.KS`), or an 8-digit "
    + "DART corp code (`00126380`). Codes match exactly; names prefer listed companies. An "
    + "ambiguous name fails with up to five candidates: retry with a code. `companies` takes "
    + "1-20 entries of the same forms."
)
_DATES: Final = (
    "`since` and `until` take ISO dates (`2025-01-01`, also `20250101`), `today`, "
    + "`yesterday`, `ytd`, or durations back from today (`30d`, `2w`, `6m`, `2y`). `until` "
    + "defaults to today in Korea (KST), and a relative `since` counts back from `until`. "
    + "Searches without a company cover at most three months. Calendar horizons count "
    + "forward (`90d`)."
)
_RESULTS: Final = (
    "Every result carries `as_of` (server date, KST), `source_filings` (cite their filing "
    + "numbers; `read_filing` opens them), and `notes` on fallbacks, estimates, and gaps. "
    + "Paged results report `total`, `has_more`, and the exact `next_call`."
)
_LIMITATIONS: Final = (
    "- No prices, volumes, market capitalization, consensus estimates, or news. Never "
    + "estimate price-based metrics; dividend yields are as filed.",
    "- Data lag: annual reports are due {fy} days after the fiscal year end, half-year and "
    + "quarterly reports {q} days after the period end. KRX fair disclosures of preliminary "
    + "results come earlier.",
    "- Amendments: corrected filings carry a bracketed title marker such as [기재정정]. "
    + "Searches return final versions by default, and events are grouped by filing number.",
    '- "No data" from OpenDART (status 013) is an empty result with a note, not an error.',
    "- The API key's daily request quota resets at 00:00 KST.",
    "- Filing documents are Korean; headings and table labels are given in English where "
    + "the filing provides them.",
)


def _codes(values: tuple[str, ...]) -> str:
    """Format vocabulary values as inline code.

    Args:
        values (tuple[str, ...]): Values.

    Returns:
        str: Comma-separated values.
    """
    return ", ".join(f"`{value}`" for value in values)


def _periods() -> str:
    """Describe the period vocabulary.

    Returns:
        str: Table and notes.
    """
    rows = [("`latest`", "Most recent periodic report of any kind", "-", "-")]
    rows += [
        (f"`{p}`", PERIOD_LABELS[p], REPORT_CODES[p], f"{FILING_DEADLINE_DAYS[p]} days")
        for p in REPORT_CODES
    ]
    notes = (
        "`fiscal_year` defaults to the latest year with the requested period. Data starts "
        + f"with fiscal {FIRST_FISCAL_YEAR}; financial ratios with {FIRST_INDICATOR_YEAR}. "
        + "Fiscal years can end in any month (`fiscal_year_end_month` in the profile), so "
        + "results state each period's end date."
    )
    headers = ("period", "Meaning", "Report code", "Due after period end")
    return join(table(headers, rows), notes)


def _glossary[K: str](name: str, meanings: Mapping[K, str]) -> str:
    """Tabulate a vocabulary with meanings.

    Args:
        name (str): Argument name.
        meanings (Mapping[K, str]): Meaning per value.

    Returns:
        str: Table.
    """
    return table((name, "Meaning"), [(f"`{value}`", text) for value, text in meanings.items()])


def _units() -> str:
    """Describe the unit vocabulary.

    Returns:
        str: Table and the scaling rule.
    """
    rows = [(f"`{unit}`", unit_label(unit), UNIT_MEANINGS[unit]) for unit in get_args(Unit)]
    rule = (
        "Only monetary amounts are scaled; per-share amounts (EPS, DPS), share counts, and "
        + "ratios never are. Structured results keep exact won."
    )
    return join(table(("unit", "Label", "Meaning"), rows), rule)


def _categories() -> str:
    """Tabulate filing categories.

    Returns:
        str: Table and a pointer to the code mapping.
    """
    rows = [(f"`{info.name}`", info.description) for info in CATEGORY_INFO.values()]
    pointer = "Upstream codes: opendart://reference/filing-categories."
    return join(table(("category", "Filings"), rows), pointer)


def _events() -> str:
    """Tabulate event groups.

    Returns:
        str: Table and a pointer to the kinds.
    """
    rows = [(f"`{group}`", GROUP_MEANINGS[group]) for group in EVENT_GROUPS]
    pointer = "Kinds, upstream services, and date fields: opendart://reference/event-kinds."
    return join(table(("group", "Events"), rows), pointer)


@cache
def vocabulary_markdown() -> str:
    """Write the vocabulary document.

    Returns:
        str: Markdown.
    """
    limitations = "\n".join(_LIMITATIONS).format(
        fy=FILING_DEADLINE_DAYS["FY"], q=FILING_DEADLINE_DAYS["Q1"]
    )
    markets = (
        f"Markets: {_codes(get_args(Market))} (OpenDART corp_cls Y, K, N, E). Filters: "
        + f"{_codes(get_args(MarketFilter))}."
    )
    return join(
        "# OpenDART vocabulary",
        "Conventions shared by every tool.",
        "## Companies",
        _COMPANIES,
        markets,
        "## Periods",
        _periods(),
        "## Statement basis",
        _glossary("basis", BASIS_MEANINGS),
        "## Units",
        _units(),
        "## Dates",
        _DATES,
        "## Output",
        _glossary("response_format", FORMAT_MEANINGS),
        _RESULTS,
        "## Filing categories",
        _categories(),
        "## Event groups",
        _events(),
        "## Limitations",
        limitations,
    )


@cache
def filing_categories_json() -> str:
    """Map filing categories to upstream codes.

    Returns:
        str: JSON text.
    """
    categories = [
        {
            "name": info.name,
            "pblntf_ty": info.group,
            "pblntf_detail_ty": info.subtype,
            "description": info.description,
        }
        for info in CATEGORY_INFO.values()
    ]
    usage = "Pass names in search_filings(categories=[...]). An entry without pblntf_detail_ty covers its whole group."
    return json.dumps(
        {"usage": usage, "categories": categories}, ensure_ascii=False, separators=(",", ":")
    )


def _kind(spec: EventKindSpec) -> dict[str, object]:
    """Describe one event kind.

    Args:
        spec (EventKindSpec): Registry entry.

    Returns:
        dict[str, object]: JSON-ready description, including the key terms that concise
            event results show and whether the kind feeds the corporate-action calendar.
    """
    presentation = PRESENTATIONS[spec.kind]
    return {
        "kind": spec.kind,
        "label": presentation.label,
        "service": spec.service,
        "resource": spec.resource,
        "title": spec.title,
        "key_terms": [key for key, _ in presentation.terms],
        "calendar": spec.kind in CALENDAR_KINDS,
        "date_fields": dict(spec.date_fields),
    }


@cache
def event_kinds_json() -> str:
    """Describe event groups and kinds.

    Returns:
        str: JSON text.
    """
    groups = [
        {
            "group": group,
            "description": GROUP_MEANINGS[group],
            "kinds": [_kind(spec) for spec in EVENT_KINDS.values() if spec.group == group],
        }
        for group in EVENT_GROUPS
    ]
    usage = "Pass group or kind names in get_corporate_events(categories=[...]) and get_corporate_action_calendar(kinds=[...]), which also takes debt_maturity for maturities from periodic reports; capital_reduction names both a group and a kind and selects the whole group. key_terms are the terms concise event results show; calendar marks kinds whose dates feed the corporate-action calendar."
    return json.dumps({"usage": usage, "groups": groups}, ensure_ascii=False, separators=(",", ":"))


@resource(
    "opendart://reference/vocabulary",
    name="vocabulary",
    version="1.0.0",
    title="Vocabulary",
    description="Argument conventions shared by every tool (companies, periods, basis, units, dates, output, categories, event groups) and the data's limitations.",
    mime_type="text/markdown",
    tags={"reference"},
    annotations=FOR_ASSISTANT,
)
async def vocabulary() -> str:
    """Vocabulary as Markdown.

    Returns:
        str: Markdown.
    """
    return vocabulary_markdown()


@resource(
    "opendart://reference/filing-categories",
    name="filing_categories",
    version="1.0.0",
    title="Filing categories",
    description="Filing category names accepted by search_filings, with their OpenDART pblntf_ty and pblntf_detail_ty codes and descriptions.",
    mime_type="application/json",
    tags={"reference"},
    annotations=FOR_ASSISTANT,
)
async def filing_categories() -> str:
    """Filing categories as JSON.

    Returns:
        str: JSON text.
    """
    return filing_categories_json()


@resource(
    "opendart://reference/event-kinds",
    name="event_kinds",
    version="1.0.0",
    title="Event kinds",
    description="Event groups and kinds accepted by get_corporate_events, with the upstream service and the date fields of each kind.",
    mime_type="application/json",
    tags={"reference"},
    annotations=FOR_ASSISTANT,
)
async def event_kinds() -> str:
    """Event kinds as JSON.

    Returns:
        str: JSON text.
    """
    return event_kinds_json()


RESOURCES = (vocabulary, filing_categories, event_kinds)
