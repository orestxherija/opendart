#!/usr/bin/env bash
# Resolve an image tag or digest to one immutable digest, pull it, and record it for later steps.
# Usage: resolve_image.sh IMAGE TAG_OR_DIGEST [HINT], where HINT extends the error when nothing is found.
set -euo pipefail

image=${1:?Usage: resolve_image.sh IMAGE TAG_OR_DIGEST [HINT]}
reference=${2:?Usage: resolve_image.sh IMAGE TAG_OR_DIGEST [HINT]}
hint=${3:-}

if [[ $reference == sha256:* ]]; then
  digest=$reference
elif ! digest=$(docker buildx imagetools inspect "$image:$reference" --format '{{json .Manifest}}' |
  jq --raw-output --exit-status '.digest'); then
  echo "::error::No published image for $image:$reference. $hint" >&2
  exit 1
fi
if [[ ! $digest =~ ^sha256:[a-f0-9]{64}$ ]]; then
  echo "::error::Invalid image digest: $digest" >&2
  exit 1
fi
docker pull --quiet "$image@$digest"
if [[ -n ${GITHUB_OUTPUT:-} ]]; then
  printf 'digest=%s\nreference=%s@%s\n' "$digest" "$image" "$digest" >>"$GITHUB_OUTPUT"
fi
echo "Resolved $image:$reference to $digest"
