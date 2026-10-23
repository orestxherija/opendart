"""Resource URIs of the apps and the tool metadata that links a tool to its app.

Each URI carries its page's version. Hosts may cache ``ui://`` content, so a change to a page
or to the structured content it reads ships under a new URI (``financials.v2.html``) instead
of replacing the page in place.
"""

from __future__ import annotations

from typing import Any, Final

from fastmcp.apps import AppConfig, app_config_to_meta_dict

FINANCIALS_URI: Final = "ui://opendart/financials.v1.html"
"""Financial statements app, linked from get_financials."""

PEERS_URI: Final = "ui://opendart/peers.v1.html"
"""Peer comparison app, linked from compare_companies."""

CALENDAR_URI: Final = "ui://opendart/calendar.v1.html"
"""Corporate-action calendar app, linked from get_corporate_action_calendar."""

LEGACY_URI_KEY: Final = "ui/resourceUri"
"""Deprecated flat link key, still read by hosts built before the nested ``ui`` object."""


def app_link(uri: str) -> dict[str, Any]:
    """Build the tool metadata that asks app-capable hosts to render results with an app.

    Hosts without MCP Apps support ignore the metadata, so the tool's text and structured
    content stay the same everywhere. The flat key is written as well, as the extension's
    reference server helper does.

    Args:
        uri (str): The app's ``ui://`` resource URI.

    Returns:
        dict[str, Any]: Value for the ``meta`` argument of the tool decorator.
    """
    return {"ui": app_config_to_meta_dict(AppConfig(resource_uri=uri)), LEGACY_URI_KEY: uri}
