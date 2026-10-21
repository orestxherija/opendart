"""Optional transport test for the API skill's illustrative billing adapter.

Requires ``app.billing_api`` and its errors contract, plus ``Upstream`` and the
async/no-network fixtures from ``example.py``. This repository loads the latter
as ``http_testing_reference``; projects should import their own test support.
No client factory, authentication, or retry implementation is required.
"""

import httpx2
import pytest
from http_testing_reference import Upstream

from app.billing_api import BillingApi, InvoiceNotFound

pytestmark = pytest.mark.anyio


async def test_api_class_reports_a_missing_invoice() -> None:
    upstream = Upstream(404)
    async with httpx2.AsyncClient(
        base_url="https://billing.example/v2/",
        transport=httpx2.MockTransport(upstream),
    ) as client:
        with pytest.raises(InvoiceNotFound):
            await BillingApi(client).get_invoice("inv_0")
    assert upstream.requests[0].url.path == "/v2/invoices/inv_0"
