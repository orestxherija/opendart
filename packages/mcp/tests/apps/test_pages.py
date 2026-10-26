"""Page assembly: shared parts first, one inline style and script, nothing that closes early."""

from __future__ import annotations

import pytest

from opendart_mcp.apps import pages
from opendart_mcp.apps.links import FINANCIALS_URI, LEGACY_URI_KEY, app_link


def test_app_links_carry_the_nested_and_the_flat_key():
    assert app_link(FINANCIALS_URI) == {
        "ui": {"resourceUri": "ui://opendart/financials.v1.html"},
        LEGACY_URI_KEY: "ui://opendart/financials.v1.html",
    }


def test_inline_content_may_not_close_its_element():
    assert pages.inline("if (a < b) {}", "script") == "if (a < b) {}"
    with pytest.raises(ValueError, match="must not contain '</script'"):
        pages.inline("const x = '</SCRIPT>';", "script")
    with pytest.raises(ValueError, match="must not contain '</style'"):
        pages.inline("p { } </style>", "style")


def test_a_page_joins_the_shell_shared_parts_and_its_own_parts_in_order():
    page = pages.build_page("peers", title="Peers & more")
    assert "<title>Peers &amp; more</title>" in page
    assert "$" not in page.split("<style>", 1)[0], "every shell placeholder is filled"
    script = page.split("<script>", 1)[1]
    order = ["function connectHost", "function structuredOf", 'const TOOL = "compare_companies"']
    positions = [script.index(marker) for marker in order]
    assert positions == sorted(positions)
    style = page.split("<style>", 1)[1].split("</style>", 1)[0]
    assert style.index("color-scheme: light dark") < style.index("/* Peer comparison app. */")
    assert '<nav id="metrics"' in page
    assert script.startswith('\n(() => {\n"use strict";\n')


def test_every_app_has_its_own_markup_styles_and_script():
    for app in ("financials", "peers", "calendar"):
        for suffix in ("html", "css", "js"):
            assert pages.read_part(f"{app}.{suffix}").strip()
