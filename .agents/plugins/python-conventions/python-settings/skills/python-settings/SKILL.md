---
name: python-settings
description: "Conventions for centralized configuration in Python using Pydantic. Use when designing, modifying, or reviewing settings/config for services, libraries, CLIs, pipelines, ETL jobs, or any multi-module project: BaseSettings, BaseModel config groups, env vars, .env files, TOML config files, settings_customise_sources, get_settings, Annotated config types, computed_field, or adding a new config value. Also use when migrating os.getenv, dataclass, or dict-based config to Pydantic. Do NOT use for throwaway one-off scripts, where argparse or plain constants are fine."
metadata:
  author: Orest Xherija
  version: "1.0.0"
  category: python
---

# Python Settings Conventions

## Rules

1. **Pydantic for all settings.** The root is a `pydantic_settings.BaseSettings`;
   nested groups subclass `SettingsGroup` (a `BaseModel`). Only the root reads
   the environment.
2. **Nest by concern.** Group fields (`DatabaseSettings`, `AuthSettings`, ...)
   instead of flat `db_host`, `db_port`. Use `env_nested_delimiter="__"`.
3. **Annotated first.** Any constraint that depends only on the field's own value
   lives in a reusable `Annotated` alias, never in a validator. Define each alias
   once, in one of two layouts:
   - **No `types.py`:** place the aliases at the top of the module, after the
     imports and before any `BaseModel` or `BaseSettings` class.
   - **With `types.py`:** create it in the settings package as soon as an alias
     is needed by more than one module. From then on, every alias lives there,
     and modules import them rather than defining their own.
4. **Validators only for multi-field logic** (see placement table).
5. **Cached factory.** Expose settings through `get_settings()` decorated with
   `@lru_cache`. Never instantiate `Settings()` at import time.
6. **Immutable.** `frozen=True` on every settings model, because cached objects
   must not be mutated.
7. **Secrets are `SecretStr`.**
8. **One name per setting.** Do not use field aliases, and never accept several
   names for the same setting. To rename a setting, rename the field and migrate
   the deployments.
9. **TOML for non-env values.** Load non-env configuration files through
   `settings_customise_sources` with `TomlConfigSettingsSource`, and nowhere
   else. Environment variables outrank the TOML file. Secrets never go in TOML.

## Validator placement

| Situation | Tool |
|---|---|
| Range, length, pattern, normalization, URL/path checks | `Annotated` alias |
| Rule across fields of one group (`min <= max`, `enabled` requires `cert`) | `@model_validator(mode="after")` on **that group** |
| Rule across groups (`api.require_auth` requires `auth.issuer`) | `@model_validator(mode="after")` on the **root** |
| Reshaping raw input (a single URL expanded into a group) | `@model_validator(mode="before")` |
| Tightening a field inherited from a parent model | `@field_validator` (the only case) |
| Value purely derived from other fields | `@computed_field` (see below) |

Place each validator on the lowest model that owns every field it reads.

## Derived values

Use `@computed_field` for a value that is purely derived from other fields of
the same model, is read by consumers like a field, and belongs in serialization
and the JSON schema (e.g. a DSN built from host, port, and credentials).

- Stack it on top of `@cached_property` when the computation is non-trivial.
  `@computed_field` goes outermost.
- A computed value that embeds a secret returns `SecretStr`, because computed
  fields appear in `model_dump()`.
- Use a plain `@property` for internal helpers that should not be serialized.
- Do not derive values inside validators.

## Model config

- Root: `extra="ignore"` (shared `.env` files carry unrelated keys), `frozen=True`.
- Nested groups inherit from a single public base, `SettingsGroup`, that sets
  `frozen=True` and `extra="forbid"`, so a new group cannot omit them. In a
  multi-module layout, define it in the settings package's `base.py` and import
  it from there.

## Anti-patterns

- `@field_validator` for something an `Annotated` alias can express
- Flat `db_host` / `db_port` fields instead of a nested model
- Module-level `settings = Settings()`
- Nested groups subclassing `BaseSettings` (duplicate env loading, prefix confusion)
- Nested groups that do not inherit `SettingsGroup`, or that override its `frozen` / `extra` settings
- `get_settings()` taking arguments (breaks `lru_cache`)
- Raw `str` for secrets
- Cross-group checks placed in a child model, or single-group checks placed on the root
- Field aliases (`validation_alias`, `AliasChoices`), or several accepted names for one setting
- `Annotated` aliases defined outside `types.py` once a `types.py` exists, or the same `Annotated` alias defined in more than one module
- `Annotated` aliases defined below or between model classes instead of at the top of the module
- Deriving a value in a validator when `@computed_field` can express it
- Computed fields that return a raw secret
- Reading config files with `tomllib` / `json.load` instead of `settings_customise_sources`
- Secrets stored in TOML files
- Introducing a settings layer into a throwaway script (pipelines, ETL jobs, and other scheduled or deployed scripts are not throwaway and do get settings)

## Reference

`references/example.py` is the canonical implementation. Match its structure
and style in all new settings code.
