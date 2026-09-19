#!/usr/bin/env bash
set -o pipefail
U=$1; V=$2; SRC=/mnt/SymonSayDistribute/$U; S=/home/google/symoneural-release/$U/v$V; W=/mnt/SymonSayDistribute/workflow
\rm -rf "$S"
"$W/pack-script-unit.sh" "$U" "$V" "$SRC" "$S" || exit 3
python3 "$W/ship-gate.py" --stage "$S" --json "$S/SHIP-GATE-REPORT.json" >/dev/null 2>&1
python3 "$W/third-party-notices.py" --report "$S/SHIP-GATE-REPORT.json" --stage "$S" --out "$S/THIRD-PARTY-NOTICES.md" >/dev/null || exit 4
python3 "$W/release-notes.py" --stage "$S" --tag "$U/v$V" --out "$S/RELEASE-NOTES.md" >/dev/null || exit 4
( cd "$S" && find . -type f ! -name SHA256SUMS ! -name SHIP-GATE-REPORT.json -printf '%P\n' | sort | xargs sha256sum > SHA256SUMS ) || exit 4
python3 "$W/ship-gate.py" --stage "$S" > "$S/.gate.txt" 2>&1; grc=$?
tail -5 "$S/.gate.txt"
[ $grc -eq 0 ] || { echo "GATE FAILED rc=$grc — not cutting"; exit 5; }
cd "$SRC" || exit 3
"$W/cut-release.sh" "$U" "$V" "$S" > "$S/.cut.txt" 2>&1; crc=$?
tail -4 "$S/.cut.txt"
exit $crc
