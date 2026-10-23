"""Load scripts/generate_mcp_registry.py so tests can call its pure functions."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from types import ModuleType

ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture(scope="session")
def generator() -> ModuleType:
    """The registry generator module, imported by path."""
    path = ROOT / "scripts/generate_mcp_registry.py"
    spec = importlib.util.spec_from_file_location("generate_mcp_registry", path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def built(generator: ModuleType) -> list[dict]:
    """Service descriptions built from the checked-in catalog and OpenAPI reference."""
    return generator.build()
