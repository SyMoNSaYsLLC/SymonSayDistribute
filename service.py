#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
# SyMoNsAyLeaRn — SyMoNeuRaL, a subdivision of SymonSaysLLC. Terms: see LICENSE.
"""symonkernel over HTTP — the kernel question asked before the reboot, not after it.

Seven routes under /api/symonkernel/. The one that matters is `coverage`: for every kernel
with a module tree on this host, is the out-of-tree module actually built and placed for it.

An upgrade that lands without a rebuild is invisible from every other angle. The running
kernel still has its driver, every probe answers, nothing logs anything. The next boot is
where it shows up, and by then the card has no driver and the estate is down with it.
"""
from __future__ import annotations

import hmac
import ipaddress
import os
import time
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query, status

from symonkernel import kernel as K

UNIT = "symonkernel"
STARTED = time.time()

app = FastAPI(
    title="SyMoNeuRaL symonkernel",
    version="1.0.0",
    description="The host kernel, and whether a module can still be built for it.",
    docs_url="/api/symonkernel/docs",
    openapi_url="/api/symonkernel/openapi.json",
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
    host = (os.environ.get("SYM_KERNEL_HOST") or "127.0.0.1").strip()
    if host.lower() in ("localhost", ""):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False          # a name we cannot prove is loopback is treated as reachable


def require_token(authorization: Annotated[str | None, Header()] = None) -> None:
    if _open_on_loopback():
        return
    expected = (os.environ.get("SYM_KERNEL_TOKEN") or "").strip()
    if not expected:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="symonkernel is unconfigured: SYM_KERNEL_TOKEN is not set")
    got = (authorization or "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(got, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="bad token")


Authed = Annotated[None, Depends(require_token)]


def _guard(fn, *a, **kw) -> Any:
    try:
        return fn(*a, **kw)
    except K.KernelError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(e))


Release = Annotated[str | None, Query(description="kernel release; the running one by default")]


@app.get("/api/symonkernel/health")
def health() -> dict[str, Any]:
    """Public; answers before the unit is configured and before anything is measured."""
    return {"unit": UNIT, "status": "ok", "uptime_s": round(time.time() - STARTED, 1),
            "configured": bool((os.environ.get("SYM_KERNEL_TOKEN") or "").strip())}


@app.get("/api/symonkernel/running")
def running(_: Authed) -> dict[str, Any]:
    """The running kernel and the compiler it was built with, read from the kernel itself."""
    return _guard(K.running)


@app.get("/api/symonkernel/kernels")
def kernels(_: Authed) -> dict[str, Any]:
    """Every kernel with a module directory here, and whether each one has headers."""
    return _guard(K.kernels)


@app.get("/api/symonkernel/dkms")
def dkms(_: Authed) -> dict[str, Any]:
    """What the module manager reports. Absent and empty are never the same answer."""
    return _guard(K.dkms)


@app.get("/api/symonkernel/modules")
def modules(_: Authed, release: Release = None) -> dict[str, Any]:
    """Module files on disk against what is loaded. The difference is the answer."""
    return _guard(K.modules, release=release)


@app.get("/api/symonkernel/coverage")
def coverage(_: Authed) -> dict[str, Any]:
    """THE ROUTE THIS UNIT EXISTS FOR: is the module built for every kernel that has one."""
    return _guard(K.coverage)


@app.get("/api/symonkernel/pinned")
def pinned(_: Authed) -> dict[str, Any]:
    """Do the DKMS registrations match the revision SymonSaySource recorded (§3.1b-iii)?"""
    return _guard(K.pinned)


@app.get("/api/symonkernel/buildable")
def buildable(_: Authed, release: Release = None) -> dict[str, Any]:
    """Can a module be built for this kernel right now, precondition by precondition."""
    return _guard(K.buildable, release=release)


def main() -> None:
    import uvicorn
    uvicorn.run(app, host=os.environ.get("SYM_KERNEL_HOST", "127.0.0.1"),
                port=int(os.environ.get("SYM_KERNEL_PORT", "8824")))


if __name__ == "__main__":
    main()
