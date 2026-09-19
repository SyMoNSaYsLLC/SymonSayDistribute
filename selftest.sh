#!/usr/bin/env bash
# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
#
# selftest — prove every gate can fail.
#
# A gate that only ever passes has enforced nothing, and looks identical in a report to a gate
# that works. Section 3.1d puts it plainly: a check that cannot fail is not a test. So each gate
# here is run twice, against a fixture built to violate it and a fixture built to satisfy it,
# and the gate is only sound if it fails the first and passes the second.
#
# The credential fixture is a synthetic string of the right SHAPE and nothing more. No real
# secret is written, printed or committed by this file.
set -o pipefail
HERE=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
WORK=$(mktemp -d "${TMPDIR:-/tmp}/gate-selftest-XXXXXX") || exit 1
trap 'rm -rf "$WORK"' EXIT
BAD="$WORK/bad"; GOOD="$WORK/good"; mkdir -p "$BAD" "$GOOD"

# ------------------------------------------------------------------ fixtures
printf '#!/bin/sh\ngit add -A\n'                              > "$BAD/blanket.sh"
printf '#!/bin/sh\ngit add -- one.txt two.txt\n'              > "$GOOD/explicit.sh"
# Assembled at run time from harmless parts. Writing the literal into this file would put a
# credential-SHAPED string into the repository, and every scanner downstream — ours, the ship
# gate, GitHub's — is right to flag that. A fixture is not worth an exemption in every tool
# that will ever read this tree, so the shape exists only in the temporary file.
printf 'token = "%s-%s-%s"\n' sk ant EXAMPLE0NOT0A0REAL0KEY000000 > "$BAD/creds.py"  # gate-allow: no-secret — synthetic fixture, written to a temp dir only
printf 'token = os.environ["SYM_CHAT_TOKEN"]\n'               > "$GOOD/creds.py"
: > "$BAD/model.safetensors"
printf 'weights live outside git\n'                           > "$GOOD/README.md"
printf 'decided on 2026-08-14\n'                              > "$BAD/old.md"  # gate-allow: no-august — synthetic fixture, written to a temp dir only
printf 'decided on 2026-09-18\n'                              > "$GOOD/new.md"
printf '#!/bin/sh\nmake all | tail -3; rc=$?\n'               > "$BAD/piped.sh"  # gate-allow: exit-code-direct — synthetic fixture, written to a temp dir only
printf '#!/bin/sh\nmake all > log 2>&1; rc=$?\ntail -3 log\n' > "$GOOD/direct.sh"
printf '#!/bin/sh\nsudo pkill --ns 1234\n'                    > "$BAD/signal.sh"  # gate-allow: forbidden-signal — synthetic fixture, written to a temp dir only
printf '#!/bin/sh\nkill -CONT "$PID"; kill -TERM "$PID"\n'    > "$GOOD/signal.sh"
mkdir -p "$BAD/pkg/source" && git -C "$BAD/pkg/source" init -q 2>/dev/null \
  && printf 'edited\n' > "$BAD/pkg/source/patched.c"
mkdir -p "$GOOD/pkg/source" && git -C "$GOOD/pkg/source" init -q 2>/dev/null \
  && printf 'pristine\n' > "$GOOD/pkg/source/orig.c" \
  && git -C "$GOOD/pkg/source" add -- orig.c >/dev/null 2>&1 \
  && git -C "$GOOD/pkg/source" -c user.email=t@t -c user.name=t commit -qm pristine >/dev/null 2>&1

# Divergence needs two trees, not two files: the fault is the same NAME carrying different
# bytes in different places. The good fixture is the same name carrying IDENTICAL bytes, which
# is duplication and deliberately not a failure.
mkdir -p "$BAD/treeA" "$BAD/treeB" "$GOOD/treeA" "$GOOD/treeB"
printf '#!/bin/sh\necho version one\n'  > "$BAD/treeA/tool.sh"
printf '#!/bin/sh\necho version two\n'  > "$BAD/treeB/tool.sh"
printf '#!/bin/sh\necho same\n'         > "$GOOD/treeA/tool.sh"
printf '#!/bin/sh\necho same\n'         > "$GOOD/treeB/tool.sh"

printf '#!/bin/sh\ncurl -s x > /tmp/.m.$$\n'          > "$BAD/tmpfile.sh"   # gate-allow: no-predictable-tmp — synthetic fixture
printf '#!/bin/sh\nf=$(mktemp) && curl -s x > "$f"\n' > "$GOOD/tmpfile.sh"

# A capability with no route. The bad fixture has a public function the service never names
# and no NOT_EXPOSED entry; the good one records why it is not exposed, which is a decision
# rather than silence.
mkdir -p "$BAD/svc/pkg" "$GOOD/svc/pkg"
printf 'from . import cap\n@app.post("/x")\ndef x(): return cap.exposed()\n' > "$BAD/svc/pkg/service.py"
printf 'def exposed(): pass\ndef forgotten(): pass\n'                        > "$BAD/svc/pkg/cap.py"
printf 'from . import cap\n@app.post("/x")\ndef x(): return cap.exposed()\n' > "$GOOD/svc/pkg/service.py"
printf 'NOT_EXPOSED = {"internal": "every caller goes through exposed()"}\ndef exposed(): pass\ndef internal(): pass\n' > "$GOOD/svc/pkg/cap.py"

