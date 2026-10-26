"""Immutable descriptions of OpenDART services, their parameters, and their response fields.

scripts/analysis/generate_mcp_registry.py builds one ServiceSpec per upstream service from the API
catalog. Names match the SDK: ServiceSpec.name is the method on the resource attribute
ServiceSpec.resource, ParamSpec.name is the method's keyword argument, and FieldSpec.name is the
attribute on the SDK record model. The wire names are the upstream ones.

Each field has a FieldKind that tells the normalization layer how to read the upstream string:

- amount: money in total, usually KRW and occasionally a foreign currency. Upstream text uses
  commas, blanks, and "-". The only kind that display units, such as millions, scale.
- per_share: money per share or per unit: par value; issue, offering, exercise, conversion,
  and appraisal prices. Never scaled.
- count: a quantity other than money: shares, people, holders, hours, years of service.
- percent: percentage points as filed, so "12.5" means 12.5 percent: shareholding ratios,
  coupons, yields, and ratios to assets or equity.
- ratio: a dimensionless ratio or multiple, sometimes written "1 : 0.5": merger, split, and
  swap ratios, or new shares allotted per share.
- number: a number whose unit depends on the row, such as dividend table columns (KRW
  millions, KRW per share, or percent by row) and financial indicator values.
- date: one calendar day, as YYYYMMDD, YYYY.MM.DD, or YYYY-MM-DD; rarely a year and month.
- period: a span or reporting period: date ranges, fiscal years, the settlement month, and
  statement term dates that are either "as of" dates or ranges.
- code: an identifier or enumerated code: filing numbers, corporation and stock codes, report
  and statement codes, currencies, and bond series ordinals.
- flag: a yes/no fact (upstream "whether" columns); values are Y/N or words.
- text: free text such as names, purposes, reasons, methods, and notes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal, get_args

# Plain aliases rather than type statements, so typing.get_args() lists the values at runtime.
FieldKind = Literal[
    "amount",
    "per_share",
    "count",
    "percent",
    "ratio",
    "number",
    "date",
    "period",
    "code",
    "flag",
    "text",
]
LabelSource = Literal["title", "description", "override", "name"]
Resource = Literal[
    "disclosures",
    "periodic_reports",
    "financial_statements",
    "equity_disclosures",
    "major_issues",
    "securities_registration",
]

FIELD_KINDS: Final[tuple[FieldKind, ...]] = get_args(FieldKind)
RESOURCES: Final[tuple[Resource, ...]] = get_args(Resource)


@dataclass(frozen=True, slots=True)
class ParamSpec:
    """One query parameter of a service, as its SDK method accepts it.

    Attributes:
        name (str): Keyword argument of the SDK method, such as filing_start_date.
        wire (str): Upstream query name, such as bgn_de.
        title (str): Catalog title.
        required (bool): Whether the upstream service requires the parameter.
        description (str): Catalog description, verbatim.
    """

    name: str
    wire: str
    title: str
    required: bool
    description: str


@dataclass(frozen=True, slots=True)
class FieldSpec:
    """One response field with its label and value kind.

    Attributes:
        name (str): Attribute on the SDK model, such as filing_number.
        wire (str): Upstream field name, such as rcept_no.
        label (str): Human-readable label, normally the catalog title.
        description (str): Catalog description, verbatim; often a format placeholder such as
            9,999,999,999.
        kind (FieldKind): How to normalize the upstream string; see the module docstring.
        label_source (LabelSource): Where the label comes from: the catalog title (stripped
            of stray wrapping quotes), the description when the title is blank or meaningless
            out of context, a reviewed override for a truncated or mislabeled title, or the
            field name.
    """

    name: str
    wire: str
    label: str
    description: str
    kind: FieldKind
    label_source: LabelSource = "title"


@dataclass(frozen=True, slots=True)
class RecordSpec:
    """A repeated record container in a response and the fields of its records.

    Attributes:
        path (tuple[str, ...]): Attribute path from the SDK response model to the record list.
            Most services use ("list",). Registration statements use ("group", "list") with
            one RecordSpec per section; the Ver 2.0 remuneration services use ("group",) and
            ("group", "list") for a nested breakdown.
        model (str | None): SDK record model class in opendart.models.<resource>, or None for
            records inside a ZIP archive, which the SDK returns as bytes.
        fields (tuple[FieldSpec, ...]): Record fields in catalog order.
        section (str): Catalog title of a registration-statement section, such as "General
            matters"; empty for other records. Field names can repeat across sections with
            different labels.
    """

    path: tuple[str, ...]
    model: str | None
    fields: tuple[FieldSpec, ...]
    section: str = ""


@dataclass(frozen=True, slots=True)
class ServiceSpec:
    """One upstream OpenDART service and how the SDK exposes it.

    Attributes:
        name (str): SDK method name, such as cvbd_is_decsn or search.
        resource (Resource): SDK client attribute that owns the method, such as major_issues.
        api_id (str): Upstream API ID, such as AE00057.
        group (str): Catalog group code, DE001 to DE006.
        title (str): Catalog title.
        description (str): Catalog description.
        path (str): Upstream endpoint path the SDK calls, such as /cvbdIsDecsn.json.
        guide_url (str): Official English guide for the service.
        params (tuple[ParamSpec, ...]): Query parameters in catalog order, without the key.
        records (tuple[RecordSpec, ...]): Record containers in catalog order.
        scalar_fields (tuple[FieldSpec, ...]): Fields at the top level of the response, outside
            any record, such as the company overview's; status, message, and pagination
            counters are omitted.
        archive (bool): The service returns a ZIP archive, so the SDK method returns bytes.
    """

    name: str
    resource: Resource
    api_id: str
    group: str
    title: str
    description: str
    path: str
    guide_url: str
    params: tuple[ParamSpec, ...] = ()
    records: tuple[RecordSpec, ...] = ()
    scalar_fields: tuple[FieldSpec, ...] = ()
    archive: bool = False

    @property
    def fields(self) -> tuple[FieldSpec, ...]:
        """Return the fields of every record container in catalog order.

        Returns:
            tuple[FieldSpec, ...]: Record-level fields; a name can repeat across sections.
        """
        return tuple(field for record in self.records for field in record.fields)
