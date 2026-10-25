"""Verify that the API key never reaches logs, exception text, or SDK object reprs."""

from __future__ import annotations

import logging
import traceback

import httpx2
import pytest

from opendart import ContractError, OpenDART, UnavailableError
from opendart.redaction import (
    HTTP_LOGGERS,
    REDACTED,
    RedactSecrets,
    RedactingFormatter,
    protect_loggers,
    redact,
)

pytestmark = pytest.mark.anyio


def rendered(error):
    """Render an exception the way logging and tracebacks do, with its whole chain.

    Args:
        error (BaseException): Exception to render.

    Returns:
        str: Traceback text including chained causes and contexts.
    """
    return "".join(traceback.format_exception(error))


def raise_chained(outer, inner):
    """Raise an exception whose explicit cause is another exception.

    Args:
        outer (BaseException): Exception to raise.
        inner (BaseException): Exception raised first and chained as the cause.

    Raises:
        BaseException: Always, the outer exception chained to the inner one.
    """
    try:
        raise inner
    except type(inner) as error:
        raise outer from error


def ok(request):
    return httpx2.Response(200, json={"status": "000", "message": "OK"})


def test_redact_patterns_and_known_secrets():
    key = "K" * 40
    text = f"GET https://x/a.json?corp_code=1&crtfc_key={key} and ?CRTFC_KEY={key}&b=2"
    assert key not in redact(text)
    assert redact(text).count(REDACTED) == 2
    assert redact(f"echo {key}!", key) == f"echo {REDACTED}!"
    assert redact("nothing here", "") == "nothing here"


async def test_request_logs_never_contain_the_key(settings, caplog):
    key = settings.api_key.get_secret_value()
    caplog.set_level(logging.DEBUG)
    caplog.set_level(logging.INFO, logger="httpx2")
    async with OpenDART(settings, transport=httpx2.MockTransport(ok)) as client:
        await client.disclosures.search()
    assert "HTTP Request: GET" in caplog.text
    assert "list.json" in caplog.text
    assert key not in caplog.text
    assert f"crtfc_key={REDACTED}" in caplog.text


@pytest.mark.parametrize("name", HTTP_LOGGERS)
def test_client_protects_every_http_logger(settings, caplog, name):
    key = settings.api_key.get_secret_value()
    OpenDART(settings, transport=httpx2.MockTransport(ok))
    caplog.set_level(logging.DEBUG, logger=name)
    url = httpx2.URL(f"https://x/list.json?crtfc_key={key}")
    logging.getLogger(name).debug("send_request_headers.started request=%r", url)
    assert caplog.records
    assert key not in caplog.text


def test_protection_is_idempotent_and_keeps_user_configuration(settings, monkeypatch):
    logger = logging.getLogger("httpx2")
    mine = logging.Filter("httpx2")
    monkeypatch.setattr(logger, "filters", [mine])
    monkeypatch.setattr(logger, "level", logging.ERROR)
    OpenDART(settings, transport=httpx2.MockTransport(ok))
    OpenDART(settings, transport=httpx2.MockTransport(ok))
    protect_loggers()
    assert logger.filters[0] is mine
    assert sum(isinstance(item, RedactSecrets) for item in logger.filters) == 1
    assert logger.level == logging.ERROR


def test_formatter_redacts_tracebacks():
    key = "K" * 40
    try:
        message = f"failed for https://x/list.json?crtfc_key={key}"
        raise ValueError(message)  # noqa: TRY301 - building a real traceback
    except ValueError as error:
        record = logging.LogRecord(
            "x", logging.ERROR, __file__, 1, "boom", None, (type(error), error, error.__traceback__)
        )
    assert key not in RedactingFormatter("%(message)s").format(record)


