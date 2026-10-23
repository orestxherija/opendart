"""Section aliases for periodic reports and section lookup by ID, alias, or heading.

Periodic reports (annual, semi-annual, quarterly) share ``AASSOCNOTE`` section codes across
filers, so aliases map to codes. Financial-sector templates were not sampled, so an alias
falls back to heading matches when its codes are absent.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

from opendart_mcp.documents.tree import compact

if TYPE_CHECKING:
    from collections.abc import Iterable

    from opendart_mcp.documents.models import SectionInfo
    from opendart_mcp.documents.tree import Section

_NUMBERING = re.compile(r"^(?:[(\[]?[0-9ivxlc가-하]+(?:-[0-9]+)*[.)\]])+", re.IGNORECASE)
_ALIAS_SEPARATORS = re.compile(r"[\s\-]+")
_CLOSEST = 5
_SUBSTRING = 2


@dataclass(frozen=True, slots=True)
class Alias:
    """A stable name for periodic-report sections.

    Attributes:
        name (str): Alias accepted by ``section``.
        codes (tuple[str, ...]): Section codes the alias reads, in document order.
        headings (tuple[str, ...]): Compact English and Korean heading fragments used when no
            code is present.
    """

    name: str
    codes: tuple[str, ...]
    headings: tuple[str, ...]


def _alias(name: str, codes: tuple[str, ...], *headings: str) -> Alias:
    """Build an alias with compacted heading fragments.

    Args:
        name (str): Alias name.
        codes (tuple[str, ...]): Section codes.
        *headings (str): Heading fragments in English or Korean.

    Returns:
        Alias: The alias.
    """
    return Alias(name, codes, tuple(compact(heading) for heading in headings))


ALIASES: tuple[Alias, ...] = (
    _alias("company_overview", ("D-0-1-1-0",), "Company overview", "회사의 개요"),
    _alias(
        "share_capital",
        ("D-0-1-3-0", "D-0-1-4-0"),
        "Total number of shares",
        "Changes in capital stock",
        "주식의 총수",
        "자본금 변동사항",
    ),
    _alias("business", ("D-0-2-0-0",), "Business Description", "사업의 내용"),
    _alias(
        "risk_and_derivatives",
        ("L-0-2-5-L1",),
        "Risk management and derivatives",
        "위험관리 및 파생거래",
    ),
    _alias(
        "contracts_and_rnd",
        ("L-0-2-6-L1",),
        "Major contracts and research and development",
        "주요계약 및 연구개발활동",
    ),
    _alias("financial_summary", ("D-0-3-1-0",), "Summary of financial information", "요약재무정보"),
    _alias(
        "consolidated_statements",
        ("D-0-3-2-0",),
        "Consolidated financial statements",
        "연결재무제표",
    ),
    _alias(
        "consolidated_notes",
        ("D-0-3-3-0",),
        "Notes to the consolidated financial statements",
        "연결재무제표 주석",
    ),
    _alias("separate_statements", ("D-0-3-4-0",), "Separate financial statements", "재무제표"),
    _alias(
        "separate_notes",
        ("D-0-3-5-0",),
        "Notes to the separate financial statements",
        "재무제표 주석",
    ),
    _alias("dividends", ("D-0-3-6-0",), "Matters related to dividends", "배당에 관한 사항"),
    _alias(
        "use_of_proceeds",
        ("D-0-3-7-0",),
        "Matters related to financing through issuance of securities",
        "증권의 발행을 통한 자금조달에 관한 사항",
    ),
    _alias(
        "mdna",
        ("D-0-4-0-0",),
        "Management Assessment and Analysis Opinion",
        "이사의 경영진단 및 분석의견",
    ),
    _alias("audit", ("D-0-5-0-0",), "Audit Opinion", "회계감사인의 감사의견 등"),
    _alias(
        "board", ("D-0-6-1-0",), "Matters related to the board of directors", "이사회에 관한 사항"
    ),
    _alias("shareholders", ("D-0-7-0-0",), "Matters Related to Shareholders", "주주에 관한 사항"),
    _alias(
        "executives_and_employees",
        ("D-0-8-1-0",),
        "Status of executives and employees",
        "임원 및 직원 등의 현황",
    ),
    _alias("executive_pay", ("D-0-8-2-0",), "Executive remuneration", "임원의 보수 등"),
    _alias(
        "affiliates",
        ("D-0-9-0-0",),
        "Matters Related to Affiliated Companies",
        "계열회사 등에 관한 사항",
    ),
    _alias(
        "related_party_transactions",
        ("D-0-10-0-0",),
        "Details of Transactions with Major Shareholders",
        "대주주 등과의 거래내용",
    ),
    _alias(
        "contingent_liabilities",
        ("D-0-11-2-0",),
        "Matters related to contingent liabilities",
        "우발부채 등에 관한 사항",
    ),
    _alias("sanctions", ("D-0-11-3-0",), "Matters related to sanctions", "제재 등과 관련된 사항"),
    _alias(
        "subsequent_events",
        ("D-0-11-4-0",),
        "material matters occurred after the document preparation date",
        "작성기준일 이후 발생한 주요사항",
    ),
)
_BY_NAME: dict[str, Alias] = {alias.name: alias for alias in ALIASES}


def alias_named(query: str) -> Alias | None:
    """Look up an alias by name, ignoring case and treating spaces and dashes as underscores.

    Args:
        query (str): Section query.

    Returns:
        Alias | None: The alias, or None.
    """
    return _BY_NAME.get(_ALIAS_SEPARATORS.sub("_", query.strip().lower()))


def alias_sections(alias: Alias, sections: list[Section], *, periodic: bool) -> list[Section]:
    """Find the sections an alias reads.

    Args:
        alias (Alias): The alias.
        sections (list[Section]): Sections in document order.
        periodic (bool): Whether the document is a periodic report, where codes apply.

    Returns:
        list[Section]: Sections by code in alias order, or the best heading match, or empty.
    """
    if periodic:
        by_code: dict[str, Section] = {}
        for section in sections:
            if section.code:
                by_code.setdefault(section.code, section)
        found = [by_code[code] for code in alias.codes if code in by_code]
        if found:
            return found
    for fragment in alias.headings:
        best = best_heading(fragment, sections, strict=True)
        if best is not None:
            return [best]
    return []


def find_sections(query: str, sections: list[Section], *, periodic: bool) -> list[Section]:
    """Resolve a section query: an ID, an alias, or a heading substring.

    Headings are matched against English titles first, then Korean titles, ignoring case,
    whitespace, and leading numbering.

    Args:
        query (str): Outline ID, alias, or heading text.
        sections (list[Section]): Sections in document order.
        periodic (bool): Whether the document is a periodic report.

    Returns:
        list[Section]: Matching sections in reading order; empty when nothing matches.
    """
    wanted = query.strip().lower()
    if not wanted:
        return []
    exact = [s for s in sections if wanted in {s.id.lower(), (s.code or "").lower()}]
    if exact:
        return exact[:1]
    alias = alias_named(query)
    if alias is not None:
        found = alias_sections(alias, sections, periodic=periodic)
        if found:
            return found
    best = best_heading(compact(query), sections)
    return [best] if best is not None else []


def best_heading(fragment: str, sections: list[Section], *, strict: bool = False) -> Section | None:
    """Pick the section whose heading best matches a compact fragment.

    English headings are tried before Korean ones. Exact matches (ignoring numbering) beat
    prefixes, which beat substrings; ties go to the shallowest, then earliest, section.

    Args:
        fragment (str): Compact (lowercase, whitespace-free) heading text.
        sections (list[Section]): Sections in document order.
        strict (bool): Accept only exact and prefix matches, as alias fallbacks do, so that
            ``재무제표`` does not match ``연결재무제표``.

    Returns:
        Section | None: The best match, or None.
    """
    if not fragment:
        return None
    for language in ("en", "ko"):
        scored = [
            (score, section.level, order, section)
            for order, section in enumerate(sections)
            if (score := _score(_title(section, language), fragment)) is not None
            and (score < _SUBSTRING or not strict)
        ]
        if scored:
            return min(scored, key=lambda entry: entry[:3])[3]
    return None


def _title(section: Section, language: str) -> str:
    """Return a section's compact heading in one language.

    Args:
        section (Section): Section.
        language (str): ``en`` or ``ko``.

    Returns:
        str: Compact heading, or an empty string when absent.
    """
    return compact((section.title.en if language == "en" else section.title.ko) or "")


def _score(title: str, fragment: str) -> int | None:
    """Score how well a compact heading matches a fragment.

    Args:
        title (str): Compact heading.
        fragment (str): Compact query fragment.

    Returns:
        int | None: 0 for an exact match ignoring numbering, 1 for a prefix, 2 for a
            substring, or None for no match.
    """
    if not title:
        return None
    bare = _NUMBERING.sub("", title)
    if fragment in {title, bare}:
        return 0
    if bare.startswith(fragment):
        return 1
    return _SUBSTRING if fragment in title else None


def closest(query: str, infos: Iterable[SectionInfo]) -> list[SectionInfo]:
    """Return the outline entries most similar to a query, for error messages.

    Args:
        query (str): Section query that matched nothing.
        infos (Iterable[SectionInfo]): Outline entries.

    Returns:
        list[SectionInfo]: Up to five entries, most similar first.
    """
    wanted = compact(query)
    ranked = sorted(
        infos,
        key=lambda info: (
            -max(
                difflib.SequenceMatcher(None, wanted, compact(text)).ratio()
                for text in (info.id, info.title_en or "", info.title_ko)
            )
        ),
    )
    return ranked[:_CLOSEST]
