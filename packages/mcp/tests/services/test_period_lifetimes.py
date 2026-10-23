"""Cache lifetimes of period data: recent periods are read again once filing lists expire."""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace

import pytest

from opendart_mcp.core.cache import TTLCache
from opendart_mcp.core.gateway import Gateway
from opendart_mcp.core.progress import no_progress
from opendart_mcp.core.ttl import DAY, FILINGS
from opendart_mcp.domain.periods import PeriodRef
from opendart_mcp.models.common import CompanyRef
from opendart_mcp.services.companies import Company
from opendart_mcp.services.compare import CompareRequest, compare_companies
from opendart_mcp.services.financials import FinancialsRequest
from opendart_mcp.services.investments import fetch_holdings
from opendart_mcp.services.ratios import company_indicators, peer_indicators, peer_ttl
from opendart_mcp.services.statement_views import statements_view
from packages.mcp.tests.tools.financials_data import (
    HYNIX,
    SAMSUNG,
    half_full_rows,
    half_summary_rows,
    indicator_rows,
    investment_rows,
)

TODAY = dt.date(2026, 10, 22)
# On 2026-10-22 Q3 2026 is inside its filing window (due 2026-11-14); H1 2026 has settled.
RECENT, SETTLED = PeriodRef(2026, "Q3"), PeriodRef(2026, "H1")


def company(corp_code, name, fye_month=12):
    ref = CompanyRef(name=name, corp_code=corp_code)
    return Company(ref=ref, fye_month=fye_month, profile=None)


SAMSUNG_CO = company(SAMSUNG, "SAMSUNG ELECTRONICS CO,.LTD")
HYNIX_CO = company(HYNIX, "SK hynix Inc.")


class Clock:
    """Monotonic seconds for the response cache, advanced by hand."""

    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def state(sdk, clock):
    cache = TTLCache(max_weight=10_000, clock=clock)
    gateway = Gateway(sdk, cache=cache, concurrency=4, retry_delay=0)
    known = {c.corp_code: c for c in (SAMSUNG_CO, HYNIX_CO)}

    async def resolve(text, *, progress=None):
        return known[text]

    return SimpleNamespace(
        require_gateway=lambda: gateway,
        today=lambda: TODAY,
        companies=SimpleNamespace(resolve=resolve),
    )


def indicators(upstream, corps=(SAMSUNG,)):
    def route(request):
        return upstream.rows(*indicator_rows(request.url.params["idx_cl_code"], corps=corps))

    return route


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("view", "path"), [("summary", "/fnlttSinglAcnt.json"), ("balance", "/fnlttSinglAcntAll.json")]
)
@pytest.mark.parametrize(("ref", "reads"), [(RECENT, 2), (SETTLED, 1)])
async def test_recent_statements_are_read_again_after_the_filing_lifetime(
    state, upstream, clock, view, path, ref, reads
):
    upstream.records("/fnlttSinglAcnt.json", *half_summary_rows())
    upstream.records("/fnlttSinglAcntAll.json", *half_full_rows())
    request = FinancialsRequest(view=view, period=ref.period, fiscal_year=ref.fiscal_year)
    for _ in range(2):
        table = await statements_view(state, SAMSUNG_CO, request=request, progress=no_progress)
        assert table.rows
        clock.now += FILINGS + 1
    assert upstream.count(path) == reads


@pytest.mark.anyio
@pytest.mark.parametrize(("ref", "reads"), [(RECENT, 2), (SETTLED, 1)])
async def test_recent_indicators_and_holdings_are_read_again(state, upstream, clock, ref, reads):
    upstream.route("/fnlttSinglIndx.json", indicators(upstream))
    upstream.route("/fnlttCmpnyIndx.json", indicators(upstream, corps=(SAMSUNG, HYNIX)))
    upstream.records("/otrCprInvstmntSttus.json", *investment_rows(3))
    for _ in range(2):
        assert await company_indicators(state, SAMSUNG_CO, ref) is not None
        assert await fetch_holdings(state, SAMSUNG_CO, ref) is not None
        assert await peer_indicators(state, [SAMSUNG_CO, HYNIX_CO], ref, categories=("M210000",))
        clock.now += FILINGS + 1
    assert upstream.count("/fnlttSinglIndx.json") == 4 * reads
    assert upstream.count("/otrCprInvstmntSttus.json") == reads
    assert upstream.count("/fnlttCmpnyIndx.json") == reads


def test_peer_answers_live_as_briefly_as_their_most_recent_member(state):
    # A September year end puts Q3 2026 at June 30, past its deadline; December's is recent.
    september = company("00266961", "NAVER Corporation", fye_month=9)
    assert peer_ttl(state, [september], RECENT) == DAY
    assert peer_ttl(state, [september, SAMSUNG_CO], RECENT) == FILINGS
    assert peer_ttl(state, [september, SAMSUNG_CO], SETTLED) == DAY


@pytest.mark.anyio
async def test_compare_sees_late_filers_once_the_filing_lifetime_ends(state, upstream, clock):
    filed = {SAMSUNG}

    def accounts(request):
        period = (request.url.params["bsns_year"], request.url.params["reprt_code"])
        corps = {("2026", "11014"): filed, ("2026", "11012"): {SAMSUNG, HYNIX}}.get(period)
        if not corps:
            return upstream.status("013")
        return upstream.rows(
            *(row for corp in sorted(corps) for row in half_summary_rows(corp=corp))
        )

    upstream.route("/fnlttMultiAcnt.json", accounts)
    request = CompareRequest(period="latest")
    early = await compare_companies(state, [SAMSUNG, HYNIX], request)
    assert (early.fiscal_year, early.period, early.company_count) == (2026, "H1", 2)
    filed.add(HYNIX)
    clock.now += FILINGS + 1
    later = await compare_companies(state, [SAMSUNG, HYNIX], request)
    assert (later.fiscal_year, later.period, later.company_count) == (2026, "Q3", 2)
    assert upstream.count("/fnlttMultiAcnt.json") == 3
