# Command line

Everything you type, in one place: the unit launchers and the tools. Each entry names its
source file, so the code is one hop away.

## Contents

- [Units](#units)
- [Tools](#tools)
- [Environment](#environment)

## Units

### `symoneural-gateway` — the `/v1` front (`gateway/`)

Installed by the gateway wheel. Reads its configuration from the environment and serves
`127.0.0.1:9001` until stopped.

```sh
symoneural-gateway                 # SYM_GW_HOST, SYM_GW_PORT, SYM_GW_KEY_FILE, SYM_CHAT_URL, SYM_LOG_LEVEL
python -m symoneural_gateway.gateway   # the same, from a checkout
```

### `symoneural-chat-engine` — the chat unit (release binary, x86_64 CUDA)

Serves the checkpoint on `127.0.0.1:8802`. The launcher forwards the `SYM_*` variables to the
engine and passes any further arguments through.

```sh
symoneural-chat-engine                         # SYM_CHAT_MODEL_DIR, SYM_CHAT_PORT, SYM_MAX_MODEL_LEN, SYM_MAX_SEQS
symoneural-chat-engine --paged-attn on         # extra engine options pass through
```

### `bringup-chat-unit.sh` and `serve-chat-unit.sh` — the recorded substitution (`runtime/`)

The ladder that brings the substitution engine up on a card where the first attempt does not
fit: allocator → context → throughput rungs, each tried in cost order, each recorded under
`SYM_RUN_DIR/logs`. `SYM_BRINGUP_GRACE` (120 s) is the time the ladder waits before judging a
rung dead — the engine prints its version before anything listens.

```sh
runtime/bringup-chat-unit.sh                   # tries the rungs, leaves the first that holds running
runtime/serve-chat-unit.sh                     # one engine, one configuration, foreground
```

### `symoneural-image` — the image unit worker (release binary, x86_64 CUDA)

A launcher that puts the unit's own library on the loader path and runs the worker.

```sh
symoneural-image --help
symoneural-image --version                     # prints the worker's version and pin
```

## Tools

| Command | Does | Exit codes |
|---|---|---|
| `tools/install-from-release.sh [--release TAG] [--units a,b] [--dstdir D] [--home H] [--dry-run]` | fetches a release's assets (through `gh` or `GITHUB_TOKEN`), verifies every one against `SHA256SUMS`, installs wheels into a venv and binaries under `--home`, links launchers into `--dstdir` | 2 usage · 3 arch · 7 fetch · 8 verification failed · 9–10 install |
| `tools/bench-gateway.sh [--duration 30s] [--workers 4] [--max-tokens 128] [--model symon-chat] [--out DIR]` | five timed stages against the live gateway; writes `bench-<ts>.json` and `.md` | 3 no key file · 4 gateway not answering |
| `tools/ship-gate.py --stage DIR [--repo DIR] [--json OUT]` | the release gate: licence class of every component in every closure, attribution, secrets by content and path, weights, trademarks, known vulnerabilities, August-dated inputs; re-derives every census itself | 0 pass/review · 1 any FAIL |
| `tools/ship-gate.py --repo .` | the same gate over every blob in the repository's history | as above |
| `tools/cut-release.sh TAG STAGE [--dry-run] [--prerelease]` | publishes a staged release only when the tag equals HEAD, the tree is clean, `SHA256SUMS` verifies and the gate passes; names assets per architecture | 3 tag/tree · 4 stage · 5 gate · 6 layout · 7 exists · 8 gh |
| `tools/licence-audit.py --check` | proves what licence each shipped package carries in the estate's image build; exit 1 if strong copyleft ships | 0/1 |

Run any of them with `--help` for the full option list.

## Environment

All configuration is environment, declared once in
[`config/symoneural-learn.env.example`](../config/symoneural-learn.env.example):

```sh
set -a; . ~/.config/symoneural/learn.env; set +a
```

The variables the commands above read: `SYM_GW_HOST` `SYM_GW_PORT` `SYM_GW_KEY_FILE`
`SYM_GW_URL` `SYM_API_URL` `SYM_CHAT_URL` `SYM_CHAT_WORKER_MODEL` `SYM_CHAT_PORT` `SYM_CHAT_MODEL_DIR`
`SYM_CHAT_ENGINE_VENV` `SYM_CHAT_SERVED_NAME` `SYM_MODELS_DIR` `SYM_MAX_MODEL_LEN`
`SYM_MAX_SEQS` `SYM_GPU_FRACTION` `SYM_CPU_OFFLOAD_GB` `SYM_BRINGUP_GRACE` `SYM_RUN_DIR`
`SYM_GW_CONNECT_TIMEOUT` `SYM_GW_READ_TIMEOUT` `SYM_LOG_LEVEL`.
