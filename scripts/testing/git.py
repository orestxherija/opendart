"""Tests that run Git in temporary repositories must never reach the checkout that runs them."""

from __future__ import annotations

import pytest

# Git hooks export these. In a linked worktree they are absolute, so a test's `git init` or
# `git config` would rewrite the real repository's index and shared configuration.
REPOSITORY_VARIABLES = (
    "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    "GIT_COMMON_DIR",
    "GIT_DIR",
    "GIT_INDEX_FILE",
    "GIT_NAMESPACE",
    "GIT_OBJECT_DIRECTORY",
    "GIT_PREFIX",
    "GIT_WORK_TREE",
)


@pytest.fixture(autouse=True)
def isolate_git_repository(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make Git discover each test's own repository, as it does outside a hook."""
    for name in REPOSITORY_VARIABLES:
        monkeypatch.delenv(name, raising=False)
