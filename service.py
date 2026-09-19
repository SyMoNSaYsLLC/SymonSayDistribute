#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
# SyMoNsAyLeaRn — SyMoNeuRaL, a subdivision of SymonSaysLLC. Terms: see LICENSE.
"""symonoematch over HTTP — §3.1b-i as a query instead of a search.

THE ROUTE THAT MATTERS IS `permissive`
The rule that decides where a component lives is the one about sources: name them, read the
licence off them, and reach for copyleft only after proving no permissive variant exists. That
proof was a manual search nobody kept a record of. `permissive` returns the three buckets and
the query it actually ran, so the record is the answer.

`match` is the same question asked of something that already exists on disk: fingerprint an
artifact, rank what provides its pieces, and carry each piece's licence class on the row.

Nothing here fetches from the network. `rebuild_plan` reports the command that would rebuild
the corpus; an operator runs it.
"""
from __future__ import annotations

import hmac
import ipaddress
import os
import time
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query, status

from symonoematch import prospect as P

UNIT = "symonoematch"
STARTED = time.time()

app = FastAPI(
    title="SyMoNeuRaL symonoematch",
    version="1.0.0",
    description="Naming a prospect's sources and reading their licences, from the local index.",
    docs_url="/api/symonoematch/docs",
    openapi_url="/api/symonoematch/openapi.json",
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
    host = (os.environ.get("SYM_OEMATCH_HOST") or "127.0.0.1").strip()
    if host.lower() in ("localhost", ""):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False          # a name we cannot prove is loopback is treated as reachable


def require_token(authorization: Annotated[str | None, Header()] = None) -> None:
    if _open_on_loopback():
        return
    expected = (os.environ.get("SYM_OEMATCH_TOKEN") or "").strip()
    if not expected:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="symonoematch is unconfigured: SYM_OEMATCH_TOKEN is not set")
    got = (authorization or "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(got, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="bad token")


Authed = Annotated[None, Depends(require_token)]


def _guard(fn, *a, **kw) -> Any:
    """A missing corpus and an unresolvable tool are 503 with the path, never an empty list.

    An empty result reads as "there is nothing", which is the one answer this component must
    never give by accident: under §3.1b-i "nothing permissive was found" is what sends a
    component to the open tree.
    """
    try:
        return fn(*a, **kw)
    except P.CorpusError as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))
    except P.ToolError as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(e))
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(e))


@app.get("/api/symonoematch/health")
def health() -> dict[str, Any]:
    """Public; answers before the corpus exists and before the tool is resolvable."""
    return {"unit": UNIT, "status": "ok", "uptime_s": round(time.time() - STARTED, 1),
            "configured": bool((os.environ.get("SYM_OEMATCH_TOKEN") or "").strip())}


@app.get("/api/symonoematch/freshness")
def freshness(_: Authed) -> dict[str, Any]:
    """How old this index is, how big, and what is in it. Every other answer carries the age."""
    return _guard(P.freshness)


@app.get("/api/symonoematch/tool")
def tool(_: Authed) -> dict[str, Any]:
    """Which oematch answered, its version read by running it, and what it can actually do."""
    return _guard(P.tool)


@app.get("/api/symonoematch/layers")
def layers(_: Authed, q: str = Query("", description="substring of the layer name"),
           limit: int = 100) -> dict[str, Any]:
    """Layers by name, with the licence each declares and whether its checkout is still there."""
    return _guard(P.layers, q, limit)


@app.get("/api/symonoematch/find")
def find(_: Authed, q: str = Query(..., description="the capability, in words"),
         limit: int = 25) -> dict[str, Any]:
    """Recipes providing a capability, permissive first and copyleft last (§3.1b-i)."""
    return _guard(P.find, q, limit)


@app.get("/api/symonoematch/licence_of")
def licence_of(_: Authed, pn: str = Query(..., description="exact recipe name"),
               limit: int = 100) -> dict[str, Any]:
    """Every layer carrying a recipe of this name, and the licence each one gives it."""
    return _guard(P.licence_of, pn, limit)


@app.get("/api/symonoematch/permissive")
def permissive(_: Authed, q: str = Query(..., description="the capability, in words"),
               limit: int = 25) -> dict[str, Any]:
    """Is there a NON-COPYLEFT implementation of this — with the query that was run."""
    return _guard(P.permissive, q, limit)


@app.get("/api/symonoematch/unlicensed")
def unlicensed(_: Authed, limit: int = 50) -> dict[str, Any]:
    """Recipes carrying no licence at all, and how many there are. A question, not a prospect."""
    return _guard(P.unlicensed, limit)


@app.get("/api/symonoematch/match")
def match(_: Authed, target: str = Query(..., description="a file or directory on this host"),
          top: int = 25) -> dict[str, Any]:
    """Fingerprint an artifact and rank the recipes that provide what it is made of.

    Reads any path this process can read. That is the same reach as the shell of whoever can
    call it, which on a loopback bind is somebody who already has code execution here (§3.2a).
    Off-loopback the token guard above applies before a path is ever opened.

    There is no timeout parameter and that is deliberate: the fingerprint phase extracts
    archives through calls that carry no timeout of their own and cannot be interrupted from
    here. A parameter that could only report an overrun after the call it was meant to bound
    would be a bound that cannot bind. The gap is stated in symonoematch.md.
    """
    return _guard(P.match, target, top)


@app.get("/api/symonoematch/upstream")
def upstream(_: Authed, url: str = Query(..., description="an upstream repository URL"),
             top: int = 8) -> dict[str, Any]:
    """Which layer carries this upstream project, and under which licence."""
    return _guard(P.upstream, url, top)


@app.get("/api/symonoematch/rebuild_plan")
def rebuild_plan(_: Authed) -> dict[str, Any]:
    """What rebuilding the corpus would do. Reported, never run: a GET does not pull a network."""
    return _guard(P.rebuild_plan)


def main() -> None:
    import uvicorn
    uvicorn.run(app, host=os.environ.get("SYM_OEMATCH_HOST", "127.0.0.1"),
                port=int(os.environ.get("SYM_OEMATCH_PORT", "8829")))


if __name__ == "__main__":
    main()
