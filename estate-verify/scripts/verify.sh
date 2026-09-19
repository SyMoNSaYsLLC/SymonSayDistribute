#!/usr/bin/env bash
# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
#
# verify — what is actually running right now, with the evidence for each answer.
#
#   scripts/verify.sh [--deep]
#
# Every line is a probe, not a recollection. The estate's recurring failure is a status board
# that was true when it was written; this is only ever true at the moment it runs, and says so.
# --deep additionally sends a real completion through the gateway, which is slow and is the
# only check that proves the whole path rather than its parts.
set -o pipefail
DEEP=0; [ "${1:-}" = "--deep" ] && DEEP=1
ok=0; bad=0
say() { printf '  %-10s %-34s %s\n' "$1" "$2" "$3"; [ "$1" = "up" ] && ok=$((ok+1)) || bad=$((bad+1)); }

echo "host $(hostname)  $(date -Is)"
echo
echo "listeners"
for spec in "9001:gateway, the Messages dialect" "8802:chat unit, the model" "8800:control plane (read-only, supervised elsewhere)" "3000:web console"; do
  port=${spec%%:*}; what=${spec#*:}
  pid=$(ss -ltnp 2>/dev/null | grep ":$port " | grep -oE 'pid=[0-9]+' | head -1 | cut -d= -f2)
  if [ -n "$pid" ]; then
    say "up" "$port  $what" "pid $pid"
  else
    say "down" "$port  $what" "nothing listening"
  fi
done

echo
echo "gateway behaviour"
code=$(curl -s -o /dev/null -w '%{http_code}' -m 5 http://127.0.0.1:9001/health 2>/dev/null)
[ "$code" = 200 ] && say "up" "/health" "200" || say "down" "/health" "${code:-no answer}"
code=$(curl -s -o /dev/null -w '%{http_code}' -m 5 http://127.0.0.1:9001/v1/models 2>/dev/null)
[ "$code" = 401 ] && say "up" "/v1/models unauthenticated" "401, refuses correctly" \
                  || say "down" "/v1/models unauthenticated" "${code:-no answer} — expected 401"

KEY=${SYM_GW_KEY_FILE:-$HOME/.config/symoneural/gateway-9001.key}
if [ -r "$KEY" ]; then
  models=$(curl -s -m 8 -H "authorization: Bearer $(cat "$KEY")" http://127.0.0.1:9001/v1/models 2>/dev/null \
    | python3 -I -c 'import json,sys
try: d=json.load(sys.stdin)
except Exception: print(""); raise SystemExit
print(",".join(m.get("id","?") for m in d.get("data",[])))' 2>/dev/null)
  [ -n "$models" ] && say "up" "models offered" "$models" || say "down" "models offered" "none returned"
else
  printf '  %-10s %-34s %s\n' "skipped" "authenticated probes" "no credential at $KEY"
fi

echo
echo "gpu"
if command -v nvidia-smi >/dev/null 2>&1; then
  printf '  %-10s %-34s %s\n' "" "memory" "$(nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader)"
  apps=$(nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader 2>/dev/null)
  # A process name here can be a browser command line hundreds of characters long, which
  # buries the one number that matters. Cut it to the binary and the memory.
  if [ -n "$apps" ]; then
    echo "$apps" | while IFS=, read -r pid name mem; do
      printf '             holding: %-28s %s (pid%s)\n' "$(basename "$(echo "$name" | awk '{print $1}')")" "$(echo "$mem" | xargs)" "$pid"
    done
  else
    echo "             nothing holding the card"
  fi
else
  echo "             no nvidia-smi on this host"
fi

if [ $DEEP -eq 1 ] && [ -r "$KEY" ]; then
  echo
  echo "a real completion (slow — this is the only check that proves the whole path)"
  out=$(curl -s -m 300 -X POST http://127.0.0.1:9001/v1/messages \
    -H "authorization: Bearer $(cat "$KEY")" -H 'content-type: application/json' \
    -d '{"model":"symon-sonnet","max_tokens":48,"messages":[{"role":"user","content":"Reply with exactly: READY"}]}' 2>/dev/null \
    | python3 -I -c 'import json,sys
try: d=json.load(sys.stdin)
except Exception: print("unparseable"); raise SystemExit
t="".join(b.get("text","") for b in d.get("content",[]) if b.get("type")=="text").strip()
print(f"{d.get(\"model\")} {d.get(\"stop_reason\")} {t[:40]!r}" if t else "no text block")' 2>/dev/null)
  case "$out" in ""|unparseable|"no text block") say "down" "completion" "${out:-no answer}";; *) say "up" "completion" "$out";; esac
fi

echo
echo "$ok up, $bad down — true as of $(date -Is), and only then."
[ $bad -eq 0 ] || exit 1
