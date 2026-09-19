# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
# SyMoNsAyLeaRn — SyMoNeuRaL, a subdivision of SymonSaysLLC. Terms: see LICENSE.
"""Serving symon-imager — a CLI wrapped honestly, on a card it has to share.

THE CONSTRAINT THAT SHAPES THIS UNIT
------------------------------------
There is one card, 15.92 GiB. The chat engine holds about 15 GiB of it while it is serving, and
symon-imager's weights are 11.80 GiB. **They cannot both be resident.** That is not a tuning
problem to be solved with a smaller batch; it is arithmetic.

So this refuses to generate while the card is held, rather than starting and dying with an
out-of-memory some seconds in. A refusal that names what is holding the card is something an
operator can act on. An OOM traceback from a CUDA allocator is not.

THE RUNTIME IS A PROGRAM, NOT A LIBRARY
The image runtime is invoked with an argument vector — never a shell string. A prompt is caller text and
it goes to a model; the day it also reaches a shell is the day a prompt becomes a command. There
is no code path here that builds a command line by concatenation.

WHERE THE BINARY IS
Not assumed. `SYM_IMAGE_BIN` names it, and if it is absent this says so rather than failing
later with a file-not-found from a subprocess. The default points at the recovered tree: these
binaries existed only in a tmpfs trash directory on 2026-09-19 and would have been destroyed by
that morning's reboot.
"""
from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any

# Recovered 2026-09-19 from /tmp/.Trash-1000, which is tmpfs — the reboot that morning would
# have taken them. Verified against the tree's own SHA256SUMS, rc=0.
DEFAULT_BIN = ("/home/google/symoneural-recovered/symon-image-from-tmpfs-trash-2026-09-19/"
               "tmp.bjhN6ZnJrG/home/image/bin/symoneural-image")
DEFAULT_STORE = "/mnt/models/symon-imager"

# What one generation needs resident on the card, measured from the placed weights rather
# than estimated. It is the size of what has to be in memory at once.
WEIGHTS_GIB = 11.80


# Every public callable here is either routed in service.py or named below with the reason it
# is not. `endpoints-current` refuses silence: a capability is exposed, or it is deliberately
# not, and not deciding is what produced a whole release of unreachable arithmetic once.
NOT_EXPOSED = {
    "binary": "resolves SYM_IMAGE_BIN to a path; its result is reported inside GET "
              "/api/symonimage/version, which is the honest surface — a caller wants what the "
              "runtime IS, not where this process looked for it",
    "store":  "resolves SYM_IMAGE_STORE to a path; its result is reported inside GET "
              "/api/symonimage/weights, beside what was actually found there",
    "card":   "served inside GET /api/symonimage/room. The free memory and the processes "
              "holding it are only meaningful next to what a generation NEEDS, and splitting "
              "them into two routes invites a caller to read one and act on it",
}


class ImageError(Exception):
    """A generation that could not be run, carrying why."""


def binary() -> Path:
    p = Path(os.environ.get("SYM_IMAGE_BIN", DEFAULT_BIN))
    if not p.is_file():
        raise ImageError(f"no image runtime at {p}. SYM_IMAGE_BIN names it; the default points "
                         f"at the tree recovered from tmpfs on 2026-09-19")
    if not os.access(p, os.X_OK):
        raise ImageError(f"{p} is not executable")
    return p


def store() -> Path:
    p = Path(os.environ.get("SYM_IMAGE_STORE", DEFAULT_STORE))
    if not p.is_dir():
        raise ImageError(f"no model store at {p}; symon-imager is placed by model-store")
    return p


def version() -> dict[str, Any]:
    """What the runtime reports about itself, read by running it rather than recorded."""
    b = binary()
    r = subprocess.run([str(b), "--help"], capture_output=True, text=True, timeout=60)
    first = (r.stdout or r.stderr).splitlines()[0] if (r.stdout or r.stderr) else ""
    m = re.search(r"version\s+(\S+),\s*commit\s+(\S+)", first)
    return {"binary": str(b), "reports": first[:160],
            "version": m.group(1) if m else None, "commit": m.group(2) if m else None,
            "pinned_at": "SymonSaySource/diffuse/pins/stable-diffusion.cpp.json"}


def weights() -> dict[str, Any]:
    """The four files a generation needs, and whether they are all there."""
    s = store()
    want = {"diffusion": "flux1-schnell-q4_k.gguf", "text_encoder": "t5xxl-Q8_0.gguf",
            "clip": "clip_l.safetensors", "autoencoder": "ae.safetensors"}
    out, missing = {}, []
    for role, name in want.items():
        p = s / name
        if p.is_file():
            out[role] = {"file": name, "bytes": p.stat().st_size}
        else:
            missing.append(name)
    return {"store": str(s), "present": out, "missing": missing,
            "complete": not missing,
            "licence": (s / "LICENSE").is_file(),
            "why": ("every file a generation needs is present" if not missing else
                    f"missing {', '.join(missing)} — a generation would fail partway")}


