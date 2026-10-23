"""The workflow prompts over the MCP protocol: listing, rendering, and the company profile."""

from __future__ import annotations

import json

import pytest
from fastmcp import Client
from mcp.shared.exceptions import MCPError

from opendart_mcp.server import create_server

ORDER = [
    "company_briefing",
    "earnings_review",
    "event_impact",
    "dilution_overhang",
    "ownership_and_control",
    "credit_and_liquidity",
    "peer_comparison",
    "filings_screen",
    "pre_trade_checklist",
    "watchlist_digest",
    "summarize_filing",
]
ARGUMENTS = {
    "company_briefing": {"company": "005930"},
    "earnings_review": {"company": "005930"},
    "event_impact": {"company": "005930"},
    "dilution_overhang": {"company": "005930"},
    "ownership_and_control": {"company": "005930"},
    "credit_and_liquidity": {"company": "005930"},
    "peer_comparison": {"companies": "005930, 000660"},
    "filings_screen": {},
    "pre_trade_checklist": {"company": "005930"},
    "watchlist_digest": {"companies": "005930, 000660"},
    "summarize_filing": {"filing_number": "20260814001234"},
}
SINGLE_COMPANY = [name for name, arguments in ARGUMENTS.items() if "company" in arguments]
PROFILE = {"corp_name": "삼성전자", "corp_cls": "Y", "acc_mt": "12", "stock_code": "005930"}


@pytest.fixture
def samsung(upstream):
    upstream.route("/company.json", upstream.ok(**PROFILE))


def text_of(result):
    return result.messages[-1].content.text


@pytest.mark.anyio
async def test_prompts_are_listed_in_design_order_with_metadata(client):
    prompts = await client.list_prompts()
    assert [p.name for p in prompts] == ORDER
    for listed in prompts:
        assert listed.title
        assert listed.description
        assert listed.meta is not None
        assert listed.meta["fastmcp"]["version"] == "1.0.0"
        assert listed.meta["fastmcp"]["tags"] == ["workflow"]
        for argument in listed.arguments or []:
            assert argument.description
            assert "JSON schema" not in argument.description
    earnings = next(p for p in prompts if p.name == "earnings_review")
    required = {a.name: a.required for a in earnings.arguments or []}
    assert required == {"company": True, "fiscal_year": False, "period": False}


@pytest.mark.anyio
@pytest.mark.parametrize("name", ORDER)
async def test_every_prompt_names_tools_rules_and_a_format_within_budget(client, samsung, name):
    result = await client.get_prompt(name, ARGUMENTS[name])
    text = text_of(result)
    assert len(text.split()) <= 300
    assert "Format" in text
    assert "filing number" in text
    assert "(" in text.split("\n\n")[1]


@pytest.mark.anyio
@pytest.mark.parametrize("name", SINGLE_COMPANY)
async def test_single_company_prompts_attach_the_profile(client, upstream, samsung, name):
    result = await client.get_prompt(name, {"company": "Samsung Electronics"})
    attached, instructions = result.messages
    resource = attached.content.resource
    assert str(resource.uri) == "opendart://company/00126380"
    assert resource.mime_type == "application/json"
    assert json.loads(resource.text)["company"]["corp_code"] == "00126380"
    text = instructions.content.text
    assert 'company="00126380"' in text or 'companies=["00126380"]' in text
    assert "SAMSUNG ELECTRONICS CO,.LTD (005930, KOSPI; DART 00126380)" in text
    assert text.endswith("The company profile is attached above.")


@pytest.mark.anyio
async def test_an_ambiguous_company_falls_back_to_instructions(client):
    result = await client.get_prompt("company_briefing", {"company": "Samsung"})
    (message,) = result.messages
    text = message.content.text
    assert 'get_ownership(company="Samsung")' in text
    assert "Note: 'Samsung' was not resolved: Ambiguous company 'Samsung'" in text
    assert "Resolve the company with find_company first." in text


@pytest.mark.anyio
async def test_an_unreadable_profile_is_left_out(client, upstream, samsung):
    upstream.route("/list.json", upstream.status("020"))
    result = await client.get_prompt("credit_and_liquidity", {"company": "00126380"})
    (message,) = result.messages
    assert 'get_debt_profile(company="00126380")' in message.content.text
    assert "attached" not in message.content.text.split("\n\n")[-1]


@pytest.mark.anyio
async def test_prompts_work_without_an_api_key(mcp_settings, upstream):
    async with Client(create_server(mcp_settings, transport=upstream.transport)) as client:
        result = await client.get_prompt("ownership_and_control", {"company": "Samsung"})
    (message,) = result.messages
    assert "OPENDART_API__API_KEY" in message.content.text
    assert upstream.count() == 0


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        ({}, ['view="summary") for headline', "the latest reported period"]),
        ({"period": "q3", "fiscal_year": "2025"}, ['period="Q3", fiscal_year=2025', "Q3 2025"]),
        ({"period": "FY"}, ['period="FY")', "the latest FY"]),
        ({"fiscal_year": " 2024 "}, ["fiscal_year=2024", "latest reported period of fiscal 2024"]),
    ],
)
async def test_earnings_review_names_the_period(client, samsung, arguments, expected):
    result = await client.get_prompt("earnings_review", {"company": "005930", **arguments})
    for fragment in expected:
        assert fragment in text_of(result)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        (
            {"filing_number": "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20250312000123"},
            ['read_filing(filing_number="20250312000123", mode="outline")', "filing 20250312"],
        ),
        (
            {"event": "Convertible bond"},
            [
                'categories=["convertible_bond"], since="1y"',
                'categories=["convertible_and_hybrid_debt"], since="5y"',
                "the latest convertible bond event",
            ],
        ),
        ({"event": "buyback"}, ['categories=["buyback"], since="5y"']),
        ({"event": "supply contract"}, ['matching "supply contract"', 'since="5y")']),
        ({}, ["its most recent material event", "take the most recent material event"]),
    ],
)
async def test_event_impact_locates_the_event(client, samsung, arguments, expected):
    result = await client.get_prompt("event_impact", {"company": "005930", **arguments})
    for fragment in expected:
        assert fragment in text_of(result)


