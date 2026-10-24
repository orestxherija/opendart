"""Parameters for call_service: names, types, accepted forms, and conversion.

Names may be SDK names, upstream names, or the topical tools' names (company, since, until,
period). Types come from the SDK method signatures, so integer, list, and choice parameters
are checked before the call. Company parameters accept names and stock codes, dates accept
ISO or relative forms, and report codes accept FY, H1, Q1, or Q3. Company lists hold 1 to 100
entries, checked before any company is resolved, and may be one comma-separated string.
"""

from __future__ import annotations

import typing
from dataclasses import dataclass, field
from functools import cache
from types import NoneType
from typing import TYPE_CHECKING, Final, Literal, get_args, get_origin

from opendart.resources.disclosures import Disclosures
from opendart.resources.equity_disclosures import EquityDisclosures
from opendart.resources.financial_statements import FinancialStatements
from opendart.resources.major_issues import MajorIssues
from opendart.resources.periodic_reports import PeriodicReports
from opendart.resources.securities_registration import SecuritiesRegistration
from opendart_analysis.domain.dates import parse_date_arg, yyyymmdd
from opendart_analysis.domain.identifiers import is_corp_code
from opendart_analysis.domain.names import split_names
from opendart_analysis.domain.periods import FIRST_FISCAL_YEAR, REPORT_CODES
from opendart_mcp.core.errors import InvalidArgumentError
from opendart_mcp.registry import service

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import date

    from opendart_mcp.core.progress import Progress
    from opendart_mcp.core.state import AppState
    from opendart_mcp.models.services import ParamValue
    from opendart_mcp.registry import ParamSpec, ServiceSpec

_SDK_CLASSES: Final[dict[str, type]] = {
    "disclosures": Disclosures,
    "equity_disclosures": EquityDisclosures,
    "financial_statements": FinancialStatements,
    "major_issues": MajorIssues,
    "periodic_reports": PeriodicReports,
    "securities_registration": SecuritiesRegistration,
}
ALIASES: Final[dict[str, str]] = {
    "company": "corp_code",
    "companies": "corp_code",
    "since": "bgn_de",
    "until": "end_de",
    "period": "reprt_code",
    "year": "bsns_year",
}
"""Topical-tool argument names accepted for upstream parameters."""

_DATE_HINT: Final = "date: 2025-01-01, 20250101, or relative such as 90d"
_HINTS: Final[dict[str, str]] = {
    "corp_code": "company name, stock code, or 8-digit corp code",
    "bgn_de": _DATE_HINT,
    "end_de": _DATE_HINT,
    "bsns_year": f"fiscal year, {FIRST_FISCAL_YEAR} or later",
    "reprt_code": "FY, H1, Q1, Q3, or a report code such as 11011",
    "rcept_no": "14-digit filing number",
}
MAX_LIST_ITEMS: Final = 100
"""Most entries a list parameter takes; OpenDART accepts 1 to 100 corp codes per call."""
_MANY_HINT: Final = f"list of companies (names or codes), up to {MAX_LIST_ITEMS}"
_REPORT_CODES: Final[dict[str, str]] = {
    **{str(period): str(code) for period, code in REPORT_CODES.items()},
    **{str(code): str(code) for code in REPORT_CODES.values()},
}
_MAX_LISTED_CHOICES: Final = 12
_YEAR_DIGITS: Final = 4


@dataclass(frozen=True, slots=True)
class Shape:
    """How an SDK method parameter is typed.

    Attributes:
        many (bool): Takes a list of strings.
        integer (bool): Takes an integer.
        choices (tuple[str, ...]): Allowed values; empty for free text.
    """

    many: bool = False
    integer: bool = False
    choices: tuple[str, ...] = ()


def _members(hint: object) -> tuple[object, ...]:
    """Flatten a union annotation, dropping None.

    Args:
        hint (object): Evaluated annotation.

    Returns:
        tuple[object, ...]: Member types.
    """
    if get_origin(hint) is typing.Union:
        return tuple(member for arg in get_args(hint) for member in _members(arg))
    return () if hint is NoneType else (hint,)


