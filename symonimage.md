# symonimage

Serving symon-imager, on a card it has to share.

This page describes what is **built and tested**: 18 tests pass, and the refusal this unit
exists for was exercised against the live card before this was written. It is not yet running
as a service — see **Status** at the end.

## The constraint that shapes the whole unit

There is one card, 15.92 GiB. The chat engine holds roughly 13.75 GiB of it while it is
serving. These weights are 11.80 GiB.

**They do not co-fit.** That is not a tuning problem to be solved with a smaller batch; it is
arithmetic, and no amount of configuration changes it.

So this refuses to start a generation it cannot finish, rather than dying in an allocator
thirty seconds into a run somebody is waiting on. Live output, with the engine up:

    free 0.96 GiB vs need 11.8 GiB -> enough: False
    why: 11.8 GiB of weights against 0.96 GiB free; VLLM::EngineCore (pid 20271) holds
         13.75 GiB. One card: these do not co-fit...

A refusal that names the process holding the card is something an operator can act on. An
out-of-memory traceback from a CUDA allocator is not.

## Why this unit exists at all

The chat unit had a server. This model had a **command-line program and nothing in front of
it**, so nothing in the estate could reach it — not the fabric, not the agents runtime, not
symon. The capability was on disk and unreachable, which is the shape of failure the
`endpoints-current` gate was written for.

## The program is a program, never a shell string

The image runtime is invoked with an argument vector. A prompt is caller text and it goes to a
model; the day it also reaches a shell is the day a prompt becomes a command. There is no code
path here that builds a command line by concatenation, and a test asserts `shell=True` appears
nowhere in `generate`.

## Nothing that commits the card has a default

`steps`, `width` and `height` are required. They decide what the card is asked to hold and for
how long, and a default there is a number nobody chose committing the one card for minutes.
`skip_room_check` exists for an operator who knows the card is theirs, and defaults to `False`
— the safe branch is the default, because the unsafe one wastes somebody else's work.

## Where the binary is

Not assumed. `SYM_IMAGE_BIN` names it. The default points at the tree recovered on 2026-09-19
from `/tmp/.Trash-1000` — which is tmpfs, so that morning's reboot would have destroyed it.
It reports `master-859-7f410a3, commit 7f410a3`, which matches
`SymonSaySource/diffuse/pins/stable-diffusion.cpp.json` exactly; a test asserts that, so the
binary drifting from its pin is a test failure rather than a surprise.

**Recorded gap, not fixed here:** that pin carries no licence field. Every other placement
question this unit had was answerable from disk; this one is not, and it is named rather than
guessed at.

## Why it measures the card itself instead of asking symonprobe

symonprobe owns the card. This does not ask it, and that is deliberate: `room()` is a safety
gate, and a gate that needs another service to be up fails open exactly when the estate is
degraded. It also needs something symonprobe does not report — `--query-compute-apps`, the
per-process holders, which is what turns a refusal into an actionable one.

The module is `imager.py`, not `runtime.py`, because symonprobe already has a `runtime.py`
about serving runtimes and two different jobs under one filename is what `no-divergent-copy`
refuses.

## Routes

    GET  /api/symonimage/health     public; answers before the unit is configured
    GET  /api/symonimage/version    what the runtime reports, by running it
    GET  /api/symonimage/weights    the four files a generation needs, and the licence with them
    GET  /api/symonimage/room       free memory, who holds the rest, and whether it is enough
    GET  /api/symonimage/ready      everything generate checks, without generating
    POST /api/symonimage/generate   one image, or a refusal naming what is in the way

Health is public; the rest need `SYM_SYMONIMAGE_TOKEN`, and an unset token closes the unit.

**This unit reads only its own namespace.** `SYM_SYMONIMAGE_TOKEN`, `SYM_SYMONIMAGE_HOST`,
`SYM_SYMONIMAGE_PORT`. The `SYM_IMAGE_*` namespace belongs to the registry image unit on 8809,
which keeps `SYM_IMAGE_TOKEN`.

