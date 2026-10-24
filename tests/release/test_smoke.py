"""Distribution probes isolate package imports and propagate installation/probe failures."""

from __future__ import annotations

import asyncio
import importlib
import os
import subprocess
import sys
from importlib.metadata import PackageNotFoundError
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import smoke_installed
from scripts.check_release import ROOT


@pytest.fixture
def runner(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT / "scripts"))
    module = importlib.import_module("scripts.smoke_distributions")
    monkeypatch.setattr(module, "check_sources", lambda _root: "0.1.0")
    monkeypatch.setattr(module, "check_artifacts", lambda _dist, _version: None)
    return module


@pytest.fixture
def dist(tmp_path: Path) -> Path:
    directory = tmp_path / "dist"
    directory.mkdir()
    for package in ("sdk", "analysis", "mcp"):
        for suffix in ("-py3-none-any.whl", ".tar.gz"):
            (directory / f"opendart_{package}-0.1.0{suffix}").write_text(f"{package}{suffix}")
    return directory


def test_each_installation_choice_gets_a_fresh_environment_and_local_constraints(
    runner, monkeypatch, tmp_path, dist
):
    calls = []
    links = {}
    pins = {}

    def record(command, **kwargs):
        calls.append((command, kwargs))
        if command[:3] == ("uv", "pip", "install"):
            constraints = Path(command[command.index("--constraint") + 1])
            directory = constraints.parent
            names = sorted(path.name for path in directory.iterdir() if path != constraints)
            links.setdefault(directory, names)
            pins.setdefault(directory, constraints.read_text().splitlines())

    monkeypatch.setattr(runner.subprocess, "run", record)
    monkeypatch.setenv("PYTHONPATH", str(ROOT))
    monkeypatch.setenv("PYTHONHOME", str(ROOT))
    monkeypatch.setenv("VIRTUAL_ENV", str(ROOT / ".venv"))
    monkeypatch.setenv("UV_PROJECT_ENVIRONMENT", str(ROOT / ".venv"))
    monkeypatch.setenv("OPENDART_API__API_KEY", "distribution-test-placeholder")
    monkeypatch.setenv("UV_CACHE_DIR", str(tmp_path / "cache"))
    runner.smoke_distributions(dist)

    venvs = [command for command, _ in calls if command[:2] == ("uv", "venv")]
    assert len(venvs) == len({command[2] for command in venvs}) == 6
    environments = {str(options["cwd"]) for _, options in calls}
    assert len(environments) == 6
    assert all(not Path(directory).exists() for directory in environments)

    installs = [command for command, _ in calls if command[:3] == ("uv", "pip", "install")]
    assert len(installs) == 6
    # One link directory per format, holding exactly that format's three artifacts.
    assert sorted(links.values()) == [
        [f"opendart_{package}-0.1.0-py3-none-any.whl" for package in ("analysis", "mcp", "sdk")],
        [f"opendart_{package}-0.1.0.tar.gz" for package in ("analysis", "mcp", "sdk")],
    ]
    # Every workspace name is pinned to a file in the same format's directory.
    for directory, lines in pins.items():
        assert sorted(lines) == sorted(
            f"opendart-{name.split("-")[0].removeprefix("opendart_")} @ {(directory / name).as_uri()}"
            for name in links[directory]
        )
    installed = []
    for command in installs:
        assert "--no-sources" in command
        assert command[-3] == "--constraint"
        artifact = Path(command[-1])
        assert artifact.parent == Path(command[-2]).parent
        # Only the distribution under test is named; its requirements select the others.
        assert [part for part in command if part.endswith((".whl", ".tar.gz"))] == [command[-1]]
        installed.append(artifact.name)
    assert installed == [
        f"opendart_{package}-0.1.0{suffix}"
        for suffix in ("-py3-none-any.whl", ".tar.gz")
        for package in ("sdk", "analysis", "mcp")
    ]

    probes = [command for command, _ in calls if "-I" in command]
    assert [command[command.index("--package") + 1] for command in probes] == [
        "sdk",
        "analysis",
        "mcp",
    ] * 2
    checks = [command for command, _ in calls if command[:3] == ("uv", "pip", "check")]
    assert len(checks) == 6
    for _command, options in calls:
        environment = options["env"]
        assert (
            not {"PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT"}
            & environment.keys()
        )
        assert not any(key.startswith("OPENDART_") for key in environment)
        assert environment["PATH"] == os.environ["PATH"]
        assert environment["UV_CACHE_DIR"] == str(tmp_path / "cache")
        assert options["check"] is True
        assert options["timeout"] > 0
        assert not Path(options["cwd"]).is_relative_to(ROOT)


