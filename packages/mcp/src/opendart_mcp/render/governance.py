"""Markdown view of governance facts: flags, audit, board, executives, pay, and employees."""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from opendart_mcp.render.markdown import (
    amount,
    company_line,
    footer,
    join,
    number,
    percent,
    section,
    table,
    unit_note,
)

if TYPE_CHECKING:
    from opendart_mcp.domain.types import Unit
    from opendart_mcp.models.governance import (
        AuditFacts,
        BoardFacts,
        Compensation,
        Employees,
        Executive,
        GovernanceResult,
        PayGroup,
        PersonPay,
    )

UNIT: Final[Unit] = "million_krw"


def _period(result: GovernanceResult) -> str:
    """Describe the reporting period.

    Args:
        result (GovernanceResult): Governance facts.

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
    end = f" (period end {result.period_end.isoformat()})" if result.period_end else ""
    return f"Period: {label}{end}. {unit_note(UNIT)}"


def _fee(value: int | None, scale: int | None) -> str:
    """Format an audit fee, in KRW million when its unit is known.

    Args:
        value (int | None): Fee in won, or as filed when the unit is unknown.
        scale (int | None): Inferred won per filed unit; None means as filed.

    Returns:
        str: Formatted fee.
    """
    return number(value) if scale is None else amount(value, UNIT)


def _audit(audit: AuditFacts | None) -> str:
    """Render the audit section.

    Args:
        audit (AuditFacts | None): Audit facts.

    Returns:
        str: Markdown block, or an empty string.
    """
    if audit is None:
        return ""
    opinion = audit.opinion or "not classified"
    filed = f" ({audit.opinion_as_filed})" if audit.opinion_as_filed else ""
    prior = f"; prior year {audit.prior_auditor}" if audit.prior_auditor else ""
    lines = [
        f"Auditor: {audit.auditor or "-"}{prior}. Opinion: {opinion}{filed}.",
        f"Emphasis of matter: {audit.emphasis or "none"}.",
        *(f"{i}. {item}" for i, item in enumerate(audit.key_audit_matters, 1)),
    ]
    if audit.key_audit_matters:
        lines.insert(2, "Key audit matters:")
    fee_rows = [
        (
            f.fiscal_year,
            f.auditor,
            _fee(f.contract_fee, audit.fee_scale),
            number(f.contract_hours),
            _fee(f.actual_fee, audit.fee_scale),
            number(f.actual_hours),
        )
        for f in audit.fees
    ]
    fee_headers = ("Fiscal year", "Auditor", "Contract fee", "Hours", "Actual fee", "Hours")
    service_rows = [
        (s.fiscal_year, s.contracted, s.service, s.period, _fee(s.fee, audit.fee_scale), s.note)
        for s in audit.non_audit_services
    ]
    service_headers = ("Fiscal year", "Contracted", "Service", "Period", "Fee", "Note")
    history = [
        (y.fiscal_year, y.auditor, y.opinion, y.opinion_as_filed, y.emphasis)
        for y in audit.history or ()
    ]
    history_headers = ("Fiscal year", "Auditor", "Opinion", "As filed", "Emphasis")
    return join(
        "\n".join(lines),
        table(fee_headers, fee_rows, numeric=(2, 3, 4, 5)),
        section("Non-audit services", table(service_headers, service_rows, numeric=(4,))),
        section("Opinion history", table(history_headers, history)),
    )


def _board(board: BoardFacts | None) -> str:
    """Render the board section.

    Args:
        board (BoardFacts | None): Board facts.

    Returns:
        str: One paragraph, or an empty string.
    """
    if board is None:
        return ""
    share = f" ({percent(board.outside_director_pct)})" if board.outside_director_pct else ""
    return (
        f"Directors: {number(board.directors)}; outside directors: {number(board.outside_directors)}{share}. "
        + f"Outside directors appointed {number(board.outside_appointed)}, dismissed {number(board.outside_dismissed)}, "
        + f"left early {number(board.outside_resigned_early)}."
    )


def _yes_no(*, value: bool | None) -> str | None:
    """Spell out a yes/no value.

    Args:
        value (bool | None): Value.

    Returns:
        str | None: "yes", "no", or None.
    """
    return None if value is None else ("yes" if value else "no")


def _executives(people: list[Executive] | None) -> str:
    """Render the executives section.

    Args:
        people (list[Executive] | None): Executives.

    Returns:
        str: Table, or an empty string.
    """
    rows = [
        (
            p.name,
            p.position,
            p.role,
            _yes_no(value=p.full_time),
            p.responsibilities,
            p.term_ends.isoformat() if p.term_ends else None,
        )
        for p in people or ()
    ]
    headers = ("Name", "Position", "Role", "Full-time", "Responsibilities", "Term ends")
    return table(headers, rows)


def _groups(groups: list[PayGroup]) -> str:
    """Tabulate pay by group.

    Args:
        groups (list[PayGroup]): Pay groups.

    Returns:
        str: Table, or an empty string.
    """
    rows = [
        (g.category, number(g.headcount), amount(g.total, UNIT), amount(g.average, UNIT))
        for g in groups
    ]
    return table(("Category", "Headcount", "Total", "Average"), rows, numeric=(1, 2, 3))


def _people(people: list[PersonPay]) -> str:
    """Tabulate individual pay.

    Args:
        people (list[PersonPay]): People.

    Returns:
        str: Table, or an empty string.
    """
    rows = [(p.name, p.position, amount(p.total, UNIT), p.not_in_total) for p in people]
    return table(("Name", "Position", "Total", "Pay outside the total"), rows, numeric=(2,))


def _compensation(pay: Compensation | None) -> str:
    """Render the compensation section.

    Args:
        pay (Compensation | None): Pay facts.

    Returns:
        str: Markdown block, or an empty string.
    """
    if pay is None:
        return ""
    summary = (
        f"Approved ceiling {amount(pay.approved_cap, UNIT)}; paid {amount(pay.paid_total, UNIT)} "
        + f"to {number(pay.headcount)} directors and auditors (average {amount(pay.average, UNIT)})."
    )
    extra = pay.unregistered_executives
    return join(
        summary,
        _groups(pay.by_type),
        section(
            "Directors and auditors paid KRW 500 million or more", _people(pay.directors_over_500m)
        ),
        section("Top paid (KRW 500 million or more)", _people(pay.top_paid)),
        section("Unregistered executives", _groups([extra]) if extra else ""),
    )


def _employees(staff: Employees | None) -> str:
    """Render the employees section.

    Args:
        staff (Employees | None): Workforce facts.

    Returns:
        str: Markdown block, or an empty string.
    """
    if staff is None:
        return ""
    tenure = number(staff.average_tenure_years, decimals=1)
    summary = (
        f"Employees {number(staff.total)} (fixed-term {number(staff.fixed_term)}); "
        + f"total salary {amount(staff.total_salary, UNIT)}; average salary "
        + f"{amount(staff.average_salary, UNIT)}; average tenure {tenure} years."
    )
    rows = [
        (
            g.division,
            g.gender,
            number(g.permanent),
            number(g.fixed_term),
            number(g.total),
            number(g.average_tenure_years, decimals=1),
            amount(g.total_salary, UNIT),
            amount(g.average_salary, UNIT),
        )
        for g in staff.groups
    ]
    headers = (
        "Division",
        "Gender",
        "Permanent",
        "Fixed-term",
        "Total",
        "Tenure (years)",
        "Total salary",
        "Average salary",
    )
    return join(summary, table(headers, rows, numeric=range(2, 8)))


def render_governance(result: GovernanceResult) -> str:
    """Render governance facts.

    Args:
        result (GovernanceResult): Governance facts.

    Returns:
        str: Markdown.
    """
    flags = "\n".join(f"- {flag.kind}: {flag.detail}" for flag in result.flags)
    return join(
        f"**Governance: {company_line(result.company)}**",
        _period(result),
        section("Flags", flags),
        section("Audit", _audit(result.audit)),
        section("Board", _board(result.board)),
        section("Executives", _executives(result.executives)),
        section("Compensation", _compensation(result.compensation)),
        section("Employees", _employees(result.employees)),
        footer(result),
    )
