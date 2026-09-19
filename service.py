#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
"""Agents over HTTP — start a run, watch it, stop it.

The loop and the registry are a library; this is what makes them supervisable. Every field the
operator panel needs is here: name, state, elapsed, what was granted, which tools were called,
which failed, why it stopped.

WHAT A CALLER MAY NOT DO
------------------------
Grant a tool that does not exist, or pass a credential. Tools are selected by name from the
registry this process holds; a name that is not there is refused before the run starts rather
than at the moment the model reaches for it. And every connector reads its own token from the
environment, so there is no argument through which one could travel.

STOPPING
--------
`stop` asks. The run ends after the step it is in, so a tool mid-write is never cut in half.
That is slower than killing a thread and it is the only version that leaves the filesystem in
a state anyone can reason about.
"""
from __future__ import annotations

import hmac
import json
import os
import time
import urllib.request
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel, Field

from symoneural_agents import connectors as C
from symoneural_agents import plugins as P
from symoneural_agents.registry import RunNotFound, Runs
from symoneural_agents.tools import Registry, ToolError

UNIT = "agents"
STARTED = time.time()

app = FastAPI(
    title="SyMoNeuRaL agents",
    version="1.1.0",
    description="Bounded runs against Symon, with capabilities granted before they start.",
    docs_url="/api/agents/docs",
    openapi_url="/api/agents/openapi.json",
)

TOOLS = Registry()
for _t in C.CONNECTORS:
    TOOLS.add(_t)

# Plugins add tools. Discovery happens at start-up and the RECORD is kept, so the surface can
# say what was present, what was enabled, and what was refused — three different states that a
# bare list of loaded tools collapses into one.
PLUGIN_RECORD: list[dict] = []
try:
    _ptools, PLUGIN_RECORD = P.load(C._call)
    for _t in _ptools:
        try:
            TOOLS.add(_t)
        except ValueError as _e:
            # A plugin may not take a name the estate already uses. Refusing is the only safe
            # answer: silently overriding a connector would let a plugin redirect a tool an
            # agent already trusts.
            PLUGIN_RECORD.append({"name": _t.name, "state": "refused", "why": str(_e)})
except Exception as _e:                      # a broken plugin directory must not stop the unit
    PLUGIN_RECORD = [{"state": "discovery failed", "why": f"{type(_e).__name__}: {_e}"}]

RUNS = Runs(max_concurrent=int(os.environ.get("SYM_AGENTS_MAX_CONCURRENT", "4")))


def require_token(authorization: Annotated[str | None, Header()] = None) -> None:
    expected = (os.environ.get("SYM_AGENTS_TOKEN") or "").strip()
    if not expected:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="agents is unconfigured: SYM_AGENTS_TOKEN is not set")
    presented = authorization[7:].strip() if authorization and authorization.lower().startswith("bearer ") else ""
    if not presented or not hmac.compare_digest(presented.encode(), expected.encode()):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="invalid or missing credential")


Authed = Annotated[None, Depends(require_token)]


def _send(payload: dict, timeout: float | None = None) -> dict:
    """One turn against the dialect gateway.

    The credential is read from the file named by SYM_GW_KEY_FILE at call time and used in the
    same expression. It is not held on the app, not passed in, and not logged.
    """
    url = C.ENDPOINTS["gateway"].rstrip("/") + "/v1/messages"
    path = os.path.expanduser(os.environ.get(
        "SYM_GW_KEY_FILE", "~/.config/symoneural/gateway-9001.key"))
    try:
        key = open(path).read().strip()
    except OSError as e:
        raise ToolError(f"no gateway credential at {path}: {e}")
    req = urllib.request.Request(
        url, data=json.dumps(payload).encode(), method="POST",
        headers={"content-type": "application/json", "anthropic-version": "2023-06-01",
                 "authorization": "Bearer " + key})
    # The run's remaining budget, when the loop supplies one, so a single slow turn cannot
    # outlive the bound the run was started with.
    cap = float(os.environ.get("SYM_AGENTS_TURN_TIMEOUT", "900"))
    with urllib.request.urlopen(req, timeout=min(cap, timeout) if timeout else cap) as r:
        return json.loads(r.read())


class StartIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=64)
    task: str = Field(..., min_length=1)
    tools: list[str] = Field(default_factory=list,
                             description="tool names to grant; anything not listed is never declared")
    model: str = Field("symon-sonnet")
    max_steps: int = Field(8, ge=1, le=200, description="no default generous enough to ignore")
    max_seconds: float = Field(600.0, gt=0, le=86400)


# --------------------------------------------------------------------------- public
@app.get("/api/agents/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "unit": UNIT, "uptime_s": round(time.time() - STARTED, 1),
            "tools": len(TOOLS.names()), "active": RUNS.active(),
            "max_concurrent": RUNS.max_concurrent}


# --------------------------------------------------------------------------- capabilities
@app.get("/api/agents/tools")
def tools(_: Authed) -> dict[str, Any]:
    """Every tool that can be granted. A run gets a subset of this and nothing else."""
    grant = TOOLS.grant(TOOLS.names())
    return {"count": len(TOOLS.names()), "tools": grant.declare()}


@app.get("/api/agents/connectors")
def connectors(_: Authed) -> dict[str, Any]:
    """Every wire between components, and whether the far end is answering.

    A connector to something that is not running is a wire to nowhere. Saying so here is more
    useful than a timeout inside a run three steps later.
    """
    return {"connectors": C.connectors(), "reachable": C.reachable()}


@app.get("/api/agents/plugins")
def plugins(_: Authed) -> dict[str, Any]:
    """Every plugin present, what it declares, and what was decided about it.

    A plugin is a MANIFEST, never code. It names a component, where that component answers,
    and the tools that reach it — so the worst a hostile one can do is point a tool at an
    endpoint, which is readable before it is enabled.

    Presence is not consent: nothing loads until it is named in SYM_PLUGINS_ENABLED. A plugin
    whose licence this runtime cannot absorb without a placement decision is listed with that
    reason rather than loaded.
    """
    return {"root": str(P.plugin_root()),
            "enabled": P.enabled_names(),
            "count": len(PLUGIN_RECORD),
            "permissive_licences": sorted(P.PERMISSIVE),
            "plugins": PLUGIN_RECORD}


# --------------------------------------------------------------------------- runs
@app.post("/api/agents/runs")
def start(body: StartIn, _: Authed) -> dict[str, Any]:
    names = body.tools or TOOLS.names()
    try:
        grant = TOOLS.grant(names)
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    try:
        run = RUNS.start(body.name, body.task, grant, _send, model=body.model,
                         max_steps=body.max_steps, max_seconds=body.max_seconds)
    except RuntimeError as e:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, detail=str(e))
    return run.report() | {"granted": grant.names(), "read_only": grant.read_only()}


@app.get("/api/agents/runs")
def list_runs(_: Authed, state: str | None = None) -> dict[str, Any]:
    rows = RUNS.list(state)
    return {"count": len(rows), "active": RUNS.active(),
            "max_concurrent": RUNS.max_concurrent, "runs": rows}


@app.get("/api/agents/runs/{run_id}")
def get_run(run_id: str, _: Authed) -> dict[str, Any]:
    try:
        e = RUNS.get(run_id)
    except RunNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"no run {run_id}")
    r = e.run.report()
    r["live"] = bool(e.thread and e.thread.is_alive())
    r["stopping"] = e.stopping
    r["steps"] = [{"n": s.n, "kind": s.kind, "tool": s.tool, "seconds": s.seconds,
                   "is_error": s.is_error,
                   # the result is truncated, not omitted: a step nobody can see is a step
                   # nobody can debug, and a whole tool output is not a supervision surface
                   "result": (s.result or "")[:2000]} for s in e.run.steps]
    return r


@app.post("/api/agents/runs/{run_id}/stop")
def stop_run(run_id: str, _: Authed) -> dict[str, Any]:
    try:
        return RUNS.stop(run_id)
    except RunNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"no run {run_id}")


@app.delete("/api/agents/runs")
def clear(_: Authed) -> dict[str, Any]:
    """Forget finished runs. Live ones are never dropped."""
    return {"cleared": RUNS.clear(keep_live=True), "remaining": len(RUNS.list())}


def main() -> None:
    import uvicorn
    uvicorn.run(app, host=os.environ.get("SYM_AGENTS_HOST", "127.0.0.1"),
                port=int(os.environ.get("SYM_AGENTS_PORT", "8813")),
                log_level=os.environ.get("SYM_LOG_LEVEL", "info"))


if __name__ == "__main__":
    main()
