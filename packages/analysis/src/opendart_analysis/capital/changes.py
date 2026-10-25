"""Share issuances and reductions, and the use of money raised, from periodic reports.

``irds_sttus`` lists share issuances and reductions with dates, Korean types such as
유상증자(제3자배정) (paid-in capital increase, third-party allotment), share counts, and
prices. ``pssrp_cptal_use_dtls`` and ``prvsrp_cptal_use_dtls`` compare the planned and actual
use of money raised by public offerings and private placements. Tables with nothing to report
arrive as rows of dashes, which are dropped. Amounts are won as filed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Literal, Protocol

from opendart_analysis.capital.shares import is_blank, share_class
from opendart_analysis.domain.normalize import clean_text, parse_amount, parse_date

if TYPE_CHECKING:
    import datetime as dt
    from collections.abc import Sequence

    from opendart_analysis.reports import ReportQuery
    from opendart_analysis.upstream import Volatility

type Offering = Literal["public", "private"]
"""How money was raised: a public offering or a private placement."""

# Keywords of filed issuance and reduction types, checked in order, and their English names.
_CHANGE_CATEGORIES: Final = (
    ("유상증자", "paid-in capital increase"),
    ("무상증자", "bonus issue"),
    ("주식배당", "stock dividend"),
    ("주식매수선택권", "stock option exercise"),
    ("신주인수권", "warrant exercise"),
    ("전환", "conversion"),
    ("감자", "capital reduction"),
    ("소각", "share retirement"),
    ("합병", "merger"),
    ("액면분할", "stock split"),
    ("주식분할", "stock split"),
    ("병합", "share consolidation"),
    ("교환", "share exchange"),
    ("상환", "redemption"),
)
_ALLOTMENTS: Final = (
    ("제3자배정", "third-party allotment"),
    ("주주배정", "shareholder allotment"),
    ("주주우선공모", "shareholder-priority public offering"),
    ("일반공모", "public offering"),
)


class CapitalChangeRecord(Protocol):
    """The fields of one share issuance or reduction row that analysis reads."""

    @property
    def isu_dcrs_de(self) -> str | None:
        """Date of the issuance or reduction."""
        ...

    @property
    def isu_dcrs_stle(self) -> str | None:
        """Type as filed, such as 유상증자(제3자배정)."""
        ...

    @property
    def isu_dcrs_stock_knd(self) -> str | None:
        """Share class as filed."""
        ...

    @property
    def isu_dcrs_qy(self) -> str | None:
        """Shares issued or cancelled."""
        ...

    @property
    def isu_dcrs_mstvdv_fval_amount(self) -> str | None:
        """Par value per share."""
        ...

    @property
    def isu_dcrs_mstvdv_amount(self) -> str | None:
        """Issue or reduction price per share."""
        ...


class ProceedsRecord(Protocol):
    """The fields that public-offering and private-placement proceeds rows share."""

    @property
    def se_nm(self) -> str | None:
        """Security or method as filed."""
        ...

    @property
    def tm(self) -> str | None:
        """Series number."""
        ...

    @property
    def pay_de(self) -> str | None:
        """Payment date."""
        ...

    @property
    def real_cptal_use_dtls_cn(self) -> str | None:
        """Actual use."""
        ...

    @property
    def real_cptal_use_dtls_amount(self) -> str | None:
        """Amount actually used."""
        ...

    @property
    def dffrnc_occrrnc_resn(self) -> str | None:
        """Reason for a difference between plan and use."""
        ...

    @property
    def pay_amount(self) -> str | None:
        """Amount paid in; filed before 2018."""
        ...

    @property
    def real_cptal_use_sttus(self) -> str | None:
        """Actual use status; filed before 2018."""
        ...


class PublicProceedsRecord(ProceedsRecord, Protocol):
    """The fields of one public-offering use-of-proceeds row that analysis reads."""

    @property
    def rs_cptal_use_plan_useprps(self) -> str | None:
        """Planned use as stated in the registration statement."""
        ...

    @property
    def rs_cptal_use_plan_prcure_amount(self) -> str | None:
        """Planned amount as stated in the registration statement."""
        ...

    @property
    def on_dclrt_cptal_use_plan(self) -> str | None:
        """Use plan at filing; filed before 2018."""
        ...


class PrivateProceedsRecord(ProceedsRecord, Protocol):
    """The fields of one private-placement use-of-proceeds row that analysis reads."""

    @property
    def mtrpt_cptal_use_plan_useprps(self) -> str | None:
        """Planned use as stated in the major-issue report."""
        ...

    @property
    def mtrpt_cptal_use_plan_prcure_amount(self) -> str | None:
        """Planned amount as stated in the major-issue report."""
        ...

    @property
    def cptal_use_plan(self) -> str | None:
        """Use plan; filed before 2018."""
        ...


class FetchCapitalChanges(Protocol):
    """Fetch one company's share issuances and reductions for one period."""

    async def __call__(
        self, query: ReportQuery, /, *, volatility: Volatility
    ) -> Sequence[CapitalChangeRecord] | None:
        """Return the issuance and reduction rows of a company's periodic report.

        Args:
            query (ReportQuery): Company and period.
            volatility (Volatility): How quickly the answer can change, for the source's cache.

        Returns:
            Sequence[CapitalChangeRecord] | None: Rows, or None when the source has none.
        """
        ...


