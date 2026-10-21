"""Shared request and response model behavior."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class RequestModel(BaseModel):
    """Base for immutable, strictly validated query parameters.

    Unknown fields are rejected. Subclasses define endpoint-specific constraints.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True, populate_by_name=True)

    def query(self) -> dict[str, str | int]:
        """Serialize query fields, omitting None and joining array values with commas.

        Returns:
            dict[str, str | int]: Query values ready to pass to the HTTP client.
        """
        data = self.model_dump(mode="json", exclude_none=True, by_alias=True)
        return {
            name: ",".join(value) if isinstance(value, list) else value
            for name, value in data.items()
        }


class ResponseModel(BaseModel):
    """Base for strictly validated responses that preserve unknown upstream fields.

    Financial strings retain their original representation. Aliased fields accept either
    their Python name or their upstream name.
    """

    model_config = ConfigDict(extra="allow", strict=True, populate_by_name=True)
