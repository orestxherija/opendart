"""latest_preliminary: find, open, and parse KRX preliminary-earnings disclosures.

Pages follow the KRX template (period table, then the results table with grouped headers
and quarter/cumulative rows); the figures are invented.
"""

from __future__ import annotations

import io
import zipfile

import anyio
import pytest

from opendart_mcp.core.errors import QuotaExhaustedError, StillRunningError
from opendart_mcp.core.metrics import Metrics
from opendart_mcp.core.runtime import open_state
from opendart_mcp.models.common import CompanyRef
from opendart_mcp.services.companies import Company
from opendart_mcp.services.preliminary import latest_preliminary
from opendart_mcp.settings import DocumentSettings

CONSOLIDATED = "연결재무제표기준영업(잠정)실적(공정공시)"
SEPARATE = "영업(잠정)실적(공정공시)"
TITLE = "Report on Business Performance according to Consolidated Financial Statements (Fair Disclosure)"
DASHES = ("-",) * 7
Q3 = (("당기실적", "2026-07-01", "2026-09-30"), ("전기실적", "2026-04-01", "2026-06-30"))
Q2 = (("당기실적", "2026-04-01", "2026-06-30"), ("전기실적", "2026-01-01", "2026-03-31"))
GUIDANCE = (
    (
        "매출액",
        ("80.00", "70.00", "14.29", "-", "75.00", "6.67", "-"),
        ("220.00", "-", "-", "-", "200.00", "10.00", "-"),
    ),
    (
        "영업이익",
        ("10.00", "8.00", "25.00", "-", "9.00", "11.11", "-"),
        ("27.00", "-", "-", "-", "24.00", "12.50", "-"),
    ),
    ("법인세비용차감전계속사업이익", DASHES, DASHES),
    ("당기순이익", DASHES, DASHES),
)
COMPLETE = (
    (
        "매출액",
        ("700,000", "650,000", "7.69", "-", "600,000", "16.67", "-"),
        ("1,350,000", "-", "-", "-", "1,200,000", "12.50", "-"),
    ),
    (
        "영업이익",
        ("80,000", "70,000", "14.29", "-", "50,000", "60.00", "-"),
        ("150,000", "-", "-", "-", "90,000", "66.67", "-"),
    ),
    (
        "법인세비용차감전계속사업이익",
        ("90,000", "75,000", "20.00", "-", "60,000", "50.00", "-"),
        DASHES,
    ),
    ("당기순이익", ("70,000", "60,000", "16.67", "-", "45,000", "55.56", "-"), DASHES),
)


def cells(values):
    return "".join(f"<td><span>{value}</span></td>" for value in values)


def page(*, form=CONSOLIDATED, unit="조원", periods=Q3, rows=GUIDANCE):
    period_rows = "".join(
        f"<tr><td><span>{label}</span></td>{cells((start, "~", end))}</tr>"
        for label, start, end in periods
    )
    data_rows = "".join(
        f'<tr><td rowspan="2"><span>{label}</span></td>{cells(("당해실적", *quarter))}</tr>'
        + f"<tr>{cells(("누계실적", *cumulative))}</tr>"
        for label, quarter, cumulative in rows
    )
    return f"""<html><head><meta content="text/html; charset=euc-kr" http-equiv="Content-Type">
<title>삼성전자/{form}/(2026.10.08){form}</title></head><body>
<table><tbody><tr><td colspan="4"><span>실적기간</span></td></tr>{period_rows}</tbody></table>
<table><tbody>
<tr><td colspan="9"><span>※ 동 정보는 잠정치로서 향후 확정치와는 다를 수 있음.</span></td></tr>
<tr><td colspan="4"><span>1. 연결실적내용</span></td><td colspan="5"><span>단위 : {unit}, %</span></td></tr>
<tr><td colspan="2" rowspan="2"><span>구분</span></td>{cells(("당기실적", "전기실적"))}<td colspan="2"><span>전기대비</span></td><td><span>전년동기실적</span></td><td colspan="2"><span>전년동기대비</span></td></tr>
<tr>{cells(("(26.3Q)", "(26.2Q)", "증감율(%)", "흑자적자전환여부", "(25.3Q)", "증감율(%)", "흑자적자전환여부"))}</tr>
{data_rows}
</tbody></table></body></html>"""


