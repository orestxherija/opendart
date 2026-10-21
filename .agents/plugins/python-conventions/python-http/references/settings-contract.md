# HTTP settings contract

Read this only when a reference needs settings helpers the project does not
already provide. The plugin depends on `python-settings ^1.0`; consult
`python-settings:python-settings` when creating the root settings object,
environment/TOML sources, or cached settings access.

The shipped references use project module names. Installing a plugin supplies
instructions and examples; it does not install an `app` Python package or Python
library dependencies into the user's application.

| Project location | Shipped source | Contract |
|---|---|---|
| `app.settings.base` | [settings_base.py](settings_base.py) | `SettingsGroup`: Pydantic `BaseModel`, frozen, unknown fields forbidden |
| `app.settings.types` | [settings_types.py](settings_types.py) | `PoolSize`, `Seconds`, `Attempts`, `HttpsUrl` |

Reuse existing matching definitions. Otherwise copy the needed definitions into
the project's settings package and adapt the `app` import prefix to its package
name. Keep each alias defined once in the application. These bounds are selected
defaults and may be adjusted to a documented upstream requirement.

`client` consumes `PoolSize` and `Seconds`; `retries` consumes `Attempts` and
`Seconds`; OAuth consumes `HttpsUrl` and `Seconds`. Simple API-key and mTLS
settings need only `SettingsGroup`. No skill requires reading all the others to
use these helpers.

Runtime baseline: Python 3.11+, `httpx2>=2.13,<3`, `pydantic>=2.7,<3`.
Root environment loading additionally uses `pydantic-settings>=2.3,<3`.
HTTP/2 requires `httpx2[http2]`. Test tools and certificate-generation libraries
are development dependencies, not prerequisites for ordinary HTTP calls.
