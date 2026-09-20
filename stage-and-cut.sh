#!/usr/bin/env bash
set -o pipefail
U=$1; V=$2; SRC=/mnt/SymonSayDistribute/$U; S=/home/google/symoneural-release/$U/v$V; W=/mnt/SymonSayDistribute/workflow
\rm -rf "$S"
"$W/pack-script-unit.sh" "$U" "$V" "$SRC" "$S" || exit 3
python3 "$W/ship-gate.py" --stage "$S" --json "$S/SHIP-GATE-REPORT.json" >/dev/null 2>&1
python3 "$W/third-party-notices.py" --report "$S/SHIP-GATE-REPORT.json" --stage "$S" --out "$S/THIRD-PARTY-NOTICES.md" >/dev/null || exit 4
# The gate above ran BEFORE the line above existed, and check_attribution() FAILs every
# permissive unit when THIRD-PARTY-NOTICES.md is absent (ship-gate.py:405). So the report on
# disk at this point records a verdict manufactured by a file this release itself ships, and
# release-notes.py reads that report. Every published note said so.
#
# Reproduced 2026-09-20 against the v1.0.0 stage, notices parked and restored:
#   without THIRD-PARTY-NOTICES.md   10 FAIL,  0 REVIEW, 0 PASS   overall FAIL
#   with it                           2 FAIL,  6 REVIEW, 2 PASS   overall FAIL
# and symoneural-learn/v1.6.0 shipped notes reading "Overall FAIL - 1 failing unit(s), 0
# needing review" beside an uploaded SHIP-GATE-REPORT.json whose own overall was REVIEW.
#
# Re-run the gate now that the notices exist, so the notes and the shipped evidence describe
# the same run. Cheap, and the alternative is a release whose two files contradict each other.
python3 "$W/ship-gate.py" --stage "$S" --json "$S/SHIP-GATE-REPORT.json" >/dev/null 2>&1
python3 "$W/release-notes.py" --stage "$S" --tag "$U/v$V" --out "$S/RELEASE-NOTES.md" >/dev/null || exit 4
( cd "$S" && find . -type f ! -name SHA256SUMS ! -name SHIP-GATE-REPORT.json -printf '%P\n' | sort | xargs sha256sum > SHA256SUMS ) || exit 4
python3 "$W/ship-gate.py" --stage "$S" > "$S/.gate.txt" 2>&1; grc=$?
tail -5 "$S/.gate.txt"
[ $grc -eq 0 ] || { echo "GATE FAILED rc=$grc — not cutting"; exit 5; }
cd "$SRC" || exit 3
"$W/cut-release.sh" "$U" "$V" "$S" > "$S/.cut.txt" 2>&1; crc=$?
tail -4 "$S/.cut.txt"
exit $crc
