"""Project debt-security maturity ladders into the debt output models.

The ladder logic lives in ``opendart_analysis.debt``: balance tables mapped onto common
remaining-maturity buckets, in won as filed. This module builds the response's ladder entries,
which list every filed column only in detailed results, and the derived figures, which the
corporate-action calendar also computes from a ladder entry.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from opendart_analysis import debt
from opendart_mcp.models.debt import DebtDerived, FiledBucket, LadderBucket, LadderEntry

if TYPE_CHECKING:
    from collections.abc import Sequence

    from opendart_analysis.debt import DebtFigures, Ladder


def ladder_entry(ladder: Ladder, *, detailed: bool) -> LadderEntry:
    """Describe one instrument's ladder.

    Args:
        ladder (Ladder): Ladder from ``opendart_analysis.debt``.
        detailed (bool): Whether to add every maturity column as filed.

    Returns:
        LadderEntry: Output entry.
    """
    filed = [
        FiledBucket(
            label=column.label, public=column.public, private=column.private, total=column.total
        )
        for column in ladder.filed
    ]
    return LadderEntry(
        instrument=ladder.instrument,
        buckets=[
            LadderBucket(maturity_bucket=b.maturity_bucket, amount=b.amount) for b in ladder.buckets
        ],
        total=ladder.total,
        public=ladder.public,
        private=ladder.private,
        issuance_limit=ladder.issuance_limit,
        remaining_limit=ladder.remaining_limit,
        filed=filed if detailed else None,
    )


def derived(figures: DebtFigures) -> DebtDerived:
    """Describe derived debt figures.

    Args:
        figures (DebtFigures): Figures from ``opendart_analysis.debt.derive``.

    Returns:
        DebtDerived: Output figures; empty for an empty ladder.
    """
    return DebtDerived(
        total_debt_securities=figures.total_debt_securities,
        due_within_1y=figures.due_within_1y,
        due_within_1y_pct=figures.due_within_1y_pct,
    )


def derive(ladder: Sequence[LadderEntry]) -> DebtDerived:
    """Compute the total and the share due within a year of ladder entries.

    Args:
        ladder (Sequence[LadderEntry]): Ladder entries.

    Returns:
        DebtDerived: Derived figures; empty when the ladder is.
    """
    return derived(debt.derive(ladder))
