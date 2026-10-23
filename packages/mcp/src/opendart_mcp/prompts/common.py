"""Shared pieces of the workflow prompts: the subject company, analysis rules, and arguments.

Prompts resolve their company once and pass its corp code to every tool call, attaching the
company profile resource when it can be read. A company that cannot be resolved does not fail
the prompt: the instructions carry the reason, and the model resolves it with find_company.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from fastmcp.exceptions import FastMCPError
from fastmcp.prompts import Message
from mcp.types import EmbeddedResource, TextResourceContents

from opendart_mcp.core.errors import InvalidArgumentError, ServerError
from opendart_mcp.domain.dates import parse_date_arg, parse_horizon
from opendart_mcp.domain.names import split_names
from opendart_mcp.domain.normalize import parse_decimal
from opendart_mcp.domain.periods import FIRST_FISCAL_YEAR
from opendart_mcp.render.markdown import company_line

if TYPE_CHECKING:
    from collections.abc import Iterable

    from fastmcp import Context

    from opendart_mcp.core.state import AppState

RULES: Final = (
    "Rules: use consolidated figures unless a tool reports a fallback to separate "
    + "statements; cite the filing number behind every fact; label estimates and derived "
    + "figures; OpenDART has no prices, volumes, or market capitalization, so never estimate "
    + "price-based metrics; state as-of and period-end dates."
)
"""Analysis rules every workflow follows."""

MAX_COMPANIES: Final = 20
_FILING_NUMBER: Final = re.compile(r"(?<![0-9])[0-9]{14}(?![0-9])")


@dataclass(frozen=True, slots=True)
class Subject:
    """The company a prompt is about.

    Attributes:
        name (str): Display name for the instructions.
        arg (str): Value for tool ``company`` arguments: the corp code once resolved.
        attachments (tuple[Message, ...]): The embedded company profile, when readable.
        note (str | None): Why the company could not be resolved, if it could not.
    """

    name: str
    arg: str
    attachments: tuple[Message, ...] = ()
    note: str | None = None

    @property
    def fields(self) -> dict[str, str]:
        """Template fields shared by single-company prompts.

        Returns:
            dict[str, str]: ``name``, ``arg`` (a JSON string literal), and ``rules``.
        """
        return {"name": self.name, "arg": quoted(self.arg), "rules": RULES}

    def messages(self, instructions: str) -> list[Message]:
        """Build the prompt messages: the attached profile, then the instructions.

        Args:
            instructions (str): Workflow text.

        Returns:
            list[Message]: Prompt messages.
        """
        lines = [instructions.rstrip()]
        if self.attachments:
            lines.append("The company profile is attached above.")
        if self.note:
            lines.append(f"Note: {self.note} Resolve the company with find_company first.")
        return [*self.attachments, Message("\n\n".join(lines))]


def quoted(value: object) -> str:
    """Write a value as a JSON literal for tool-call examples.

    Args:
        value (object): String, number, or list.

    Returns:
        str: JSON text, keeping Korean characters readable.
    """
    return json.dumps(value, ensure_ascii=False)


async def _profile(ctx: Context, corp_code: str) -> tuple[Message, ...]:
    """Read the company profile resource as an embedded resource message.

    Args:
        ctx (Context): Request context.
        corp_code (str): 8-digit corp code.

    Returns:
        tuple[Message, ...]: One message, or none when the profile cannot be read.
    """
    uri = f"opendart://company/{corp_code}"
    try:
        result = await ctx.read_resource(uri)
    except FastMCPError, ServerError:
        return ()
    first = result.contents[0]
    text = first.content if isinstance(first.content, str) else first.content.decode()
    contents = TextResourceContents(
        uri=uri, mime_type=first.mime_type or "application/json", text=text
    )
    return (Message(EmbeddedResource(type="resource", resource=contents)),)


async def subject(state: AppState, ctx: Context, company: str) -> Subject:
    """Resolve a prompt's company and attach its profile.

    Args:
        state (AppState): Server state.
        ctx (Context): Request context.
        company (str): Name, stock code, or corp code.

    Returns:
        Subject: The resolved company, or the text with the reason it did not resolve.

    Raises:
        InvalidArgumentError: The argument is blank.
    """
    text = company.strip()
    if not text:
        message = "company is required: pass a company name, stock code, or DART corp code."
        raise InvalidArgumentError(message)
    try:
        resolved = await state.companies.resolve(text)
    except ServerError as error:
        return Subject(name=text, arg=text, note=f"'{text}' was not resolved: {error}")
    attachments = await _profile(ctx, resolved.corp_code)
    return Subject(company_line(resolved.ref), resolved.corp_code, attachments)


def check_choice(name: str, value: str, options: Iterable[str]) -> str:
    """Match an argument against allowed values, ignoring case.

    Args:
        name (str): Argument name, for the error message.
        value (str): Value given.
        options (Iterable[str]): Allowed values.

    Returns:
        str: The allowed value as spelled in options.

    Raises:
        InvalidArgumentError: The value is not allowed.
    """
    allowed = tuple(options)
    found = next((o for o in allowed if o.casefold() == value.strip().casefold()), None)
    if found is None:
        message = f"{name} must be one of {", ".join(allowed)}; got '{value}'."
        raise InvalidArgumentError(message)
    return found


def check_year(value: str, state: AppState) -> int | None:
    """Check an optional fiscal year argument.

    Args:
        value (str): Four-digit year, or blank for the latest.
        state (AppState): Server state, for today's date.

    Returns:
        int | None: The year, or None when blank.

    Raises:
        InvalidArgumentError: The year is malformed or out of range.
    """
    text = value.strip()
    if not text:
        return None
    last = state.today().year + 1
    if not text.isdecimal() or not FIRST_FISCAL_YEAR <= int(text) <= last:
        message = f"fiscal_year must be a year from {FIRST_FISCAL_YEAR} to {last}, or blank for the latest; got '{value}'."
        raise InvalidArgumentError(message)
    return int(text)


def check_window(name: str, value: str, state: AppState, *, forward: bool = False) -> str:
    """Check a date or duration argument such as 7d or 2025-01-01.

    Args:
        name (str): Argument name, for the error message.
        value (str): Date or duration.
        state (AppState): Server state, for today's date.
        forward (bool): Whether durations count forward, as calendar horizons do.

    Returns:
        str: The value, stripped.

    Raises:
        InvalidArgumentError: The value is not a date or duration.
    """
    text = value.strip()
    parse = parse_horizon if forward else parse_date_arg
    try:
        parse(text, today=state.today())
    except ValueError as error:
        message = f"{name}: {error}"
        raise InvalidArgumentError(message) from error
    return text


def split_companies(value: str) -> list[str]:
    """Split a list of companies separated by commas, semicolons, or new lines.

    Legal-form fragments left by names such as ``SAMSUNG ELECTRONICS CO,.LTD`` are joined
    back to the name before them.

    Args:
        value (str): Company names or codes.

    Returns:
        list[str]: 1-20 companies.

    Raises:
        InvalidArgumentError: The list is empty or too long.
    """
    companies = split_names(value)
    if not 1 <= len(companies) <= MAX_COMPANIES:
        message = f"companies must list 1 to {MAX_COMPANIES} companies separated by commas; got {len(companies)}."
        raise InvalidArgumentError(message)
    return companies


def find_filing_number(value: str) -> str:
    """Find a 14-digit filing number, also inside a DART viewer link.

    Args:
        value (str): Filing number or link.

    Returns:
        str: The filing number.

    Raises:
        InvalidArgumentError: The value contains no filing number.
    """
    match = _FILING_NUMBER.search(value)
    if match is None:
        message = f"filing_number must be a 14-digit filing number such as 20250312000123; got '{value}'. Find it with search_filings."
        raise InvalidArgumentError(message)
    return match.group(0)


def check_price(value: str) -> str | None:
    """Check an optional share price in won.

    Args:
        value (str): Price such as 71,500, or blank.

    Returns:
        str | None: The price with thousands separators, or None when blank.

    Raises:
        InvalidArgumentError: The value is not a positive number.
    """
    text = value.strip().removeprefix("KRW").removeprefix("₩").removesuffix("원").strip()
    if not text:
        return None
    price = parse_decimal(text)
    if price is None or price <= 0:
        message = f"share_price must be a positive price in won, such as 71500; got '{value}'."
        raise InvalidArgumentError(message)
    return f"{price:,}"
