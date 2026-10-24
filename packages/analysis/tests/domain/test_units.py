"""Display units."""

from __future__ import annotations

import pytest

from opendart_analysis.domain.units import (
    scale_amount,
    unit_label,
)


@pytest.mark.parametrize(
    ("amount", "unit", "expected"),
    [
        (1_234_567_890, "krw", 1_234_567_890),
        (1_234_567_890, "million_krw", 1234.6),
        (1_234_567_890, "billion_krw", 1.2),
        (1_250_000, "million_krw", 1.3),
        (-1_250_000, "million_krw", -1.3),
        (1_249_999, "million_krw", 1.2),
        (0, "million_krw", 0.0),
        (None, "million_krw", None),
        (None, "krw", None),
        (300_000_000_000_000, "billion_krw", 300000.0),
    ],
)
def test_scale_amount(amount, unit, expected):
    assert scale_amount(amount, unit) == expected


def test_scale_amount_types():
    assert isinstance(scale_amount(5, "krw"), int)
    assert isinstance(scale_amount(5, "million_krw"), float)


@pytest.mark.parametrize(
    ("unit", "label"),
    [("krw", "KRW"), ("million_krw", "KRW million"), ("billion_krw", "KRW billion")],
)
def test_unit_label(unit, label):
    assert unit_label(unit) == label
