"""Framework-independent OpenDART domain logic for the MCP server.

The modules here are pure: they parse and index the company directory, resolve company
references, normalize upstream strings, and model periods, dates, units, filing categories,
and filing titles. They never import the MCP framework or perform I/O, so tools, resources,
and prompts can share them and tests can exercise them offline.
"""

from __future__ import annotations
