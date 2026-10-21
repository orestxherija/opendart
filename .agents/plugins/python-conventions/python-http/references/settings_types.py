"""Validated aliases consumed by HTTP references, copied into app.settings.types.

These are convention defaults, not HTTP protocol limits. Reuse matching project
aliases and adjust constraints deliberately when an upstream needs other bounds.
"""

from typing import Annotated

from pydantic import AnyUrl, Field, UrlConstraints

PoolSize = Annotated[int, Field(ge=1, le=500)]
"""A connection pool size (1–500); matches the python-settings example."""

Seconds = Annotated[float, Field(gt=0, le=300)]
"""A positive per-phase timeout or backoff in seconds, at most 300."""

HttpsUrl = Annotated[AnyUrl, UrlConstraints(allowed_schemes=["https"])]
"""An absolute HTTPS URL for endpoints that receive credentials."""

Attempts = Annotated[int, Field(ge=1, le=10)]
"""Total attempts, including the first (1–10)."""
