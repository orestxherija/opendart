"""Optional bulk lookup for an upstream that documents a batch endpoint.

Copy this reference to ``app/billing_bulk.py`` only when bulk lookup is needed.
It extends ``BillingApi`` from ``app.billing_api``; use that reference's normal
client ownership and optional retry policy. The illustrative API accepts at most
100 identifiers per request. No pagination assumptions are made.

Example::

    billing = BulkBillingApi(http)
    invoices = await billing.get_invoices(invoice_ids)
    missing = set(invoice_ids) - invoices.keys()
"""

from collections.abc import Iterable
from functools import partial

from pydantic import BaseModel, ConfigDict

from app.billing_api import BillingApi, Invoice

MAX_BATCH = 100
"""Most identifiers the billing API documents for one bulk lookup."""


class InvoiceBatch(BaseModel):
    """The body of a bulk lookup: the invoices found, in no particular order."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    invoices: list[Invoice]


class BulkBillingApi(BillingApi):
    """Billing adapter with the optional bulk-lookup operation."""

    async def get_invoices(self, invoice_ids: Iterable[str]) -> dict[str, Invoice]:
        """Fetch many invoices, ``MAX_BATCH`` per request.

        With an explicit retry policy, each request retries only its own chunk.

        Args:
            invoice_ids (Iterable[str]): The invoice identifiers. Duplicates are
                fetched once.

        Returns:
            dict[str, Invoice]: The invoices found, by identifier. Identifiers
                the billing API does not know are absent.

        Raises:
            BillingError: If a request fails, as one of its outcome classes.
        """
        unique = list(dict.fromkeys(invoice_ids))
        found: dict[str, Invoice] = {}
        for start in range(0, len(unique), MAX_BATCH):
            chunk = unique[start : start + MAX_BATCH]
            response = await self._send(
                partial(self._client.get, "invoices", params={"id": chunk})
            )
            for invoice in self._parse(response, InvoiceBatch).invoices:
                found[invoice.id] = invoice
        return found
