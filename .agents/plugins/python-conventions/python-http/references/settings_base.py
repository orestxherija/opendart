"""Minimal settings contract from the python-settings dependency.

Reuse the project's existing SettingsGroup when present. This shipped adapter
lets the HTTP examples run independently; tests check it against python-settings.
"""

from pydantic import BaseModel, ConfigDict


class SettingsGroup(BaseModel):
    """Immutable configuration group with unknown fields rejected."""

    model_config = ConfigDict(frozen=True, extra="forbid")
