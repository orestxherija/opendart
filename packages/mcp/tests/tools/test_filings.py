"""search_filings over the MCP protocol: schema, company and market-wide searches, errors."""

from __future__ import annotations

import pytest
from fastmcp import Client

from opendart_mcp.server import create_server

PROFILE = {"corp_name": "삼성전자", "corp_name_eng": "SAMSUNG ELECTRONICS CO,.LTD", "corp_cls": "Y"}


def row(
    number, title, *, corp_code="00126380", name="SAMSUNG ELECTRONICS", stock="005930", **extra
):
    return {
        "corp_cls": extra.get("cls", "Y"),
        "corp_name": name,
        "corp_code": corp_code,
        "stock_code": stock,
        "report_nm": title,
        "rcept_no": number,
        "flr_nm": extra.get("submitter", "삼성전자"),
        "rcept_dt": number[:8],
        "rm": extra.get("rm", ""),
    }


SAMSUNG_ROWS = (
    row("20261013800651", "Report on Shares Change of Largest Shareholders              ", rm="S"),
    row(
        "20261008800004",
        "Report on Business Performance according to Consolidated Financial Statements (Fair Disclosure)   ",
        rm="S",
    ),
    row("20260814003699", "Semi-annual Report (2026.06)", rm="U"),
    row(
        "20260730800103", "[Corrected description]Report on Business Performance (Fair Disclosure)"
    ),
)


@pytest.mark.anyio
async def test_search_filings_is_listed_with_its_schema(client):
    tools = await client.list_tools()
    names = [tool.name for tool in tools]
    assert names.index("search_filings") == names.index("get_company_profile") + 1
    tool = tools[names.index("search_filings")]
    assert tool.meta is not None
    assert tool.meta["fastmcp"]["version"] == "1.0.0"
    assert tool.annotations is not None
    assert tool.annotations.read_only_hint is True
    assert tool.annotations.open_world_hint is False
    schema = tool.input_schema
    assert "required" not in schema
    assert set(schema["properties"]) == {
        "company",
        "categories",
        "since",
        "until",
        "market",
        "title_contains",
        "final_only",
        "limit",
        "page",
    }
    assert schema["properties"]["company"]["description"].startswith("Company name")
    assert schema["properties"]["limit"]["maximum"] == 100
    assert tool.output_schema is not None
    assert {"filings", "pagination", "since", "until"} <= set(tool.output_schema["properties"])


@pytest.mark.anyio
async def test_company_search_returns_filings_newest_first(client, upstream):
    upstream.route("/company.json", upstream.ok(**PROFILE))
    upstream.records("/list.json", *SAMSUNG_ROWS, total_count=4, total_page=1)
    result = await client.call_tool("search_filings", {"company": "005930"})
    data = result.structured_content
    assert data["company"]["corp_code"] == "00126380"
    assert (data["since"], data["until"]) == ("2026-07-24", "2026-10-22")
    first, earnings, semiannual, corrected = data["filings"]
    assert first == {
        "filing_number": "20261013800651",
        "filed": "2026-10-13",
        "title": "Report on Shares Change of Largest Shareholders",
        "submitter": "삼성전자",
        "category": "exchange_disclosures",
        "is_amendment": False,
        "dart_url": "https://englishdart.fss.or.kr/dsbh001/main.do?rcpNo=20261013800651",
    }
    assert earnings["title"].endswith("(Fair Disclosure)")
    assert semiannual["category"] == "semiannual_report"
    assert semiannual["corrected_later"] is True
    assert corrected["is_amendment"] is True
    assert data["pagination"] == {"total": 4, "page": 1, "limit": 50, "has_more": False}
    (query,) = upstream.params("/list.json")
    assert query == {
        "corp_code": "00126380",
        "bgn_de": "20260724",
        "end_de": "20261022",
        "last_reprt_at": "Y",
        "page_no": "1",
        "page_count": "100",
    }
    text = result.content[0].text
    assert "**Filings, SAMSUNG ELECTRONICS CO,.LTD (005930, KOSPI; DART 00126380)" in text
    assert "| Filed | Title | Category | Filing number |" in text
    assert "Semi-annual Report (2026.06) [corrected later]" in text
    assert "Showing 1-4 of 4." in text


