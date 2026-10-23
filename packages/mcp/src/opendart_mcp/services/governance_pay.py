"""Director, auditor, and executive pay from periodic reports.

Six tables describe pay: the shareholder-approved ceiling by director category (Korean
categories with a 계 total row), the total paid to all directors and auditors, the total by
category (English categories such as "Outside director (excluding members of the audit
committee)"), individual directors and auditors paid KRW 500 million or more, the five
highest-paid people over KRW 500 million, and unregistered executives. Amounts arrive in
won. The Ver 2.0 individual services nest people under ``group`` with stock-based pay
details; the caller prefers them and falls back to Ver 1.0 rows, which read the same way
here. Tables that cover several fiscal years (``fscl_year``) keep the newest.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from opendart_mcp.domain.normalize import clean_text, parse_amount
from opendart_mcp.models.governance import Compensation, PayGroup, PersonPay
from opendart_mcp.services.extracts import filed_text, is_total, term_ages, text

if TYPE_CHECKING:
    from collections.abc import Sequence


@dataclass(frozen=True, slots=True)
class PayTables:
    """The pay tables of one periodic report.

    Attributes:
        approved (Sequence[object]): Shareholder-approved ceiling by category.
        paid (Sequence[object]): Total paid to all directors and auditors.
        by_type (Sequence[object]): Total paid by category.
        directors (Sequence[object]): Directors and auditors paid KRW 500 million or more.
        top (Sequence[object]): Five highest-paid people over KRW 500 million.
        unregistered (Sequence[object]): Unregistered executives.
    """

    approved: Sequence[object] = ()
    paid: Sequence[object] = ()
    by_type: Sequence[object] = ()
    directors: Sequence[object] = ()
    top: Sequence[object] = ()
    unregistered: Sequence[object] = ()


def newest(records: Sequence[object]) -> list[object]:
    """Keep the rows of the newest fiscal year in a multi-year table.

    Args:
        records (Sequence[object]): Records with an optional ``fscl_year`` field.

    Returns:
        list[object]: Rows of the newest year; all rows when years are not filed.
    """
    ages = term_ages([text(record, "fscl_year") for record in records])
    return [record for record, age in zip(records, ages, strict=True) if age == 0]


def _approved(records: Sequence[object]) -> int | None:
    """Read the approved ceiling: the total row, or the sum of the category rows.

    Args:
        records (Sequence[object]): ``drctr_adt_all_mendng_sttus_gmtsck_confm_amount`` records.

    Returns:
        int | None: Ceiling in won, or None.
    """
    rows = newest(records)
    totals = [row for row in rows if is_total(text(row, "se"))]
    amounts = [parse_amount(text(row, "gmtsck_confm_amount")) for row in totals or rows]
    known = [amount for amount in amounts if amount is not None]
    return sum(known) if known else None


def _group(row: object, fields: tuple[str, str, str], *, detailed: bool) -> PayGroup:
    """Read a pay group.

    Args:
        row (object): Pay record.
        fields (tuple[str, str, str]): Headcount, total, and average field names.
        detailed (bool): Whether to keep stock-based pay and notes.

    Returns:
        PayGroup: Group.
    """
    headcount, total, average = fields
    return PayGroup(
        category=clean_text(text(row, "se")),
        headcount=parse_amount(text(row, headcount)),
        total=parse_amount(text(row, total)),
        average=parse_amount(text(row, average)),
        stock_based=parse_amount(text(row, "stk_bsd_pd_mendng_totamt")) if detailed else None,
        note=filed_text(text(row, "rm")) if detailed else None,
    )


def _by_type(records: Sequence[object], *, detailed: bool) -> list[PayGroup]:
    """Read pay by director category, without total rows and empty categories.

    Args:
        records (Sequence[object]): ``drctr_adt_all_mendng_sttus_mendng_pymntamt_ty_cl`` records.
        detailed (bool): Whether to keep stock-based pay and notes.

    Returns:
        list[PayGroup]: Categories with figures.
    """
    fields = ("nmpr", "pymnt_totamt", "psn1_avrg_pymntamt")
    groups = [
        _group(row, fields, detailed=detailed)
        for row in newest(records)
        if not is_total(text(row, "se"))
    ]
    return [g for g in groups if g.headcount is not None or g.total is not None]


def people(records: Sequence[object], *, detailed: bool) -> list[PersonPay]:
    """Read individual pay, highest first.

    Args:
        records (Sequence[object]): Ver 2.0 ``group`` items or Ver 1.0 ``list`` records.
        detailed (bool): Whether to keep pay outside the total, as filed.

    Returns:
        list[PersonPay]: People with a name.
    """
    found = [
        PersonPay(
            name=name,
            position=clean_text(text(row, "ofcps")),
            total=parse_amount(text(row, "mendng_totamt")),
            not_in_total=filed_text(text(row, "mendng_totamt_ct_incls_mendng"))
            if detailed
            else None,
        )
        for row in newest(records)
        if (name := clean_text(text(row, "nm")))
    ]
    return sorted(found, key=lambda person: -(person.total or 0))


def compensation(tables: PayTables, *, detailed: bool) -> Compensation | None:
    """Combine the pay tables of one report.

    Args:
        tables (PayTables): Pay records.
        detailed (bool): Whether to keep stock-based pay, notes, and filed remarks.

    Returns:
        Compensation | None: Pay facts, or None when every table is empty.
    """
    paid = next(iter(newest(tables.paid)), None)
    unregistered = next(iter(newest(tables.unregistered)), None)
    result = Compensation(
        approved_cap=_approved(tables.approved),
        paid_total=parse_amount(text(paid, "mendng_totamt")),
        headcount=parse_amount(text(paid, "nmpr")),
        average=parse_amount(text(paid, "jan_avrg_mendng_am")),
        by_type=_by_type(tables.by_type, detailed=detailed),
        directors_over_500m=people(tables.directors, detailed=detailed),
        top_paid=people(tables.top, detailed=detailed),
        unregistered_executives=None
        if unregistered is None
        else _group(
            unregistered, ("nmpr", "fyer_salary_totamt", "jan_salary_am"), detailed=detailed
        ),
    )
    return None if result == Compensation() else result
