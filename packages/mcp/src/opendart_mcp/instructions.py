"""Server instructions: cross-tool guidance every client receives on connection."""

from __future__ import annotations

from typing import Final

INSTRUCTIONS: Final = """\
OpenDART serves the regulatory filings of Korean companies from DART: identities, filing \
lists, original filing documents, financial statements, peer tables, material events, \
ownership, share capital, debt, dividends, governance, and upcoming corporate-action dates.

- Pass companies by name (English or Korean), stock code (005930), or 8-digit DART corp \
code; every tool resolves them. An ambiguous name returns candidates: retry with a code. \
Use find_company to confirm identities or browse matches.
- There are no prices, volumes, market capitalization, consensus estimates, or news. Never \
estimate price-based metrics; dividend yields are only as filed.
- period="latest" means the most recent periodic report of any kind; results state the \
period end date, and fiscal years can end in months other than December.
- Amounts are in won; text tables default to millions of won. Ratios, per-share amounts, \
and share counts are never scaled.
- Cite filing numbers from source_filings. read_filing opens any filing: documents are \
Korean, headings and labels are in English where the filing provides them, and you \
translate the prose.
- "No data" is a normal answer with a note, not an error.
- Start broad (search_filings, get_corporate_events), then drill down with read_filing. \
Prefer concise output; use response_format="detailed" only when needed.
- Slow calls report progress. If a result says work is still in progress, repeat the same \
call in about a minute; the result will be cached.
- Conventions: opendart://reference/vocabulary. Codes: \
opendart://reference/filing-categories and opendart://reference/event-kinds.
"""
