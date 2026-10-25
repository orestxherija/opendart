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
        "packages/analysis/pyproject.toml",
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
                content = re.sub(
                    r'"opendart-analysis[^"]*"', '"opendart-analysis>=0.2.0,<0.3"', content
                )
            destination.write_text(content)
    return tmp_path


def make_artifacts(
    root: Path, *, omit: str = "", wrong_metadata: str = "", only: str | None = None
) -> Path:
    """Write all six artifacts; `omit` drops one member, `only` limits metadata drift."""
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
                if wrong_metadata == suffix and only in {None, package}
                else metadata
            )
            if suffix.endswith(".whl"):
                with ZipFile(dist / f"{stem}{suffix}", "w") as archive:
                    archive.writestr(f"{stem}.dist-info/METADATA", content)
                    archive.writestr(
                        f"{stem}.dist-info/entry_points.txt",
                        "[console_scripts]\n"
                        if omit == "entry_points.txt"
                        else "[console_scripts]\nopendart-mcp = opendart_mcp.server:main\n",
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
    "file",
    [
        "cz.toml",
        "packages/sdk/pyproject.toml",
        "packages/analysis/pyproject.toml",
        "packages/mcp/pyproject.toml",
    ],
)
def test_drift_in_any_release_version_is_rejected(release_tree, file):
    path = release_tree / file
    path.write_text(path.read_text().replace('version = "0.2.0"', 'version = "0.2.1"'))
    with pytest.raises(ValueError, match="versions must agree"):
        check_sources(release_tree)


def add_dependency(root: Path, package: str, dependency: str) -> None:
    path = root / "packages" / package / "pyproject.toml"
    content = path.read_text()
    assert "dependencies = [" in content
    path.write_text(content.replace("dependencies = [", f'dependencies = ["{dependency}", ', 1))


@pytest.mark.parametrize(("name", "label"), [("sdk", "SDK"), ("analysis", "analysis")])
@pytest.mark.parametrize(
    "dependency",
    [
        "{}",
        "{}>=0.2.0",
        "{}<0.3",
        "{}>=0.3,<0.4",
        "{}>=0.1,<0.3",
        "{}>=0.2,<1",
        "{}>=0.2,<0.3; python_version<'3'",
        "{}[extra]>=0.2,<0.3",
        "{} @ https://example.invalid/package.whl",
    ],
)
def test_unbounded_or_incompatible_mcp_dependencies_are_rejected(
    release_tree, name, label, dependency
):
    path = release_tree / "packages/mcp/pyproject.toml"
    distribution = f"opendart-{name}"
    content = path.read_text()
    assert f"{distribution}>=0.2.0,<0.3" in content
    path.write_text(content.replace(f"{distribution}>=0.2.0,<0.3", dependency.format(distribution)))
    with pytest.raises(ValueError, match=f"MCP must require the compatible {label} release"):
        check_sources(release_tree)


@pytest.mark.parametrize("name", ["sdk", "analysis"])
def test_mcp_must_declare_each_internal_dependency(release_tree, name):
    path = release_tree / "packages/mcp/pyproject.toml"
    content = path.read_text()
    requirement = f'  "opendart-{name}>=0.2.0,<0.3",\n'
    assert requirement in content
    path.write_text(content.replace(requirement, ""))
    with pytest.raises(ValueError, match="MCP must require the compatible"):
        check_sources(release_tree)


def test_duplicate_internal_requirements_are_rejected(release_tree):
    add_dependency(release_tree, "mcp", "opendart-analysis>=0.2.0,<0.3")
    with pytest.raises(ValueError, match="compatible analysis"):
        check_sources(release_tree)


@pytest.mark.parametrize(
    ("package", "dependency", "message"),
    [
        ("analysis", "opendart-sdk", "analysis must not require opendart-sdk"),
        ("analysis", "opendart_mcp", "analysis must not require opendart-mcp"),
        ("sdk", "opendart-analysis", "SDK must not require opendart-analysis"),
        ("sdk", "opendart-mcp", "SDK must not require opendart-mcp"),
        ("mcp", "opendart-mcp", "MCP must not require opendart-mcp"),
    ],
)
def test_undeclared_internal_dependency_edges_are_rejected(
    release_tree, package, dependency, message
):
    # Even a compatible range is forbidden: only MCP's two edges are part of the release graph.
    add_dependency(release_tree, package, f"{dependency}>=0.2.0,<0.3")
    with pytest.raises(ValueError, match=message):
        check_sources(release_tree)


