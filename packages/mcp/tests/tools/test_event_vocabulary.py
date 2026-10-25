"""The event vocabulary matches the get_corporate_events table in COMPONENT_DESIGN.md."""

from __future__ import annotations

import re
from pathlib import Path

from opendart_analysis.catalog import EVENT_GROUPS, EVENT_KINDS

DESIGN = Path(__file__).resolve().parents[2] / "docs/COMPONENT_DESIGN.md"


def design_vocabulary() -> list[tuple[str, str, str]]:
    """Parse the get_corporate_events vocabulary table: (kind, group, SDK method).

    Its rows are the only ones whose first cell is one code word and whose second cell lists
    kinds as `kind` (`method`).
    """
    text = DESIGN.read_text(encoding="utf-8")
    rows = re.findall(r"^\| `(\w+)` \| (`\w+` \(`\w+`\).*) \|$", text, re.MULTILINE)
    return [
        (kind, group, method)
        for group, kinds in rows
        for kind, method in re.findall(r"`(\w+)` \(`(\w+)`\)", kinds)
    ]


def test_vocabulary_matches_the_design_table():
    expected = design_vocabulary()
    assert len(expected) == 42, f"Vocabulary table not found or changed in {DESIGN}"
    assert [(spec.kind, spec.group, spec.service) for spec in EVENT_KINDS.values()] == expected
    assert tuple(dict.fromkeys(group for _, group, _ in expected)) == EVENT_GROUPS
