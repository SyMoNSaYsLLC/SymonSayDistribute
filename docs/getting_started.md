# Getting started

What you get, what must already exist, two ways to install, and the first request. Everything
on this page was run on the reference host on 2026-09-18; where a step depends on your
hardware it says so.

## Contents

- [What you get](#what-you-get)
- [Before you start](#before-you-start)
- [Install from a release](#install-from-a-release)
- [Install from source](#install-from-source)
- [Configure](#configure)
- [Start the units](#start-the-units)
- [First request](#first-request)
- [Next steps](#next-steps)

## What you get

| Unit | What it is | Port | Ships as |
|---|---|---|---|
| gateway | the `/v1` Messages-dialect front: credential, model cards, relay | 9001 | wheel (`py3-none-any`) |
| chat unit | the engine holding the weights on the GPU | 8802 | binary (x86_64, CUDA) and the bring-up scripts |
| web | the first-party interface: chat, code, work, models, rack, settings | 8812 | source (build with the pinned lockfile) |
| image unit | text-to-image worker with the CUDA backend | 8809 | binary (x86_64, CUDA) |
| api native | the C library behind the control plane | — | shared library (x86_64, aarch64, armv7) |

Weights are **not** in any release. See [Before you start](#before-you-start).

## Before you start

**Hardware.** A GPU with 16 GB of memory holds the 20-billion-parameter MXFP4 checkpoint at a
16k served context on the reference host (compute capability 12.0, CUDA 13.4 toolkit). Less
memory means CPU offload and lower throughput; BUILD.md §4 has the measured profiles.

**Software.** Linux x86_64 (or aarch64 / armv7 for the pure-Python and C units), Python ≥ 3.11,
the CUDA 13 runtime libraries for the GPU units, `curl`. For installing from a release you
need either an authenticated `gh` or a `GITHUB_TOKEN` — the repository is private.

**Weights.** Acquire the checkpoint yourself and place it under `SYM_MODELS_DIR` as
`symon-chat/` (a symlink to the checkpoint directory is fine). The runtime reads it from that
path at start and never packages it. That directory name is a filesystem path and is
deliberately not one of the wire model ids: `SYM_CHAT_MODEL_DIR` points at the checkpoint on
disk, while `symon-sonnet` and its siblings are what a client asks for. Its licence
(Apache-2.0) and provenance are recorded in the estate's model register.

**The credential.** Generate one key and store it where `SYM_GW_KEY_FILE` points, mode 0600:

```sh
install -d -m 0700 ~/.config/symoneural
umask 077; head -c 32 /dev/urandom | base64 | tr -d '/+=' > ~/.config/symoneural/gateway-9001.key
```

Never paste it into a file that is tracked, a shell history you keep, or a chat.

## Install from a release

The installer verifies `SHA256SUMS` before installing anything:

```sh
git clone https://github.com/SyMoNSaYsLLC/symoneural-learn.git && cd symoneural-learn
tools/install-from-release.sh --dry-run                  # shows the plan for this machine
tools/install-from-release.sh                            # latest release, all units for this arch
tools/install-from-release.sh --release v1.0.0 --units gateway,image --dstdir ~/.local/bin
```

Wheels land in a virtual environment under `~/.local/share/symoneural-learn/venv` with their
console scripts linked into `--dstdir`; binary units under `~/.local/share/symoneural-learn/<unit>/`
with a launcher linked likewise. `tools/install-from-release.sh --help` lists every option.

## Install from source

```sh
git clone https://github.com/SyMoNSaYsLLC/symoneural-learn.git && cd symoneural-learn
python3 -m venv ~/.local/share/symoneural-learn/venv
~/.local/share/symoneural-learn/venv/bin/pip install ./gateway        # symoneural-gateway
```

The web interface: `cd web && corepack pnpm install --frozen-lockfile && node
node_modules/next/dist/bin/next build` (network for the lockfile-pinned dependency set). The
chat-unit engine and the image unit are built out-of-tree from the estate's pinned trees;
BUILD.md §3 has the exact commands and the measured results.

## Configure

```sh
install -m 0644 config/symoneural-learn.env.example ~/.config/symoneural/learn.env
$EDITOR ~/.config/symoneural/learn.env      # paths for this host; nothing else usually changes
set -a; . ~/.config/symoneural/learn.env; set +a
```

Every `SYM_*` variable, its default and the reason for it is in that file. Precedence:
process environment > the sourced file > the default in code.

## Start the units

In this order — the gateway fails closed until the key file exists, and answers `/health`
before the engine is up:

```sh
symoneural-chat-engine &                         # 8802: loads the checkpoint (about a minute on the reference host)
symoneural-gateway &                             # 9001
cd web && PORT=8812 HOSTNAME=127.0.0.1 node server.js &   # 8812, from the standalone build
```

`runtime/bringup-chat-unit.sh` is the ladder for the recorded substitution engine; it tries
allocator, context and throughput settings in cost order and records which rung held.

## First request

```sh
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:9001/health          # 200, no key
curl -s http://127.0.0.1:9001/v1/models -H "x-api-key: $(cat "$SYM_GW_KEY_FILE")" | python3 -m json.tool
curl -s http://127.0.0.1:9001/v1/messages -H "x-api-key: $(cat "$SYM_GW_KEY_FILE")" \
  -H 'content-type: application/json' \
  -d '{"model":"symon-sonnet","max_tokens":64,"messages":[{"role":"user","content":"In one sentence, what are you?"}]}'
```

Three model rows come back (`symon-sonnet`, `symon-opus`, `symon-fable`), and the reply names
`symon-sonnet` as its model. Any client that speaks the dialect works by pointing its base URL at
`http://127.0.0.1:9001` and supplying the key.

## Next steps

- [HTTP API](http_api.md) for every route and the error envelope.
- [Monitoring](monitoring.md) to see what the units report about themselves.
- [Performance](performance.md) for the measured numbers and `tools/bench-gateway.sh`.
- [Troubleshooting](troubleshooting.md) when a step above does not do what it says.
