"""Audit facts from periodic reports: auditor, opinion, key audit matters, fees, and flags.

``accnut_adtor_nm_nd_adt_opinion`` lists the auditor and opinion for the current and up to
two prior fiscal years, often twice (consolidated and separate statements), labeled by term
such as ``제57기 (당기)``. Opinions, emphasis paragraphs, and key audit matters are Korean as
filed: 적정의견 is unqualified, 한정 qualified, 부적정 adverse, and 의견거절 a disclaimer;
계속기업 (going concern) marks going-concern language. The two fee services file amounts in
the filing's own unit (often KRW million), which OpenDART omits, so the unit is inferred
from the fee per audit hour.
"""

from __future__ import annotations

import math
import re
from typing import TYPE_CHECKING, Final

from opendart_mcp.domain.normalize import clean_text, parse_amount
from opendart_mcp.models.governance import (
    AuditFacts,
    AuditFee,
    AuditYear,
    GovernanceFlag,
    NonAuditService,
)
from opendart_mcp.services.extracts import filed_text, fold, term_ages, text

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from opendart_mcp.models.governance import Opinion

_OPINIONS: Final[tuple[tuple[Opinion, tuple[str, ...]], ...]] = (
    ("adverse", ("부적정", "adverse")),
    ("disclaimer", ("의견거절", "disclaimer")),
    ("unqualified", ("unqualified",)),
    ("qualified", ("한정", "qualified")),
    ("unqualified", ("적정", "clean")),
)
_SEVERITY: Final[dict[Opinion | None, int]] = {
    None: -1,
    "unqualified": 0,
    "qualified": 1,
    "adverse": 2,
    "disclaimer": 3,
}
_MODIFIED: Final[dict[Opinion | None, str]] = {
    "qualified": "Qualified opinion",
    "adverse": "Adverse opinion",
    "disclaimer": "Disclaimer of opinion",
}
_GOING_CONCERN: Final = ("계속기업", "goingconcern")
_EXCERPT: Final = 200
# Numbered items such as "1. ...2. ..." in key audit matters; "1.5" is not a marker.
_ITEM: Final = re.compile(r"(?:^|(?<=\D))\d{1,2}[.)](?!\d)\s*")
_FEE_PAIRS: Final = (
    ("adt_cntrct_dtls_mendng", "adt_cntrct_dtls_time"),
    ("real_exc_dtls_mendng", "real_exc_dtls_time"),
    ("mendng", "tot_reqre_time"),
)
_SCALES: Final = (1, 1_000, 1_000_000)
_SCALE_NAMES: Final = {1_000: "thousand", 1_000_000: "million"}
# Audit fees run near KRW 100,000 per hour; a filed unit must land within 1.5 decades.
_TYPICAL_RATE: Final = 5.0
_TOLERANCE: Final = 1.5
_AUDITOR_NOISE: Final = re.compile(
    r"회계법인|주식회사|㈜|\(주\)|accounting|corporation|llc|[\s.,()]"
)


def opinion(value: str | None) -> Opinion | None:
    """Classify an audit opinion as filed.

    Args:
        value (str | None): Opinion text, such as 적정의견 or "Qualified opinion".

    Returns:
        Opinion | None: Opinion type, or None when unrecognized.
    """
    folded = fold(value)
    if not folded:
        return None
    return next((kind for kind, words in _OPINIONS if any(w in folded for w in words)), None)


def key_matters(value: str | None) -> list[str]:
    """Split key audit matters into items.

    Args:
        value (str | None): Filed text, usually numbered ("1. ... 2. ...").

    Returns:
        list[str]: Items without their numbers; empty when none are filed.
    """
    cleaned = filed_text(value)
    if cleaned is None:
        return []
    return [item for part in _ITEM.split(cleaned) if (item := part.strip(" ;,"))]


def opinion_rows(records: Sequence[object], fiscal_year: int) -> list[AuditYear]:
    """Parse audit-opinion rows, newest fiscal year first, without duplicate rows.

    Args:
        records (Sequence[object]): ``accnut_adtor_nm_nd_adt_opinion`` records.
        fiscal_year (int): Fiscal year of the report's current term.

    Returns:
        list[AuditYear]: One entry per distinct row.
    """
    ages = term_ages([text(record, "fiscal_year") for record in records])
    years: dict[str, AuditYear] = {}
    for record, age in zip(records, ages, strict=True):
        filed = text(record, "adt_opinion")
        year = AuditYear(
            fiscal_year=fiscal_year - age,
            auditor=filed_text(text(record, "adtor")),
            opinion=opinion(filed),
            opinion_as_filed=filed_text(filed),
            emphasis=filed_text(text(record, "emphs_matter")),
            key_audit_matters=key_matters(text(record, "core_adt_matter")),
            special_matters=filed_text(text(record, "adt_reprt_spcmnt_matter")),
            term_as_filed=clean_text(text(record, "fiscal_year")),
        )
        years.setdefault(year.model_dump_json(), year)
    return sorted(years.values(), key=lambda y: -(y.fiscal_year or 0))


