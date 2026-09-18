# SyMoNsAyLeaRn — architecture, design, and why

The shape of the product and the reason behind each choice. It describes what is built and
running; where something is a direction rather than a fact, it says so. Every example below
is a request against this runtime, not a quotation from anyone else's documentation.

---

## 1. What the product is

An inference runtime you run on your own hardware. One GPU, one host, three loopback ports,
a public wire dialect on the front. Nothing in it calls a third-party service: the model runs
on the operator's card, the gateway binds `127.0.0.1`, and reach from outside is the
operator's edge proxy and tunnel — never an interface binding.

```
                    any client that speaks the dialect
                                │  https, via the operator's edge proxy
                                ▼
   ┌───────────────────────── host ───────────────────────────────────────┐
   │  web UI        127.0.0.1:8812   the first-party interface             │
   │      │ /gw/*                                                          │
   │      ▼                                                                │
   │  gateway       127.0.0.1:9001   /v1 dialect · credential · model cards │
   │      │ SYM_CHAT_URL                                                   │
   │      ▼                                                                │
   │  chat unit     127.0.0.1:8802   the engine, holding the weights on GPU │
   │                                                                       │
   │  control plane 127.0.0.1:8800   /api/* — units, rack, GPU lock (R14)  │
   └───────────────────────────────────────────────────────────────────────┘
```

Every address is a `SYM_*` variable with a default; `config/symoneural-learn.env.example`
is the complete list.

## 2. The wire contract — and why it is not proprietary

The gateway exposes the **Messages dialect**:

| Route | Purpose | Credential |
|---|---|---|
| `GET  /health` | liveness, answers even when nothing else is configured | none |
| `GET  /version` | the live engine facts — served context, engine, model | key |
| `GET  /v1/models` | the model cards the runtime offers | key |
| `GET  /v1/models/{id}` | one card, plus first-party provenance under `x-symoneural` | key |
| `POST /v1/messages` | one turn; `"stream": true` returns server-sent events | key |
| `POST /v1/messages/count_tokens` | token accounting for a request | key |

**Why this dialect.** It is a public specification with many independent client and server
implementations. Choosing it means every client that already speaks it works against this
runtime by changing a base URL — no plugin, no fork, no vendor lock in either direction. The
endpoint shapes are not ours and are not proprietary; what is ours, and what the licence
covers, is the implementation behind them, the model cards, the composition, and the
engine work. This runtime implements the dialect from the specification and proves
conformance with a suite that exercises it through unmodified public client libraries. No
traffic was ever sent to anyone else's inference service.

**The second dialect.** The engine layer also speaks the chat-completions dialect. The
gateway does not re-expose it today; the conformance suite covers both so that a future
engine is judged against both.

### The model-listing fact that shapes the design

Clients that implement the dialect **filter** `GET /v1/models`. A row survives when its id
matches one of the dialect's family patterns *or* the row carries the family-tier field;
ids that carry an upstream vendor's name are commonly dropped outright. Two consequences:

1. The upstream checkpoint's name is never exposed. The runtime offers its own names.
2. A first-party id (`symon-chat`) matches no family pattern, so it is selectable **only**
   because the gateway emits the tier field on every row. A plain chat-completions model
   list cannot carry it. The gateway is therefore not a convenience layer — it is the path
   by which a Symon-branded model reaches a picker at all.

The field is a protocol identifier, declared once as `FAMILY_TIER_FIELD` in `models.py`. It
states nothing about equivalence to anyone else's model.

## 3. The gateway — by example

All examples assume `set -a; . ~/.config/symoneural/learn.env; set +a` and a key in the file
`SYM_GW_KEY_FILE` names. The key is never echoed; it is read straight from the file.

**Liveness, no credential:**

```sh
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:9001/health
# 200
```

**The catalogue.** Three rows, three tiers, one default per tier:

```sh
curl -s http://127.0.0.1:9001/v1/models -H "x-api-key: $(cat "$SYM_GW_KEY_FILE")" | python3 -m json.tool
```
```json
{
  "data": [
    {"type": "model", "id": "symon-chat",  "display_name": "Symon Chat",
     "created_at": "2026-09-18T00:00:00Z", "description": "...",
     "anthropic_family_tier": "sonnet", "is_family_default": true,
     "max_input_tokens": 16384, "max_output_tokens": 4096},
    {"type": "model", "id": "symon-coder", "display_name": "Symon Coder", "...": "...",
     "anthropic_family_tier": "opus",   "is_family_default": true,
     "max_input_tokens": 16384, "max_output_tokens": 8192},
    {"type": "model", "id": "symon-work",  "display_name": "Symon Work",  "...": "...",
     "anthropic_family_tier": "fable",  "is_family_default": true,
     "max_input_tokens": 16384, "max_output_tokens": 8192}
  ],
  "has_more": false
}
```

