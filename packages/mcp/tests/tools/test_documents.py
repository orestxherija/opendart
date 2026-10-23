"""read_filing over the MCP protocol: outline, read, search, errors, and both task modes.

Archives are synthetic: DART XML with an unescaped ampersand, nested sections with and
without codes and English titles, a table, an image, attachments, an amendment section, and
a KRX page. Download errors are XML bodies, as OpenDART sends them for document.xml.
"""

from __future__ import annotations

import io
import uuid
import zipfile

import anyio
import pytest
from fastmcp import Client
from fastmcp_tasks import call_tool_task

from opendart_mcp.server import create_server
from opendart_mcp.settings import (
    DirectorySettings,
    DocumentSettings,
    HttpSettings,
    Settings,
    TaskSettings,
)

ANNUAL = "20260310002820"
KRX = "20261022800010"
PROSE = "당사는 반도체와 R&D 중심의 전자 회사입니다. " * 30

CORRECTION = """<CORRECTION><TITLE ATOC="Y">정 정 신 고 (보고)</TITLE>
<TABLE><TBODY>
<TR><TD>정정대상 공시서류</TD><TD>사업보고서</TD></TR>
<TR><TD>정정대상 공시서류의 최초제출일</TD><TD>2026년 03월 10일</TD></TR>
<TR><TD>정정사유</TD><TD>오기 정정</TD></TR>
</TBODY></TABLE>
<TABLE><TBODY>
<TR><TH>정정항목</TH><TH>정정전</TH><TH>정정후</TH></TR>
<TR><TD>직원 수</TD><TD>100명</TD><TD>110명</TD></TR>
</TBODY></TABLE></CORRECTION>"""


def dart(form_code="11011", form="사업보고서", *, correction="", extra=""):
    return f"""<?xml version="1.0" encoding="utf-8"?>
<DOCUMENT xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="dart4.xsd">
<DOCUMENT-NAME ACODE="{form_code}">{form}</DOCUMENT-NAME>
<COMPANY-NAME AREGCIK="00126380">삼성전자</COMPANY-NAME>
<BODY>{correction}
<COVER><COVER-TITLE ENG="Annual Report">사 업 보 고 서</COVER-TITLE><P>M&A 및 R&D</P></COVER>
<SECTION-1><TITLE ATOC="Y" AASSOCNOTE="D-0-1-0-0" ENG="I. Company Overview">I. 회사의 개요</TITLE>
<SECTION-2><TITLE ATOC="Y" AASSOCNOTE="D-0-1-1-0" ENG="1. Company overview">1. 회사의 개요</TITLE>
<P>{PROSE}</P>
<TABLE><TBODY><TR><TH>구분</TH><TH ENG="Amount">금액</TH></TR><TR><TD>매출액</TD><TD>1,234</TD></TR></TBODY></TABLE>
</SECTION-2>
<SECTION-2><TITLE ATOC="Y" ATOCID="7">2. 회사의 연혁</TITLE><P>1969년 설립</P></SECTION-2>
</SECTION-1>
<SECTION-1><TITLE ATOC="Y" AASSOCNOTE="D-0-3-0-0" ENG="III. Financial Matters">III. 재무에 관한 사항</TITLE>
<SECTION-2><TITLE ATOC="Y" AASSOCNOTE="D-0-3-3-0" ENG="3. Notes to Consolidated Financial Statements">3. 연결재무제표 주석</TITLE>
<P>전환사채의 공정가치는 다음과 같습니다.</P><P>전환 사채 상환 일정</P>
<IMAGE><IMG>chart.jpg</IMG><IMG-CAPTION>조직도</IMG-CAPTION></IMAGE>
</SECTION-2>
</SECTION-1>{extra}
</BODY>
</DOCUMENT>
"""


