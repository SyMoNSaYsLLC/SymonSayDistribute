#!/usr/bin/env bash
# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
# SyMoNsAyLeaRn — SyMoNeuRaL, a subdivision of SymonSaysLLC. Terms: see LICENSE.
#
# drive-sweep — scan the cloud remote for exposed credentials, one bounded batch at a time.
#
#   workflow/drive-sweep.sh <workspace> <remote-path> [<remote-path> ...]
#   workflow/drive-sweep.sh <workspace> --files-from <list> [--chunk N]
#
#   workflow/drive-sweep.sh ~/Desktop/claude/drive-reconcile Projects/Active Projects/Crypto
#   workflow/drive-sweep.sh ~/Desktop/claude/drive-reconcile --files-from cred-files.txt
#
# TWO MODES, BECAUSE THE REMOTE HAS TWO SHAPES OF WORK
# A whole folder is the right batch when the folder is small. It is the wrong batch when the
# folder holds 25,000 files of somebody else's source: fetching all of it to find the four
# config files in it is days of throttled API calls for no extra coverage. --files-from takes
# an exact list, chosen from the inventory, and fetches only those. The list is the record of
# what was chosen, and what was left out belongs in its own list beside it.
#
# WHY THIS IS A FILE AND NOT A COMMAND SOMEBODY RETYPES
# ----------------------------------------------------
# §3.3a: the first run may be from scratch; the second means it is a tool, and a tool lives on
# a branch with a licence and a version. This pattern was run three times inline on 2026-09-20
# before it was written down, which is exactly the drift that rule exists to stop.
#
# WHAT IT REFUSES TO DO
# - It never uploads a finding, and never sends one to an external service. The scanner is
#   workflow/secret-sweep.py on this machine.
# - It never writes to the remote. `rclone copy remote local` only reads.
# - It never prints a credential. Findings carry location, kind, fingerprint and length (R13).
# - It removes the fetched copies as soon as a folder is scanned. Staging a credential locally
#   to look at it creates a second copy of it, and a second copy is a second thing that leaks.
#
# HOW IT SURVIVES BEING KILLED
# One folder per batch, each with its own findings file. A folder whose findings file exists and
# parses is skipped, so a re-run resumes where the last one stopped rather than starting the
# remote again. A single-run lock refuses to overlap; two sweeps fetching the same tree would
# double the API load and interleave their staging directories.
set -o pipefail
W=${1:?workspace directory}; shift
FILES_FROM=""; CHUNK=${SYM_DRIVE_CHUNK:-400}
args=()
while [ $# -gt 0 ]; do
  case "$1" in
    --files-from) FILES_FROM=${2:?--files-from needs a path}; shift 2 ;;
    --chunk)      CHUNK=${2:?--chunk needs a number}; shift 2 ;;
    *)            args+=("$1"); shift ;;
  esac
done
set -- "${args[@]}"
[ -n "$FILES_FROM" ] || [ $# -gt 0 ] || {
  echo "usage: drive-sweep.sh <workspace> <remote-path>... | --files-from <list> [--chunk N]" >&2
  exit 2; }
[ -z "$FILES_FROM" ] || [ -r "$FILES_FROM" ] || { echo "cannot read $FILES_FROM" >&2; exit 2; }
SCANNER=$(cd "$(dirname "$0")" && pwd)/secret-sweep.py
[ -r "$SCANNER" ] || { echo "no scanner at $SCANNER" >&2; exit 2; }

REMOTE=${SYM_DRIVE_REMOTE:-gdrive:}
CAP=${SYM_DRIVE_MAX_SIZE:-1M}
LOCK="$W/.sweep.lock"
mkdir -p "$W/sweep" || exit 2
mkdir "$LOCK" 2>/dev/null || { echo "another sweep holds $LOCK — refusing to overlap"; exit 3; }
STAGE=$(mktemp -d "$W/.stage-XXXXXX") || exit 2
chmod 700 "$STAGE"
trap 'rmdir "$LOCK" 2>/dev/null; rm -rf "$STAGE"' EXIT

