"""Framework-independent OpenDART domain logic.

The modules here are pure: they parse and index the company directory, resolve company
references, normalize upstream strings, and model periods, dates, units, filing categories,
and filing titles. They never perform I/O, so any application can share them and tests can
exercise them offline. ``opendart_analysis.directory`` is the public entry point for company
lookup; the other modules are internal and may change.
"""

from __future__ import annotations
