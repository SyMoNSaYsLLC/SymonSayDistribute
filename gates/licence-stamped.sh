#!/usr/bin/env bash
# one-line: every branch carries the LICENSE its tree requires
# staged: no — asks which of the four trees a directory is in
# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
#
# The four trees carry two licences between them, and which tree a thing sits in is the whole
# answer to what it ships under. A branch with no LICENSE, or with the other tree's LICENSE,
# breaks that correspondence and makes the layout unable to answer the question it exists for.
set -o pipefail
T=${1:?a worktree directory inside one of the four trees}
[ -d "$T" ] || { echo "no such directory: $T" >&2; exit 2; }
ABS=$(cd "$T" && pwd)
case "$ABS" in
  /mnt/SymonSayDistribute/*|/mnt/SymonSaySource/*) WANT="SymonSaysLLC Proprietary License" ;;
  /mnt/SymonSayOSS/*|/mnt/SymonSayOpen/*)          WANT="SymonSaysLLC Open Source License" ;;
  *) echo "not inside one of the four trees: $ABS" >&2; exit 2 ;;
esac
[ -f "$ABS/LICENSE" ] || { echo "no LICENSE in $ABS — its tree requires the $WANT"; exit 1; }
if ! grep -q "$WANT" "$ABS/LICENSE"; then
  echo "LICENSE in $ABS does not name the $WANT"
  echo "  first line: $(head -1 "$ABS/LICENSE")"
  exit 1
fi
exit 0