class FetchPublicProceeds(Protocol):
    """Fetch one company's use of public-offering proceeds for one period."""

    async def __call__(
        self, query: ReportQuery, /, *, volatility: Volatility
    ) -> Sequence[PublicProceedsRecord] | None:
        """Return the public-offering use-of-proceeds rows of a company's periodic report.

        Args:
            query (ReportQuery): Company and period.
            volatility (Volatility): How quickly the answer can change, for the source's cache.

        Returns:
            Sequence[PublicProceedsRecord] | None: Rows, or None when the source has none.
        """
        ...


class FetchPrivateProceeds(Protocol):
    """Fetch one company's use of private-placement proceeds for one period."""

    async def __call__(
        self, query: ReportQuery, /, *, volatility: Volatility
    ) -> Sequence[PrivateProceedsRecord] | None:
        """Return the private-placement use-of-proceeds rows of a company's periodic report.

        Args:
            query (ReportQuery): Company and period.
            volatility (Volatility): How quickly the answer can change, for the source's cache.

        Returns:
            Sequence[PrivateProceedsRecord] | None: Rows, or None when the source has none.
        """
        ...


@dataclass(frozen=True, slots=True)
class CapitalChange:
    """One share issuance or reduction; amounts in won.

    Attributes:
        date (dt.date | None): Date of the change.
        kind (str | None): Type as filed, usually Korean.
        category (str | None): English name of the type, when recognized.
        share_class (str | None): ``common``, ``preferred``, or the class as filed.
        shares (int | None): Shares issued or cancelled.
        par_value (int | None): Par value per share.
        price (int | None): Issue or reduction price per share.
    """

    date: dt.date | None
    kind: str | None
    category: str | None
    share_class: str | None
    shares: int | None
    par_value: int | None
    price: int | None


@dataclass(frozen=True, slots=True)
class ProceedsUse:
    """Planned versus actual use of money raised; amounts in won.

    ``amount_paid``, ``plan``, and ``actual_status`` come from reports filed before 2018.

    Attributes:
        offering (Offering): ``public`` offering or ``private`` placement.
        kind (str | None): Security or method as filed.
        series (str | None): Series number.
        paid_on (dt.date | None): Payment date.
        planned_use (str | None): Planned use.
        planned_amount (int | None): Planned amount.
        actual_use (str | None): Actual use.
        actual_amount (int | None): Amount actually used.
        difference_reason (str | None): Reason for a difference between plan and use.
        amount_paid (int | None): Amount paid in.
        plan (str | None): Use plan.
        actual_status (str | None): Actual use status.
    """

    offering: Offering
    kind: str | None
    series: str | None
    paid_on: dt.date | None
    planned_use: str | None
    planned_amount: int | None
    actual_use: str | None
    actual_amount: int | None
    difference_reason: str | None
    amount_paid: int | None
    plan: str | None
    actual_status: str | None


