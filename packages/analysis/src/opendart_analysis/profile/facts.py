"""Normalize OpenDART's company overview into reference facts.

The overview (``disclosures.company``) holds a company's names, codes, CEO, registration
numbers, contact details, industry code, establishment date, and fiscal year-end month, all
as strings. Placeholders such as blanks and ``-`` become None.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from opendart_analysis.domain.normalize import clean_text, parse_date

if TYPE_CHECKING:
    from datetime import date


class CompanyOverview(Protocol):
    """The fields of the company overview that analysis reads."""

    @property
    def stock_name(self) -> str | None:
        """Listed item name, or the abbreviated name of an unlisted company."""
        ...

    @property
    def ceo_nm(self) -> str | None:
        """Representative (CEO) name."""
        ...

    @property
    def induty_code(self) -> str | None:
        """Korean Standard Industrial Classification code."""
        ...

    @property
    def est_dt(self) -> str | None:
        """Establishment date (YYYYMMDD)."""
        ...

    @property
    def adres(self) -> str | None:
        """Address."""
        ...

    @property
    def hm_url(self) -> str | None:
        """Website URL."""
        ...

    @property
    def ir_url(self) -> str | None:
        """Investor-relations website URL."""
        ...

    @property
    def phn_no(self) -> str | None:
        """Telephone number."""
        ...

    @property
    def fax_no(self) -> str | None:
        """Fax number."""
        ...

    @property
    def jurir_no(self) -> str | None:
        """Corporate registration number."""
        ...

    @property
    def bizr_no(self) -> str | None:
        """Business registration number."""
        ...


@dataclass(frozen=True, slots=True)
class CompanyFacts:
    """Reference facts from the company overview; None where it has none.

    Attributes:
        stock_name (str | None): Listed item name, or the abbreviated name.
        ceo (str | None): Representative name.
        industry_code (str | None): Industry classification code.
        fiscal_year_end_month (int): Fiscal year-end month, 1 to 12.
        established (date | None): Establishment date.
        address (str | None): Address.
        website (str | None): Website URL as filed.
        ir_url (str | None): Investor-relations URL as filed.
        phone (str | None): Telephone number.
        fax (str | None): Fax number.
        corporate_registration_number (str | None): Corporate registration number.
        business_registration_number (str | None): Business registration number.
    """

    stock_name: str | None
    ceo: str | None
    industry_code: str | None
    fiscal_year_end_month: int
    established: date | None
    address: str | None
    website: str | None
    ir_url: str | None
    phone: str | None
    fax: str | None
    corporate_registration_number: str | None
    business_registration_number: str | None


def company_facts(overview: CompanyOverview | None, fye_month: int) -> CompanyFacts:
    """Normalize the company overview.

    Args:
        overview (CompanyOverview | None): Company overview, or None when there is none.
        fye_month (int): Fiscal year-end month the company was resolved with.

    Returns:
        CompanyFacts: Reference facts; only the fiscal year-end month without an overview.
    """
    if overview is None:
        return CompanyFacts(
            stock_name=None,
            ceo=None,
            industry_code=None,
            fiscal_year_end_month=fye_month,
            established=None,
            address=None,
            website=None,
            ir_url=None,
            phone=None,
            fax=None,
            corporate_registration_number=None,
            business_registration_number=None,
        )
    return CompanyFacts(
        stock_name=clean_text(overview.stock_name),
        ceo=clean_text(overview.ceo_nm),
        industry_code=clean_text(overview.induty_code),
        fiscal_year_end_month=fye_month,
        established=parse_date(overview.est_dt),
        address=clean_text(overview.adres),
        website=clean_text(overview.hm_url),
        ir_url=clean_text(overview.ir_url),
        phone=clean_text(overview.phn_no),
        fax=clean_text(overview.fax_no),
        corporate_registration_number=clean_text(overview.jurir_no),
        business_registration_number=clean_text(overview.bizr_no),
    )
