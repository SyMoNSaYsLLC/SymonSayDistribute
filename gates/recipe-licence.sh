#!/usr/bin/env bash
# one-line: refuses a recipe that declares no licence
# target: worktree — recipes live in a tree, and the question is about the tree's contents
# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
#
# A recipe with no declared LICENSE cannot be placed by the placement procedure, cannot be
# audited, and cannot be defended at a review. It is the one thing about a recipe that is never
# a judgement call — the answer is in the upstream source.
#
# Two recipes in SymonSayOpen have sat undeclared: symoneural-gstreamer-plugins-base and
# symoneural-nvidia-open-kernel-debian. The estate had thirteen gates and not one of them asked.
#
# LIC_FILES_CHKSUM IS CHECKED SEPARATELY AND MORE SOFTLY.
# A licence NAME is a claim; the checksum of the licence file is what makes that claim checkable
# after upstream relicenses, adds a clause, or changes a copyright holder. A recipe that names a
# licence without one is reported, not refused — some recipes legitimately have no file to
# checksum — and a recipe that names nothing at all is refused outright.
set -o pipefail
T=${1:?path to check}
[ -d "$T" ] || { echo "no such directory: $T" >&2; exit 2; }

mapfile -t RECIPES < <(find "$T" \( -name '*.bb' -o -name '*.bbappend' \) -not -path '*/.git/*' 2>/dev/null | sort)
[ "${#RECIPES[@]}" -gt 0 ] || { echo "no recipes here" >&2; exit 2; }

undeclared=""; unchecksummed=""
for f in "${RECIPES[@]}"; do
  # a .bbappend inherits its licence from the recipe it appends to
  case "$f" in *.bbappend) continue ;; esac
  rel=${f#"$T"/}
  if ! grep -qE '^[[:space:]]*LICENSE[[:space:]]*(\?)?=' "$f"; then
    undeclared="$undeclared $rel"
  elif ! grep -qE '^[[:space:]]*LIC_FILES_CHKSUM[[:space:]]*(\?)?=' "$f"; then
    unchecksummed="$unchecksummed $rel"
  fi
done

if [ -n "$unchecksummed" ]; then
  echo "declares a licence with no LIC_FILES_CHKSUM — the name is a claim, the checksum is the check:"
  for r in $unchecksummed; do echo "  $r"; done
fi
if [ -n "$undeclared" ]; then
  echo "declares no LICENSE at all:"
  for r in $undeclared; do echo "  $r"; done
  echo
  echo "  A recipe with no licence cannot be placed, audited, or defended."
  echo "  The answer is in the upstream source; it is not a judgement call."
  exit 1
fi
exit 0
