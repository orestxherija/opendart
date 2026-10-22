"""Typed access to one upstream: a billing API.

``BillingApi`` is the only code that knows the billing API speaks HTTP. Its
methods take and return models, and every failure leaves it as one of the
billing exceptions, translated as the errors skill describes. Business code
depends on this class, never on ``httpx2``.

Copy this reference to ``app/billing_api.py``. Its required project contract is
``app.http_errors`` from the errors skill; it accepts any existing async client.
Its optional ``sender`` accepts an operation wrapper such as a retry helper;
no retry module is imported. See ``with_retries.py`` for that composition and
``bulk.py`` only when bulk lookup is needed.

The illustrative upstream documents opaque, nonempty identifiers other than
``.`` and ``..``, and an ``Idempotency-Key`` contract for invoice creation. Adapt
both rules to the real upstream: sending a key alone never makes a write safe
to repeat, and deduplication lasts only for the upstream's documented window.

Example:
    The owner builds the client and hands it in, so the lifecycle stays in one
    place::

        async with build_client(settings.billing) as http:
            billing = BillingApi(http)
            invoice = await billing.get_invoice("inv_42")

    Opt in to retries only when the operation is safe to repeat::

        from functools import partial
        from app.http_retries import send_with_retries

        sender = partial(send_with_retries, policy=settings.billing_retries)
        billing = BillingApi(http, sender=sender)

    Business code catches the upstream's exceptions only, by case, by outcome,
    or by upstream::

        try:
            invoice = await billing.get_invoice(invoice_id)
        except InvoiceNotFound:
            ...
        except UpstreamUnavailable:
            ...
"""

import uuid
from collections.abc import Awaitable, Callable
from datetime import date
from decimal import Decimal
from typing import TypeVar
from urllib.parse import quote

import httpx2
from pydantic import BaseModel, ConfigDict, ValidationError

from app.http_errors import (
    ErrorTypes,
    UpstreamContractError,
    UpstreamError,
    UpstreamRejected,
    UpstreamUnavailable,
    translate,
)

Model = TypeVar("Model", bound=BaseModel)
Send = Callable[[], Awaitable[httpx2.Response]]
Sender = Callable[[Send], Awaitable[httpx2.Response]]


class BillingError(UpstreamError):
    """Any failure talking to the billing API."""


class BillingUnavailable(BillingError, UpstreamUnavailable):
    """The billing API gave no usable answer; trying later may work."""


class BillingRejected(BillingError, UpstreamRejected):
    """The billing API refused the request."""


class BillingContractError(BillingError, UpstreamContractError):
    """The billing API answered in a form this code does not understand."""


class InvoiceNotFound(BillingRejected):
    """The requested invoice does not exist."""


BILLING_ERRORS = ErrorTypes(BillingUnavailable, BillingRejected, BillingContractError)


class Invoice(BaseModel):
    """An invoice as the billing API returns it.

    Unknown fields are ignored, so the upstream can add fields without breaking
    this code; the fields used here are validated.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    id: str
    customer_id: str
    amount: Decimal
    currency: str
    due: date


class InvoiceDraft(BaseModel):
    """A new invoice to create. Unknown fields are rejected before sending."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    customer_id: str
    amount: Decimal
    currency: str
    due: date


class BillingApi:
    """The billing API, as the rest of the code sees it."""

    def __init__(
        self, client: httpx2.AsyncClient, *, sender: Sender | None = None
    ) -> None:
        """Wrap a client the caller owns.

        Args:
            client (httpx2.AsyncClient): An existing client configured for the
                billing base URL. The caller closes it.
            sender (Sender | None): An optional operation wrapper, such as a
                retry helper bound to its policy. Without one, send once.
        """
        self._client = client
        self._sender = sender

    async def get_invoice(self, invoice_id: str) -> Invoice:
        """Fetch one invoice.

        Args:
            invoice_id (str): The invoice identifier.

        Returns:
            Invoice: The invoice.

        Raises:
            ValueError: If the identifier violates the documented contract.
            InvoiceNotFound: If the invoice does not exist.
            BillingError: For any other failure, as one of its outcome classes.
        """
        # URL quoting leaves dot segments unchanged, so reject them first.
        if not invoice_id or invoice_id in {".", ".."}:
            raise ValueError("invoice_id must be nonempty and not a dot segment")
        # The documented opaque identifier stays one encoded path segment.
        path = f"invoices/{quote(invoice_id, safe='')}"
        response = await self._send(lambda: self._client.get(path))
        # Map the statuses callers act on before the general translation.
        if response.status_code == 404:
            raise InvoiceNotFound(f"invoice {invoice_id!r} not found", status=404)
        return self._parse(response, Invoice)

    async def create_invoice(self, draft: InvoiceDraft) -> Invoice:
        """Create an invoice under this upstream's documented idempotency contract.

        Args:
            draft (InvoiceDraft): The invoice to create.

        Returns:
            Invoice: The created invoice.

        Raises:
            BillingError: If the invoice could not be created.
        """
        # This example assumes the upstream documents this header and its
        # deduplication window. Keep one key per logical call across attempts.
        # For caller-managed resume after an uncertain failure, persist the key
        # with the operation and accept it from that caller instead.
        headers = {"Idempotency-Key": str(uuid.uuid4())}
        body = draft.model_dump(mode="json")
        response = await self._send(
            lambda: self._client.post("invoices", json=body, headers=headers)
        )
        return self._parse(response, Invoice)

    async def _send(self, send: Send) -> httpx2.Response:
        """Send once or with an explicit retry policy; translate transport failures.

        Raises:
            BillingUnavailable: If the configured attempts all fail.
        """
        try:
            if self._sender is None:
                return await send()
            return await self._sender(send)
        except (httpx2.HTTPError, TimeoutError) as error:
            raise translate(error, BILLING_ERRORS) from error

    @staticmethod
    def _parse(response: httpx2.Response, model: type[Model]) -> Model:
        """Check the status and validate the body against a model.

        Raises:
            BillingUnavailable: On a 429 or 5xx.
            BillingRejected: On any other error status.
            BillingContractError: On a body that does not match the model.
        """
        try:
            response.raise_for_status()
            return model.model_validate_json(response.content)
        except (httpx2.HTTPStatusError, ValidationError) as error:
            raise translate(error, BILLING_ERRORS) from error
