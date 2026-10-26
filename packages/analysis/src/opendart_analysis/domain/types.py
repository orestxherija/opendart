"""Shared business vocabulary for OpenDART queries and results.

Each alias is a plain ``Literal`` so that ``typing.get_args`` lists its values at runtime,
for example to document or validate the vocabulary.
"""

from __future__ import annotations

from typing import Literal

Market = Literal["KOSPI", "KOSDAQ", "KONEX", "OTHER"]
"""Listing market from OpenDART's ``corp_cls`` (Y, K, N, E)."""

MarketFilter = Literal["all", "KOSPI", "KOSDAQ", "KONEX", "unlisted"]
"""Market restriction accepted by company and filing searches."""

Period = Literal["latest", "FY", "Q1", "H1", "Q3"]
"""Requested reporting period; ``latest`` is resolved to a concrete period."""

ConcretePeriod = Literal["FY", "Q1", "H1", "Q3"]
"""Reporting period with an upstream report code."""

ReportCode = Literal["11011", "11012", "11013", "11014"]
"""Upstream ``reprt_code``: annual, half-year, first quarter, third quarter."""

Unit = Literal["million_krw", "billion_krw", "krw"]
"""Display unit for monetary amounts."""

Basis = Literal["auto", "consolidated", "separate"]
"""Financial statement basis; ``auto`` prefers consolidated statements."""
