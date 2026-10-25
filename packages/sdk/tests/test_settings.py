"""Verify explicit settings loading, caching, immutability, and validation."""

from __future__ import annotations

import pytest
from pydantic import SecretStr, ValidationError

from opendart import OpenDARTSettings, Settings, get_settings


@pytest.fixture
def secret_directory(tmp_path, monkeypatch):
    """Create an isolated file secret without using the developer's credentials."""
    monkeypatch.delenv("OPENDART_API", raising=False)
    monkeypatch.delenv("OPENDART_API__API_KEY", raising=False)
    (tmp_path / "OPENDART_API__API_KEY").write_text("x" * 40 + "\n")
    return tmp_path


def test_nested_file_secret_is_validated_and_masked(secret_directory):
    settings = Settings(_secrets_dir=secret_directory)
    assert settings.api.api_key.get_secret_value() == "x" * 40
    assert "x" * 40 not in repr(settings)
    assert "x" * 40 not in settings.model_dump_json()
    (secret_directory / "OPENDART_API__API_KEY").write_text("invalid-secret")
    with pytest.raises(ValidationError) as error:
        Settings(_secrets_dir=secret_directory)
    assert "invalid-secret" not in str(error.value)


def test_file_secret_has_lowest_priority(secret_directory, monkeypatch):
    dotenv = secret_directory / ".env"
    dotenv.write_text("OPENDART_API__API_KEY=" + "y" * 40 + "\n")
    assert Settings(_secrets_dir=secret_directory, _env_file=dotenv).api.api_key == SecretStr(
        "y" * 40
    )
    monkeypatch.setenv("OPENDART_API__API_KEY", "z" * 40)
    assert Settings(_secrets_dir=secret_directory, _env_file=dotenv).api.api_key == SecretStr(
        "z" * 40
    )
    assert Settings(
        api={"api_key": "w" * 40}, _secrets_dir=secret_directory, _env_file=dotenv
    ).api.api_key == SecretStr("w" * 40)


def test_missing_secret_directory_is_optional(tmp_path, monkeypatch):
    monkeypatch.delenv("OPENDART_API", raising=False)
    monkeypatch.delenv("OPENDART_API__API_KEY", raising=False)
    with pytest.raises(ValidationError):
        Settings(_secrets_dir=tmp_path / "missing")
    assert Settings(api={"api_key": "x" * 40}, _secrets_dir=tmp_path / "missing").api.api_key


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
        OpenDARTSettings(**values)
