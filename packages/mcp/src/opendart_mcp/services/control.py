"""Show the control snapshot of get_ownership.

``opendart_analysis.ownership`` builds the snapshot from the largest-shareholder table: the
voting class, the controlling group's stake, share counts, minority shareholders, and the
free-float estimate. Here it becomes the output model: concise results list the largest
holdings of the voting class without detail fields, and notes qualify the estimate.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import TYPE_CHECKING, Final

from opendart_mcp.models.ownership import Holder, Minority, OwnershipSnapshot

if TYPE_CHECKING:
    from opendart_analysis.ownership import ControlSnapshot, Holder as Holding, MinorityHolders

CONCISE_HOLDERS: Final = 10
"""Most holdings of the voting class a concise snapshot lists."""
_FLOAT_NOTE: Final = "free_float_estimate_pct is an estimate: issued {share_class} shares minus the controlling group's and treasury shares, over issued shares; other large holders and lock-ups are not excluded."
_NO_FLOAT_NOTE: Final = "The free float could not be estimated: the share-count table or the controlling group's total is missing."


def snapshot_view(
    snapshot: ControlSnapshot, *, detailed: bool
) -> tuple[OwnershipSnapshot, list[str]]:
    """Show the control snapshot and the notes that qualify it.

    Args:
        snapshot (ControlSnapshot): Snapshot from the periodic report.
        detailed (bool): Whether to list every holding with every field.

    Returns:
        tuple[OwnershipSnapshot, list[str]]: Snapshot and notes.
    """
    basis = snapshot.share_class
    listed = (
        list(snapshot.holders)
        if detailed
        else [holder for holder in snapshot.holders if holder.share_class == basis][
            :CONCISE_HOLDERS
        ]
    )
    model = OwnershipSnapshot(
        share_class=basis,
        largest_shareholder=snapshot.largest_shareholder,
        largest_shareholder_group=[_holder(holder, detailed=detailed) for holder in listed],
        group_members=snapshot.group_members,
        controlling_shares=snapshot.controlling_shares,
        controlling_pct=snapshot.controlling_pct,
        controlling_pct_begin=snapshot.controlling_pct_begin,
        minority=_minority(snapshot.minority, detailed=detailed),
        shares_issued=snapshot.shares_issued,
        treasury_shares=snapshot.treasury_shares,
        shares_outstanding=snapshot.shares_outstanding,
        free_float_estimate_pct=snapshot.free_float_estimate_pct,
    )
    return model, _notes(model, shown=len(listed), total=len(snapshot.holders))


def _holder(holder: Holding, *, detailed: bool) -> Holder:
    """Show one holding; concise results leave out the opening shares and the note.

    Args:
        holder (Holding): Holding.
        detailed (bool): Whether to keep every field.

    Returns:
        Holder: Output holding.
    """
    fields = asdict(holder)
    if not detailed:
        fields.update(shares_begin=None, note=None)
    return Holder(**fields)


def _minority(minority: MinorityHolders | None, *, detailed: bool) -> Minority | None:
    """Show minority figures; concise results leave out the issued shares.

    Args:
        minority (MinorityHolders | None): Figures, if found.
        detailed (bool): Whether to keep every field.

    Returns:
        Minority | None: Output figures.
    """
    if minority is None:
        return None
    fields = asdict(minority)
    if not detailed:
        fields.update(total_shares=None)
    return Minority(**fields)


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
