#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
# SyMoNsAyLeaRn — SyMoNeuRaL, a subdivision of SymonSaysLLC. Terms: see LICENSE.
"""symonprobe over HTTP — what the hardware is, and what a runtime can actually do on it.

Eight routes under /api/symonprobe/, every one a GET. Nothing here installs, configures or
starts anything: it is the same refusal symonscope makes, for the same reason — a probe that
can change what it probes is a probe whose answers cannot be trusted.
"""
from __future__ import annotations

import hmac
import os
import time
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, status

from symonprobe import device as D
from symonprobe import runtime as R

UNIT = "symonprobe"
STARTED = time.time()

app = FastAPI(
    title="SyMoNeuRaL symonprobe",
    version="1.0.0",
    description="The card, the builds, and whether they can run on each other.",
    docs_url="/api/symonprobe/docs",
    openapi_url="/api/symonprobe/openapi.json",
)


def require_token(authorization: Annotated[str | None, Header()] = None) -> None:
    expected = (os.environ.get("SYM_PROBE_TOKEN") or "").strip()
    if not expected:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="symonprobe is unconfigured: SYM_PROBE_TOKEN is not set")
    got = (authorization or "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(got, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="bad token")


Authed = Annotated[None, Depends(require_token)]


def _guard(fn, *a, **kw) -> Any:
    try:
        return fn(*a, **kw)
    except D.ProbeError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(e))


@app.get("/api/symonprobe/health")
def health() -> dict[str, Any]:
    """Public; answers before the unit is configured."""
    return {"unit": UNIT, "status": "ok", "uptime_s": round(time.time() - STARTED, 1),
            "configured": bool((os.environ.get("SYM_PROBE_TOKEN") or "").strip())}


@app.get("/api/symonprobe/devices")
def devices(_: Authed) -> dict[str, Any]:
    """Every GPU, with compute capability labelled as silicon and not as a CUDA version."""
    return {"devices": _guard(D.devices)}


@app.get("/api/symonprobe/venvs")
def venvs(_: Authed) -> dict[str, Any]:
    """Python environments on this host."""
    rows = _guard(R.venvs)
    return {"count": len(rows), "venvs": rows}


@app.get("/api/symonprobe/build")
def build(_: Authed, venv: str) -> dict[str, Any]:
    """What an environment was built against: versions, CUDA toolkit, compiled architectures."""
    return _guard(D.build, venv)


@app.get("/api/symonprobe/fit")
def fit(_: Authed, venv: str, index: int = 0) -> dict[str, Any]:
    """Can this build run on this card? The compiled arch list decides, not the name."""
    return _guard(D.fit, venv, index)


@app.get("/api/symonprobe/packages")
def packages(_: Authed, venv: str, contains: str = "") -> dict[str, Any]:
    """Installed distributions and versions, from the environment's own metadata."""
    rows = _guard(R.packages, venv, contains)
    return {"venv": venv, "count": len(rows), "packages": rows}


@app.get("/api/symonprobe/parsers")
def parsers(_: Authed, venv: str) -> dict[str, Any]:
    """Which tool-call and reasoning parsers a serving runtime offers, by REGISTERED name."""
    return _guard(R.parsers, venv)


@app.get("/api/symonprobe/suggest")
def suggest(_: Authed, venv: str, model_dir: str) -> dict[str, Any]:
    """Which parser names suit a checkpoint. Candidates with evidence, never an assertion."""
    return _guard(R.suggest, venv, model_dir)


def main() -> None:
    import uvicorn
    uvicorn.run(app, host=os.environ.get("SYM_PROBE_HOST", "127.0.0.1"),
                port=int(os.environ.get("SYM_PROBE_PORT", "8817")))


if __name__ == "__main__":
    main()