@cache
def param_shapes(name: str) -> dict[str, Shape]:
    """Read parameter types from the SDK method behind a service.

    Args:
        name (str): SDK method name.

    Returns:
        dict[str, Shape]: Shapes keyed by SDK parameter name.
    """
    spec = service(name)
    hints = typing.get_type_hints(getattr(_SDK_CLASSES[spec.resource], spec.name))
    shapes: dict[str, Shape] = {}
    for param in spec.params:
        members = _members(hints[param.name])
        choices = [str(v) for m in members if get_origin(m) is Literal for v in get_args(m)]
        shapes[param.name] = Shape(
            many=any(get_origin(m) is list for m in members),
            integer=int in members,
            choices=tuple(choices),
        )
    return shapes


def accepts(spec: ServiceSpec, param: ParamSpec) -> str:
    """Describe the values a parameter accepts.

    Args:
        spec (ServiceSpec): Service.
        param (ParamSpec): Parameter.

    Returns:
        str: Short description, such as the allowed codes.
    """
    shape = param_shapes(spec.name)[param.name]
    if shape.many:
        return _MANY_HINT
    if param.wire in _HINTS:
        return _HINTS[param.wire]
    if not shape.choices:
        return "whole number" if shape.integer else param.title
    shown = ", ".join(shape.choices[:_MAX_LISTED_CHOICES])
    more = f", ... ({len(shape.choices)} codes)" if len(shape.choices) > _MAX_LISTED_CHOICES else ""
    return f"one of {shown}{more}"


def _param_names(spec: ServiceSpec) -> str:
    """List a service's parameters for error messages.

    Args:
        spec (ServiceSpec): Service.

    Returns:
        str: Upstream names with required ones marked.
    """
    names = [f"{p.wire} ({"required" if p.required else "optional"})" for p in spec.params]
    return ", ".join(names) or "none"


def bind(
    spec: ServiceSpec, params: dict[str, ParamValue]
) -> dict[str, tuple[ParamSpec, ParamValue]]:
    """Match parameter names to a service's parameters.

    Args:
        spec (ServiceSpec): Service.
        params (dict[str, ParamValue]): Values by SDK name, upstream name, or alias.

    Returns:
        dict[str, tuple[ParamSpec, ParamValue]]: Parameter and value by upstream name.

    Raises:
        InvalidArgumentError: A name is unknown or repeated, or a required parameter is missing.
    """
    known = {key.casefold(): p for p in spec.params for key in (p.name, p.wire)}
    bound: dict[str, tuple[ParamSpec, ParamValue]] = {}
    for key, value in params.items():
        folded = key.strip().casefold()
        param = known.get(folded) or known.get(ALIASES.get(folded, ""))
        if param is None:
            message = f"{spec.name} has no parameter '{key}'. Parameters: {_param_names(spec)}."
            raise InvalidArgumentError(message)
        if param.wire in bound:
            message = f"Parameter {param.wire} was given twice; pass it once."
            raise InvalidArgumentError(message)
        bound[param.wire] = (param, value)
    if missing := [p.wire for p in spec.params if p.required and p.wire not in bound]:
        message = f"{spec.name} requires {", ".join(missing)}. Parameters: {_param_names(spec)}."
        raise InvalidArgumentError(message)
    return bound


def _date(param: ParamSpec, text: str, today: date) -> str:
    """Convert a date argument to YYYYMMDD.

    Args:
        param (ParamSpec): Parameter.
        text (str): ISO, compact, or relative date.
        today (date): Today in KST.

    Returns:
        str: Eight digits.

    Raises:
        InvalidArgumentError: The date is invalid.
    """
    try:
        return yyyymmdd(parse_date_arg(text, today=today))
    except ValueError as error:
        message = f"{param.wire}: {error}"
        raise InvalidArgumentError(message) from error


def _report_code(param: ParamSpec, text: str, today: date) -> str:
    """Convert a period such as FY to its report code.

    Args:
        param (ParamSpec): Parameter.
        text (str): FY, H1, Q1, Q3, or a report code.
        today (date): Unused; converters share one signature.

    Returns:
        str: Report code.

    Raises:
        InvalidArgumentError: The value is neither a period nor a report code.
    """
    del today
    code = _REPORT_CODES.get(text.upper())
    if code is None:
        message = f"{param.wire} must be FY, H1, Q1, Q3, or a report code (11011, 11012, 11013, 11014); got '{text}'."
        raise InvalidArgumentError(message)
    return code


