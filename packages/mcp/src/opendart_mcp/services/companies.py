"""Turn the company text a tool receives into a resolved identity with its profile.

Every tool accepts a name, stock code, or DART corporation code. Codes resolve exactly;
names go through the directory. The company profile supplies the listing market and the
fiscal year-end month that period resolution needs, and is cached for a day.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from opendart_analysis.domain.identifiers import parse_identifier
from opendart_analysis.domain.normalize import clean_text, market_from_corp_cls
from opendart_analysis.domain.resolver import resolve
from opendart_mcp.core.errors import (
    API_KEY_MISSING,
    AmbiguousCompanyError,
    CompanyNotFoundError,
    ConfigurationError,
    InvalidArgumentError,
)
from opendart_mcp.core.interaction import current_chooser
from opendart_mcp.core.ttl import DAY
from opendart_mcp.models.common import CompanyRef
from opendart_mcp.services.company_messages import ambiguity_message, not_found_message

if TYPE_CHECKING:
    from opendart.models import CompanyResponse
    from opendart_analysis.domain.directory import CorpRecord
    from opendart_mcp.core.gateway import Gateway
    from opendart_mcp.core.interaction import Chooser
    from opendart_mcp.core.progress import Progress
    from opendart_mcp.services.directory import DirectoryService

DECEMBER = 12


@dataclass(frozen=True, slots=True)
class Company:
    """A resolved company with the profile facts other components need.

    Attributes:
        ref (CompanyRef): Identity attached to results.
        fye_month (int): Fiscal year-end month (1-12); 12 when the profile omits it.
        profile (CompanyResponse | None): Company overview, when OpenDART has one.
    """

    ref: CompanyRef
    fye_month: int
    profile: CompanyResponse | None

    @property
    def corp_code(self) -> str:
        """The 8-digit DART corporation code.

        Returns:
            str: Corporation code.
        """
        return self.ref.corp_code


def _fye_month(profile: CompanyResponse | None) -> int:
    """Read the fiscal year-end month from a profile.

    Args:
        profile (CompanyResponse | None): Company overview.

    Returns:
        int: Month 1-12, defaulting to December.
    """
    month = clean_text(profile.acc_mt if profile else None)
    return int(month) if month and month.isdigit() and 1 <= int(month) <= DECEMBER else DECEMBER


class Companies:
    """Resolve company arguments and fetch company profiles."""

    def __init__(
        self, directory: DirectoryService, gateway: Gateway | None, *, wait: float
    ) -> None:
        """Bind the directory and upstream access.

        Args:
            directory (DirectoryService): Company directory owner.
            gateway (Gateway | None): Upstream access; None when no API key is configured.
            wait (float): Seconds to wait for a loading directory.
        """
        self._directory = directory
        self._gateway = gateway
        self._wait = wait

    async def profile(self, corp_code: str) -> CompanyResponse | None:
        """Fetch a company overview, cached for a day.

        Args:
            corp_code (str): 8-digit DART corporation code.

        Returns:
            CompanyResponse | None: Overview, or None when OpenDART has none.

        Raises:
            ConfigurationError: No API key is configured.
        """
        if self._gateway is None:
            raise ConfigurationError(API_KEY_MISSING)
        sdk = self._gateway.sdk
        return await self._gateway.call(DAY, sdk.disclosures.company, corporation_code=corp_code)

    async def describe(self, record: CorpRecord) -> Company:
        """Attach profile facts to a directory record.

        Args:
            record (CorpRecord): Directory entry.

        Returns:
            Company: Resolved company.
        """
        profile = await self.profile(record.corp_code)
        ref = CompanyRef(
            name=record.english_name or record.name,
            korean_name=record.name,
            corp_code=record.corp_code,
            stock_code=record.stock_code,
            market=market_from_corp_cls(profile.corporation_type if profile else None),
        )
        return Company(ref=ref, fye_month=_fye_month(profile), profile=profile)

    async def resolve(
        self, text: str, *, progress: Progress | None = None, choose: Chooser | None = None
    ) -> Company:
        """Resolve a company argument to one company.

        Args:
            text (str): Name, stock code, or corporation code.
            progress (Progress | None): Reports progress while the directory loads.
            choose (Chooser | None): Asks the user to pick among ambiguous candidates.

        Returns:
            Company: The resolved company.

        Raises:
            InvalidArgumentError: The text is a filing number.
            CompanyNotFoundError: Nothing matches.
            AmbiguousCompanyError: Several companies match and none was chosen.
        """
        identifier = parse_identifier(text)
        if identifier is not None and identifier.kind == "filing_number":
            message = f"'{text}' is a filing number, not a company. Pass a company name or code, or call read_filing for the filing."
            raise InvalidArgumentError(message)
        if identifier is not None and identifier.kind == "corp_code":
            return await self._by_corp_code(identifier.value)
        directory = await self._directory.wait(self._wait, progress)
        resolution = resolve(directory, text)
        if resolution.record is not None:
            return await self.describe(resolution.record)
        if resolution.reason != "ambiguous":
            raise CompanyNotFoundError(not_found_message(text))
        choose = choose or current_chooser()
        chosen = await choose(text, resolution.candidates) if choose else None
        if chosen is None:
            raise AmbiguousCompanyError(ambiguity_message(text, resolution.candidates))
        return await self.describe(chosen)

    async def _by_corp_code(self, corp_code: str) -> Company:
        """Resolve a corporation code, with or without the directory.

        Args:
            corp_code (str): 8-digit DART corporation code.

        Returns:
            Company: Resolved company.

        Raises:
            CompanyNotFoundError: OpenDART has no company with this code.
        """
        directory = self._directory.directory
        record = directory.get(corp_code) if directory is not None else None
        if record is not None:
            return await self.describe(record)
        profile = await self.profile(corp_code)
        if profile is None:
            message = (
                f"No company has DART corp code {corp_code}. Call find_company to search by name."
            )
            raise CompanyNotFoundError(message)
        korean = clean_text(profile.corporation_name)
        ref = CompanyRef(
            name=clean_text(profile.corp_name_eng) or korean or corp_code,
            korean_name=korean,
            corp_code=corp_code,
            stock_code=clean_text(profile.stock_code),
            market=market_from_corp_cls(profile.corporation_type),
        )
        return Company(ref=ref, fye_month=_fye_month(profile), profile=profile)
