"""Compose the minimal API adapter with an explicitly selected retry policy.

Copy/adapt this operation only if retries are needed. Its project dependencies
are ``app.billing_api`` (and that adapter's errors) plus ``app.http_retries``
(and its settings contracts). The client remains owned by its caller.

Bind a retry policy to the sender at the composition point. An application that
makes many calls should construct the adapter once in that same owning scope.
Writes require documented upstream idempotency support before using this sender.
"""

from functools import partial

import httpx2

from app.billing_api import BillingApi, Invoice
from app.http_retries import RetrySettings, send_with_retries


async def get_invoice_with_retries(
    client: httpx2.AsyncClient, invoice_id: str, policy: RetrySettings
) -> Invoice:
    """Example read operation with explicit retry composition."""
    sender = partial(send_with_retries, policy=policy)
    billing = BillingApi(client, sender=sender)
    return await billing.get_invoice(invoice_id)