def same_auditor(first: str | None, second: str | None) -> bool | None:
    """Compare two audit firm names, ignoring suffixes such as 회계법인 (accounting firm).

    Args:
        first (str | None): One firm name.
        second (str | None): Other firm name.

    Returns:
        bool | None: Whether they name the same firm; None when either is unknown.
    """
    one, two = (_AUDITOR_NOISE.sub("", (name or "").casefold()) for name in (first, second))
    if not one or not two:
        return None
    return one in two or two in one


def changed(current: str | None, prior: str | None) -> bool | None:
    """Tell whether the auditor changed from the prior fiscal year.

    Args:
        current (str | None): Current auditor.
        prior (str | None): Prior-year auditor.

    Returns:
        bool | None: True for a change; None when either auditor is unknown.
    """
    same = same_auditor(current, prior)
    return None if same is None else not same


def _amounts(record: object, pair: tuple[str, str]) -> tuple[int | None, int | None]:
    """Read a fee and its hours.

    Args:
        record (object): Audit-fee record.
        pair (tuple[str, str]): Fee and hours field names.

    Returns:
        tuple[int | None, int | None]: Fee as filed and hours.
    """
    return parse_amount(text(record, pair[0])), parse_amount(text(record, pair[1]))


def _rate_error(fee: int, hours: int, scale: int) -> float:
    """Measure how far a fee per hour is from typical audit rates, in decades.

    Args:
        fee (int): Fee as filed.
        hours (int): Audit hours.
        scale (int): Won per filed unit to test.

    Returns:
        float: Absolute log10 distance from KRW 100,000 per hour.
    """
    return abs(math.log10(fee * scale / hours) - _TYPICAL_RATE)


def fee_scale(records: Sequence[object]) -> int | None:
    """Infer the won per filed unit of audit fees from the fee per audit hour.

    Args:
        records (Sequence[object]): ``adt_servc_cncls_sttus`` records.

    Returns:
        int | None: 1, 1,000, or 1,000,000; None when no row has both a fee and hours or
            no unit gives a plausible hourly rate.
    """
    found = _fee_and_hours(records)
    if found is None:
        return None
    best = min(_SCALES, key=lambda scale: _rate_error(*found, scale))
    return best if _rate_error(*found, best) <= _TOLERANCE else None


def _fee_and_hours(records: Sequence[object]) -> tuple[int, int] | None:
    """Find the first positive fee filed together with its audit hours.

    Args:
        records (Sequence[object]): ``adt_servc_cncls_sttus`` records.

    Returns:
        tuple[int, int] | None: Fee as filed and hours, or None.
    """
    for record in records:
        for pair in _FEE_PAIRS:
            fee, hours = _amounts(record, pair)
            if fee is not None and hours is not None and min(fee, hours) > 0:
                return fee, hours
    return None


def scale_note(scale: int | None) -> str | None:
    """Explain how audit fees were converted.

    Args:
        scale (int | None): Inferred won per filed unit.

    Returns:
        str | None: Note, or None when fees were filed in won.
    """
    if scale is None:
        return "Audit fees are as filed: OpenDART omits their unit and it could not be inferred."
    name = _SCALE_NAMES.get(scale)
    if name is None:
        return None
    return f"Audit fees are filed without a unit; amounts assume KRW {name} per filed unit, inferred from the fee per audit hour."


def _scaled(value: int | None, scale: int | None) -> int | None:
    """Convert a filed fee to won when the unit is known.

    Args:
        value (int | None): Fee as filed.
        scale (int | None): Won per filed unit, or None to keep the filed number.

    Returns:
        int | None: Fee.
    """
    return None if value is None else value * (scale or 1)


def audit_fees(
    records: Sequence[object], fiscal_year: int, scale: int | None, *, detailed: bool
) -> list[AuditFee]:
    """Parse audit fees and hours by fiscal year.

    Args:
        records (Sequence[object]): ``adt_servc_cncls_sttus`` records.
        fiscal_year (int): Fiscal year of the report's current term.
        scale (int | None): Won per filed fee unit.
        detailed (bool): Whether to keep the work covered.

    Returns:
        list[AuditFee]: Fees, newest fiscal year first.
    """
    ages = term_ages([text(record, "fiscal_year") for record in records])
    fees = []
    for record, age in zip(records, ages, strict=True):
        (fee, hours), (spent, worked), (old_fee, old_hours) = (
            _amounts(record, pair) for pair in _FEE_PAIRS
        )
        fees.append(
            AuditFee(
                fiscal_year=fiscal_year - age,
                auditor=filed_text(text(record, "adtor")),
                contract_fee=_scaled(fee if fee is not None else old_fee, scale),
                contract_hours=hours if hours is not None else old_hours,
                actual_fee=_scaled(spent, scale),
                actual_hours=worked,
                scope=filed_text(text(record, "cn")) if detailed else None,
            )
        )
    return [fee for fee in fees if fee.contract_fee is not None or fee.actual_fee is not None]


