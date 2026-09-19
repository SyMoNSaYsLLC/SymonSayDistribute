#!/usr/bin/env bash
# one-line: refuses a writable acquired upstream source tree
# staged: no — asks about worktrees on disk, not about staged bytes
# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
#
# R1: acquired upstream source is read-only. A modified upstream tree makes the pin a lie — the
# recorded SHA no longer describes what was built, and nothing downstream can tell.
set -o pipefail
T=${1:?path to check}
[ -e "$T" ] || { echo "no such path: $T" >&2; exit 2; }
rc=0
while IFS= read -r d; do
  [ -z "$d" ] && continue
  dirty=$(git -C "$d" status --porcelain 2>/dev/null | head -5)
  if [ -n "$dirty" ]; then
    echo "upstream tree modified: $d"; echo "$dirty" | sed 's/^/    /'; rc=1
  fi
done < <(find "$T" -type d -path '*/source' -maxdepth 4 2>/dev/null)
exit $rc
