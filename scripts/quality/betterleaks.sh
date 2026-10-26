#!/usr/bin/env bash
# Run the same checksum-verified Betterleaks release in local hooks and CI.
set -euo pipefail

version=1.7.4
case "$(uname -s)/$(uname -m)" in
  Darwin/arm64)
    platform=darwin_arm64
    checksum=9d68ab4a009a26f3f35131f321ddff11e53aaa5608a1633308836a802fe2f732
    ;;
  Darwin/x86_64)
    platform=darwin_x64
    checksum=36afd22f9cfc90c1de83a9fd4a6181e3d9a7ca473783bcfed826998a64029e11
    ;;
  Linux/aarch64 | Linux/arm64)
    platform=linux_arm64
    checksum=038d8379935fb6699e12c2c95d0d4901a1ef420cbc553b7c4d4710570d03024e
    ;;
  Linux/x86_64)
    platform=linux_x64
    checksum=9ed7739a39a26a2217f38726bff8a8f4fe079d3b21272caa7959823ccc444d96
    ;;
  *)
    echo "Betterleaks supports macOS and Linux on arm64 or x86_64." >&2
    exit 2
    ;;
esac

repository_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd)
# Override only the cache location; the release and trusted digests stay pinned.
cache_root=${BETTERLEAKS_CACHE_DIR:-"$repository_root/.cache/betterleaks"}
install_dir="$cache_root/$version-$platform"
binary="$install_dir/betterleaks"

if [[ ! -x "$binary" ]]; then
  (
    mkdir -p -- "$install_dir"
    temporary_dir=$(mktemp -d "$install_dir/download.XXXXXX")
    trap 'rm -rf -- "$temporary_dir"' EXIT
    archive="betterleaks_${version}_${platform}.tar.gz"
    # Digests come from the immutable upstream v1.7.4 release's checksums.txt.
    curl --fail --silent --show-error --location --retry 3 \
      --connect-timeout 10 --max-time 120 --proto '=https' --proto-redir '=https' \
      "https://github.com/betterleaks/betterleaks/releases/download/v$version/$archive" \
      --output "$temporary_dir/$archive"
    if command -v sha256sum >/dev/null 2>&1; then
      actual_checksum=$(sha256sum "$temporary_dir/$archive")
    else
      actual_checksum=$(shasum -a 256 "$temporary_dir/$archive")
    fi
    if [[ "${actual_checksum%% *}" != "$checksum" ]]; then
      echo "Betterleaks archive checksum mismatch; refusing to install." >&2
      exit 1
    fi
    tar -xzf "$temporary_dir/$archive" -C "$temporary_dir" betterleaks
    chmod 755 "$temporary_dir/betterleaks"
    mv -f -- "$temporary_dir/betterleaks" "$binary"
  )
fi

exec "$binary" "$@"