def non_audit_services(
    records: Sequence[object], fiscal_year: int, scale: int | None, *, detailed: bool
) -> list[NonAuditService]:
    """Parse non-audit services contracted with the auditor.

    Args:
        records (Sequence[object]): ``accnut_adtor_non_adt_servc_cncls_sttus`` records.
        fiscal_year (int): Fiscal year of the report's current term.
        scale (int | None): Won per filed fee unit, from the audit-fee table.
        detailed (bool): Whether to keep prior fiscal years.

    Returns:
        list[NonAuditService]: Services with a description, date, or fee.
    """
    ages = term_ages([text(record, "fiscal_year") for record in records])
    services = [
        NonAuditService(
            fiscal_year=fiscal_year - age,
            contracted=clean_text(text(record, "cntrct_cncls_de")),
            service=filed_text(text(record, "servc_cn")),
            period=clean_text(text(record, "servc_exc_pd")),
            fee=_scaled(parse_amount(text(record, "servc_mendng")), scale),
            note=filed_text(text(record, "rm")),
        )
        for record, age in zip(records, ages, strict=True)
        if detailed or age == 0
    ]
    return [s for s in services if s.service or s.fee is not None or s.contracted]


def audit_facts(
    history: Sequence[AuditYear],
    fees: Sequence[object],
    services: Sequence[object],
    *,
    fiscal_year: int,
    detailed: bool,
) -> AuditFacts | None:
    """Combine the opinion, fee, and non-audit tables of one report.

    Args:
        history (Sequence[AuditYear]): Parsed opinion rows.
        fees (Sequence[object]): ``adt_servc_cncls_sttus`` records.
        services (Sequence[object]): ``accnut_adtor_non_adt_servc_cncls_sttus`` records.
        fiscal_year (int): Fiscal year of the report's current term.
        detailed (bool): Whether to add history, prior-year services, and filed text.

    Returns:
        AuditFacts | None: Audit facts, or None when all three tables are empty.
    """
    if not (history or fees or services):
        return None
    current = [year for year in history if year.fiscal_year == fiscal_year] or [AuditYear()]
    worst = max(current, key=lambda year: _SEVERITY[year.opinion])
    prior = next(
        (y.auditor for y in history if y.fiscal_year == fiscal_year - 1 and y.auditor), None
    )
    scale = fee_scale(fees)
    return AuditFacts(
        auditor=current[0].auditor,
        opinion=worst.opinion,
        opinion_as_filed=worst.opinion_as_filed,
        emphasis=next((year.emphasis for year in current if year.emphasis), None),
        key_audit_matters=next((y.key_audit_matters for y in current if y.key_audit_matters), []),
        prior_auditor=prior,
        auditor_changed_vs_prior_year=changed(current[0].auditor, prior),
        fees=audit_fees(fees, fiscal_year, scale, detailed=detailed),
        fee_scale=scale,
        non_audit_services=non_audit_services(services, fiscal_year, scale, detailed=detailed),
        history=list(history) if detailed else None,
    )


def _excerpt(texts: Iterable[str | None]) -> str | None:
    """Find the first text with going-concern language.

    Args:
        texts (Iterable[str | None]): Audit-report texts.

    Returns:
        str | None: The text, shortened, or None.
    """
    found = next((t for t in texts if t and any(w in fold(t) for w in _GOING_CONCERN)), None)
    if found is None or len(found) <= _EXCERPT:
        return found
    return found[:_EXCERPT].rstrip() + "..."


def audit_flags(
    facts: AuditFacts, history: Sequence[AuditYear], *, fiscal_year: int, label: str
) -> list[GovernanceFlag]:
    """Flag a modified opinion, going-concern language, and an auditor change.

    Args:
        facts (AuditFacts): Audit facts for the report.
        history (Sequence[AuditYear]): Parsed opinion rows.
        fiscal_year (int): Fiscal year of the report's current term.
        label (str): Period label for messages, such as FY2025.

    Returns:
        list[GovernanceFlag]: Flags, possibly empty.
    """
    flags = []
    name = _MODIFIED.get(facts.opinion)
    if name is not None:
        detail = f"{name} for {label}, filed as {facts.opinion_as_filed}."
        flags.append(GovernanceFlag(kind="modified_opinion", detail=detail))
    current = [year for year in history if year.fiscal_year == fiscal_year]
    texts = (
        item
        for year in current
        for item in (
            year.opinion_as_filed,
            year.emphasis,
            year.special_matters,
            *year.key_audit_matters,
        )
    )
    excerpt = _excerpt(texts)
    if excerpt is not None:
        detail = f"Going-concern language in the {label} audit report: {excerpt}"
        flags.append(GovernanceFlag(kind="going_concern", detail=detail))
    if facts.auditor_changed_vs_prior_year:
        detail = f"Auditor changed from {facts.prior_auditor} to {facts.auditor}."
        flags.append(GovernanceFlag(kind="auditor_change", detail=detail))
    return flags
