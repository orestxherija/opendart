#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.."

audit_dir="$(mktemp -d)"
readonly audit_dir

cleanup() {
  rm -rf -- "${audit_dir}"
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

# Cover SDK/MCP runtime dependencies, optional extras, and every development group.
# Only local workspace projects are omitted; their third-party dependencies remain.
uv export \
  --locked \
  --all-packages \
  --all-groups \
  --all-extras \
  --format pylock.toml \
  --no-emit-workspace \
  --output-file "${audit_dir}/pylock.toml" >/dev/null

# Reading the lockfile avoids installing or building the packages being audited.
pip-audit --locked "${audit_dir}" "$@"
