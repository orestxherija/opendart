---
name: auth
description: "Implement or review outbound httpx2 credentials in Python: API-key headers, OAuth client-credentials tokens, basic auth, and mutual TLS. Applies to upstream clients, not authentication of users calling your own service."
metadata:
  author: Orest Xherija
  category: python
---

# Outbound HTTP authentication

Choose the credential scheme the upstream documents. Reuse the caller's client;
adding credentials does not require introducing a new factory or retry layer.
For a scoped change, preserve the existing HTTP library and architecture.

## Prerequisites

Python 3.11+, `httpx2>=2.13,<3`, `pydantic>=2.7,<3`.
Settings classes use `SettingsGroup`; OAuth also uses `Seconds` and `HttpsUrl`
from the [settings contract](../../references/settings-contract.md).
Secrets remain `SecretStr` until signing a request or loading a private key.

## Pick only the required reference

| Scheme | Implementation and reference |
|---|---|
| Static bearer | Existing client `settings.token` convenience; consult [client](../client/SKILL.md) only when its construction changes |
| API-key header | `ApiKeyAuth` in [example.py](references/example.py), project module `app.http_auth` |
| Basic auth | `httpx2.BasicAuth(username, password.get_secret_value())`; keep values in settings |
| OAuth client credentials | `ClientCredentialsAuth` in [oauth2.py](references/oauth2.py), module `app.http_oauth2` |
| Mutual TLS | `create_mtls_context` in [mtls.py](references/mtls.py), module `app.http_mtls` |

Pass an Auth through `auth=` and a TLS context through `verify=`, on either the
existing client or this plugin's factory. Set `settings.token` to None when
providing an explicit Auth. A certificate and an application credential can
combine.

## Token refresh contract

Read the OAuth reference only for client-credentials token acquisition and
renewal. It caches tokens, uses a monotonic expiry margin capped at half the
lifetime, and serializes refresh with a lock and generation counter.
Validate the token response before caching: a usable bearer token and a finite,
nonnegative `expires_in` when supplied. Malformed responses are contract errors.

A yielded token request needs an absolute HTTPS URL and its own timeout
extension: the owning client's default request headers, base URL, and timeout
are not applied to that yielded request. The reference shares the client's
transport configuration. Use separately owned clients when the identity
provider and resource server require different TLS/proxy/lifetime policies.

The default `replay_after_401=False` returns a 401 and invalidates the rejected
cached token for the next call. Opt into one refresh and replay only when the
upstream contract and request body permit it. That mode buffers the body: limit
the body before enabling replay and keep replay off for unbounded streams.
Concurrent 401s must not invalidate a newer token.

User authorization, PKCE, OIDC discovery, and persisted refresh-token rotation
need a protocol-specific integration. Confirm the chosen library supports the
project's HTTP client/version before adding it.

## Credential boundaries

- Keep credentials out of URLs, query strings, default header dictionaries,
  diagnostic output, and token-response logs.
- An API key in a custom header can survive cross-origin redirects. Leave
  redirects disabled unless target origins and header handling are explicit.
- mTLS starts from the library's verified SSL context, adds the certificate
  chain, and preserves server trust configuration.
- Token renewal is separate from retrying an application operation. Consult
  [retries](../retries/SKILL.md) only when adding that operation's retry policy.
- Use [testing](../testing/SKILL.md) for transport and clock tests, and
  [streaming](../streaming/SKILL.md) when body ownership or replay matters.
