"""Distribution probes isolate package imports and propagate installation/probe failures."""

from __future__ import annotations

import asyncio
import importlib
import os
import subprocess
import sys
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


def test_distribution_installs_are_isolated_and_both_formats_use_local_sdk(
    runner, monkeypatch, tmp_path
):
    calls = []
    monkeypatch.setattr(
        runner.subprocess, "run", lambda command, **kwargs: calls.append((command, kwargs))
    )
    monkeypatch.setenv("PYTHONPATH", str(ROOT))
    monkeypatch.setenv("PYTHONHOME", str(ROOT))
    monkeypatch.setenv("VIRTUAL_ENV", str(ROOT / ".venv"))
    monkeypatch.setenv("UV_PROJECT_ENVIRONMENT", str(ROOT / ".venv"))
    monkeypatch.setenv("OPENDART_API__API_KEY", "distribution-test-placeholder")
    monkeypatch.setenv("UV_CACHE_DIR", str(tmp_path / "cache"))
    runner.smoke_distributions(tmp_path)
    environments = {str(options["cwd"]) for _, options in calls}
    assert len(environments) == 2
    assert all(not Path(directory).exists() for directory in environments)
    probes = [command for command, _ in calls if "-I" in command]
    assert len(probes) == 4
    assert sum("--sdk-only" in command for command in probes) == 2
    installs = [command for command, _ in calls if command[:3] == ("uv", "pip", "install")]
    assert len(installs) == 4
    for command, options in calls:
        environment = options["env"]
        assert (
            not {"PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT"}
            & environment.keys()
        )
        assert not any(key.startswith("OPENDART_") for key in environment)
        assert environment["PATH"] == os.environ["PATH"]
        assert environment["UV_CACHE_DIR"] == str(tmp_path / "cache")
        assert options["check"] is True
        if command in installs and "opendart_mcp" in command[-1]:
            assert "opendart_sdk" in command[-2]
            assert command[-1].endswith(".whl") == command[-2].endswith(".whl")


def test_failed_install_stops_smoke_without_trying_other_formats(runner, monkeypatch, tmp_path):
    calls = []

    def fail_install(command, **kwargs):
        calls.append((command, kwargs))
        if command[:3] == ("uv", "pip", "install"):
            raise subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(runner.subprocess, "run", fail_install)
    with pytest.raises(subprocess.CalledProcessError):
        runner.smoke_distributions(tmp_path)
    assert len(calls) == 2
    assert not calls[0][1]["cwd"].exists()


def test_installed_sdk_probe_uses_mocked_http():
    asyncio.run(smoke_installed.check_sdk())


def test_installed_probe_rejects_nonisolated_interpreter(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["smoke_installed.py", "--version", "0.1.0", "--sdk-only"])
    monkeypatch.setattr(
        smoke_installed, "sys", SimpleNamespace(flags=SimpleNamespace(isolated=False))
    )
    with pytest.raises(RuntimeError, match="python -I"):
        smoke_installed.main()


def test_installed_probe_rejects_wrong_distribution_version(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["smoke_installed.py", "--version", "0.1.0", "--sdk-only"])
    monkeypatch.setattr(
        smoke_installed, "sys", SimpleNamespace(flags=SimpleNamespace(isolated=True))
    )
    monkeypatch.setattr(smoke_installed, "version", lambda _package: "9.9.9")
    with pytest.raises(RuntimeError, match="Wrong SDK distribution version"):
        smoke_installed.main()
