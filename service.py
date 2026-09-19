#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
# SyMoNsAyLeaRn — SyMoNeuRaL, a subdivision of SymonSaysLLC. Terms: see LICENSE.
"""symonloop over HTTP — recurring work that survives the process that created it.

Seven routes. None of them runs anything: this records what is owed, answers what is due at a
moment you name, and records that a firing happened. Execution belongs to an adapter, outside
the core, so that an adapter disappearing takes nothing with it.

`now` is a parameter on every route that needs one, defaulting to this host's clock — the same
discipline as symonscheduler, and for the same reason: a ledger nobody can replay is a ledger
nobody can explain.
"""
from __future__ import annotations

import hmac
import ipaddress
import os
import time
from datetime import datetime
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel

from symonloop import ledger as L

UNIT = "symonloop"
STARTED = time.time()

app = FastAPI(
    title="SyMoNeuRaL symonloop",
    version="1.0.0",
    description="Recurring work that survives the process that created it.",
    docs_url="/api/symonloop/docs",
    openapi_url="/api/symonloop/openapi.json",
)


def _open_on_loopback() -> bool:
    """A key is for traffic that leaves this machine. Loopback traffic does not (§3.2a)."""
    host = (os.environ.get("SYM_LOOP_HOST") or "127.0.0.1").strip()
    if host.lower() in ("localhost", ""):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def require_token(authorization: Annotated[str | None, Header()] = None) -> None:
    if _open_on_loopback():
        return
    expected = (os.environ.get("SYM_LOOP_TOKEN") or "").strip()
    if not expected:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="symonloop is bound off-loopback and SYM_LOOP_TOKEN is not "
                                   "set; a reachable unit will not serve without a key")
    got = (authorization or "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(got, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="bad token")


Authed = Annotated[None, Depends(require_token)]


def _guard(fn) -> Any:
    try:
        return fn()
    except L.LedgerError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(e))


def _now(v: str | None) -> str:
    return v or datetime.now().isoformat()


class AddIn(BaseModel):
    work: str
    cadence: str
    next_fire: str
    now: str | None = None
    job_id: str | None = None
    expires_days: int = L.DEFAULT_EXPIRY_DAYS
    note: str = ""


class FireIn(BaseModel):
    next_fire: str
    now: str | None = None


class StopIn(BaseModel):
    reason: str = ""
    now: str | None = None


class ResumeIn(BaseModel):
    next_fire: str
    now: str | None = None


@app.get("/api/symonloop/health")
def health() -> dict[str, Any]:
    """Public; answers before the unit is configured and before any job exists."""
    return {"unit": UNIT, "status": "ok", "uptime_s": round(time.time() - STARTED, 1),
            "ledger": str(L.root()), "clock": datetime.now().isoformat()}


@app.get("/api/symonloop/jobs")
def list_jobs(_: Authed, state: str | None = None) -> dict[str, Any]:
    """Every job, with unreadable records named rather than silently dropped."""
    return _guard(lambda: L.jobs(state=state))


@app.get("/api/symonloop/jobs/{job_id}")
def get_job(_: Authed, job_id: str) -> dict[str, Any]:
    """One job, or a refusal naming the id and where it was looked for."""
    return _guard(lambda: L.get(job_id))


@app.get("/api/symonloop/due")
def due(_: Authed, now: str | None = None, grace_s: int = 0) -> dict[str, Any]:
    """What is due at `now`, expiring anything that lapsed on the way."""
    return _guard(lambda: L.due(_now(now), grace_s=grace_s))


@app.post("/api/symonloop/jobs")
def add_job(body: AddIn, _: Authed) -> dict[str, Any]:
    """Record recurring work. `next_fire` comes from symonscheduler, not from here."""
    return _guard(lambda: L.add(work=body.work, cadence=body.cadence,
                                next_fire=body.next_fire, now=_now(body.now),
                                job_id=body.job_id, expires_days=body.expires_days,
                                note=body.note))


@app.post("/api/symonloop/jobs/{job_id}/fired")
def record_fire(job_id: str, body: FireIn, _: Authed) -> dict[str, Any]:
    """Record that a job fired and when it is next owed."""
    return _guard(lambda: L.record_fire(job_id, now=_now(body.now),
                                        next_fire=body.next_fire))


@app.post("/api/symonloop/jobs/{job_id}/stop")
def stop_job(job_id: str, body: StopIn, _: Authed) -> dict[str, Any]:
    """Stop a job without removing it — the record is the history of what ran here."""
    return _guard(lambda: L.stop(job_id, now=_now(body.now), reason=body.reason))


@app.post("/api/symonloop/jobs/{job_id}/resume")
def resume_job(job_id: str, body: ResumeIn, _: Authed) -> dict[str, Any]:
    """Return a stopped job to service. An expired one is refused, not revived."""
    return _guard(lambda: L.resume(job_id, now=_now(body.now), next_fire=body.next_fire))


def main() -> None:
    import uvicorn
    uvicorn.run(app, host=os.environ.get("SYM_LOOP_HOST", "127.0.0.1"),
                port=int(os.environ.get("SYM_LOOP_PORT", "8830")))


if __name__ == "__main__":
    main()
