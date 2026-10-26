"""Verify localhost defaults and environment overrides for the MCP listener."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from opendart_mcp.settings import Settings, get_settings


@pytest.fixture(autouse=True)
def isolate_settings(monkeypatch):
    """Keep listener settings independent of the developer's environment."""
    monkeypatch.delenv("OPENDART_MCP_HTTP", raising=False)
    monkeypatch.delenv("OPENDART_MCP_HTTP__HOST", raising=False)
    monkeypatch.delenv("OPENDART_MCP_HTTP__PORT", raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_defaults_are_local_without_api_key(monkeypatch, tmp_path):
    """Start locally without credentials or automatically loading dotenv files."""
    monkeypatch.delenv("OPENDART_API__API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("OPENDART_MCP_HTTP__HOST=0.0.0.0\n")
    settings = get_settings()
    assert settings.http.host == "127.0.0.1"
    assert settings.http.port == 8000


def test_environment_overrides_are_validated_and_cached(monkeypatch):
    """Read Docker's wildcard bind and a custom port once per process."""
    monkeypatch.setenv("OPENDART_MCP_HTTP__HOST", "0.0.0.0")
    monkeypatch.setenv("OPENDART_MCP_HTTP__PORT", "9000")
    settings = get_settings()
    assert settings.http.host == "0.0.0.0"
    assert settings.http.port == 9000
    monkeypatch.setenv("OPENDART_MCP_HTTP__PORT", "9001")
    assert get_settings() is settings
    with pytest.raises(ValidationError, match="frozen_instance"):
        settings.http.port = 9001


@pytest.mark.parametrize("port", ["0", "65536", "not-a-port"])
def test_invalid_port_is_rejected(monkeypatch, port):
    """Reject invalid listener ports before attempting to start a server."""
    monkeypatch.setenv("OPENDART_MCP_HTTP__PORT", port)
    with pytest.raises(ValidationError):
        get_settings()


def test_unknown_listener_setting_is_rejected(monkeypatch):
    """Catch misspelled options within the HTTP settings group."""
    monkeypatch.setenv("OPENDART_MCP_HTTP__PRT", "9000")
    with pytest.raises(ValidationError, match="extra_forbidden"):
        Settings()
