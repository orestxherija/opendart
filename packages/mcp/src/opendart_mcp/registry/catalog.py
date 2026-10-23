"""Look up OpenDART services, field labels, and value kinds in the generated registry.

Lookups accept SDK names or upstream names, so a tool can label a raw upstream record and a
typed SDK record alike. search_services backs the list_services escape-hatch tool, and
sdk_method turns a ServiceSpec into the SDK coroutine function that calls it.
"""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass
from functools import cache
from typing import TYPE_CHECKING, Any, Final

from opendart_mcp.registry._generated import SERVICES, SERVICE_NAMES
from opendart_mcp.registry.specs import RESOURCES

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from opendart import OpenDart
    from opendart_mcp.registry.specs import FieldKind, FieldSpec, ServiceSpec

_STOPWORDS: Final = frozenset(
    {"a", "an", "and", "by", "etc", "for", "in", "of", "on", "or", "the", "to", "with"}
)
# Analyst shorthand mapped to the catalog's wording; keys are normalized like query words.
_SHORTHAND: Final[dict[str, tuple[str, ...]]] = {
    "bonus": ("consideration",),
    "buyback": ("treasury",),
    "bw": ("warrant",),
    "cb": ("convertible",),
    "coco": ("contingent",),
    "compensation": ("remuneration",),
    "default": ("bankruptcy",),
    "eb": ("exchangeable",),
    "employee": ("staff",),
    "insider": ("executive",),
    "litigation": ("lawsuit",),
    "pay": ("remuneration",),
    "raise": ("increase",),
    "repurchase": ("treasury",),
    "rights": ("paid",),
    "salary": ("remuneration",),
    "spin": ("split",),
    "spinoff": ("split",),
}
# Score per matched query word by where it matches; higher is more specific.
_TITLE: Final = 3
_NAME: Final = 2
_DESCRIPTION: Final = 1
_PHRASE: Final = 3
_EXACT: Final = 100
# Shorter words keep a trailing "s" (gas, bus), and "-ies" needs a longer stem.
_SHORT: Final = 4


def _key(name: str) -> str:
    """Normalize a service name, API ID, or endpoint path for alias lookup.

    Args:
        name (str): User-supplied service identifier.

    Returns:
        str: Case-folded identifier without a leading slash or a .json or .xml suffix.
    """
    return re.sub(r"\.(json|xml)$", "", name.strip().strip("/").casefold())


_ALIASES: Final[dict[str, str]] = {
    alias: spec.name
    for spec in SERVICES.values()
    for alias in (_key(spec.name), _key(spec.api_id), _key(spec.path))
}


def _spec(value: str | ServiceSpec) -> ServiceSpec:
    """Return a ServiceSpec for a name or pass a spec through.

    Args:
        value (str | ServiceSpec): Service name or spec.

    Returns:
        ServiceSpec: The matching spec.
    """
    return service(value) if isinstance(value, str) else value


def service(name: str) -> ServiceSpec:
    """Find a service by SDK method name, upstream API ID, or endpoint path.

    Args:
        name (str): SDK method name (cvbd_is_decsn), API ID (AE00057), or endpoint
            (cvbdIsDecsn, /cvbdIsDecsn.json); matching ignores case.

    Returns:
        ServiceSpec: The matching service.

    Raises:
        KeyError: No service matches; the message suggests close method names.
    """
    spec = SERVICES.get(name) or SERVICES.get(_ALIASES.get(_key(name), ""))
    if spec is not None:
        return spec
    matches = difflib.get_close_matches(_key(name), SERVICE_NAMES, n=3)
    hint = f"; did you mean {", ".join(matches)}?" if matches else ""
    message = f"Unknown OpenDART service {name!r}{hint}"
    raise KeyError(message)


def services(resource: str | None = None) -> tuple[ServiceSpec, ...]:
    """List services in catalog order, optionally for one SDK resource.

    Args:
        resource (str | None): SDK resource attribute, such as major_issues. None lists all.

    Returns:
        tuple[ServiceSpec, ...]: Matching services.

    Raises:
        ValueError: The resource is not an SDK resource.
    """
    if resource is not None and resource not in RESOURCES:
        message = f"Unknown resource {resource!r}; expected one of {", ".join(RESOURCES)}"
        raise ValueError(message)
    return tuple(spec for spec in SERVICES.values() if resource in (None, spec.resource))


@cache
def _fields(name: str, section: str | None) -> dict[str, FieldSpec]:
    """Index a service's fields by Python and wire name; the first occurrence wins.

    Args:
        name (str): SDK method name.
        section (str | None): Registration-statement section title, or None for all records.

    Returns:
        dict[str, FieldSpec]: Fields keyed by both names.
    """
    spec = SERVICES[name]
    groups = [r.fields for r in spec.records if section is None or r.section == section]
    found: dict[str, FieldSpec] = {}
    for field in (*(field for fields in groups for field in fields), *spec.scalar_fields):
        found.setdefault(field.name, field)
        found.setdefault(field.wire, field)
    return found


def field_spec(
    service: str | ServiceSpec, field: str, *, section: str | None = None
) -> FieldSpec | None:
    """Find a response field by its SDK attribute name or upstream name.

    Args:
        service (str | ServiceSpec): Service name or spec.
        field (str): SDK attribute name (filing_number) or upstream name (rcept_no).
        section (str | None): Registration-statement section title, such as "General
            matters", to prefer that section's label where sections reuse a field name.
            Fields outside the section are still found.

    Returns:
        FieldSpec | None: The field, or None when the catalog does not document it.

    Raises:
        KeyError: The service is unknown.
    """
    name = _spec(service).name
    if section is not None and (found := _fields(name, section).get(field)) is not None:
        return found
    return _fields(name, None).get(field)


