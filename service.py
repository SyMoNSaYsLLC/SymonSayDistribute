#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
# SyMoNsAyLeaRn — SyMoNeuRaL, a subdivision of SymonSaysLLC. Terms: see LICENSE.
"""symonsdk over HTTP — what this machine can build with, answered rather than guessed.

Six routes under /api/symonsdk/. The question behind all of them is the one symon cannot
answer by recalling anything: what toolchains are here, do they RUN, which virtualenvs still
have an interpreter, what the SDK trees hold, what source is here to build from — and, for a
named ecosystem, whether a build would start right now and which part is missing if not.

THE ROUTE THAT MATTERS IS `can-build`
The others report. `can-build` decides, and names every precondition separately so that a "no"
is actionable: not "node is unavailable" but "node 24.19.0 is here and npm is on no PATH
entry". That is a different problem with a different fix, and a caller told only "no" would
have to go and find that out for itself.
"""
from __future__ import annotations

import hmac
import ipaddress
import os
import time
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, status

from symonsdk import toolchains as R

UNIT = "symonsdk"
STARTED = time.time()

app = FastAPI(
    title="SyMoNeuRaL symonsdk",
    version="1.0.0",
    description="What can be built on this machine, with what, and whether it is usable.",
    docs_url="/api/symonsdk/docs",
    openapi_url="/api/symonsdk/openapi.json",
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
    host = (os.environ.get("SYM_SDK_HOST") or "127.0.0.1").strip()
    if host.lower() in ("localhost", ""):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False          # a name we cannot prove is loopback is treated as reachable


def require_token(authorization: Annotated[str | None, Header()] = None) -> None:
    if _open_on_loopback():
        return
    expected = (os.environ.get("SYM_SDK_TOKEN") or "").strip()
    if not expected:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="symonsdk is unconfigured: SYM_SDK_TOKEN is not set")
    got = (authorization or "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(got, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="bad token")


Authed = Annotated[None, Depends(require_token)]


def _guard(fn, *a, **kw) -> Any:
    try:
        return fn(*a, **kw)
    except R.SdkError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(e))


@app.get("/api/symonsdk/health")
def health() -> dict[str, Any]:
    """Public; answers before the unit is configured and before anything has been probed."""
    return {"unit": UNIT, "status": "ok", "uptime_s": round(time.time() - STARTED, 1),
            "configured": bool((os.environ.get("SYM_SDK_TOKEN") or "").strip())}


@app.get("/api/symonsdk/toolchains")
def toolchains(_: Authed) -> dict[str, Any]:
    """Every known toolchain, versioned by RUNNING it with its own argument vector."""
    return _guard(R.toolchains)


@app.get("/api/symonsdk/venvs")
def venvs(_: Authed) -> dict[str, Any]:
    """Every virtualenv under SYM_VENV_ROOT, and whether its interpreter still exists and runs."""
    return _guard(R.venvs)


@app.get("/api/symonsdk/sdks")
def sdks(_: Authed) -> dict[str, Any]:
    """The non-python SDK trees: present, where, how large, and the versions readable on disk."""
    return _guard(R.sdks)


@app.get("/api/symonsdk/pinned")
def pinned(_: Authed) -> dict[str, Any]:
    """Which build tools have a recorded version, which agree, and which are unrecorded."""
    return _guard(R.pinned)


@app.get("/api/symonsdk/sources")
def sources(_: Authed) -> dict[str, Any]:
    """Source trees to build from, each with its path, git status and build manifest."""
    return _guard(R.sources)


@app.get("/api/symonsdk/can-build")
def can_build(ecosystem: str, _: Authed) -> dict[str, Any]:
    """Can this host build `ecosystem` now — and if not, which precondition is missing.

    An unknown name is a 400 carrying the list of names this host does know, because a caller
    that guessed wrong needs the vocabulary, not a refusal.
    """
    return _guard(R.can_build, ecosystem)


def main() -> None:
    import uvicorn
    uvicorn.run(app, host=os.environ.get("SYM_SDK_HOST", "127.0.0.1"),
                port=int(os.environ.get("SYM_SDK_PORT", "8826")))


if __name__ == "__main__":
    main()
