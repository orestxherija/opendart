"""get_corporate_events over the MCP protocol: schema, index strategy, formats, and errors."""

from __future__ import annotations

import httpx2
import pytest
from fastmcp import Client

from opendart_mcp.server import create_server
from opendart_mcp.settings import Settings, UpstreamSettings
from tests.support.events import (
    convertible_bond,
    debt_registration,
    equity_registration,
    filing,
    identity,
    merger,
    profile,
    rights_issue,
)

CB = "/cvbdIsDecsn.json"
MERGER = "/cmpMgDecsn.json"


def index(upstream, major=(), offerings=(), *, pages=1):
    """Answer filing searches by disclosure group, with an optional page count."""

    def answer(request):
        records = major if request.url.params.get("pblntf_ty") == "B" else offerings
        if not records:
            return upstream.status("013")
        return upstream.rows(*records, total_page=pages, total_count=len(records))

    upstream.route("/list.json", answer)


def samsung(upstream):
    upstream.route("/company.json", upstream.ok(**profile()))


async def call(client, **arguments):
    result = await client.call_tool(
        "get_corporate_events", {"company": "005930", **arguments}, raise_on_error=False
    )
    return result, result.structured_content


@pytest.mark.anyio
async def test_tools_are_listed_with_schemas_versions_and_annotations(client):
    tools = {tool.name: tool for tool in await client.list_tools()}
    names = list(tools)
    assert names.index("get_corporate_events") < names.index("get_corporate_action_calendar")
    events = tools["get_corporate_events"]
    assert events.meta["fastmcp"]["version"] == "1.0.0"
    assert events.annotations.read_only_hint is True
    assert events.annotations.open_world_hint is False
    schema = events.input_schema
    assert schema["required"] == ["company"]
    assert schema["properties"]["since"]["default"] == "1y"
    assert schema["properties"]["limit"]["maximum"] == 200
    assert {"events", "coverage", "since", "until"} <= set(events.output_schema["properties"])
    words = len(events.description.split())
    assert 60 <= words <= 120


@pytest.mark.anyio
async def test_the_filing_index_picks_the_reports_to_read(client, upstream):
    samsung(upstream)
    index(
        upstream,
        major=[
            filing("20260915000123", "Decision on Issuance of Convertible Bonds"),
            filing("20260901000456", "Decision on Merger"),
            filing("20260820000111", "Decision on Donation"),
        ],
    )
    upstream.records(CB, convertible_bond())
    upstream.records(MERGER, merger())
    result, data = await call(client)
    assert not result.is_error
    assert [e["kind"] for e in data["events"]] == ["convertible_bond", "merger"]
    assert data["coverage"] == {
        "strategy": "filing_index",
        "kinds_queried": ["convertible_bond", "merger"],
        "kinds_with_data": ["convertible_bond", "merger"],
    }
    assert (data["since"], data["until"]) == ("2025-10-22", "2026-10-22")
    assert upstream.count("/piicDecsn.json") == 0
    query = upstream.params(CB)[0]
    assert (query["corp_code"], query["bgn_de"], query["end_de"]) == (
        "00126380",
        "20251022",
        "20261022",
    )
    assert any("Decision on Donation (20260820000111)" in note for note in data["notes"])
    bond = data["events"][0]
    assert bond["headline"].startswith("KRW 30.0bn convertible bond, series 3, Private placement")
    assert bond["key_terms"]["conversion_price"] == 52300
    assert bond["key_terms"]["dilution_pct"] == 0.01
    assert bond["dates"][0] == {"what": "subscription", "date": "2026-11-12"}
    assert bond["flags"] == ["private_placement"]
    assert bond["board_date"] == "2026-09-15"
    assert bond["dart_url"].endswith("rcpNo=20260915000123")
    assert "fields" not in bond
    assert data["events"][1]["flags"] == ["put_option"]
    text = result.content[0].text
    assert "| Filed | Kind | Headline | Dates | Flags | Filing |" in text
    assert "Subscription 2026-11-12" in text


@pytest.mark.anyio
async def test_requested_categories_skip_the_index(client, upstream):
    samsung(upstream)
    upstream.records(CB, convertible_bond())
    _, data = await call(client, categories=["convertible_and_hybrid_debt"])
    assert data["coverage"]["strategy"] == "requested"
    assert data["coverage"]["kinds_queried"] == [
        "convertible_bond",
        "bond_with_warrants",
        "exchangeable_bond",
        "contingent_capital_bond",
        "debt_offering_registration",
    ]
    assert upstream.count("/list.json") == 0
    assert upstream.count("/bdRs.json") == 1


