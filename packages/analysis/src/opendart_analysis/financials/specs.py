"""Which rows each statement reads, its reading order, and its key lines.

The major accounts (``summary``) come from one answer that holds the consolidated and the
separate rows; the full statements come one basis per answer and are filtered by statement
type. Full statements arrive sorted by account ID, so each statement ranks its key accounts
first, in reading order, followed by the other lines in upstream order.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, Literal

from opendart_analysis.financials.accounts import (
    COMPONENT_ORDER,
    EQUITY_AT_END,
    KEY_ACCOUNTS,
    KEY_ACCOUNT_NAMES,
    METRICS,
    METRIC_RANK,
    TOTAL_COMPONENT,
    component,
    metric_of,
    normalize,
)

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from opendart_analysis.domain.types import Basis
    from opendart_analysis.financials.access import StatementScope
    from opendart_analysis.financials.statements import Item, Ranker, StatementBasis

FullStatement = Literal["income", "balance", "cash_flow", "comprehensive_income", "equity_changes"]
"""One of a company's full financial statements."""

StatementKind = Literal[
    "summary", "income", "balance", "cash_flow", "comprehensive_income", "equity_changes"
]
"""A statement: the major accounts (``summary``) or one of the full statements."""

SCOPES: Final[Mapping[Basis, tuple[tuple[StatementScope, StatementBasis], ...]]] = MappingProxyType(
    {
        "auto": (("CFS", "consolidated"), ("OFS", "separate")),
        "consolidated": (("CFS", "consolidated"),),
        "separate": (("OFS", "separate"),),
    }
)
"""Basis codes to try for a requested basis, in order, with the basis each one means."""

# Statement-of-changes-in-equity ranks: component position times this span, plus the line.
_EQUITY_SPAN: Final = 10_000
_ALL_KEY: Final = 1 << 30


@dataclass(frozen=True, slots=True)
class StatementSpec:
    """How a statement selects, orders, and derives.

    Attributes:
        statements (tuple[str, ...]): Statement types to read; the first with rows wins.
        rank (Ranker): Sort position of a row given its upstream position.
        key_limit (int): Lines ranked below this are key lines.
        derive (bool): Whether derived metrics apply.
        name (str): Name of the statement, such as ``income statement``.
    """

    statements: tuple[str, ...]
    rank: Ranker
    key_limit: int
    derive: bool
    name: str


def _key_rank(keys: Sequence[str], names: Mapping[str, str]) -> Ranker:
    """Rank key accounts in reading order, then other lines in upstream order.

    Args:
        keys (Sequence[str]): Key account IDs in reading order.
        names (Mapping[str, str]): Key account ID by normalized name, for lines that lack a
            standard ID.

    Returns:
        Ranker: Ranking function.
    """
    order = {account_id: rank for rank, account_id in enumerate(keys)}

    def rank(item: Item, position: int) -> int:
        """Return an account's configured position in the statement.

        Args:
            item (Item): Reduced statement row.
            position (int): Original position in the upstream response.

        Returns:
            int: Sort position, with unlisted accounts following key accounts.
        """
        account_id = item.account_id or names.get(normalize(item.account), "")
        return order.get(account_id, len(order) + position)

    return rank


def summary_rank(item: Item, position: int) -> int:
    """Rank major-account lines: income lines, then the balance sheet, then the rest.

    Args:
        item (Item): Reduced row.
        position (int): Upstream position.

    Returns:
        int: Sort position.
    """
    metric = metric_of(item.account_id, item.account)
    return METRIC_RANK[metric.key] if metric is not None else len(METRICS) + position


def _equity_rank(item: Item, position: int) -> int:
    """Rank equity changes by component, opening balance first and closing balance last.

    Args:
        item (Item): Reduced row.
        position (int): Upstream position.

    Returns:
        int: Sort position; whole-equity lines rank below ``_EQUITY_SPAN``.
    """
    part = component(item.detail) or TOTAL_COMPONENT
    group = COMPONENT_ORDER.index(part) if part in COMPONENT_ORDER else len(COMPONENT_ORDER)
    if item.account_id in KEY_ACCOUNTS["SCE"]:
        line = 0
    elif item.account_id == EQUITY_AT_END:
        line = _EQUITY_SPAN - 1
    else:
        line = position + 1
    return group * _EQUITY_SPAN + min(line, _EQUITY_SPAN - 1)


def _spec(statements: tuple[str, ...], keys: str, *, derive: bool, name: str) -> StatementSpec:
    """Build the spec of a full statement ranked by key accounts.

    Args:
        statements (tuple[str, ...]): Statement types to read.
        keys (str): Statement type whose key accounts rank first.
        derive (bool): Whether derived metrics apply.
        name (str): Name of the statement.

    Returns:
        StatementSpec: Statement spec.
    """
    accounts = KEY_ACCOUNTS[keys]
    names = KEY_ACCOUNT_NAMES.get(keys, {})
    return StatementSpec(statements, _key_rank(accounts, names), len(accounts), derive, name)


STATEMENTS: Final[Mapping[StatementKind, StatementSpec]] = MappingProxyType(
    {
        "summary": StatementSpec(
            ("BS", "IS"), summary_rank, _ALL_KEY, derive=True, name="major accounts"
        ),
        "income": _spec(("IS", "CIS"), "IS", derive=True, name="income statement"),
        "balance": _spec(("BS",), "BS", derive=True, name="balance sheet"),
        "cash_flow": _spec(("CF",), "CF", derive=False, name="cash flow statement"),
        "comprehensive_income": _spec(
            ("CIS",), "CIS", derive=False, name="statement of comprehensive income"
        ),
        "equity_changes": StatementSpec(
            ("SCE",),
            _equity_rank,
            _EQUITY_SPAN,
            derive=False,
            name="statement of changes in equity",
        ),
    }
)
"""Each statement and how it selects, orders, and derives; every major-account line is key."""
