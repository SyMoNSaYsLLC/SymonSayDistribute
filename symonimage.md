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

Health is public; the rest need `SYM_IMAGE_TOKEN`, and an unset token closes the unit.

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

Built and tested; **not yet commissioned**. It needs `SYM_IMAGE_TOKEN` provisioned and a port
registered on the control board before anything can reach it. Until then the capability is
real and unreachable, which is precisely what this unit was written to stop being true of
symon-imager.