@pytest.mark.anyio
async def test_detailed_format_adds_labeled_fields(client, upstream):
    samsung(upstream)
    upstream.records("/estkRs.json", **equity_registration())
    _, data = await call(
        client, categories=["equity_offering_registration"], response_format="detailed"
    )
    (offering,) = data["events"]
    assert offering["headline"].startswith("Equity offering of 6,000,000 Common stock")
    whats = [d["what"] for d in offering["dates"]]
    assert whats[:3] == ["record_date", "subscription_start", "subscription_end"]
    assert "redemption_claim_start" in whats
    fields = {(f.get("section"), f["name"]): f for f in offering["fields"]}
    amount = fields[("Purpose of use of funds", "amt")]
    assert (amount["value"], amount["raw"]) == (19490000000, "19,490,000,000")
    assert fields[("Securities class", "stksen")]["label"] == "Type of securities"
    assert "raw" not in fields[("Securities class", "stksen")]


@pytest.mark.anyio
async def test_a_company_without_filings_gets_an_empty_result(client, upstream):
    samsung(upstream)
    result, data = await call(client)
    assert not result.is_error
    assert data["events"] == []
    assert data["coverage"]["kinds_queried"] == []
    assert "filed no major-issue or offering reports" in data["notes"][-1]


@pytest.mark.anyio
async def test_amended_rows_are_flagged_from_the_index_or_the_board_date(client, upstream):
    samsung(upstream)
    index(
        upstream,
        major=[filing("20261020000999", "[Corrected description]Decision on Merger")],
    )
    upstream.records(MERGER, merger("20261020000999"))
    _, data = await call(client)
    assert data["events"][0]["flags"] == ["put_option", "amended"]
    assert data["events"][0]["filed"] == "2026-10-20"
    assert any("latest correction" in note for note in data["notes"])
    upstream.records(CB, convertible_bond("20261021000202", bddd="2025.12.09"))
    _, data = await call(client, categories=["convertible_bond"])
    assert data["events"][0]["flags"] == ["private_placement", "possibly_amended"]
    (note,) = (note for note in data["notes"] if "possibly_amended" in note)
    assert "more than 7 days after the board resolution" in note
    assert "they may show amended terms" in note
    assert not any("latest correction" in note for note in data["notes"])


@pytest.mark.anyio
async def test_late_filing_is_no_amendment_sign_for_registrations(client, upstream):
    samsung(upstream)
    general = {
        "rcept_no": "20261015000123",
        **identity(),
        "stn": "Merger",
        "bddd": "2026.09.01",
        "ctrd": "2026.09.01",
        "ap_gmtsck": "2026.11.15",
        "mgdt_etc": "2027.01.01",
    }
    upstream.records("/mgRs.json", group=[{"title": "General matters", "list": [general]}])
    upstream.records("/piicDecsn.json", rights_issue("20261021000777"))
    _, data = await call(client, categories=["merger_registration", "rights_or_third_party_issue"])
    merger_registration, issue = data["events"][1], data["events"][0]
    assert (merger_registration["kind"], merger_registration["board_date"]) == (
        "merger_registration",
        "2026-09-01",
    )
    assert "flags" not in merger_registration
    assert issue["flags"] == ["third_party_allotment"]
    assert not any("amended" in note for note in data["notes"])


@pytest.mark.anyio
async def test_limit_cuts_newest_first_with_the_next_call(client, upstream):
    samsung(upstream)
    upstream.records(
        CB,
        convertible_bond("20260115000001"),
        convertible_bond("20260915000003"),
        convertible_bond("20260515000002"),
    )
    result, data = await call(client, categories=["convertible_bond"], limit=2)
    assert [e["filing_number"] for e in data["events"]] == ["20260915000003", "20260515000002"]
    pagination = data["pagination"]
    assert (pagination["total"], pagination["has_more"]) == (3, True)
    assert pagination["next_call"]["arguments"] == {
        "company": "00126380",
        "since": "2025-10-22",
        "until": "2026-10-22",
        "limit": 3,
        "categories": ["convertible_bond"],
    }
    assert "Showing the 2 most recent of 3 events" in data["notes"][-1]
    assert "More: get_corporate_events(" in result.content[0].text


@pytest.mark.anyio
async def test_a_large_index_falls_back_to_every_major_issue_report(client, upstream):
    samsung(upstream)
    index(upstream, major=[filing("20260915000123", "Lawsuit Filing, etc.")], pages=5)
    _, data = await call(client)
    assert data["coverage"]["strategy"] == "all_kinds"
    assert len(data["coverage"]["kinds_queried"]) == 36
    assert upstream.count("/list.json") == 4  # three pages of B, one of C
    assert "every major-issue report was read" in data["notes"][0]


@pytest.mark.anyio
async def test_windows_before_2015_are_clamped(client, upstream):
    samsung(upstream)
    _, data = await call(client, categories=["merger"], since="2010-01-01", until="2016-01-01")
    assert (data["since"], data["until"]) == ("2015-01-01", "2016-01-01")
    assert data["notes"][0].startswith("Event reports start in 2015")


