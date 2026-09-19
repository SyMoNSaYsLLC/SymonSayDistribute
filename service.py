#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
# SyMoNsAyLeaRn — SyMoNeuRaL, a subdivision of SymonSaysLLC. Terms: see LICENSE.
"""symonscope over HTTP — what this estate actually is, answered from disk.

Eight routes under /api/symonscope/. Every one is a GET, and the unit has no route that
writes anything. That is not an oversight to be fixed later: a surveyor that can change what
it surveys is a surveyor whose answers cannot be trusted, and the estate already has units
whose job is to change things.

WHY IT IS WORTH A SERVICE AT ALL
--------------------------------
Because symon should be able to answer "what is in this estate" by looking, rather than by
being told in a prompt that goes stale. Reached as a connector, this is the difference between
a model that recites an architecture and one that reads it.
"""
from __future__ import annotations

import hmac
import os
import time
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, status

from symonscope import edges as E
from symonscope import layers as L
from symonscope import live as V
from symonscope import survey as S

UNIT = "symonscope"
STARTED = time.time()

app = FastAPI(
    title="SyMoNeuRaL symonscope",
    version="1.0.0",
    description="What this estate is: units, subcomponents, edges, derived layers, live state.",
    docs_url="/api/symonscope/docs",
    openapi_url="/api/symonscope/openapi.json",
)


def require_token(authorization: Annotated[str | None, Header()] = None) -> None:
    expected = (os.environ.get("SYM_SCOPE_TOKEN") or "").strip()
    if not expected:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="symonscope is unconfigured: SYM_SCOPE_TOKEN is not set")
    got = (authorization or "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(got, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="bad token")


Authed = Annotated[None, Depends(require_token)]


def _run(fn, *a, **kw) -> Any:
    """A survey that cannot complete says why. It never returns an empty result that reads
    like 'there is nothing there'."""
    try:
        return fn(*a, **kw)
    except S.SurveyError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(e))


@app.get("/api/symonscope/health")
def health() -> dict[str, Any]:
    """Public; answers before the unit is configured."""
    return {"unit": UNIT, "status": "ok", "uptime_s": round(time.time() - STARTED, 1),
            "configured": bool((os.environ.get("SYM_SCOPE_TOKEN") or "").strip())}


@app.get("/api/symonscope/trees")
def trees(_: Authed) -> dict[str, Any]:
    """The four trees, present or absent, with how many units and tags each holds."""
    return {"trees": _run(S.trees)}


@app.get("/api/symonscope/units")
def units(_: Authed, tree: str = "SymonSayDistribute") -> dict[str, Any]:
    """Every unit: what it says it is, what kind it is, where it answers, what it released."""
    rows = _run(S.units, tree)
    return {"tree": tree, "count": len(rows), "units": rows,
            "undocumented": [r["unit"] for r in rows if not r["has_document"]]}


@app.get("/api/symonscope/subcomponents")
def subcomponents(_: Authed, tree: str = "SymonSayDistribute") -> dict[str, Any]:
    """The components inside each unit, because a branch is not always one thing."""
    rows = _run(S.subcomponents, tree)
    return {"tree": tree, "units": rows,
            "more_than_one_thing": [r["unit"] for r in rows if r["count"] > 1]}


@app.get("/api/symonscope/edges")
def edges(_: Authed, tree: str = "SymonSayDistribute") -> dict[str, Any]:
    """Every dependency between units, each carrying the file and line that proves it."""
    return _run(E.edges, tree)


@app.get("/api/symonscope/layers")
def layers(_: Authed, tree: str = "SymonSayDistribute") -> dict[str, Any]:
    """Layers derived from the edges. A cycle is reported, never smoothed into a number."""
    return _run(L.layers, tree)


@app.get("/api/symonscope/live")
def live(_: Authed, tree: str = "SymonSayDistribute") -> dict[str, Any]:
    """What is running, against what is declared, with every disagreement named."""
    return _run(V.state, tree)


@app.get("/api/symonscope/survey")
def full(_: Authed, tree: str = "SymonSayDistribute") -> dict[str, Any]:
    """Everything, in one call.

    This exists for symon. A model asking "what is this estate" should get one answer rather
    than have to know which six routes to stitch together, and a question a model has to know
    the shape of in advance is a question it will not ask.
    """
    u = _run(S.units, tree)
    lay = _run(L.layers, tree)
    st = _run(V.state, tree)
    ed = _run(E.edges, tree)
    # "unwired" is the ISOLATED set, not layer 0. Layer 0 means provider — ravencalc, board
    # and model-store are layer 0 and all three have callers. Reporting layer 0 as unwired
    # said the estate's foundations were dead, which is the opposite of what it means.
    return {"tree": tree, "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "units": u, "subcomponents": _run(S.subcomponents, tree),
            "edges": ed, "layers": lay, "live": st,
            "headline": {
                "units": len(u),
                "services": sum(1 for r in u if r["kind"] == "service"),
                "released": sum(1 for r in u if r["releases"]),
                "unwired": ed["isolated"],
                "unwired_means": "nothing depends on it and it depends on nothing — either a "
                                 "leaf tool, or something built and never connected",
                "providers": [x["unit"] for l in lay["layers"] if l["layer"] == 0
                              for x in l["units"]],
                "cycles": lay.get("cycles", []),
                "live_disagreements": len(st.get("findings", [])),
            }}


def main() -> None:
    import uvicorn
    uvicorn.run(app, host=os.environ.get("SYM_SCOPE_HOST", "127.0.0.1"),
                port=int(os.environ.get("SYM_SCOPE_PORT", "8815")))


if __name__ == "__main__":
    main()
