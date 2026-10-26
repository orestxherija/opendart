"""Output models for the escape-hatch tools: the upstream service catalog and direct calls."""

from __future__ import annotations

from pydantic import Field

from opendart_analysis.catalog.specs import FieldKind
from opendart_mcp.models.common import OutputModel, Pagination, ToolOutput

type Cell = str | int | float | None
"""A normalized value: exact won and counts as integers, percentages as floats, ISO dates."""

type ParamValue = str | int | list[str]
"""A parameter value as call_service accepts and sends it."""


class ServiceParam(OutputModel):
    """One parameter of an upstream service."""

    name: str = Field(description="Parameter name; the upstream name also works.")
    wire: str = Field(description="Upstream parameter name.")
    required: bool
    accepts: str = Field(description="Values the parameter accepts.")


class ServiceInfo(OutputModel):
    """An upstream service that call_service can call."""

    service: str = Field(description="Name to pass to call_service.")
    title: str
    description: str
    params: list[ServiceParam]
    covered_by: str | None = Field(
        default=None, description="Tool that already serves this data; prefer it."
    )


class ServiceListResult(ToolOutput):
    """Upstream services matching a search, best first."""

    query: str | None = None
    total: int = Field(description="Services matching the query.")
    services: list[ServiceInfo]


class ServiceColumn(OutputModel):
    """A response field with its catalog label and value kind."""

    name: str = Field(description="Field name in the SDK record.")
    label: str
    kind: FieldKind


class ServiceTable(OutputModel):
    """Records from one part of a service response."""

    section: str | None = Field(default=None, description="Registration-statement section.")
    common: dict[str, Cell] | None = Field(
        default=None, description="Values shared by every row, by label."
    )
    columns: list[ServiceColumn]
    rows: list[list[Cell]] = Field(description="Values aligned with columns.")
    raw: list[list[str | None]] | None = Field(
        default=None, description="Upstream text aligned with columns."
    )


class ServiceCallResult(ToolOutput):
    """Records returned by one upstream service call."""

    service: str
    title: str
    params: dict[str, ParamValue] = Field(description="Upstream parameters sent.")
    tables: list[ServiceTable]
    pagination: Pagination
