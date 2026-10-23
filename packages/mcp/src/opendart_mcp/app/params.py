"""Argument types shared by tools, so equal concepts get equal schemas.

Descriptions stay short: conventions are explained once in the server instructions and the
``opendart://reference/vocabulary`` resource.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from opendart_mcp.domain.types import Basis, Period, ResponseFormat, Unit

CompanyArg = Annotated[
    str,
    Field(
        min_length=1,
        max_length=100,
        description="Company name (English or Korean), stock code, or 8-digit DART corp code.",
    ),
]
CompaniesArg = Annotated[
    list[Annotated[str, Field(min_length=1, max_length=100)]],
    Field(
        min_length=1,
        max_length=20,
        description="1-20 companies: names, stock codes, or corp codes.",
    ),
]
PeriodArg = Annotated[
    Period, Field(description="latest (most recent periodic report), FY, H1, Q1, or Q3.")
]
FiscalYearArg = Annotated[
    int | None, Field(ge=2015, le=2100, description="Fiscal year; default: latest with the period.")
]
BasisArg = Annotated[
    Basis, Field(description="auto: consolidated if filed, else separate (noted).")
]
UnitArg = Annotated[Unit, Field(description="Unit for monetary amounts; ratios are never scaled.")]
ResponseFormatArg = Annotated[
    ResponseFormat, Field(description="concise: key fields; detailed: every labeled field.")
]
SinceArg = Annotated[
    str,
    Field(min_length=2, max_length=10, description="Start: ISO date or relative (30d, 6m, 2y)."),
]
UntilArg = Annotated[
    str | None,
    Field(
        min_length=2, max_length=10, description="End: ISO date or relative; default today (KST)."
    ),
]
PageArg = Annotated[int, Field(ge=1, le=1000, description="1-based page number.")]
