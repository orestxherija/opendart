#!/usr/bin/env bash
# Exercise an MCP image's restricted runtime, a file-mounted synthetic key, and HTTP transport security.
# Usage: check_mcp_container.sh IMAGE, where IMAGE is an already pulled tag or digest reference.
set -euo pipefail

export OPENDART_MCP_IMAGE=${1:?Usage: check_mcp_container.sh IMAGE}
compose=(docker compose -f packages/mcp/docker-compose.yml)
secret_directory=$(mktemp -d "${RUNNER_TEMP:-/tmp}/mcp-secret.XXXXXX")
cleanup() {
  "${compose[@]}" down --remove-orphans >/dev/null 2>&1 || true
  rm -rf -- "$secret_directory"
}
trap cleanup EXIT

echo "::group::Runtime without a key"
"${compose[@]}" run --rm --no-deps -T mcp python - <scripts/mcp/check_mcp_runtime.py
echo "::endgroup::"

echo "::group::File-mounted synthetic key"
# A visible placeholder exercises permissions and loading without an API call.
export OPENDART_API_KEY_FILE="$secret_directory/api-key"
printf '%040d\n' 0 >"$OPENDART_API_KEY_FILE"
chmod 0444 "$OPENDART_API_KEY_FILE"
"${compose[@]}" -f packages/mcp/compose.secrets.yml run --rm --no-deps -T mcp \
  python - --require-secret <scripts/mcp/check_mcp_runtime.py
unset OPENDART_API_KEY_FILE
echo "::endgroup::"

echo "::group::MCP protocol and hostile headers"
"${compose[@]}" up --detach --wait --wait-timeout 60 mcp
uv run --no-sync python scripts/mcp/check_mcp.py --url http://127.0.0.1:8000/mcp
echo "::endgroup::"
