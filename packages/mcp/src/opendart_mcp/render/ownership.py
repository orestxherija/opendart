"""Markdown view of get_ownership: control snapshot, control changes, and holding reports."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from opendart_mcp.render.capital import class_name, period_title, sparse_table
from opendart_mcp.render.markdown import (
    MISSING_VALUE,
    company_line,
    footer,
    join,
    number,
    percent,
    section,
)

if TYPE_CHECKING:
    from opendart_mcp.models.ownership import (
        ControlChange,
        Holder,
        InsiderReport,
        MajorHolderReport,
        Minority,
        OwnershipResult,
        OwnershipSnapshot,
        ReportActivity,
    )
    from opendart_mcp.render.capital import Column


def _yes_no(*, value: bool | None) -> str | None:
    """Render a yes/no cell.

    Args:
        value (bool | None): Fact; None when unknown.

    Returns:
        str | None: "yes", "no", or None.
    """
    return None if value is None else ("yes" if value else "no")


def _signed(value: float | None) -> str:
    """Format a change with an explicit sign.

    Args:
        value (float | None): Share change (integer) or percentage-point change; None
            renders as a dash.

    Returns:
        str: Text such as "+6,317" or "-0.14".
    """
    if value is None:
        return MISSING_VALUE
    return f"{value:+,}" if isinstance(value, int) else f"{value:+.2f}"


def _pct(value: float | None) -> str:
    """Format a shareholding percentage with two decimals.

    Args:
        value (float | None): Percentage.

    Returns:
        str: Text such as "19.84%".
    """
    return percent(value, decimals=2)


_HOLDER_COLUMNS: Final[tuple[Column[Holder], ...]] = (
    ("Holder", lambda r: r.name, False),
    ("Relation", lambda r: r.relation, False),
    ("Class", lambda r: class_name(r.share_class), False),
    ("Shares (start)", lambda r: number(r.shares_begin), True),
    ("Shares", lambda r: number(r.shares), True),
    ("% start", lambda r: _pct(r.pct_begin), True),
    ("% end", lambda r: _pct(r.pct_end), True),
    ("Note", lambda r: r.note, False),
)
_CHANGE_COLUMNS: Final[tuple[Column[ControlChange], ...]] = (
    ("Date", lambda r: r.date.isoformat() if r.date else None, False),
    ("New largest shareholder", lambda r: r.new_largest_shareholder, False),
    ("Shares", lambda r: number(r.shares), True),
    ("%", lambda r: _pct(r.pct), True),
    ("Cause", lambda r: r.cause, False),
    ("Note", lambda r: r.note, False),
)
_MAJOR_COLUMNS: Final[tuple[Column[MajorHolderReport], ...]] = (
    ("Filed", lambda r: r.filed.isoformat() if r.filed else None, False),
    ("Reporter", lambda r: r.reporter, False),
    ("Type", lambda r: r.report_type, False),
    ("Shares", lambda r: number(r.shares), True),
    ("Change", lambda r: _signed(r.change_in_shares), True),
    ("%", lambda r: _pct(r.pct), True),
    ("Change (pp)", lambda r: _signed(r.change_in_pct), True),
    ("Contract shares", lambda r: number(r.contract_shares), True),
    ("Reason", lambda r: r.reason, False),
    ("Filing", lambda r: r.filing_number, False),
)
_INSIDER_COLUMNS: Final[tuple[Column[InsiderReport], ...]] = (
    ("Filed", lambda r: r.filed.isoformat() if r.filed else None, False),
    ("Reporter", lambda r: r.reporter, False),
    ("Position", lambda r: r.position, False),
    ("Registered", lambda r: _yes_no(value=r.is_registered_officer), False),
    ("Major holder", lambda r: r.major_shareholder, False),
    ("Shares", lambda r: number(r.shares), True),
    ("Change", lambda r: _signed(r.change), True),
    ("%", lambda r: _pct(r.pct), True),
    ("Change (pp)", lambda r: _signed(r.change_pct), True),
    ("Filing", lambda r: r.filing_number, False),
)


def _control_text(snapshot: OwnershipSnapshot) -> str:
    """Summarize control, share counts, and the free float.

    Args:
        snapshot (OwnershipSnapshot): Control snapshot.

    Returns:
        str: Two or three lines of text.
    """
    kind = class_name(snapshot.share_class)
    begin = (
        f" ({_pct(snapshot.controlling_pct_begin)} at the period start)"
        if snapshot.controlling_pct_begin is not None
        else ""
    )
    lines = [
        f"Largest shareholder: {snapshot.largest_shareholder or MISSING_VALUE}. "
        + f"The group ({snapshot.group_members} holders) owns {number(snapshot.controlling_shares)} "
        + f"{snapshot.share_class} shares, {_pct(snapshot.controlling_pct)}{begin}.",
        f"{kind} shares: {number(snapshot.shares_issued)} issued, "
        + f"{number(snapshot.treasury_shares)} treasury, "
        + f"{number(snapshot.shares_outstanding)} outstanding; "
        + f"free float estimate {_pct(snapshot.free_float_estimate_pct)}.",
    ]
    if snapshot.minority is not None:
        lines.append(_minority_text(snapshot.minority))
    return "\n".join(lines)


def _minority_text(minority: Minority) -> str:
    """Summarize minority shareholders.

    Args:
        minority (Minority): Minority figures.

    Returns:
        str: One line.
    """
    as_of = f" as of {minority.as_of.isoformat()}" if minority.as_of else ""
    return (
        f"Minority shareholders{as_of}: {number(minority.holders)} of "
        + f"{number(minority.total_holders)} holders ({_pct(minority.holder_pct)}) own "
        + f"{number(minority.shares)} shares ({_pct(minority.share_pct)})."
    )


def _activity_text(activity: ReportActivity | None, noun: str) -> str:
    """Summarize holding reports in the window.

    Args:
        activity (ReportActivity | None): Counts, or None while still downloading.
        noun (str): Kind of report, plural.

    Returns:
        str: One line.
    """
    if activity is None:
        return f"The {noun} are still downloading; see the note below."
    if activity.reports == 0:
        return f"No {noun} were filed in the window."
    return (
        f"{activity.reports} in the window ({activity.increases} up, {activity.decreases} down, "
        + f"net {_signed(activity.net_change)} shares); showing the newest {activity.shown}."
    )


def render_ownership(result: OwnershipResult) -> str:
    """Render an ownership result.

    Args:
        result (OwnershipResult): Result to render.

    Returns:
        str: Markdown.
    """
    snapshot = result.snapshot
    period = period_title(result.fiscal_year, result.period, result.period_end)
    since = result.activity_since.isoformat()
    group = snapshot.largest_shareholder_group if snapshot else []
    return join(
        f"**{company_line(result.company)}: ownership and control{period}**",
        _control_text(snapshot) if snapshot else "",
        section("Largest shareholder group", sparse_table(group, _HOLDER_COLUMNS)),
        section(
            "Changes of the largest shareholder",
            sparse_table(result.control_changes, _CHANGE_COLUMNS),
        ),
        section(
            f"5% holder reports since {since}",
            join(
                _activity_text(result.major_holder_activity, "5% holder reports"),
                sparse_table(result.major_holder_reports, _MAJOR_COLUMNS),
            ),
        ),
        section(
            f"Insider reports since {since}",
            join(
                _activity_text(result.insider_activity, "insider reports"),
                sparse_table(result.insider_reports, _INSIDER_COLUMNS),
            ),
        ),
        footer(result),
    )
