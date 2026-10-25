"""Synthetic filing archives that reproduce the structures seen in live OpenDART documents.

The fixtures are small, hand-written imitations of DART XML (periodic report, amended major-
issue report, audit reports) and KRX HTML (ad hoc and preliminary-earnings pages). They keep
the quirks the parser must tolerate: an XML prolog with unescaped ``&``, unclosed tags, nested
sections with and without codes, spanned tables, units in caption tables, images, and an
amendment section. No real filing text is used.
"""

from __future__ import annotations

import io
import zipfile

import pytest

PROLOG = """<?xml version="1.0" encoding="utf-8"?>
<!DOCTYPE DOCUMENT [<!ENTITY boom "expanded">]>
<DOCUMENT xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xsi:noNamespaceSchemaLocation="dart4.xsd">
"""


def dart(body: str, *, code: str = "11013", name: str = "분기보고서") -> str:
    """Wrap a DART BODY in the document prolog and metadata."""
    return f"""{PROLOG}<DOCUMENT-NAME ACODE="{code}">{name}</DOCUMENT-NAME>
<FORMULA-VERSION ADATE="20260501">6.5</FORMULA-VERSION>
<COMPANY-NAME AREGCIK="00999999">테스트전자(주)</COMPANY-NAME>
<SUMMARY><EXTRACTION ACODE="RPT_TP" AFEATURE="BOTH">1</EXTRACTION></SUMMARY>
<BODY>
{body}
</BODY>
</DOCUMENT>
"""


def title(
    text: str,
    eng: str | None = None,
    code: str | None = None,
    toc: str | None = None,
    atoc: str = "Y",
) -> str:
    """Build a TITLE element."""
    attrs = f' ATOC="{atoc}"'
    attrs += f' AASSOCNOTE="{code}"' if code else ""
    attrs += f' ENG="{eng}"' if eng else ""
    attrs += f' ATOCID="{toc}"' if toc else ""
    return f"<TITLE{attrs}>{text}</TITLE>"


COVER = """<COVER>
<COVER-TITLE ATOC="Y" AASSOCNOTE="COVER" ENG="Quarterly Report" ATOCID="1">분 기 보 고 서</COVER-TITLE>
<P USERMARK="F-16 ">(제 28 기)</P>
<TABLE-GROUP ACLASS="COVER"><TABLE ACLASS="EXTRACTION" BORDER="0"><TBODY>
<TR><TD ROWSPAN="2" ENG="Fiscal year">사업연도</TD><TU AUNIT="PERIODFROM" AUNITVALUE="20260101">2026년 01월 01일</TU><TD ENG="From">부터</TD></TR>
<TR><TU AUNIT="PERIODTO" AUNITVALUE="20260331">2026년 03월 31일</TU><TD ENG="To">까지</TD></TR>
</TBODY></TABLE></TABLE-GROUP>
<TABLE ACLASS="NORMAL" BORDER="0"><TBODY>
<TR><TD>회 사 명 :</TD><TD>테스트전자 주식회사</TD></TR>
<TR><TD></TD><TD></TD></TR>
<TR><TD ENG="Occurrence of reasons for relief:">면제사유발생 :</TD><TU ENG="N/A">해당사항 없음</TU></TR>
</TBODY></TABLE>
<PGBRK></PGBRK>
</COVER>
<TITLE ATOC="N" ENG="Table of Contents">목     차</TITLE>"""

CEO = f"""<SECTION-1 AID="CEO-CERT">{title("【 대표이사 등의 확인 】", "【Confirmation by CEO, etc.】", "TTL_CEO_CERT", "2")}
<IMAGE><IMG WIDTH="594">대표이사 확인서.jpg</IMG><IMG-CAPTION ATOC="N">대표이사등의확인ㆍ서명</IMG-CAPTION></IMAGE>
<P></P>
</SECTION-1>"""