def test_environment_python_is_the_one_installed_and_probed(runner, monkeypatch, dist):
    calls = []
    monkeypatch.setattr(
        runner.subprocess, "run", lambda command, **kwargs: calls.append((command, kwargs))
    )
    runner.smoke_distributions(dist)
    for start in range(0, len(calls), 4):
        venv, install, check, probe = (command for command, _ in calls[start : start + 4])
        python = install[install.index("--python") + 1]
        assert Path(python).is_relative_to(venv[2])
        assert check[check.index("--python") + 1] == python
        assert probe[:2] == (python, "-I")


def test_failed_install_stops_smoke_without_trying_other_choices(runner, monkeypatch, dist):
    calls = []

    def fail_install(command, **kwargs):
        calls.append((command, kwargs))
        if command[:3] == ("uv", "pip", "install"):
            raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(runner.subprocess, "run", fail_install)
    with pytest.raises(subprocess.CalledProcessError):
        runner.smoke_distributions(dist)
    assert len(calls) == 2
    assert not calls[0][1]["cwd"].exists()


def test_failed_probe_stops_before_the_next_choice(runner, monkeypatch, dist):
    calls = []

    def fail_analysis(command, **kwargs):
        calls.append(command)
        if "--package" in command and command[command.index("--package") + 1] == "analysis":
            raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(runner.subprocess, "run", fail_analysis)
    with pytest.raises(subprocess.CalledProcessError):
        runner.smoke_distributions(dist)
    assert len(calls) == 8
    assert not any("opendart_mcp" in part for command in calls for part in command)


def test_installed_sdk_probe_uses_mocked_http():
    asyncio.run(smoke_installed.check_sdk())


def test_installed_analysis_probe_parses_a_synthetic_filing():
    smoke_installed.check_analysis()


@pytest.mark.parametrize(
    ("package", "absent"),
    [
        ("sdk", {"opendart_analysis", "opendart_mcp", "fastmcp", "mcp"}),
        ("analysis", {"opendart", "opendart_mcp", "fastmcp", "mcp"}),
    ],
)
def test_library_choices_exclude_the_other_library_and_mcp(package, absent):
    assert {module for module, _ in smoke_installed.ABSENT[package]} == absent


def test_absent_packages_are_rejected_without_importing_them(monkeypatch):
    # The workspace environment has every package installed, so each check must fail.
    for module, distribution in smoke_installed.ABSENT["analysis"]:
        with pytest.raises(RuntimeError, match=f"{module} must not be importable"):
            smoke_installed.check_absent(((module, distribution),))
    monkeypatch.setattr(smoke_installed, "find_spec", lambda _module: None)
    with pytest.raises(RuntimeError, match="opendart-sdk must not be installed"):
        smoke_installed.check_absent((("opendart", "opendart-sdk"),))


def isolated(monkeypatch, package: str, *, flag: bool = True) -> None:
    monkeypatch.setattr(
        sys, "argv", ["smoke_installed.py", "--version", "0.1.0", "--package", package]
    )
    monkeypatch.setattr(
        smoke_installed, "sys", SimpleNamespace(flags=SimpleNamespace(isolated=flag))
    )


def test_installed_probe_rejects_nonisolated_interpreter(monkeypatch):
    isolated(monkeypatch, "sdk", flag=False)
    with pytest.raises(RuntimeError, match="python -I"):
        smoke_installed.main()


@pytest.mark.parametrize(
    ("package", "distribution"),
    [("sdk", "opendart-sdk"), ("analysis", "opendart-analysis"), ("mcp", "opendart-sdk")],
)
def test_installed_probe_rejects_wrong_distribution_version(monkeypatch, package, distribution):
    isolated(monkeypatch, package)
    monkeypatch.setattr(smoke_installed, "version", lambda _package: "9.9.9")
    with pytest.raises(RuntimeError, match=f"Wrong {distribution} distribution version"):
        smoke_installed.main()


def test_installed_probe_requires_every_distribution_for_mcp(monkeypatch):
    isolated(monkeypatch, "mcp")
    monkeypatch.setattr(
        smoke_installed,
        "version",
        lambda package: "9.9.9" if package == "opendart-analysis" else "0.1.0",
    )
    with pytest.raises(RuntimeError, match="Wrong opendart-analysis distribution version"):
        smoke_installed.main()


def test_installed_probe_reports_a_missing_mcp_requirement(monkeypatch):
    # MCP metadata without opendart-analysis leaves it uninstalled in the fresh environment.
    isolated(monkeypatch, "mcp")

    def version(package):
        if package == "opendart-analysis":
            raise PackageNotFoundError(package)
        return "0.1.0"

    monkeypatch.setattr(smoke_installed, "version", version)
    with pytest.raises(RuntimeError, match="opendart-analysis is not installed"):
        smoke_installed.main()


def test_installed_sdk_choice_rejects_workspace_extras(monkeypatch):
    # The workspace environment contains analysis and MCP, which the SDK choice must lack.
    isolated(monkeypatch, "sdk")
    monkeypatch.setattr(smoke_installed, "version", lambda _package: "0.1.0")
    with pytest.raises(RuntimeError, match="opendart_analysis must not be importable"):
        smoke_installed.main()