def card() -> dict[str, Any]:
    """What the card has free right now, and who is holding the rest.

    Measured, every time. The whole point of this function is that the answer changes depending
    on whether the chat engine is up, and a cached answer would be wrong exactly when it matters.
    """
    exe = "/usr/bin/nvidia-smi"
    if not Path(exe).exists():
        raise ImageError("no nvidia-smi; this host has no device to report on")
    q = subprocess.run([exe, "--query-gpu=memory.total,memory.free", "--format=csv,noheader,nounits"],
                       capture_output=True, text=True, timeout=20)
    if q.returncode != 0:
        raise ImageError(f"nvidia-smi rc={q.returncode}: {q.stderr.strip()[:160]}")
    total, free = (int(x.strip()) for x in q.stdout.strip().splitlines()[0].split(","))
    procs = subprocess.run([exe, "--query-compute-apps=pid,process_name,used_memory",
                            "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=20)
    holders = []
    for line in (procs.stdout or "").strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) == 3:
            holders.append({"pid": int(parts[0]), "process": parts[1], "mib": int(parts[2])})
    return {"total_mib": total, "free_mib": free, "free_gib": round(free / 1024, 2),
            "holders": sorted(holders, key=lambda h: -h["mib"])}


def room(*, need_gib: float = WEIGHTS_GIB) -> dict[str, Any]:
    """Is there room to generate, and if not, what is in the way.

    This is the check the unit exists to make. One card, 15.92 GiB; the chat engine holds about
    15 of it while serving and these weights are 11.80. They do not co-fit, and finding that out
    from a CUDA out-of-memory several seconds into a generation is finding it out too late.
    """
    c = card()
    have = c["free_gib"]
    ok = have >= need_gib
    biggest = c["holders"][0] if c["holders"] else None
    return {**c, "need_gib": need_gib, "have_gib": have, "enough": ok,
            "shortfall_gib": round(max(0.0, need_gib - have), 2),
            "why": ("there is room to load the weights" if ok else
                    f"{need_gib} GiB of weights against {have} GiB free"
                    + (f"; {biggest['process']} (pid {biggest['pid']}) holds "
                       f"{round(biggest['mib']/1024, 2)} GiB" if biggest else "")
                    + ". One card: these do not co-fit, and this refuses rather than failing "
                      "with an allocator error partway through")}


def generate(*, prompt: str, out_path: str, steps: int, width: int, height: int,
             seed: int | None = None, timeout_s: float = 900.0,
             skip_room_check: bool = False) -> dict[str, Any]:
    """Run one generation. An argument vector, never a shell string.

    `steps`, `width` and `height` have no defaults. They decide what the card is asked to hold
    and how long it is held for, and a default here is a number nobody chose committing the one
    card for minutes.
    """
    if not prompt.strip():
        raise ImageError("an empty prompt generates nothing")
    for name, v in (("steps", steps), ("width", width), ("height", height)):
        if v <= 0:
            raise ImageError(f"{name} must be positive; it has no default because it decides "
                             f"what the card is asked to do")
    w = weights()
    if not w["complete"]:
        raise ImageError(w["why"])
    if not skip_room_check:
        r = room()
        if not r["enough"]:
            raise ImageError(r["why"])

    s = store()
    argv = [str(binary()),
            "--diffusion-model", str(s / "flux1-schnell-q4_k.gguf"),
            "--t5xxl", str(s / "t5xxl-Q8_0.gguf"),
            "--clip_l", str(s / "clip_l.safetensors"),
            "--vae", str(s / "ae.safetensors"),
            "-p", prompt,                      # argv, so a prompt is never shell
            "-o", out_path,
            "--steps", str(steps), "-W", str(width), "-H", str(height),
            "--cfg-scale", "1.0", "--sampling-method", "euler"]
    if seed is not None:
        argv += ["-s", str(seed)]

    t0 = time.time()
    try:
        r = subprocess.run(argv, capture_output=True, text=True, timeout=timeout_s)
    except subprocess.TimeoutExpired:
        raise ImageError(f"the generation did not finish in {timeout_s}s and was stopped; the "
                         f"card is shared, so a run without a bound would hold it indefinitely")
    took = time.time() - t0
    produced = Path(out_path).is_file()
    return {"ok": r.returncode == 0 and produced, "returncode": r.returncode,
            "output": out_path, "produced": produced,
            "bytes": Path(out_path).stat().st_size if produced else 0,
            "seconds": round(took, 2), "steps": steps, "size": [width, height],
            "seed": seed,
            "stderr_tail": (r.stderr or "").strip().splitlines()[-3:],
            "argv_note": "the prompt was passed as an argument vector element, never through a "
                         "shell — a prompt that reaches a shell is a prompt that is a command"}
