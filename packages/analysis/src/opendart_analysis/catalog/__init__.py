"""Catalog of the 85 OpenDART services: SDK names, catalog labels, value kinds, and events.

SERVICES is generated from api_reference/sources/catalog.json by
scripts/analysis/generate_mcp_registry.py; regenerate it rather than editing _generated.py. SDK
method and attribute names are data; this package never imports the SDK.
"""

from __future__ import annotations

from opendart_analysis.catalog._generated import SERVICES, SERVICE_NAMES
from opendart_analysis.catalog.catalog import (
    field_kind,
    field_label,
    field_spec,
    search_services,
    service,
    services,
)
from opendart_analysis.catalog.events import (
    EVENT_GROUPS,
    EVENT_KINDS,
    EVENT_KIND_NAMES,
    EventGroup,
    EventKind,
    EventKindSpec,
    expand,
    kinds_in,
)
from opendart_analysis.catalog.specs import (
    FIELD_KINDS,
    RESOURCES,
    FieldKind,
    FieldSpec,
    LabelSource,
    ParamSpec,
    RecordSpec,
    Resource,
    ServiceSpec,
)

__all__ = [
    "EVENT_GROUPS",
    "EVENT_KINDS",
    "EVENT_KIND_NAMES",
    "FIELD_KINDS",
    "RESOURCES",
    "SERVICES",
    "SERVICE_NAMES",
    "EventGroup",
    "EventKind",
    "EventKindSpec",
    "FieldKind",
    "FieldSpec",
    "LabelSource",
    "ParamSpec",
    "RecordSpec",
    "Resource",
    "ServiceSpec",
    "expand",
    "field_kind",
    "field_label",
    "field_spec",
    "kinds_in",
    "search_services",
    "service",
    "services",
]