# A contract that does not declare what the code reads, and one that does. The pattern form
# is in the good fixture because a name built by f-string at run time cannot be found by
# reading code, and a contract entry for the pattern is the only thing that can cover it.
mkdir -p "$BAD/contract" "$GOOD/contract"
printf 'import os\nos.environ.get("SYM_DECLARED")\nos.environ.get("SYM_MISSING")\n' > "$BAD/contract/app.py"
printf 'SYM_DECLARED=x\n' > "$BAD/contract/symoneural-learn.env.example"
printf 'import os\nos.environ.get("SYM_DECLARED")\nos.environ.get("SYM_CHAT_ENABLED")\n' > "$GOOD/contract/app.py"
printf 'SYM_DECLARED=x\nSYM_<NAME>_ENABLED=\n' > "$GOOD/contract/symoneural-learn.env.example"

# A recipe with no LICENSE, and one with a licence and a checksum.
mkdir -p "$BAD/recipes" "$GOOD/recipes"
printf 'SUMMARY = "no licence"\nSRC_URI = "git://example"\n' > "$BAD/recipes/thing_git.bb"
printf 'SUMMARY = "declared"\nLICENSE = "MIT"\nLIC_FILES_CHKSUM = "file://COPYING;md5=0"\n' > "$GOOD/recipes/thing_git.bb"

pass=0; fail=0
check() { # check <gate> <fixture> <expect: FAIL|PASS> <extra args...>
  local g=$1 fixture=$2 expect=$3; shift 3
  "$HERE/gate" "$g" "$fixture" "$@" >/dev/null 2>&1; local rc=$?
  local got; if [ $rc -eq 0 ]; then got=PASS; elif [ $rc -eq 2 ]; then got=MISUSE; else got=FAIL; fi
  if [ "$got" = "$expect" ]; then
    printf '  ok    %-22s %-34s %s\n' "$g" "$(basename "$fixture")" "$expect"; pass=$((pass+1))
  else
    printf '  BROKEN %-21s %-34s expected %s, got %s\n' "$g" "$(basename "$fixture")" "$expect" "$got"; fail=$((fail+1))
  fi
}

echo "each gate against a fixture that violates it, then one that satisfies it"
echo
check no-blanket-add    "$BAD/blanket.sh"   FAIL
check no-blanket-add    "$GOOD/explicit.sh" PASS
check no-secret         "$BAD/creds.py"     FAIL
check no-secret         "$GOOD/creds.py"    PASS
check no-weights        "$BAD"              FAIL
check no-weights        "$GOOD/README.md"   PASS
check no-august         "$BAD/old.md"       FAIL
check no-august         "$GOOD/new.md"      PASS
check exit-code-direct  "$BAD/piped.sh"     FAIL
check exit-code-direct  "$GOOD/direct.sh"   PASS
check forbidden-signal  "$BAD/signal.sh"    FAIL
check forbidden-signal  "$GOOD/signal.sh"   PASS
check no-upstream-write "$BAD/pkg"          FAIL
check no-upstream-write "$GOOD/pkg"         PASS
check on-disk           "$HERE"             PASS
# A tmpfs accepts every write and keeps none of them across a reboot. It is the exact thing
# "on disk" exists to exclude, so it is the fixture that proves this gate can fail.
[ -d /dev/shm ] && check on-disk "/dev/shm"  FAIL
check claim             "$HERE/gate"        PASS   executable
# A false claim reports FALSE and exits 1. That is the gate working: the point is to make the
# claim fail HERE rather than three steps later inside whatever was built on it.
check claim             "$WORK/absent"      FAIL   exists
check claim             "$HERE"             FAIL   file
check contract-declared "$BAD/contract"     FAIL
check contract-declared "$GOOD/contract"    PASS
check recipe-licence    "$BAD/recipes"      FAIL
check recipe-licence    "$GOOD/recipes"     PASS
check endpoints-current "$BAD/svc"          FAIL
check endpoints-current "$GOOD/svc"         PASS
check no-predictable-tmp "$BAD/tmpfile.sh"  FAIL
check no-predictable-tmp "$GOOD/tmpfile.sh" PASS
check no-divergent-copy "$BAD"              FAIL
check no-divergent-copy "$GOOD"             PASS
check licence-stamped   "$WORK"             MISUSE
# Inside one of the four trees, a directory with no LICENSE is exactly the state this refuses.
[ -d /mnt/SymonSayDistribute/.bare ] && check licence-stamped /mnt/SymonSayDistribute/.bare FAIL
[ -d /mnt/SymonSayDistribute/workflow ] && check licence-stamped /mnt/SymonSayDistribute/workflow PASS

echo
echo "$pass sound, $fail broken"
[ $fail -eq 0 ] || exit 1
