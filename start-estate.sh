#!/usr/bin/env bash
# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
# SyMoNsAyLeaRn — SyMoNeuRaL, a subdivision of SymonSaysLLC. Terms: see LICENSE.
#
# start-estate — bring the estate's services up after a reboot.
#
#   workflow/start-estate.sh [--dry-run]
#
# WHY THIS EXISTS
# ---------------
# The host rebooted on 2026-09-19 at 08:05 and every service in the estate was gone: eleven
# units, the gateway and the engine. Nothing brought them back, because nothing ever had —
# each had been started by hand, in a terminal, and inherited that terminal's lifetime.
#
# The second half of that failure is worse than the first. /tmp is tmpfs here, so the reboot
# also destroyed the only copies of the image unit's binaries, which happened to have been
# copied to durable storage hours earlier. Nothing about "start it by hand" survives a power
# cut, and the estate had no answer to one.
#
# THE BOARD IS THE AUTHORITY
# --------------------------
# Ports are read from /models/control.board, not written here. It has been called this
# estate's port authority in five documents; the fabric reads it and so does this. A port
# changed there changes here, and a unit named there with no way to start it is REPORTED
# rather than skipped — a launcher that silently ignores what it cannot start is how a service
# stays down for a day.
#
# setsid, NOT just nohup: a background job still shares the session, and closing the terminal
# takes it. That is how these died the first time.
set -o pipefail

BOARD=${SYM_BOARD_FILE:-/mnt/models/control.board}
TREES=${SYM_TREES:-/mnt/SymonSayDistribute}
LOGS=${SYM_RUN_DIR:-$HOME/symoneural-run}/logs
DRY=0
[ "${1:-}" = "--dry-run" ] && DRY=1

mkdir -p "$LOGS"

# Units this script does NOT start, and why each. Recorded rather than omitted: a name missing
# from a launcher with no reason is indistinguishable from an oversight.
declare -A SKIP=(
  [chat]="the engine. runtime/serve-chat-unit.sh owns its ladder and its fit settings; starting it from here would duplicate that and get it wrong"
  [gateway]="served from work/runtimes/api/app by a different tree; started separately until that divergence is closed"
  [web]="a browser interface with its own build output; not a python service"
  [control_plane]="read-only and supervised elsewhere (rules R14)"
)

# Which worktree holds each unit, where its name differs from the board's.
declare -A TREE=( [store]=model-store [fabric]=adaptive-fabric )

[ -r "$BOARD" ] || { echo "no board at $BOARD — there is no port authority to read" >&2; exit 4; }

section=0; started=0; already=0; failed=0; skipped=0
while IFS= read -r line; do
  case "$line" in
    "[ports]") section=1; continue ;;
    "["*) [ $section -eq 1 ] && break ;;
  esac
  [ $section -eq 1 ] || continue
  name=$(printf '%s' "$line" | sed -n 's/^[[:space:]]*\([a-z_][a-z0-9_]*\)[[:space:]]*=.*/\1/p')
  port=$(printf '%s' "$line" | sed -n 's/^[[:space:]]*[a-z_][a-z0-9_]*[[:space:]]*=[[:space:]]*\([0-9]\{2,5\}\).*/\1/p')
  [ -n "$name" ] && [ -n "$port" ] || continue

  if [ -n "${SKIP[$name]:-}" ]; then
    printf '  %-13s %-5s skipped — %s\n' "$name" "$port" "${SKIP[$name]}"
    skipped=$((skipped+1)); continue
  fi

  if ss -ltnH "sport = :$port" 2>/dev/null | grep -q .; then
    printf '  %-13s %-5s already listening\n' "$name" "$port"
    already=$((already+1)); continue
  fi

  dir="$TREES/${TREE[$name]:-$name}"
  if [ ! -d "$dir" ]; then
    printf '  %-13s %-5s NO WORKTREE at %s\n' "$name" "$port" "$dir"
    failed=$((failed+1)); continue
  fi

  # service:app at the worktree root, or inside the unit's package (ravencalc keeps it there).
  app=""
  [ -f "$dir/service.py" ] && app="service:app"
  if [ -z "$app" ]; then
    inner=$(find "$dir" -maxdepth 2 -name service.py -not -path '*/tests/*' 2>/dev/null | head -1)
    [ -n "$inner" ] && app="$(basename "$(dirname "$inner")").service:app"
  fi
  if [ -z "$app" ]; then
    printf '  %-13s %-5s NO service.py under %s\n' "$name" "$port" "$dir"
    failed=$((failed+1)); continue
  fi

  if [ $DRY -eq 1 ]; then
    printf '  %-13s %-5s would start: %s  (cwd %s)\n' "$name" "$port" "$app" "$dir"
    continue
  fi

  ( cd "$dir" && setsid nohup python3 -m uvicorn "$app" --host 127.0.0.1 --port "$port" \
      > "$LOGS/$name.log" 2>&1 < /dev/null & ) 
  for _ in $(seq 1 20); do
    ss -ltnH "sport = :$port" 2>/dev/null | grep -q . && break
    sleep 0.5
  done
  if ss -ltnH "sport = :$port" 2>/dev/null | grep -q .; then
    printf '  %-13s %-5s started\n' "$name" "$port"; started=$((started+1))
  else
    printf '  %-13s %-5s FAILED — see %s/%s.log\n' "$name" "$port" "$LOGS" "$name"
    failed=$((failed+1))
  fi
done < "$BOARD"

echo
echo "  started $started, already up $already, skipped $skipped, failed $failed"
[ "$failed" -eq 0 ]