# Extensions whose content is not text. The scanner also checks for a NUL byte, so this is a
# cost saving rather than the safety net; a file that slips through is still read as bytes.
SKIP='*.{png,jpg,jpeg,gif,webp,heic,pdf,zip,gz,xz,bz2,tar,7z,mp4,mov,mp3,wav,so,o,a,bin,safetensors,gguf,pt,pth,onnx,ico,woff,woff2,svg,ttf,otf,iso,img,deb,rpm,whl,jar,class,pyc,exe,dll,dylib,bmp,tiff,psd,ai,mkv,webm,flac,aac,m4a,apk,dmg,msi,zst}'

total_review=0; total_skipped=0; done_n=0; fail_n=0

# --files-from: split the list into chunks so a kill loses one chunk, not the whole run. The
# remote throttles hard on long runs, and an unbounded fetch that dies at 90% has produced
# nothing at all.
if [ -n "$FILES_FROM" ]; then
  # Chunks go in a directory derived from the list, never a shared one that is cleared on
  # entry. The first version used one fixed directory and wiped it at the start, so passing it
  # a list that LIVED there deleted the input before reading it — and then reported success.
  parts="$W/sweep/.chunks-$(basename "$FILES_FROM" | tr -c 'A-Za-z0-9._-' '_')"
  rm -rf "$parts"; mkdir -p "$parts"
  split -l "$CHUNK" -d -a 4 "$FILES_FROM" "$parts/part-"
  nparts=$(find "$parts" -name 'part-*' | wc -l)
  # Zero chunks means the list was empty or unreadable. That is not a clean sweep.
  [ "$nparts" -gt 0 ] || { echo "  $FILES_FROM produced no chunks — nothing was scanned"; exit 1; }
  echo "  $(wc -l < "$FILES_FROM") file(s) in $nparts chunk(s) of $CHUNK"
  # The checkpoint key must name the LIST as well as the part. Keying on the part alone means
  # two different lists both produce part-0000, and the second run skips the first run's
  # checkpoints as though its own work were already done. Measured 2026-09-20: a 400-file retry
  # split into four parts skipped all four against an unrelated earlier run, and reported rc=0.
  listkey=$(basename "$parts" | sed 's/^\.chunks-//')
  for part in "$parts"/part-*; do
    key="chunk-$listkey-$(basename "$part")"
    out="$W/sweep/findings-$key.json"
    if [ -s "$out" ] && python3 -c "import json,sys;json.load(open(sys.argv[1]))" "$out" 2>/dev/null; then
      echo "  SKIP (checkpoint) $key"; continue
    fi
    d="$STAGE/$key"; mkdir -p "$d"
    printf '  %-24s ' "$key"
    # NO --max-size here. rclone: "the usage of --files-from overrides all other filters, it
    # should be used alone or with --files-from-raw" — passing both makes it refuse to load
    # any filter and fetch NOTHING, while still exiting 0. The size cap belongs where the list
    # is built, not at fetch time. Reproduced 2026-09-20: 0 of 5196 files fetched, 13 chunks,
    # and this script called it a clean sweep.
    rclone copy "$REMOTE" "$d" --files-from "$part" \
           --transfers 16 --checkers 16 >"$STAGE/$key.err" 2>&1
    rc=$?
    n=$(find "$d" -type f 2>/dev/null | wc -l)
    want=$(wc -l < "$part")
    # A scan of zero files is not a clean scan. Reporting "0 findings" for a chunk that fetched
    # nothing is the false-clean this whole tool exists to avoid, so it is a failure and it
    # writes no checkpoint — a re-run must come back here.
    if [ "$n" -eq 0 ] && [ "$want" -gt 0 ]; then
      echo "FETCHED NOTHING of $want (rclone rc=$rc) — NOT a clean result, no checkpoint written"
      sed 's/^/        /' "$STAGE/$key.err" 2>/dev/null | head -3
      fail_n=$((fail_n+1)); rm -rf "$d"; continue
    fi
    # A partial fetch is still worth scanning: the files that arrived are real. What matters is
    # that the shortfall is reported rather than read as coverage.
    python3 "$SCANNER" --tree "$d" --out "$out" >"$W/sweep/summary-$key.json" 2>/dev/null
    src=$?
    chmod 600 "$out" "$W/sweep/summary-$key.json" 2>/dev/null
    # The stage is removed on exit, and with it the only record of WHY a fetch fell short.
    [ "$n" -lt "$want" ] && cp -f "$STAGE/$key.err" "$W/sweep/stderr-$key.txt" 2>/dev/null
    rm -rf "$d"
    if [ ! -s "$out" ]; then
      echo "SCAN FAILED (no checkpoint; re-run resumes here)"; fail_n=$((fail_n+1)); continue
    fi
    read -r rev skp < <(python3 - "$out" <<'PY'
import json,sys
d=json.load(open(sys.argv[1]))
print(d.get("findings_to_review",0), d.get("not_scanned_count",0))
PY
)
    total_review=$((total_review+rev)); total_skipped=$((total_skipped+skp)); done_n=$((done_n+1))
    if [ "$n" -lt "$want" ]; then
      # A short fetch is not a short remote. rclone exits 0 having quietly dropped files —
      # measured 2026-09-20: 317 of 400 arrived, rc=0, and all 12 sampled absentees were still
      # present on the remote. The checkpoint is withheld so a re-run comes back here; keeping
      # it would make today's shortfall permanent on every future run.
      echo "$n/$want fetched (rclone rc=$rc), review=$rev, not-scanned=$skp — SHORT by $((want-n)), NO checkpoint"
      mv -f "$out" "$out.partial" 2>/dev/null
      fail_n=$((fail_n+1))
    else
      echo "$n/$want fetched (rclone rc=$rc), review=$rev, not-scanned=$skp"
    fi
  done
  echo
  echo "  $done_n chunk(s) scanned, $fail_n failed, $total_review finding(s) to review, $total_skipped not scanned"
  echo "  findings are mode 0600 under $W/sweep/ and carry no credential values"
  [ $fail_n -eq 0 ] || exit 1
  exit 0