@pytest.mark.parametrize(
    ("package", "dependency", "message"),
    [
        ("analysis", "opendart-sdk", "analysis must not require opendart-sdk through its 'sdk'"),
        ("mcp", "opendart-analysis", "MCP must not require opendart-analysis through its 'sdk'"),
    ],
)
def test_internal_edges_through_extras_are_rejected(release_tree, package, dependency, message):
    path = release_tree / "packages" / package / "pyproject.toml"
    path.write_text(
        f'{path.read_text()}\n[project.optional-dependencies]\nsdk = ["{dependency}>=0.2.0,<0.3"]\n'
    )
    with pytest.raises(ValueError, match=message):
        check_sources(release_tree)


def test_commitizen_cannot_version_the_virtual_root(release_tree):
    path = release_tree / "cz.toml"
    path.write_text(
        path.read_text().replace("packages/sdk/pyproject.toml:version", "pyproject.toml:version")
    )
    with pytest.raises(ValueError, match="virtual root"):
        check_sources(release_tree)


def test_commitizen_must_version_the_analysis_distribution(release_tree):
    path = release_tree / "cz.toml"
    content = path.read_text()
    entry = '"packages/analysis/pyproject.toml:version",'
    assert entry in content
    path.write_text(content.replace(entry, ""))
    with pytest.raises(ValueError, match="all three distributions"):
        check_sources(release_tree)


def test_artifact_set_matches_all_manifests_and_includes_required_assets(release_tree):
    check_artifacts(make_artifacts(release_tree), "0.2.0", root=release_tree)


@pytest.mark.parametrize(
    "artifact", ["opendart_analysis-0.2.0-py3-none-any.whl", "opendart_analysis-0.2.0.tar.gz"]
)
def test_missing_analysis_artifact_is_rejected(release_tree, artifact):
    dist = make_artifacts(release_tree)
    (dist / artifact).unlink()
    with pytest.raises(ValueError, match=re.escape(f"missing=['{artifact}'], unexpected=[]")):
        check_artifacts(dist, "0.2.0", root=release_tree)


@pytest.mark.parametrize(
    "extra", ["opendart_sdk-0.1.0-py3-none-any.whl", "unrelated.txt", ".hidden-wheel"]
)
def test_stale_and_unrelated_artifacts_are_rejected(release_tree, extra):
    dist = make_artifacts(release_tree)
    (dist / extra).touch()
    with pytest.raises(ValueError, match="unexpected="):
        check_artifacts(dist, "0.2.0", root=release_tree)


@pytest.mark.parametrize("only", [None, "analysis"])
@pytest.mark.parametrize("suffix", ["-py3-none-any.whl", ".tar.gz"])
def test_wheel_and_sdist_metadata_drift_is_rejected(release_tree, suffix, only):
    dist = make_artifacts(release_tree, wrong_metadata=suffix, only=only)
    with pytest.raises(ValueError, match="incorrect metadata"):
        check_artifacts(dist, "0.2.0", root=release_tree)


@pytest.mark.parametrize(
    "asset",
    [
        "opendart/py.typed",
        "opendart_analysis/py.typed",
        "opendart_mcp/server.py",
        "src/opendart/py.typed",
        "src/opendart_analysis/__init__.py",
        "README.md",
    ],
)
def test_missing_wheel_or_sdist_assets_are_rejected(release_tree, asset):
    with pytest.raises(ValueError, match="missing package source or data"):
        check_artifacts(make_artifacts(release_tree, omit=asset), "0.2.0", root=release_tree)


def test_missing_mcp_console_entry_point_is_rejected(release_tree):
    dist = make_artifacts(release_tree, omit="entry_points.txt")
    with pytest.raises(ValueError, match="missing MCP console entry point"):
        check_artifacts(dist, "0.2.0", root=release_tree)


def test_commitizen_bumps_all_distributions_without_touching_root_or_git(release_tree):
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
    for package in ("sdk", "analysis", "mcp"):
        project = tomllib.loads(
            (release_tree / "packages" / package / "pyproject.toml").read_text()
        )
        assert project["project"]["version"] == "0.2.1"
    assert check_sources(release_tree, "v0.2.1") == "0.2.1"
    assert subprocess.check_output([git, "tag", "--list"], cwd=release_tree, text=True) == ""  # noqa: S603
