# Monitoring

What each unit reports about itself, where it writes, and how to read the bring-up ladder.
Nothing here needs a credential except the routes marked so.

This page describes what is **running**, with one exception marked in place: the control plane
on `127.0.0.1:8800` is supervised elsewhere and was not answering when this page was last
checked, so treat its rows as the contract it serves when up, not as a live surface.

## Contents

- [Liveness and readiness](#liveness-and-readiness)
- [What the engine is actually doing](#what-the-engine-is-actually-doing)
- [Request ids](#request-ids)
- [Logs](#logs)
- [The bring-up ladder's record](#the-bring-up-ladders-record)
- [The GPU](#the-gpu)
- [The rack view](#the-rack-view)

## Liveness and readiness

| Probe | Credential | Meaning |
|---|---|---|
| `GET http://127.0.0.1:9001/health` | none | the gateway process is up. Answers `200 {"status":"ok"}` even when the key file is missing and every unit is down — it is the one route that must always answer |
| `GET http://127.0.0.1:9001/ready` | key | the gateway can reach the engine and lists the three models; `200 {"status":"ready", ...}` |
| `GET http://127.0.0.1:8802/v1/models` | none (loopback) | the engine itself is answering |
| `GET http://127.0.0.1:3000/` | none | the web interface is serving |

```sh
for p in 9001/health 3000/; do curl -s -o /dev/null -w "$p %{http_code}\n" http://127.0.0.1:$p; done
curl -s -H "x-api-key: $(cat "$SYM_GW_KEY_FILE")" http://127.0.0.1:9001/ready
```

## What the engine is actually doing

`GET /version` (key) re-reads the live engine's own facts rather than repeating configuration:
the served context length, the engine identity, and the model it reports. When the number the
gateway was configured with (`SYM_MAX_MODEL_LEN`) and the number the engine is running with
differ, this is where the drift shows.

## Request ids

Every gateway response carries `x-request-id`. Quote it when reporting a problem; the gateway
log line for that request carries the same id.

## Logs

| Unit | Where | What |
|---|---|---|
| gateway | stdout/stderr of `symoneural-gateway` (`SYM_LOG_LEVEL`, default `info`) | one line per request with status, path, request id, upstream latency; never the key, never request bodies |
| chat unit (release engine) | stdout/stderr of `symoneural-chat-engine` | load plan (weights, device mapping, KV cache), then per-request lines |
| chat unit (substitution ladder) | `SYM_RUN_DIR/logs/chat-unit.log`, `chat-unit-bringup.log` | the engine's own log, and the ladder's record of every rung tried |
| web | stdout of `node server.js` | Next.js request log |

`SYM_RUN_DIR` defaults to `~/symoneural-run`.

## The bring-up ladder's record

`runtime/bringup-chat-unit.sh` records, in `chat-unit-bringup.log`, each rung's settings, the
time it waited, and whether the engine answered. A rung is only judged dead after
`SYM_BRINGUP_GRACE` seconds (120 by default), because the engine prints its version and loads
weights before anything listens — a probe that fires earlier measures its own impatience. The
rung that held is the configuration to write into `learn.env`.

## The GPU

```sh
nvidia-smi --query-gpu=memory.used,memory.total,utilization.gpu --format=csv,noheader
nvidia-smi --query-compute-apps=pid,process_name,used_memory --format=csv,noheader
```

On the reference host the substitution engine holds about 15.8 GiB of the card's 15.92 GiB
(16303 MiB, measured with `nvidia-smi --query-gpu=memory.total`) with 3 GB of weights
offloaded to the host; roughly 1 GB is held by other processes when the chat unit is down.
An engine that plans its KV cache against the card's total rather than what is free will
report "not enough memory" at load — see [Troubleshooting](troubleshooting.md).

## The rack view

The web interface's **rack** page shows every unit's port, state and last probe, read through
the control plane (`SYM_API_URL`, `127.0.0.1:8800`, `/api/*`). The control plane is read-only
and demo-critical (estate rule R14): the rack view observes it and never changes it.
