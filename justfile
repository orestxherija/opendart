mod sdk 'packages/sdk/justfile'
mod mcp 'packages/mcp/justfile'
mod reference 'api_reference/justfile'

# List available commands.
default:
    @just --list

# Install locked workspace and offline test dependencies.
sync:
    uv sync --locked --all-packages --group contracts

# Check every component offline.
check:
    just sdk check
    just mcp check
    just reference check

# Build both Python packages.
build:
    just sdk build
    just mcp build

# Regenerate the reference before the SDK.
generate:
    just reference generate
    just sdk generate
