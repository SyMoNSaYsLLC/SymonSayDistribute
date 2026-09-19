#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
# SyMoNsAyLeaRn — SyMoNeuRaL, a subdivision of SymonSaysLLC. Terms: see LICENSE.
"""symonskill over HTTP — the named procedures this estate knows.

Six skills sat on disk with no way to discover them. This is that way.

It catalogues; it does not execute. Running a skill's script needs the permission to execute,
and a catalogue that also executed could not be asked "what is available?" without risk. Same
separation as symonscheduler (computes WHEN, runs nothing) and symonloop (remembers WHAT,
executes nothing).
"""
from __future__ import annotations

import hmac
import ipaddress
import os
import time
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, status

from symonskill import catalogue as C

UNIT = "symonskill"
STARTED = time.time()

app = FastAPI(
    title="SyMoNeuRaL symonskill",
    version="1.0.0",
    description="The named procedures this estate knows, made reachable.",
    docs_url="/api/symonskill/docs",
    openapi_url="/api/symonskill/openapi.json",
)


def _open_on_loopback() -> bool:
    """A key is for traffic that leaves this machine. Loopback traffic does not (§3.2a)."""
    host = (os.environ.get("SYM_SKILL_HOST") or "127.0.0.1").strip()
    if host.lower() in ("localhost", ""):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def require_token(authorization: Annotated[str | None, Header()] = None) -> None:
    if _open_on_loopback():
        return
    expected = (os.environ.get("SYM_SKILL_TOKEN") or "").strip()
    if not expected:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="symonskill is bound off-loopback and SYM_SKILL_TOKEN is not "
                                   "set; a reachable unit will not serve without a key")
    got = (authorization or "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(got, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="bad token")


Authed = Annotated[None, Depends(require_token)]


def _guard(fn) -> Any:
    try:
        return fn()
    except C.SkillError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(e))


@app.get("/api/symonskill/health")
def health() -> dict[str, Any]:
    """Public; answers before the unit is configured and before any skill is found."""
    return {"unit": UNIT, "status": "ok", "uptime_s": round(time.time() - STARTED, 1),
            "roots": [str(r) for r in C.roots()]}


@app.get("/api/symonskill/skills")
def list_skills(_: Authed) -> dict[str, Any]:
    """Every skill found, with invalid ones named rather than dropped."""
    return _guard(lambda: C.skills())


@app.get("/api/symonskill/skills/{name}")
def get_skill(_: Authed, name: str) -> dict[str, Any]:
    """One skill with its body — what a caller loads when it decides to use it."""
    return _guard(lambda: C.get(name))


@app.get("/api/symonskill/relevant")
def relevant(_: Authed, task: str, limit: int = 5) -> dict[str, Any]:
    """Which skills a task might need, ranked, with the words that matched."""
    return _guard(lambda: C.relevant(task, limit=limit))


@app.get("/api/symonskill/validate")
def validate(_: Authed) -> dict[str, Any]:
    """Every contract defect across the collection. Reports; never repairs."""
    return _guard(lambda: C.validate())


@app.get("/api/symonskill/frontmatter")
def frontmatter(_: Authed, text: str) -> dict[str, Any]:
    """Read a metadata block and say precisely what is wrong with it, without storing it."""
    return _guard(lambda: C.parse_frontmatter(text))


def main() -> None:
    import uvicorn
    uvicorn.run(app, host=os.environ.get("SYM_SKILL_HOST", "127.0.0.1"),
                port=int(os.environ.get("SYM_SKILL_PORT", "8833")))


if __name__ == "__main__":
    main()
