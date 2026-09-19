#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
# SyMoNsAyLeaRn — SyMoNeuRaL, a subdivision of SymonSaysLLC. Terms: see LICENSE.
"""symonengine over HTTP — what a serving build can do, asked of the build.

Five routes under /api/symonengine/, all GET. It starts nothing and serves nothing; it reports
on a build that would.
"""
from __future__ import annotations

import hmac
import os
import time
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, status

from symonengine import capability as C

UNIT = "symonengine"
STARTED = time.time()
DEFAULT_VENV = os.environ.get("SYM_ENGINE_VENV", "/home/google/.venvs/vllm-0271-cu130")

app = FastAPI(
    title="SyMoNeuRaL symonengine",
    version="1.0.0",
    description="The capability surface of the serving build, read from the build.",
    docs_url="/api/symonengine/docs",
    openapi_url="/api/symonengine/openapi.json",
)


def require_token(authorization: Annotated[str | None, Header()] = None) -> None:
    expected = (os.environ.get("SYM_ENGINE_TOKEN") or "").strip()
    if not expected:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="symonengine is unconfigured: SYM_ENGINE_TOKEN is not set")
    got = (authorization or "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(got, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="bad token")


Authed = Annotated[None, Depends(require_token)]


def _guard(fn, *a, **kw) -> Any:
    try:
        return fn(*a, **kw)
    except C.CapabilityError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(e))


@app.get("/api/symonengine/health")
def health() -> dict[str, Any]:
    """Public; answers before the unit is configured."""
    return {"unit": UNIT, "status": "ok", "uptime_s": round(time.time() - STARTED, 1),
            "configured": bool((os.environ.get("SYM_ENGINE_TOKEN") or "").strip()),
            "default_venv": DEFAULT_VENV}


@app.get("/api/symonengine/surface")
def surface(_: Authed, venv: str = "") -> dict[str, Any]:
    """Everything this build supports: architectures, quantization, features, versions."""
    return _guard(C.surface, venv or DEFAULT_VENV)


@app.get("/api/symonengine/summary")
def summary(_: Authed, venv: str = "") -> dict[str, Any]:
    """The same surface as counts, for when the full lists are not the question."""
    s = _guard(C.surface, venv or DEFAULT_VENV)
    return {"runtime": s.get("runtime"), "version": s.get("version"), "venv": s["venv"],
            "torch": s.get("torch"), "cuda_built_against": s.get("cuda_built_against"),
            "counts": s["counts"],
            "features": {k: v["present"] for k, v in (s.get("features") or {}).items()},
            "read_how": s["read_how"]}


@app.get("/api/symonengine/supports")
def supports(_: Authed, architecture: str = "", quantization: str = "",
             venv: str = "") -> dict[str, Any]:
    """Whether one architecture or one quantization method is in this build, by exact name."""
    if not architecture and not quantization:
        raise HTTPException(status.HTTP_400_BAD_REQUEST,
                            detail="name an architecture or a quantization method to ask about")
    s = _guard(C.surface, venv or DEFAULT_VENV)
    out: dict[str, Any] = {"version": s.get("version")}
    if architecture:
        archs = s.get("architectures") or []
        out["architecture"] = {"name": architecture, "supported": architecture in archs,
                               "of": len(archs)}
    if quantization:
        qs = s.get("quantization") or []
        out["quantization"] = {"name": quantization, "supported": quantization in qs,
                               "of": len(qs)}
    return out


@app.get("/api/symonengine/serves")
def serves(_: Authed, model_dir: str, venv: str = "") -> dict[str, Any]:
    """Can this build serve this checkpoint? The question that precedes a serving decision."""
    return _guard(C.serves, venv or DEFAULT_VENV, model_dir)


def main() -> None:
    import uvicorn
    uvicorn.run(app, host=os.environ.get("SYM_ENGINE_HOST", "127.0.0.1"),
                port=int(os.environ.get("SYM_ENGINE_PORT", "8821")))


if __name__ == "__main__":
    main()
