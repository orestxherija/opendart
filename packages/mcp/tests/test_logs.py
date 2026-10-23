"""Expected component errors are logged without tracebacks."""

from __future__ import annotations

import logging
import sys

import pytest
from pydantic import SecretStr

from opendart import OpenDartSettings
from opendart_mcp.app.logs import (
    FASTMCP_SERVER_LOGGER,
    QuietExpectedErrors,
    configure_logging,
    quiet_expected_errors,
)
from opendart_mcp.core.metrics import Metrics
from opendart_mcp.core.redaction import RedactingFormatter, protect_secrets, redact
from opendart_mcp.core.runtime import open_state


def record(level, exc_info):
    return logging.LogRecord("x", level, __file__, 1, "message", None, exc_info)


def boom():
    raise ValueError("boom")


def failure():
    try:
        boom()
    except ValueError as error:
        return (type(error), error, error.__traceback__)
    return None


@pytest.mark.parametrize(("level", "keeps"), [(logging.INFO, False), (logging.ERROR, True)])
def test_tracebacks_are_kept_only_for_errors(level, keeps):
    item = record(level, failure())
    assert QuietExpectedErrors().filter(item) is True
    assert (item.exc_info is not None) is keeps


def test_the_filter_is_installed_once():
    quiet_expected_errors()
    quiet_expected_errors()
    filters = logging.getLogger(FASTMCP_SERVER_LOGGER).filters
    assert sum(isinstance(item, QuietExpectedErrors) for item in filters) == 1


KEY = "K" * 40


def test_redact_replaces_every_key_value():
    text = f"GET https://x/a.json?corp_code=1&crtfc_key={KEY} and ?CRTFC_KEY={KEY}&b=2"
    assert KEY not in redact(text)
    assert redact(text).count("[REDACTED]") == 2


def test_the_formatter_redacts_tracebacks():
    formatter = RedactingFormatter("%(message)s")
    try:
        message = f"failed for https://x/list.json?crtfc_key={KEY}"
        raise ValueError(message)  # noqa: TRY301 - building a real traceback
    except ValueError:
        record = logging.LogRecord("x", logging.ERROR, __file__, 1, "boom", None, sys.exc_info())
    assert KEY not in formatter.format(record)


@pytest.mark.anyio
async def test_upstream_request_logs_never_contain_the_key(caplog, mcp_settings, upstream):
    protect_secrets()
    caplog.set_level(logging.INFO)
    caplog.set_level(logging.INFO, logger="httpx2")  # another test may have quieted it
    upstream.route("/company.json", upstream.ok(corp_name="x"))
    api = OpenDartSettings(api_key=SecretStr(KEY))
    async with open_state(
        mcp_settings, metrics=Metrics(), api=api, transport=upstream.transport
    ) as state:
        gateway = state.require_gateway()
        await gateway.call(60, gateway.sdk.disclosures.company, corporation_code="00126380")
    assert "company.json" in caplog.text
    assert KEY not in caplog.text
    assert "crtfc_key=[REDACTED]" in caplog.text


def test_server_logging_quiets_http_clients(monkeypatch):
    # Work on a private root handler list and logger levels so other tests are unaffected.
    root = logging.getLogger()
    monkeypatch.setattr(root, "handlers", [])
    for name in ("httpx2", "httpcore2", "httpx", "httpcore", "docket.worker"):
        monkeypatch.setattr(logging.getLogger(name), "level", logging.NOTSET)
    configure_logging()
    assert logging.getLogger("httpx2").level == logging.WARNING
    assert logging.getLogger("docket.worker").level == logging.WARNING
    assert root.handlers
    assert all(isinstance(handler.formatter, RedactingFormatter) for handler in root.handlers)
