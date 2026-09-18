# HTTP API

The gateway on `127.0.0.1:9001` serves the **Messages dialect** — a public wire format with
many independent client and server implementations — under SyMoNsAyLeaRn's own model names.
The endpoint shapes are the dialect's; the implementation, the model cards and the engine are
ours. Every example on this page was taken against this runtime.

## Contents

- [Base URL and credential](#base-url-and-credential)
- [Routes](#routes)
- [Model rows and the family-tier field](#model-rows-and-the-family-tier-field)
- [Messages](#messages)
- [Streaming](#streaming)
- [Token counting](#token-counting)
- [Errors](#errors)
- [Conformance](#conformance)

## Base URL and credential

Base URL `http://127.0.0.1:9001`. Loopback is the design: public reach is the operator's edge
proxy and tunnel, never an interface binding.

Every route except `/health` requires the key, sent either way:

```
x-api-key: <key>
Authorization: Bearer <key>
```

The key is compared in constant time and re-read from the file `SYM_GW_KEY_FILE` names on every
request, so rotation is "replace the file". An unconfigured gateway (no key file) answers
`500` in the error envelope rather than opening up.

## Routes

| Method and path | Credential | Answer |
|---|---|---|
| `GET /health` | none | `200 {"status":"ok"}`, with an `x-request-id` header |
| `GET /ready` | key | `200 {"status":"ready", ...}` naming the three models once the engine answers |
| `GET /version` | key | the live engine facts: served context, engine identity, model — re-read from the engine so drift is reported, not assumed |
| `GET /v1/models` | key | `{"data":[...three rows...], "has_more": false}` |
| `GET /v1/models/{id}` | key | one row plus first-party provenance under `x-symoneural` |
| `POST /v1/messages` | key | one turn; `"stream": true` returns server-sent events |
| `POST /v1/messages/count_tokens` | key | `{"input_tokens": N}` |
| anything else under `/v1` | key | `404` in the error envelope |

## Model rows and the family-tier field

```sh
curl -s http://127.0.0.1:9001/v1/models -H "x-api-key: $(cat "$SYM_GW_KEY_FILE")"
```

```json
{"type": "model", "id": "symon-sonnet", "display_name": "Symon Chat",
 "created_at": "2026-09-18T00:00:00Z",
 "description": "Quick questions and drafting, served from this host.",
 "anthropic_family_tier": "sonnet", "is_family_default": true,
 "max_input_tokens": 16384, "max_output_tokens": 4096}
```

Three cards, three tiers, one default per tier:

| id | tier | surface | max output |
|---|---|---|---|
| `symon-sonnet` | sonnet | chat | 4096 |
| `symon-opus` | opus | code | 8192 |
| `symon-fable` | fable | cowork | 8192 |

Clients that implement the dialect filter this list: a row survives when its id matches one of
the dialect's family patterns *or* carries the family-tier field. No `symon-*` id matches a
family pattern, so the field is what makes a first-party model selectable at all. It is a
protocol identifier — declared once as `FAMILY_TIER_FIELD` in `models.py` — and says nothing
about equivalence to anyone else's model.

`GET /v1/models/symon-chat` adds:

```json
"x-symoneural": {"surface": "chat", "unit": "chat", "worker_model": "symon-ai",
  "upstream": "20B MXFP4 mixture-of-experts, 24 layers, 32 experts, 4 active; provenance in the estate model register",
  "licence": "Apache-2.0", "shares_weights_with": ["symon-opus", "symon-fable"]}
```

Shared weights are stated, never inferred: today all three cards resolve to one engine.

## Messages

```sh
curl -s http://127.0.0.1:9001/v1/messages -H "x-api-key: $(cat "$SYM_GW_KEY_FILE")" \
  -H 'content-type: application/json' \
  -d '{"model":"symon-sonnet","max_tokens":64,
       "messages":[{"role":"user","content":"In one sentence, what are you?"}]}'
```

The response is the dialect's message object with `"model": "symon-sonnet"` — the engine's own
name for the checkpoint never crosses this boundary. Sampling defaults from the model card
(`temperature`, `top_p`, an output cap) apply only to fields the request left unset; an explicit
value always wins. `max_tokens` above the card's cap is clamped to it.

Unknown model ids are refused by name with `404 not_found_error`, including the upstream
checkpoint's own name.

## Streaming

Add `"stream": true`. The gateway relays the engine's bytes unmodified as server-sent events
(`content-type: text/event-stream`, `x-accel-buffering: no`), in the dialect's order:
`message_start`, `content_block_start`, `content_block_delta` (one per text delta),
`content_block_stop`, `message_delta`, `message_stop`.

```
event: message_start
data: {"type":"message_start","message":{"id":"msg_...","type":"message","role":"assistant", ...}}

event: content_block_delta
data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"I"}}
```

Measured on the reference host: first event in 370 ms (see [Performance](performance.md)).

## Token counting

```sh
curl -s http://127.0.0.1:9001/v1/messages/count_tokens -H "x-api-key: $(cat "$SYM_GW_KEY_FILE")" \
  -H 'content-type: application/json' \
  -d '{"model":"symon-opus","messages":[{"role":"user","content":"hello"}]}'
# {"input_tokens": 82}   ← the number includes the dialect's message framing
```

## Errors

Always the dialect's envelope — never a framework default — so a client that pattern-matches on
`error.type` behaves as it would anywhere:

```json
{"type": "error", "error": {"type": "authentication_error", "message": "..."}}
```

| Situation | Status | `error.type` |
|---|---|---|
| missing or wrong key | 401 | `authentication_error` |
| unknown model or route | 404 | `not_found_error` |
| malformed request | 400 | `invalid_request_error` |
| engine unreachable | 503 | `api_error` |
| gateway without a key file | 500 | `api_error` |

## Conformance

The estate keeps a suite of 51 assertions that exercises this gateway with unmodified public
client libraries for the Messages dialect and the chat-completions dialect. It is the
measurable definition of "the implementation changed but the contract did not", and it runs
before any engine is swapped behind `/v1`. Its result for each release is recorded in the
release notes.
