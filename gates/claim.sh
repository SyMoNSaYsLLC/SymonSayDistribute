#!/usr/bin/env bash
# one-line: tests a claim about a path before anything is built on it
# staged: no — takes a claim to test; there is none to infer from a commit
# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
#
# Section 3.1d, test before deciding. A claim carried forward from a summary, a report or an
# earlier session is untested. This is the cheapest possible way to test one, so there is no
# excuse for building on it untested.
#
#   claim.sh <path> exists|file|dir|executable|nonempty|git-clean|mount
#
# Exit 0 the claim holds, 1 it does not, 2 it was not stated properly. Under-invoking it is
# MISUSE and never a pass: a claim nobody stated cannot be a claim that held.
set -o pipefail
if [ $# -lt 2 ]; then
  echo "usage: claim.sh <path> exists|file|dir|executable|nonempty|git-clean|mount" >&2
  exit 2
fi
T=$1; WHAT=$2
say() { echo "claim: $T is $WHAT -> $1"; }
case "$WHAT" in
  exists)     [ -e "$T" ] && { say TRUE; exit 0; } ;;
  file)       [ -f "$T" ] && { say TRUE; exit 0; } ;;
  dir)        [ -d "$T" ] && { say TRUE; exit 0; } ;;
  executable) [ -x "$T" ] && { say TRUE; exit 0; } ;;
  nonempty)   [ -s "$T" ] && { say TRUE; exit 0; } ;;
  mount)      if [ "$(findmnt -no TARGET -T "$T" 2>/dev/null)" = "$(cd "$T" 2>/dev/null && pwd)" ]; then say TRUE; exit 0; fi ;;
  git-clean)  git -C "$T" rev-parse --git-dir >/dev/null 2>&1 && [ -z "$(git -C "$T" status --porcelain 2>/dev/null)" ] && { say TRUE; exit 0; } ;;
  *) echo "unknown claim: $WHAT" >&2; exit 2 ;;
esac
say FALSE
exit 1