def change_category(kind: str | None) -> str | None:
    """Name a filed issuance or reduction type in English.

    Args:
        kind (str | None): Type as filed, such as 유상증자(제3자배정).

    Returns:
        str | None: English name such as "paid-in capital increase (third-party
            allotment)", or None when the type is not recognized.
    """
    folded = "".join((kind or "").split())
    base = next((name for word, name in _CHANGE_CATEGORIES if word in folded), None)
    allotment = next((name for word, name in _ALLOTMENTS if word in folded), None)
    return f"{base} ({allotment})" if base is not None and allotment is not None else base


def capital_changes(records: Sequence[CapitalChangeRecord]) -> list[CapitalChange]:
    """List share issuances and reductions with a date or a share count, newest first.

    Undated changes come last, in filed order.

    Args:
        records (Sequence[CapitalChangeRecord]): Upstream rows.

    Returns:
        list[CapitalChange]: Changes.
    """
    changes = [
        CapitalChange(
            date=parse_date(record.isu_dcrs_de),
            kind=clean_text(record.isu_dcrs_stle),
            category=change_category(record.isu_dcrs_stle),
            share_class=share_class(record.isu_dcrs_stock_knd),
            shares=parse_amount(record.isu_dcrs_qy),
            par_value=parse_amount(record.isu_dcrs_mstvdv_fval_amount),
            price=parse_amount(record.isu_dcrs_mstvdv_amount),
        )
        for record in records
    ]
    kept = [change for change in changes if change.date is not None or change.shares is not None]
    return sorted(kept, key=lambda c: c.date.toordinal() if c.date else 0, reverse=True)


def _public_use(record: PublicProceedsRecord) -> ProceedsUse:
    """Parse one public-offering use-of-proceeds row.

    Args:
        record (PublicProceedsRecord): Upstream row.

    Returns:
        ProceedsUse: Planned and actual use.
    """
    return ProceedsUse(
        offering="public",
        kind=clean_text(record.se_nm),
        series=clean_text(record.tm),
        paid_on=parse_date(record.pay_de),
        planned_use=clean_text(record.rs_cptal_use_plan_useprps),
        planned_amount=parse_amount(record.rs_cptal_use_plan_prcure_amount),
        actual_use=clean_text(record.real_cptal_use_dtls_cn),
        actual_amount=parse_amount(record.real_cptal_use_dtls_amount),
        difference_reason=clean_text(record.dffrnc_occrrnc_resn),
        amount_paid=parse_amount(record.pay_amount),
        plan=clean_text(record.on_dclrt_cptal_use_plan),
        actual_status=clean_text(record.real_cptal_use_sttus),
    )


def _private_use(record: PrivateProceedsRecord) -> ProceedsUse:
    """Parse one private-placement use-of-proceeds row.

    Args:
        record (PrivateProceedsRecord): Upstream row.

    Returns:
        ProceedsUse: Planned and actual use.
    """
    return ProceedsUse(
        offering="private",
        kind=clean_text(record.se_nm),
        series=clean_text(record.tm),
        paid_on=parse_date(record.pay_de),
        planned_use=clean_text(record.mtrpt_cptal_use_plan_useprps),
        planned_amount=parse_amount(record.mtrpt_cptal_use_plan_prcure_amount),
        actual_use=clean_text(record.real_cptal_use_dtls_cn),
        actual_amount=parse_amount(record.real_cptal_use_dtls_amount),
        difference_reason=clean_text(record.dffrnc_occrrnc_resn),
        amount_paid=parse_amount(record.pay_amount),
        plan=clean_text(record.cptal_use_plan),
        actual_status=clean_text(record.real_cptal_use_sttus),
    )


def proceeds_uses(
    public: Sequence[PublicProceedsRecord], private: Sequence[PrivateProceedsRecord]
) -> list[ProceedsUse]:
    """List planned versus actual use of proceeds, public offerings first, in filed order.

    Args:
        public (Sequence[PublicProceedsRecord]): Public-offering rows.
        private (Sequence[PrivateProceedsRecord]): Private-placement rows.

    Returns:
        list[ProceedsUse]: Rows with a date, an amount, or a stated use.
    """
    rows = [*map(_public_use, public), *map(_private_use, private)]
    return [row for row in rows if not is_blank(row, "offering", "kind", "series")]
