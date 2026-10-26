"""Company filing index, filing outline, and filing section resources."""

from __future__ import annotations

import io
import json
import zipfile

import pytest
from mcp.shared.exceptions import MCPError

NUMBER = "20260515002181"
QUARTERLY = """<?xml version="1.0" encoding="utf-8"?>
<DOCUMENT xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="dart4.xsd">
<DOCUMENT-NAME ACODE="11013">분기보고서</DOCUMENT-NAME>
<COMPANY-NAME AREGCIK="00126380">삼성전자</COMPANY-NAME>
<BODY>
<SECTION-1><TITLE ATOC="Y" AASSOCNOTE="D-0-1-0-0" ENG="I. Company Overview">I. 회사의 개요</TITLE>
<SECTION-2><TITLE ATOC="Y" AASSOCNOTE="D-0-1-1-0" ENG="1. Company overview">1. 회사의 개요</TITLE>
<P>당사는 R&D 중심 회사입니다.</P>
</SECTION-2></SECTION-1>
<SECTION-1><TITLE ATOC="Y" AASSOCNOTE="D-0-3-0-0" ENG="III. Financial Matters">III. 재무에 관한 사항</TITLE>
<SECTION-2><TITLE ATOC="Y" AASSOCNOTE="D-0-3-3-0" ENG="3. Notes to Consolidated Financial Statements">3. 연결재무제표 주석</TITLE>
<P>주석 본문</P>
</SECTION-2></SECTION-1>
</BODY>
</DOCUMENT>
"""


def archive():
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as handle:
        handle.writestr(f"{NUMBER}.xml", QUARTERLY.encode())
    return buffer.getvalue()


def row(number, title):
    return {
        "corp_cls": "Y",
        "corp_name": "SAMSUNG ELECTRONICS",
        "corp_code": "00126380",
        "stock_code": "005930",
        "report_nm": title,
        "rcept_no": number,
        "flr_nm": "삼성전자",
        "rcept_dt": number[:8],
        "rm": "",
    }


@pytest.mark.anyio
async def test_filing_templates_are_listed_with_mime_types(client):
    templates = {t.uri_template: t for t in await client.list_resource_templates()}
    index = templates["opendart://company/{corp_code}/filings{?since,category}"]
    outline = templates["opendart://filing/{filing_number}"]
    section = templates["opendart://filing/{filing_number}/sections/{section_id}"]
    assert (index.mime_type, outline.mime_type, section.mime_type) == (
        "application/json",
        "application/json",
        "text/markdown",
    )
    for template in (index, outline, section):
        assert template.meta is not None
        assert template.meta["fastmcp"]["version"] == "1.0.0"
        assert template.annotations is not None
        assert template.annotations.audience == ["assistant"]
        assert template.description is not None
        assert "Args:" not in template.description
    assert "last 90 days" in index.description


@pytest.mark.anyio
async def test_company_filing_index_defaults_to_90_days(client, upstream):
    upstream.records("/list.json", row(NUMBER, "Quarterly Report (2026.03)"), total_count=1)
    (content,) = await client.read_resource("opendart://company/00126380/filings")
    assert content.mime_type == "application/json"
    data = json.loads(content.text)
    assert (data["since"], data["until"]) == ("2026-07-24", "2026-10-22")
    assert data["company"]["corp_code"] == "00126380"
    assert data["filings"][0]["category"] == "quarterly_report"
    assert data["pagination"]["limit"] == 100
    (query,) = upstream.params("/list.json")
    assert query["corp_code"] == "00126380"
    assert query["bgn_de"] == "20260724"
    assert "pblntf_ty" not in query
    assert "pblntf_detail_ty" not in query


@pytest.mark.anyio
async def test_company_filing_index_takes_since_and_category(client, upstream):
    (content,) = await client.read_resource(
        "opendart://company/00126380/filings?since=2026-01-01&category=fair_disclosure"
    )
    data = json.loads(content.text)
    assert data["filings"] == []
    assert data["since"] == "2026-01-01"
    (query,) = upstream.params("/list.json")
    assert query["pblntf_detail_ty"] == "I002"
    assert "pblntf_ty" not in query
    assert query["bgn_de"] == "20260101"


@pytest.mark.anyio
async def test_unknown_categories_are_explained(client):
    with pytest.raises(
        MCPError, match="Unknown filing category 'rumors'; use one of: periodic_reports"
    ):
        await client.read_resource("opendart://company/00126380/filings?category=rumors")


@pytest.mark.anyio
async def test_filing_outline_is_json(client, upstream):
    upstream.route("/document.xml", archive())
    (content,) = await client.read_resource(f"opendart://filing/{NUMBER}")
    assert content.mime_type == "application/json"
    data = json.loads(content.text)
    assert data["mode"] == "outline"
    assert data["filing"]["form_name"] == "Quarterly Report"
    assert [s["id"] for s in data["outline"]["sections"]] == [
        "D-0-1-0-0",
        "D-0-1-1-0",
        "D-0-3-0-0",
        "D-0-3-3-0",
    ]


@pytest.mark.anyio
async def test_filing_sections_are_markdown_by_id_or_alias(client, upstream):
    upstream.route("/document.xml", archive())
    (content,) = await client.read_resource(f"opendart://filing/{NUMBER}/sections/D-0-1-1-0")
    assert content.mime_type == "text/markdown"
    assert content.text.startswith("## 1. Company overview [D-0-1-1-0]")
    assert "R&D" in content.text
    (notes,) = await client.read_resource(f"opendart://filing/{NUMBER}/sections/consolidated_notes")
    assert notes.text.startswith("## 3. Notes to Consolidated Financial Statements [D-0-3-3-0]")
    assert upstream.count("/document.xml") == 1


@pytest.mark.anyio
async def test_unknown_sections_list_the_closest_ones(client, upstream):
    upstream.route("/document.xml", archive())
    with pytest.raises(MCPError, match=f"No section of filing {NUMBER} matches 'dividends'"):
        await client.read_resource(f"opendart://filing/{NUMBER}/sections/dividends")


@pytest.mark.anyio
async def test_malformed_and_unknown_filings_are_explained(client, upstream):
    with pytest.raises(MCPError, match="'12345' is not a filing number"):
        await client.read_resource("opendart://filing/12345")
    upstream.route("/document.xml", b"<result><status>013</status><message>m</message></result>")
    with pytest.raises(MCPError, match=f"OpenDART has no filing {NUMBER}"):
        await client.read_resource(f"opendart://filing/{NUMBER}/sections/D-0-1-1-0")
