#!/usr/bin/env python3
"""Probe one installed distribution choice using an isolated interpreter outside the checkout."""

from __future__ import annotations

import argparse
import asyncio
import io
import os
import runpy
import socket
import sys
import zipfile
from importlib.metadata import PackageNotFoundError, version
from importlib.resources import files
from importlib.util import find_spec
from pathlib import Path

# The distributions each installation choice must contain and the modules it must lack.
DISTRIBUTIONS = {
    "sdk": ("opendart-sdk",),
    "analysis": ("opendart-analysis",),
    "mcp": ("opendart-sdk", "opendart-analysis", "opendart-mcp"),
}
FRAMEWORKS = (("opendart_mcp", "opendart-mcp"), ("fastmcp", "fastmcp"), ("mcp", "mcp"))
ABSENT = {
    "sdk": (("opendart_analysis", "opendart-analysis"), *FRAMEWORKS),
    "analysis": (("opendart", "opendart-sdk"), *FRAMEWORKS),
    "mcp": (),
}
FILING = "20260515003117"
# Minimal DART XML: one numbered section with an English heading and a Korean paragraph.
FILING_XML = """<?xml version="1.0" encoding="utf-8"?>
<DOCUMENT>
<DOCUMENT-NAME ACODE="11013">분기보고서</DOCUMENT-NAME>
<BODY>
<SECTION-1><TITLE ATOC="Y" AASSOCNOTE="D-0-1-0-0" ENG="I. Company Overview">I. 회사의 개요</TITLE>
<P>당사는 전자부품을 제조합니다.</P>
</SECTION-1>
</BODY>
</DOCUMENT>
"""


def require(condition: object, message: str) -> None:
    """Keep smoke assertions active even when PYTHONOPTIMIZE is configured."""
    if not condition:
        raise RuntimeError(message)


def installed(distribution: str) -> bool:
    """Report whether a distribution is installed in this environment."""
    try:
        version(distribution)
    except PackageNotFoundError:
        return False
    return True


def check_absent(packages: tuple[tuple[str, str], ...]) -> None:
    """Reject modules and distributions outside this installation choice without importing them."""
    for module, distribution in packages:
        require(find_spec(module) is None, f"{module} must not be importable here")
        require(not installed(distribution), f"{distribution} must not be installed here")


async def check_sdk() -> None:
    """Import the SDK's generated resources and perform one request using a mock transport."""
    import httpx2

    from opendart import OpenDART, OpenDARTSettings

    requests = []

    def respond(request):
        requests.append(request)
        return httpx2.Response(200, json={"status": "000", "message": "OK"})

    settings = OpenDARTSettings(api_key="0" * 40)
    async with OpenDART(settings, transport=httpx2.MockTransport(respond)) as client:
        response = await client.disclosures.search()
        require(response.status == "000", "SDK did not parse the synthetic response")
    require(len(requests) == 1 and client.is_closed, "SDK request or cleanup failed")
    require(files("opendart").joinpath("py.typed").is_file(), "SDK typing marker is missing")


def check_analysis() -> None:
    """Parse a synthetic DART XML archive in memory and outline, read, and search it."""
    from opendart_analysis.documents import parse_filing

    require(
        files("opendart_analysis").joinpath("py.typed").is_file(),
        "analysis typing marker is missing",
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(f"{FILING}.xml", FILING_XML.encode())
    filing = parse_filing(FILING, buffer.getvalue())
    outline = filing.outline()
    require(
        outline.filing_number == FILING
        and [document.form_code for document in outline.documents] == ["11013"]
        and [(section.id, section.title_en) for section in outline.sections]
        == [("D-0-1-0-0", "I. Company Overview")],
        "analysis did not outline the synthetic filing",
    )
    chunk = filing.read(section="D-0-1-0-0")
    require(
        "# I. Company Overview" in chunk.content
        and "전자부품을 제조합니다" in chunk.content
        and not chunk.truncated,
        "analysis did not render the synthetic section",
    )
    result = filing.search("전자부품")
    require(
        result.total_hits == 1 and result.hits[0].section_id == "D-0-1-0-0",
        "analysis did not search the synthetic filing",
    )


async def check_mcp() -> None:
    """Launch the installed console script and reuse the localhost HTTP protocol/security probe."""
    import anyio

    # Loading a single trusted probe does not add the checkout to the isolated interpreter's path.
    check = runpy.run_path(str(Path(__file__).with_name("check_mcp.py")))["check"]
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    command = Path(sys.executable).with_name(
        "opendart-mcp.exe" if os.name == "nt" else "opendart-mcp"
    )
    environment = {
        **{key: value for key, value in os.environ.items() if not key.startswith("OPENDART_")},
        "OPENDART_MCP_HTTP__HOST": "127.0.0.1",
        "OPENDART_MCP_HTTP__PORT": str(port),
    }
    async with await anyio.open_process(
        [str(command)], env=environment, stdout=sys.stderr, stderr=sys.stderr
    ) as process:
        try:
            await check(f"http://127.0.0.1:{port}/mcp")
        finally:
            if process.returncode is None:
                process.terminate()
                with anyio.move_on_after(5):
                    await process.wait()
                if process.returncode is None:
                    process.kill()
                    await process.wait()


def main() -> None:
    """Validate one installation choice: the SDK, analysis, or MCP with both libraries."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", required=True)
    parser.add_argument("--package", required=True, choices=sorted(DISTRIBUTIONS))
    args = parser.parse_args()
    require(sys.flags.isolated, "Run this probe with python -I to exclude checkout imports")
    for distribution in DISTRIBUTIONS[args.package]:
        require(installed(distribution), f"{distribution} is not installed")
        require(version(distribution) == args.version, f"Wrong {distribution} distribution version")
    check_absent(ABSENT[args.package])
    if args.package in {"sdk", "mcp"}:
        asyncio.run(check_sdk())
    if args.package == "analysis":
        check_analysis()
    if args.package == "mcp":
        asyncio.run(check_mcp())
    print(f"installed opendart-{args.package} {args.version}: smoke check passed")


if __name__ == "__main__":
    main()