OVERVIEW = f"""<SECTION-1>{title("I. 회사의 개요", "I. Company Overview", toc="3")}
<SECTION-2>{title("1. 회사의 개요", "1. Company overview", "D-0-1-1-0", "4")}
<P USERMARK="F-14 B">가. 회사의 법적ㆍ상업적 명칭</P>
<P>당사는 R&D 및 M&A로 성장했으며 C&T와 <SPAN USERMARK="B">협력</SPAN>합니다 &amp; &boom; &lt;끝&gt;</P>
<P># 표시 문단</P>
{title("소규모 표제", "Minor heading", atoc="N")}
</SECTION-2>
<SECTION-2>{title("3. 자본금 변동사항", "3. Changes in capital stock", "D-0-1-3-0", "5")}
<P>당사는 기업공시서식 작성기준에 따라 분기보고서의 본 항목을 기재하지 않습니다.</P>
</SECTION-2>
<SECTION-2>{title("4. 주식의 총수 등", "4. Total number of shares, etc.", "D-0-1-4-0", "6")}
<P>가. 주식의 총수 현황 [단위 : 주]</P>
<TABLE BORDER="1"><THEAD>
<TR><TH ROWSPAN="2" ENG="Classification">구 분</TH><TH COLSPAN="2" ENG="Class of shares">주식의 종류</TH></TR>
<TR><TH ENG="Common">보통주</TH><TH ENG="Preferred">우선주</TH></TR>
</THEAD><TBODY>
<TR><TD ENG="Authorized">발행할 주식의 총수</TD><TD>500,000,000</TD><TD>-</TD></TR>
<TR><TD ENG="Issued">발행한 주식의 총수</TD><TD>16,708,389</TD><TD>-</TD></TR>
</TBODY></TABLE>
</SECTION-2>
</SECTION-1>"""

BUSINESS = f"""<SECTION-1>{title("II. 사업의 내용", "II. Business Description", "D-0-2-0-0", "7")}
<LIBRARY><SECTION-2>{title("5. 위험관리 및 파생거래", "5. Risk management and derivatives transactions", "L-0-2-5-L1", "30")}
<P>환율 변동 위험을 관리합니다. 전환 사채 발행 계획은 없으며 전환사채 잔액도 없습니다.</P>
</SECTION-2></LIBRARY>
</SECTION-1>"""

STATEMENT_ROWS = "".join(
    f'<TR><TE ENG="Line item {n}">계정 {n}</TE><TE ACODE="ifrs-full_X">{n},000</TE><TE>({n}00)</TE></TR>\n'
    for n in range(1, 41)
)

FINANCE = f"""<SECTION-1>{title("III. 재무에 관한 사항", "III. Financial Matters", "D-0-3-0-0", "8")}
<LIBRARY><SECTION-2>{title("2. 연결재무제표", "2. Consolidated financial statements", "D-0-3-2-0", "31")}
<TABLE-GROUP ACLASS="{{XBRL}}BS_C">
{title("2-1. 연결 재무상태표", "2-1. Consolidated Statement Of FinancialPosition", toc="32")}
<TABLE ACLASS="NORMAL" BORDER="0"><TBODY>
<TR><TE ENG="Consolidated Statement Of FinancialPosition">연결 재무상태표</TE></TR>
<TR><TE ENG="FY 2026 03/31/2026 Current">제 28 기 1분기말 2026.03.31 현재</TE></TR>
<TR><TE ENG="(Unit : KRW million)">(단위 : 백만원)</TE></TR>
</TBODY></TABLE>
<TABLE ACLASS="NORMAL" BORDER="1"><THEAD>
<TR><TH>　</TH><TH ENG="FY 2026">제 28 기 1분기말</TH><TH ENG="FY 2025">제 27 기말</TH></TR>
</THEAD><TBODY>
<TR><TE ENG="Assets">자산</TE><TE>　</TE><TE>　</TE></TR>
{STATEMENT_ROWS}</TBODY></TABLE>
</TABLE-GROUP>
</SECTION-2>
<SECTION-2>{title("3. 연결재무제표 주석", "3. Notes to the consolidated financial statements", "D-0-3-3-0", "33")}
{title("1. 일반사항 (연결)", "1. Corporate information (Consolidated)", toc="34")}
<P>지배기업은 전자부품을 제조합니다.</P>
{title("2. 차입금 (연결)", "2. Borrowings (Consolidated)", toc="35")}
<TABLE BORDER="1"><THEAD>
<TR><TH ROWSPAN="2">구분(단위 : 백만원, %)</TH><TH COLSPAN="2" ENG="Current">당기</TH><TH COLSPAN="2" ENG="Prior">전기</TH></TR>
<TR><TH ENG="Amount">금액</TH><TH ENG="Rate">이자율</TH><TH ENG="Amount">금액</TH><TH ENG="Rate">이자율</TH></TR>
</THEAD><TBODY>
<TR><TD ROWSPAN="2">단기|차입금</TD><TD>1,000</TD><TD>3.5</TD><TD>800</TD><TD>4.0</TD></TR>
<TR><TD>200</TD><TD>2.0</TD><TD></TD><TD></TD></TR>
<TR><TD></TD><TD></TD><TD></TD><TD></TD><TD></TD></TR>
</TBODY></TABLE>
</SECTION-2></LIBRARY>
</SECTION-1>"""

