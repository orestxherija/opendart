"""The control snapshot from a periodic report's largest-shareholder table.

``hyslr_sttus`` lists the largest shareholder and related parties: one row per holder and
share class, with Korean relations (최대주주 본인, 최대주주의 특수관계인, 계열회사 임원) and
a "Total" row per class. Control is measured in the voting class (common shares when held):
the class's total row gives the controlling group's stake, and the share-count table gives
issued and treasury shares for the free-float estimate.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, Protocol

from opendart_analysis.capital.shares import COMMON, ShareClassCounts, share_class, sum_known
from opendart_analysis.domain.normalize import clean_text, parse_amount, parse_percent
from opendart_analysis.extracts import is_total

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from opendart_analysis.capital.shares import ShareCounts
    from opendart_analysis.ownership.tables import MinorityHolders
    from opendart_analysis.reports import ReportQuery
    from opendart_analysis.upstream import Volatility

LARGEST: Final = "largest shareholder"
"""Relation of the largest shareholder itself."""
RELATIONS: Final = MappingProxyType(
    {
        "최대주주본인": LARGEST,
        "본인": LARGEST,
        "최대주주": LARGEST,
        "최대주주의특수관계인": "related party",
        "특수관계인": "related party",
        "계열회사임원": "affiliate officer",
        "계열사임원": "affiliate officer",
        "계열회사": "affiliate",
        "계열사": "affiliate",
        "출연재단": "foundation",
        "재단": "foundation",
        "임원": "officer",
        "친인척": "relative",
        "친족": "relative",
        "배우자": "spouse",
        "자녀": "child",
    }
)
"""Relations as filed, whitespace removed, in English; unknown relations stay as filed."""
_TREASURY_NAMES: Final = ("자기주식", "자사주", "treasury")


class LargestHolderRecord(Protocol):
    """The fields of one largest-shareholder row that analysis reads."""

    @property
    def nm(self) -> str | None:
        """Holder name as filed, or a total label."""
        ...

    @property
    def relate(self) -> str | None:
        """Relation to the largest shareholder as filed."""
        ...

    @property
    def stock_knd(self) -> str | None:
        """Share class as filed."""
        ...

    @property
    def bsis_posesn_stock_co(self) -> str | None:
        """Shares held at the period start."""
        ...

    @property
    def bsis_posesn_stock_qota_rt(self) -> str | None:
        """Ownership at the period start, in percent."""
        ...

    @property
    def trmend_posesn_stock_co(self) -> str | None:
        """Shares held at the period end."""
        ...

    @property
    def trmend_posesn_stock_qota_rt(self) -> str | None:
        """Ownership at the period end, in percent."""
        ...

    @property
    def rm(self) -> str | None:
        """Note."""
        ...

    @property
    def stlm_dt(self) -> str | None:
        """Settlement date stated with the table."""
        ...

    @property
    def filing_number(self) -> str | None:
        """14-digit filing number of the periodic report."""
        ...


class FetchLargestHolders(Protocol):
    """Fetch one company's largest-shareholder table for one period; bound by the caller."""

    async def __call__(
        self, query: ReportQuery, /, *, volatility: Volatility
    ) -> Sequence[LargestHolderRecord] | None:
        """Return the largest-shareholder rows of a company's periodic report.

        Args:
            query (ReportQuery): Company and period.
            volatility (Volatility): How quickly the answer can change, for the source's cache.

        Returns:
            Sequence[LargestHolderRecord] | None: Rows, or None when the source has none.
        """
        ...


@dataclass(frozen=True, slots=True)
class Holder:
    """One holding of the largest shareholder or a related party, in one share class.

    Percentages are of the class's issued shares, as filed.

    Attributes:
        name (str): Holder name as filed.
        relation (str | None): Relation to the largest shareholder, in English when common.
        share_class (str): ``common``, ``preferred``, or the class as filed.
        shares (int | None): Shares at the period end.
        pct_begin (float | None): Ownership at the period start, in percent.
        pct_end (float | None): Ownership at the period end, in percent.
        shares_begin (int | None): Shares at the period start.
        note (str | None): Note as filed, such as the reason for a change.
    """

    name: str
    relation: str | None
    share_class: str
    shares: int | None
    pct_begin: float | None
    pct_end: float | None
    shares_begin: int | None = None
    note: str | None = None