def krx_page():
    return """<html><head><meta charset="euc-kr"><title>삼성전자/단일판매ㆍ공급계약체결/(2026.10.22)단일판매ㆍ공급계약체결</title>
<style>td {font-size: 9pt}</style></head><body>
<table><tr><td>1. 판매ㆍ공급계약 내용</td><td><span class="xforms_input">반도체 공급</span></td></tr>
<tr><td>2. 계약금액(원)</td><td><span class="xforms_input">1,000,000,000</span></td></tr></table>
</body></html>"""


def archive(members):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as handle:
        for name, text in members.items():
            handle.writestr(name, text if isinstance(text, bytes) else text.encode())
    return buffer.getvalue()


def annual_archive(**kwargs):
    return archive(
        {
            f"{ANNUAL}.xml": dart(**kwargs),
            f"{ANNUAL}_00760.xml": dart("00760", "감사보고서"),
            f"{ANNUAL}_00761.xml": dart("00761", "연결감사보고서"),
        }
    )


def error_body(status):
    return f'<?xml version="1.0" encoding="UTF-8"?><result><status>{status}</status><message>status {status}</message></result>'.encode()


async def read(client, **arguments):
    return await client.call_tool("read_filing", arguments, raise_on_error=False)


@pytest.mark.anyio
async def test_read_filing_is_listed_as_an_optional_task(client, server):
    tools = await client.list_tools()
    names = [tool.name for tool in tools]
    assert names.index("read_filing") == names.index("search_filings") + 1
    tool = tools[names.index("read_filing")]
    assert tool.meta is not None
    assert tool.meta["fastmcp"]["version"] == "1.0.0"
    assert tool.annotations is not None
    assert tool.annotations.read_only_hint is True
    schema = tool.input_schema
    assert schema["required"] == ["filing_number"]
    assert schema["properties"]["filing_number"]["pattern"] == r"^\d{14}$"
    assert schema["properties"]["max_chars"]["maximum"] == 30000
    assert schema["properties"]["mode"]["enum"] == ["outline", "read", "search"]
    assert tool.output_schema is not None
    assert {"filing", "mode", "outline", "page", "search"} <= set(tool.output_schema["properties"])
    async with Client(server, mode="legacy") as legacy:
        legacy_tool = next(t for t in await legacy.list_tools() if t.name == "read_filing")
    assert legacy_tool.execution is not None
    assert legacy_tool.execution.task_support == "optional"


@pytest.mark.anyio
async def test_outline_lists_documents_sections_and_aliases(client, upstream):
    upstream.route("/document.xml", annual_archive())
    result = await read(client, filing_number=ANNUAL)
    data = result.structured_content
    assert data["filing"] == {
        "filing_number": ANNUAL,
        "form_code": "11011",
        "form_name": "Annual Report",
        "form_name_ko": "사업보고서",
        "company": "삼성전자",
        "corp_code": "00126380",
        "filed": "2026-03-10",
        "is_amendment": False,
        "format": "dart_xml",
        "language": "ko",
        "dart_url": f"https://englishdart.fss.or.kr/dsbh001/main.do?rcpNo={ANNUAL}",
    }
    assert (data["mode"], data["document"]) == ("outline", "main")
    outline = data["outline"]
    assert [d["key"] for d in outline["documents"]] == [
        "main",
        "audit_report",
        "consolidated_audit_report",
    ]
    ids = [s["id"] for s in outline["sections"]]
    assert ids[1:] == ["D-0-1-0-0", "D-0-1-1-0", "s7", "D-0-3-0-0", "D-0-3-3-0"]
    history = outline["sections"][3]
    assert history == {
        "id": "s7",
        "level": 2,
        "title_ko": "2. 회사의 연혁",
        "chars": history["chars"],
        "tables": 0,
    }
    aliases = {a["alias"]: a["section_ids"] for a in outline["suggested_sections"]}
    assert aliases["company_overview"] == ["D-0-1-1-0"]
    assert any("attachments" in note for note in data["notes"])
    assert data["source_filings"][0]["title"] == "Annual Report"
    assert upstream.params("/document.xml") == [{"rcept_no": ANNUAL}]
    text = result.content[0].text
    assert text.startswith(
        "**Annual Report (사업보고서)**: 삼성전자, DART 00126380; filed 2026-03-10"
    )
    assert (
        "| D-0-3-3-0 | · 3. Notes to Consolidated Financial Statements | 3. 연결재무제표 주석 |"
        in text
    )
    assert "| s7 | · 2. 회사의 연혁 | - |" in text
    assert "Section aliases: company_overview (D-0-1-1-0)" in text
    assert "### Documents" in text


