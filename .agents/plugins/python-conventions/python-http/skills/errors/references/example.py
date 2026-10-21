"""How HTTP failures leave an upstream's boundary.

Every failure calling an upstream becomes one of three outcomes callers can act
on: the upstream is unavailable (try later), it rejected the request (fix the
request, the data, or the permissions), or it answered in a form this code does
not understand (investigate the contract). ``translate`` maps httpx2 and
validation errors to those outcomes. Each upstream subclasses them, so callers
can catch by upstream, by outcome, or both.

Copy this module to ``app/http_errors.py``. It depends only on ``httpx2`` and
Pydantic, and can be used at a function boundary or in an adapter class. No
client factory, settings, authentication, or retry implementation is required.

The translated message omits query strings and bodies, but preserves path and
host for diagnosis. Paths can themselves be sensitive, and the original cause
may contain full URLs or validation inputs. A safe default log records static
operation labels, exception type, and status without formatting the exception
or traceback. Consult the observability skill for a reusable implementation;
keeping exception causes intact does not require logging them.

Example:
    One upstream's exceptions, in its API module::

        class BillingError(UpstreamError): ...
        class BillingUnavailable(BillingError, UpstreamUnavailable): ...
        class BillingRejected(BillingError, UpstreamRejected): ...
        class BillingContractError(BillingError, UpstreamContractError): ...

        BILLING_ERRORS = ErrorTypes(
            BillingUnavailable, BillingRejected, BillingContractError
        )

    At an HTTP boundary, in a function or an adapter method::

        except httpx2.HTTPError as error:
            raise translate(error, BILLING_ERRORS) from error

    In business code, by outcome or by upstream::

        except UpstreamUnavailable:
            schedule_retry_later()

    At the logging boundary, with labels defined by your code::

        except UpstreamError as error:
            logger.warning(
                "Upstream call failed",
                extra={"upstream": "billing", "operation": "get_invoice",
                       "error_type": type(error).__name__, "status": error.status},
                exc_info=False,
            )

    Do not pass ``error`` as a formatting argument or use ``logger.exception``
    in this safe-default path. Capture raw tracebacks only through a separately
    reviewed diagnostic destination with appropriate redaction and access.
"""

from dataclasses import dataclass

import httpx2
from pydantic import ValidationError


class UpstreamError(Exception):
    """A call to an upstream failed.

    Attributes:
        status (int | None): The HTTP status, when the upstream answered.
    """

    def __init__(self, message: str, *, status: int | None = None) -> None:
        """Store the message and the status.

        Args:
            message (str): Identifies the call: method, host, path, and status.
            status (int | None): The HTTP status, when the upstream answered.
        """
        super().__init__(message)
        self.status = status


class UpstreamUnavailable(UpstreamError):
    """No usable answer: a transport failure, a deadline, a 429, or a 5xx.

    Trying again later may work.
    """


class UpstreamRejected(UpstreamError):
    """The upstream refused the request with a 4xx other than 429.

    Repeating the same request will not help.
    """


class UpstreamContractError(UpstreamError):
    """The upstream answered, but not in a form this code understands."""


@dataclass(frozen=True)
class ErrorTypes:
    """One upstream's exception class for each outcome.

    Attributes:
        unavailable (type[UpstreamUnavailable]): Raised when there is no usable
            answer.
        rejected (type[UpstreamRejected]): Raised when the upstream says no.
        contract (type[UpstreamContractError]): Raised for an unexpected answer.
    """

    unavailable: type[UpstreamUnavailable]
    rejected: type[UpstreamRejected]
    contract: type[UpstreamContractError]


def _where(error: httpx2.HTTPError) -> str:
    """Method, host, and path of the failed call, without the query string."""
    try:
        request = error.request
    except RuntimeError:
        return "request"
    return f"{request.method} {request.url.host}{request.url.path}"


def translate(error: Exception, types: ErrorTypes) -> UpstreamError:
    """Map a failure at an upstream's boundary to that upstream's exception.

    Raise the result ``from`` the original error, so the httpx2 error stays in
    the traceback as the cause while callers see the upstream's own type. That
    chain is diagnostic data, not safe-to-log text; see the module's logging
    example or the optional observability skill.

    Args:
        error (Exception): The failure caught at the boundary.
        types (ErrorTypes): The upstream's exception classes.

    Returns:
        UpstreamError: The exception to raise, an instance of one of ``types``.

    Raises:
        TypeError: If ``error`` is not an upstream failure. A bug in the calling
            code must propagate unchanged, not be reported as an outage.
    """
    if isinstance(error, httpx2.HTTPStatusError):
        status = error.response.status_code
        message = f"{_where(error)} returned {status}"
        if status == 429 or status >= 500:
            return types.unavailable(message, status=status)
        return types.rejected(message, status=status)
    if isinstance(error, httpx2.DecodingError):
        return types.contract(f"{_where(error)} sent a body that could not be decoded")
    if isinstance(error, httpx2.RequestError):
        return types.unavailable(f"{_where(error)} failed: {type(error).__name__}")
    if isinstance(error, ValidationError):
        count = error.error_count()
        return types.contract(f"unexpected response body ({count} validation errors)")
    if isinstance(error, TimeoutError):
        return types.unavailable("deadline exceeded")
    raise TypeError(f"not an upstream failure: {type(error).__name__}")
