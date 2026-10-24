"""Parse debt-security balance tables into maturity ladders by instrument.

Five periodic-report services report outstanding balances by remaining maturity, one row per
offering type (public, private, and their total) named in ``remndr_exprtn2`` under the same
``remndr_exprtn1`` heading ("Unredeemed balance"). Both headings carry the catalog label
"Remaining maturity", so columns are identified by field name, never by label. Each
instrument files different maturity columns; ``LADDERS`` maps them onto common buckets.
Balances arrive in won even when the filing states KRW million.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal, Protocol

from opendart_analysis.catalog import field_label
from opendart_analysis.domain.normalize import parse_amount
from opendart_analysis.extracts.fields import fold, is_total, text

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

Instrument = Literal[
    "corporate_bonds",
    "short_term_bonds",
    "commercial_paper",
    "hybrid_securities",
    "contingent_capital",
]
"""Debt security kinds with a maturity-ladder table in periodic reports."""

MaturityBucket = Literal["<=1y", "1-2y", "2-3y", "3-5y", "1-5y", ">3y", "5-10y", ">10y"]
"""Common remaining-maturity buckets; 1-5y (hybrids) and >3y (commercial paper) are as filed."""

Offering = Literal["public", "private", "total"]
"""Offering type of a balance row."""


@dataclass(frozen=True, slots=True)
class LadderSpec:
    """How one balance service maps onto the common ladder.

    Attributes:
        instrument (Instrument): Instrument the service reports.
        service (str): SDK method name.
        columns (tuple[tuple[str, MaturityBucket], ...]): Maturity fields in order, each with
            its common bucket.
    """

    instrument: Instrument
    service: str
    columns: tuple[tuple[str, MaturityBucket], ...]


_DAYS: Final[tuple[tuple[str, MaturityBucket], ...]] = (
    ("de10_below", "<=1y"),
    ("de10_excess_de30_below", "<=1y"),
    ("de30_excess_de90_below", "<=1y"),
    ("de90_excess_de180_below", "<=1y"),
    ("de180_excess_yy1_below", "<=1y"),
)
_YEARS: Final[tuple[tuple[str, MaturityBucket], ...]] = (
    ("yy1_below", "<=1y"),
    ("yy1_excess_yy2_below", "1-2y"),
    ("yy2_excess_yy3_below", "2-3y"),
    ("yy3_excess_yy4_below", "3-5y"),
    ("yy4_excess_yy5_below", "3-5y"),
    ("yy5_excess_yy10_below", "5-10y"),
)
LADDERS: Final[tuple[LadderSpec, ...]] = (
    LadderSpec("corporate_bonds", "cprnd_nrdmp_blce", (*_YEARS, ("yy10_excess", ">10y"))),
    LadderSpec("short_term_bonds", "srtpd_psndbt_nrdmp_blce", _DAYS),
    LadderSpec(
        "commercial_paper",
        "entrprs_bil_scrits_nrdmp_blce",
        (
            *_DAYS,
            ("yy1_excess_yy2_below", "1-2y"),
            ("yy2_excess_yy3_below", "2-3y"),
            ("yy3_excess", ">3y"),
        ),
    ),
    LadderSpec(
        "hybrid_securities",
        "new_capl_scrits_nrdmp_blce",
        (
            ("yy1_below", "<=1y"),
            ("yy1_excess_yy5_below", "1-5y"),
            ("yy5_excess_yy10_below", "5-10y"),
            ("yy10_excess_yy15_below", ">10y"),
            ("yy15_excess_yy20_below", ">10y"),
            ("yy20_excess_yy30_below", ">10y"),
            ("yy30_excess", ">10y"),
        ),
    ),
    LadderSpec(
        "contingent_capital",
        "cndl_capl_scrits_nrdmp_blce",
        (
            *_YEARS,
            ("yy10_excess_yy20_below", ">10y"),
            ("yy20_excess_yy30_below", ">10y"),
            ("yy30_excess", ">10y"),
        ),
    ),
)
"""Balance services in ladder order, with their columns."""
BONDS: Final = LADDERS[0]
"""The corporate-bond balance table, which covers every bond outstanding at the period end."""

_OFFERINGS: Final[tuple[tuple[Offering, tuple[str, ...]], ...]] = (
    ("public", ("public", "공모")),
    ("private", ("private", "사모")),
    ("total", ("total", "합계")),
)
_PARTS: Final[tuple[Offering, ...]] = ("public", "private")


@dataclass(frozen=True, slots=True)
class Bucket:
    """Outstanding amount in one common remaining-maturity bucket.

    Attributes:
        maturity_bucket (MaturityBucket): Bucket.
        amount (int): Won outstanding, never zero.
    """

    maturity_bucket: MaturityBucket
    amount: int


@dataclass(frozen=True, slots=True)
class FiledColumn:
    """One maturity column as filed, by offering type.

    Attributes:
        name (str): SDK field name, such as ``yy1_below``.
        label (str): Catalog label, such as "1 year or less".
        public (int | None): Public offerings, in won; None when not filed.
        private (int | None): Private placements, in won; None when not filed.
        total (int | None): Total, in won; None when not filed.
    """

    name: str
    label: str
    public: int | None
    private: int | None
    total: int | None


@dataclass(frozen=True, slots=True)
class Ladder:
    """Outstanding balance of one instrument by remaining maturity, in won.

    Attributes:
        instrument (Instrument): Instrument.
        buckets (tuple[Bucket, ...]): Non-zero common buckets in maturity order.
        total (int): Total outstanding: the filed total, else the sum of the buckets.
        public (int | None): Filed total of public offerings.
        private (int | None): Filed total of private placements.
        issuance_limit (int | None): Issuance limit, for short-term bonds.
        remaining_limit (int | None): Remaining limit, for short-term bonds.
        filed (tuple[FiledColumn, ...]): Every maturity column of the service as filed.
    """

    instrument: Instrument
    buckets: tuple[Bucket, ...]
    total: int
    public: int | None
    private: int | None
    issuance_limit: int | None
    remaining_limit: int | None
    filed: tuple[FiledColumn, ...]


class BucketAmount(Protocol):
    """The fields of a ladder bucket that ``derive`` reads."""

    @property
    def maturity_bucket(self) -> str:
        """Common remaining-maturity bucket."""
        ...

    @property
    def amount(self) -> int:
        """Amount outstanding."""
        ...


class LadderTotals(Protocol):
    """The fields of a ladder that ``derive`` reads; ``Ladder`` has them."""

    @property
    def total(self) -> int | None:
        """Total outstanding."""
        ...

    @property
    def buckets(self) -> Sequence[BucketAmount]:
        """Amounts by bucket."""
        ...


@dataclass(frozen=True, slots=True)
class DebtFigures:
    """Figures computed from ladders.

    Attributes:
        total_debt_securities (int | None): Sum of instrument totals, hybrids and contingent
            capital included; None for an empty ladder.
        due_within_1y (int | None): Amount in the ``<=1y`` buckets.
        due_within_1y_pct (float | None): That amount as a percentage of the total, rounded
            to one decimal.
    """

    total_debt_securities: int | None = None
    due_within_1y: int | None = None
    due_within_1y_pct: float | None = None


def offering(label: str | None) -> Offering | None:
    """Classify a balance row by offering type.

    Args:
        label (str | None): ``remndr_exprtn2`` value, such as "Public offering" or 공모.

    Returns:
        Offering | None: public, private, total, or None when unrecognized.
    """
    folded = fold(label)
    if is_total(label):
        return "total"
    return next((kind for kind, words in _OFFERINGS if any(w in folded for w in words)), None)


def _sum(values: Iterable[int | None]) -> int | None:
    """Add the known values.

    Args:
        values (Iterable[int | None]): Values; None means not filed.

    Returns:
        int | None: Sum, or None when no value is known.
    """
    known = [value for value in values if value is not None]
    return sum(known) if known else None


def _column(rows: Sequence[object], name: str) -> int | None:
    """Add one column across rows.

    Args:
        rows (Sequence[object]): Balance rows.
        name (str): Field name.

    Returns:
        int | None: Sum of the parsed amounts, or None when none is filed.
    """
    return _sum(parse_amount(text(row, name)) for row in rows)


def _rows_by_offering(rows: Sequence[object]) -> dict[Offering, list[object]]:
    """Group balance rows by offering, treating a lone unlabeled row as the total.

    Args:
        rows (Sequence[object]): Balance rows.

    Returns:
        dict[Offering, list[object]]: The total row, or the public and private rows to add.
    """
    grouped: dict[Offering, list[object]] = {}
    for row in rows:
        kind = offering(text(row, "remndr_exprtn2"))
        if kind is not None:
            grouped.setdefault(kind, [row])
    if "total" not in grouped:
        parts = [row for kind in _PARTS for row in grouped.get(kind, [])]
        grouped["total"] = parts or list(rows[:1])
    return grouped


def _buckets(spec: LadderSpec, totals: Sequence[object]) -> tuple[Bucket, ...]:
    """Map the total row's maturity columns onto common buckets.

    Args:
        spec (LadderSpec): Instrument mapping.
        totals (Sequence[object]): Rows that add up to the total.

    Returns:
        tuple[Bucket, ...]: Non-zero buckets in maturity order.
    """
    amounts: dict[MaturityBucket, int] = {}
    for name, bucket in spec.columns:
        amounts[bucket] = amounts.get(bucket, 0) + (_column(totals, name) or 0)
    return tuple(Bucket(b, a) for b, a in amounts.items() if a)


def _filed(spec: LadderSpec, grouped: dict[Offering, list[object]]) -> tuple[FiledColumn, ...]:
    """List every maturity column as filed, by offering type.

    Args:
        spec (LadderSpec): Instrument mapping.
        grouped (dict[Offering, list[object]]): Rows by offering.

    Returns:
        tuple[FiledColumn, ...]: One entry per column, labeled from the catalog.
    """
    return tuple(
        FiledColumn(
            name=name,
            label=field_label(spec.service, name),
            public=_column(grouped.get("public", []), name),
            private=_column(grouped.get("private", []), name),
            total=_column(grouped["total"], name),
        )
        for name, _ in spec.columns
    )


def build_ladder(spec: LadderSpec, rows: Sequence[object]) -> Ladder | None:
    """Build one instrument's ladder from its balance rows.

    Args:
        spec (LadderSpec): Instrument mapping.
        rows (Sequence[object]): Balance rows from ``spec.service``, read by SDK field name.

    Returns:
        Ladder | None: The ladder, or None when nothing is outstanding.
    """
    grouped = _rows_by_offering(rows)
    totals = grouped["total"]
    buckets = _buckets(spec, totals)
    total = _column(totals, "sm") or _sum(bucket.amount for bucket in buckets)
    if not total:
        return None
    return Ladder(
        instrument=spec.instrument,
        buckets=buckets,
        total=total,
        public=_column(grouped.get("public", []), "sm"),
        private=_column(grouped.get("private", []), "sm"),
        issuance_limit=_column(totals, "isu_lmt"),
        remaining_limit=_column(totals, "remndr_lmt"),
        filed=_filed(spec, grouped),
    )


def derive(ladder: Sequence[LadderTotals]) -> DebtFigures:
    """Compute the total and the share due within a year.

    Args:
        ladder (Sequence[LadderTotals]): Ladders, such as ``Ladder`` values.

    Returns:
        DebtFigures: Derived figures; empty when the ladders add up to nothing.
    """
    total = _sum(entry.total for entry in ladder)
    if not total:
        return DebtFigures()
    within = sum(b.amount for e in ladder for b in e.buckets if b.maturity_bucket == "<=1y")
    return DebtFigures(
        total_debt_securities=total,
        due_within_1y=within,
        due_within_1y_pct=round(within / total * 100, 1),
    )
