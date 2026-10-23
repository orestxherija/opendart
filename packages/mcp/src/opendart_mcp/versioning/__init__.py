"""Component versions without the MCP framework: lock records, schema diffs, and bump rules.

``model`` holds the lock records and the hashing and token rules; ``schema`` and ``keywords``
classify JSON Schema differences; ``changes`` classifies whole component definitions and
compares versions; ``policy`` reviews a recorded lock against the current server.
``opendart_mcp.manifest`` builds the records from a running FastMCP server.
"""
