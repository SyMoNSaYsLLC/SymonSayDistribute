#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
# SyMoNsAyLeaRn — SyMoNeuRaL, a subdivision of SymonSaysLLC. Terms: see LICENSE.
"""symonscheduler over HTTP — when recurring work should next happen.

The first component of the SyMonComponents core. It computes; it does not sleep, spawn a
thread, or run anybody's work. Deciding WHEN is a different job from deciding WHAT, and a
scheduler that also executes cannot be asked a question without side effects.

`now` is accepted as a parameter on every route that needs one, defaulting to this host's
clock. That is what makes a schedule explainable after the fact: an operator can ask what
this would have decided at any moment, and get the same answer the scheduler got.
"""
from __future__ import annotations

import hmac
import ipaddress
import os
import time
from datetime import datetime
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, status

from symonscheduler import cadence as C

UNIT = "symonscheduler"
STARTED = time.time()

app = FastAPI(
    title="SyMoNeuRaL symonscheduler",
    version="1.0.0",
    description="When recurring work should next happen, computed rather than waited for.",
    docs_url="/api/symonscheduler/docs",
    openapi_url="/api/symonscheduler/openapi.json",
)


def _open_on_loopback() -> bool:
    """A key is for traffic that leaves this machine. Loopback traffic does not.

    Rules §3.2a. A token on a 127.0.0.1 bind defends only against a caller who already has
    code execution here — and who can therefore read the token. The BIND ADDRESS decides.
    """
    host = (os.environ.get("SYM_SCHEDULER_HOST") or "127.0.0.1").strip()
    if host.lower() in ("localhost", ""):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def require_token(authorization: Annotated[str | None, Header()] = None) -> None:
    if _open_on_loopback():
        return
    expected = (os.environ.get("SYM_SCHEDULER_TOKEN") or "").strip()
    if not expected:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="symonscheduler is bound off-loopback and "
                                   "SYM_SCHEDULER_TOKEN is not set; a reachable unit will not "
                                   "serve without a key")
    got = (authorization or "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(got, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="bad token")


Authed = Annotated[None, Depends(require_token)]


def _guard(fn, *a, **kw) -> Any:
    try:
        return fn(*a, **kw)
    except C.CadenceError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(e))


def _when(now: str | None) -> datetime:
    if not now:
        return datetime.now()
    try:
        return datetime.fromisoformat(now)
    except ValueError:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            detail=f"{now!r} is not an ISO-8601 datetime")


@app.get("/api/symonscheduler/health")
def health() -> dict[str, Any]:
    """Public; answers before the unit is configured."""
    return {"unit": UNIT, "status": "ok", "uptime_s": round(time.time() - STARTED, 1),
            "clock": datetime.now().isoformat()}


@app.get("/api/symonscheduler/interval")
def interval(_: Authed, spec: str) -> dict[str, Any]:
    """Read an interval like 5m or 2h, refusing anything ambiguous."""
    return _guard(lambda: C.interval_seconds(spec))


@app.get("/api/symonscheduler/to-cron")
def to_cron(_: Authed, spec: str) -> dict[str, Any]:
    """Express an interval as cron, saying plainly when the result is not exact."""
    return _guard(lambda: C.to_cron(spec))


@app.get("/api/symonscheduler/parse")
def parse(_: Authed, cron: str) -> dict[str, Any]:
    """Expand a five-field expression into the values each field matches."""
    return _guard(lambda: C.parse(cron))


@app.get("/api/symonscheduler/next")
def next_fire(_: Authed, cron: str, now: str | None = None) -> dict[str, Any]:
    """The first moment at or after `now` that the expression matches."""
    return _guard(lambda: C.next_fire(cron, _when(now)))


@app.get("/api/symonscheduler/upcoming")
def upcoming(_: Authed, cron: str, count: int = 5, now: str | None = None) -> dict[str, Any]:
    """The next several firings — what a schedule DOES, before it is trusted with work."""
    return _guard(lambda: C.upcoming(cron, _when(now), count))


@app.get("/api/symonscheduler/describe")
def describe(_: Authed, cron: str) -> dict[str, Any]:
    """A schedule in words, so a wrong one can be caught before it is relied on."""
    return _guard(lambda: C.describe(cron))


def main() -> None:
    import uvicorn
    uvicorn.run(app, host=os.environ.get("SYM_SCHEDULER_HOST", "127.0.0.1"),
                port=int(os.environ.get("SYM_SCHEDULER_PORT", "8831")))


if __name__ == "__main__":
    main()