MDNA = f"""<SECTION-1>{title("IV. 이사의 경영진단 및 분석의견", "IV. Director\u2019s Management Assessment and Analysis Opinion", "D-0-4-0-0", "9")}
<P></P>
<SECTION-2>{title("1. 예측정보에 대한 주의사항", "1. Forward-Looking Statements", "D-0-4-1-0", "10")}
<P>당사는 기업공시서식 작성기준에 따라 분기보고서의 본 항목을 기재하지 않습니다.</P>
</SECTION-2>
</SECTION-1>
<SECTION-1>{title("XI. 그 밖에 투자자 보호를 위하여 필요한 사항", "XI. Other Matters Necessary for Investor Protection", "D-0-11-0-0", "11")}
<SECTION-2>{title("【상세 기재】", "【Details】", atoc="N")}
<SECTION-3>{title("1. 개요", "1. Overview", atoc="N")}<P>세부 내용입니다.</P></SECTION-3>
<SECTION-3>{title("2. 개요", "2. Overview", atoc="N")}<P>추가 내용입니다.</P><P>미완성 문단</SECTION-3>
</SECTION-2>
<SECTION-2>{title("", atoc="N")}{title("4. 작성기준일 이후 발생한 주요사항 등 기타사항", "4. Other matters", "D-0-11-4-0", "12")}
<P>보고기간 후 사건은 없습니다.</P>
</SECTION-2>
<SECTION-2>{title("4. 중복 항목", "4. Duplicate", "D-0-11-4-0", "13")}<P>중복</P></SECTION-2>
</SECTION-1>"""


def periodic_xml(code: str = "11013", name: str = "분기보고서") -> str:
    """Build a periodic report with every structure the renderer handles."""
    parts = (COVER, CEO, OVERVIEW, BUSINESS, FINANCE, MDNA)
    return dart("\n".join(parts), code=code, name=name)


CORRECTION = """<LIBRARY><CORRECTION>
<TITLE ATOC="Y" AASSOCNOTE="CORRECTION" ENG="Report of Disclosure Revision" ATOCID="3">정 정 신 고 (보고)</TITLE>
<TABLE ACLASS="NORMAL"><TBODY><TR><TD></TD></TR><TR><TD ALIGN="RIGHT">2026년 10월 22일</TD></TR></TBODY></TABLE>
<TABLE ACLASS="NORMAL"><TBODY><TR><TD ENG="1. Disclosure document to be revised:">1. 정정대상 공시서류 :</TD><TD>주요사항보고서(전환사채권 발행결정)</TD></TR></TBODY></TABLE>
<TABLE ACLASS="NORMAL"><TBODY><TR><TD ENG="2. First submission date of disclosure document to be revised:">2. 정정대상 공시서류의 최초제출일 :</TD><TD>2026년 10월 20일</TD></TR></TBODY></TABLE>
<TABLE ACLASS="NORMAL"><THEAD><TR><TH ENG="Items">항  목</TH><TH ENG="Reason for revision">정정사유</TH><TH ENG="Before revision">정 정 전</TH><TH ENG="After revision">정 정 후</TH></TR></THEAD>
<TBODY>
<TR><TD>9-1. 옵션에 관한 사항</TD><TD ROWSPAN="2">인수계약서 수정</TD><TD><P>15일이 경과한 날</P></TD><TD><P>10영업일이 경과한 날</P><P USERMARK="BU">(변경)</P></TD></TR>
<TR><TD>23. 기타 투자판단에 참고할 사항</TD><TD>{long_before}</TD><TD>짧은 내용</TD></TR>
</TBODY></TABLE>
<PGBRK></PGBRK>
</CORRECTION></LIBRARY>"""