**One turn.** The engine's own name for the checkpoint never crosses this boundary; the
response says `symon-chat` back:

```sh
curl -s http://127.0.0.1:9001/v1/messages \
  -H "x-api-key: $(cat "$SYM_GW_KEY_FILE")" -H 'content-type: application/json' \
  -d '{"model": "symon-chat", "max_tokens": 64,
       "messages": [{"role": "user", "content": "In one sentence, what are you?"}]}'
```
```json
{"id": "msg_...", "type": "message", "role": "assistant", "model": "symon-chat",
 "content": [{"type": "text", "text": "..."}],
 "stop_reason": "end_turn", "stop_sequence": null,
 "usage": {"input_tokens": 0, "output_tokens": 0}}
```

**Streaming.** Add `"stream": true`; the bytes are relayed from the engine unmodified, as
server-sent events in the dialect's event order — `message_start`, `content_block_start`,
`content_block_delta` (one per text delta), `content_block_stop`, `message_delta`,
`message_stop`:

```
event: message_start
data: {"type":"message_start","message":{"id":"msg_...","type":"message","role":"assistant","model":"symon-chat", ...}}

event: content_block_delta
data: {"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"I"}}
```

**Token accounting:**

```sh
curl -s http://127.0.0.1:9001/v1/messages/count_tokens \
  -H "x-api-key: $(cat "$SYM_GW_KEY_FILE")" -H 'content-type: application/json' \
  -d '{"model": "symon-coder", "messages": [{"role": "user", "content": "hello"}]}'
# {"input_tokens": N}
```

**Refusals use the dialect's envelope**, never a framework default, so a client that
pattern-matches on `error.type` behaves the same as it would anywhere else:

```sh
curl -s http://127.0.0.1:9001/v1/models                         # no key → 401
# {"type":"error","error":{"type":"authentication_error","message":"..."}}

curl -s http://127.0.0.1:9001/v1/messages -H "x-api-key: $(cat "$SYM_GW_KEY_FILE")" \
  -H 'content-type: application/json' -d '{"model":"not-a-card","max_tokens":1,"messages":[]}'
# 404 {"type":"error","error":{"type":"not_found_error","message":"..."}}
```

### How the gateway is built

`gateway/symoneural_gateway/` — four modules, one process, pure Python today
(FastAPI + httpx); `pip install ./gateway` gives the `symoneural-gateway` command.

| Module | Responsibility | Design rule it embodies |
|---|---|---|
| `models.py` | the three cards — `symon-chat` (tier sonnet, surface chat), `symon-coder` (opus, code), `symon-work` (fable, cowork); sampling defaults applied only where the caller left a field unset | one default per tier, one card per surface; shared weights are *stated* in `x-symoneural.shares_weights_with`, never inferred |
| `worker.py` | the client to the chat unit; connect 2 s, read 900 s | forwards rather than translates — re-deriving a wire format the engine already emits is a second implementation of one spec, and the two drift |
| `dialect.py` | the `/v1` router; error envelope; unknown models refused by name; the engine's model name rewritten to the card id on the way back; streams relayed byte-for-byte | the client never learns the checkpoint name |
| `gateway.py` | the app; `Authorization: Bearer` or `x-api-key`, constant-time comparison; key re-read from `SYM_GW_KEY_FILE` on every request | unconfigured fails closed (500); `/health` is the only public route; rotation is "replace the file" |

**Credential model.** One static key, generated by the operator, in a 0600 file outside
every repository. Code and documents name *where* it is and never *what* it is; the ship gate
fails any artifact or history blob that carries one.

## 4. The engine, and the substitution on record

The product's own engine is `symoneural-llm`. Today the chat unit is served by an
**acquired** engine (vLLM 0.27.1) from a host virtualenv — a substitution recorded under the
estate rules (§3.10), named in `GET /version`, never reported as first-party. The gateway
was written so that replacing it is a change of one address: `worker.py` reads
`SYM_CHAT_URL`, and nothing above it knows which engine answers.

The checkpoint is a 20-billion-parameter MXFP4 mixture-of-experts — 24 layers, 32 experts
with 4 active per token, 13 GB on disk — held on a 16 GB card at a 16k served context and
offered as `symon-chat`, `symon-coder`, `symon-work`. Its licence is Apache-2.0 and its
provenance is recorded in the estate's model register and the release's third-party
notices, where a licence obliges us to record it. Weights live outside every repository and
are never packaged.

