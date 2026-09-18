#!/usr/bin/env bash
# SPDX-License-Identifier: FSL-1.1-ALv2
# Copyright 2026 SymonSaysLLC
# SyMoNsAyLeaRn — SyMoNeuRaL, a subdivision of SymonSaysLLC. Terms: see LICENSE.
#
# bench-gateway — the measured numbers a release carries, taken through the gateway.
#
#   tools/bench-gateway.sh [--url http://127.0.0.1:9001] [--model symon-chat] [--duration 30s]
#                          [--workers 4] [--max-tokens 128] [--out DIR] [--quiet]
#
# Five stages, each timed and recorded, against the live gateway with the operator's key
# (read from SYM_GW_KEY_FILE, never printed):
#   1. catalogue     GET /v1/models, /v1/models/{id}, /version — latency, N requests
#   2. count_tokens  POST /v1/messages/count_tokens — latency
#   3. single-stream POST /v1/messages non-streaming, one at a time for --duration:
#                    requests, output tokens, tokens/s, p50/p95 latency
#   4. streaming     one streaming request: time to first event, time to last, event count
#   5. concurrent    --workers parallel non-streaming requests for --duration: aggregate tokens/s
# Output: <out>/bench-<timestamp>.json (machine-readable) and .md (the table for release notes).
# Nothing here changes the gateway or the engine; it is a client.
set -o pipefail
url=${SYM_GW_URL:-http://127.0.0.1:9001}; model=symon-chat; duration=30s; workers=4; max_tokens=128; out=${SYM_BENCH_OUT:-$PWD/bench}; quiet=0
while (( $# )); do case "$1" in
  --url) url=$2; shift 2;; --model) model=$2; shift 2;; --duration) duration=$2; shift 2;; --workers) workers=$2; shift 2;;
  --max-tokens) max_tokens=$2; shift 2;; --out) out=$2; shift 2;; --quiet) quiet=1; shift;;
  -h|--help) sed -n '6,22p' "$0" | sed 's/^# \{0,1\}//'; exit 0;; *) echo "unknown argument: $1" >&2; exit 2;; esac; done
keyfile=${SYM_GW_KEY_FILE:-$HOME/.config/symoneural/gateway-9001.key}
[ -r "$keyfile" ] || { echo "key file not readable: $keyfile" >&2; exit 3; }
case "$duration" in *m) dsec=$(( ${duration%m} * 60 ));; *s) dsec=${duration%s};; *) dsec=$duration;; esac
mkdir -p "$out"; ts=$(date +%Y%m%d-%H%M%S); J=$out/bench-$ts.json; M=$out/bench-$ts.md; tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
say() { [ $quiet -eq 1 ] || echo "$@"; }
auth() { curl -sS -o "$1" -w '%{http_code} %{time_total}\n' -H "x-api-key: $(cat "$keyfile")" "${@:2}"; }
now_ms() { date +%s%3N; }

say "== bench: $url model=$model duration=$duration workers=$workers max_tokens=$max_tokens"
curl -sf -o /dev/null "$url/health" || { echo "gateway not answering at $url" >&2; exit 4; }

# 1. catalogue ---------------------------------------------------------------------------------
lat=(); for i in $(seq 1 20); do r=$(auth /dev/null "$url/v1/models"); lat+=("${r#* }"); done
models_p50=$(printf '%s\n' "${lat[@]}" | sort -n | sed -n '10p'); version_body=$(auth "$tmp/version.json" "$url/version" | cut -d' ' -f1)
say "1. catalogue: /v1/models p50 ${models_p50}s over 20; /version -> $version_body"

# 2. count_tokens ------------------------------------------------------------------------------
body='{"model":"'$model'","messages":[{"role":"user","content":"Describe, in three sentences, how you allocate attention across a long document."}]}'
r=$(auth "$tmp/ct.json" -H 'content-type: application/json' -d "$body" "$url/v1/messages/count_tokens"); ct_code=${r% *}; ct_lat=${r#* }
ct_tokens=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("input_tokens","?"))' "$tmp/ct.json" 2>/dev/null)
say "2. count_tokens: $ct_code in ${ct_lat}s -> $ct_tokens input tokens"

# 3. single-stream -----------------------------------------------------------------------------
req='{"model":"'$model'","max_tokens":'$max_tokens',"temperature":0.7,"messages":[{"role":"user","content":"Write a short paragraph about a lighthouse keeper who repairs radios."}]}'
n=0; toks=0; lats=(); t_end=$(( $(date +%s) + dsec )); s_start=$(now_ms)
while [ "$(date +%s)" -lt "$t_end" ]; do
  r=$(auth "$tmp/m.json" -H 'content-type: application/json' -d "$req" "$url/v1/messages"); code=${r% *}; l=${r#* }
  [ "$code" = 200 ] || { say "   request failed: $code"; break; }
  o=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["usage"]["output_tokens"])' "$tmp/m.json"); n=$((n+1)); toks=$((toks+o)); lats+=("$l")
