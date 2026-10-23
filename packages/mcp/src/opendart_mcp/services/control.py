"""Build the control snapshot from a periodic report's largest-shareholder table.

``hyslr_sttus`` lists the largest shareholder and related parties: one row per holder and
share class, with Korean relations (최대주주 본인, 최대주주의 특수관계인, 계열회사 임원) and
a "Total" row per class. Control is measured in the voting class (common shares when held):
the class's total row gives the controlling group's stake, and the share-count table gives
issued and treasury shares for the free-float estimate.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from opendart_mcp.domain.normalize import clean_text, parse_amount, parse_percent
from opendart_mcp.models.capital import ShareClassRow
from opendart_mcp.models.ownership import Holder, OwnershipSnapshot
from opendart_mcp.services.shares import COMMON, is_total, share_class, sum_known, trim

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    from opendart.models.periodic_reports import HyslrSttusResponseListItem
    from opendart_mcp.models.ownership import Minority
    from opendart_mcp.services.shares import ShareCounts

LARGEST: Final = "largest shareholder"
CONCISE_HOLDERS: Final = 10
# Relations as filed, whitespace removed, in English; unknown relations stay as filed.
RELATIONS: Final = {
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
_TREASURY_NAMES: Final = ("자기주식", "자사주", "treasury")
_HOLDER_DETAIL: Final = ("shares_begin", "note")
_FLOAT_NOTE: Final = "free_float_estimate_pct is an estimate: issued {share_class} shares minus the controlling group's and treasury shares, over issued shares; other large holders and lock-ups are not excluded."
_NO_FLOAT_NOTE: Final = "The free float could not be estimated: the share-count table or the controlling group's total is missing."


def build_snapshot(
    items: Sequence[HyslrSttusResponseListItem],
    counts: ShareCounts | None,
    minority: Minority | None,
    *,
    detailed: bool,
) -> tuple[OwnershipSnapshot, list[str]]:
    """Build the control snapshot and the notes that qualify it.

    Args:
        items (Sequence[HyslrSttusResponseListItem]): Largest-shareholder rows.
        counts (ShareCounts | None): Share counts from the same report.
        minority (Minority | None): Minority shareholder figures.
        detailed (bool): Whether to list every holding with every field.

    Returns:
        tuple[OwnershipSnapshot, list[str]]: Snapshot and notes.
    """
    holders, totals = _group(items)
    basis = _basis(holders, counts)
    members = [holder for holder in holders if holder.share_class == basis]
    group = totals.get(basis) or _sum_group(members, basis)
    shares = _class_counts(counts, basis)
    treasury = 0 if any(_is_treasury(holder.name) for holder in members) else shares.treasury
    listed = _listed(holders, basis, detailed=detailed)
    snapshot = OwnershipSnapshot(
        share_class=basis,
        largest_shareholder=_largest(holders, members),
        largest_shareholder_group=listed,
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
    return snapshot, _notes(snapshot, shown=len(listed), total=len(holders))


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


def _notes(snapshot: OwnershipSnapshot, *, shown: int, total: int) -> list[str]:
    """Explain the estimate and anything left out of the snapshot.

    Args:
        snapshot (OwnershipSnapshot): Built snapshot.
        shown (int): Holdings listed.
        total (int): Holdings in the group, all classes.

    Returns:
        list[str]: Notes.
    """
    estimated = snapshot.free_float_estimate_pct is not None
    notes = [_FLOAT_NOTE.format(share_class=snapshot.share_class) if estimated else _NO_FLOAT_NOTE]
    if shown < total:
        notes.append(
            f"Showing the {shown} largest {snapshot.share_class}-share holdings of the group's {total}; response_format='detailed' lists all of them."
        )
    return notes


def _holder(item: HyslrSttusResponseListItem) -> Holder:
    """Parse one largest-shareholder row.

    Args:
        item (HyslrSttusResponseListItem): Upstream row.

    Returns:
        Holder: Holding; a blank share class counts as common shares.
    """
    return Holder(
        name=clean_text(item.nm) or "unnamed",
        relation=relation(item.relate),
        share_class=share_class(item.stock_knd) or COMMON,
        shares=parse_amount(item.trmend_posesn_stock_co),
        pct_begin=parse_percent(item.bsis_posesn_stock_qota_rt),
        pct_end=parse_percent(item.trmend_posesn_stock_qota_rt),
        shares_begin=parse_amount(item.bsis_posesn_stock_co),
        note=clean_text(item.rm),
    )


def _group(items: Iterable[HyslrSttusResponseListItem]) -> tuple[list[Holder], dict[str, Holder]]:
    """Separate holdings from the per-class total rows.

    Args:
        items (Iterable[HyslrSttusResponseListItem]): Upstream rows.

    Returns:
        tuple[list[Holder], dict[str, Holder]]: Holdings in filed order, and totals by class.
    """
    parsed = [(is_total(item.nm), _holder(item)) for item in items]
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
        share_class=basis,
        shares=sum_known(holder.shares for holder in members),
        pct_begin=round(sum(begin), 2) if begin else None,
        pct_end=round(sum(end), 2) if end else None,
    )


def _class_counts(counts: ShareCounts | None, basis: str) -> ShareClassRow:
    """Find the share counts of one class.

    Args:
        counts (ShareCounts | None): Share counts of the report.
        basis (str): Share class.

    Returns:
        ShareClassRow: Counts, all None when unknown.
    """
    rows = counts.classes if counts is not None else ()
    return next((row for row in rows if row.share_class == basis), ShareClassRow(share_class=basis))


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


def _listed(holders: Sequence[Holder], basis: str, *, detailed: bool) -> list[Holder]:
    """Order holdings by class and size; concise keeps the largest of the basis class.

    Args:
        holders (Sequence[Holder]): Holdings.
        basis (str): Share class control is measured in.
        detailed (bool): Whether to keep every holding and field.

    Returns:
        list[Holder]: Holdings to show.
    """
    ranked = sorted(holders, key=lambda h: (h.share_class != basis, -(h.shares or 0)))
    if detailed:
        return ranked
    kept = [holder for holder in ranked if holder.share_class == basis][:CONCISE_HOLDERS]
    return [trim(holder, _HOLDER_DETAIL) for holder in kept]
