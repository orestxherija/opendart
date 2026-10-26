#!/usr/bin/env bash
# Install a pinned, checksum-verified Aikido Safe Chain release for CI.
set -euo pipefail

version=1.5.25
checksum=83069f6db4215cccf6a26bdd6e65a5c2366b9d24322b2d5d2862d47385e56682

installer=$(mktemp "${RUNNER_TEMP:-/tmp}/install-safe-chain.XXXXXX")
trap 'rm -f -- "$installer"' EXIT
curl --fail --silent --show-error --location --retry 3 --proto '=https' --proto-redir '=https' \
  "https://github.com/AikidoSec/safe-chain/releases/download/$version/install-safe-chain.sh" \
  --output "$installer"
printf '%s  %s\n' "$checksum" "$installer" | sha256sum --check --strict --quiet
sh "$installer" --ci