done
s_wall=$(( ($(now_ms) - s_start) ))
single_tps=$(python3 -c "print(round($toks / max($s_wall,1) * 1000, 1))")
p50=$(printf '%s\n' "${lats[@]}" | sort -n | awk '{a[NR]=$1} END{print a[int(NR*0.5)+1]}'); p95=$(printf '%s\n' "${lats[@]}" | sort -n | awk '{a[NR]=$1} END{print a[int(NR*0.95)+1]}')
say "3. single-stream: $n requests, $toks output tokens in ${s_wall}ms -> $single_tps tok/s; latency p50 ${p50}s p95 ${p95}s"

# 4. streaming ---------------------------------------------------------------------------------
sreq='{"model":"'$model'","max_tokens":'$max_tokens',"stream":true,"messages":[{"role":"user","content":"Count from one to twenty in words."}]}'
st0=$(now_ms); first=""; events=0
while IFS= read -r line; do case "$line" in event:*) events=$((events+1)); [ -z "$first" ] && first=$(( $(now_ms) - st0 ));; esac; done < <(curl -sN -H "x-api-key: $(cat "$keyfile")" -H 'content-type: application/json' -d "$sreq" "$url/v1/messages")
st_total=$(( $(now_ms) - st0 )); say "4. streaming: first event ${first:-?}ms, last ${st_total}ms, $events events"

# 5. concurrent --------------------------------------------------------------------------------
c_start=$(now_ms); : > "$tmp/conc.txt"
for w in $(seq 1 "$workers"); do ( t_end=$(( $(date +%s) + dsec )); while [ "$(date +%s)" -lt "$t_end" ]; do
    r=$(auth "$tmp/c$w.json" -H 'content-type: application/json' -d "$req" "$url/v1/messages"); [ "${r% *}" = 200 ] || break
    python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["usage"]["output_tokens"])' "$tmp/c$w.json" >> "$tmp/conc.txt"; done ) & done; wait
c_wall=$(( $(now_ms) - c_start )); c_n=$(wc -l < "$tmp/conc.txt"); c_toks=$(awk '{s+=$1} END{print s+0}' "$tmp/conc.txt")
conc_tps=$(python3 -c "print(round($c_toks / max($c_wall,1) * 1000, 1))")
say "5. concurrent x$workers: $c_n requests, $c_toks output tokens in ${c_wall}ms -> $conc_tps tok/s aggregate"

# record ---------------------------------------------------------------------------------------
python3 - "$J" "$M" <<PY
import json, sys, datetime
j = {"timestamp": "$ts", "url": "$url", "model": "$model", "duration_s": $dsec, "workers": $workers, "max_tokens": $max_tokens,
     "version": json.load(open("$tmp/version.json")) if "$version_body" == "200" else None,
     "catalogue_p50_s": float("${models_p50:-0}"), "count_tokens": {"status": $ct_code, "latency_s": float("$ct_lat"), "input_tokens": "$ct_tokens"},
     "single_stream": {"requests": $n, "output_tokens": $toks, "wall_ms": $s_wall, "tokens_per_s": $single_tps, "p50_s": float("${p50:-0}"), "p95_s": float("${p95:-0}")},
     "streaming": {"first_event_ms": ${first:-0}, "total_ms": $st_total, "events": $events},
     "concurrent": {"workers": $workers, "requests": $c_n, "output_tokens": $c_toks, "wall_ms": $c_wall, "tokens_per_s": $conc_tps}}
open(sys.argv[1], "w").write(json.dumps(j, indent=1) + "\n")
md = f"""| stage | result |
|---|---|
| catalogue | /v1/models p50 {j['catalogue_p50_s']:.3f} s |
| count_tokens | {j['count_tokens']['latency_s']:.3f} s, {j['count_tokens']['input_tokens']} input tokens |
| single-stream | {j['single_stream']['requests']} requests, {j['single_stream']['tokens_per_s']} tok/s, p50 {j['single_stream']['p50_s']:.2f} s, p95 {j['single_stream']['p95_s']:.2f} s |
| streaming | first event {j['streaming']['first_event_ms']} ms, {j['streaming']['events']} events in {j['streaming']['total_ms']} ms |
| concurrent x{j['workers']} | {j['concurrent']['requests']} requests, {j['concurrent']['tokens_per_s']} tok/s aggregate |
"""
open(sys.argv[2], "w").write(f"# bench {j['timestamp']} — {j['model']} via {j['url']}\\n\\n" + md)
print(md)
PY
say "records: $J  $M"
