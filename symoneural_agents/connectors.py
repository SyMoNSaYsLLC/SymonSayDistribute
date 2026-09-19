# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
"""Connectors — the tools that reach the rest of the estate.

A connector is a tool that talks to another SyMoNeuRaL component over its own HTTP surface.
That is the whole definition, and it is deliberately narrow: a connector never reaches into
another component's files or database, only through the endpoints that component publishes.
If a component has no endpoint for something, the connector cannot do it, and the answer is
to build the endpoint rather than to reach around it.

WHY THAT MATTERS MORE THAN IT SOUNDS
------------------------------------
It makes the estate's wiring visible. Every connection between components is a connector with
a name, a base URL and a licence class, and `connectors()` lists them. A component reaching
into another's internals privately is a connection nobody can enumerate — which is the state
this estate was in before the endpoints existed.

WHAT A CONNECTOR REFUSES
------------------------
To carry a credential in an argument. Each reads its own token from the environment at call
time. A model that could pass a credential as a tool argument could also be persuaded to put
one in a message, and then it is in a transcript.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from typing import Any

from .tools import Tool, ToolError

# EVERYTHING GOES THROUGH THE FABRIC. Garrett, 2026-09-19: all symon component wiring routes
# through the symoneural-adaptive-fabric.
#
# This file used to hold a table of five endpoints and five token variables, which meant this
# process had to hold every credential it might ever use. It now holds exactly one: the
# fabric's. A caller names a component and a path; the fabric knows where that component is
# (from /models/control.board) and attaches its key from its own environment.
#
# Two things follow that are worth more than the tidiness. An agent process that is compromised
# cannot leak a credential it never had. And a port change is one edit on the board rather than
# an edit here — this file no longer knows or cares what port anything is on.
FABRIC = os.environ.get("SYM_FABRIC_URL", "http://127.0.0.1:8816")
FABRIC_TOKEN_ENV = "SYM_FABRIC_TOKEN"


def _call(component: str, path: str, method: str = "GET", body: dict | None = None,
          timeout: float = 20.0) -> Any:
    """Reach another component THROUGH THE FABRIC. This process holds no component keys.

    The far end's answer is returned unwrapped, because a tool result is what the model reads
    and it should not have to understand the fabric's envelope to read it. What the fabric adds
    — where the call actually went — is put on the ToolError when something fails, which is the
    moment anybody wants it.
    """
    tok = (os.environ.get(FABRIC_TOKEN_ENV) or "").strip()
    if not tok:
        raise ToolError(
            f"the fabric needs {FABRIC_TOKEN_ENV} and it is not set. Every component is reached "
            f"through it, so this one variable is all this process needs — and all it can leak.")
    payload = json.dumps({"component": component, "path": path, "method": method,
                          "body": body, "timeout": timeout}).encode()
    req = urllib.request.Request(
        FABRIC.rstrip("/") + "/api/fabric/call", data=payload, method="POST",
        headers={"content-type": "application/json", "accept": "application/json",
                 "authorization": "Bearer " + tok})
    try:
        with urllib.request.urlopen(req, timeout=timeout + 10) as r:
            env = json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = json.loads(e.read()).get("detail", "")
        except Exception:
            pass
        raise ToolError(f"the fabric declined to route to {component}: {detail or e.reason}")
    except urllib.error.URLError as e:
        raise ToolError(f"the fabric at {FABRIC} is not answering: {e.reason}. Nothing can be "
                        f"reached without it — that is the cost of one place holding the keys.")
    except Exception as e:
        raise ToolError(f"fabric: {type(e).__name__}: {e}")

    status = env.get("status")
    if not isinstance(status, int) or not 200 <= status < 300:
        raise ToolError(f"{component} answered {status} at {env.get('routed_to')}: "
                        f"{str(env.get('body'))[:200]}")
    return env.get("body")


def _fabric_get(path: str, timeout: float = 20.0) -> Any:
    """Ask the fabric about itself — the wiring table, or what is reachable."""
    tok = (os.environ.get(FABRIC_TOKEN_ENV) or "").strip()
    if not tok:
        raise ToolError(f"the fabric needs {FABRIC_TOKEN_ENV} and it is not set")
    req = urllib.request.Request(FABRIC.rstrip("/") + path, headers={
        "accept": "application/json", "authorization": "Bearer " + tok})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"null")
    except Exception as e:
        raise ToolError(f"the fabric at {FABRIC} did not answer {path}: {e}")


# Each connector below is reached AS A TOOL, inside a run, not as a route of its own. That is
# the point of them: an agent is granted a subset, and a capability it was not granted is never
# declared. Routing them individually would create a second way in that no grant governs — a
# caller could then do through HTTP exactly what the grant exists to bound.
#
# They are still enumerable: GET /api/agents/connectors lists every one with its component,
# endpoint and token variable, and whether the far end is answering.
NOT_EXPOSED = {
    "web_fetch":      "granted as a tool; enumerated by GET /api/agents/connectors",
    "web_browse":     "granted as a tool; enumerated by GET /api/agents/connectors",
    "estate_survey":  "granted as a tool; enumerated by GET /api/agents/connectors",
    "estate_layers":  "granted as a tool; enumerated by GET /api/agents/connectors",
    "estate_live":    "granted as a tool; enumerated by GET /api/agents/connectors",
    "board_settings": "granted as a tool; enumerated by GET /api/agents/connectors",
    "board_status":   "granted as a tool; enumerated by GET /api/agents/connectors",
    "board_check":    "granted as a tool; enumerated by GET /api/agents/connectors",
    "model_budget":   "granted as a tool; enumerated by GET /api/agents/connectors",
    "model_kv_cache": "granted as a tool; enumerated by GET /api/agents/connectors",
    "list_models":    "granted as a tool; enumerated by GET /api/agents/connectors",
    "connectors":     "routed as GET /api/agents/connectors",
    "reachable":      "routed as part of GET /api/agents/connectors",
}

# --------------------------------------------------------------------------- the connectors
def board_settings(a: dict) -> Any:
    """Every configured setting, or one section of them."""
    section = a.get("section")
    return _call("board", "/api/board/settings" + (f"?section={section}" if section else ""))


def board_status(a: dict) -> Any:
    """What is actually running, measured now, with anything that has drifted marked."""
    return _call("board", "/api/board/live")


def board_check(a: dict) -> Any:
    """Whether every path on the board exists, every port is a port, nothing is stale."""
    return _call("board", "/api/board/check")


def model_budget(a: dict) -> Any:
    """Does a checkpoint fit on a card: weights plus cache, with the shortfall named."""
    for k in ("model_dir", "context", "vram_bytes"):
        if k not in a:
            raise ToolError(f"model_budget needs {k}")
    return _call("ravencalc", "/api/ravencalc/model/budget", "POST", {
        "model_dir": a["model_dir"], "context": int(a["context"]),
        "sequences": int(a.get("sequences", 1)), "vram_bytes": int(a["vram_bytes"])})


def model_kv_cache(a: dict) -> Any:
    """Key/value cache bytes for a context and concurrency, from the checkpoint itself."""
    for k in ("model_dir", "context"):
        if k not in a:
            raise ToolError(f"model_kv_cache needs {k}")
    return _call("ravencalc", "/api/ravencalc/model/kv-cache", "POST", {
        "model_dir": a["model_dir"], "context": int(a["context"]),
        "sequences": int(a.get("sequences", 1))})


def list_models(a: dict) -> Any:
    """The model rows the gateway offers."""
    return _call("gateway", "/v1/models")


def estate_survey(a: dict) -> Any:
    """What this estate is, read from disk: units, subcomponents, edges, layers, live state.

    One call rather than six, deliberately. A question a model has to know the shape of in
    advance is a question it will not ask, and "what is in this estate" should not require
    knowing which routes to stitch together.
    """
    tree = a.get("tree", "SymonSayDistribute")
    return _call("symonscope", f"/api/symonscope/survey?tree={tree}", timeout=60.0)


def estate_layers(a: dict) -> Any:
    """Which component rests on which, derived from real dependencies rather than declared."""
    tree = a.get("tree", "SymonSayDistribute")
    return _call("symonscope", f"/api/symonscope/layers?tree={tree}", timeout=60.0)


def estate_live(a: dict) -> Any:
    """What is running against what is declared, with every disagreement named."""
    tree = a.get("tree", "SymonSayDistribute")
    return _call("symonscope", f"/api/symonscope/live?tree={tree}", timeout=60.0)


def web_fetch(a: dict) -> Any:
    """Read a public web page: one request, no javascript."""
    if not a.get("url"):
        raise ToolError("web_fetch needs a url")
    return _call("symonweb", "/api/symonweb/fetch", "POST",
                 {"url": a["url"], "timeout": float(a.get("timeout", 20.0))}, timeout=60.0)


def web_browse(a: dict) -> Any:
    """Read a public web page as a reader sees it, with scripts run. Costs a browser."""
    if not a.get("url"):
        raise ToolError("web_browse needs a url")
    return _call("symonweb", "/api/symonweb/browse", "POST",
                 {"url": a["url"], "headless": True}, timeout=120.0)


CONNECTORS: list[Tool] = [
    Tool("board_settings", "Every configured setting in the estate, or one section. "
         "Optional argument: section.",
         {"type": "object", "properties": {"section": {"type": "string"}}}, board_settings),
    Tool("board_status", "What is actually running right now, measured, with anything that "
         "has drifted from the configuration marked.",
         {"type": "object", "properties": {}}, board_status),
    Tool("board_check", "Whether every path on the control board exists, every port is a "
         "port, and nothing is an unmeasured value.",
         {"type": "object", "properties": {}}, board_check),
    Tool("model_kv_cache", "Key/value cache size for a checkpoint at a given context and "
         "concurrency, derived from the checkpoint rather than estimated.",
         {"type": "object",
          "properties": {"model_dir": {"type": "string"}, "context": {"type": "integer"},
                         "sequences": {"type": "integer"}},
          "required": ["model_dir", "context"]}, model_kv_cache),
    Tool("model_budget", "Whether a checkpoint fits on a card at a given context and "
         "concurrency, with the shortfall named if it does not.",
         {"type": "object",
          "properties": {"model_dir": {"type": "string"}, "context": {"type": "integer"},
                         "sequences": {"type": "integer"}, "vram_bytes": {"type": "integer"}},
          "required": ["model_dir", "context", "vram_bytes"]}, model_budget),
    Tool("list_models", "The model rows this estate offers.",
         {"type": "object", "properties": {}}, list_models),
    Tool("estate_survey", "What this estate actually is, read from disk right now: every "
         "component, the components inside them, what depends on what with the file and line "
         "proving it, the layers derived from those dependencies, and what is running against "
         "what is declared. Use this for any question about what exists, what is built, what "
         "is wired to what, or what is running — it is faster and more current than reasoning "
         "from memory, and it cannot go stale.",
         {"type": "object", "properties": {"tree": {"type": "string",
          "description": "one of SymonSayDistribute, SymonSaySource, SymonSayOpen, SymonSayOSS; "
                         "defaults to SymonSayDistribute"}}}, estate_survey),
    Tool("estate_layers", "Which components rest on which, derived from real dependency edges "
         "rather than from a written-down list. Reports cycles instead of hiding them.",
         {"type": "object", "properties": {"tree": {"type": "string",
          "description": "one of SymonSayDistribute, SymonSaySource, SymonSayOpen, SymonSayOSS; "
                         "defaults to SymonSayDistribute"}}}, estate_layers),
    Tool("estate_live", "What is listening right now against what each component declares, "
         "with every disagreement named — a declared port with nothing on it, a port running "
         "from the wrong tree, a port nothing claims.",
         {"type": "object", "properties": {"tree": {"type": "string",
          "description": "one of SymonSayDistribute, SymonSaySource, SymonSayOpen, SymonSayOSS; "
                         "defaults to SymonSayDistribute"}}}, estate_live),
    Tool("web_fetch", "Read a public web page and get back its title, text and links. One HTTP "
         "request, no javascript — fast, and what most pages need. Any address that is not "
         "public is refused, so this cannot be pointed at the estate's own services.",
         {"type": "object",
          "properties": {"url": {"type": "string"}, "timeout": {"type": "number"}},
          "required": ["url"]}, web_fetch),
    Tool("web_browse", "Read a public web page the way a reader sees it, with javascript run. "
         "Use when a page comes back empty or wrong under web_fetch, which means it builds "
         "itself in the browser. Costs a browser process, so try web_fetch first.",
         {"type": "object", "properties": {"url": {"type": "string"}},
          "required": ["url"]}, web_browse),
]


def connectors() -> list[dict]:
    """Every wire between components, enumerated.

    The endpoint and the token variable are no longer known here — the fabric owns them, and
    asking it is the point. If the fabric is not answering this reports that rather than
    printing a table it cannot stand behind, because a wiring list that keeps working when the
    wiring is down is a list that is lying.
    """
    by_tool = {
        "board_settings": "board", "board_status": "board", "board_check": "board",
        "model_kv_cache": "ravencalc", "model_budget": "ravencalc",
        "list_models": "gateway",
        "estate_survey": "symonscope", "estate_layers": "symonscope",
        "estate_live": "symonscope",
        "web_fetch": "symonweb", "web_browse": "symonweb",
    }
    try:
        table = {c["component"]: c for c in _fabric_get("/api/fabric/components")["components"]}
        err = None
    except ToolError as e:
        table, err = {}, str(e)
    rows = []
    for tool in CONNECTORS:
        comp = by_tool.get(tool.name, "?")
        c = table.get(comp, {})
        rows.append({"tool": tool.name, "component": comp,
                     "via": "fabric", "fabric": FABRIC,
                     "endpoint": c.get("base"), "token_variable": c.get("token_env"),
                     "token_set": c.get("token_set"),
                     "mutates": tool.mutates, "description": tool.description,
                     **({"fabric_error": err} if err else {})})
    return rows


def reachable() -> list[dict]:
    """Which components answer, right now, as the fabric sees them.

    Asked of the fabric rather than probed here on purpose: this process no longer knows where
    anything is, and a second opinion assembled from a stale local table would be worse than no
    opinion. If the fabric is down, everything is unreachable from here and that is the honest
    answer rather than a per-component guess.
    """
    try:
        return _fabric_get("/api/fabric/reachable")["components"]
    except ToolError as e:
        return [{"component": "fabric", "endpoint": FABRIC, "up": False, "status": str(e),
                 "note": "every component is reached through the fabric, so nothing is "
                         "reachable while it is down"}]
