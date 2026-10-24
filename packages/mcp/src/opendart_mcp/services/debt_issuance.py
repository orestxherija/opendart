"""Parse the issuance record of debt securities, and list upcoming maturities from it.

``det_scrits_isu_acmslt`` lists debt securities issued in the period, sometimes by
subsidiaries, with English security types and methods ("Corporate Bonds", "Public
offering"), Korean redemption statuses (상환 redeemed, 미상환 outstanding, 일부상환 partly
redeemed) as of the period end, ratings such as ``A1(한국기업평가/NICE신용평가)`` or
``AA-(S&P), Aa2(Moody's)``, and a closing total row that is skipped.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import TYPE_CHECKING, Final, Literal

from opendart_analysis.domain.normalize import clean_text, parse_amount, parse_date, parse_percent
from opendart_mcp.models.debt import DebtMaturity, Issuance
from opendart_mcp.services.debt_tables import offering
from opendart_mcp.services.extracts import fold, is_total, text

if TYPE_CHECKING:
    from collections.abc import Sequence

    from opendart_mcp.models.debt import Redeemed
    from opendart_mcp.services.debt_tables import Offering

ISSUANCE_SERVICE: Final = "det_scrits_isu_acmslt"
"""Service listing debt securities issued in the period."""

_METHODS: Final[dict[Offering, Literal["public", "private"]]] = {
    "public": "public",
    "private": "private",
}
_REDEMPTIONS: Final[tuple[tuple[Redeemed, tuple[str, ...]], ...]] = (
    ("partly", ("일부", "partial", "partly")),
    ("no", ("미상환", "unredeemed", "notredeemed", "outstanding")),
    ("yes", ("상환", "redeemed", "repaid")),
)
_AGENCIES: Final = {
    "한국기업평가": "Korea Ratings",
    "nice신용평가": "NICE Investors Service",
    "나이스신용평가": "NICE Investors Service",
    "한국신용평가": "Korea Investors Service",
    "서울신용평가": "Seoul Credit Rating",
}
_RATING: Final = re.compile(r"([^,;()]+?)\s*\(([^()]*)\)")
_AGENCY_SEPARATORS: Final = re.compile(r"\s*[/,]\s*")
_CORPORATE_MARKERS: Final = re.compile(
    r"㈜|\(주\)|주식회사|co\.?,?\s*ltd\.?|corporation|corp\.?|inc\.?"
)


def _method(value: str | None) -> Literal["public", "private"] | None:
    """Classify an issuance method.

    Args:
        value (str | None): ``isu_mth_nm``, such as "Public offering" or 사모.

    Returns:
        Literal["public", "private"] | None: Method, or None when not stated.
    """
    kind = offering(value)
    return None if kind is None else _METHODS.get(kind)


def redeemed(value: str | None) -> Redeemed | None:
    """Classify a redemption status.

    Args:
        value (str | None): ``repy_at``, such as 상환, 미상환, or 일부상환.

    Returns:
        Redeemed | None: yes, no, partly, or None when unrecognized.
    """
    folded = fold(value)
    return next((kind for kind, words in _REDEMPTIONS if any(w in folded for w in words)), None)


def _agency(value: str) -> str:
    """Translate Korean rating-agency names, keeping others as filed.

    Args:
        value (str): One or more agencies separated by slashes or commas.

    Returns:
        str: Agencies joined with commas.
    """
    names = [name for name in _AGENCY_SEPARATORS.split(value.strip()) if name]
    return ", ".join(_AGENCIES.get(fold(name), name) for name in names)


def rating(value: str | None) -> tuple[str | None, str | None]:
    """Split a filed rating such as ``AA-(S&P), Aa2(Moody's)`` into ratings and agencies.

    Args:
        value (str | None): ``evl_grad_instt``.

    Returns:
        tuple[str | None, str | None]: Ratings and agencies, each joined with "; " when
            several agencies rate the issue.
    """
    cleaned = clean_text(value)
    if cleaned is None:
        return None, None
    pairs = _RATING.findall(cleaned)
    if not pairs:
        return cleaned, None
    grades = "; ".join(grade.strip() for grade, _ in pairs)
    return grades, "; ".join(_agency(agency) for _, agency in pairs)


def company_key(name: str | None) -> str:
    """Reduce a company name to a comparable key without corporate suffixes.

    Args:
        name (str | None): Korean or English company name.

    Returns:
        str: Key; empty for None.
    """
    return fold(_CORPORATE_MARKERS.sub("", (name or "").casefold())).strip(".,")


def _issuer(value: str | None, names: frozenset[str], *, detailed: bool) -> str | None:
    """Name the issuer when it is not the company itself.

    Args:
        value (str | None): ``isu_cmpny``.
        names (frozenset[str]): Company keys of the reporting company.
        detailed (bool): Whether to name the issuer even when it is the company.

    Returns:
        str | None: Issuer as filed, or None.
    """
    cleaned = clean_text(value)
    if cleaned is None or (not detailed and company_key(cleaned) in names):
        return None
    return cleaned


def issue(row: object, names: frozenset[str], *, detailed: bool) -> Issuance:
    """Normalize one issuance-record row.

    Args:
        row (object): ``det_scrits_isu_acmslt`` record.
        names (frozenset[str]): Company keys of the reporting company.
        detailed (bool): Whether to add the underwriter and always name the issuer.

    Returns:
        Issuance: Normalized issue.
    """
    grade, agency = rating(text(row, "evl_grad_instt"))
    return Issuance(
        issued=parse_date(text(row, "isu_de")),
        security=clean_text(text(row, "scrits_knd_nm")),
        method=_method(text(row, "isu_mth_nm")),
        amount=parse_amount(text(row, "facvalu_totamt")),
        coupon=parse_percent(text(row, "intrt")),
        rating=grade,
        rating_agency=agency,
        maturity=parse_date(text(row, "mtd")),
        redeemed=redeemed(text(row, "repy_at")),
        issuer=_issuer(text(row, "isu_cmpny"), names, detailed=detailed),
        underwriter=clean_text(text(row, "mngt_cmpny")) if detailed else None,
    )


def is_issue(row: object) -> bool:
    """Tell an issued security from the record's total row and blank rows.

    Args:
        row (object): ``det_scrits_isu_acmslt`` record.

    Returns:
        bool: True when the row describes an issue.
    """
    if is_total(text(row, "isu_cmpny")):
        return False
    fields = ("isu_de", "scrits_knd_nm", "facvalu_totamt", "mtd")
    return any(clean_text(text(row, name)) for name in fields)


def _order(item: Issuance) -> tuple[dt.date, dt.date]:
    """Sort issues by maturity, then issue date, unknown dates last.

    Args:
        item (Issuance): Issue.

    Returns:
        tuple[dt.date, dt.date]: Sort key.
    """
    return item.maturity or dt.date.max, item.issued or dt.date.max


def issuance(
    rows: Sequence[object], names: frozenset[str], *, detailed: bool
) -> tuple[list[Issuance], int]:
    """Normalize the issuance record; concise results keep issues not fully redeemed.

    Args:
        rows (Sequence[object]): ``det_scrits_isu_acmslt`` records.
        names (frozenset[str]): Company keys of the reporting company.
        detailed (bool): Whether to keep redeemed issues and every field.

    Returns:
        tuple[list[Issuance], int]: Issues by maturity, and how many redeemed ones were left
            out.
    """
    issues = sorted((issue(r, names, detailed=detailed) for r in rows if is_issue(r)), key=_order)
    if detailed:
        return issues, 0
    kept = [item for item in issues if item.redeemed != "yes"]
    return kept, len(issues) - len(kept)


def maturities(
    rows: Sequence[object], names: frozenset[str], *, start: dt.date, until: dt.date
) -> list[DebtMaturity]:
    """List issues that mature between two dates and are not fully redeemed.

    Partly redeemed issues keep their original face value, marked by their redemption
    status, because the record does not say how much is left.

    Args:
        rows (Sequence[object]): ``det_scrits_isu_acmslt`` records, possibly from several
            reports; repeated issues are listed once, the first report's row winning.
        names (frozenset[str]): Company keys of the reporting company.
        start (dt.date): First maturity date to include.
        until (dt.date): Last maturity date to include.

    Returns:
        list[DebtMaturity]: Maturities, earliest first.
    """
    found: dict[tuple[object, ...], DebtMaturity] = {}
    for row in filter(is_issue, rows):
        item = issue(row, names, detailed=False)
        due = item.maturity
        if due is None or not start <= due <= until or item.redeemed == "yes":
            continue
        found.setdefault(
            (item.issued, item.security, item.amount, due),
            DebtMaturity(
                date=due,
                instrument=item.security or "Debt security",
                face_value=item.amount,
                filing_number=clean_text(text(row, "filing_number")),
                coupon=item.coupon,
                redeemed=item.redeemed,
                issuer=item.issuer,
            ),
        )
    return sorted(found.values(), key=lambda m: (m.date, m.instrument))