DECISION = """<LIBRARY><SECTION-1 ACLASS="MANDATORY">
<TITLE ATOC="Y" AASSOCNOTE="D-0-0-0-0" ENG="Report on Major Issues\uff0fReporting Obligations to the KRX" ATOCID="2">주요사항보고서 / 거래소 신고의무 사항</TITLE>
<TABLE ACLASS="NORMAL" BORDER="0"><TBODY>
<TR><TD COLSPAN="2">금융위원회 / 한국거래소 귀중</TD><TD ALIGN="RIGHT">2026년 10월 22일</TD></TR>
<TR><TD>작 성 책 임 자 :</TD><TD>(직 책) 재무팀장</TD><TD>(성 명) 홍길동</TD></TR>
</TBODY></TABLE>
</SECTION-1></LIBRARY>
<SECTION-1 ACLASS="MANDATORY">
<TITLE ATOC="Y" AASSOCNOTE="D-0-1-0-0" ENG="Decision on Issuance of Convertible Bonds" ATOCID="1">전환사채권 발행결정</TITLE>
<TABLE-GROUP ACLASS="CB_PUB"><TABLE ACLASS="EXTRACTION" BORDER="1"><TBODY>
<TR><TD COLSPAN="2" ENG="1. Type of bonds">1. 사채의 종류</TD><TD ENG="Ordinal">회차</TD><TE ACODE="SEQ_NO">43</TE><TD ENG="Class of shares">종류</TD><TE COLSPAN="2" ACODE="PL_KND">무기명식 사모 전환사채</TE></TR>
<TR><TD COLSPAN="2" ENG="2. Total face value of bonds (KRW)">2. 사채의 권면총액 (원)</TD><TE COLSPAN="5" ACODE="DNM_SUM">6,000,000,000</TE></TR>
<TR><TD ROWSPAN="2" ENG="3. Interest rate">3. 사채의 이율</TD><TD ENG="Coupon rate (%)">표면이자율 (%)</TD><TE COLSPAN="5">1.5</TE></TR>
<TR><TD ENG="Yield to maturity (%)">만기이자율 (%)</TD><TE COLSPAN="5">4.0</TE></TR>
<TR><TD COLSPAN="2" ENG="4. Method of interest payment">4. 이자지급방법</TD><TE COLSPAN="5"><P>분기마다 지급한다.</P><P>[사채의 이율]</P></TE></TR>
<TR><TD COLSPAN="2" ENG="5. Method of bond issuance">5. 사채발행방법</TD><TU COLSPAN="5" AUNIT="BOND_MTH" AUNITVALUE="2" ENG="Private placement">사모</TU></TR>
</TBODY></TABLE></TABLE-GROUP>
<IMAGE><IMG>약정서.jpg</IMG></IMAGE>
</SECTION-1>"""


def amended_xml() -> str:
    """Build an amended convertible bond decision with a correction section."""
    correction = CORRECTION.replace("{long_before}", "변경 전 문장 " * 80)
    return dart(
        correction + "\n" + DECISION, code="11324", name="주요사항보고서(전환사채권 발행결정)"
    )


def audit_xml(code: str, name: str) -> str:
    """Build a small audit report attachment."""
    body = f"""<COVER><COVER-TITLE ATOC="Y" ENG="Audit Report" ATOCID="1">감 사 보 고 서</COVER-TITLE></COVER>
<LIBRARY><SECTION-1>{title("독립된 감사인의 감사보고서", "Independent Auditor\u2019s Audit Report", "D-0-0-1-0", "2")}
<P>감사의견: 적정</P></SECTION-1></LIBRARY>"""
    return dart(body, code=code, name=name)


KRX_STYLE = "<STYLE>.xforms {font-size:10pt}</STYLE>"


def krx(title_text: str, body: str) -> str:
    """Build a KRX xforms page; the declared charset is wrong on purpose."""
    return f"""<html>
 <head>
  <meta content="text/html; charset=euc-kr" http-equiv="Content-Type">
  {KRX_STYLE}
  <title>{title_text}</title>
 </head>
 <body>
  <div class="xforms"><span class="noprint" style="display:none">숨김</span>
{body}
  </div>
  <script>document.write('x')</script>
 </body>
</html>
"""


