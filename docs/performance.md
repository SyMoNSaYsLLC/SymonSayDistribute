# Performance

Measured numbers, how they were taken, and what changes them. Every figure names the engine
that produced it — the recorded substitution engine and the estate's own build are different
things and are never averaged together.

## Contents

- [How the numbers are taken](#how-the-numbers-are-taken)
- [Reference host](#reference-host)
- [Baseline — the substitution engine](#baseline--the-substitution-engine)
- [The estate's own engine](#the-estates-own-engine)
- [What changes the numbers](#what-changes-the-numbers)

## How the numbers are taken

`tools/bench-gateway.sh` runs five timed stages **through the gateway** — so the numbers include
the credential check and the relay, which is what a client experiences:

1. catalogue — `GET /v1/models` ×20, p50 latency
2. count_tokens — one request, latency and the count
3. single-stream — non-streaming requests one at a time for `--duration`: tokens/s, p50/p95
4. streaming — one streaming request: time to first event, total, event count
5. concurrent — `--workers` parallel requests for `--duration`: aggregate tokens/s

It writes `bench-<timestamp>.json` and `.md`; the markdown table goes into the release notes,
the JSON into the estate's `production/bench/` as evidence.

```sh
tools/bench-gateway.sh --duration 30s --workers 4 --max-tokens 128 --out ./bench
```

## Reference host

One 16 GB card, compute capability 12.0, CUDA 13.4 toolkit; 8 CPU threads available to the
runtime (cgroup-pinned); 94 GB RAM; the 20-billion-parameter MXFP4 checkpoint (13 GB on disk),
served context 16,384.

## Baseline — the substitution engine

Recorded 2026-09-18 08:13, `production/bench/bench-20260918-081351.json`. The acquired engine
runs with 3 GB of weights offloaded to the host to fit the card, which is what the throughput
reflects.

| stage | result |
|---|---|
| catalogue | `/v1/models` p50 **3 ms** |
| count_tokens | **8.6 ms**, 82 input tokens |
| single-stream (48-token replies) | **6.5 tok/s**, p50 7.44 s per reply |
| streaming | first event **370 ms**, 51 events in 7.25 s |
| concurrent ×2 | **8.8 tok/s** aggregate |

The gateway's own overhead is the catalogue and count_tokens rows: single-digit milliseconds.
Everything else is the engine.

## The estate's own engine

Built 2026-09-18 (`symoneural-chat-engine`, 74 sm_120a kernels, MXFP4 kept 4-bit on the GPU, no
host offload). It loaded the checkpoint in 6 s with an explicit 820 MB KV cache and served the
dialect through the unchanged gateway at **136 tok/s single-stream, 150 tok/s at two workers,
first streamed event 35 ms** (`bench-20260918-082649.json`) — and **decoded garbage** — on the card and, in a second test, on the CPU path of the same build: a raw
completion of "The capital of France is" at temperature 0 came back as unrelated words. The
defect is the engine's model implementation for this checkpoint at the pinned commit, not the
GPU kernels or the toolkit. Those throughput figures
are therefore the speed of a wrong answer and are **not a performance number for the product**.
The engine is staged as built-unverified; the defect, its isolation and the next tests are in
the estate's `production/cutover/CUTOVER-2026-09-18.md`. The substitution engine was restored.

| stage | result |
|---|---|
| any | not recorded until the decode is correct |

## What changes the numbers

- **Host offload.** Every GB of weights on the host instead of the card costs throughput out of
  proportion to its size; the baseline's 6.5 tok/s is dominated by it. An engine that keeps the
  4-bit experts resident is the fix, not a bigger card.
- **KV cache size** (`--pa-memory-mb`, `SYM_MAX_SEQS`) trades concurrency against the memory
  left after weights.
- **Served context** (`SYM_MAX_MODEL_LEN`): lower is cheaper per sequence; the card, not the
  checkpoint's 131k maximum, sets it.
- **`max_tokens`** in the request: the bench uses short replies; long replies raise tokens/s
  as prefill amortises.
- **The gateway** adds milliseconds, measured, and relays streams byte-for-byte; it is not
  where time goes.
