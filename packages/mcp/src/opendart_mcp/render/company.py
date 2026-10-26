"""Markdown views of company search results and company profiles."""

from __future__ import annotations

from typing import TYPE_CHECKING

from opendart_mcp.render.markdown import company_line, footer, join, table

if TYPE_CHECKING:
    from opendart_mcp.models.company import (
        CompanyMatch,
        CompanyProfileResult,
        FindCompanyResult,
        PeriodicReportRef,
    )


def _match_line(match: CompanyMatch) -> str:
    """Describe a match in one line.

    Args:
        match (CompanyMatch): Directory match.

    Returns:
        str: Name with codes.
    """
    listing = ", ".join(part for part in (match.stock_code, match.market) if part)
    prefix = f"{listing}; " if listing else ""
    return f"{match.name} ({prefix}DART {match.corp_code})"


def _listing(match: CompanyMatch) -> str:
    """Name the market when known; the directory alone only says whether a company is listed.

    Args:
        match (CompanyMatch): Directory match.

    Returns:
        str: Market such as KOSPI, else ``listed`` or ``unlisted``.
    """
    return match.market or ("listed" if match.listed else "unlisted")


def render_find_company(result: FindCompanyResult) -> str:
    """Render company matches.

    Args:
        result (FindCompanyResult): Search result.

    Returns:
        str: Markdown.
    """
    rows = [
        (m.name, m.korean_name, m.stock_code, _listing(m), m.corp_code, m.match)
        for m in result.matches
    ]
    headers = ("Company", "Korean name", "Stock code", "Listing", "Corp code", "Match")
    if result.best_match is not None:
        verdict = f"Best match: {_match_line(result.best_match)}."
    elif result.matches:
        verdict = "No single match dominates; pass a stock code or corp code to other tools."
    else:
        verdict = ""
    return join(
        f'**Companies matching "{result.query}"**', table(headers, rows), verdict, footer(result)
    )


def _report_line(report: PeriodicReportRef) -> str:
    """Describe the latest periodic report.

    Args:
        report (PeriodicReportRef): Latest report.

    Returns:
        str: One sentence.
    """
    end = f", period end {report.period_end.isoformat()}" if report.period_end else ""
    filed = f", filed {report.filed.isoformat()}" if report.filed else ""
    label = (
        f"FY{report.fiscal_year}"
        if report.period == "FY"
        else f"{report.period} {report.fiscal_year}"
    )
    return f'Latest periodic report: "{report.title}" = {label}{end}{filed} (filing {report.filing_number}). period="latest" refers to it.'


def render_profile(result: CompanyProfileResult) -> str:
    """Render a company profile.

    Args:
        result (CompanyProfileResult): Profile result.

    Returns:
        str: Markdown.
    """
    company, profile = result.company, result.profile
    rows = [
        ("Korean name", company.korean_name),
        ("Short name", profile.stock_name),
        ("CEO", profile.ceo),
        ("Industry code", profile.industry_code),
        ("Fiscal year end", f"month {profile.fiscal_year_end_month}"),
        ("Established", profile.established.isoformat() if profile.established else None),
        ("Address", profile.address),
        ("Website", profile.website),
        ("IR site", profile.ir_url),
        ("Phone", profile.phone),
    ]
    report = result.latest_periodic_report
    return join(
        f"**{company_line(company)}**",
        table(("Field", "Value"), [row for row in rows if row[1]]),
        _report_line(report) if report else "",
        footer(result),
    )
