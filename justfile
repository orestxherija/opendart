mod sdk 'packages/sdk/justfile'
mod analysis 'packages/analysis/justfile'
mod mcp 'packages/mcp/justfile'
mod reference 'scripts/api_reference/justfile'
mod ci '.github/justfile'

release_files := 'scripts/check_release.py scripts/smoke_distributions.py scripts/smoke_installed.py tests/release'

# List available commands.
default:
    @just --list

# Install locked workspace and offline test dependencies.
sync:
    uv sync --locked --all-packages --group contracts

# Check repository quality and every component's offline suite.
check:
    just quality
    just boundaries
    just release-check
    just sdk check
    just analysis check
    just mcp check
    just reference check
    just ci test

# Check file integrity, style, shell scripts, workflows, spelling, and file lengths.
quality:
    .venv/bin/prek run --group builtin --require-group ci --all-files --stage pre-commit
    .venv/bin/ruff check
    .venv/bin/ruff format --check
    .venv/bin/prek run markdownlint-cli2 yamllint taplo-format shellcheck shfmt actionlint typos loq --all-files --stage pre-commit
    .venv/bin/prek run taplo-lint --all-files --stage pre-push

# Check that analysis and the SDK never import each other or MCP; needs the synced workspace.
boundaries:
    uv run --no-sync lint-imports --config importlinter.toml --no-cache

# Audit workflows with Zizmor and locked Python dependencies against current advisories.
audit:
    .venv/bin/prek run zizmor --all-files --stage pre-commit
    .venv/bin/prek run pip-audit --all-files --stage pre-push

# Scan all local Git history with redacted output.
secrets:
    bash scripts/betterleaks.sh git --config=betterleaks.toml --redact --log-opts=--all

# Audit documentation links, including external sites.
links:
    .venv/bin/prek run lychee --all-files --stage pre-push --verbose

# Build every Python package.
build:
    just sdk build
    just analysis build
    just mcp build

# Check release tooling, coordinated package versions, and release-checker regression tests.
release-check:
    uv run --no-sync ruff check {{ release_files }}
    uv run --no-sync ruff format --check {{ release_files }}
    uv run --no-sync python scripts/check_release.py
    uv run --no-sync pytest tests/release --no-cov --html=.cache/pytest/release-report.html -o cache_dir=.cache/pytest/release

# Build both formats, validate their metadata, and smoke-test isolated installations.
release-dist:
    uv build --all-packages --no-sources
    uv run --no-sync python scripts/check_release.py --dist dist
    uv run --no-sync twine check --strict dist/*
    .venv/bin/python scripts/smoke_distributions.py

# Run the release checks, then build and smoke-test the distributions.
release-build: release-check release-dist

# Regenerate the reference, then the SDK and the MCP registry built from it.
generate:
    just reference generate
    just sdk generate
    just mcp generate