def inp(text: str) -> str:
    """Wrap a value in a KRX form input span."""
    return f'<span class="xforms_input">{text}</span>'


KRX_ADHOC = krx(
    "테스트전자/신규시설투자등/(2026.10.22)신규시설투자등",
    f"""<div class="xforms_title"><div><span style="font-weight:bold">신규 시설투자 등</span></div></div>
<table border="1"><tbody>
<tr><td colspan="2">1. 투자구분</td><td colspan="2">{inp("신규시설투자")}</td></tr>
<tr><td rowspan="2">2. 투자내역</td><td>투자금액(원)</td><td colspan="2">{inp("615,000,000,000")}</td></tr>
<tr><td>자기자본대비(%)</td><td colspan="2">{inp("68.54")}</td></tr>
<tr><td colspan="2">3. 기타 투자판단과 관련한 중요사항</td><td colspan="2">{inp("1. 첫째 줄<br>2. 둘째 줄")}</td></tr>
<tr><td>4. 이미지</td><td colspan="3"><img src="files/chart.png"></td></tr>
</tbody></table>""",
)


def prelim_rows(values: dict[str, list[str]]) -> str:
    """Build the quarter and cumulative rows of a preliminary-earnings table."""
    rows = []
    for label, cells in values.items():
        quarter, cumulative = cells[:7], cells[7:]
        rows.append(
            f'<tr><td rowspan="2">{label}</td><td>당해실적</td>'
            + "".join(f"<td>{inp(c)}</td>" for c in quarter)
            + "</tr>"
        )
        rows.append(
            "<tr><td>누계실적</td>"
            + "".join(f"<td>{inp(c) if c != "-" else c}</td>" for c in cumulative)
            + "</tr>"
        )
    return "\n".join(rows)


def prelim_page(
    unit: str, values: dict[str, list[str]], *, labels: tuple[str, str, str], prefix: str = ""
) -> str:
    """Build a KRX preliminary-earnings fair disclosure page."""
    current, prior, year_ago = labels
    body = f"""{prefix}<div class="xforms_title"><div><span>연결재무제표 기준 영업(잠정)실적(공정공시)</span></div></div>
<table border="1"><tbody>
<tr><td colspan="4">실적기간</td></tr>
<tr><td>당기실적</td><td>{inp("2026-07-01")}</td><td>~</td><td>{inp("2026-09-30")}</td></tr>
<tr><td>전기실적</td><td>{inp("2026-04-01")}</td><td>~</td><td>{inp("2026-06-30")}</td></tr>
<tr><td>전년동기실적</td><td>{inp("2025-07-01")}</td><td>~</td><td>{inp("2025-09-30")}</td></tr>
<tr><td>당기누계실적</td><td>{inp("2026-01-01")}</td><td>~</td><td>{inp("2026-09-30")}</td></tr>
<tr><td>전년동기누적실적</td><td>{inp("2025-01-01")}</td><td>~</td><td>{inp("2025-09-30")}</td></tr>
</tbody></table>
<table border="1"><tbody>
<tr><td colspan="9">※ 동 정보는 잠정치로서 향후 확정치와는 다를 수 있음.</td></tr>
<tr><td colspan="4">1. 연결실적내용</td><td colspan="5">{inp(unit)}</td></tr>
<tr><td colspan="2" rowspan="2">구분</td><td>당기실적</td><td>전기실적</td><td colspan="2">전기대비</td><td>전년동기실적</td><td colspan="2">전년동기대비</td></tr>
<tr><td>{inp(current)}</td><td>{inp(prior)}</td><td>증감율(%)</td><td>흑자적자전환여부</td><td>{inp(year_ago)}</td><td>증감율(%)</td><td>흑자적자전환여부</td></tr>
{prelim_rows(values)}
<tr><td colspan="2" rowspan="2">2. 정보제공내역</td><td colspan="2">정보제공자</td><td colspan="5">{inp("IR팀")}</td></tr>
<tr><td colspan="2">정보제공대상자</td><td colspan="5">{inp("투자자")}</td></tr>
</tbody></table>"""
    return krx(
        "테스트전자/연결재무제표기준영업(잠정)실적(공정공시)/(2026.10.08)연결재무제표기준영업(잠정)실적(공정공시)",
        body,
    )


