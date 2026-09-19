#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
# SyMoNsAyLeaRn — SyMoNeuRaL, a subdivision of SymonSaysLLC. Terms: see LICENSE.
"""symoncross over HTTP — what this build host can target, asked over the network.

Six routes under /api/symoncross/. The component reports capability and compiles nothing the
estate ships; `targets` proves its verdicts by compiling a few lines of probe source into a
temporary directory and reading what came out.

THE ROUTE THAT MATTERS IS `portability`
`targets` answers what the toolchain could emit. `portability` answers why these components do
not run elsewhere anyway — and for a Python estate with no native code, that second answer is
the real one. A cross-compiler nobody needs is not what is in the way; the Linux-only paths and
programs written into the components are.

`targets` is not fast. The darwin verdict costs about nineteen seconds because it is settled by
running the compiler rather than by reading the SDK's manifest, and the manifest would have
given the wrong answer. The probes are cached for the life of the process and every record says
when it was measured.
"""
from __future__ import annotations

import hmac
import ipaddress
import os
import time
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Header, Query, status

from symoncross import targets as X

UNIT = "symoncross"
STARTED = time.time()

app = FastAPI(
    title="SyMoNeuRaL symoncross",
    version="1.0.0",
    description="What this build host can target, measured rather than recalled.",
    docs_url="/api/symoncross/docs",
    openapi_url="/api/symoncross/openapi.json",
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
    host = (os.environ.get("SYM_CROSS_HOST") or "127.0.0.1").strip()
    if host.lower() in ("localhost", ""):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False          # a name we cannot prove is loopback is treated as reachable


def require_token(authorization: Annotated[str | None, Header()] = None) -> None:
    if _open_on_loopback():
        return
    expected = (os.environ.get("SYM_CROSS_TOKEN") or "").strip()
    if not expected:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="symoncross is unconfigured: SYM_CROSS_TOKEN is not set")
    got = (authorization or "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(got, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="bad token")


Authed = Annotated[None, Depends(require_token)]


@app.get("/api/symoncross/health")
def health() -> dict[str, Any]:
    """Public; answers before the unit is configured and before anything has been probed."""
    return {"unit": UNIT, "status": "ok", "uptime_s": round(time.time() - STARTED, 1),
            "configured": bool((os.environ.get("SYM_CROSS_TOKEN") or "").strip()),
            "cross_compiles_nothing": True}


@app.get("/api/symoncross/hosts")
def hosts_route(_: Authed) -> dict[str, Any]:
    """The build host itself — os, arch, libc, native compiler — read at call time."""
    return X.hosts()


@app.get("/api/symoncross/layers")
def layers_route(_: Authed,
                 name: Annotated[list[str] | None, Query()] = None) -> dict[str, Any]:
    """OE layers on this host, each ACQUIRED or merely PRESENT. `name` selects by directory."""
    return X.layers(names=name or None)


@app.get("/api/symoncross/builders")
def builders_route(_: Authed) -> dict[str, Any]:
    """Build systems: every copy found, and whether any of them is on PATH."""
    return X.builders()


@app.get("/api/symoncross/targets")
def targets_route(_: Authed) -> dict[str, Any]:
    """Every target, with its preconditions and what blocks it. Slow: it compiles probes."""
    return X.targets()


@app.get("/api/symoncross/targets/{name}")
def target_route(name: str, _: Authed) -> dict[str, Any]:
    """One target by name. An unknown name is a 404 naming the ones that exist."""
    try:
        return X.targets(name=name)
    except KeyError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(e.args[0]))


@app.get("/api/symoncross/portability")
def portability_route(_: Authed, root: str | None = None) -> dict[str, Any]:
    """Every platform-locked path and program in the estate's own Python, with file and line."""
    return X.portability(root=root)


def main() -> None:
    import uvicorn
    uvicorn.run(app, host=os.environ.get("SYM_CROSS_HOST", "127.0.0.1"),
                port=int(os.environ.get("SYM_CROSS_PORT", "8827")))


if __name__ == "__main__":
    main()
