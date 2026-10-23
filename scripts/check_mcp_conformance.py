"""Run the official MCP conformance suite against the OpenDART MCP server.

Starts an isolated native server on a free loopback port (or tests --url), then runs every
server scenario twice: once with the suite's default wire inference (2025-11-25 for
scenarios shared by both eras, plus 2026-only and extension scenarios such as tasks) and
once at the 2026-07-28 wire. Known failures are listed in
packages/mcp/conformance-baseline.yaml; an unexpected failure, or a baselined check that
now passes, fails the run. Requires Node.js for npx.

The server runs without an API key, so no tool reaches OpenDART: the suite tests the
protocol, and every component still lists. Rate limiting is disabled because the suite
sends bursts of requests that the default limit rejects.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import TYPE_CHECKING

import httpx2

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

ROOT = Path(__file__).resolve().parents[1]
BASELINE = ROOT / "packages/mcp/conformance-baseline.yaml"
RESULTS = ROOT / ".cache/conformance"
# Only the 0.2 prereleases know the 2026-07-28 revision; 0.1.x tests 2025-11-25 alone.
SUITE = "@modelcontextprotocol/conformance@0.2.0-alpha.12"
# Each run is (results subdirectory, suite arguments).
RUNS = (
    ("default", ("--suite", "all")),
    ("2026-07-28", ("--suite", "all", "--spec-version", "2026-07-28")),
)
STARTUP_SECONDS = 60


def free_port() -> int:
    """Reserve and release an unused loopback port.

    Returns:
        A port number that was free a moment ago.
    """
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def server_environment(port: int, cache_dir: Path) -> dict[str, str]:
    """Build an environment that isolates the server from local OpenDART configuration.

    Args:
        port: Listener port.
        cache_dir: Empty directory for the company directory cache.

    Returns:
        The process environment without any OPENDART_* variable, including the API key.
    """
    environment = {k: v for k, v in os.environ.items() if not k.startswith("OPENDART_")}
    http = {"host": "127.0.0.1", "port": port, "rate_limit": None}
    environment["OPENDART_MCP_HTTP"] = json.dumps(http)
    environment["OPENDART_MCP_DIRECTORY__CACHE_DIR"] = str(cache_dir)
    return environment


def wait_for_health(url: str, server: subprocess.Popen[bytes], log: Path) -> None:
    """Poll GET /health until the server answers.

    Args:
        url: MCP endpoint; /health is a sibling path.
        server: Server process, checked for an early exit.
        log: Server log, named in failures.
    """
    health = url.removesuffix("/mcp") + "/health"
    deadline = time.monotonic() + STARTUP_SECONDS
    with httpx2.Client(trust_env=False, timeout=2) as client:
        while time.monotonic() < deadline:
            if server.poll() is not None:
                raise RuntimeError(f"The MCP server exited early; see {log}")
            with suppress(httpx2.TransportError):
                if client.get(health).status_code == httpx2.codes.OK:
                    return
            time.sleep(0.2)
    raise RuntimeError(f"The MCP server did not answer {health}; see {log}")


@contextmanager
def native_server(log: Path) -> Iterator[str]:
    """Start the server without an API key on a free port and stop it afterwards.

    Args:
        log: File that receives the server's output.

    Yields:
        The server's MCP endpoint.
    """
    port = free_port()
    url = f"http://127.0.0.1:{port}/mcp"
    with (
        tempfile.TemporaryDirectory(prefix="opendart-conformance-") as cache_dir,
        log.open("wb") as output,
    ):
        server = subprocess.Popen(
            [sys.executable, "-m", "opendart_mcp.server"],
            env=server_environment(port, Path(cache_dir)),
            stdout=output,
            stderr=subprocess.STDOUT,
        )
        try:
            wait_for_health(url, server, log)
            yield url
        finally:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()


def run_suite(url: str, *, scenario: str | None) -> list[str]:
    """Run the conformance suite in each wire era against one endpoint.

    Args:
        url: MCP endpoint.
        scenario: Run only this scenario, in every era that applies to it.

    Returns:
        Names of the runs that failed.
    """
    npx = shutil.which("npx")
    if npx is None:
        raise RuntimeError("npx was not found; install Node.js 20 or later")
    failed = []
    for name, arguments in RUNS:
        output = RESULTS / name
        shutil.rmtree(output, ignore_errors=True)
        command = [npx, "--yes", f"--package={SUITE}", "conformance", "server", "--url", url]
        command += [*arguments, "--expected-failures", str(BASELINE), "--output-dir", str(output)]
        if scenario:
            command += ["--scenario", scenario]
        print(f"\n=== Conformance run: {name} ===", flush=True)
        if subprocess.run(command, cwd=ROOT, check=False).returncode:
            failed.append(name)
    return failed


def main(argv: Sequence[str] | None = None) -> int:
    """Run the suite against a running server or an isolated native one.

    Args:
        argv: Command-line arguments; defaults to sys.argv.

    Returns:
        Process exit status.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--url",
        help="Running MCP endpoint with rate limiting off; omit to start an isolated server",
    )
    parser.add_argument("--scenario", help="Run one scenario, for example tools-list")
    args = parser.parse_args(argv)
    RESULTS.mkdir(parents=True, exist_ok=True)
    if args.url:
        failed = run_suite(args.url, scenario=args.scenario)
    else:
        with native_server(RESULTS / "server.log") as url:
            failed = run_suite(url, scenario=args.scenario)
    if failed:
        print(f"\nConformance failed in: {", ".join(failed)}. Results are in {RESULTS}.")
        return 1
    print("\nConformance passed in both protocol eras; only baselined checks failed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
