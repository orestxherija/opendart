"""Tool versions pinned in more than one file stay in step when Renovate updates one of them."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


def setup_action_uv() -> str:
    action = yaml.safe_load((ROOT / ".github/actions/setup/action.yml").read_text())
    [step] = [
        step
        for step in action["runs"]["steps"]
        if step.get("uses", "").startswith("astral-sh/setup-uv@")
    ]
    return step["with"]["version"]


def dockerfile_uv() -> str:
    dockerfile = (ROOT / "packages/mcp/Dockerfile").read_text()
    [version] = re.findall(
        r"^COPY --from=ghcr\.io/astral-sh/uv:([^@\s]+)@sha256:", dockerfile, re.MULTILINE
    )
    return version


def test_ci_and_the_mcp_image_pin_the_same_uv_release() -> None:
    assert dockerfile_uv() == setup_action_uv(), (
        "Update the uv pins in packages/mcp/Dockerfile and .github/actions/setup/action.yml together"
    )