def _year(param: ParamSpec, text: str, today: date) -> str:
    """Check a fiscal year.

    Args:
        param (ParamSpec): Parameter.
        text (str): Four-digit year.
        today (date): Today in KST; the year may be at most next year.

    Returns:
        str: The year.

    Raises:
        InvalidArgumentError: The year is malformed or out of range.
    """
    last = today.year + 1
    if (
        len(text) != _YEAR_DIGITS
        or not text.isdecimal()
        or not FIRST_FISCAL_YEAR <= int(text) <= last
    ):
        message = (
            f"{param.wire} must be a fiscal year from {FIRST_FISCAL_YEAR} to {last}; got '{text}'."
        )
        raise InvalidArgumentError(message)
    return text


def _entries(param: ParamSpec, value: ParamValue) -> list[str]:
    """Read the entries of a list parameter, checking their number before any is resolved.

    Args:
        param (ParamSpec): Parameter.
        value (ParamValue): A list, or one string of comma-separated entries.

    Returns:
        list[str]: 1 to ``MAX_LIST_ITEMS`` non-blank entries.

    Raises:
        InvalidArgumentError: The list is empty or too long.
    """
    entries = value if isinstance(value, list) else split_names(str(value))
    items = [entry for entry in entries if entry.strip()]
    if not 1 <= len(items) <= MAX_LIST_ITEMS:
        message = f"{param.wire} takes 1 to {MAX_LIST_ITEMS} companies per call; got {len(items)}. Split a longer list into several calls."
        raise InvalidArgumentError(message)
    return items


_CONVERTERS: Final[dict[str, Callable[[ParamSpec, str, date], str]]] = {
    "bgn_de": _date,
    "end_de": _date,
    "reprt_code": _report_code,
    "bsns_year": _year,
}


@dataclass(slots=True)
class Converter:
    """Convert one call's parameter values to what the SDK method expects.

    Attributes:
        spec (ServiceSpec): Service being called.
        state (AppState): Server state, for company resolution and today's date.
        progress (Progress): Progress callback for company resolution.
        notes (list[str]): Notes about resolved companies.
    """

    spec: ServiceSpec
    state: AppState
    progress: Progress
    notes: list[str] = field(default_factory=list)

    async def corp_code(self, text: str) -> str:
        """Resolve a company argument to a corp code.

        Args:
            text (str): Name, stock code, or corp code.

        Returns:
            str: 8-digit corp code.
        """
        if is_corp_code(text):
            return text
        company = await self.state.companies.resolve(text, progress=self.progress)
        self.notes.append(
            f"Resolved '{text}' to {company.ref.name} (corp code {company.corp_code})."
        )
        return company.corp_code

    async def text(self, param: ParamSpec, shape: Shape, value: str | int) -> str:
        """Convert one text value and check it against the allowed choices.

        Args:
            param (ParamSpec): Parameter.
            shape (Shape): Parameter type.
            value (str | int): Value as given.

        Returns:
            str: Value to send.

        Raises:
            InvalidArgumentError: The value is not allowed.
        """
        text = str(value).strip()
        if param.wire == "corp_code":
            return await self.corp_code(text)
        convert = _CONVERTERS.get(param.wire)
        text = convert(param, text, self.state.today()) if convert else text
        if not shape.choices:
            return text
        chosen = next((c for c in shape.choices if c.casefold() == text.casefold()), None)
        if chosen is None:
            message = f"{param.wire} must be one of {", ".join(shape.choices)}; got '{text}'."
            raise InvalidArgumentError(message)
        return chosen

    async def value(self, param: ParamSpec, value: ParamValue) -> ParamValue:
        """Convert a value to the type the SDK method expects.

        Args:
            param (ParamSpec): Parameter of the service being called.
            value (ParamValue): Value as given.

        Returns:
            ParamValue: Value to send.

        Raises:
            InvalidArgumentError: The value has the wrong type or is not allowed.
        """
        shape = param_shapes(self.spec.name)[param.name]
        if shape.many:
            items = _entries(param, value)
            return [await self.text(param, shape, item) for item in items]
        if isinstance(value, list):
            message = f"{param.wire} takes one value, not a list."
            raise InvalidArgumentError(message)
        if not shape.integer:
            return await self.text(param, shape, value)
        if isinstance(value, int) or value.strip().isdecimal():
            return int(value)
        message = f"{param.wire} must be a whole number; got '{value}'."
        raise InvalidArgumentError(message)