The token was split on 2026-09-19 so that one service's credential could not authorise another.
The **host and port were missed**, and that mattered more than a naming nit: §3.2a makes the bind
address the thing that decides whether a credential is required at all, so exposing 8809 by
setting `SYM_IMAGE_HOST` would have moved this unit off loopback with it. Corrected 2026-09-20;
a test reads `service.py` and fails if any `SYM_IMAGE_HOST`, `SYM_IMAGE_PORT` or
`SYM_IMAGE_TOKEN` appears in it.

`SYM_IMAGE_BIN`, `SYM_IMAGE_STORE` and `SYM_IMAGE_OUT` are deliberately unchanged. They name the
image runtime, its weights store and its output directory — resources rather than this unit's
identity — and none of them decides authorisation.

Three public callables carry no route and say so in `NOT_EXPOSED`: `binary` and `store` resolve
environment variables and are reported inside `version` and `weights`; `card` is served inside
`room`, because free memory is only meaningful beside what a generation needs.

## Placement

    placement-triage prospect symonimage --sources python-stdlib@PSF-2.0,fastapi@MIT
    -> SymonSayDistribute, SymonSaysLLC Proprietary License

The image runtime and the weights are **invoked and read as data, never linked or imported**,
so they are not components of this artifact — the same reasoning that places `symonweb`, whose
browser is also a program it runs rather than a library it links. The weights carry their own
`LICENSE`, `NOTICE` and provenance in `/models/symon-imager/`, placed by `model-store`.

**The ship gate does not corroborate this, and saying so matters.** Its census for v1.0.0 lists
six components, all PERMISSIVE, all Python: cpython and python3.13-minimal (PSF-2.0), fastapi,
pydantic and pytest (MIT), uvicorn (BSD-3-Clause). The image runtime appears at no class at
all. The gate *can* emit `INVOKED_NOT_LINKED` — `board/v1.3.0` carries two, for bash and
coreutils — but it detects interpreters and Python imports, not a program reached through
`subprocess` from a path held in an environment variable. So the claim above is reasoned from
how the code works, not confirmed by the census. Silence from a gate is not agreement from it,
and a licence claim resting on a gate that never looked is the kind of thing this estate
records rather than rounds up.

Adjacent and deliberately not built here: a census that reads argv-invoked programs.

## Testing

18 tests, and most are about refusing, because the one thing this unit must never do is start a
generation that cannot finish on a card somebody else is using: the room check refuses and names
the holder, an empty prompt generates nothing, a non-positive shape is refused, no shape field
has a default, the room check can only be skipped explicitly, `shell=True` appears nowhere, a
missing binary and a missing store are each named rather than failing later, health is public
while everything else is closed, and `ready` names what blocks it.

Three read the real thing: the runtime identifies itself, its commit matches the recorded pin,
and the weights are complete with their licence carried.

    python3 -m pytest tests/ -q

## Releases

Tagged `symonimage/v<version>`.

## Status

Running on 8822 and routed: registered in `/models/control.board`, present in the fabric's
wiring table (`unknown_on_board()` empty, 12 components routable), and reachable as three
agent tools — `image_room`, `image_ready`, `image_generate`.

**Not yet commissioned.** `SYM_SYMONIMAGE_TOKEN` is unprovisioned, so health answers and every
other route returns 503 by design. Generating a secret is Garrett's alone (R13), and until he
does the unit is wired but closed.

## Directories

Every directory below, what is in it, and the document that carries it.

| Directory | Holds |
|---|---|
| [`symonimage`](symonimage/symonimage.md) | the capability this unit provides — `imager.py` |
| [`tests`](tests/tests.md) | what proves this unit does what it says — 1 test file(s) |

## Where this leads

Onward, in the order the code runs: [`symonimage`](symonimage/symonimage.md), [`tests`](tests/tests.md).
