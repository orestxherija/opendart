"""Assemble each app's self-contained HTML page from shared and app-specific parts.

Pages are built once, at import, from package data under ``web/``: the shell document, the
shared stylesheet, host bridge, and helpers, and the app's own markup, styles, and script.
Styles and scripts are inlined into one ``<style>`` and one ``<script>`` element, because
hosts load app pages under a content security policy that allows inline code and nothing
else, so a page never references another file or origin.
"""

from __future__ import annotations

from html import escape
from importlib.resources import files
from string import Template
from typing import Final

PACKAGE: Final = "opendart_mcp.apps"
"""Package that holds the page parts."""

PARTS: Final = "web"
"""Directory of the page parts inside the package."""

SHARED_STYLES: Final = ("base.css",)
"""Stylesheets every page starts with, before its own."""

SHARED_SCRIPTS: Final = ("bridge.js", "common.js")
"""Scripts every page starts with, before its own: the host bridge and shared helpers."""


def read_part(name: str) -> str:
    """Read one page part from package data.

    Args:
        name (str): File name inside ``web/``.

    Returns:
        str: File text.
    """
    return files(PACKAGE).joinpath(PARTS, name).read_text(encoding="utf-8")


def inline(text: str, tag: str) -> str:
    """Check that text can sit inside an inline element without closing it early.

    Args:
        text (str): Element content.
        tag (str): Element name, ``style`` or ``script``.

    Returns:
        str: The text, unchanged.

    Raises:
        ValueError: The text contains the element's closing tag.
    """
    if f"</{tag}" in text.lower():
        message = f"Inline <{tag}> content must not contain '</{tag}'."
        raise ValueError(message)
    return text


def build_page(app: str, *, title: str) -> str:
    """Build an app's page from the shell, the shared parts, and the app's own files.

    Args:
        app (str): App name; ``web/`` holds its ``.html`` body, ``.css``, and ``.js``.
        title (str): Document title.

    Returns:
        str: Self-contained HTML document.
    """
    style = "\n".join(read_part(name) for name in (*SHARED_STYLES, f"{app}.css"))
    script = "\n".join(read_part(name) for name in (*SHARED_SCRIPTS, f"{app}.js"))
    return Template(read_part("shell.html")).substitute(
        title=escape(title),
        style=inline(style, "style"),
        body=read_part(f"{app}.html"),
        script=inline(script, "script"),
    )
