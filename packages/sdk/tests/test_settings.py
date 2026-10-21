"""Verify explicit settings loading, caching, immutability, and validation."""

from __future__ import annotations

import pytest
from pydantic import SecretStr, ValidationError

from opendart import OpenDartSettings, Settings, get_settings


def test_environment_and_cache(monkeypatch):
    """Verify nested environment loading, secret masking, caching, and immutability.

    Args:
        monkeypatch (pytest.MonkeyPatch): Fixture for temporary environment and
            process-state changes.
    """
    key = "x" * 40
    monkeypatch.setenv("OPENDART_API__API_KEY", key)
    monkeypatch.setenv("OPENDART_API__TIMEOUT", "12.5")
    settings = get_settings()
    assert settings.api.api_key.get_secret_value() == key
    assert settings.api.timeout == 12.5
    assert get_settings() is settings
    assert key not in repr(settings)
    assert key not in settings.model_dump_json()
    with pytest.raises(ValidationError):
        settings.api.timeout = 1


def test_dotenv_is_opt_in_and_environment_wins(tmp_path, monkeypatch):
    """Verify dotenv opt-in, ignored unrelated keys, and environment precedence.

    Args:
        tmp_path (Path): Temporary directory for an isolated dotenv file.
        monkeypatch (pytest.MonkeyPatch): Fixture for temporary environment and
            process-state changes.
    """
    monkeypatch.delenv("OPENDART_API", raising=False)
    monkeypatch.delenv("OPENDART_API__API_KEY", raising=False)
    monkeypatch.chdir(tmp_path)
    (tmp_path / ".env").write_text("OPENDART_API__API_KEY=" + "x" * 40 + "\nUNRELATED=allowed\n")
    with pytest.raises(ValidationError):
        Settings()
    assert Settings(_env_file=tmp_path / ".env").api.api_key.get_secret_value() == "x" * 40
    monkeypatch.setenv("OPENDART_API__API_KEY", "y" * 40)
    assert Settings(_env_file=tmp_path / ".env").api.api_key.get_secret_value() == "y" * 40


@pytest.mark.parametrize(
    "updates",
    [
        {"api_key": "short"},
        {"timeout": 0},
        {"timeout": float("inf")},
        {"max_connections": 1, "max_keepalive_connections": 2},
        {"max_response_bytes": 0},
        {"base_url": "http://engopendart.fss.or.kr/engapi"},
        {"base_url": "https://opendart.fss.or.kr/api"},
        {"base_url": "https://user:secret@example.com/api"},
        {"base_url": "https://example.com/api?crtfc_key=secret"},
        {"typo": True},
    ],
)
def test_invalid_settings(updates):
    """Verify that invalid or unknown configuration values are rejected.

    Args:
        updates (dict[str, object]): Invalid field values overlaid on otherwise valid
            settings.
    """
    values = {"api_key": SecretStr("x" * 40), **updates}
    with pytest.raises(ValidationError):
        OpenDartSettings(**values)
