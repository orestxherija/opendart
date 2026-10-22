#!/usr/bin/env python3
"""Validate coordinated SDK/MCP versions and the complete set of release distributions."""

from __future__ import annotations

import argparse
import sys
import tarfile
import tomllib
from email.parser import BytesParser
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

ROOT = Path(__file__).resolve().parents[1]
PACKAGES = ("sdk", "mcp")
ASSETS = {
    "sdk": {"opendart/__init__.py", "opendart/client.py", "opendart/py.typed"},
    "mcp": {"opendart_mcp/__init__.py", "opendart_mcp/__main__.py", "opendart_mcp/server.py"},
}


def projects(root: Path) -> dict:
    """Read the two publishable project tables."""
    return {
        name: tomllib.loads((root / "packages" / name / "pyproject.toml").read_text())["project"]
        for name in PACKAGES
    }


def check_sources(root: Path, tag: str | None = None) -> str:
    """Return the coordinated release version; the virtual workspace root is independent."""
    packages = projects(root)
    release = tomllib.loads((root / "cz.toml").read_text())["tool"]["commitizen"]
    version = str(Version(packages["sdk"]["version"]))
    if (
        any(packages[name]["version"] != version for name in PACKAGES)
        or release.get("version") != version
    ):
        raise ValueError("SDK, MCP and Commitizen release versions must agree")
    if release.get("version_provider") != "commitizen" or set(release.get("version_files", [])) != {
        "packages/sdk/pyproject.toml:version",
        "packages/mcp/pyproject.toml:version",
    }:
        raise ValueError(
            "Commitizen must version both distributions without changing the virtual root"
        )
    if tag is not None and tag != f"v{version}":
        raise ValueError(f"tag must be v{version}, got {tag!r}")
    root_python = tomllib.loads((root / "pyproject.toml").read_text())["project"]["requires-python"]
    for name, project in packages.items():
        if project["name"] != f"opendart-{name}" or project["requires-python"] != root_python:
            raise ValueError(f"incorrect distribution name or Python requirement for {name}")
    requirements = [Requirement(value) for value in packages["mcp"]["dependencies"]]
    sdk = [
        requirement
        for requirement in requirements
        if canonicalize_name(requirement.name) == "opendart-sdk"
    ]
    current = Version(version)
    bounds = (
        {specifier.operator: specifier.version for specifier in sdk[0].specifier}
        if len(sdk) == 1
        else {}
    )
    compatible = (
        len(sdk) == 1
        and sdk[0].url is None
        and sdk[0].marker is None
        and not sdk[0].extras
        and len(sdk[0].specifier) == len(bounds) == len({">=", "<"})
        and set(bounds) == {">=", "<"}
        and Version(f"{current.major}.{current.minor}.0") <= Version(bounds[">="]) <= current
        and Version(bounds["<"]) == Version(f"{current.major}.{current.minor + 1}.0")
        and sdk[0].specifier.contains(current, prereleases=True)
    )
    if not compatible:
        raise ValueError(
            "MCP must require the compatible SDK release with lower and upper version bounds"
        )
    return version


def check_metadata(content: bytes, project: dict, artifact: str) -> None:
    """Reject distribution metadata that diverges from the source package manifest."""
    metadata = BytesParser().parsebytes(content)
    actual_dependencies = {
        str(Requirement(value)) for value in metadata.get_all("Requires-Dist", [])
    }
    expected_dependencies = {str(Requirement(value)) for value in project["dependencies"]}
    if (
        canonicalize_name(metadata.get("Name", "")) != canonicalize_name(project["name"])
        or metadata["Version"] != project["version"]
        or metadata["Requires-Python"] != project["requires-python"]
        or actual_dependencies != expected_dependencies
    ):
        raise ValueError(f"incorrect metadata or dependencies in {artifact}")


def check_artifacts(dist: Path, version: str, *, root: Path = ROOT) -> None:
    """Require exactly four valid distributions, including metadata, source, and package data."""
    expected = {
        f"opendart_{package}-{version}{suffix}"
        for package in PACKAGES
        for suffix in ("-py3-none-any.whl", ".tar.gz")
    }
    actual = {path.name for path in dist.iterdir() if path.name != ".gitignore"}
    if actual != expected:
        raise ValueError(
            f"release artifacts differ: missing={sorted(expected - actual)}, unexpected={sorted(actual - expected)}"
        )
    for package, project in projects(root).items():
        stem = f"opendart_{package}-{version}"
        wheel = dist / f"{stem}-py3-none-any.whl"
        with ZipFile(wheel) as archive:
            check_metadata(archive.read(f"{stem}.dist-info/METADATA"), project, wheel.name)
            if not ASSETS[package] <= set(archive.namelist()):
                raise ValueError(f"missing package source or data in {wheel.name}")
            if package == "mcp":
                entry_points = archive.read(f"{stem}.dist-info/entry_points.txt").decode()
                if "opendart-mcp = opendart_mcp.server:main" not in entry_points:
                    raise ValueError(f"missing MCP console entry point in {wheel.name}")
        source = dist / f"{stem}.tar.gz"
        with tarfile.open(source) as archive:
            required = {f"{stem}/src/{asset}" for asset in ASSETS[package]}
            required |= {f"{stem}/pyproject.toml", f"{stem}/README.md", f"{stem}/PKG-INFO"}
            members = {member.name: member for member in archive.getmembers()}
            if not required <= members.keys() or any(
                not members[name].isfile() for name in required
            ):
                raise ValueError(f"missing package source or data in {source.name}")
            metadata_file = archive.extractfile(f"{stem}/PKG-INFO")
            if metadata_file is None:
                raise ValueError(f"missing package metadata in {source.name}")
            with metadata_file:
                check_metadata(metadata_file.read(), project, source.name)


def main() -> int:
    """Check source metadata and, when supplied, release artifacts and the proposed tag."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tag", help="Expected release tag, for example v0.1.0")
    parser.add_argument(
        "--dist", type=Path, help="Directory containing exactly the four release artifacts"
    )
    args = parser.parse_args()
    try:
        version = check_sources(ROOT, args.tag)
        if args.dist is not None:
            check_artifacts(args.dist, version)
    except (ValueError, OSError, KeyError, BadZipFile, tarfile.TarError) as exc:
        print(f"release check failed: {exc}", file=sys.stderr)
        return 1
    print(f"release metadata verified: opendart-sdk and opendart-mcp {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