@dataclass(frozen=True, slots=True)
class ControlSnapshot:
    """Control at the period end, measured in the voting share class.

    Attributes:
        share_class (str): Class the percentages, counts, and float refer to.
        largest_shareholder (str | None): Holder filed as the largest shareholder, else the
            biggest holding of the class.
        holders (tuple[Holder, ...]): Every holding of the group, without total rows: the
            class's holdings first, then other classes, each largest first.
        group_members (int): Distinct holders in the group, all classes.
        controlling_shares (int | None): Shares the group holds in the class.
        controlling_pct (float | None): The group's ownership at the period end, in percent.
        controlling_pct_begin (float | None): The group's ownership at the period start.
        minority (MinorityHolders | None): Minority shareholder figures.
        shares_issued (int | None): Issued shares of the class, treasury included.
        treasury_shares (int | None): Treasury shares of the class.
        shares_outstanding (int | None): Issued minus treasury shares of the class.
        free_float_estimate_pct (float | None): Issued shares minus the group's and treasury
            shares, over issued shares, in percent; other large holders and lock-ups are not
            excluded.
    """

    share_class: str
    largest_shareholder: str | None
    holders: tuple[Holder, ...]
    group_members: int
    controlling_shares: int | None
    controlling_pct: float | None
    controlling_pct_begin: float | None
    minority: MinorityHolders | None
    shares_issued: int | None
    treasury_shares: int | None
    shares_outstanding: int | None
    free_float_estimate_pct: float | None


def control_snapshot(
    records: Sequence[LargestHolderRecord],
    counts: ShareCounts | None,
    minority: MinorityHolders | None = None,
) -> ControlSnapshot:
    """Build the control snapshot of one report.

    Args:
        records (Sequence[LargestHolderRecord]): Largest-shareholder rows, in filed order.
        counts (ShareCounts | None): Share counts from the same report.
        minority (MinorityHolders | None): Minority shareholder figures.

    Returns:
        ControlSnapshot: The snapshot.
    """
    holders, totals = _group(records)
    basis = _basis(holders, counts)
    members = [holder for holder in holders if holder.share_class == basis]
    group = totals.get(basis) or _sum_group(members, basis)
    shares = _class_counts(counts, basis)
    treasury = 0 if any(_is_treasury(holder.name) for holder in members) else shares.treasury
    ranked = sorted(holders, key=lambda h: (h.share_class != basis, -(h.shares or 0)))
    return ControlSnapshot(
        share_class=basis,
        largest_shareholder=_largest(holders, members),
        holders=tuple(ranked),
        group_members=len({holder.name for holder in holders}),
        controlling_shares=group.shares,
        controlling_pct=group.pct_end,
        controlling_pct_begin=group.pct_begin,
        minority=minority,
        shares_issued=shares.issued,
        treasury_shares=shares.treasury,
        shares_outstanding=shares.outstanding,
        free_float_estimate_pct=free_float(shares.issued, group.shares, treasury),
    )


def free_float(issued: int | None, controlling: int | None, treasury: int | None) -> float | None:
    """Estimate the free float as a percentage of issued shares.

    Args:
        issued (int | None): Issued shares of the class, treasury included.
        controlling (int | None): Shares held by the controlling group.
        treasury (int | None): Treasury shares not already counted in the group.

    Returns:
        float | None: Percentage rounded to two decimals, or None when a count is missing.
    """
    if not issued or controlling is None:
        return None
    floating = max(issued - controlling - (treasury or 0), 0)
    return round(floating * 100 / issued, 2)


