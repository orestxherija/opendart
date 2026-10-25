"""Framework-free test data and fakes shared by more than one package's suite.

Modules here import neither FastMCP nor the MCP server, so the analysis suite can use them
without MCP installed. CI filters and test hooks for each suite that imports them list
``tests/support/**``.
"""