**Direction (decided 2026-09-18, not yet built).** The engine and the backend move to Rust.
The evaluation in the estate (`reports/rust-engine-eval-2026-09-18.md`) names the engine selected:
it loads this checkpoint natively, keeps the MXFP4 experts 4-bit on the GPU, targets this
card's compute capability, and serves `/v1/messages` itself — conditional on a one-line
toolkit-version patch carried as a recipe patch. Its model list is chat-completions-shaped,
so the thin first-party layer (credential, cards, the tier field) remains and moves to Rust
with it. A WASM runtime in Rust (MIT) is acquired for the same reason: one language, one
toolchain, one static-linking story to audit.

## 5. The web interface

`web/` — Next.js, source only, dependency set pinned by `pnpm-lock.yaml`. It reaches the
gateway through a same-origin rewrite (`/gw/*` → `SYM_GW_URL`) and the control plane through
`/ctl/*` → `SYM_API_URL`, so no external origin appears in its configuration and the
credential never reaches the browser. Three surfaces — chat, code, work — each bound to its
card; a models view; a rack view; settings. The design language lives in `globals.css`:
depth from lightness steps, two-layer shadows and a top hairline; the brand block at the top
of that file is the only thing to edit to rebrand.

## 6. Configuration

One contract, `config/symoneural-learn.env.example`: every `SYM_*` variable the gateway,
the web UI and the bring-up scripts read, with the default the code uses. Precedence:
process environment > the sourced file > the default in code. `config/` holds declarations
the product reads and nothing else — no client application state, no host paths by
accident, no secrets, no weights. How a given client is pointed at `SYM_GW_URL` is that
client's business and deliberately not part of the product.

```sh
install -d -m 0700 ~/.config/symoneural
install -m 0644 config/symoneural-learn.env.example ~/.config/symoneural/learn.env
$EDITOR ~/.config/symoneural/learn.env          # paths for this host
set -a; . ~/.config/symoneural/learn.env; set +a
pip install ./gateway && symoneural-gateway     # 127.0.0.1:9001
```

## 7. Packaging and release

- **Wheels** (`py3-none-any`) for the gateway; **tarballs** for the bring-up scripts and the
  web source; **binaries** per architecture where a toolchain exists (x86_64, aarch64,
  armv7, i686). Wheels are built twice from clean exports with `SOURCE_DATE_EPOCH` and must
  match byte-for-byte.
- **The ship gate** (`tools/ship-gate.py`, policy `tools/ship-gate-policy.json`) runs over
  the staged artifacts and the repository history before anything is published: licence
  class of every component in every closure (strong, network, weak, use-restricted,
  proprietary, unknown), attribution present, no secrets by content or path, no weights,
  no third-party marks in artifact names, no HIGH/CRITICAL known vulnerabilities, no
  August-2026 inputs. `tools/cut-release.sh` refuses to publish unless the gate exits 0.
- **Images.** The estate packages the product as an OpenEmbedded image. The recipes here
  document that packaging and build inside the estate's layer, not standalone. A
  non-copyleft image requires distro-policy work (the busybox userland → toybox, no runtime
  package manager, GPL-2 excluded) that is in progress and not yet proven; release notes say
  which artifacts are shipped and which are not.

## 8. Licence position

FSL-1.1-ALv2: proprietary, source-available, Apache-2.0 two years after each release.
Licensor SymonSaysLLC. It covers the first-party implementation in this repository. It does
not cover the wire dialect (public), the weights (Apache-2.0, acquired separately), or any
third-party component a build pulls in — each keeps its own licence, recorded per recipe with
a checksum of its text. `NOTICE` states the boundary; the ship gate enforces it.

## 9. Rules the design obeys

- **Evidence, not assertion.** A route is BUILT when a consumer has exercised it and the
  evidence is recorded; a plan or a commit message is not evidence.
- **The API is fixed; the force behind it is swappable.** Nothing above `worker.py` knows
  the engine.
- **Never a third-party inference service.** The product's own runtimes are the product.
- **No other company in our code** unless a law or a licence requires it (rules §3.11).
  Protocol identifiers are constants; hardware is described by capability; other people's
  code is never pasted in.
- **Loopback by design.** Public reach is the operator's proxy, never a binding.
- **No secret, no weight, no personal identifier in any repository** — enforced by pattern.
- **Upstream source is read-only.** Builds run out-of-tree from pinned, checksummed trees.