@pytest.mark.anyio
async def test_market_wide_categories_send_subtypes_alone_and_merge(client, upstream):
    def by_category(request):
        params = request.url.params
        if params.get("pblntf_ty") == "B":
            return upstream.rows(
                row(
                    "20261021000300",
                    "Report on Major Issues",
                    corp_code="00164779",
                    name="SK hynix",
                ),
                row(
                    "20261019000100",
                    "Report on Major Issues",
                    corp_code="00164779",
                    name="SK hynix",
                ),
                total_count=2,
                total_page=1,
            )
        return upstream.rows(
            row("20261022800004", "Report on Business Performance (Fair Disclosure)"),
            row("20261020900001", "Report on Business Performance (Fair Disclosure)", cls="K"),
            total_count=2,
            total_page=1,
        )

    upstream.route("/list.json", by_category)
    result = await client.call_tool(
        "search_filings",
        {"categories": ["major_issues", "fair_disclosure", "major_issues"], "since": "7d"},
    )
    data = result.structured_content
    assert "company" not in data
    numbers = [f["filing_number"] for f in data["filings"]]
    assert numbers == ["20261022800004", "20261021000300", "20261020900001", "20261019000100"]
    assert [f["category"] for f in data["filings"]] == [
        "fair_disclosure",
        "major_issues",
        "fair_disclosure",
        "major_issues",
    ]
    assert data["pagination"]["total"] == 4
    queries = upstream.params("/list.json")
    assert len(queries) == 2
    major = next(q for q in queries if "pblntf_ty" in q)
    fair = next(q for q in queries if "pblntf_detail_ty" in q)
    assert major["pblntf_ty"] == "B"
    assert "pblntf_detail_ty" not in major
    assert fair["pblntf_detail_ty"] == "I002"
    assert "pblntf_ty" not in fair
    assert "corp_code" not in fair
    assert fair["bgn_de"] == "20261015"
    text = result.content[0].text
    assert "| Filed | Company | Title | Category | Filing number |" in text
    assert "SK hynix (005930)" in text


@pytest.mark.anyio
async def test_market_filter_and_final_only_map_to_upstream_codes(client, upstream):
    await client.call_tool(
        "search_filings",
        {"market": "unlisted", "final_only": False, "categories": ["periodic_reports"]},
    )
    (query,) = upstream.params("/list.json")
    assert query["corp_cls"] == "E"
    assert query["pblntf_ty"] == "A"
    assert "last_reprt_at" not in query


@pytest.mark.anyio
async def test_paging_returns_the_exact_next_call(client, upstream):
    def pages(request):
        page = int(request.url.params["page_no"])
        start = 250 - (page - 1) * 100
        numbers = [f"20261022{900000 + n:06d}" for n in range(start, max(start - 100, 0), -1)]
        rows = [row(number, f"Filing {number}", cls="K") for number in numbers]
        return upstream.rows(*rows, total_count=250, total_page=3)

    upstream.route("/list.json", pages)
    first = await client.call_tool("search_filings", {"since": "1d", "limit": 60, "page": 2})
    data = first.structured_content
    assert [f["filing_number"] for f in data["filings"][:1]] == ["20261022900190"]
    assert len(data["filings"]) == 60
    assert [q["page_no"] for q in upstream.params("/list.json")] == ["1", "2"]
    pagination = data["pagination"]
    assert pagination["has_more"] is True
    assert pagination["next_call"] == {
        "tool": "search_filings",
        "arguments": {"since": "2026-10-21", "until": "2026-10-22", "limit": 60, "page": 3},
    }
    text = first.content[0].text
    assert "Showing 61-120 of 250." in text
    assert '"page": 3' in text
    last = await client.call_tool("search_filings", pagination["next_call"]["arguments"])
    assert len(last.structured_content["filings"]) == 60
    assert last.structured_content["pagination"]["has_more"] is True


@pytest.mark.anyio
async def test_title_text_is_matched_client_side(client, upstream):
    upstream.records(
        "/list.json",
        row("20261022800010", "Suspension of Stock Trading"),
        row("20261021800020", "Report on Business Performance (Fair Disclosure)"),
        row("20261020800030", "[Corrected description]Report on BUSINESS  performance"),
        total_count=3,
        total_page=1,
    )
    result = await client.call_tool(
        "search_filings", {"company": "00126380", "title_contains": "business performance"}
    )
    data = result.structured_content
    assert [f["filing_number"] for f in data["filings"]] == ["20261021800020", "20261020800030"]
    assert data["pagination"]["total"] == 2
    assert data["notes"] == []


@pytest.mark.anyio
async def test_title_scans_stop_at_the_budget_with_a_note(client, upstream):
    def busy(request):
        page = int(request.url.params["page_no"])
        rows = [
            row(f"20261022{900000 - page * 100 - n:06d}", "Suspension of Stock Trading")
            for n in range(100)
        ]
        return upstream.rows(*rows, total_count=2335, total_page=24)

    upstream.route("/list.json", busy)
    result = await client.call_tool(
        "search_filings", {"since": "1d", "title_contains": "Business Performance"}
    )
    data = result.structured_content
    assert data["filings"] == []
    assert data["pagination"] == {"page": 1, "limit": 50, "has_more": False}
    assert upstream.count("/list.json") == 5
    assert "matched against the newest 500 filings back to 2026-10-22" in data["notes"][0]


