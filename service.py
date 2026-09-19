#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
# SyMoNsAyLeaRn — SyMoNeuRaL, a subdivision of SymonSaysLLC. Terms: see LICENSE.
"""symondriver over HTTP — seven routes under /api/symondriver/.

THE ROUTE THAT MATTERS IS `consistent`
The other six report one source each. `consistent` puts them side by side and answers the
question a partial upgrade makes unanswerable: does the loaded kernel module agree with
userspace, with the libraries on disk, and with the installed packages?

When they disagree it names every source and what each one said, because "the driver is
inconsistent" sends an operator to look at all four, and the useful fact is which one is the
odd one out.
"""
from __future__ import annotations

import hmac
import ipaddress
import os
import time
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, status

from symondriver import driver as D

UNIT = "symondriver"
STARTED = time.time()

app = FastAPI(
    title="SyMoNeuRaL symondriver",
    version="1.0.0",
    description="The GPU driver's userspace surface, and whether it agrees with the kernel module.",
    docs_url="/api/symondriver/docs",
    openapi_url="/api/symondriver/openapi.json",
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
    host = (os.environ.get("SYM_DRIVER_HOST") or "127.0.0.1").strip()
    if host.lower() in ("localhost", ""):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False          # a name we cannot prove is loopback is treated as reachable


def require_token(authorization: Annotated[str | None, Header()] = None) -> None:
    if _open_on_loopback():
        return
    expected = (os.environ.get("SYM_DRIVER_TOKEN") or "").strip()
    if not expected:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="symondriver is unconfigured: SYM_DRIVER_TOKEN is not set")
    got = (authorization or "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(got, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="bad token")


Authed = Annotated[None, Depends(require_token)]


def _guard(fn, *a, **kw) -> Any:
    try:
        return fn(*a, **kw)
    except D.DriverError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(e))


@app.get("/api/symondriver/health")
def health() -> dict[str, Any]:
    """Public; answers before the unit is configured and before anything has been read."""
    return {"unit": UNIT, "status": "ok", "uptime_s": round(time.time() - STARTED, 1),
            "configured": bool((os.environ.get("SYM_DRIVER_TOKEN") or "").strip())}


@app.get("/api/symondriver/kernel-module")
def kernel_module(_: Authed) -> dict[str, Any]:
    """What the loaded module says about itself: version, variant, build host, date, compiler.

    An absent file answers "not loaded" rather than answering nothing.
    """
    return _guard(D.kernel_module)


@app.get("/api/symondriver/userspace")
def userspace(_: Authed) -> dict[str, Any]:
    """The version userspace reports, obtained by running the query tool rather than reading a
    record of what was installed."""
    return _guard(D.userspace)


@app.get("/api/symondriver/libraries")
def libraries(_: Authed) -> dict[str, Any]:
    """Every driver library found, grouped by architecture, with its soname and version.

    Both architectures installed here are reported; the 32-bit half is the one nobody looks at.
    """
    return _guard(D.libraries)


@app.get("/api/symondriver/binaries")
def binaries(_: Authed) -> dict[str, Any]:
    """Which known driver programs exist, and their real paths. None of them is executed."""
    return _guard(D.binaries)


@app.get("/api/symondriver/packages")
def packages(_: Authed) -> dict[str, Any]:
    """The installed package family and their versions, split by version series with the
    reason each set-aside package was not compared."""
    return _guard(D.packages)


@app.get("/api/symondriver/pinned")
def pinned(_: Authed) -> dict[str, Any]:
    """Does the loaded kernel module match the revision SymonSaySource recorded (§3.1b-iii)?"""
    return _guard(D.pinned)


@app.get("/api/symondriver/consistent")
def consistent(_: Authed) -> dict[str, Any]:
    """THE POINT OF THIS UNIT. Every version seen, and where each one came from.

    Disagreement is the finding, not an error: this returns 200 with the sources named, because
    a mismatch an operator can read is the deliverable.
    """
    return _guard(D.consistent)


def main() -> None:
    import uvicorn
    uvicorn.run(app, host=os.environ.get("SYM_DRIVER_HOST", "127.0.0.1"),
                port=int(os.environ.get("SYM_DRIVER_PORT", "8825")))


if __name__ == "__main__":
    main()
