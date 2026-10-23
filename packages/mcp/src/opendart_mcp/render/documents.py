"""Markdown views of read_filing results: outline tables, pages of text, and search hits."""

from __future__ import annotations

from typing import TYPE_CHECKING

from opendart_mcp.render.markdown import footer, join, number, section, table

if TYPE_CHECKING:
    from opendart_mcp.documents import Amendment
    from opendart_mcp.models.documents import (
        FilingHits,
        FilingInfo,
        FilingOutline,
        FilingPage,
        OutlineSection,
        ReadFilingResult,
    )

_INDENT = "· "


def _filing_line(filing: FilingInfo, document: str) -> str:
    """Describe the filing in one line.

    Args:
        filing (FilingInfo): Filing identity.
        document (str): Key of the document shown.

    Returns:
        str: Form, company, date, number, and viewer link.
    """
    form = filing.form_name or filing.form_name_ko or "Filing"
    korean = f" ({filing.form_name_ko})" if filing.form_name and filing.form_name_ko else ""
    company = ", ".join(
        part
        for part in (filing.company, f"DART {filing.corp_code}" if filing.corp_code else None)
        if part
    )
    details = [
        part
        for part in (
            company or None,
            f"filed {filing.filed.isoformat()}" if filing.filed else None,
            f"filing {filing.filing_number}",
            "amended filing" if filing.is_amendment else None,
            None if document == "main" else f"document {document}",
        )
        if part
    ]
    return f"**{form}{korean}**: {"; ".join(details)}. Original (Korean): {filing.dart_url}"


def _title(entry: OutlineSection) -> str:
    """Indent a section title by its level.

    Args:
        entry (OutlineSection): Outline entry.

    Returns:
        str: English title (Korean when absent), prefixed by its depth.
    """
    return _INDENT * (entry.level - 1) + (entry.title_en or entry.title_ko)


def _flag(entry: OutlineSection) -> str | None:
    """Describe a section's content caveat.

    Args:
        entry (OutlineSection): Outline entry.

    Returns:
        str | None: Caveat, or None.
    """
    if entry.placeholder:
        return "omitted"
    return "images only" if entry.image_only else None


def _amendment(amendment: Amendment) -> str:
    """Summarize what an amended filing changed.

    Args:
        amendment (Amendment): Correction summary.

    Returns:
        str: Titled block with the changes.
    """
    filed = f" filed {amendment.original_filed}" if amendment.original_filed else ""
    document = f" ({amendment.corrected_document})" if amendment.corrected_document else ""
    reason = f" Reason: {amendment.reason}" if amendment.reason else ""
    where = f" Full text: section {amendment.section_id}." if amendment.section_id else ""
    rows = [(change.item, change.before, change.after) for change in amendment.changes]
    return section(
        "Amendment",
        join(
            f"Corrects a filing{filed}{document}.{reason}{where}",
            table(("Item", "Before", "After"), rows),
        ),
    )


def _outline(outline: FilingOutline) -> str:
    """Render a document outline.

    Args:
        outline (FilingOutline): Outline.

    Returns:
        str: Documents, sections, aliases, and the amendment summary.
    """
    documents = (
        table(
            ("Document", "Form code", "Name", "Characters"),
            [(d.key, d.form_code, d.name or d.name_ko, number(d.chars)) for d in outline.documents],
            numeric=(3,),
        )
        if len(outline.documents) > 1
        else ""
    )
    sections = table(
        ("Section", "Title", "Korean title", "Characters", "Tables", "Note"),
        [
            (
                s.id,
                _title(s),
                s.title_ko if s.title_en else None,
                number(s.chars),
                s.tables,
                _flag(s),
            )
            for s in outline.sections
        ],
        numeric=(3, 4),
    )
    aliases = ", ".join(
        f"{alias.alias} ({", ".join(alias.section_ids)})" for alias in outline.suggested_sections
    )
    return join(
        _amendment(outline.amendment) if outline.amendment else "",
        section("Documents", documents),
        section("Sections", sections),
        f"Section aliases: {aliases}." if aliases else "",
        "Read a section with mode='read' and its ID or alias; search with mode='search'.",
    )


def _page(page: FilingPage) -> str:
    """Render one page of text.

    Args:
        page (FilingPage): Page.

    Returns:
        str: Position line, the Markdown content, and how to continue.
    """
    where = (
        f"Section {page.section.id} ({page.section.title_en or page.section.title_ko})"
        if page.section
        else "Whole document"
    )
    end = page.next_offset if page.next_offset is not None else page.total_chars
    position = f"{where}, characters {page.offset:,}-{end:,} of {page.total_chars:,}."
    more = (
        f"More text follows: repeat the call with offset={page.next_offset}."
        if page.next_offset is not None
        else ""
    )
    return join(position, page.content, more)


def _search(search: FilingHits) -> str:
    """Render search hits.

    Args:
        search (FilingHits): Search result.

    Returns:
        str: Match count, numbered passages, and how to read one.
    """
    scope = f" in section {search.section}" if search.section else ""
    matches = f"{search.total_hits} match" + ("" if search.total_hits == 1 else "es")
    passages = f"{len(search.hits)} passage" + ("" if len(search.hits) == 1 else "s")
    lines = [
        f"{index}. {hit.section_id or "outside sections"}"
        + (f" ({hit.section_title_en})" if hit.section_title_en else "")
        + f", offset {hit.section_offset if hit.section_offset is not None else hit.offset}: "
        + hit.snippet
        for index, hit in enumerate(search.hits, 1)
    ]
    hint = (
        "Offsets are within each passage's section: read it with mode='read', that section, the offset, and the same labels."
        if search.hits
        else ""
    )
    return join(
        f'{matches} for "{search.query}"{scope} in {passages}.',
        "\n".join(lines),
        hint,
    )


def render_read_filing(result: ReadFilingResult) -> str:
    """Render a read_filing result.

    Args:
        result (ReadFilingResult): Outline, page, or search result.

    Returns:
        str: Markdown.
    """
    if result.outline is not None:
        body = _outline(result.outline)
    elif result.page is not None:
        body = _page(result.page)
    else:
        body = _search(result.search) if result.search is not None else ""
    return join(_filing_line(result.filing, result.document), body, footer(result))
