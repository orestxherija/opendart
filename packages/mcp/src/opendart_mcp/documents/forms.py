"""Form names, document keys, and form families.

Documents name their form in Korean (``DOCUMENT-NAME`` or the KRX page title). English names
come from a short table of common forms, then from the filing's own English cover or decision
headings.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

from opendart_mcp.documents.tree import compact, walk_sections

if TYPE_CHECKING:
    from opendart_mcp.documents.models import DocumentFormat
    from opendart_mcp.documents.tree import DocumentTree

ANNUAL_REPORT = "11011"
PERIODIC_FORMS = frozenset({"11011", "11012", "11013", "11014"})
INTERIM_FORMS = frozenset({"11012", "11013", "11014"})
DART_VIEWER = "https://englishdart.fss.or.kr/dsbh001/main.do?rcpNo={filing_number}"

_KNOWN_FORMS: dict[str, str] = {
    "11011": "Annual Report",
    "11012": "Semi-annual Report",
    "11013": "Quarterly Report",
    "11014": "Quarterly Report",
    "00760": "Audit Report",
    "00761": "Consolidated Audit Report",
}
_KRX_FORMS: dict[str, str] = {
    compact("연결재무제표기준영업(잠정)실적(공정공시)"): (
        "Report on Business Performance according to Consolidated Financial Statements (Fair Disclosure)"
    ),
    compact("영업(잠정)실적(공정공시)"): "Report on Business Performance (Fair Disclosure)",
}
_ATTACHMENT_KEYS: dict[str, str] = {"00760": "audit_report", "00761": "consolidated_audit_report"}
_MAJOR_ISSUES = "주요사항보고서"
_DECISION_CODE = "D-0-1-0-0"
_UNSAFE_KEY = re.compile(r"[^A-Za-z0-9._-]+")


def dart_url(filing_number: str) -> str:
    """Return the English DART viewer link for a filing.

    Args:
        filing_number (str): 14-digit filing number.

    Returns:
        str: Viewer URL.
    """
    return DART_VIEWER.format(filing_number=filing_number)


def english_form_name(tree: DocumentTree) -> str | None:
    """Find an English name for a document's form.

    Args:
        tree (DocumentTree): Parsed document.

    Returns:
        str | None: English form name, or None when the filing offers none.
    """
    known = _KNOWN_FORMS.get(tree.form_code or "")
    if known is not None:
        return known
    if tree.format == "krx_html":
        return _KRX_FORMS.get(compact(tree.form_name_ko or ""))
    if (tree.form_name_ko or "").startswith(_MAJOR_ISSUES):
        decision = _decision_title(tree)
        if decision:
            return f"Report on Major Issues ({decision})"
    return tree.cover_title_en or _first_english_title(tree)


def _decision_title(tree: DocumentTree) -> str | None:
    """Return the English heading of a major-issue report's decision section.

    Args:
        tree (DocumentTree): Parsed document.

    Returns:
        str | None: Heading such as ``Decision on Issuance of Convertible Bonds``.
    """
    for section in walk_sections(tree.items):
        if section.code == _DECISION_CODE:
            return section.title.en
    return None


def _first_english_title(tree: DocumentTree) -> str | None:
    """Return the first English section heading.

    Args:
        tree (DocumentTree): Parsed document.

    Returns:
        str | None: Heading, or None.
    """
    return next((s.title.en for s in walk_sections(tree.items) if s.title.en), None)


def document_key(member: str, filing_number: str) -> str:
    """Derive a document key from an archive member name.

    ``{filing}.xml`` is ``main``; ``{filing}_00760.xml`` is ``audit_report``;
    ``{filing}_00761.xml`` is ``consolidated_audit_report``; other attachments use their form
    code.

    Args:
        member (str): Archive member name.
        filing_number (str): 14-digit filing number.

    Returns:
        str: Document key.
    """
    stem = member.rsplit("/", 1)[-1].rsplit(".", 1)[0]
    if stem == filing_number:
        return "main"
    if stem.startswith(f"{filing_number}_"):
        code = stem.removeprefix(f"{filing_number}_")
        return _ATTACHMENT_KEYS.get(code, _UNSAFE_KEY.sub("_", code) or "attachment")
    return _UNSAFE_KEY.sub("_", stem) or "attachment"


def document_keys(
    names: list[str], formats: list[DocumentFormat | None], filing_number: str
) -> list[str]:
    """Assign unique document keys; the first markup member is ``main`` if none is named so.

    Args:
        names (list[str]): Member names in archive order.
        formats (list[DocumentFormat | None]): Their formats; None for non-markup members.
        filing_number (str): 14-digit filing number.

    Returns:
        list[str]: One key per member.
    """
    preferred = [document_key(name, filing_number) for name in names]
    markup = [index for index, found in enumerate(formats) if found is not None]
    if not any(preferred[index] == "main" for index in markup):
        preferred = ["member" if key == "main" else key for key in preferred]
        preferred[markup[0]] = "main"
    used: set[str] = set()
    return [unique_key(key, used) for key in preferred]


def unique_key(key: str, keys: set[str]) -> str:
    """Make a document key unique within the archive.

    Args:
        key (str): Preferred key.
        keys (set[str]): Keys already used; updated in place.

    Returns:
        str: The key, or the key with a ``~N`` suffix.
    """
    unique, counter = key, 1
    while unique in keys:
        counter += 1
        unique = f"{key}~{counter}"
    keys.add(unique)
    return unique
