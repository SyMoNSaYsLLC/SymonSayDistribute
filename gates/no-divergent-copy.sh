#!/usr/bin/env bash
# one-line: refuses the same tool existing at several paths with different contents
# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
#
#   no-divergent-copy.sh <path> [more paths ...]
#
# A tool that exists four times with four different hashes has no canonical version. Every
# reader picks one, each believes it is THE one, and the differences between them are invisible
# until something behaves differently depending on which copy ran.
#
# This was found in this estate on 2026-09-18: ship-gate.py existed at four paths across two
# filesystems, three of them stale by thirteen kilobytes — the release gate itself, with no
# agreement about what it was. Nothing reported it, because each copy was individually fine.
#
# Identical copies are reported as duplication and do not fail: the same bytes in two places is
# a tidiness question. DIFFERENT bytes under the same name is the fault, and it fails.
#
# Only scripts are compared. LICENSE, README.md and per-branch documents are SUPPOSED to differ
# between branches — comparing them would bury the real finding in noise.
set -o pipefail
[ $# -ge 1 ] || { echo "usage: no-divergent-copy.sh <path> [more paths ...]" >&2; exit 2; }
for p in "$@"; do [ -e "$p" ] || { echo "no such path: $p" >&2; exit 2; }; done

# Names that are structurally per-package rather than a tool. `__init__.py` differs in every
# Python package by design; comparing them reports seven "divergences" that are simply seven
# different packages, and buries the real finding.
SKIP_NAMES='^(__init__\.py|__main__\.py|conftest\.py|setup\.py|_version\.py)$'

LIST=$(mktemp) || exit 2
trap 'rm -f "$LIST" "$LIST.g"' EXIT

for root in "$@"; do
  find "$root" -type f \( -name '*.sh' -o -name '*.py' -o -name '*.bash' \) \
       -not -path '*/.git/*' -not -path '*/__pycache__/*' -not -path '*/node_modules/*' \
       -not -path '*/site-packages/*' -not -path '*/.venv/*' -not -path '*/venv/*' \
       -print0 2>/dev/null \
    | xargs -0 -r sha256sum 2>/dev/null
done | awk '{ sum=$1; $1=""; sub(/^ +/,""); n=split($0,a,"/"); print a[n]"\t"sum"\t"$0 }' > "$LIST"

rc=0
# group by basename; a basename with more than one distinct hash is divergent
cut -f1 "$LIST" | sort -u > "$LIST.g"
while IFS= read -r base; do
  [ -n "$base" ] || continue
  printf '%s' "$base" | grep -qE "$SKIP_NAMES" && continue
  rows=$(awk -F'\t' -v b="$base" '$1==b' "$LIST")
  nh=$(printf '%s\n' "$rows" | cut -f2 | sort -u | wc -l)
  np=$(printf '%s\n' "$rows" | wc -l)
  [ "$np" -gt 1 ] || continue
  if [ "$nh" -gt 1 ]; then
    echo "divergent: $base exists $np times with $nh different contents"
    printf '%s\n' "$rows" | while IFS=$'\t' read -r b h f; do
      printf '    %s  %s\n' "$(echo "$h" | cut -c1-12)" "$f"
    done
    rc=1
  fi
done < "$LIST.g"

[ $rc -eq 0 ] || echo "  Pick one canonical copy. The others become a reference to it, or they go."
exit $rc
