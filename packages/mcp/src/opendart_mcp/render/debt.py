"""Markdown view of the debt profile: maturity ladder, derived figures, and issuance record."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from opendart_mcp.render.markdown import (
    amount,
    company_line,
    footer,
    join,
    percent,
    section,
    table,
    unit_note,
)

if TYPE_CHECKING:
    import datetime as dt
    from collections.abc import Callable

    from opendart_mcp.domain.types import Unit
    from opendart_mcp.models.debt import (
        DebtProfileResult,
        Issuance,
        LadderEntry,
        MaturityBucket,
    )

UNIT: Final[Unit] = "million_krw"
_INSTRUMENTS: Final = {
    "corporate_bonds": "Corporate bonds",
    "short_term_bonds": "Short-term bonds",
    "commercial_paper": "Commercial paper",
    "hybrid_securities": "Hybrid securities",
    "contingent_capital": "Contingent capital",
}
_BUCKETS: Final[tuple[MaturityBucket, ...]] = (
    "<=1y",
    "1-2y",
    "2-3y",
    "1-5y",
    ">3y",
    "3-5y",
    "5-10y",
    ">10y",
)


def _period(result: DebtProfileResult) -> str:
    """Describe the reporting period.

    Args:
        result (DebtProfileResult): Debt profile.

    Returns:
        str: Period sentence, or an empty string when no period had data.
    """
    if result.fiscal_year is None or result.period is None:
        return ""
    label = (
        f"FY{result.fiscal_year}"
        if result.period == "FY"
        else f"{result.period} {result.fiscal_year}"
    )
    end = f", balances as of {result.period_end.isoformat()}" if result.period_end else ""
    return f"Period: {label}{end}. {unit_note(UNIT)}"


def _ladder(ladder: list[LadderEntry]) -> str:
    """Tabulate outstanding balances by remaining maturity.

    Args:
        ladder (list[LadderEntry]): Ladder entries.

    Returns:
        str: Table with one column per bucket in use.
    """
    used = {bucket.maturity_bucket for entry in ladder for bucket in entry.buckets}
    columns = [bucket for bucket in _BUCKETS if bucket in used]
    rows = []
    for entry in ladder:
        amounts = {bucket.maturity_bucket: bucket.amount for bucket in entry.buckets}
        rows.append(
            (
                _INSTRUMENTS[entry.instrument],
                *(amount(amounts.get(column), UNIT) for column in columns),
                amount(entry.total, UNIT),
                amount(entry.public, UNIT),
                amount(entry.private, UNIT),
            )
        )
    headers = ("Instrument", *columns, "Total", "Public", "Private")
    return table(headers, rows, numeric=range(1, len(headers)))


def _derived(result: DebtProfileResult) -> str:
    """Summarize the total and the share due within a year.

    Args:
        result (DebtProfileResult): Debt profile.

    Returns:
        str: One sentence, or an empty string without a ladder.
    """
    derived = result.derived
    if derived.total_debt_securities is None:
        return ""
    total = amount(derived.total_debt_securities, UNIT)
    within = amount(derived.due_within_1y, UNIT)
    share = percent(derived.due_within_1y_pct)
    return f"Total debt securities {total}; due within 1 year {within} ({share})."


def _rating(item: Issuance) -> str | None:
    """Join a rating with its agencies.

    Args:
        item (Issuance): Issue.

    Returns:
        str | None: Rating text, or None.
    """
    if item.rating and item.rating_agency:
        return f"{item.rating} ({item.rating_agency})"
    return item.rating


def _date(value: dt.date | None) -> str | None:
    """Format an optional date.

    Args:
        value (dt.date | None): Date.

    Returns:
        str | None: ISO date, or None.
    """
    return value.isoformat() if value else None


# Issuance columns: heading, cell, and whether the column is dropped when every cell is empty.
_ISSUE_COLUMNS: Final[tuple[tuple[str, Callable[[Issuance], object], bool], ...]] = (
    ("Issued", lambda item: _date(item.issued), False),
    ("Security", lambda item: item.security, False),
    ("Method", lambda item: item.method, True),
    ("Amount", lambda item: amount(item.amount, UNIT), False),
    ("Coupon", lambda item: percent(item.coupon, decimals=2), False),
    ("Rating", _rating, False),
    ("Maturity", lambda item: _date(item.maturity), False),
    ("Redeemed", lambda item: item.redeemed, False),
    ("Issuer", lambda item: item.issuer, True),
    ("Underwriter", lambda item: item.underwriter, True),
)


def _issuance(items: list[Issuance]) -> str:
    """Tabulate the issuance record without optional columns that are empty.

    Args:
        items (list[Issuance]): Issues.

    Returns:
        str: Table, or an empty string without issues.
    """
    columns = [
        (heading, cell)
        for heading, cell, optional in _ISSUE_COLUMNS
        if not optional or any(cell(item) is not None for item in items)
    ]
    rows = [tuple(cell(item) for _, cell in columns) for item in items]
    numeric = [i for i, (heading, _) in enumerate(columns) if heading in {"Amount", "Coupon"}]
    return table([heading for heading, _ in columns], rows, numeric=numeric)


def _filed(ladder: list[LadderEntry]) -> str:
    """Tabulate every maturity column as filed, for detailed results.

    Args:
        ladder (list[LadderEntry]): Ladder entries.

    Returns:
        str: One titled table per instrument with filed columns.
    """
    blocks = []
    for entry in ladder:
        rows = [
            (b.label, amount(b.public, UNIT), amount(b.private, UNIT), amount(b.total, UNIT))
            for b in entry.filed or ()
        ]
        headers = ("Remaining maturity", "Public", "Private", "Total")
        blocks.append(
            section(
                f"{_INSTRUMENTS[entry.instrument]} as filed",
                table(headers, rows, numeric=(1, 2, 3)),
            )
        )
    return join(*blocks)


def render_debt_profile(result: DebtProfileResult) -> str:
    """Render a debt profile.

    Args:
        result (DebtProfileResult): Debt profile.

    Returns:
        str: Markdown.
    """
    limits = [
        f"Short-term bond issuance limit {amount(e.issuance_limit, UNIT)}, remaining {amount(e.remaining_limit, UNIT)}."
        for e in result.ladder
        if e.issuance_limit is not None
    ]
    return join(
        f"**Debt profile: {company_line(result.company)}**",
        _period(result),
        section("Maturity ladder", _ladder(result.ladder)),
        _derived(result),
        *limits,
        section("Issuance record", _issuance(result.issuance)),
        _filed(result.ladder),
        footer(result),
    )