@pytest.mark.anyio
async def test_derived_terms_for_a_third_party_allotment(client, upstream):
    samsung(upstream)
    upstream.records("/piicDecsn.json", rights_issue())
    _, data = await call(client, categories=["rights_or_third_party_issue"])
    (issue,) = data["events"]
    assert issue["key_terms"]["proceeds"] == 9999992440
    assert issue["key_terms"]["dilution_pct"] == 16.25
    assert issue["flags"] == ["third_party_allotment"]


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        ({"company": "Samsung"}, "Ambiguous company"),
        ({"company": "005930", "categories": ["cb"]}, "Unknown event categories: cb"),
        ({"company": "005930", "since": "lately"}, "Invalid date 'lately'"),
        ({"company": "005930", "since": "2030-01-01"}, "is after until"),
        (
            {"company": "005930", "since": "2010-01-01", "until": "2014-06-30"},
            "must overlap 2015-01-01 to today",
        ),
        ({"company": "20260915000123"}, "is a filing number"),
        ({"company": "999999"}, "find_company"),
    ],
)
async def test_invalid_arguments_are_explained(client, upstream, arguments, expected):
    samsung(upstream)
    result = await client.call_tool("get_corporate_events", arguments, raise_on_error=False)
    assert result.is_error
    assert expected in result.content[0].text


@pytest.mark.anyio
async def test_quota_exhaustion_fails_the_call(client, upstream):
    samsung(upstream)
    upstream.route(CB, upstream.status("020"))
    result, _ = await call(client, categories=["convertible_bond", "merger"])
    assert result.is_error
    assert "Retry after 00:00 KST" in result.content[0].text


@pytest.mark.anyio
async def test_a_missing_api_key_is_explained(mcp_settings, upstream):
    server = create_server(mcp_settings, transport=upstream.transport)
    async with Client(server) as client:
        result, _ = await call(client)
    assert result.is_error
    assert "OPENDART_API__API_KEY" in result.content[0].text


@pytest.mark.anyio
async def test_a_failing_report_is_listed_while_the_others_answer(
    mcp_settings, sdk_settings, upstream, now
):
    settings = Settings(
        http=mcp_settings.http,
        directory=mcp_settings.directory,
        tasks=mcp_settings.tasks,
        upstream=UpstreamSettings(retry_delay=0),
    )
    upstream.route("/corpCode.xml", upstream.corp_archive())
    samsung(upstream)
    upstream.route(CB, httpx2.Response(503))
    upstream.records(MERGER, merger())
    server = create_server(
        settings, api=sdk_settings, transport=upstream.transport, clock=lambda: now
    )
    async with Client(server) as client:
        result, data = await call(client, categories=["convertible_bond", "merger"])
    assert not result.is_error
    assert data["coverage"]["kinds_failed"] == ["convertible_bond"]
    assert [e["kind"] for e in data["events"]] == ["merger"]
    assert "OpenDART did not answer for convertible_bond" in data["notes"][0]
    assert "No answer for: convertible_bond." in result.content[0].text


@pytest.mark.anyio
async def test_the_largest_limit_offers_no_next_call(client, upstream):
    samsung(upstream)
    upstream.records(CB, *(convertible_bond(f"20260915{n:06d}") for n in range(201)))
    _, data = await call(client, categories=["convertible_bond"], limit=200)
    assert len(data["events"]) == 200
    assert data["pagination"] == {"total": 201, "page": 1, "limit": 200, "has_more": True}


@pytest.mark.anyio
async def test_the_next_call_keeps_the_detailed_format(client, upstream):
    samsung(upstream)
    upstream.records(CB, convertible_bond("20260915000001"), convertible_bond("20260915000002"))
    _, data = await call(
        client, categories=["convertible_bond"], limit=1, response_format="detailed"
    )
    arguments = data["pagination"]["next_call"]["arguments"]
    assert (arguments["limit"], arguments["response_format"]) == (2, "detailed")
    assert data["events"][0]["fields"]


@pytest.mark.anyio
async def test_each_tranche_of_a_debt_offering_is_an_event(client, upstream):
    samsung(upstream)
    upstream.records("/bdRs.json", **debt_registration())
    result, data = await call(client, categories=["debt_offering_registration"])
    first, second = data["events"]
    assert first["filing_number"] == second["filing_number"] == "20261020000111"
    assert [first["key_terms"]["series"], second["key_terms"]["series"]] == ["301-1", "301-2"]
    assert second["key_terms"]["face_value"] == 200000000000
    assert {"what": "maturity", "date": "2031-11-05"} in second["dates"]
    assert {"what": "maturity", "date": "2029-11-05"} not in second["dates"]
    assert data["coverage"]["kinds_with_data"] == ["debt_offering_registration"]
    assert "listed once per tranche" in data["notes"][-1]
    assert "series 301-2" in result.content[0].text
