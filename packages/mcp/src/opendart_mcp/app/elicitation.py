"""Ask the user to pick a company when a name is ambiguous, if the host supports it.

Two protocol eras need two mechanisms. On 2026-07-28 connections the tool ends the round
with an ``InputRequiredResult`` and the client retries with the user's answer in
``ctx.input_responses`` (the guard pattern). On 2025-11-25 sessions the server sends an
elicitation request and awaits the answer. Hosts without elicitation, and background tasks,
get no chooser, so resolution fails with a candidate list as before.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from fastmcp import Context
from mcp.types import ElicitRequest, ElicitRequestFormParams, ElicitResult, InputRequiredResult
from mcp_types.version import MODERN_PROTOCOL_VERSIONS

from opendart_analysis.domain.resolver import company_label
from opendart_mcp.core.state import AppState

if TYPE_CHECKING:
    from opendart_analysis.domain.directory import CorpRecord, Match
    from opendart_mcp.core.interaction import Chooser

MAX_CHOICES = 8

logger = logging.getLogger(__name__)


class InputRequiredError(Exception):
    """Ends the current tool round with a request for user input (2026-07-28 guard pattern).

    Attributes:
        result (InputRequiredResult): What to send to the client.
    """

    def __init__(self, result: InputRequiredResult) -> None:
        """Wrap the input request.

        Args:
            result (InputRequiredResult): What to send to the client.
        """
        super().__init__("input required")
        self.result = result


def client_can_elicit(ctx: Context) -> bool:
    """Report whether the client declared the elicitation capability.

    Args:
        ctx (Context): Request context.

    Returns:
        bool: False in background tasks, which have no session.
    """
    try:
        capabilities = ctx.session.client_capabilities
    except RuntimeError:
        return False
    return capabilities is not None and capabilities.elicitation is not None


def _key(query: str) -> str:
    """Name the input request for one ambiguous query.

    Args:
        query (str): Company text as the caller passed it.

    Returns:
        str: Input request key, distinct per query within one call.
    """
    return f"company:{query.strip().casefold()}"


def _message(query: str) -> str:
    """Phrase the question.

    Args:
        query (str): Company text as the caller passed it.

    Returns:
        str: Question for the user.
    """
    return f"'{query}' matches several companies. Which one do you mean?"


def _request(
    query: str, candidates: tuple[Match, ...], answers: dict[str, str]
) -> InputRequiredResult:
    """Build the input request listing candidates by corporation code.

    Answers from earlier rounds travel in ``request_state``, which FastMCP seals: clients
    resend only the latest round's answers, so a call with several ambiguous companies
    would otherwise ask for the first one again forever.

    Args:
        query (str): Company text as the caller passed it.
        candidates (tuple[Match, ...]): Ranked candidates.
        answers (dict[str, str]): Answers so far, by input key.

    Returns:
        InputRequiredResult: Request for one corp code.
    """
    options = [
        {"const": m.record.corp_code, "title": company_label(m.record)}
        for m in candidates[:MAX_CHOICES]
    ]
    schema = {
        "type": "object",
        "properties": {"corp_code": {"type": "string", "title": "Company", "oneOf": options}},
        "required": ["corp_code"],
    }
    params = ElicitRequestFormParams(message=_message(query), requested_schema=schema)
    request = ElicitRequest(method="elicitation/create", params=params)
    return InputRequiredResult(
        result_type="input_required",
        input_requests={_key(query): request},
        request_state=json.dumps(answers),
    )


def _pick(candidates: tuple[Match, ...], corp_code: object) -> CorpRecord | None:
    """Find the chosen candidate.

    Args:
        candidates (tuple[Match, ...]): Offered candidates.
        corp_code (object): Answer from the user.

    Returns:
        CorpRecord | None: The chosen company, or None for an unexpected answer.
    """
    return next((m.record for m in candidates if m.record.corp_code == str(corp_code)), None)


def _guard_chooser(ctx: Context) -> Chooser:
    """Choose through the 2026-07-28 guard pattern.

    Args:
        ctx (Context): Request context.

    Returns:
        Chooser: Raises InputRequiredError until the client answers.
    """

    async def choose(query: str, candidates: tuple[Match, ...]) -> CorpRecord | None:
        """Resolve one query from the answer supplied by the client.

        Args:
            query (str): Company text passed by the caller.
            candidates (tuple[Match, ...]): Ranked matching companies offered to the client.

        Returns:
            CorpRecord | None: Selected company, or None when the user declines.

        Raises:
            InputRequiredError: No answer has been supplied for this query yet.
        """
        answers = _answers(ctx)
        key = _key(query)
        if key not in answers:
            raise InputRequiredError(_request(query, candidates, answers))
        return _pick(candidates, answers[key]) if answers[key] else None

    return choose


def _answers(ctx: Context) -> dict[str, str]:
    """Collect answers from earlier rounds and this one, by input key.

    Args:
        ctx (Context): Request context.

    Returns:
        dict[str, str]: Chosen corp code per key; an empty string records a refusal.
    """
    try:
        stored: object = json.loads(ctx.request_state or "{}")
    except ValueError:
        stored = None
    answers = {
        key: value
        for key, value in (stored.items() if isinstance(stored, dict) else ())
        if isinstance(key, str) and isinstance(value, str)
    }
    for key, response in (ctx.input_responses or {}).items():
        accepted = isinstance(response, ElicitResult) and response.action == "accept"
        content = response.content if accepted and isinstance(response, ElicitResult) else None
        answers[key] = str(content.get("corp_code", "")) if content else ""
    return answers


def _session_chooser(ctx: Context) -> Chooser:
    """Choose through a 2025-11-25 server-to-client elicitation request.

    Args:
        ctx (Context): Request context.

    Returns:
        Chooser: Awaits the user's answer.
    """

    async def choose(query: str, candidates: tuple[Match, ...]) -> CorpRecord | None:
        """Ask the client to choose among the matching companies.

        Args:
            query (str): Company text passed by the caller.
            candidates (tuple[Match, ...]): Ranked matching companies offered to the client.

        Returns:
            CorpRecord | None: Selected company, or None when the user declines or the host
                cannot complete the request.
        """
        options = {
            m.record.corp_code: {"title": company_label(m.record)} for m in candidates[:MAX_CHOICES]
        }
        try:
            result = await ctx.elicit(_message(query), response_type=options)
        except Exception:  # Any host failure falls back to the candidate list.
            logger.info("Elicitation failed; returning candidates instead", exc_info=True)
            return None
        return _pick(candidates, result.data) if result.action == "accept" else None

    return choose


def company_chooser(ctx: object, state: object) -> Chooser | None:
    """Build the chooser for one tool call, or None when the host cannot ask.

    Args:
        ctx (object): The call's injected ``ctx`` argument, if any.
        state (object): The call's injected ``state`` argument, if any.

    Returns:
        Chooser | None: Chooser for this call.
    """
    if not isinstance(ctx, Context) or not isinstance(state, AppState):
        return None
    if not state.settings.tools.elicit_ambiguous_company or not client_can_elicit(ctx):
        return None
    context = ctx.request_context
    if context is not None and context.protocol_version in MODERN_PROTOCOL_VERSIONS:
        return _guard_chooser(ctx)
    return _session_chooser(ctx)
