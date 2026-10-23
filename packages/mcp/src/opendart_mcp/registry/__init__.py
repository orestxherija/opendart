"""Registry of the 85 OpenDART services: SDK names, catalog labels, value kinds, and events.

SERVICES is generated from api_reference/sources/catalog.json by
scripts/generate_mcp_registry.py; regenerate it rather than editing _generated.py.
"""

from __future__ import annotations

from opendart_mcp.registry._generated import SERVICES, SERVICE_NAMES
from opendart_mcp.registry.catalog import (
    field_kind,
    field_label,
    field_spec,
    sdk_method,
    search_services,
    service,
    services,
)
from opendart_mcp.registry.events import (
    EVENT_GROUPS,
    EVENT_KINDS,
    EVENT_KIND_NAMES,
    EventGroup,
    EventKind,
    EventKindSpec,
    expand,
    kinds_in,
)
from opendart_mcp.registry.specs import (
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
    "sdk_method",
    "search_services",
    "service",
    "services",
]
