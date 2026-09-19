#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
# SyMoNsAyLeaRn — SyMoNeuRaL, a subdivision of SymonSaysLLC. Terms: see LICENSE.
"""symonweb over HTTP — the estate's only component that reaches off this host.

Six routes under /api/symonweb/. Two ways to read a page and they are not interchangeable:

    fetch    one HTTP request, no javascript. Fast, cheap, and what most pages need.
    browse   a real browser, scripts run, the text is what a reader would see. Seconds and
             hundreds of megabytes of process, so it is asked for rather than defaulted to.

THE BOUNDARY THIS UNIT SITS ON
------------------------------
Everything else here binds loopback and talks to things on this host. This one goes out, and it
does so on behalf of a model that takes instructions from whoever is talking to it. Every
refusal in `guard` exists for that: a URL that resolves to a private address is declined before
the request and after every redirect, because the shortest path from "summarise this page" to
"read the control board" is a link.
"""
from __future__ import annotations

import hmac
import ipaddress
import os
import time
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel

from symonweb import browse as B
from symonweb import fetch as F
from symonweb import guard as G

UNIT = "symonweb"
STARTED = time.time()

app = FastAPI(
    title="SyMoNeuRaL symonweb",
    version="1.0.0",
    description="Fetch a page, or drive a browser. The only component that leaves this host.",
    docs_url="/api/symonweb/docs",
    openapi_url="/api/symonweb/openapi.json",
)

# One politeness clock for the process, so two callers cannot hammer one host by arriving
# separately. No default interval: it is a decision about how this estate behaves to others.
_POLITE = G.Politeness(min_interval_s=float(os.environ.get("SYM_WEB_MIN_INTERVAL_S", "1.0")))


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
    host = (os.environ.get("SYM_WEB_HOST") or "127.0.0.1").strip()
    if host.lower() in ("localhost", ""):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False          # a name we cannot prove is loopback is treated as reachable

def require_token(authorization: Annotated[str | None, Header()] = None) -> None:
    if _open_on_loopback():
        return
    expected = (os.environ.get("SYM_WEB_TOKEN") or "").strip()
    if not expected:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="symonweb is unconfigured: SYM_WEB_TOKEN is not set")
    got = (authorization or "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(got, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="bad token")


Authed = Annotated[None, Depends(require_token)]


class FetchIn(BaseModel):
    url: str
    timeout: float = 20.0
    max_bytes: int = G.MAX_BYTES
    ignore_robots: bool = False
    robots_reason: str = ""


class BrowseIn(BaseModel):
    url: str
    driver: str | None = None
    headless: bool = True
    page_load_s: float = 30.0


def _refusal(e: G.Refused) -> HTTPException:
    # 403, not 400: the request was well formed and this unit declined to make it. The reason
    # is the useful part and it is always present.
    return HTTPException(status.HTTP_403_FORBIDDEN,
                         detail={"refused": e.reason, "url": e.url})


@app.get("/api/symonweb/health")
def health() -> dict[str, Any]:
    """Public; answers before the unit is configured."""
    return {"unit": UNIT, "status": "ok", "uptime_s": round(time.time() - STARTED, 1),
            "configured": bool((os.environ.get("SYM_WEB_TOKEN") or "").strip())}


@app.get("/api/symonweb/drivers")
def drivers(_: Authed) -> dict[str, Any]:
    """Which W3C WebDriver implementations are on this host."""
    rows = B.drivers()
    return {"count": len(rows), "drivers": rows,
            "note": "any W3C driver works; nothing here is specific to one browser"}


@app.get("/api/symonweb/robots")
def robots(_: Authed, url: str) -> dict[str, Any]:
    """What robots.txt says, without fetching the page. `allowed: null` means unknown."""
    return G.robots_allows(url)


@app.get("/api/symonweb/check")
def check(_: Authed, url: str) -> dict[str, Any]:
    """Would this be allowed, and where does it resolve? Asked without making a request."""
    try:
        return {"allowed": True, **G.check_public(url)}
    except G.Refused as e:
        return {"allowed": False, "refused": e.reason, "url": e.url}


@app.post("/api/symonweb/fetch")
def do_fetch(body: FetchIn, _: Authed) -> dict[str, Any]:
    """One HTTP request, no javascript. What most pages need."""
    try:
        where = G.check_public(body.url)
        _POLITE.check(where["host"])
        return F.fetch(body.url, timeout=body.timeout, max_bytes=body.max_bytes,
                       ignore_robots=body.ignore_robots, robots_reason=body.robots_reason)
    except G.Refused as e:
        raise _refusal(e)


@app.post("/api/symonweb/browse")
def do_browse(body: BrowseIn, _: Authed) -> dict[str, Any]:
    """A real browser. Scripts run; the text is what a reader would see."""
    try:
        where = G.check_public(body.url)
        _POLITE.check(where["host"])
        return B.visit(body.url, driver=body.driver, headless=body.headless,
                       page_load_s=body.page_load_s)
    except G.Refused as e:
        raise _refusal(e)
    except B.BrowserError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(e))


def main() -> None:
    import uvicorn
    uvicorn.run(app, host=os.environ.get("SYM_WEB_HOST", "127.0.0.1"),
                port=int(os.environ.get("SYM_WEB_PORT", "8818")))


if __name__ == "__main__":
    main()