@pytest.mark.anyio
async def test_dilution_overhang_uses_only_a_given_share_price(client, samsung):
    priced = await client.get_prompt(
        "dilution_overhang", {"company": "005930", "lookback": "2y", "share_price": "₩71500"}
    )
    assert "share price of KRW 71,500" in text_of(priced)
    assert 'since="2y"' in text_of(priced)
    unpriced = await client.get_prompt("dilution_overhang", {"company": "005930"})
    assert "No share price was given" in text_of(unpriced)
    assert "from the last 3y" in text_of(unpriced)


@pytest.mark.anyio
async def test_the_checklist_adapts_to_the_trade_direction(client, samsung):
    short = text_of(
        await client.get_prompt(
            "pre_trade_checklist", {"company": "005930", "direction": "SHORT", "horizon": "6m"}
        )
    )
    assert "short position over 6m" in short
    assert 'horizon="6m"' in short
    assert "For a short position, also flag buybacks" in short
    assert "amendments, price support." in short
    long = text_of(await client.get_prompt("pre_trade_checklist", {"company": "005930"}))
    assert "For a short position" not in long
    assert "amendments. End" in long


@pytest.mark.anyio
async def test_peer_comparison_lists_the_companies(client):
    arguments = {"companies": "SAMSUNG ELECTRONICS CO,.LTD, SK hynix; 035420", "focus": "Growth"}
    text = text_of(await client.get_prompt("peer_comparison", arguments))
    companies = '["SAMSUNG ELECTRONICS CO,.LTD", "SK hynix", "035420"]'
    assert f'compare_companies(companies={companies}, metrics="both", period="FY")' in text
    assert "Compare 3 companies on growth: revenue" in text
    assert "the latest fiscal year" in text
    dated = text_of(
        await client.get_prompt("peer_comparison", {"companies": "005930", "fiscal_year": "2024"})
    )
    assert 'period="FY", fiscal_year=2024)' in dated
    assert "on every metric for fiscal 2024" in dated


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        ({}, ['market="KOSPI"; market="KOSDAQ"', "KOSPI and KOSDAQ filings since 1d"]),
        ({"market": "all, KOSPI"}, ["Screen all filings", 'once per market: market="all".']),
        (
            {"market": "konex", "focus": "buybacks", "since": "7d"},
            ['categories=["treasury_stock", "treasury_trust", "major_issues"]', "focusing on"],
        ),
    ],
)
async def test_filings_screen_searches_each_market(client, arguments, expected):
    text = text_of(await client.get_prompt("filings_screen", arguments))
    for fragment in expected:
        assert fragment in text


@pytest.mark.anyio
async def test_watchlist_digest_and_filing_summary(client):
    digest = text_of(
        await client.get_prompt(
            "watchlist_digest", {"companies": "Samsung Electronics, NAVER", "since": "2026-10-01"}
        )
    )
    assert "these 2 companies filed since 2026-10-01: Samsung Electronics, NAVER" in digest
    assert 'companies=["Samsung Electronics", "NAVER"], horizon="30d"' in digest
    summary = text_of(
        await client.get_prompt(
            "summarize_filing", {"filing_number": "20260814001234", "focus": " dividends "}
        )
    )
    assert summary.startswith("Summarize filing 20260814001234 in English, focusing on dividends.")
    assert 'read_filing(filing_number="20260814001234", mode="outline")' in summary


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("name", "arguments", "expected"),
    [
        ("company_briefing", {"company": "  "}, "company is required"),
        ("earnings_review", {"company": "005930", "period": "Q2"}, "period must be one of"),
        ("earnings_review", {"company": "005930", "fiscal_year": "1999"}, "from 2015 to 2027"),
        ("earnings_review", {"company": "005930", "fiscal_year": "FY25"}, "fiscal_year must be"),
        ("earnings_review", {"company": "005930", "fiscal_year": "\u00b2025"}, "fiscal_year must"),
        ("event_impact", {"company": "005930", "filing_number": "12345"}, "14-digit"),
        ("dilution_overhang", {"company": "005930", "share_price": "cheap"}, "share_price"),
        ("dilution_overhang", {"company": "005930", "share_price": "-5"}, "positive price"),
        ("dilution_overhang", {"company": "005930", "lookback": "ages"}, "lookback: Invalid"),
        ("pre_trade_checklist", {"company": "005930", "direction": "flat"}, "long, short"),
        ("pre_trade_checklist", {"company": "005930", "horizon": "soon"}, "horizon: Invalid"),
        ("peer_comparison", {"companies": " , ;"}, "got 0"),
        ("peer_comparison", {"companies": ",".join(["005930"] * 21)}, "got 21"),
        ("peer_comparison", {"companies": "005930", "focus": "value"}, "focus must be"),
        ("filings_screen", {"market": "NYSE"}, "market must be one of KOSPI"),
        ("filings_screen", {"since": "lately"}, "since: Invalid"),
        ("watchlist_digest", {"companies": "005930", "since": "x"}, "since: Invalid"),
        ("summarize_filing", {"filing_number": "latest"}, "search_filings"),
    ],
)
async def test_invalid_arguments_explain_the_fix(client, name, arguments, expected):
    with pytest.raises(MCPError, match=expected):
        await client.get_prompt(name, arguments)
