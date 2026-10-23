"""Event dates in the corporate-action calendar: debt offering tranches and trust terminations."""

from __future__ import annotations

import pytest

from packages.mcp.tests.events.data import debt_registration, identity, profile

SHORT_TRANCHES = (
    ("301-1", "100,000,000,000", "3.10", "2026.12.15"),
    ("301-2", "200,000,000,000", "3.40", "2027.01.15"),
)


async def calendar(client, kinds):
    result = await client.call_tool(
        "get_corporate_action_calendar",
        {"companies": ["005930"], "kinds": kinds},
        raise_on_error=False,
    )
    assert not result.is_error
    return result.structured_content["items"]


@pytest.mark.anyio
async def test_tranche_maturities_carry_their_own_terms(client, upstream):
    upstream.route("/company.json", upstream.ok(**profile()))
    upstream.records("/bdRs.json", **debt_registration(tranches=SHORT_TRANCHES))
    items = await calendar(client, ["debt_offering_registration"])
    maturities = [
        (item["date"], item["details"]["face_value"])
        for item in items
        if item["action"] == "maturity" and item["source_kind"] == "debt_offering_registration"
    ]
    assert maturities == [("2026-12-15", 100000000000), ("2027-01-15", 200000000000)]
    assert {item["filing_number"] for item in items} == {"20261020000111"}


@pytest.mark.anyio
async def test_a_trust_termination_adds_no_contract_period_dates(client, upstream):
    upstream.route("/company.json", upstream.ok(**profile()))
    termination = {
        "rcept_no": "20261020000555",
        **identity(),
        "ctr_prc_bfcc": "100,000,000,000",
        "ctr_pd_bfcc_bgd": "2026.06.01",
        "ctr_pd_bfcc_edd": "2026.12.01",
        "cc_pp": "계약기간 중도 해지",
        "cc_int": "삼성증권",
        "cc_prd": "2026.11.02",
        "bddd": "2026.10.20",
    }
    upstream.records("/tsstkAqTrctrCcDecsn.json", termination)
    items = await calendar(client, ["treasury_trust_termination"])
    assert [(item["date"], item["action"]) for item in items] == [
        ("2026-11-02", "termination_date")
    ]
