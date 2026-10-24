#!/usr/bin/env python3
"""Validate coordinated SDK/analysis/MCP versions, dependency edges, and the release artifacts."""

from __future__ import annotations

import argparse
import sys
import tarfile
import tomllib
from dataclasses import dataclass
from email.parser import BytesParser
from pathlib import Path
from zipfile import BadZipFile, ZipFile

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

ROOT = Path(__file__).resolve().parents[1]
SUFFIXES = ("-py3-none-any.whl", ".tar.gz")


@dataclass(frozen=True)
class Package:
    """A publishable workspace distribution and the release facts checked for it.

    Attributes:
        name (str): Directory under ``packages/``; the distribution is ``opendart-<name>``.
        label (str): Name used in error messages.
        assets (frozenset[str]): Files every wheel and, under ``src/``, every sdist must contain.
        requires (tuple[str, ...]): Workspace packages this one must require with compatible
            bounds. Every other workspace requirement is forbidden.
        entry_points (tuple[str, ...]): Lines the wheel's ``entry_points.txt`` must contain.
    """

    name: str
    label: str
    assets: frozenset[str]
    requires: tuple[str, ...] = ()
    entry_points: tuple[str, ...] = ()

    @property
    def distribution(self) -> str:
        """Return the published distribution name."""
        return f"opendart-{self.name}"


PACKAGES = (
    Package(
        "sdk",
        "SDK",
        frozenset({"opendart/__init__.py", "opendart/client.py", "opendart/py.typed"}),
    ),
    # Analysis receives bytes, records, and callbacks, so it never requires the SDK or MCP.
    Package(
        "analysis",
        "analysis",
        frozenset({"opendart_analysis/__init__.py", "opendart_analysis/py.typed"}),
    ),
    Package(
        "mcp",
        "MCP",
        frozenset({"opendart_mcp/__init__.py", "opendart_mcp/server.py"}),
        requires=("sdk", "analysis"),
        entry_points=("opendart-mcp = opendart_mcp.server:main",),
    ),
)
BY_NAME = {package.name: package for package in PACKAGES}
ASSETS = {package.name: package.assets for package in PACKAGES}


def projects(root: Path) -> dict:
    """Read the publishable project tables, keyed by package name."""
    return {
        package.name: tomllib.loads(
            (root / "packages" / package.name / "pyproject.toml").read_text()
        )["project"]
        for package in PACKAGES
    }


def compatible(requirements: list[Requirement], current: Version) -> bool:
    """Accept one plain `>=X.Y.a,<X.(Y+1).0` requirement that contains the current release."""
    if len(requirements) != 1:
        return False
    (requirement,) = requirements
    bounds = {specifier.operator: specifier.version for specifier in requirement.specifier}
    return (
        requirement.url is None
        and requirement.marker is None
        and not requirement.extras
        and len(requirement.specifier) == len(bounds) == len({">=", "<"})
        and set(bounds) == {">=", "<"}
        and Version(f"{current.major}.{current.minor}.0") <= Version(bounds[">="]) <= current
        and Version(bounds["<"]) == Version(f"{current.major}.{current.minor + 1}.0")
        and requirement.specifier.contains(current, prereleases=True)
    )


def check_edges(packages: dict, current: Version) -> None:
    """Require each declared workspace dependency edge and forbid every undeclared one."""
    internal = {canonicalize_name(package.distribution): package for package in PACKAGES}
    for package in PACKAGES:
        found: dict[str, list[Requirement]] = {}
        for value in packages[package.name]["dependencies"]:
            requirement = Requirement(value)
            dependency = internal.get(canonicalize_name(requirement.name))
            if dependency is not None:
                found.setdefault(dependency.name, []).append(requirement)
        for name in sorted(found.keys() - set(package.requires)):
            raise ValueError(f"{package.label} must not require {BY_NAME[name].distribution}")
        for name in package.requires:
            if not compatible(found.get(name, []), current):
                raise ValueError(
                    f"{package.label} must require the compatible {BY_NAME[name].label} release"
                    " with lower and upper version bounds"
                )


def check_sources(root: Path, tag: str | None = None) -> str:
    """Return the coordinated release version; the virtual workspace root is independent."""
    packages = projects(root)
    release = tomllib.loads((root / "cz.toml").read_text())["tool"]["commitizen"]
    version = str(Version(packages[PACKAGES[0].name]["version"]))
    if (
        any(packages[package.name]["version"] != version for package in PACKAGES)
        or release.get("version") != version
    ):
        raise ValueError("SDK, analysis, MCP, and Commitizen release versions must agree")
    if release.get("version_provider") != "commitizen" or set(release.get("version_files", [])) != {
        f"packages/{package.name}/pyproject.toml:version" for package in PACKAGES
    }:
        raise ValueError(
            "Commitizen must version all three distributions without changing the virtual root"
        )
    if tag is not None and tag != f"v{version}":
        raise ValueError(f"tag must be v{version}, got {tag!r}")
    root_python = tomllib.loads((root / "pyproject.toml").read_text())["project"]["requires-python"]
    for package in PACKAGES:
        project = packages[package.name]
        if project["name"] != package.distribution or project["requires-python"] != root_python:
            raise ValueError(
                f"incorrect distribution name or Python requirement for {package.name}"
            )
    check_edges(packages, Version(version))
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
    """Require exactly six valid distributions, including metadata, source, and package data."""
    expected = {
        f"opendart_{package.name}-{version}{suffix}" for package in PACKAGES for suffix in SUFFIXES
    }
    actual = {path.name for path in dist.iterdir() if path.name != ".gitignore"}
    if actual != expected:
        raise ValueError(
            f"release artifacts differ: missing={sorted(expected - actual)}, unexpected={sorted(actual - expected)}"
        )
    manifests = projects(root)
    for package in PACKAGES:
        project = manifests[package.name]
        stem = f"opendart_{package.name}-{version}"
        wheel = dist / f"{stem}-py3-none-any.whl"
        with ZipFile(wheel) as archive:
            check_metadata(archive.read(f"{stem}.dist-info/METADATA"), project, wheel.name)
            if not package.assets <= set(archive.namelist()):
                raise ValueError(f"missing package source or data in {wheel.name}")
            if package.entry_points:
                entry_points = archive.read(f"{stem}.dist-info/entry_points.txt").decode()
                if not all(line in entry_points.splitlines() for line in package.entry_points):
                    raise ValueError(f"missing {package.label} console entry point in {wheel.name}")
        source = dist / f"{stem}.tar.gz"
        with tarfile.open(source) as archive:
            required = {f"{stem}/src/{asset}" for asset in package.assets}
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
        "--dist", type=Path, help="Directory containing exactly the six release artifacts"
    )
    args = parser.parse_args()
    try:
        version = check_sources(ROOT, args.tag)
        if args.dist is not None:
            check_artifacts(args.dist, version)
    except (ValueError, OSError, KeyError, BadZipFile, tarfile.TarError) as exc:
        print(f"release check failed: {exc}", file=sys.stderr)
        return 1
    names = ", ".join(package.distribution for package in PACKAGES[:-1])
    print(f"release metadata verified: {names}, and {PACKAGES[-1].distribution} {version}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