fi

for path in "$@"; do
  key=$(printf '%s' "$path" | tr '/ ' '__')
  out="$W/sweep/findings-$key.json"
  if [ -s "$out" ] && python3 -c "import json,sys;json.load(open(sys.argv[1]))" "$out" 2>/dev/null; then
    echo "  SKIP (checkpoint) $path"; continue
  fi
  d="$STAGE/$key"; mkdir -p "$d"
  printf '  %-46s ' "$path"
  rclone copy "$REMOTE$path" "$d" --max-size "$CAP" --transfers 16 --checkers 16 \
         --exclude "$SKIP" >/dev/null 2>&1
  rc=$?
  if [ $rc -ne 0 ]; then
    echo "FETCH FAILED rc=$rc (no checkpoint; re-run resumes here)"; fail_n=$((fail_n+1))
    rm -rf "$d"; continue
  fi
  n=$(find "$d" -type f 2>/dev/null | wc -l)
  python3 "$SCANNER" --tree "$d" --out "$out" >"$W/sweep/summary-$key.json" 2>/dev/null
  src=$?
  chmod 600 "$out" "$W/sweep/summary-$key.json" 2>/dev/null
  # Remove the fetched copies NOW. Everything worth keeping is already in the findings file,
  # and what is left on disk is somebody's credentials in a second place.
  rm -rf "$d"
  if [ ! -s "$out" ]; then
    echo "SCAN FAILED (no findings file; re-run resumes here)"; fail_n=$((fail_n+1)); continue
  fi
  read -r rev skp < <(python3 - "$out" <<'PY'
import json,sys
d=json.load(open(sys.argv[1]))
print(d.get("findings_to_review",0), d.get("not_scanned_count",0))
PY
)
  total_review=$((total_review+rev)); total_skipped=$((total_skipped+skp)); done_n=$((done_n+1))
  echo "$n files, review=$rev, not-scanned=$skp (scanner rc=$src)"
done

echo
echo "  $done_n folder(s) scanned, $fail_n failed, $total_review finding(s) to review, $total_skipped not scanned"
echo "  findings are mode 0600 under $W/sweep/ and carry no credential values"
[ $fail_n -eq 0 ] || exit 1