def cells(row: str) -> list[str]:
    """Split a space-separated row of sample cell values."""
    return row.split()


TRILLION_VALUES = {
    "매출액": cells("195.00 171.50 13.70 - 86.06 126.59 - 500.37 - - - 239.77 108.69 -"),
    "영업이익": cells("107.40 89.49 20.01 - 12.17 782.50 - 254.13 - - - 23.53 980.03 -"),
    "법인세비용차감전계속사업이익": ["-"] * 14,
    "당기순이익": ["-"] * 14,
    "지배기업 소유주지분 순이익": ["-"] * 14,
}
MILLION_VALUES = {
    "매출액": cells("1,234 1,000 23.40 - 900 37.11 - 3,500 - - - 3,000 16.67 -"),
    "영업이익": cells("-120 50 - 적자전환 (30) - 적자지속 △100 - - - 40 - 적자전환"),
    "법인세비용차감전계속영업이익": cells("10 20 -50.00 - 5 100.00 - 30 - - - 10 200.00 -"),
    "당기순이익": cells("8 16 -50.00 - 4 100.00 - 24 - - - 8 200.00 -"),
    "지배기업 소유주지분 순이익": cells(
        "7 14 -50.00 흑자전환 3 133.33 흑자지속 21 - - - 7 200.00 기타"
    ),
}

KRX_CORRECTION = f"""<div id="LIB_LC000"> 정정신고(보고) </div>
<table border="1"><tbody><tr><td>정정일자</td><td>{inp("2026-10-09")}</td></tr></tbody></table>
<table border="1"><tbody>
<tr><td>1. 정정관련 공시서류</td><td colspan="2">{inp("연결재무제표기준영업(잠정)실적(공정공시)")}</td></tr>
<tr><td>2. 정정관련 공시서류제출일</td><td colspan="2">{inp("2026.10.08")}</td></tr>
<tr><td>3. 정정사유</td><td colspan="2">{inp("단순 오기 정정")}</td></tr>
<tr><td colspan="3">4. 정정사항</td></tr>
<tr><td>정정항목</td><td>정정전</td><td>정정후</td></tr>
<tr><td>{inp("1. 연결실적내용<br>- 매출액(당해실적)")}</td><td>{inp("194.00")}</td><td>{inp("195.00")}</td></tr>
</tbody></table>
"""


def make_zip(members: dict[str, str | bytes], *, method: int = zipfile.ZIP_DEFLATED) -> bytes:
    """Build a ZIP archive in memory."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", method) as archive:
        for name, content in members.items():
            archive.writestr(name, content.encode() if isinstance(content, str) else content)
    return buffer.getvalue()


FILING = "20260515003117"


@pytest.fixture
def zipper():
    """Return the in-memory ZIP builder."""
    return make_zip


@pytest.fixture
def periodic():
    """Return the periodic-report builder."""
    return periodic_xml


@pytest.fixture
def periodic_archive() -> bytes:
    """A quarterly report archive with a single main member."""
    return make_zip({f"{FILING}.xml": periodic_xml()})


@pytest.fixture
def annual_archive() -> bytes:
    """An annual report archive with audit report and consolidated audit report members."""
    number = "20260310002820"
    return make_zip(
        {
            f"{number}.xml": periodic_xml("11011", "사업보고서"),
            f"{number}_00760.xml": audit_xml("00760", "감사보고서"),
            f"{number}_00761.xml": audit_xml("00761", "연결감사보고서"),
        }
    )


@pytest.fixture
def amended_archive() -> bytes:
    """An amended convertible bond decision archive."""
    return make_zip({"20261022000506.xml": amended_xml()})


@pytest.fixture
def krx_adhoc() -> str:
    """A KRX ad hoc key/value page."""
    return KRX_ADHOC


@pytest.fixture
def prelim():
    """Return the preliminary-earnings page builder and its sample values."""
    return {
        "page": prelim_page,
        "trillion": TRILLION_VALUES,
        "million": MILLION_VALUES,
        "correction": KRX_CORRECTION,
        "krx": krx,
        "input": inp,
    }


@pytest.fixture
def dart_doc():
    """Return the DART document wrapper for parser-level tests."""
    return dart


@pytest.fixture
def krx_page():
    """Return the KRX page wrapper for parser-level tests."""
    return krx
