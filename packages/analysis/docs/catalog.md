# Service catalog

Part of the [opendart-analysis guide](../README.md).

`opendart_analysis.catalog` describes all 85 OpenDART services: SDK method and resource names (as data; the package
never imports the SDK), upstream API IDs and paths, parameters, response fields with catalog labels, and a value kind
per field (amount, per_share, count, percent, ratio, number, date, period, code, flag, text).

- `service()` accepts a method name, API ID, or endpoint path.
- `field_label()` and `field_kind()` accept SDK or upstream field names.
- `search_services()` ranks services for free text, including analyst shorthand such as "CB" and "buyback".
- `EVENT_KINDS`, `EVENT_GROUPS`, `expand()`, and `kinds_in()` define the 42 corporate-event kinds in 8 groups with
  their date fields.

```python
from opendart_analysis.catalog import field_label, search_services, service

service("AE00057").name  # "cvbd_is_decsn"
field_label("search", "rcept_no")  # "Filing No."
[spec.name for spec in search_services("convertible bond", limit=3)]
```

`SERVICES` is generated from `api_reference/sources/catalog.json` and the SDK generator's naming rules by
`scripts/generate_mcp_registry.py`. Regenerate it with `just analysis generate`; CI runs `just analysis generated` to
check that it is fresh. Binding a service to an SDK client method belongs to the caller; MCP does it with
`opendart_mcp.services.sdk_binding.sdk_method`.
