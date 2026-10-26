"""Check the container's actual privileges, filesystem, and optional mounted API key.

Run inside the container through stdin so this check need not ship in the image.
The CI script scripts/mcp/check_mcp_container.sh supplies the Compose command.
"""

from __future__ import annotations

import argparse
import errno
import os
import ssl
import tempfile
from pathlib import Path

import opendart
from opendart import get_settings

RUNTIME_ID = 10001
API_KEY_LENGTH = 40


def require(condition: object, message: str, /) -> None:
    """Fail with a safe diagnostic even when Python assertions are disabled."""
    if not condition:
        raise RuntimeError(message)


def check(*, require_secret: bool = False) -> None:
    """Exercise restrictions from inside the service container."""
    require(os.getuid() == RUNTIME_ID and os.getgid() == RUNTIME_ID, "Unexpected runtime UID/GID")
    require(bool(ssl.create_default_context().get_ca_certs()), "CA certificates missing")
    require(Path(opendart.__file__).stat().st_uid == 0, "Installed code must be root-owned")
    require(not os.access(opendart.__file__, os.W_OK), "Runtime user can modify installed code")
    status = dict(line.split(":", 1) for line in Path("/proc/self/status").read_text().splitlines())
    for name in ("CapInh", "CapPrm", "CapEff", "CapBnd", "CapAmb"):
        require(int(status[name].strip(), 16) == 0, f"Unexpected capability set: {name}")
    require(status["NoNewPrivs"].strip() == "1", "Privilege escalation is enabled")
    require(status["Seccomp"].strip() == "2", "Seccomp filtering is disabled")
    try:
        with tempfile.TemporaryFile(dir="/app"):
            pass
    except OSError as error:
        require(error.errno == errno.EROFS, "Application filesystem is not read-only")
    else:
        raise RuntimeError("Application filesystem is writable")
    mount = next(
        line.split()
        for line in Path("/proc/mounts").read_text().splitlines()
        if line.split()[1] == tempfile.gettempdir()
    )
    require(mount[2] == "tmpfs", "Temporary files are not on tmpfs")
    require({"rw", "noexec", "nosuid", "nodev"} <= set(mount[3].split(",")), "Unsafe tmpfs flags")
    with tempfile.TemporaryFile() as temporary:
        temporary.write(b"runtime-check")
        temporary.seek(0)
        require(temporary.read() == b"runtime-check", "Temporary storage is unusable")
    require("OPENDART_API__API_KEY" not in os.environ, "API key leaked into container environment")
    secret_exists = Path("/run/secrets/OPENDART_API__API_KEY").exists()
    require(not require_secret or secret_exists, "Expected API key file was not mounted")
    if secret_exists:
        require(
            len(get_settings().api.api_key.get_secret_value()) == API_KEY_LENGTH,
            "File secret failed to load",
        )
    print("MCP runtime restrictions and mounted secret checks passed")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-secret", action="store_true")
    check(require_secret=parser.parse_args().require_secret)
