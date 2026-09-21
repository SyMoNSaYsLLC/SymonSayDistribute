#!/usr/bin/env bash
# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
# SyMoNsAyLeaRn — SyMoNeuRaL, a subdivision of SymonSaysLLC. Terms: see LICENSE.
#
# acquire.sh — put the release asset pin.json names on disk, verified, read-only.
#
#   acquire.sh            fetch the pinned asset if it is not on disk, verify, unpack, install
#   acquire.sh --check    verify what is on disk against the pin; fetch nothing; non-zero on drift
#
# Never "latest". The tag, the asset name, both sha256 values, the licence checksum and the
# commit the binary must report all come from pin.json. The tarball stays beside the binary so
# a reinstall on this host needs no network.
set -euo pipefail

HERE=$(cd -- "$(dirname -- "$(readlink -f "${BASH_SOURCE[0]}")")" && pwd)
PIN=${SYM_GITHUB_PIN:-$HERE/pin.json}
INST=${SYM_GITHUB_INSTALL:-${HOME:?}/.local/share/symoneural/github-mcp-server}
CHECK=0; [ "${1:-}" = "--check" ] && CHECK=1

die() { echo "acquire.sh: $1" >&2; exit "${2:-1}"; }
[ -r "$PIN" ] || die "pin missing: $PIN" 78

read -r TAG REPO ASSET ASSET_SHA CHECKSUMS BIN_SHA COMMIT LIC_MD5 < <(python3 - "$PIN" <<'PY'
import json, sys
p = json.load(open(sys.argv[1])); r = p["release"]
print(p["nearest_tag"], r["repo"], r["asset"], r["asset_sha256"], r["checksums_file"],
      r["binary_sha256"], p["commit_sha"], p["license_md5"])
PY
)
DEST="$INST/$TAG"
mkdir -p "$DEST"

if [ ! -f "$DEST/$ASSET" ]; then
  [ $CHECK = 1 ] && die "asset not on disk: $DEST/$ASSET" 66
  echo "fetching $REPO $TAG $ASSET"
  gh release download "$TAG" --repo "$REPO" --pattern "$ASSET" --pattern "$CHECKSUMS" --dir "$DEST"
fi

echo "$ASSET_SHA  $DEST/$ASSET" | sha256sum -c - >/dev/null || die "asset sha256 drift" 70
if [ -f "$DEST/$CHECKSUMS" ]; then
  UP=$(awk -v a="$ASSET" '$2==a{print $1}' "$DEST/$CHECKSUMS")
  [ "$UP" = "$ASSET_SHA" ] || die "upstream checksums file disagrees with the pin ($UP)" 70
fi

if [ ! -x "$DEST/github-mcp-server" ]; then
  [ $CHECK = 1 ] && die "binary not unpacked" 66
  tar -xzf "$DEST/$ASSET" -C "$DEST" github-mcp-server LICENSE README.md
fi
echo "$BIN_SHA  $DEST/github-mcp-server" | sha256sum -c - >/dev/null || die "binary sha256 drift" 70
[ "$(md5sum "$DEST/LICENSE" | cut -d' ' -f1)" = "$LIC_MD5" ] || die "licence text drift" 70
GOT=$("$DEST/github-mcp-server" --version 2>/dev/null | awk '/^Commit:/{print $2}')
[ "$GOT" = "$COMMIT" ] || die "binary reports commit ${GOT:-none}; pin says $COMMIT" 70

if [ $CHECK = 0 ]; then
  chmod 0555 "$DEST/github-mcp-server"
  chmod 0444 "$DEST/$ASSET" "$DEST/LICENSE" "$DEST/README.md"
  [ -f "$DEST/$CHECKSUMS" ] && chmod 0444 "$DEST/$CHECKSUMS"
fi
echo "ok $TAG commit $COMMIT sha256 $BIN_SHA at $DEST"