@pytest.mark.anyio
async def test_read_pages_through_a_section_by_alias(client, upstream):
    upstream.route("/document.xml", annual_archive())
    first = await read(
        client, filing_number=ANNUAL, mode="read", section="company_overview", max_chars=500
    )
    page = first.structured_content["page"]
    assert page["section"]["id"] == "D-0-1-1-0"
    assert page["content"].startswith("## 1. Company overview [D-0-1-1-0]")
    assert page["truncated"] is True
    assert page["offset"] == 0
    assert 0 < page["next_offset"] < page["total_chars"]
    assert f"repeat the call with offset={page["next_offset"]}" in first.content[0].text
    rest = await read(
        client,
        filing_number=ANNUAL,
        mode="read",
        section="company_overview",
        offset=page["next_offset"],
        max_chars=30000,
    )
    last = rest.structured_content["page"]
    assert last["truncated"] is False
    assert "next_offset" not in last
    assert "| 구분 | Amount |" in last["content"]
    assert upstream.count("/document.xml") == 1


@pytest.mark.anyio
async def test_read_in_korean_labels_and_past_the_end(client, upstream):
    upstream.route("/document.xml", annual_archive())
    korean = await read(
        client, filing_number=ANNUAL, mode="read", section="D-0-1-1-0", labels="korean"
    )
    assert "| 구분 | 금액 |" in korean.structured_content["page"]["content"]
    past = await read(client, filing_number=ANNUAL, mode="read", offset=10_000_000)
    data = past.structured_content
    assert data["page"]["content"] == ""
    assert "section" not in data["page"]
    assert any("past the end" in note for note in data["notes"])
    assert "Whole document" in past.content[0].text


@pytest.mark.anyio
async def test_search_returns_passages_with_offsets(client, upstream):
    upstream.route("/document.xml", annual_archive())
    result = await read(client, filing_number=ANNUAL, mode="search", query="전환사채")
    search = result.structured_content["search"]
    assert search["query"] == "전환사채"
    assert search["total_hits"] == 2
    hit = search["hits"][0]
    assert hit["section_id"] == "D-0-3-3-0"
    assert hit["section_title_en"] == "3. Notes to Consolidated Financial Statements"
    assert "전환사채의 공정가치" in hit["snippet"]
    text = result.content[0].text
    assert '2 matches for "전환사채" in 1 passage.' in text
    assert "1. D-0-3-3-0 (3. Notes to Consolidated Financial Statements), offset" in text
    assert "and the same labels" in text
    scoped = await read(client, filing_number=ANNUAL, mode="search", query="설립", section="s7")
    assert scoped.structured_content["search"]["section"] == "s7"
    assert '1 match for "설립" in section s7 in 1 passage.' in scoped.content[0].text


@pytest.mark.anyio
async def test_search_needs_a_query(client, upstream):
    upstream.route("/document.xml", annual_archive())
    result = await read(client, filing_number=ANNUAL, mode="search", query="   ")
    assert result.is_error
    assert "mode='search' needs query" in result.content[0].text
    assert upstream.count("/document.xml") == 0


@pytest.mark.anyio
async def test_arguments_a_mode_ignores_are_noted(client, upstream):
    upstream.route("/document.xml", annual_archive())
    result = await read(client, filing_number=ANNUAL, section="business", query="x")
    assert result.structured_content["notes"][0] == "Ignored in outline mode: section, query."


