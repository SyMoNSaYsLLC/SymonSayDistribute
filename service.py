#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
# SyMoNsAyLeaRn — SyMoNeuRaL, a subdivision of SymonSaysLLC. Terms: see LICENSE.
"""symonbuild over HTTP — the build capability, answerable without starting a build.

Seven routes under /api/symonbuild/. The estate is founded on the OpenEmbedded layering system
and nothing owned it, so every question about it — where the task executor is, which copy the
pins name, what the configurations declare, whether those layers exist — was answered from
documents rather than from disk.

THE ROUTE THAT MATTERS IS `cooker-live`
R2 forbids editing a recipe while a cooker is running. Anything about to edit one has to be
able to ask, over the network, at that moment, and get an answer that was read from the process
table rather than remembered. That is why this service never starts a build: a component that
could launch a cooker is a component whose answer to "is one live?" cannot be trusted.
"""
from __future__ import annotations

import hmac
import ipaddress
import os
import time
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, status

from symonbuild import cooker as C

UNIT = "symonbuild"
STARTED = time.time()

app = FastAPI(
    title="SyMoNeuRaL symonbuild",
    version="1.0.0",
    description="The build capability, reported. Never exercised.",
    docs_url="/api/symonbuild/docs",
    openapi_url="/api/symonbuild/openapi.json",
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
    host = (os.environ.get("SYM_BUILD_HOST") or "127.0.0.1").strip()
    if host.lower() in ("localhost", ""):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False          # a name we cannot prove is loopback is treated as reachable


def require_token(authorization: Annotated[str | None, Header()] = None) -> None:
    if _open_on_loopback():
        return
    expected = (os.environ.get("SYM_BUILD_TOKEN") or "").strip()
    if not expected:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="symonbuild is unconfigured: SYM_BUILD_TOKEN is not set")
    got = (authorization or "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(got, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="bad token")


Authed = Annotated[None, Depends(require_token)]


def _guard(fn, *a, **kw) -> Any:
    try:
        return fn(*a, **kw)
    except C.BuildError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(e))


@app.get("/api/symonbuild/health")
def health() -> dict[str, Any]:
    """Public; answers before the unit is configured and before anything is buildable."""
    return {"unit": UNIT, "status": "ok", "uptime_s": round(time.time() - STARTED, 1),
            "configured": bool((os.environ.get("SYM_BUILD_TOKEN") or "").strip())}


@app.get("/api/symonbuild/bitbakes")
def bitbakes(_: Authed) -> dict[str, Any]:
    """Every task executor found, its version read from the file, and the version spread."""
    return _guard(C.bitbakes)


@app.get("/api/symonbuild/devtools")
def devtools(_: Authed) -> dict[str, Any]:
    """The OE tooling beside the executor. An absent tool is named, never omitted."""
    return _guard(C.devtools)


@app.get("/api/symonbuild/configs")
def configs(_: Authed) -> dict[str, Any]:
    """Every build configuration, and for each declared layer whether it exists on disk."""
    return _guard(C.configs)


@app.get("/api/symonbuild/layers")
def layers(_: Authed) -> dict[str, Any]:
    """Layers on disk, the name each declares, and whether it is acquired or merely present."""
    return _guard(C.layers)


@app.get("/api/symonbuild/cooker-live")
def cooker_live(_: Authed) -> dict[str, Any]:
    """Is a cooker running? Read from the process table every time. R2 rests on this."""
    return _guard(C.cooker_live)


@app.get("/api/symonbuild/buildable")
def buildable(_: Authed) -> dict[str, Any]:
    """Could a build run right now — per precondition, with what is in the way when it cannot."""
    return _guard(C.buildable)


def main() -> None:
    import uvicorn
    uvicorn.run(app, host=os.environ.get("SYM_BUILD_HOST", "127.0.0.1"),
                port=int(os.environ.get("SYM_BUILD_PORT", "8828")))


if __name__ == "__main__":
    main()
