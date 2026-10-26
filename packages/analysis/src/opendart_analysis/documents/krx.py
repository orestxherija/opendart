"""KRX HTML builder: exchange disclosures rendered as one ``body`` section.

KRX pages are "xforms" HTML with inline CSS, a ``<title>`` of the form
``company/form/(date)title``, and one or two tables whose entered values sit in
``span.xforms_input``. Styles, scripts, and hidden ``noprint`` elements are dropped.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, override

from opendart_analysis.documents.building import SectionBuilder
from opendart_analysis.documents.markup import MarkupBuilder
from opendart_analysis.documents.tree import DocumentTree, Label, collapse

if TYPE_CHECKING:
    from opendart_analysis.documents.building import Attributes, Frame

_HTML_VOID_TAGS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "param",
        "source",
        "track",
        "wbr",
    }
)
_HIDDEN_STYLE = re.compile(r"display\s*:\s*none", re.IGNORECASE)
_TITLE_PARTS = re.compile(r"^(?P<company>[^/]*)/(?P<form>[^/]*)/\((?P<date>[^)]*)\)(?P<rest>.*)$")
BODY_SECTION_ID = "body"


def title_parts(title: str | None) -> tuple[str | None, str | None]:
    """Split a KRX page title into company and form name.

    Args:
        title (str | None): Page title such as
            ``삼성전자/신규시설투자등/(2026.10.22)신규시설투자등``.

    Returns:
        tuple[str | None, str | None]: Company and form name, or Nones when the title has
            another shape.
    """
    match = _TITLE_PARTS.match(title or "")
    if match is None:
        return None, None
    return collapse(match.group("company")) or None, collapse(match.group("form")) or None


def _classes(attrs: Attributes) -> list[str]:
    """Split an element's class attribute.

    Args:
        attrs (Attributes): Element attributes.

    Returns:
        list[str]: Class names.
    """
    return (attrs.get("class") or "").split()


class KrxBuilder(MarkupBuilder):
    """Build a document tree from one KRX HTML page.

    Attributes:
        page_title (str | None): Text of the page's ``<title>``.
    """

    VOID_TAGS: frozenset[str] = _HTML_VOID_TAGS

    def __init__(self) -> None:
        """Start an empty KRX page."""
        super().__init__()
        self.page_title: str | None = None

    @override
    def skips(self, tag: str, attrs: Attributes) -> bool:
        """Ignore styles, scripts, and hidden elements.

        Args:
            tag (str): Lowercased tag name.
            attrs (Attributes): Element attributes.

        Returns:
            bool: True to ignore the element and its content.
        """
        hidden = "noprint" in _classes(attrs) or bool(
            _HIDDEN_STYLE.search(attrs.get("style") or "")
        )
        return hidden or super().skips(tag, attrs)

    @override
    def style_bold(self, tag: str, attrs: Attributes) -> bool | None:
        """Treat the form title block as bold.

        Args:
            tag (str): Lowercased tag name.
            attrs (Attributes): Element attributes.

        Returns:
            bool | None: The weight the element sets, or None to inherit it.
        """
        if "xforms_title" in _classes(attrs):
            return True
        return super().style_bold(tag, attrs)

    @override
    def current(self) -> SectionBuilder:
        """Return the page's single ``body`` section, creating it on first use.

        Returns:
            SectionBuilder: The body section.
        """
        if not self.open_sections:
            label = Label(self.page_title or "KRX disclosure")
            section = SectionBuilder(BODY_SECTION_ID, 1, label, None, "body", None, (1,))
            self.root.items.append(section)
            self.open_sections.append(section)
        return self.open_sections[-1]

    def build(self) -> DocumentTree:
        """Finish parsing and return the document tree.

        Returns:
            DocumentTree: The parsed page.
        """
        self.current()
        items = tuple(self.finish_items())
        company, form = title_parts(self.page_title)
        return DocumentTree(
            format="krx_html",
            items=items,
            form_name_ko=form,
            company_name=company,
            title=self.page_title,
        )

    def _start_title(self, frame: Frame, attrs: Attributes) -> None:
        """Start capturing the page title.

        Args:
            frame (Frame): Frame for the title element.
            attrs (Attributes): Title attributes, currently unused.
        """
        del frame, attrs
        self.capture = []

    def _end_title(self, frame: Frame) -> None:
        """Record the page title.

        Args:
            frame (Frame): Frame for the closing title element.
        """
        del frame
        self.page_title = collapse("".join(self.capture or ())) or self.page_title
        self.capture = None

    def _start_span(self, frame: Frame, attrs: Attributes) -> None:
        """Mark the open cell as a value cell when the span is a form input.

        Args:
            frame (Frame): Frame for the span element, currently unused.
            attrs (Attributes): Span attributes checked for ``xforms_input``.
        """
        del frame
        cell = self.open_cell()
        if cell is not None and "xforms_input" in _classes(attrs):
            cell.value = True

    def _start_img(self, frame: Frame, attrs: Attributes) -> None:
        """Place an image reference by its alternative text or file name.

        Args:
            frame (Frame): Frame for the image element, currently unused.
            attrs (Attributes): Image attributes containing its source and optional alt text.
        """
        del frame
        source = (attrs.get("src") or "").rsplit("/", 1)[-1]
        self.place_image(attrs.get("alt") or source)