@pytest.mark.anyio
async def test_unknown_sections_list_the_closest_ones(client, upstream):
    upstream.route("/document.xml", annual_archive())
    result = await read(
        client, filing_number=ANNUAL, mode="read", section="zzz quarterly dividends"
    )
    assert result.is_error
    message = result.content[0].text
    assert message.startswith(f"No section of filing {ANNUAL} matches 'zzz quarterly dividends'.")
    assert "Closest sections:" in message
    assert "mode='outline' lists the sections" in message


@pytest.mark.anyio
async def test_attachments_are_read_by_key_and_unknown_keys_listed(client, upstream):
    upstream.route("/document.xml", annual_archive())
    audit = await read(client, filing_number=ANNUAL, document="00760")
    assert audit.structured_content["document"] == "audit_report"
    assert "document audit_report" in audit.content[0].text
    missing = await read(client, filing_number=ANNUAL, document="articles")
    assert missing.is_error
    assert missing.content[0].text == (
        f"Filing {ANNUAL} has no document 'articles'. Use one of: main, audit_report, consolidated_audit_report."
    )


@pytest.mark.anyio
async def test_amended_filings_summarize_their_changes(client, upstream):
    upstream.route("/document.xml", archive({f"{ANNUAL}.xml": dart(correction=CORRECTION)}))
    result = await read(client, filing_number=ANNUAL)
    data = result.structured_content
    assert data["filing"]["is_amendment"] is True
    amendment = data["outline"]["amendment"]
    assert amendment["original_filed"] == "2026-03-10"
    assert amendment["changes"] == [
        {"item": "직원 수", "reason": "오기 정정", "before": "100명", "after": "110명"}
    ]
    text = result.content[0].text
    assert "### Amendment" in text
    assert "Corrects a filing filed 2026-03-10 (사업보고서). Reason: 오기 정정" in text
    assert "| 직원 수 | 100명 | 110명 |" in text
    assert "amended filing" in text


@pytest.mark.anyio
async def test_krx_disclosures_read_as_one_section(client, upstream):
    upstream.route("/document.xml", archive({f"{KRX}.xml": krx_page()}))
    outline = await read(client, filing_number=KRX)
    data = outline.structured_content
    assert data["filing"]["format"] == "krx_html"
    assert "form_code" not in data["filing"]
    assert [s["id"] for s in data["outline"]["sections"]] == ["body"]
    page = await read(client, filing_number=KRX, mode="read")
    content = page.structured_content["page"]["content"]
    assert "2. 계약금액(원): 1,000,000,000" in content


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("013", f"OpenDART has no filing {ANNUAL}. Pass the 14-digit filing_number"),
        ("014", f"cannot provide the document of filing {ANNUAL} (status 014)"),
        ("020", "daily request quota"),
    ],
)
async def test_download_statuses_become_instructions(client, upstream, status, expected):
    upstream.route("/document.xml", error_body(status))
    result = await read(client, filing_number=ANNUAL)
    assert result.is_error
    assert expected in result.content[0].text
    if status == "014":
        assert f"main.do?rcpNo={ANNUAL}" in result.content[0].text


@pytest.mark.anyio
async def test_oversized_and_unreadable_archives_link_the_viewer(client, upstream):
    upstream.route("/document.xml", archive({f"m{n}.xml": dart() for n in range(21)}))
    crowded = await read(client, filing_number=ANNUAL)
    assert crowded.is_error
    assert (
        "too large to open here (Archive exceeds the members limit: 21 > 20)"
        in crowded.content[0].text
    )
    assert f"rcpNo={ANNUAL}" in crowded.content[0].text
    upstream.route("/document.xml", archive({"chart.png": b"\x89PNG\r\n\x1a\nbinary"}))
    binary = await read(client, filing_number=ANNUAL)
    assert binary.is_error
    assert (
        "could not be read (The archive holds no DART XML or KRX HTML document)"
        in binary.content[0].text
    )


@pytest.mark.anyio
async def test_malformed_filing_numbers_fail_validation(client, upstream):
    result = await read(client, filing_number="2026031000282")
    assert result.is_error
    assert upstream.count("/document.xml") == 0