@pytest.mark.parametrize(
    "failure,kind",
    [
        (httpx2.ConnectError, UnavailableError),
        (httpx2.ReadTimeout, UnavailableError),
        (httpx2.RemoteProtocolError, UnavailableError),
        (httpx2.DecodingError, ContractError),
    ],
)
async def test_http_failure_causes_are_redacted(settings, failure, kind):
    key = settings.api_key.get_secret_value()

    def handler(request):
        outer = failure(f"Request failed for url '{request.url}'", request=request)
        raise_chained(outer, OSError(f"low-level failure for {request.url}"))

    async with OpenDART(settings, transport=httpx2.MockTransport(handler)) as client:
        with pytest.raises(kind) as caught:
            await client.disclosures.search()
    cause = caught.value.__cause__
    assert isinstance(cause, failure)
    assert key not in rendered(caught.value)
    assert key not in str(cause.request.url)
    assert key not in repr(cause.request)
    assert REDACTED in str(cause)
    assert cause.request.url.path.endswith("/list.json")


@pytest.mark.parametrize("archive", [False, True])
async def test_body_echo_never_reaches_validation_causes(settings, archive):
    key = settings.api_key.get_secret_value()

    def handler(request):
        if archive:
            body = f"<result><status>{key}</status><message>x</message></result>"
        else:
            body = f"<html>Rejected {request.url}</html>"
        return httpx2.Response(200, content=body.encode())

    async with OpenDART(settings, transport=httpx2.MockTransport(handler)) as client:
        with pytest.raises(ContractError) as caught:
            if archive:
                await client.disclosures.corporation_codes()
            else:
                await client.disclosures.search()
    text = rendered(caught.value)
    assert key[-12:] not in text
    assert key[:12] not in text


async def test_unrecognized_cause_text_is_dropped(settings):
    key = settings.api_key.get_secret_value()

    class OpaqueError(Exception):
        def __str__(self):
            return f"opaque {key}"

    def handler(request):
        raise_chained(httpx2.ConnectError("connect failed", request=request), OpaqueError())

    async with OpenDART(settings, transport=httpx2.MockTransport(handler)) as client:
        with pytest.raises(UnavailableError) as caught:
            await client.disclosures.search()
    assert caught.value.__cause__ is None
    assert caught.value.__suppress_context__
    assert key not in rendered(caught.value)


async def test_other_propagating_failures_are_redacted(settings):
    key = settings.api_key.get_secret_value()

    def handler(request):
        message = f"{request.url} not mocked"
        raise AssertionError(message)

    async with OpenDART(settings, transport=httpx2.MockTransport(handler)) as client:
        with pytest.raises(AssertionError) as caught:
            await client.disclosures.search()
    assert "not mocked" in str(caught.value)
    assert key not in rendered(caught.value)


async def test_reprs_never_contain_the_key(settings):
    key = settings.api_key.get_secret_value()
    async with OpenDART(settings, transport=httpx2.MockTransport(ok)) as client:
        transport = client._transport
        texts = [
            repr(client),
            repr(transport),
            repr(vars(transport)),
            repr(settings),
            str(settings),
            settings.model_dump_json(),
            repr(transport.http.auth),
            repr(vars(transport.http.auth)),
        ]
    assert all(key not in text for text in texts)


async def test_exception_groups_notes_and_requestless_errors_are_redacted(settings):
    key = settings.api_key.get_secret_value()
    elsewhere = httpx2.Request("GET", "https://elsewhere.example/")

    def handler(request):
        group = ExceptionGroup(
            "transport failures",
            [
                httpx2.HTTPError(f"no request attached for {request.url}"),
                httpx2.ConnectError("unrelated request", request=elsewhere),
            ],
        )
        group.add_note(f"while fetching {request.url}")
        raise group

    async with OpenDART(settings, transport=httpx2.MockTransport(handler)) as client:
        with pytest.raises(ExceptionGroup) as caught:
            await client.disclosures.search()
    assert key not in rendered(caught.value)
    assert f"crtfc_key={REDACTED}" in caught.value.__notes__[0]
    assert str(elsewhere.url) == "https://elsewhere.example/"