def relation(text: str | None) -> str | None:
    """Translate a filed relation to the largest shareholder.

    Args:
        text (str | None): Relation as filed, such as 최대주주의 특수관계인.

    Returns:
        str | None: English relation such as ``related party``, the filed text when the
            relation is not a common one, or None when blank.
    """
    cleaned = clean_text(text)
    return RELATIONS.get("".join(cleaned.split()), cleaned) if cleaned else None


def _holder(record: LargestHolderRecord) -> Holder:
    """Parse one largest-shareholder row.

    Args:
        record (LargestHolderRecord): Upstream row.

    Returns:
        Holder: Holding; a blank share class counts as common shares.
    """
    return Holder(
        name=clean_text(record.nm) or "unnamed",
        relation=relation(record.relate),
        share_class=share_class(record.stock_knd) or COMMON,
        shares=parse_amount(record.trmend_posesn_stock_co),
        pct_begin=parse_percent(record.bsis_posesn_stock_qota_rt),
        pct_end=parse_percent(record.trmend_posesn_stock_qota_rt),
        shares_begin=parse_amount(record.bsis_posesn_stock_co),
        note=clean_text(record.rm),
    )


def _group(records: Iterable[LargestHolderRecord]) -> tuple[list[Holder], dict[str, Holder]]:
    """Separate holdings from the per-class total rows.

    Args:
        records (Iterable[LargestHolderRecord]): Upstream rows.

    Returns:
        tuple[list[Holder], dict[str, Holder]]: Holdings in filed order, and totals by class.
    """
    parsed = [(is_total(record.nm), _holder(record)) for record in records]
    totals = {holder.share_class: holder for total, holder in parsed if total}
    return [holder for total, holder in parsed if not total], totals


def _basis(holders: Sequence[Holder], counts: ShareCounts | None) -> str:
    """Choose the class that control is measured in: common shares when the group holds them.

    Args:
        holders (Sequence[Holder]): Holdings.
        counts (ShareCounts | None): Share counts of the same report.

    Returns:
        str: Share class.
    """
    primary = counts.primary if counts is not None else None
    preferred = primary.share_class if primary is not None else COMMON
    classes = [holder.share_class for holder in holders]
    return preferred if preferred in classes or not classes else classes[0]


def _sum_group(members: Sequence[Holder], basis: str) -> Holder:
    """Add up the group when the report has no total row for the class.

    Args:
        members (Sequence[Holder]): Holdings of the basis class.
        basis (str): Share class.

    Returns:
        Holder: Combined holding.
    """
    begin = [holder.pct_begin for holder in members if holder.pct_begin is not None]
    end = [holder.pct_end for holder in members if holder.pct_end is not None]
    return Holder(
        name="Total",
        relation=None,
        share_class=basis,
        shares=sum_known(holder.shares for holder in members),
        pct_begin=round(sum(begin), 2) if begin else None,
        pct_end=round(sum(end), 2) if end else None,
    )


def _class_counts(counts: ShareCounts | None, basis: str) -> ShareClassCounts:
    """Find the share counts of one class.

    Args:
        counts (ShareCounts | None): Share counts of the report.
        basis (str): Share class.

    Returns:
        ShareClassCounts: Counts, all None when unknown.
    """
    rows = counts.classes if counts is not None else ()
    return next((row for row in rows if row.share_class == basis), ShareClassCounts(basis))


def _is_treasury(name: str) -> bool:
    """Check whether a holder is the company's own treasury stock, which some groups list.

    Args:
        name (str): Holder name.

    Returns:
        bool: True for treasury-stock entries.
    """
    folded = name.casefold()
    return any(word in folded for word in _TREASURY_NAMES)


def _largest(holders: Sequence[Holder], members: Sequence[Holder]) -> str | None:
    """Name the largest shareholder: the holder filed as such, else the biggest holding.

    Args:
        holders (Sequence[Holder]): All holdings.
        members (Sequence[Holder]): Holdings of the basis class.

    Returns:
        str | None: Holder name.
    """
    named = next((holder.name for holder in holders if holder.relation == LARGEST), None)
    if named is not None or not members:
        return named
    return max(members, key=lambda holder: holder.shares or 0).name
