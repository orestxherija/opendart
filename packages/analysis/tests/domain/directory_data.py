"""Synthetic company-directory rows and archive builders shared by directory tests.

Rows reuse public identifiers from the real OpenDART directory (Samsung, SK, Hyundai,
Kakao, and others) plus invented ones in the 09xxxxxx range for edge cases. Nothing is read
from the network or from real archives.
"""

from __future__ import annotations

import io
import zipfile
from datetime import UTC, date, datetime
from xml.sax.saxutils import escape

from opendart_analysis.domain.directory import CorpRecord

type Row = tuple[str, str, str | None, str | None, date | None]

LOADED_AT = datetime(2026, 10, 22, 6, 0, tzinfo=UTC)

ROWS: tuple[Row, ...] = (
    # Listed companies.
    ("00126380", "삼성전자", "SAMSUNG ELECTRONICS CO,.LTD", "005930", date(2025, 12, 1)),
    ("00126371", "삼성전기", "SAMSUNG ELECTRO-MECHANICS CO.,LTD", "009150", date(2023, 1, 2)),
    ("00126362", "삼성SDI", "SAMSUNG SDI CO.,LTD", "006400", date(2026, 3, 6)),
    ("00877059", "삼성바이오로직스", "SAMSUNG BIOLOGICS CO.,LTD.", "207940", date(2024, 7, 1)),
    ("00126256", "삼성생명", "Samsung Life Insurance co., Ltd", "032830", date(2025, 3, 1)),
    ("00149655", "삼성물산", "SAMSUNG C&T CORPORATION", "028260", date(2026, 3, 23)),
    ("00126229", "삼성물산", "Samsung C&T Corporation", "000830", date(2017, 6, 30)),
    ("00164779", "SK하이닉스", "SK hynix Inc.", "000660", date(2024, 3, 28)),
    ("00181712", "SK", "SK Inc.", "034730", date(2024, 3, 28)),
    ("00144155", "SK", "SK Holdings Co., Ltd.", "003600", date(2017, 6, 30)),
    ("00266961", "NAVER", "NAVER Corporation", "035420", date(2024, 3, 11)),
    ("00258801", "카카오", "Kakao Corp.", "035720", date(2024, 3, 29)),
    ("01133217", "카카오뱅크", "KakaoBank Corp.", "323410", date(2025, 3, 20)),
    ("01137383", "카카오게임즈", "Kakao Games Corp.", "293490", date(2025, 3, 20)),
    ("00413046", "셀트리온", "Celltrion, Inc.", "068270", date(2026, 3, 25)),
    ("00155319", "POSCO홀딩스", "POSCO Holdings Inc.", "005490", date(2025, 3, 21)),
    ("01515323", "LG에너지솔루션", "LG ENERGY SOLUTION, LTD.", "373220", date(2025, 8, 12)),
    (
        "01933981",
        "비엔케이제3호스팩",
        "BNK  3 SPECIAL PURPOSE ACQUISITION COMPANY",
        "0068Y0",
        date(2025, 11, 21),
    ),
    ("00164742", "현대자동차", "HYUNDAI MOTOR CO", "005380", date(2026, 3, 31)),
    ("00164812", "현대코퍼레이션", "HYUNDAI CORPORATION", "011760", date(2023, 2, 16)),
    ("00164788", "현대모비스", "HYUNDAI MOBIS CO.,LTD", "012330", date(2025, 3, 18)),
    ("00145880", "현대제철", "HYUNDAI STEEL COMPANY", "004020", date(2026, 9, 4)),
    ("00137997", "현대차증권", "HYUNDAI MOTOR SECURITIES CO.,LTD.", "001500", date(2024, 3, 22)),
    # Two listed companies with one name, modified one year apart (invented).
    ("09000101", "대한정밀", "DAEHAN PRECISION CO., LTD.", "900101", date(2025, 3, 1)),
    ("09000102", "대한정밀", "Daehan Precision Co., Ltd.", "900102", date(2024, 3, 1)),
    # Unlisted companies.
    (
        "01345812",
        "삼성전자서비스씨에스",
        "SAMSUNG ELECTRONICS SERVICE CUSTOMER SATISFACTION., LTD.",
        None,
        date(2023, 1, 25),
    ),
    ("00252074", "삼성전자판매", "SAMSUNG ELECTRONICS SALES Co., Ltd.", None, date(2024, 1, 24)),
    ("01182596", "삼성산업개발", "samsung", None, date(2023, 5, 1)),
    ("00907679", "삼성바이오에피스", "SAMSUNGBIOEPIS CO,.LTD", None, date(2025, 3, 28)),
    ("00421045", "셀트리온", "Celltrion, Inc.", None, date(2024, 6, 28)),
    ("01019166", "쿠팡", "Coupang Corp.", None, date(2025, 1, 1)),
    ("01561252", "쿠팡페이", "Coupang Pay, Ltd.", None, date(2025, 1, 1)),
    ("01265516", "에스케이하이닉스시스템아이씨", "SK hynix system ic Inc.", None, date(2024, 1, 1)),
    ("09000001", "한국전장", "한국전장주식회사", None, date(2020, 1, 1)),
    ("09000002", "다코", None, None, None),
)


def record(row: Row) -> CorpRecord:
    """Build a record from a fixture row."""
    code, name, english, stock, modified = row
    return CorpRecord(code, name, english, stock, modified)


def list_element(**fields: str) -> str:
    """Render one <list> record from child element texts."""
    children = "".join(f"<{tag}>{text}</{tag}>" for tag, text in fields.items())
    return f"<list>{children}</list>"


def directory_xml(rows: tuple[Row, ...]) -> str:
    """Render rows as CORPCODE.xml, with blank stock codes as a single space."""
    entries = "".join(
        list_element(
            corp_code=code,
            corp_name=escape(name),
            corp_eng_name=escape(english or ""),
            stock_code=stock or " ",
            modify_date=modified.strftime("%Y%m%d") if modified else "",
        )
        for code, name, english, stock, modified in rows
    )
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<result>{entries}</result>'


def zip_members(members: dict[str, bytes | str]) -> bytes:
    """Build a deflated ZIP archive from member names and contents."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in members.items():
            archive.writestr(name, content)
    return buffer.getvalue()
