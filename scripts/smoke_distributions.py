#!/usr/bin/env python3
"""Install each SDK/analysis/MCP wheel and sdist into a fresh environment and probe it.

Each installation names only the distribution under test. Its declared requirements select the
other workspace packages from the same format's local artifacts and everything else from the
package index, without editable workspace packages. The probes make no requests to OpenDART
and require no API key. Installing dependencies requires network access.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from check_release import PACKAGES, ROOT, SUFFIXES, check_artifacts, check_sources

SCRUBBED = {"PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT"}


def smoke_distributions(dist: Path) -> None:
    """Exercise the SDK, analysis, and MCP installation choices from each artifact format."""
    dist = dist.resolve()
    version = check_sources(ROOT)
    check_artifacts(dist, version)
    probe = ROOT / "scripts" / "smoke_installed.py"
    environment = {
        key: value
        for key, value in os.environ.items()
        if key not in SCRUBBED and not key.startswith("OPENDART_")
    }
    # Relative cache locations must not disappear when the temporary working directory is removed.
    environment["UV_CACHE_DIR"] = str(
        Path(environment.get("UV_CACHE_DIR", ROOT / ".cache" / "uv")).resolve()
    )

    def run(*command: str, working_directory: Path) -> None:
        subprocess.run(  # noqa: S603 - fixed commands and validated local artifacts, no shell
            command, cwd=working_directory, env=environment, check=True, timeout=300
        )

    for suffix in SUFFIXES:
        with TemporaryDirectory(prefix="opendart-release-") as temporary:
            # The other format's artifacts must not satisfy this format's requirements.
            links = Path(temporary) / "artifacts"
            links.mkdir()
            for package in PACKAGES:
                name = f"opendart_{package.name}-{version}{suffix}"
                shutil.copy2(dist / name, links / name)
            # URL constraints pin workspace names to these files, so a same-named package on
            # the index can never be chosen; constraints add no requirements, so a missing
            # dependency declaration still fails.
            constraints = links / "constraints.txt"
            constraints.write_text(
                "".join(
                    f"opendart-{package.name} @ "
                    f"{(links / f"opendart_{package.name}-{version}{suffix}").as_uri()}\n"
                    for package in PACKAGES
                )
            )
            for package in PACKAGES:
                directory = Path(temporary) / package.name
                directory.mkdir()
                venv = directory / "venv"
                python = venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
                artifact = links / f"opendart_{package.name}-{version}{suffix}"
                run(
                    "uv", "venv", str(venv), "--python", sys.executable, working_directory=directory
                )
                run(
                    "uv",
                    "pip",
                    "install",
                    "--python",
                    str(python),
                    "--no-sources",
                    "--constraint",
                    str(constraints),
                    str(artifact),
                    working_directory=directory,
                )
                run("uv", "pip", "check", "--python", str(python), working_directory=directory)
                run(
                    str(python),
                    "-I",
                    str(probe),
                    "--version",
                    version,
                    "--package",
                    package.name,
                    working_directory=directory,
                )


def main() -> None:
    """Parse the artifact directory and validate every installation choice in both formats."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, default=ROOT / "dist")
    smoke_distributions(parser.parse_args().dist)


if __name__ == "__main__":
    main()