@pytest.mark.anyio
async def test_explicit_wide_windows_need_a_company(client, upstream):
    result = await client.call_tool("search_filings", {"since": "6m"}, raise_on_error=False)
    assert result.is_error
    assert result.content[0].text == (
        "OpenDART limits searches without a company to three months; narrow since/until or pass company."
    )
    assert upstream.count("/list.json") == 0


@pytest.mark.anyio
async def test_the_default_window_is_capped_to_three_months(client, upstream):
    result = await client.call_tool("search_filings", {"until": "2025-05-01"})
    data = result.structured_content
    assert (data["since"], data["until"]) == ("2025-02-01", "2025-05-01")
    assert "starts on 2025-02-01" in data["notes"][0]
    assert upstream.params("/list.json")[0]["bgn_de"] == "20250201"


@pytest.mark.anyio
async def test_no_filings_is_an_empty_result_with_a_note(client):
    result = await client.call_tool("search_filings", {"since": "2d"})
    data = result.structured_content
    assert data["filings"] == []
    assert data["pagination"]["total"] == 0
    assert "No filings by any company matched from 2026-10-20 to 2026-10-22" in data["notes"][0]
    assert "Showing" not in result.content[0].text


@pytest.mark.anyio
async def test_ambiguous_companies_return_candidates(client):
    result = await client.call_tool("search_filings", {"company": "Samsung"}, raise_on_error=False)
    assert result.is_error
    assert "Ambiguous company" in result.content[0].text


@pytest.mark.anyio
async def test_invalid_dates_are_explained(client):
    result = await client.call_tool(
        "search_filings", {"company": "00126380", "since": "soon"}, raise_on_error=False
    )
    assert result.is_error
    assert "Invalid date 'soon'" in result.content[0].text


@pytest.mark.anyio
async def test_unknown_categories_are_rejected_by_the_schema(client):
    result = await client.call_tool(
        "search_filings", {"categories": ["rumors"]}, raise_on_error=False
    )
    assert result.is_error
    assert "categories" in result.content[0].text


@pytest.mark.anyio
async def test_a_missing_api_key_is_explained(mcp_settings, upstream):
    async with Client(create_server(mcp_settings, transport=upstream.transport)) as client:
        result = await client.call_tool("search_filings", {}, raise_on_error=False)
    assert result.is_error
    assert "OPENDART_API__API_KEY" in result.content[0].text


def test_market_wide_rows_tolerate_items_without_a_company():
    from datetime import date

    from opendart_mcp.models.common import Pagination
    from opendart_mcp.models.filings import FilingItem, SearchFilingsResult
    from opendart_mcp.render.filings import render_search_filings

    item = FilingItem(
        filing_number="20261022000001",
        title="Report on Major Issues",
        is_amendment=False,
        dart_url="https://englishdart.fss.or.kr/dsbh001/main.do?rcpNo=20261022000001",
    )
    result = SearchFilingsResult(
        since=date(2026, 10, 21),
        until=date(2026, 10, 22),
        filings=[item],
        pagination=Pagination(total=1, page=1, limit=50, has_more=False),
        as_of=date(2026, 10, 22),
    )
    assert "| - | - | Report on Major Issues | - | 20261022000001 |" in render_search_filings(
        result
    )


@pytest.mark.anyio
async def test_next_calls_page_merged_searches_without_repeats_or_gaps(client, upstream):
    # Upstream order within one day (by time), which filing numbers do not follow.
    groups = {
        "B": ["20261022000505", "20261022000508", "20261022000506", "20261022000492"],
        "I": ["20261022900774", "20261022800778", "20261022900773", "20261022800765"],
    }

    def by_group(request):
        numbers = groups[request.url.params["pblntf_ty"]]
        records = [row(n, "Report", corp_code="00164779", name="SK hynix") for n in numbers]
        return upstream.rows(*records, total_count=4, total_page=1)

    upstream.route("/list.json", by_group)
    arguments = {"categories": ["major_issues", "exchange_disclosures"], "limit": 3}
    seen = []
    while arguments is not None:
        result = await client.call_tool("search_filings", arguments)
        data = result.structured_content
        seen.append([f["filing_number"] for f in data["filings"]])
        assert data["pagination"]["total"] == 8
        arguments = data["pagination"].get("next_call", {}).get("arguments")
    assert [len(page) for page in seen] == [3, 3, 2]
    assert [n for page in seen for n in page] == [
        n for pair in zip(groups["B"], groups["I"], strict=True) for n in pair
    ]
