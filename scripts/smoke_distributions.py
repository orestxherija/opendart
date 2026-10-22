#!/usr/bin/env python3
"""Install SDK/MCP wheels and sdists into separate environments and probe installed packages.

Dependencies resolve from published metadata, without editable workspace packages. The probes
make no requests to OpenDART and require no API key.
Installing dependencies requires network access.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from check_release import ROOT, check_artifacts, check_sources


def smoke_distributions(dist: Path) -> None:
    """Exercise the standalone SDK, then the SDK plus MCP, from each artifact format."""
    dist = dist.resolve()
    version = check_sources(ROOT)
    check_artifacts(dist, version)
    probe = ROOT / "scripts" / "smoke_installed.py"
    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in {"PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT"}
        and not key.startswith("OPENDART_")
    }
    # Relative cache locations must not disappear when the temporary working directory is removed.
    environment["UV_CACHE_DIR"] = str(
        Path(environment.get("UV_CACHE_DIR", ROOT / ".cache" / "uv")).resolve()
    )
    for suffix in ("-py3-none-any.whl", ".tar.gz"):
        with TemporaryDirectory(prefix="opendart-release-") as temporary:
            directory = Path(temporary)
            venv = directory / "venv"
            python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")

            def run(*command: str, working_directory: Path = directory) -> None:
                subprocess.run(  # noqa: S603 - fixed commands and validated local artifacts, no shell
                    command, cwd=working_directory, env=environment, check=True, timeout=300
                )

            run("uv", "venv", str(venv), "--python", sys.executable)
            sdk = str(dist / f"opendart_sdk-{version}{suffix}")
            for package in ("sdk", "mcp"):
                artifacts = (
                    (sdk,)
                    if package == "sdk"
                    else (sdk, str(dist / f"opendart_mcp-{version}{suffix}"))
                )
                run("uv", "pip", "install", "--python", str(python), "--no-sources", *artifacts)
                run("uv", "pip", "check", "--python", str(python))
                flags = ("--sdk-only",) if package == "sdk" else ()
                run(str(python), "-I", str(probe), "--version", version, *flags)


def main() -> None:
    """Parse the artifact directory and validate both installed distribution formats."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, default=ROOT / "dist")
    smoke_distributions(parser.parse_args().dist)


if __name__ == "__main__":
    main()
