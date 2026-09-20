#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
# SyMoNsAyLeaRn — SyMoNeuRaL, a subdivision of SymonSaysLLC. Terms: see LICENSE.
"""symonimage over HTTP — the surface symon-imager did not have.

Six routes under /api/symonimage/. The chat unit has a server; this model had a command-line
program and nothing in front of it, so nothing in the estate could reach it.

THE ROUTE THAT MATTERS IS `room`
There is one card. The chat engine holds about 15 GiB of 15.92 while it serves and these
weights are 11.80 GiB, so they cannot both be resident. `room` answers that before anything is
started, and `generate` refuses on it — naming the process holding the card rather than dying
in an allocator half a minute into a run somebody is waiting on.
"""
from __future__ import annotations

import hmac
import ipaddress
import os
import time
import uuid
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel

from symonimage import imager as R

UNIT = "symonimage"
STARTED = time.time()
OUT_DIR = Path(os.environ.get("SYM_IMAGE_OUT", os.path.expanduser("~/symoneural-run/images")))

app = FastAPI(
    title="SyMoNeuRaL symonimage",
    version="1.0.0",
    description="Serving symon-imager, on a card it has to share.",
    docs_url="/api/symonimage/docs",
    openapi_url="/api/symonimage/openapi.json",
)


def _open_on_loopback() -> bool:
    """A key is for traffic that leaves this machine. Loopback traffic does not.

    Garrett, 2026-09-19: "i do not need keys for hardware to hardware endpoints. If endpoint to
    endpoint is not routing through the internet we do not need those."

    The reason is worth writing down: a token on a 127.0.0.1 bind defends only against a caller
    who already has code execution on this host — and such a caller can read the token itself.
    It costs a provisioning step and buys nothing.

    So the BIND ADDRESS decides, not a convention. Off-loopback the token is required, and an
    unset one closes the unit: a unit that becomes reachable through a config change must not
    become public through that same change.
    """
    # SYM_SYMONIMAGE_HOST, not SYM_IMAGE_HOST. The IMAGE namespace belongs to the registry
    # image unit on 8809, which keeps SYM_IMAGE_TOKEN; this unit is symonimage on 8822 and was
    # split onto SYM_SYMONIMAGE_TOKEN so that one service's credential namespace cannot
    # accidentally authorise another. The TOKEN was split and the HOST was missed — and §3.2a
    # makes the bind address the thing that DECIDES whether a credential is required at all,
    # so exposing 8809 by setting SYM_IMAGE_HOST would have moved this unit off loopback too.
    # Every sibling reads its own: SYM_DEVICE_HOST, SYM_SDK_HOST, SYM_PROBE_HOST, SYM_BOARD_HOST.
    host = (os.environ.get("SYM_SYMONIMAGE_HOST") or "127.0.0.1").strip()
    if host.lower() in ("localhost", ""):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False          # a name we cannot prove is loopback is treated as reachable

def require_token(authorization: Annotated[str | None, Header()] = None) -> None:
    if _open_on_loopback():
        return
    expected = (os.environ.get("SYM_SYMONIMAGE_TOKEN") or "").strip()
    if not expected:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="symonimage is unconfigured: SYM_SYMONIMAGE_TOKEN is not set")
    got = (authorization or "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(got, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="bad token")


Authed = Annotated[None, Depends(require_token)]


def _guard(fn, *a, **kw) -> Any:
    try:
        return fn(*a, **kw)
    except R.ImageError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(e))


class GenerateIn(BaseModel):
    prompt: str
    steps: int
    width: int
    height: int
    seed: int | None = None
    timeout_s: float = 900.0


@app.get("/api/symonimage/health")
def health() -> dict[str, Any]:
    """Public; answers before the unit is configured and before the card is free."""
    return {"unit": UNIT, "status": "ok", "uptime_s": round(time.time() - STARTED, 1),
            "configured": bool((os.environ.get("SYM_SYMONIMAGE_TOKEN") or "").strip())}


@app.get("/api/symonimage/version")
def version(_: Authed) -> dict[str, Any]:
    """What the runtime reports about itself, read by running it rather than recorded."""
    return _guard(R.version)


@app.get("/api/symonimage/weights")
def weights(_: Authed) -> dict[str, Any]:
    """The four files a generation needs, and whether the licence is carried with them."""
    return _guard(R.weights)


@app.get("/api/symonimage/room")
def room(_: Authed) -> dict[str, Any]:
    """Is there room on the card, and what is holding the rest. Measured every time."""
    return _guard(R.room)


@app.get("/api/symonimage/ready")
def ready(_: Authed) -> dict[str, Any]:
    """Everything `generate` checks, without generating — runtime, weights and room."""
    out: dict[str, Any] = {}
    problems = []
    for name, fn in (("runtime", R.version), ("weights", R.weights), ("room", R.room)):
        try:
            out[name] = fn()
        except R.ImageError as e:
            out[name] = {"error": str(e)}
            problems.append(name)
    if out.get("weights", {}).get("complete") is False:
        problems.append("weights")
    if out.get("room", {}).get("enough") is False:
        problems.append("room")
    return {**out, "ready": not problems, "blocked_on": sorted(set(problems)),
            "why": ("a generation would start now" if not problems else
                    f"not ready: {', '.join(sorted(set(problems)))}")}


@app.post("/api/symonimage/generate")
def generate(body: GenerateIn, _: Authed) -> dict[str, Any]:
    """Generate one image. Refuses when the card is held rather than dying partway."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{int(time.time())}-{uuid.uuid4().hex[:8]}.png"
    return _guard(R.generate, prompt=body.prompt, out_path=str(out), steps=body.steps,
                  width=body.width, height=body.height, seed=body.seed,
                  timeout_s=body.timeout_s)


def main() -> None:
    import uvicorn
    uvicorn.run(app, host=os.environ.get("SYM_SYMONIMAGE_HOST", "127.0.0.1"),
                port=int(os.environ.get("SYM_SYMONIMAGE_PORT", "8822")))


if __name__ == "__main__":
    main()
