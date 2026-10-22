"""Release gates reject version drift, wrong metadata, and unintended distribution files."""

from __future__ import annotations

import io
import re
import shutil
import subprocess
import sys
import tarfile
import tomllib
from pathlib import Path
from zipfile import ZipFile

import pytest

from scripts.check_release import ASSETS, ROOT, check_artifacts, check_sources, projects


@pytest.fixture
def release_tree(tmp_path: Path) -> Path:
    for relative in (
        "pyproject.toml",
        "cz.toml",
        "packages/sdk/pyproject.toml",
        "packages/mcp/pyproject.toml",
    ):
        destination = tmp_path / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / relative, destination)
        if relative != "pyproject.toml":
            content = re.sub(
                r'^version = "[^"]+"',
                'version = "0.2.0"',
                destination.read_text(),
                flags=re.MULTILINE,
            )
            if relative == "packages/mcp/pyproject.toml":
                content = re.sub(r'"opendart-sdk[^"]*"', '"opendart-sdk>=0.2.0,<0.3"', content)
            destination.write_text(content)
    return tmp_path


def make_artifacts(root: Path, *, omit: str = "", wrong_metadata: str = "") -> Path:
    dist = root / "dist"
    dist.mkdir(exist_ok=True)
    for package, project in projects(root).items():
        stem = f"opendart_{package}-0.2.0"
        metadata = "\n".join(
            [
                "Metadata-Version: 2.4",
                f"Name: {project["name"]}",
                "Version: 0.2.0",
                f"Requires-Python: {project["requires-python"]}",
                *(f"Requires-Dist: {requirement}" for requirement in project["dependencies"]),
                "",
            ]
        ).encode()
        for suffix in ("-py3-none-any.whl", ".tar.gz"):
            content = (
                metadata.replace(b"Version: 0.2.0", b"Version: 9.0.0")
                if wrong_metadata == suffix
                else metadata
            )
            if suffix.endswith(".whl"):
                with ZipFile(dist / f"{stem}{suffix}", "w") as archive:
                    archive.writestr(f"{stem}.dist-info/METADATA", content)
                    archive.writestr(
                        f"{stem}.dist-info/entry_points.txt",
                        "[console_scripts]\nopendart-mcp = opendart_mcp.server:main\n",
                    )
                    for asset in ASSETS[package] - {omit}:
                        archive.writestr(asset, "")
            else:
                with tarfile.open(dist / f"{stem}{suffix}", "w:gz") as archive:
                    files = {f"src/{asset}": b"" for asset in ASSETS[package]}
                    files |= {"pyproject.toml": b"", "README.md": b"", "PKG-INFO": content}
                    for name, value in files.items():
                        if name == omit:
                            continue
                        member = tarfile.TarInfo(f"{stem}/{name}")
                        member.size = len(value)
                        archive.addfile(member, io.BytesIO(value))
    return dist


def test_release_tag_comes_from_distributions_not_virtual_root(release_tree):
    (release_tree / "pyproject.toml").write_text(
        '[project]\nversion = "9.9.9"\nrequires-python = ">=3.14"\n'
    )
    assert check_sources(release_tree, "v0.2.0") == "0.2.0"
    with pytest.raises(ValueError, match="tag must be"):
        check_sources(release_tree, "v9.9.9")


@pytest.mark.parametrize(
    "file", ["cz.toml", "packages/sdk/pyproject.toml", "packages/mcp/pyproject.toml"]
)
def test_drift_in_any_release_version_is_rejected(release_tree, file):
    path = release_tree / file
    path.write_text(path.read_text().replace('version = "0.2.0"', 'version = "0.2.1"'))
    with pytest.raises(ValueError, match="versions must agree"):
        check_sources(release_tree)


@pytest.mark.parametrize(
    "dependency",
    [
        "opendart-sdk",
        "opendart-sdk>=0.2.0",
        "opendart-sdk<0.3",
        "opendart-sdk>=0.3,<0.4",
        "opendart-sdk>=0.1,<0.3",
        "opendart-sdk>=0.2,<1",
        "opendart-sdk>=0.2,<0.3; python_version<'3'",
        "opendart-sdk @ https://example.invalid/sdk.whl",
    ],
)
def test_unbounded_or_incompatible_sdk_dependencies_are_rejected(release_tree, dependency):
    path = release_tree / "packages/mcp/pyproject.toml"
    path.write_text(path.read_text().replace("opendart-sdk>=0.2.0,<0.3", dependency))
    with pytest.raises(ValueError, match="compatible SDK"):
        check_sources(release_tree)


def test_commitizen_cannot_version_the_virtual_root(release_tree):
    path = release_tree / "cz.toml"
    path.write_text(
        path.read_text().replace("packages/sdk/pyproject.toml:version", "pyproject.toml:version")
    )
    with pytest.raises(ValueError, match="virtual root"):
        check_sources(release_tree)


def test_artifact_set_matches_both_manifests_and_includes_required_assets(release_tree):
    check_artifacts(make_artifacts(release_tree), "0.2.0", root=release_tree)


@pytest.mark.parametrize(
    "extra", ["opendart_sdk-0.1.0-py3-none-any.whl", "unrelated.txt", ".hidden-wheel"]
)
def test_stale_and_unrelated_artifacts_are_rejected(release_tree, extra):
    dist = make_artifacts(release_tree)
    (dist / extra).touch()
    with pytest.raises(ValueError, match="unexpected="):
        check_artifacts(dist, "0.2.0", root=release_tree)


@pytest.mark.parametrize("suffix", ["-py3-none-any.whl", ".tar.gz"])
def test_wheel_and_sdist_metadata_drift_is_rejected(release_tree, suffix):
    with pytest.raises(ValueError, match="incorrect metadata"):
        check_artifacts(
            make_artifacts(release_tree, wrong_metadata=suffix), "0.2.0", root=release_tree
        )


@pytest.mark.parametrize(
    "asset", ["opendart/py.typed", "opendart_mcp/server.py", "src/opendart/py.typed", "README.md"]
)
def test_missing_wheel_or_sdist_assets_are_rejected(release_tree, asset):
    with pytest.raises(ValueError, match="missing package source or data"):
        check_artifacts(make_artifacts(release_tree, omit=asset), "0.2.0", root=release_tree)


def test_commitizen_bumps_both_distributions_without_touching_root_or_git(release_tree):
    git = shutil.which("git")
    assert git is not None
    subprocess.run([git, "init", "--quiet", str(release_tree)], check=True)  # noqa: S603 - test-owned repository
    before = (release_tree / "pyproject.toml").read_bytes()
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "commitizen",
            "--config",
            "cz.toml",
            "bump",
            "0.2.1",
            "--version-files-only",
            "--yes",
        ],
        cwd=release_tree,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert (release_tree / "pyproject.toml").read_bytes() == before
    for package in ("sdk", "mcp"):
        project = tomllib.loads(
            (release_tree / "packages" / package / "pyproject.toml").read_text()
        )
        assert project["project"]["version"] == "0.2.1"
    assert check_sources(release_tree, "v0.2.1") == "0.2.1"
    assert subprocess.check_output([git, "tag", "--list"], cwd=release_tree, text=True) == ""  # noqa: S603
