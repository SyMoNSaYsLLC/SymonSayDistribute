#!/usr/bin/env bash
# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
#
# install — put the gates where they fire.
#
#   install.sh [--uninstall] [--dry-run]
#
# A gate in a directory is a document. A gate on the commit path is a gate. This installs a
# pre-commit hook into each of the four trees and puts `gate` on PATH.
#
# Hooks live in the COMMON git directory, which every worktree of a tree shares, so one install
# per tree covers all of its branches. An existing hook is never overwritten: it is moved aside
# to <name>.before-gates and the path is printed, because section 3.2 forbids deleting Garrett's
# files and a hook he wrote by hand is exactly the kind of thing that disappears silently.
set -o pipefail
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
TREES=(/mnt/SymonSayDistribute /mnt/SymonSaySource /mnt/SymonSayOSS /mnt/SymonSayOpen)
BIN="$HOME/.local/bin"
UNINSTALL=0; DRY=0
for a in "$@"; do case "$a" in --uninstall) UNINSTALL=1;; --dry-run) DRY=1;; *) echo "unknown arg $a" >&2; exit 2;; esac; done

hook_body() {
cat <<'HOOK'
#!/usr/bin/env bash
# installed by SymonSayDistribute/gates — see gates.md
# Runs the content gates against what is STAGED, not against the worktree: the worktree may
# hold anything, but only staged content is about to become history, and history is what
# cannot be taken back.
set -o pipefail
GATE_HOME=__GATE_HOME__
[ -x "$GATE_HOME/gate" ] || exit 0
STAGED=$(git diff --cached --name-only --diff-filter=ACM)
skipped=""
[ -n "$STAGED" ] || exit 0
TMP=$(mktemp -d "${TMPDIR:-/tmp}/pre-commit-gate-XXXXXX") || exit 0
trap 'rm -rf "$TMP"' EXIT
git checkout-index -a -f --prefix="$TMP/" 2>/dev/null || exit 0
rc=0
# EVERY gate, not a chosen five. The first version named five, which meant seven gates were
# installed, reported as installed, and never fired on a commit — the exact shape of failure
# the gates exist to prevent. A gate that does not apply to staged content exits 2 and is
# skipped by name, which is visible; being left out of a list is not.
# Each gate declares whether it applies to STAGED CONTENT, in its own header. A hardcoded
# list here is how seven gates were installed, reported as installed, and never fired. A
# declaration in the gate is visible to anyone reading the gate; a list somewhere else is not.
for g in $(cd "$GATE_HOME/gates" && grep -l '^# staged: yes' *.sh 2>/dev/null | sed 's/\.sh$//'); do
  out=$("$GATE_HOME/gate" "$g" "$TMP" 2>&1); grc=$?
  if [ $grc -eq 1 ]; then echo "commit refused by gate '$g':"; echo "$out" | sed 's/^/  /'; rc=1
  elif [ $grc -eq 2 ]; then skipped="$skipped $g"; fi
done
[ -z "$skipped" ] || echo "gates not applicable to this change:$skipped"
[ $rc -eq 0 ] || echo "
Nothing was committed. Fix the above, or commit with --no-verify if this is a
deliberate exception you can name."
exit $rc
HOOK
}

for T in "${TREES[@]}"; do
  [ -d "$T" ] || { echo "skip  $T (not on this machine)"; continue; }
  WT=$(ls -1d "$T"/*/ 2>/dev/null | grep -v '\.bare' | head -1)
  [ -n "$WT" ] || { echo "skip  $T (no worktree to read the hook path from)"; continue; }
  COMMON=$(git -C "$WT" rev-parse --path-format=absolute --git-common-dir 2>/dev/null)
  [ -d "$COMMON" ] || { echo "skip  $T (no common git dir)"; continue; }
  H="$COMMON/hooks/pre-commit"
  if [ $UNINSTALL -eq 1 ]; then
    if [ -f "$H" ] && grep -q 'installed by SymonSayDistribute/gates' "$H" 2>/dev/null; then
      [ $DRY -eq 1 ] && { echo "would remove  $H"; continue; }
      mv "$H" "$H.removed-$(date +%Y%m%d-%H%M%S)"; echo "removed  $H (moved aside, not deleted)"
    else echo "none     $H is not ours — left alone"; fi
    continue
  fi
  if [ -f "$H" ] && ! grep -q 'installed by SymonSayDistribute/gates' "$H" 2>/dev/null; then
    [ $DRY -eq 1 ] && { echo "would move aside  $H"; } || { mv "$H" "$H.before-gates"; echo "moved aside  $H.before-gates"; }
  fi
  if [ $DRY -eq 1 ]; then echo "would install  $H"; continue; fi
  mkdir -p "$(dirname "$H")"
  hook_body | sed "s|__GATE_HOME__|$HERE|" > "$H" && chmod +x "$H" && echo "installed  $H"
done

if [ $UNINSTALL -eq 0 ]; then
  if [ $DRY -eq 1 ]; then echo "would link  $BIN/gate -> $HERE/gate"
  else mkdir -p "$BIN"; ln -sf "$HERE/gate" "$BIN/gate"; echo "linked     $BIN/gate -> $HERE/gate"
       case ":$PATH:" in *":$BIN:"*) ;; *) echo "note       $BIN is not on PATH in this shell";; esac
  fi
fi
