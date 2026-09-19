#!/usr/bin/env bash
# one-line: refuses a SYM_* variable read in code but absent from the configuration contract
# target: worktree — the contract and the code that reads it both live in the tree
# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
#
# The contract file says of itself: "the ship gate's repo scan lists undeclared SYM_* names."
#
# THAT SCAN DID NOT EXIST. Zero matches for it across all three copies of ship-gate.py. The
# contract described an enforcement that was never written, so nothing ever checked it, and
# 55 of 83 runtime variables drifted out of it — including ten unit tokens, ten enable flags,
# and seven flags built by f-string at run time that appear nowhere on disk at all.
#
# A document claiming to be enforced is worse than one that admits it is not: the claim is why
# nobody looked.
#
# WHAT IT CHECKS
# --------------
# Every SYM_* name read from the environment anywhere in the tree must appear in the contract.
# A name that is constructed rather than written (f"SYM_{name.upper()}_ENABLED") cannot be
# found by reading code, so a contract entry for the PATTERN satisfies it — written as
# SYM_<NAME>_ENABLED — and that is stated rather than silently allowed.
set -o pipefail
T=${1:?path to check}
[ -d "$T" ] || { echo "no such directory: $T" >&2; exit 2; }

CONTRACT=$(find "$T" -name 'symoneural-learn.env.example' -not -path '*/.git/*' 2>/dev/null | head -1)
[ -n "$CONTRACT" ] || { echo "no configuration contract in this tree" >&2; exit 2; }

# Names the contract declares, including a pattern form like SYM_<NAME>_ENABLED.
declared=$(grep -oE '^[[:space:]]*#?[[:space:]]*(SYM|SYMONEURAL)_[A-Z0-9_<>]+' "$CONTRACT" \
           | grep -oE '(SYM|SYMONEURAL)_[A-Z0-9_<>]+' | sort -u)

# Names the code actually reads.
read_names=$(grep -rhoE '(os\.environ(\.get)?\(|getenv\(|\$\{?)["'"'"']?(SYM|SYMONEURAL)_[A-Z0-9_]+' "$T" \
  --include='*.py' --include='*.sh' --include='*.ts' --include='*.tsx' --include='*.c' --include='*.h' \
  --exclude-dir=.git --exclude-dir=node_modules --exclude-dir=__pycache__ 2>/dev/null \
  | grep -oE '(SYM|SYMONEURAL)_[A-Z0-9_]+' | sort -u)

missing=""
for n in $read_names; do
  printf '%s\n' "$declared" | grep -qx "$n" && continue
  # a declared pattern covers a constructed name: SYM_<NAME>_ENABLED covers SYM_CHAT_ENABLED
  covered=0
  while IFS= read -r d; do
    case "$d" in *'<'*'>'*)
      rx=$(printf '%s' "$d" | sed 's/<[A-Z]*>/[A-Z0-9]+/g')
      printf '%s' "$n" | grep -qE "^${rx}$" && { covered=1; break; } ;;
    esac
  done <<< "$declared"
  [ $covered -eq 1 ] || missing="$missing $n"
done

if [ -n "$missing" ]; then
  echo "read in code, absent from the configuration contract:"
  for n in $missing; do echo "  $n"; done
  echo
  echo "  contract: $CONTRACT"
  echo "  The contract says this is a defect to fix in the same change that introduced the"
  echo "  variable. Declare it there, or declare the pattern as SYM_<NAME>_SUFFIX."
  exit 1
fi
exit 0
