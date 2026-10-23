"""Output model for preliminary earnings, the input of get_financials(view="preliminary")."""

from __future__ import annotations

from pydantic import Field

from opendart_mcp.documents.preliminary import PreliminaryEarnings
from opendart_mcp.models.common import OutputModel, SourceFiling


class PreliminaryResult(OutputModel):
    """A company's latest preliminary (unaudited) quarterly results and their filing."""

    earnings: PreliminaryEarnings
    source: SourceFiling = Field(description="The KRX fair disclosure the figures come from.")
    notes: list[str] = Field(
        default_factory=list, description="Newer disclosures that could not be read, if any."
    )
