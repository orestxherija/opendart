"""Synthetic directory fixtures for the domain tests; the data lives in ``directory_data``."""

from __future__ import annotations

from collections.abc import Callable

import pytest

from opendart_analysis.domain.directory import CorpRecord, Directory
from packages.analysis.tests.domain.directory_data import (
    LOADED_AT,
    ROWS,
    Row,
    directory_xml,
    record,
    zip_members,
)


@pytest.fixture(scope="session")
def records() -> tuple[CorpRecord, ...]:
    """Every synthetic record."""
    return tuple(record(row) for row in ROWS)


@pytest.fixture(scope="session")
def directory(records: tuple[CorpRecord, ...]) -> Directory:
    """A directory over the synthetic records."""
    return Directory.build(records, loaded_at=LOADED_AT)


@pytest.fixture
def make_archive() -> Callable[..., bytes]:
    """Return a builder for directory archives: rows, raw XML, or explicit members."""

    def build(
        rows: tuple[Row, ...] = ROWS,
        *,
        xml: str | bytes | None = None,
        members: dict[str, bytes | str] | None = None,
    ) -> bytes:
        if members is not None:
            return zip_members(members)
        return zip_members({"CORPCODE.xml": directory_xml(rows) if xml is None else xml})

    return build
