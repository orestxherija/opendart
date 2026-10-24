"""Per-kind presentation of event reports: headline templates, key terms, derived values.

A headline is a lead fragment followed by optional fragments, each a ``str.format`` template
over named fields. A fragment appears only when every field it names has a value, so one
template serves reports that fill different columns. Values are normalized by registry
field kind and formatted for reading (``KRW 5.0bn``, ``8.52%``, ISO dates). Key terms are
the normalized values of a short list of fields under friendly names: amounts in won,
``*_pct`` in percent. Derived values (a sum of financing purposes, new shares as a percentage
of shares outstanding) behave like fields.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from opendart_analysis.catalog import field_kind
from opendart_mcp.events.values import TEXT_LIMIT, display, shorten

if TYPE_CHECKING:
    from opendart_mcp.events.records import EventRecord
    from opendart_mcp.events.values import Scalar


@dataclass(frozen=True, slots=True)
class Part:
    """A headline fragment, shown only when every field it names has a value.

    Attributes:
        text (str): Template with one ``{}`` per field, in order.
        fields (tuple[str, ...]): SDK field names or derived keys.
    """

    text: str
    fields: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Derived:
    """A value computed from report fields.

    Attributes:
        key (str): Name used in headline parts and key terms.
        kind (Literal["amount", "percent"]): amount sums the fields; percent divides the
            first field by the second and multiplies by 100.
        fields (tuple[str, ...]): SDK field names.
    """

    key: str
    kind: Literal["amount", "percent"]
    fields: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Presentation:
    """How one event kind is summarized.

    Attributes:
        label (str): Short English name, used when the lead fragment has no values.
        lead (Part): First headline fragment, usually the size of the deal.
        parts (tuple[Part, ...]): Further fragments, joined with commas.
        terms (tuple[tuple[str, str], ...]): Concise key terms as (key, field) pairs.
        derived (tuple[Derived, ...]): Values computed from fields.
    """

    label: str
    lead: Part
    parts: tuple[Part, ...] = ()
    terms: tuple[tuple[str, str], ...] = ()
    derived: tuple[Derived, ...] = ()

    def fields(self) -> frozenset[str]:
        """List the SDK fields the presentation reads.

        Returns:
            frozenset[str]: Field names, excluding derived keys.
        """
        keys = {item.key for item in self.derived}
        named = {name for part in (self.lead, *self.parts) for name in part.fields}
        named |= {name for _, name in self.terms}
        named |= {name for item in self.derived for name in item.fields}
        return frozenset(named - keys)


def part(text: str, *fields: str) -> Part:
    """Build a headline fragment.

    Args:
        text (str): Template with one ``{}`` per field.
        *fields (str): Field names or derived keys.

    Returns:
        Part: The fragment.
    """
    return Part(text, fields)


def total(key: str, *fields: str) -> Derived:
    """Declare a sum of amount fields.

    Args:
        key (str): Name of the derived value.
        *fields (str): Amount fields to add; blank ones are skipped.

    Returns:
        Derived: The derived amount.
    """
    return Derived(key, "amount", fields)


def ratio(key: str, numerator: str, denominator: str) -> Derived:
    """Declare one field as a percentage of another.

    Args:
        key (str): Name of the derived value.
        numerator (str): Field divided.
        denominator (str): Field divided by.

    Returns:
        Derived: The derived percentage, rounded to two decimals.
    """
    return Derived(key, "percent", (numerator, denominator))


def _number(value: Scalar) -> float | None:
    """Accept a numeric value, rejecting flags and text.

    Args:
        value (Scalar): Normalized value.

    Returns:
        float | None: The number, or None.
    """
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return value


def _derive(item: Derived, record: EventRecord) -> Scalar:
    """Compute a derived value.

    Args:
        item (Derived): Declaration.
        record (EventRecord): Event rows.

    Returns:
        Scalar: Integer won for sums, a percentage, or None when inputs are missing.
    """
    numbers = [_number(record.value(name)) for name in item.fields]
    known = [number for number in numbers if number is not None]
    if item.kind == "amount":
        return int(sum(known)) if known else None
    if len(known) != len(numbers) or not known[1]:
        return None
    return round(100 * known[0] / known[1], 2)


class Lookup:
    """Normalized field and derived values of one record, with their kinds."""

    def __init__(self, presentation: Presentation, record: EventRecord) -> None:
        """Compute the derived values of a record.

        Args:
            presentation (Presentation): Kind presentation.
            record (EventRecord): Event rows.
        """
        self._record = record
        self._derived = {
            item.key: (item.kind, _derive(item, record)) for item in presentation.derived
        }

    def get(self, name: str) -> tuple[str, Scalar]:
        """Return a value and its field kind.

        Args:
            name (str): SDK field name or derived key.

        Returns:
            tuple[str, Scalar]: Field kind and normalized value.
        """
        if name in self._derived:
            return self._derived[name]
        return field_kind(self._record.service, name), self._record.value(name)

    def render(self, fragment: Part) -> str | None:
        """Fill a headline fragment.

        Args:
            fragment (Part): Fragment to fill.

        Returns:
            str | None: Text, or None when a field has no value.
        """
        shown = [display(*self.get(name)) for name in fragment.fields]
        if any(text is None for text in shown):
            return None
        return fragment.text.format(*shown)


def headline(presentation: Presentation, record: EventRecord) -> str:
    """Summarize an event in one line.

    Args:
        presentation (Presentation): Kind presentation.
        record (EventRecord): Event rows.

    Returns:
        str: Lead fragment (or the label) followed by the fragments that have values.
    """
    lookup = Lookup(presentation, record)
    rest = [text for fragment in presentation.parts if (text := lookup.render(fragment))]
    return ", ".join([lookup.render(presentation.lead) or presentation.label, *rest])


def key_terms(presentation: Presentation, record: EventRecord) -> dict[str, Scalar]:
    """Collect the concise key terms that have values.

    Args:
        presentation (Presentation): Kind presentation.
        record (EventRecord): Event rows.

    Returns:
        dict[str, Scalar]: Friendly key to normalized value; long text is shortened.
    """
    lookup = Lookup(presentation, record)
    terms: dict[str, Scalar] = {}
    for key, name in presentation.terms:
        _, value = lookup.get(name)
        if value is not None and value != "":
            terms[key] = shorten(value, TEXT_LIMIT) if isinstance(value, str) else value
    return terms
