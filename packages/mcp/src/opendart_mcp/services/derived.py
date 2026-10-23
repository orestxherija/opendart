"""Metrics derived in code from reported amounts: growth, margins, and leverage.

Nothing here uses prices. Values are percentages rounded to two decimals. A metric is left
out when an input is missing or its base is not positive, since growth from a loss or a
ratio over negative equity means nothing. Quarterly income lines use year-to-date amounts,
the same basis as OpenDART's own indicators.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from opendart_mcp.services.accounts import metric_of

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

    from opendart_mcp.domain.periods import PeriodRef
    from opendart_mcp.models.financials import Number
    from opendart_mcp.services.statements import Line

    type Pair = tuple[Number | None, Number | None]

GROWTH: Final[tuple[tuple[str, str], ...]] = (
    ("revenue_growth", "revenue"),
    ("operating_income_growth", "operating_income"),
    ("net_income_growth", "net_income"),
)
"""Derived growth keys and the metric each compares with its prior-year value."""

INCOME_KEYS: Final = frozenset(
    {
        "revenue_growth",
        "operating_income_growth",
        "net_income_growth",
        "operating_margin",
        "net_margin",
    }
)
"""Derived keys computed from income lines, which are year to date in quarterly reports."""

RATIOS: Final[tuple[tuple[str, str, str], ...]] = (
    ("operating_margin", "operating_income", "revenue"),
    ("net_margin", "net_income", "revenue"),
    ("debt_to_equity", "total_liabilities", "total_equity"),
    ("current_ratio", "current_assets", "current_liabilities"),
)
"""Derived ratio keys with numerator and denominator metrics."""

_FORMULAS: Final = {
    "operating_margin": "operating_margin = operating profit / revenue",
    "net_margin": "net_margin = net profit / revenue",
    "debt_to_equity": "debt_to_equity = total liabilities / total equity",
    "current_ratio": "current_ratio = current assets / current liabilities",
}
_PERCENT: Final = 100


def _ratio(numerator: Number | None, denominator: Number | None) -> float | None:
    """Divide two amounts, requiring a positive denominator.

    Args:
        numerator (Number | None): Top amount.
        denominator (Number | None): Bottom amount.

    Returns:
        float | None: Quotient, or None.
    """
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return numerator / denominator


def compute(values: Mapping[str, Pair]) -> dict[str, float]:
    """Compute every derived metric the inputs allow.

    Args:
        values (Mapping[str, Pair]): Metric key to (current, prior-year) amounts.

    Returns:
        dict[str, float]: Derived metrics in percent, rounded to two decimals.
    """
    result: dict[str, float] = {}
    for key, metric in GROWTH:
        ratio = _ratio(*values.get(metric, (None, None)))
        if ratio is not None:
            result[key] = round((ratio - 1) * _PERCENT, 2)
    for key, top, bottom in RATIOS:
        ratio = _ratio(values.get(top, (None, None))[0], values.get(bottom, (None, None))[0])
        if ratio is not None:
            result[key] = round(ratio * _PERCENT, 2)
    return result


def _value(line: Line, ref: PeriodRef | None) -> Number | None:
    """Read a line's year-to-date amount for a period, else its period amount.

    Args:
        line (Line): Line item.
        ref (PeriodRef | None): Period, or None when there is none.

    Returns:
        Number | None: Amount.
    """
    if ref is None:
        return None
    total = line.cumulative.get(ref)
    return total if total is not None else line.values.get(ref)


def metric_values(
    lines: Iterable[Line], current: PeriodRef, prior: PeriodRef | None
) -> dict[str, Pair]:
    """Find the key metrics among lines for a period and its prior-year comparable.

    Args:
        lines (Iterable[Line]): Line items; the best-ranked line of each metric wins.
        current (PeriodRef): Period to measure.
        prior (PeriodRef | None): Same period a year earlier, if available.

    Returns:
        dict[str, Pair]: Metric key to (current, prior) amounts.
    """
    found: dict[str, Pair] = {}
    for line in sorted(lines, key=lambda line: line.rank):
        metric = metric_of(line.account_id, line.name or line.account)
        if metric is not None and metric.key not in found:
            found[metric.key] = (_value(line, current), _value(line, prior))
    return found


def note(keys: Iterable[str], *, period: str, comparison: str | None) -> str | None:
    """Explain which derived metrics were computed and how.

    Args:
        keys (Iterable[str]): Derived metric keys present in the result.
        period (str): Label of the measured period, such as FY2025.
        comparison (str | None): Label of the prior-year period used for growth.

    Returns:
        str | None: Note text, or None when nothing was derived.
    """
    present = list(keys)
    growth = [key for key, _ in GROWTH if key in present]
    parts = [f"{", ".join(growth)} = change versus {comparison}"] if growth else []
    parts.extend(_FORMULAS[key] for key, _, _ in RATIOS if key in present)
    if not parts:
        return None
    return f"derived: computed in code for {period} from reported amounts (not filed figures), in percent; {"; ".join(parts)}."
