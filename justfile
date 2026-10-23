mod sdk 'packages/sdk/justfile'
mod mcp 'packages/mcp/justfile'
mod reference 'scripts/api_reference/justfile'

# List available commands.
default:
    @just --list

# Install locked workspace and offline test dependencies.
sync:
    uv sync --locked --all-packages --group contracts

# Check repository quality and every component's offline suite.
check:
    just quality
    just release-check
    just sdk check
    just mcp check
    just reference check

# Check file integrity, repository style, workflow security, and file lengths.
quality:
    .venv/bin/prek run --group builtin --require-group ci --all-files --stage pre-commit
    .venv/bin/ruff check
    .venv/bin/ruff format --check
    .venv/bin/prek run markdownlint-cli2 yamllint taplo-format typos loq --all-files --stage pre-commit
    .venv/bin/prek run taplo-lint --all-files --stage pre-push
    .venv/bin/prek run zizmor --all-files --stage pre-commit

# Audit all locked Python dependencies against current vulnerability advisories.
audit:
    .venv/bin/prek run pip-audit --all-files --stage pre-push

# Scan all local Git history with redacted output.
secrets:
    bash scripts/betterleaks.sh git --config=betterleaks.toml --redact --log-opts=--all

# Audit documentation links, including external sites.
links:
    .venv/bin/prek run lychee --all-files --stage pre-push --verbose

# Build both Python packages.
build:
    just sdk build
    just mcp build

# Validate coordinated package versions and release-checker regression tests.
release-check:
    uv run --no-sync python scripts/check_release.py
    uv run --no-sync pytest tests/release --no-cov --html=.cache/pytest/release-report.html -o cache_dir=.cache/pytest/release

# Build and validate both formats, then smoke-test isolated installations.
release-build:
    just release-check
    uv build --all-packages --no-sources
    uv run --no-sync python scripts/check_release.py --dist dist
    uv run --no-sync twine check --strict dist/*
    .venv/bin/python scripts/smoke_distributions.py

# Regenerate the reference, then the SDK and the MCP registry built from it.
generate:
    just reference generate
    just sdk generate
    just mcp generate