def archive(number, html):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as handle:
        handle.writestr(f"{number}.xml", html.encode())
    return buffer.getvalue()


def error_body(status):
    return f"<result><status>{status}</status><message>m</message></result>".encode()


def listing(number, title):
    return {
        "corp_cls": "Y",
        "corp_name": "SAMSUNG ELECTRONICS",
        "corp_code": "00126380",
        "stock_code": "005930",
        "report_nm": f"{title}              ",
        "rcept_no": number,
        "flr_nm": "삼성전자",
        "rcept_dt": number[:8],
        "rm": "S",
    }


SAMSUNG = Company(
    ref=CompanyRef(name="SAMSUNG ELECTRONICS", corp_code="00126380", stock_code="005930"),
    fye_month=12,
    profile=None,
)


def serve(upstream, documents, *rows):
    upstream.records("/list.json", *rows)

    def document(request):
        body = documents[request.url.params["rcept_no"]]
        return body if isinstance(body, bytes) else archive(request.url.params["rcept_no"], body)

    upstream.route("/document.xml", document)


@pytest.fixture
async def state(mcp_settings, sdk_settings, upstream, now):
    upstream.route("/corpCode.xml", upstream.corp_archive())
    async with open_state(
        mcp_settings,
        metrics=Metrics(),
        api=sdk_settings,
        transport=upstream.transport,
        clock=lambda: now,
    ) as opened:
        # Wait for the directory so company identity does not depend on load timing.
        await opened.directory.wait(5)
        yield opened


@pytest.mark.anyio
async def test_the_newest_quarter_is_returned(state, upstream):
    serve(
        upstream,
        {"20261008800004": page(), "20260730800077": page(unit="억원", periods=Q2, rows=COMPLETE)},
        listing("20261013800651", "Report on Shares Change of Largest Shareholders"),
        listing("20261008800004", TITLE),
        listing("20260730800077", TITLE),
    )
    messages = []

    async def progress(message):
        messages.append(message)

    result = await latest_preliminary(state, SAMSUNG, progress=progress)
    assert result is not None
    assert result.source.filing_number == "20261008800004"
    assert result.source.title == TITLE
    assert result.source.filed.isoformat() == "2026-10-08"
    earnings = result.earnings
    assert (earnings.basis, earnings.unit_multiplier) == ("consolidated", 10**12)
    revenue = earnings.rows[0]
    assert (revenue.metric, revenue.current_quarter.krw) == ("revenue", 80 * 10**12)
    assert revenue.quarter_on_quarter.percent == 14.29
    assert result.notes == []
    assert messages == ["Reading preliminary earnings in filing 20261008800004"]
    (query,) = upstream.params("/list.json")
    assert query == {
        "corp_code": "00126380",
        "bgn_de": "20260624",
        "end_de": "20261022",
        "last_reprt_at": "Y",
        "pblntf_detail_ty": "I002",
        "page_count": "100",
    }
    assert upstream.count("/document.xml") == 1


@pytest.mark.anyio
async def test_a_complete_release_beats_newer_guidance_for_the_same_quarter(state, upstream):
    serve(
        upstream,
        {
            "20260730800103": page(periods=Q2),
            "20260730800077": page(unit="억원", periods=Q2, rows=COMPLETE),
        },
        listing("20260730800103", f"[Corrected description]{TITLE}"),
        listing("20260730800077", TITLE),
    )
    result = await latest_preliminary(state, SAMSUNG)
    assert result is not None
    assert result.source.filing_number == "20260730800077"
    net = next(row for row in result.earnings.rows if row.metric == "net_profit")
    assert net.current_quarter.krw == 70_000 * 10**8
    assert result.notes == [
        "Filing 20260730800103 reports only revenue and operating profit; the complete release 20260730800077 for the same quarter is used."
    ]


