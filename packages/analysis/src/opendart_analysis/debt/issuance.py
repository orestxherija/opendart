"""Parse the issuance record of debt securities, and list maturities from it.

``det_scrits_isu_acmslt`` lists debt securities issued in the period, sometimes by
subsidiaries, with English security types and methods ("Corporate Bonds", "Public
offering"), Korean redemption statuses (상환 redeemed, 미상환 outstanding, 일부상환 partly
redeemed) as of the period end, ratings such as ``A1(한국기업평가/NICE신용평가)`` or
``AA-(S&P), Aa2(Moody's)``, and a closing total row that is skipped.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal

from opendart_analysis.debt.ladders import offering
from opendart_analysis.domain.normalize import clean_text, parse_amount, parse_date, parse_percent
from opendart_analysis.extracts.fields import fold, is_total, text

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from opendart_analysis.debt.ladders import Offering

ISSUANCE_SERVICE: Final = "det_scrits_isu_acmslt"
"""Service listing debt securities issued in the period."""

Redeemed = Literal["yes", "no", "partly"]
"""Redemption status of an issue as filed."""

Method = Literal["public", "private"]
"""Issuance method."""

_METHODS: Final[dict[Offering, Method]] = {"public": "public", "private": "private"}
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


@dataclass(frozen=True, slots=True)
class Issue:
    """One debt security in the issuance record.

    Attributes:
        issued (dt.date | None): Issue date.
        security (str | None): Security type as filed, such as "Corporate Bonds".
        method (Method | None): Public offering or private placement.
        amount (int | None): Face value in won.
        coupon (float | None): Interest rate in percent.
        rating (str | None): Ratings, joined with "; " when several agencies rate the issue.
        rating_agency (str | None): Agencies, in the same order, Korean names translated.
        maturity (dt.date | None): Maturity date.
        redeemed (Redeemed | None): Redemption status as of the period end.
        issuer (str | None): Issuing company as filed.
        own (bool): Whether the issuer is the reporting company itself, by name.
        underwriter (str | None): Underwriters as filed.
        filing_number (str | None): Periodic report that lists the issue.
    """

    issued: dt.date | None
    security: str | None
    method: Method | None
    amount: int | None
    coupon: float | None
    rating: str | None
    rating_agency: str | None
    maturity: dt.date | None
    redeemed: Redeemed | None
    issuer: str | None
    own: bool
    underwriter: str | None
    filing_number: str | None

    @property
    def other_issuer(self) -> str | None:
        """Name the issuer when another entity, such as a subsidiary, issued the security.

        Returns:
            str | None: The issuer as filed, or None when it is the company or not stated.
        """
        return None if self.own else self.issuer


@dataclass(frozen=True, slots=True)
class Maturity:
    """An issue that falls due, from the issuance record.

    Attributes:
        date (dt.date): Maturity date.
        instrument (str): Security type as filed, or "Debt security".
        face_value (int | None): Original face value in won; partly redeemed issues owe less.
        filing_number (str | None): Periodic report that lists the issue.
        coupon (float | None): Interest rate in percent.
        redeemed (Redeemed | None): ``no`` or ``partly`` as of the period end, or None.
        issuer (str | None): Set when another entity, such as a subsidiary, issued it.
    """

    date: dt.date
    instrument: str
    face_value: int | None
    filing_number: str | None
    coupon: float | None
    redeemed: Redeemed | None
    issuer: str | None


def _method(value: str | None) -> Method | None:
    """Classify an issuance method.

    Args:
        value (str | None): ``isu_mth_nm``, such as "Public offering" or 사모.

    Returns:
        Method | None: Method, or None when not stated.
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


def company_names(names: Iterable[str | None]) -> frozenset[str]:
    """Collect comparable keys of the company's names, to spot issues by other entities.

    Args:
        names (Iterable[str | None]): The company's names, such as its Korean and English
            names.

    Returns:
        frozenset[str]: Non-empty name keys.
    """
    return frozenset(key for key in map(company_key, names) if key)


def issue(row: object, own: frozenset[str]) -> Issue:
    """Normalize one issuance-record row.

    Args:
        row (object): ``det_scrits_isu_acmslt`` record, read by SDK field name.
        own (frozenset[str]): Name keys of the reporting company, from ``company_names``.

    Returns:
        Issue: Normalized issue.
    """
    grade, agency = rating(text(row, "evl_grad_instt"))
    issuer = clean_text(text(row, "isu_cmpny"))
    return Issue(
        issued=parse_date(text(row, "isu_de")),
        security=clean_text(text(row, "scrits_knd_nm")),
        method=_method(text(row, "isu_mth_nm")),
        amount=parse_amount(text(row, "facvalu_totamt")),
        coupon=parse_percent(text(row, "intrt")),
        rating=grade,
        rating_agency=agency,
        maturity=parse_date(text(row, "mtd")),
        redeemed=redeemed(text(row, "repy_at")),
        issuer=issuer,
        own=issuer is not None and company_key(issuer) in own,
        underwriter=clean_text(text(row, "mngt_cmpny")),
        filing_number=clean_text(text(row, "filing_number")),
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


def _order(item: Issue) -> tuple[dt.date, dt.date]:
    """Sort issues by maturity, then issue date, unknown dates last.

    Args:
        item (Issue): Issue.

    Returns:
        tuple[dt.date, dt.date]: Sort key.
    """
    return item.maturity or dt.date.max, item.issued or dt.date.max


def issuance(rows: Sequence[object], own: frozenset[str]) -> tuple[Issue, ...]:
    """Normalize the issuance record, redeemed issues included.

    Args:
        rows (Sequence[object]): ``det_scrits_isu_acmslt`` records.
        own (frozenset[str]): Name keys of the reporting company, from ``company_names``.

    Returns:
        tuple[Issue, ...]: Issues by maturity, then issue date, unknown dates last; ties keep
            the record's order.
    """
    return tuple(sorted((issue(row, own) for row in rows if is_issue(row)), key=_order))


def maturities(
    rows: Sequence[object], own: frozenset[str], *, start: dt.date, until: dt.date
) -> tuple[Maturity, ...]:
    """List issues that mature between two dates and are not fully redeemed.

    Partly redeemed issues keep their original face value, marked by their redemption
    status, because the record does not say how much is left.

    Args:
        rows (Sequence[object]): ``det_scrits_isu_acmslt`` records, possibly from several
            reports; an issue repeated with the same issue date, security type, face value,
            and maturity is listed once, the first report's row winning.
        own (frozenset[str]): Name keys of the reporting company, from ``company_names``.
        start (dt.date): First maturity date to include.
        until (dt.date): Last maturity date to include.

    Returns:
        tuple[Maturity, ...]: Maturities by date, then security type.
    """
    found: dict[tuple[object, ...], Maturity] = {}
    for row in filter(is_issue, rows):
        item = issue(row, own)
        due = item.maturity
        if due is None or not start <= due <= until or item.redeemed == "yes":
            continue
        found.setdefault(
            (item.issued, item.security, item.amount, due),
            Maturity(
                date=due,
                instrument=item.security or "Debt security",
                face_value=item.amount,
                filing_number=item.filing_number,
                coupon=item.coupon,
                redeemed=item.redeemed,
                issuer=item.other_issuer,
            ),
        )
    return tuple(sorted(found.values(), key=lambda m: (m.date, m.instrument)))
