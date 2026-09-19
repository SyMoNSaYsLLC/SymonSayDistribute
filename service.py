#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
"""The weight store over HTTP — what is in it, and whether it still is what it was.

Placement is deliberately NOT here. Putting thirteen gigabytes somewhere is an act with a
filesystem, free space and a licence to check, and it stays a command somebody runs with their
hands. A surface that could place a model by accident is a surface that will.

What is here is everything a caller needs to answer a question: where the store is, what is in
it, what each model claims about itself, and — the one that matters — whether re-hashing it
still agrees with that claim.
"""
from __future__ import annotations

import hmac
import os
import time
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, status

from store import inspect as S

UNIT = "store"
STARTED = time.time()

app = FastAPI(
    title="SyMoNeuRaL weight store",
    version="1.1.0",
    description="What is in the weight store, and whether it has drifted.",
    docs_url="/api/store/docs",
    openapi_url="/api/store/openapi.json",
)


def require_token(authorization: Annotated[str | None, Header()] = None) -> None:
    expected = (os.environ.get("SYM_STORE_TOKEN") or "").strip()
    if not expected:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="store is unconfigured: SYM_STORE_TOKEN is not set")
    presented = authorization[7:].strip() if authorization and authorization.lower().startswith("bearer ") else ""
    if not presented or not hmac.compare_digest(presented.encode(), expected.encode()):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="invalid or missing credential")


Authed = Annotated[None, Depends(require_token)]


@app.get("/api/store/health")
def health() -> dict[str, Any]:
    """Public. Answers while the store is unconfigured and even while it is empty."""
    w = S.where()
    return {"status": "ok", "unit": UNIT, "uptime_s": round(time.time() - STARTED, 1),
            "store": w["store"], "is_disk": w["is_disk"]}


@app.get("/api/store/where")
def where(_: Authed) -> dict[str, Any]:
    """The store's real location: device, filesystem, UUID, free space.

    `is_disk` is false for tmpfs, overlay and network mounts — all of which accept every write
    and lose them — and false when no filesystem UUID can be read at all.
    """
    return S.where()


@app.get("/api/store/models")
def models(_: Authed) -> dict[str, Any]:
    rows = S.models()
    return {"count": len(rows), "store": str(S.store_root()),
            "unverifiable": [r["name"] for r in rows if not r.get("manifest")],
            "models": rows}


@app.get("/api/store/models/{name}")
def model(name: str, _: Authed) -> dict[str, Any]:
    try:
        m = S.manifest(name)
    except S.StoreError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(e))
    out = {k: v for k, v in m.items() if k != "files"}
    out["file_count"] = len(m.get("files", {}))
    try:
        out["provenance"] = S.provenance(name)
    except S.StoreError as e:
        out["provenance"] = None
        out["provenance_why"] = str(e)
    return out


@app.post("/api/store/models/{name}/verify")
def verify(name: str, _: Authed) -> dict[str, Any]:
    """Re-hash every tracked file and compare with the manifest.

    A manifest nobody recomputes is a claim, not a check. This is a POST because it reads
    every byte of a multi-gigabyte checkpoint, which is not something to do on a page load.
    """
    try:
        return S.verify(name)
    except S.StoreError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(e))


@app.post("/api/store/models/{name}/manifest")
def make_manifest(name: str, _: Authed, version: str = "", note: str = "") -> dict[str, Any]:
    """Record a baseline manifest for a model that has none.

    It refuses to overwrite. An existing manifest is the record of what the model was when it
    was placed; replacing it with a hash of whatever is there now would turn the check into a
    tautology and make drift undetectable at the moment of recording.

    What it writes is marked `recorded_after_the_fact`, because a baseline is not provenance:
    it says what is here now, not that this is what arrived.
    """
    try:
        return S.write_manifest(name, version, note)
    except S.StoreError as e:
        raise HTTPException(status.HTTP_409_CONFLICT if "already has" in str(e)
                            else status.HTTP_404_NOT_FOUND, detail=str(e))


def main() -> None:
    import uvicorn
    uvicorn.run(app, host=os.environ.get("SYM_STORE_HOST", "127.0.0.1"),
                port=int(os.environ.get("SYM_STORE_PORT", "8812")),
                log_level=os.environ.get("SYM_LOG_LEVEL", "info"))


if __name__ == "__main__":
    main()