def field_label(service: str | ServiceSpec, field: str, *, section: str | None = None) -> str:
    """Return a field's catalog label, or the field name when it is undocumented.

    Args:
        service (str | ServiceSpec): Service name or spec.
        field (str): SDK attribute name or upstream name.
        section (str | None): Registration-statement section title; see field_spec.

    Returns:
        str: Label for display.

    Raises:
        KeyError: The service is unknown.
    """
    spec = field_spec(service, field, section=section)
    return field if spec is None else spec.label


def field_kind(service: str | ServiceSpec, field: str, *, section: str | None = None) -> FieldKind:
    """Return how to normalize a field's value; undocumented fields are text.

    Args:
        service (str | ServiceSpec): Service name or spec.
        field (str): SDK attribute name or upstream name.
        section (str | None): Registration-statement section title; see field_spec.

    Returns:
        FieldKind: The field's value kind.

    Raises:
        KeyError: The service is unknown.
    """
    spec = field_spec(service, field, section=section)
    return "text" if spec is None else spec.kind


def _stem(word: str) -> str:
    """Reduce a lowercase word to a crude singular form.

    Args:
        word (str): Lowercase word.

    Returns:
        str: The word without a plural ending.
    """
    if len(word) > _SHORT and word.endswith("ies"):
        return word.removesuffix("ies") + "y"
    if len(word) >= _SHORT and word.endswith("s") and not word.endswith("ss"):
        return word.removesuffix("s")
    return word


def _words(text: str) -> tuple[str, ...]:
    """Split text into lowercase singular words without stopwords.

    Args:
        text (str): Free text.

    Returns:
        tuple[str, ...]: Normalized words in order.
    """
    words = re.findall(r"[a-z0-9]+", text.casefold())
    return tuple(_stem(word) for word in words if word not in _STOPWORDS)


_SYNONYMS: Final = {_stem(word): options for word, options in _SHORTHAND.items()}


@dataclass(frozen=True, slots=True)
class _Entry:
    """Searchable words of one service."""

    spec: ServiceSpec
    title: tuple[str, ...]
    names: frozenset[str]
    description: frozenset[str]

    def score(self, query: str, words: tuple[str, ...]) -> int:
        """Score this service against a query.

        Args:
            query (str): Case-folded query.
            words (tuple[str, ...]): Normalized query words.

        Returns:
            int: Zero for no match; higher is better.
        """
        score = _EXACT if query in {self.spec.name, self.spec.api_id.casefold()} else 0
        for word in words:
            options = {word, *_SYNONYMS.get(word, ())}
            if options.intersection(self.title):
                score += _TITLE
            elif options & self.names:
                score += _NAME
            elif options & self.description:
                score += _DESCRIPTION
        size = len(words)
        starts = range(len(self.title) - size + 1)
        if size > 1 and any(self.title[start : start + size] == words for start in starts):
            score += _PHRASE
        return score


@cache
def _index() -> tuple[_Entry, ...]:
    """Precompute searchable words for every service.

    Returns:
        tuple[_Entry, ...]: One entry per service in catalog order.
    """
    return tuple(
        _Entry(
            spec=spec,
            title=_words(spec.title),
            names=frozenset(
                (
                    *_words(spec.name.replace("_", " ")),
                    *_words(spec.resource),
                    spec.api_id.casefold(),
                )
            ),
            description=frozenset(_words(spec.description)),
        )
        for spec in SERVICES.values()
    )


def search_services(query: str, *, limit: int = 10) -> tuple[ServiceSpec, ...]:
    """Rank services for a free-text query over titles, descriptions, names, and API IDs.

    Scoring is deterministic: each query word scores by the most specific place it matches
    (title, then method name, resource, or API ID, then description), a query found as a
    phrase in a title earns a bonus, and an exact method name or API ID ranks first. Plurals
    and common shorthand such as "CB" or "buyback" match the catalog's wording. Ties keep
    catalog order.

    Args:
        query (str): Keywords such as "convertible bond", "largest shareholder", or "dividend".
        limit (int): Maximum number of services to return.

    Returns:
        tuple[ServiceSpec, ...]: Matching services, best first; empty when nothing matches.
    """
    normalized = query.strip().casefold()
    words = _words(normalized)
    scored = [(entry.score(normalized, words), entry.spec) for entry in _index()]
    # sorted() is stable, so equal scores keep catalog order.
    ranked = sorted((item for item in scored if item[0] > 0), key=lambda item: -item[0])
    return tuple(spec for _, spec in ranked[: max(limit, 0)])


def sdk_method(client: OpenDart, spec: str | ServiceSpec) -> Callable[..., Awaitable[Any]]:
    """Return the bound SDK coroutine function for a service.

    Args:
        client (OpenDart): Open SDK client.
        spec (str | ServiceSpec): Service name or spec.

    Returns:
        Callable[..., Awaitable[Any]]: The method, such as client.major_issues.cvbd_is_decsn;
            call it with the ParamSpec names as keyword arguments.

    Raises:
        KeyError: The service is unknown.
    """
    resolved = _spec(spec)
    method: Callable[..., Awaitable[Any]] = getattr(
        getattr(client, resolved.resource), resolved.name
    )
    return method
