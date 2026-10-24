"""Board, executives, and employees from periodic reports.

``outcmpny_drctr_nd_change_sttus`` gives board size, outside directors, and outside-director
changes in the period. ``exctv_sttus`` lists executives with English board roles ("Executive
Directors", "Outside Director") and full-time status, but Korean names, titles, duties, and
careers; duty lists use ``ㆍ`` bullets. ``emp_sttus`` gives headcount and pay by business
division and gender, with subtotal rows such as 성별합계 (total by gender); salaries arrive
in won and average tenure in years.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Final

from opendart_analysis.domain.normalize import clean_text, parse_amount, parse_date, parse_decimal
from opendart_analysis.extracts.fields import filed_text, fold, is_total, sum_known, text
from opendart_analysis.governance.values import BoardFacts, EmployeeGroup, Employees, Executive

if TYPE_CHECKING:
    from collections.abc import Sequence

    from opendart_analysis.governance.values import Role

_BOARD_FIELDS: Final = ("drctr_co", "otcmp_drctr_co", "apnt", "rlsofc", "mdstrm_resig")
_ROLES: Final[tuple[tuple[Role, tuple[str, ...]], ...]] = (
    ("unregistered", ("unregistered", "non-registered", "nonregistered", "미등기")),
    ("outside_director", ("outside", "independent", "사외")),
    ("non_executive_director", ("non-executive", "nonexecutive", "기타비상무")),
    ("auditor", ("auditor", "감사")),
    ("executive_director", ("executive", "inside", "사내", "등기")),
)
_PART_TIME: Final = ("part-time", "parttime", "비상근", "non-standing", "nonstanding")
_FULL_TIME: Final = ("full-time", "fulltime", "상근", "standing")
_GENDERS: Final = (("female", ("female", "여")), ("male", ("male", "남")))
_SUBTOTALS: Final = ("합계", "소계", "총계", "전체", "total")
# Hangul araea, middle dot, and bullet: the separators of duty and career lists.
_BULLETS: Final = re.compile("[ㆍ·•]")
_BIRTH: Final = re.compile(r"((?:19|20)\d{2})\D{0,3}(\d{1,2})")
_MONTHS: Final = range(1, 13)


def board(records: Sequence[object]) -> BoardFacts | None:
    """Read board size and outside-director changes.

    Args:
        records (Sequence[object]): ``outcmpny_drctr_nd_change_sttus`` records.

    Returns:
        BoardFacts | None: Board facts from the first filled row, or None.
    """
    row = next((r for r in records if any(clean_text(text(r, f)) for f in _BOARD_FIELDS)), None)
    if row is None:
        return None
    directors = parse_amount(text(row, "drctr_co"))
    outside = parse_amount(text(row, "otcmp_drctr_co"))
    share = round(outside / directors * 100, 1) if directors and outside is not None else None
    return BoardFacts(
        directors=directors,
        outside_directors=outside,
        outside_director_pct=share,
        outside_appointed=parse_amount(text(row, "apnt")),
        outside_dismissed=parse_amount(text(row, "rlsofc")),
        outside_resigned_early=parse_amount(text(row, "mdstrm_resig")),
    )


def role(value: str | None) -> Role | None:
    """Classify a board role as filed.

    Args:
        value (str | None): ``rgist_exctv_at``, such as "Outside Director" or 사내이사.

    Returns:
        Role | None: Role, or None when unrecognized.
    """
    folded = fold(value)
    if not folded:
        return None
    return next((kind for kind, words in _ROLES if any(w in folded for w in words)), None)


def full_time(value: str | None) -> bool | None:
    """Read full-time status.

    Args:
        value (str | None): ``fte_at``, such as "Full-time" or 비상근 (part-time).

    Returns:
        bool | None: True for full-time, False for part-time, None when unstated.
    """
    folded = fold(value)
    if any(word in folded for word in _PART_TIME):
        return False
    return True if any(word in folded for word in _FULL_TIME) else None


def bullets(value: str | None) -> str | None:
    """Turn a bulleted list into one line of items separated by semicolons.

    Args:
        value (str | None): Text with ``ㆍ`` bullets and line breaks.

    Returns:
        str | None: Items joined with "; ", or None when empty.
    """
    cleaned = filed_text(value)
    if cleaned is None:
        return None
    return "; ".join(item for part in _BULLETS.split(cleaned) if (item := part.strip())) or None


def born(value: str | None) -> str | None:
    """Format a birth year and month as YYYY-MM.

    Args:
        value (str | None): ``birth_ym``, such as ``1960.12``.

    Returns:
        str | None: Year and month, or None when unreadable.
    """
    match = _BIRTH.search(value or "")
    if match is None or int(match.group(2)) not in _MONTHS:
        return None
    return f"{match.group(1)}-{int(match.group(2)):02d}"


def gender(value: str | None) -> str | None:
    """Name a gender in English; totals have none.

    Args:
        value (str | None): ``sexdstn``, such as "Male", 여, or 합계.

    Returns:
        str | None: male, female, the value as filed, or None for totals and blanks.
    """
    cleaned = filed_text(value)
    if cleaned is None or is_subtotal(cleaned):
        return None
    folded = fold(cleaned)
    return next((name for name, words in _GENDERS if any(w in folded for w in words)), cleaned)


def is_subtotal(value: str | None) -> bool:
    """Tell whether a division or gender label marks a subtotal, such as 성별합계.

    Args:
        value (str | None): Label.

    Returns:
        bool: True for total and subtotal labels.
    """
    folded = fold(value)
    return is_total(value) or any(word in folded for word in _SUBTOTALS)


def executive(record: object) -> Executive:
    """Normalize one executive.

    Args:
        record (object): ``exctv_sttus`` record.

    Returns:
        Executive: Executive with personal details and career.
    """
    filed_role = clean_text(text(record, "rgist_exctv_at"))
    return Executive(
        name=clean_text(text(record, "nm")) or "",
        position=clean_text(text(record, "ofcps")),
        role=role(filed_role),
        full_time=full_time(text(record, "fte_at")),
        responsibilities=bullets(text(record, "chrg_job")),
        term_ends=parse_date(text(record, "tenure_end_on")),
        gender=gender(text(record, "sexdstn")),
        born=born(text(record, "birth_ym")),
        career=bullets(text(record, "main_career")),
        largest_shareholder_relation=filed_text(text(record, "mxmm_shrholdr_relate")),
        tenure=filed_text(text(record, "hffc_pd")),
        role_as_filed=filed_role,
    )


def executives(records: Sequence[object]) -> list[Executive]:
    """List the named executives, registered and unregistered, in filing order.

    Args:
        records (Sequence[object]): ``exctv_sttus`` records.

    Returns:
        list[Executive]: Executives; rows without a name are skipped.
    """
    return [executive(r) for r in records if clean_text(text(r, "nm"))]


def _first(*values: int | None) -> int | None:
    """Pick the first filed value.

    Args:
        values (int | None): Candidate values in order of preference.

    Returns:
        int | None: First value that is not None.
    """
    return next((v for v in values if v is not None), None)


def _group(record: object) -> EmployeeGroup:
    """Normalize one workforce row.

    Args:
        record (object): ``emp_sttus`` record.

    Returns:
        EmployeeGroup: Row; the pre-2016 headcount columns fill in when the current ones are
            blank.
    """
    division = clean_text(text(record, "fo_bbm"))
    filed_gender = text(record, "sexdstn")
    tenure = parse_decimal(text(record, "avrg_cnwk_sdytrn"))
    count = parse_amount
    return EmployeeGroup(
        division=division,
        gender=gender(filed_gender),
        subtotal=True if is_subtotal(division) or is_subtotal(filed_gender) else None,
        permanent=_first(
            count(text(record, "rgllbr_co")), count(text(record, "reform_bfe_emp_co_rgllbr"))
        ),
        fixed_term=_first(
            count(text(record, "cnttk_co")), count(text(record, "reform_bfe_emp_co_cnttk"))
        ),
        total=count(text(record, "sm")),
        average_tenure_years=None if tenure is None else float(tenure),
        total_salary=count(text(record, "fyer_salary_totamt")),
        average_salary=count(text(record, "jan_salary_am")),
    )


def headline(groups: Sequence[EmployeeGroup]) -> list[EmployeeGroup]:
    """Choose the rows that add up to the whole workforce.

    A grand-total row wins; otherwise subtotal rows (such as one per gender); otherwise
    every row.

    Args:
        groups (Sequence[EmployeeGroup]): Workforce rows.

    Returns:
        list[EmployeeGroup]: Rows to add.
    """
    subtotals = [group for group in groups if group.subtotal]
    grand = [group for group in subtotals if group.gender is None]
    return grand[:1] or subtotals or list(groups)


def _average_salary(rows: Sequence[EmployeeGroup]) -> int | None:
    """Average salary over the average headcount each row's figures imply.

    Filers divide total salary by the average headcount of the year, not the year-end
    headcount, so rows are weighted the same way.

    Args:
        rows (Sequence[EmployeeGroup]): Headline rows.

    Returns:
        int | None: Average salary in won, or None.
    """
    pairs = [
        (r.total_salary, r.average_salary) for r in rows if r.total_salary and r.average_salary
    ]
    if len(pairs) == 1:
        return pairs[0][1]
    heads = sum(total / average for total, average in pairs)
    return round(sum(total for total, _ in pairs) / heads) if heads else None


def _average_tenure(rows: Sequence[EmployeeGroup]) -> float | None:
    """Headcount-weighted average tenure.

    Args:
        rows (Sequence[EmployeeGroup]): Headline rows.

    Returns:
        float | None: Years, one decimal, or None.
    """
    pairs = [(r.average_tenure_years, r.total) for r in rows if r.total]
    known = [(years, count) for years, count in pairs if years is not None and count]
    weight = sum(count for _, count in known)
    return round(sum(years * count for years, count in known) / weight, 1) if weight else None


def employees(records: Sequence[object]) -> Employees | None:
    """Summarize the workforce from its headline rows.

    Args:
        records (Sequence[object]): ``emp_sttus`` records.

    Returns:
        Employees | None: Totals and every row with figures, or None when no row has any.
    """
    groups = [g for g in map(_group, records) if g.total is not None or g.total_salary]
    if not groups:
        return None
    rows = headline(groups)
    return Employees(
        total=sum_known(row.total for row in rows),
        fixed_term=sum_known(row.fixed_term for row in rows),
        total_salary=sum_known(row.total_salary for row in rows),
        average_salary=_average_salary(rows),
        average_tenure_years=_average_tenure(rows),
        groups=tuple(groups),
    )
