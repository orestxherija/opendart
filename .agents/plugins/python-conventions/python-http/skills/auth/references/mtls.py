"""A mutual-TLS context, independent of other authentication schemes.

Copy this reference to ``app/http_mtls.py``. The only project dependency is
``app.settings.base.SettingsGroup`` from ``python-settings``. Pass the resulting
context as ``verify`` to an existing ``httpx2.AsyncClient`` or the optional
client skill's factory. The caller retains normal client-lifecycle ownership.

Example::

    verify = create_mtls_context(settings.ledger_cert)
    async with httpx2.AsyncClient(verify=verify) as client:
        response = await client.get("https://ledger.example/entries")
        response.raise_for_status()
"""

import ssl

import httpx2
from pydantic import Field, FilePath, SecretStr

from app.settings.base import SettingsGroup


class ClientCertSettings(SettingsGroup):
    """A client certificate for mutual TLS.

    Attributes:
        cert_file (FilePath): PEM certificate chain.
        key_file (FilePath): PEM private key.
        key_password (SecretStr | None): Password for an encrypted key.
    """

    cert_file: FilePath = Field(description="PEM certificate chain.")
    key_file: FilePath = Field(description="PEM private key.")
    key_password: SecretStr | None = Field(
        default=None, description="Password for an encrypted private key."
    )


def create_mtls_context(settings: ClientCertSettings) -> ssl.SSLContext:
    """Build a TLS context that presents a client certificate.

    Starts from httpx2's default context, so server verification still uses the
    operating system trust store and honors ``SSL_CERT_FILE`` / ``SSL_CERT_DIR``.

    Args:
        settings (ClientCertSettings): Certificate, key, and optional password.

    Returns:
        ssl.SSLContext: A context to pass to ``build_client`` as ``verify``.
    """
    context = httpx2.create_ssl_context()
    context.load_cert_chain(
        certfile=settings.cert_file,
        keyfile=settings.key_file,
        password=(
            settings.key_password.get_secret_value() if settings.key_password else None
        ),
    )
    return context