@pytest.mark.anyio
async def test_slow_downloads_continue_and_are_cached(mcp_settings, sdk_settings, upstream, now):
    release = anyio.Event()

    async def slow(request):
        await release.wait()
        return annual_archive()

    upstream.route("/corpCode.xml", upstream.corp_archive())
    upstream.route("/document.xml", slow)
    settings = mcp_settings.model_copy(update={"documents": DocumentSettings(wait=0.2)})
    server = create_server(
        settings, api=sdk_settings, transport=upstream.transport, clock=lambda: now
    )

    class NoTasksClient(Client):
        _auto_internal_extensions = False

    async with NoTasksClient(server) as client:
        pending = await read(client, filing_number=ANNUAL)
        assert pending.is_error
        assert pending.content[0].text.startswith(f"Filing {ANNUAL} is still downloading")
        assert "Repeat the same call in about a minute" in pending.content[0].text
        release.set()
        await anyio.sleep(0.05)
        done = await read(client, filing_number=ANNUAL)
    assert done.structured_content["outline"]["sections"]
    assert upstream.count("/document.xml") == 1


@pytest.mark.anyio
async def test_background_tasks_return_the_same_result(client, upstream):
    upstream.route("/document.xml", annual_archive())
    task = await call_tool_task(client, "read_filing", {"filing_number": ANNUAL, "mode": "read"})
    assert task.create_result.status == "working"
    result = await task.result()
    assert result.structured_content["page"]["content"].startswith("# Annual Report")


@pytest.mark.anyio
async def test_a_client_without_tasks_gets_a_direct_result(server, upstream):
    upstream.route("/document.xml", annual_archive())
    async with Client(server, mode="legacy") as legacy:
        result = await legacy.call_tool("read_filing", {"filing_number": ANNUAL})
    assert result.structured_content["outline"]["documents"][0]["key"] == "main"


@pytest.mark.anyio
async def test_a_missing_api_key_is_explained(upstream):
    settings = Settings(
        http=HttpSettings(rate_limit=None),
        directory=DirectorySettings(cache_dir=None),
        tasks=TaskSettings(queue=f"test-{uuid.uuid4().hex[:12]}"),
    )
    async with Client(create_server(settings, transport=upstream.transport)) as client:
        result = await read(client, filing_number=ANNUAL)
    assert result.is_error
    assert "OPENDART_API__API_KEY" in result.content[0].text


QUARTERLY_EXTRA = """
<SECTION-1><TITLE ATOC="Y" AASSOCNOTE="D-0-4-0-0" ENG="IV. Management's Discussion and Analysis">IV. 이사의 경영진단 및 분석의견</TITLE>
<P>기업공시서식 작성기준에 따라 분기보고서에 기재하지 않습니다.</P></SECTION-1>
<SECTION-1><TITLE ATOC="Y" ATOCID="9">조직도</TITLE><IMAGE><IMG>org.jpg</IMG></IMAGE></SECTION-1>"""


@pytest.mark.anyio
async def test_placeholder_and_image_only_sections_are_flagged(client, upstream):
    upstream.route(
        "/document.xml",
        archive({f"{ANNUAL}.xml": dart("11013", "분기보고서", extra=QUARTERLY_EXTRA)}),
    )
    result = await read(client, filing_number=ANNUAL)
    data = result.structured_content
    sections = {s["id"]: s for s in data["outline"]["sections"]}
    assert sections["D-0-4-0-0"]["placeholder"] is True
    assert sections["s9"]["image_only"] is True
    assert "placeholder" not in sections["D-0-1-1-0"]
    assert any(note.startswith("MD&A sections (D-0-4-*)") for note in data["notes"])
    text = result.content[0].text
    assert "| omitted |" in text
    assert "| images only |" in text
    mdna = await read(client, filing_number=ANNUAL, mode="read", section="mdna")
    assert "only states that the item is omitted" in mdna.structured_content["notes"][0]
