#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
# SyMoNsAyLeaRn — SyMoNeuRaL, a subdivision of SymonSaysLLC. Terms: see LICENSE.
"""symoneural-adaptive-fabric over HTTP — component wiring, through one place.

Six routes under /api/fabric/. Callers name a COMPONENT, never a host and port, and never hold
that component's credential.

WHY THIS IS THE ONLY THING THAT SHOULD HOLD THE TOKENS
------------------------------------------------------
Before this, the agents runtime hardcoded five endpoints and needed every token it might ever
use. Any caller wanting to reach two components held two credentials. Here a caller holds none:
it says "board" and "/api/board/settings", and the fabric attaches the key from its own
environment. A caller that is compromised cannot leak a credential it never had.
"""
from __future__ import annotations

import hmac
import os
import time
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel

from symoneural_fabric import wiring as R
from symoneural_fabric import route as T

UNIT = "fabric"
STARTED = time.time()

app = FastAPI(
    title="SyMoNeuRaL adaptive fabric",
    version="1.0.0",
    description="Component wiring: name a component, not a port.",
    docs_url="/api/fabric/docs",
    openapi_url="/api/fabric/openapi.json",
)


def require_token(authorization: Annotated[str | None, Header()] = None) -> None:
    expected = (os.environ.get("SYM_FABRIC_TOKEN") or "").strip()
    if not expected:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="fabric is unconfigured: SYM_FABRIC_TOKEN is not set")
    got = (authorization or "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(got, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="bad token")


Authed = Annotated[None, Depends(require_token)]


class CallIn(BaseModel):
    component: str
    path: str
    method: str = "GET"
    body: dict | None = None
    timeout: float = 30.0


def _guard(fn, *a, **kw) -> Any:
    try:
        return fn(*a, **kw)
    except R.FabricError as e:
        # 409, not 400 or 502: the request was well formed and the fabric declined to route it.
        # A caller reading 400 edits its payload; a caller reading 409 reads the reason, which
        # names the routable components or the prefix it stepped outside.
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(e))


@app.get("/api/fabric/health")
def health() -> dict[str, Any]:
    """Public; answers before the fabric is configured."""
    return {"unit": UNIT, "status": "ok", "uptime_s": round(time.time() - STARTED, 1),
            "configured": bool((os.environ.get("SYM_FABRIC_TOKEN") or "").strip())}


@app.get("/api/fabric/components")
def components(_: Authed) -> dict[str, Any]:
    """The wiring table, read from the board. Token NAMES only; never a token."""
    table = _guard(R.components)
    return {"source": R.BOARD, "count": len(table),
            "components": sorted(table.values(), key=lambda c: c["component"]),
            "not_routable": _guard(R.not_routable),
            "on_board_unaccounted": _guard(R.unknown_on_board),
            "unprovisioned": sorted(c["component"] for c in table.values()
                                    if c["token_env"] and not c["token_set"])}


@app.get("/api/fabric/reachable")
def reachable(_: Authed) -> dict[str, Any]:
    """Which components answer right now. Needs no token: health is public estate-wide."""
    rows = T.reachable()
    return {"components": rows, "up": sum(1 for r in rows if r["up"]), "count": len(rows)}


@app.get("/api/fabric/resolve")
def resolve(_: Authed, component: str, path: str) -> dict[str, Any]:
    """Where a call WOULD go, without making it. The refusals are the same ones `call` uses."""
    t = _guard(R.resolve, component, path)
    return {k: v for k, v in t.items() if k != "token_set"}


@app.post("/api/fabric/call")
def do_call(body: CallIn, _: Authed) -> dict[str, Any]:
    """Route one call and return the answer, with what it was routed to.

    `routed_to` is always in the response, including on an error from the far end. Wiring that
    cannot say where it went is wiring nobody can debug.
    """
    return _guard(T.call, body.component, body.path, body.method, body.body, body.timeout)


@app.get("/api/fabric/board")
def board(_: Authed) -> dict[str, Any]:
    """The ports section as the board actually writes it.

    Here because the board has been called this estate's port authority in five documents while
    exactly one service read it. Now a second one does, and the claim is load-bearing rather
    than prose.
    """
    return {"file": R.BOARD, "ports": _guard(R.ports)}


def main() -> None:
    import uvicorn
    uvicorn.run(app, host=os.environ.get("SYM_FABRIC_HOST", "127.0.0.1"),
                port=int(os.environ.get("SYM_FABRIC_PORT", "8816")))


if __name__ == "__main__":
    main()
