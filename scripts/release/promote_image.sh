#!/usr/bin/env bash
# Point tags at one verified image digest without rebuilding.
#
# The main tag never moves to an older commit: it stays put when it already refers to a newer
# default-branch commit. A release tag (vX.Y.Z) never moves once it has been published.
# Usage: promote_image.sh IMAGE DIGEST TAG...
set -euo pipefail

usage="Usage: promote_image.sh IMAGE DIGEST TAG..."
image=${1:?$usage}
digest=${2:?$usage}
shift 2
if [[ $# -eq 0 ]]; then
  echo "$usage" >&2
  exit 2
fi
if [[ ! $digest =~ ^sha256:[a-f0-9]{64}$ ]]; then
  echo "::error::Invalid image digest: $digest" >&2
  exit 1
fi

tag_digest() {
  docker buildx imagetools inspect "$image:$1" --format '{{json .Manifest}}' 2>/dev/null |
    jq --raw-output --exit-status '.digest'
}

# Move main when it is missing, unreadable, rewritten away, or an ancestor of this commit.
main_may_move() {
  local config revision
  config=$(docker buildx imagetools inspect "$image:main" --format '{{json .Image}}' 2>/dev/null) || return 0
  revision=$(jq --raw-output 'if has("config") then . else .["linux/amd64"] end
    | .config.Labels["org.opencontainers.image.revision"] // empty' <<<"$config") || return 0
  [[ -n $revision ]] || return 0
  git cat-file -e "$revision^{commit}" 2>/dev/null || return 0
  git merge-base --is-ancestor "$revision" HEAD
}

tags=()
for tag in "$@"; do
  case $tag in
    main)
      if main_may_move; then
        tags+=("$tag")
      else
        echo "::notice::main already refers to a newer commit; leaving it unchanged."
      fi
      ;;
    v[0-9]*)
      if released=$(tag_digest "$tag") && [[ $released != "$digest" ]]; then
        echo "::error::$image:$tag already refers to $released, not $digest." >&2
        exit 1
      fi
      tags+=("$tag")
      ;;
    *)
      tags+=("$tag")
      ;;
  esac
done
if [[ ${#tags[@]} -eq 0 ]]; then
  echo "No tags to promote."
  exit 0
fi

arguments=()
for tag in "${tags[@]}"; do
  arguments+=(--tag "$image:$tag")
done
docker buildx imagetools create --prefer-index=false "${arguments[@]}" "$image@$digest"
for tag in "${tags[@]}"; do
  if [[ $(tag_digest "$tag") != "$digest" ]]; then
    echo "::error::$image:$tag does not refer to $digest after promotion." >&2
    exit 1
  fi
done
if [[ -n ${GITHUB_STEP_SUMMARY:-} ]]; then
  {
    printf "Promoted \`%s@%s\` to:\n\n" "$image" "$digest"
    for tag in "${tags[@]}"; do
      printf -- "- \`%s:%s\`\n" "$image" "$tag"
    done
  } >>"$GITHUB_STEP_SUMMARY"
fi
