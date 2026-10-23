"""The calendar's maturity provider hook and elicitation for ambiguous watchlist names."""

from __future__ import annotations

from datetime import date

import pytest
from fastmcp import Client
from fastmcp.client.elicitation import ElicitResult
from fastmcp.client.transports import FastMCPTransport

from opendart_mcp.core.metrics import Metrics
from opendart_mcp.core.runtime import open_state
from opendart_mcp.domain.identifiers import dart_viewer_url
from opendart_mcp.models.calendar import CalendarItem
from opendart_mcp.services.calendar import CalendarRequest, action_calendar
from packages.mcp.tests.events.data import merger, profile

BOND = "20260314000100"


class NoTasksClient(Client[FastMCPTransport]):
    """A modern client without the tasks extension, like Claude hosts today."""

    _auto_internal_extensions = False


def item(company, day):
    return CalendarItem(
        date=day,
        company=company.ref,
        action="bond_maturity",
        source_kind="debt_ladder",
        filing_number=BOND,
        dart_url=dart_viewer_url(BOND),
        details={"amount": 50_000_000_000},
    )


@pytest.mark.anyio
async def test_a_maturity_provider_merges_items_within_the_window(
    mcp_settings, sdk_settings, upstream, now
):
    upstream.route("/corpCode.xml", upstream.corp_archive())
    upstream.route("/company.json", upstream.ok(**profile()))
    upstream.records("/cmpMgDecsn.json", merger())
    asked = []

    async def maturities(state, company, window):
        asked.append((company.corp_code, window.start, window.end))
        items = [item(company, date(2026, 12, 22)), item(company, date(2028, 1, 1))]
        return items, ["Maturities cover recent issues only.", "A second note."]

    request = CalendarRequest(kinds=("merger", "debt_maturity"))
    async with open_state(
        mcp_settings,
        metrics=Metrics(),
        api=sdk_settings,
        transport=upstream.transport,
        clock=lambda: now,
    ) as state:
        result = await action_calendar(state, ["00126380"], request=request, maturities=maturities)
        without = await action_calendar(
            state, ["00126380"], request=CalendarRequest(kinds=("merger",)), maturities=maturities
        )
    assert asked == [("00126380", date(2026, 10, 22), date(2027, 1, 20))]
    same_day = [(i.action, i.source_kind) for i in result.items if i.date == date(2026, 12, 22)]
    assert same_day == [("effective_date", "merger"), ("bond_maturity", "debt_ladder")]
    assert date(2028, 1, 1) not in {i.date for i in result.items}
    assert result.notes[1:] == ["Maturities cover recent issues only.", "A second note."]
    assert not any("maturities are not included" in note for note in result.notes)
    # kinds without debt_maturity leave the provider out.
    assert {i.source_kind for i in without.items} == {"merger"}
    assert "A second note." not in without.notes


@pytest.mark.anyio
async def test_debt_maturities_without_a_provider_are_noted(
    mcp_settings, sdk_settings, upstream, now
):
    upstream.route("/corpCode.xml", upstream.corp_archive())
    upstream.route("/company.json", upstream.ok(**profile()))
    async with open_state(
        mcp_settings,
        metrics=Metrics(),
        api=sdk_settings,
        transport=upstream.transport,
        clock=lambda: now,
    ) as state:
        result = await action_calendar(
            state, ["00126380"], request=CalendarRequest(kinds=("debt_maturity",))
        )
    assert result.items == []
    assert result.notes == [
        "Debt maturities are not included; see get_debt_profile.",
        "No corporate-action dates from 2026-10-22 to 2027-01-20.",
    ]
    assert upstream.count("/list.json") == 0


@pytest.mark.anyio
async def test_ambiguous_watchlist_names_are_asked_about(server, upstream):
    upstream.route("/company.json", upstream.ok(**profile()))
    upstream.records("/cmpMgDecsn.json", merger())
    asked: list[str] = []

    async def accept(message, response_type, params, context):
        asked.append(message)
        try:
            content = response_type(corp_code="00126380")
        except TypeError:
            content = response_type(value="00126380")
        return ElicitResult(action="accept", content=content)

    async with NoTasksClient(server, elicitation_handler=accept) as client:
        result = await client.call_tool(
            "get_corporate_action_calendar",
            {"companies": ["Samsung", "000660"], "kinds": ["merger"]},
        )
    assert asked == ["'Samsung' matches several companies. Which one do you mean?"]
    companies = [c["corp_code"] for c in result.structured_content["companies"]]
    assert companies == ["00126380", "00164779"]
