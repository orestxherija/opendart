#!/usr/bin/env bash
# Check that a release tag matches the opendart-mcp version and marks a default-branch commit.
# Usage: check_release_tag.sh TAG DEFAULT_BRANCH
set -euo pipefail

tag=${1:?Usage: check_release_tag.sh TAG DEFAULT_BRANCH}
default_branch=${2:?Usage: check_release_tag.sh TAG DEFAULT_BRANCH}

if [[ ! $tag =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "::error::Release tags use vX.Y.Z; got $tag." >&2
  exit 1
fi
version=$(python3 -c 'import pathlib, tomllib
print(tomllib.loads(pathlib.Path("packages/mcp/pyproject.toml").read_text())["project"]["version"])')
if [[ v$version != "$tag" ]]; then
  echo "::error::Tag $tag does not match opendart-mcp version $version." >&2
  exit 1
fi
commit=$(git rev-parse HEAD)
if ! git merge-base --is-ancestor "$commit" "origin/$default_branch"; then
  echo "::error::Tag a commit on $default_branch; $commit is not in its history." >&2
  exit 1
fi
if [[ -n ${GITHUB_OUTPUT:-} ]]; then
  printf 'commit=%s\n' "$commit" >>"$GITHUB_OUTPUT"
fi
echo "Release $tag marks $default_branch commit $commit"
