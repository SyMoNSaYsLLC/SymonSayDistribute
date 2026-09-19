#!/usr/bin/env bash
# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
#
# mutants — prove the SELFTEST can fail, by breaking each gate on purpose.
#
#   ./mutants.sh [--verbose]
#
# selftest.sh proves each gate can fail. This proves the selftest can fail. Without it the
# suite has an obvious hole: a gate whose fixtures never exercised it looks identical, in every
# report, to a gate that works — and so does a gate somebody edited into uselessness.
#
# HOW
# ---
# The whole tree is copied, one gate is replaced with a mutant, and the selftest is run against
# the copy. The mutant is expected to be KILLED: the selftest must fail. A mutant that SURVIVES
# means that gate can be broken without any test noticing, and is reported by name.
#
# Two mutants per gate, which between them cover both directions:
#   always-pass   the gate exits 0 whatever it is given — it has stopped refusing anything
#   always-fail   the gate exits 1 whatever it is given — it now refuses everything
#
# Nothing here writes outside its temporary directory, and the real gates are never modified.
set -o pipefail
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
VERBOSE=0; [ "${1:-}" = "--verbose" ] && VERBOSE=1

[ -x "$HERE/selftest.sh" ] || { echo "no selftest.sh beside this script" >&2; exit 2; }

# THE COPIES MUST LIVE ON DISK.
# The first version put them in $TMPDIR, which on this host is tmpfs. The selftest asserts that
# its own directory is on a real filesystem — correctly, since that is what `on-disk` is for —
# so it failed in every mutant tree for a reason that had nothing to do with the mutation, and
# all twenty mutants were reported killed when none of them had been exercised at all. A green
# run that is green for the wrong reason is worse than a red one.
pick_root() {
  local c
  for c in "$MUTANT_TMPDIR" "$(dirname "$HERE")" "$TMPDIR" /tmp; do
    [ -n "$c" ] && [ -d "$c" ] && [ -w "$c" ] || continue
    case "$(findmnt -no FSTYPE -T "$c" 2>/dev/null)" in
      tmpfs|ramfs|overlay|fuse*|nfs*|cifs|9p) continue ;;
    esac
    echo "$c"; return 0
  done
  return 1
}
ROOT=$(pick_root) || { echo "no disk-backed directory to work in — set MUTANT_TMPDIR" >&2; exit 2; }
WORK=$(mktemp -d "$ROOT/.gate-mutants-XXXXXX") || exit 1
trap 'rm -rf "$WORK"' EXIT
echo "working in $WORK ($(findmnt -no FSTYPE -T "$WORK"))"

# CONTROL FIRST.
# An unmutated copy must pass in exactly the place the mutants will run. If it does not, every
# mutant would be "killed" by whatever is wrong with the environment and the whole run means
# nothing. This is the check that would have caught the tmpfs fault immediately.
CTL="$WORK/control"; mkdir -p "$CTL"
cp -a "$HERE/gate" "$HERE/gates" "$HERE/selftest.sh" "$CTL/" 2>/dev/null
ctl_out=$("$CTL/selftest.sh" 2>&1); ctl_rc=$?
if [ $ctl_rc -ne 0 ]; then
  echo "CONTROL FAILED — the unmutated tree does not pass its own selftest here."
  echo "Every mutant would be killed by this, not by the mutation. Nothing is measured."
  echo "$ctl_out" | sed 's/^/  /'
  exit 2
fi
echo "control passes: $(echo "$ctl_out" | tail -1)"
echo

killed=0; survived=0; SURVIVORS=()

for g in "$HERE"/gates/*.sh; do
  name=$(basename "$g" .sh)
  for kind in always-pass always-fail; do
    T="$WORK/$name-$kind"
    mkdir -p "$T"
    cp -a "$HERE/gate" "$HERE/gates" "$HERE/selftest.sh" "$T/" 2>/dev/null
    case "$kind" in
      always-pass) printf '#!/usr/bin/env bash\n# mutant: refuses nothing\nexit 0\n' > "$T/gates/$name.sh" ;;
      always-fail) printf '#!/usr/bin/env bash\n# mutant: refuses everything\nexit 1\n' > "$T/gates/$name.sh" ;;
    esac
    chmod +x "$T/gates/$name.sh"

    out=$("$T/selftest.sh" 2>&1); rc=$?
    if [ $rc -ne 0 ]; then
      killed=$((killed+1))
      [ $VERBOSE -eq 1 ] && printf '  killed    %-22s %s\n' "$name" "$kind"
    else
      survived=$((survived+1))
      SURVIVORS+=("$name/$kind")
      printf '  SURVIVED  %-22s %s — this gate can be broken and no test notices\n' "$name" "$kind"
    fi
  done
done

total=$((killed+survived))
echo
echo "$total mutants, $killed killed, $survived survived"
if [ $survived -gt 0 ]; then
  echo
  echo "Each survivor is a gate with no test behind it. Add a fixture to selftest.sh that the"
  echo "gate must fail, and one it must pass, then run this again:"
  printf '  %s\n' "${SURVIVORS[@]}"
  exit 1
fi