@pytest.mark.anyio
async def test_unreadable_and_other_templates_are_skipped(state, upstream):
    serve(
        upstream,
        {
            "20261010800001": error_body("014"),
            "20261009800001": page(form="영업실적등에대한전망(공정공시)"),
            "20261008800004": page(),
        },
        listing("20261010800001", TITLE),
        listing("20261009800001", "Forecast of Business Performance (Fair Disclosure)"),
        listing("20261008800004", TITLE),
    )
    result = await latest_preliminary(state, SAMSUNG)
    assert result is not None
    assert result.source.filing_number == "20261008800004"
    assert result.notes == [
        f"Filing 20261010800001 ({TITLE}) could not be opened, so it was skipped.",
        "Filing 20261009800001 (Forecast of Business Performance (Fair Disclosure)) does not use the preliminary-results table.",
    ]


@pytest.mark.anyio
async def test_consolidated_results_come_first_on_the_same_day(state, upstream):
    serve(
        upstream,
        {
            "20261008800009": page(form=SEPARATE),
            "20261008800004": page(),
        },
        listing("20261008800009", "Report on Business Performance (Fair Disclosure)"),
        listing("20261008800004", TITLE),
    )
    result = await latest_preliminary(state, SAMSUNG)
    assert result is not None
    assert result.source.filing_number == "20261008800004"


@pytest.mark.anyio
async def test_guidance_for_an_older_quarter_is_not_merged(state, upstream):
    serve(
        upstream,
        {"20261008800004": page(), "20260707800004": page(periods=Q2)},
        listing("20261008800004", TITLE),
        listing("20260707800004", TITLE),
    )
    result = await latest_preliminary(state, SAMSUNG)
    assert result is not None
    assert result.source.filing_number == "20261008800004"
    assert result.notes == []


@pytest.mark.anyio
async def test_no_preliminary_disclosure_returns_none(state, upstream):
    upstream.records(
        "/list.json", listing("20261013800651", "Organization of Investor Relations Event")
    )
    assert await latest_preliminary(state, SAMSUNG) is None
    upstream.route("/list.json", upstream.status("013"))
    assert await latest_preliminary(state, SAMSUNG) is None
    assert upstream.count("/document.xml") == 0


@pytest.mark.anyio
async def test_nothing_readable_returns_none(state, upstream):
    serve(upstream, {"20261008800004": error_body("013")}, listing("20261008800004", TITLE))
    assert await latest_preliminary(state, SAMSUNG) is None


@pytest.mark.anyio
async def test_quota_errors_are_not_skipped(state, upstream):
    serve(upstream, {"20261008800004": error_body("020")}, listing("20261008800004", TITLE))
    with pytest.raises(QuotaExhaustedError, match="quota"):
        await latest_preliminary(state, SAMSUNG)


@pytest.mark.anyio
async def test_slow_downloads_ask_for_a_retry(mcp_settings, sdk_settings, upstream, now):
    release = anyio.Event()

    async def slow(request):
        await release.wait()
        return archive("20261008800004", page())

    upstream.records("/list.json", listing("20261008800004", TITLE))
    upstream.route("/document.xml", slow)
    settings = mcp_settings.model_copy(update={"documents": DocumentSettings(wait=0.1)})
    async with open_state(
        settings,
        metrics=Metrics(),
        api=sdk_settings,
        transport=upstream.transport,
        clock=lambda: now,
    ) as state:
        with pytest.raises(StillRunningError, match="Repeat the same call"):
            await latest_preliminary(state, SAMSUNG)
        release.set()
        await anyio.sleep(0.05)
        result = await latest_preliminary(state, SAMSUNG)
    assert result is not None
    assert upstream.count("/document.xml") == 1


@pytest.mark.anyio
async def test_a_recent_release_for_another_quarter_is_not_used(state, upstream):
    serve(
        upstream,
        {
            "20261008800004": page(),
            "20260915800001": page(unit="억원", periods=Q2, rows=COMPLETE),
        },
        listing("20261008800004", TITLE),
        listing("20260915800001", TITLE),
    )
    result = await latest_preliminary(state, SAMSUNG)
    assert result is not None
    assert result.source.filing_number == "20261008800004"
    assert result.notes == []
    assert upstream.count("/document.xml") == 2
