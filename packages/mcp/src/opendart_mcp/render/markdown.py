"""Compact Markdown for tool results: tables, numbers, identity lines, and footers.

Hosts show the model this text, while typed JSON goes to the host as structured content.
Tables cost far fewer tokens than repeated JSON keys, so concise results use them.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from opendart_analysis.domain.units import scale_amount, unit_label

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence
    from datetime import date

    from opendart_analysis.domain.types import Unit
    from opendart_mcp.models.common import CompanyRef, ToolOutput

MISSING_VALUE: Final = "-"


def escape(text: object) -> str:
    """Make a value safe inside one Markdown table cell.

    Args:
        text (object): Cell value; None renders as a dash.

    Returns:
        str: Single-line text with pipes escaped.
    """
    if text is None:
        return MISSING_VALUE
    return " ".join(str(text).split()).replace("|", "\\|") or MISSING_VALUE


def table(
    headers: Sequence[str], rows: Iterable[Sequence[object]], *, numeric: Iterable[int] = ()
) -> str:
    """Render a Markdown table, right-aligning numeric columns.

    Args:
        headers (Sequence[str]): Column headings.
        rows (Iterable[Sequence[object]]): Cell values; None renders as a dash.
        numeric (Iterable[int]): Zero-based indexes of right-aligned columns.

    Returns:
        str: Table text, or an empty string when there are no rows.
    """
    right = set(numeric)
    body = ["| " + " | ".join(escape(cell) for cell in row) + " |" for row in rows]
    if not body:
        return ""
    rule = "| " + " | ".join("---:" if i in right else "---" for i in range(len(headers))) + " |"
    return "\n".join(["| " + " | ".join(escape(h) for h in headers) + " |", rule, *body])


def number(value: float | None, *, decimals: int = 0) -> str:
    """Format a number with thousands separators.

    Args:
        value (float | None): Number to format; None renders as a dash.
        decimals (int): Digits after the decimal point.

    Returns:
        str: Formatted number.
    """
    return MISSING_VALUE if value is None else f"{value:,.{decimals}f}"


def amount(value: int | None, unit: Unit) -> str:
    """Format a won amount in the requested unit.

    Args:
        value (int | None): Exact amount in won.
        unit (Unit): Display unit; million and billion won keep one decimal place.

    Returns:
        str: Formatted amount without the unit label.
    """
    scaled = scale_amount(value, unit)
    return number(scaled, decimals=0 if unit == "krw" else 1)


def percent(value: float | None, *, decimals: int = 1, signed: bool = False) -> str:
    """Format a percentage value that is already in percent units.

    Args:
        value (float | None): Percentage, for example 12.5 for 12.5%.
        decimals (int): Digits after the decimal point.
        signed (bool): Whether to prefix positive values with a plus sign.

    Returns:
        str: Formatted percentage.
    """
    if value is None:
        return MISSING_VALUE
    return f"{value:+.{decimals}f}%" if signed else f"{value:.{decimals}f}%"


def company_line(company: CompanyRef) -> str:
    """Describe a resolved company in one line.

    Args:
        company (CompanyRef): Resolved identity.

    Returns:
        str: For example "Samsung Electronics (005930, KOSPI; DART 00126380)".
    """
    listing = ", ".join(part for part in (company.stock_code, company.market) if part)
    prefix = f"{listing}; " if listing else ""
    return f"{company.name} ({prefix}DART {company.corp_code})"


def unit_note(unit: Unit) -> str:
    """State the monetary unit used by a table.

    Args:
        unit (Unit): Display unit.

    Returns:
        str: For example "Amounts in KRW million."
    """
    return f"Amounts in {unit_label(unit)}."


def footer(output: ToolOutput, *, limit: int = 5) -> str:
    """Render provenance: notes, cited filings, and the as-of date.

    Args:
        output (ToolOutput): Result whose provenance to render.
        limit (int): Maximum filings to list; the rest are counted.

    Returns:
        str: Footer text.
    """
    lines = [f"Note: {note}" for note in output.notes]
    filings = output.source_filings
    cited = ", ".join(f"{f.filing_number} ({_title(f.title, f.filed)})" for f in filings[:limit])
    if cited:
        more = f" and {len(filings) - limit} more" if len(filings) > limit else ""
        lines.append(f"Sources: {cited}{more}.")
    lines.append(f"As of {output.as_of.isoformat()} (KST).")
    return "\n".join(lines)


def _title(title: str | None, filed: date | None) -> str:
    """Join a filing title and date for citation.

    Args:
        title (str | None): Report title.
        filed (date | None): Filing date.

    Returns:
        str: Title and date, or whichever is known.
    """
    parts = [part for part in (title, filed.isoformat() if filed else None) if part]
    return ", ".join(parts) or "filing"


def section(title: str, body: str) -> str:
    """Render a titled block, omitting it when the body is empty.

    Args:
        title (str): Heading text.
        body (str): Block content.

    Returns:
        str: Markdown with a level-3 heading, or an empty string.
    """
    return f"### {title}\n{body}" if body.strip() else ""


def join(*blocks: str) -> str:
    """Join non-empty blocks with blank lines.

    Args:
        *blocks (str): Text blocks; empty ones are skipped.

    Returns:
        str: Combined text.
    """
    return "\n\n".join(block for block in blocks if block.strip())
