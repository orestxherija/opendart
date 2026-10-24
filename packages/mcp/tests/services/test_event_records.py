"""SDK response models group into the same event records as the decoded bodies they parse.

``opendart_analysis.events.records_from`` reads SDK models through ``model_dump`` and decoded
JSON bodies as mappings; the analysis suite, which runs without the SDK, uses bodies.
"""

from __future__ import annotations

from opendart.models.major_issues import CvbdIsDecsnResponse
from opendart.models.securities_registration import BdRsResponse, EstkRsResponse
from opendart_analysis.events import records_from
from tests.support.events import convertible_bond, debt_registration, equity_registration


def test_list_models_match_their_bodies():
    rows = [convertible_bond("20261021000315"), convertible_bond(new_field="7")]
    body = {"status": "000", "message": "ok", "list": rows}
    model = CvbdIsDecsnResponse.model_validate(body)
    assert records_from("convertible_bond", model) == records_from("convertible_bond", body)


def test_group_models_match_their_bodies():
    for kind, response, body in (
        ("equity_offering_registration", EstkRsResponse, equity_registration()),
        ("debt_offering_registration", BdRsResponse, debt_registration()),
    ):
        full = {"status": "000", "message": "ok", **body}
        from_model = records_from(kind, response.model_validate(full))
        assert from_model == records_from(kind, full)
        assert from_model
