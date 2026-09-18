# Troubleshooting

The traps this runtime has already paid for, each with the symptom you see, the cause, and the
fix. Ordered by how likely you are to meet them. When something new goes wrong, start with the
`x-request-id` from the gateway response and the log line that carries it.

## Contents

- [The engine exits at load with "Num GPU blocks is 0"](#the-engine-exits-at-load-with-num-gpu-blocks-is-0)
- [The engine exits with an out-of-memory error a few MiB short](#the-engine-exits-with-an-out-of-memory-error-a-few-mib-short)
- [The bring-up ladder declares a rung dead that later comes up](#the-bring-up-ladder-declares-a-rung-dead-that-later-comes-up)
- [`pkill -f` kills your own shell](#pkill--f-kills-your-own-shell)
- [A client shows no models](#a-client-shows-no-models)
- [`401` with the right key](#401-with-the-right-key)
- [`500` from every route except `/health`](#500-from-every-route-except-health)
- [`503 api_error` on `/v1/messages`](#503-api_error-on-v1messages)
- [A Python command dies with `Input/output error` before doing anything](#a-python-command-dies-with-inputoutput-error-before-doing-anything)
- [`cp` or `mv` hangs a script forever](#cp-or-mv-hangs-a-script-forever)
- [Build traps](#build-traps)

## The engine exits at load with "Num GPU blocks is 0"

**Symptom.** The release engine logs its load plan (`model_mib=13123`, "Reserving 128 MB ...
for activations") and exits: `Error: Num GPU blocks is 0. This means there is not enough
memory. Either reduce the memory amount/utilization/context size or disable PagedAttention.`

**Cause.** With no explicit KV-cache size, the planner takes a fraction of the memory it
believes available; after 13.1 GiB of weights on a 16 GiB card that leaves nothing at its
default fraction.

**Fix.** Size the KV cache explicitly: `--pa-memory-mb 1800 --max-seqs 2` holds two 16k
contexts on the reference host (about 49 KB per token for this checkpoint). The launcher's
`SYM_*` variables pass through; extra engine options can be appended to `symoneural-chat-engine`.

## The engine exits with an out-of-memory error a few MiB short

**Symptom.** The substitution engine dies during expert repacking with an allocation failure a
few MiB short of what it asked for, although the card shows free memory.

**Cause.** Allocator fragmentation, not a real shortage.

**Fix.** `PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True` (in the env example). It is the
first rung of the bring-up ladder for that reason.

## The bring-up ladder declares a rung dead that later comes up

**Symptom.** `bringup-chat-unit.sh` logs a rung as FAILED after a few seconds; the engine's own
log shows it loading weights 30 s later.

**Cause.** The launcher runs the engine's `--version` first, and during those seconds no
process matches the liveness probe. A probe that fires before the thing can be alive measures
its own timing.

**Fix.** `SYM_BRINGUP_GRACE` (default 120 s) is the wait before a rung is judged. Raise it on
slower disks.

## `pkill -f` kills your own shell

**Symptom.** A script that stops the engine with `pkill -f '<engine> serve'` exits with code
144 and does nothing else.

**Cause.** The pattern is part of the command line of the shell running it, so `pkill`
matches — and kills — that shell.

**Fix.** Stop processes by PID (`ss -ltnp` gives the PID on the port), or free the port with
`fuser -k -n tcp 8802`. Never `pkill -f` a literal that appears in your own command.

## A client shows no models

**Symptom.** `GET /v1/models` returns three rows with `curl`, but a client's model picker is
empty.

**Cause.** Clients that implement the dialect filter the list: a row survives when its id
matches one of the dialect's family patterns or carries the family-tier field. If a proxy or a
rewrite in front of the gateway strips unknown fields, the tier is lost and every `symon-*` row
is dropped.

**Fix.** Make sure the gateway's rows reach the client unmodified; check that
`anthropic_family_tier` is present in what the client receives. Do not type model names into
a client's manual model list — typed entries go through a different validator that cannot
carry the field.

## `401` with the right key

**Cause.** The key file has a trailing newline the client included, or the key was pasted
with whitespace; or the file `SYM_GW_KEY_FILE` points at is not the one you edited.

**Fix.** `tr -d '\n' < "$SYM_GW_KEY_FILE" | wc -c` should be the key's length; scripts read it
with `$(cat "$SYM_GW_KEY_FILE")`, which strips the trailing newline.

## `500` from every route except `/health`

**Cause.** The gateway is unconfigured: the key file is missing or unreadable. It fails closed
by design.

**Fix.** Create the key file (see [Getting started](getting_started.md#before-you-start)),
mode 0600, owned by the user running the gateway. No restart needed — the file is re-read per
request.

## `503 api_error` on `/v1/messages`

**Cause.** The gateway cannot reach the engine at `SYM_CHAT_URL` within
`SYM_GW_CONNECT_TIMEOUT` (2 s), or the engine closed the connection.

**Fix.** `curl http://127.0.0.1:8802/v1/models` directly. If the engine is loading, wait for it;
if it is down, bring it up; if `SYM_CHAT_URL` points elsewhere, fix the env file.

## A Python command dies with `Input/output error` before doing anything

**Symptom.** `python3 -c ...` fails in `importlib._bootstrap_external` with
`OSError: [Errno 5] Input/output error: '<directory>'`.

**Cause.** The current directory is a dead mount (a filesystem whose device vanished). Python
lists the cwd at startup.

**Fix.** `cd` to a live directory first, or run `python3 -I`. Check `/proc/mounts` for
`emergency_ro` and lazy-unmount the dead entry.

## `cp` or `mv` hangs a script forever

**Cause.** The shell aliases `cp`, `mv`, `rm` to their interactive `-i` forms; a script that
inherits the alias waits at "overwrite?" for a keypress that never comes.

**Fix.** Use `install -m MODE src dst` for copies, `\cp -f` to bypass the alias, or Python.

## Build traps

From the estate's build records (BUILD.md §7), for anyone building from source:

- `set -u` kills the OpenEmbedded environment script; the symptom is an empty build log and
  `rc=1` with no error line.
- `addtask foo` binds to a function named `do_foo`; without the prefix the task silently never
  runs.
- `git archive` honours `.gitattributes export-ignore`; an export is not always the whole tree.
- An empty `PYTHONPATH` entry (a trailing colon) means the current directory, which can shadow
  a standard-library module with a file of the same name in the source tree.
- `bb.fatal` in an anonymous `python () { }` block fails every recipe in the layer, because
  parsing runs that block on every build.
- The engine's toolkit allowlist stops at CUDA 13.3; the 13.4 toolkit is accepted via a
  one-line recipe patch (`recipes-llm/symoneural-mistralrs`) plus `CUDARC_CUDA_VERSION=13030`.
