#!/usr/bin/env bash
# Verify the signed SBOM and provenance of the DHI base images pinned in the MCP Dockerfile,
# using Docker's public key. Scout reads DOCKER_SCOUT_HUB_USER and DOCKER_SCOUT_HUB_PASSWORD.
set -euo pipefail

version=1.27.0
checksum=815207e27559fd3d7dddfe778e86f0aeb823eeb24b3cd79d00bc5cd8dfd0724d
dockerfile=packages/mcp/Dockerfile

work=$(mktemp -d "${RUNNER_TEMP:-/tmp}/docker-scout.XXXXXX")
trap 'rm -rf -- "$work"' EXIT
curl --fail --silent --show-error --location --retry 3 --proto '=https' --proto-redir '=https' \
  "https://github.com/docker/scout-cli/releases/download/v$version/docker-scout_${version}_linux_amd64.tar.gz" \
  --output "$work/scout.tar.gz"
printf '%s  %s\n' "$checksum" "$work/scout.tar.gz" | sha256sum --check --strict --quiet
tar -xzf "$work/scout.tar.gz" -C "$work" docker-scout

mapfile -t images < <(awk '$1 == "FROM" && $2 ~ /^dhi[.]io\// {print $2}' "$dockerfile")
if [[ ${#images[@]} -ne 2 ]]; then
  echo "::error::Expected two DHI base images in $dockerfile, found ${#images[@]}." >&2
  exit 1
fi
for image in "${images[@]}"; do
  if [[ ! $image =~ @sha256:[a-f0-9]{64}$ ]]; then
    echo "::error::$image is not pinned by digest." >&2
    exit 1
  fi
  for predicate in https://scout.docker.com/sbom/v0.1 https://slsa.dev/provenance/v1; do
    # DHI may omit Rekor records, so skip only the transparency log, as Docker documents.
    "$work/docker-scout" attest get "registry://$image" --platform linux/amd64 \
      --predicate-type "$predicate" --verify --skip-tlog --output "$work/attestation.json"
    jq --exit-status --arg predicate "$predicate" \
      '.predicateType == $predicate and (.subject | length > 0)' "$work/attestation.json" >/dev/null
  done
  echo "Verified SBOM and provenance for $image"
done
