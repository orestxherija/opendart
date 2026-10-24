"""Reading all-string periodic-report fields: containers, amounts, labels, totals, and terms."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from opendart_analysis.extracts import (
    amount,
    filed_text,
    fold,
    is_total,
    records,
    term_ages,
    text,
)


def test_records_reads_a_named_container_and_tolerates_a_missing_one():
    rows = [SimpleNamespace(se="x")]
    assert records(SimpleNamespace(list=rows)) == rows
    assert records(SimpleNamespace(group=rows), "group") == rows
    assert records(SimpleNamespace(list=None)) == []
    assert records(SimpleNamespace(list="not a list")) == []
    assert records(object()) == []


def test_records_copies_the_container_without_touching_it():
    rows = [SimpleNamespace(se="x")]
    found = records(SimpleNamespace(list=rows))
    found.append(SimpleNamespace(se="y"))
    assert len(rows) == 1


def test_text_reads_strings_only():
    record = SimpleNamespace(se=" Cash dividend ", thstrm=1668, stlm_dt=None)
    assert text(record, "se") == " Cash dividend "
    assert text(record, "thstrm") is None
    assert text(record, "stlm_dt") is None
    assert text(record, "missing") is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1,234,567", 1234567),
        ("(1,234)", -1234),
        ("△500", -500),
        ("0", 0),
        ("-", None),
        ("", None),
        ("1.5", None),
        ("1,23", None),
        (None, None),
    ],
)
def test_amount_parses_separators_signs_and_placeholders(raw, expected):
    assert amount(SimpleNamespace(thstrm=raw), "thstrm") == expected


def test_fold_drops_whitespace_and_case():
    assert fold(" Sub\nTotal ") == "subtotal"
    assert fold(None) == ""


@pytest.mark.parametrize("label", ["합 계", "계", "총계", "소계", "Total", "SUB TOTAL", "sum"])
def test_total_labels_are_recognized(label):
    assert is_total(label)


@pytest.mark.parametrize("label", ["Public offering", "합계액", None, ""])
def test_other_labels_are_not_totals(label):
    assert not is_total(label)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  감사\n  의견 ", "감사 의견"),
        ("해당사항 없음", None),
        ("해당사항없습니다.", None),
        ("N/A", None),
        ("Not applicable.", None),
        ("-", None),
        ("", None),
        (None, None),
        ("None of the above applies", "None of the above applies"),
    ],
)
def test_filed_text_drops_placeholders(raw, expected):
    assert filed_text(raw) == expected


@pytest.mark.parametrize(
    ("labels", "expected"),
    [
        (
            ["제57기 \n(당기)", "제57기 \n(당기)", "제56기\n(전기)", "제55기\n(전전기)"],
            [0, 0, 1, 2],
        ),
        # Term numbers win over words, since filers mislabel older terms as 당기 (current).
        (["제57기(당기)", "제56기(당기)", "제55기(당기)"], [0, 1, 2]),
        (["당기", "전기", "전전기"], [0, 1, 2]),
        (["2025", "2024", "2023"], [0, 1, 2]),
        # Years win over term numbers.
        (["제57기 2025", "제56기 2024"], [0, 1]),
        (["57th (current)", "56th (prior)"], [0, 1]),
        (["1st", "22nd", "23rd"], [22, 1, 0]),
        (["Current term", "Prior term", "Two years prior"], [0, 1, 2]),
        (["Current term", "Previous term"], [0, 1]),
        # Without numbers or words, first appearance decides.
        (["A", "B", "A"], [0, 1, 0]),
        # Blank labels continue the previous row's term.
        (["제57기(당기)", None, "-", "제56기(전기)"], [0, 0, 0, 1]),
        (["-", "-"], [0, 0]),
        ([], []),
    ],
)
def test_term_ages(labels, expected):
    assert term_ages(labels) == expected
