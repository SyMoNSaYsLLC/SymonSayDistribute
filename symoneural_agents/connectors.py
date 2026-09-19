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

# Where each component answers. Every one is a first-party surface on this host.
ENDPOINTS = {
    "board":     os.environ.get("SYM_BOARD_URL",     "http://127.0.0.1:8811"),
    "ravencalc": os.environ.get("SYM_RAVENCALC_URL", "http://127.0.0.1:8801"),
    "gateway":   os.environ.get("SYM_GW_URL",        "http://127.0.0.1:9001"),
    "store":     os.environ.get("SYM_STORE_URL",     "http://127.0.0.1:8812"),
    "symonscope": os.environ.get("SYM_SCOPE_URL",    "http://127.0.0.1:8815"),
}

# The token each one wants, by NAME. Read at call time, never passed as an argument.
TOKEN_ENV = {
    "board":     "SYM_BOARD_TOKEN",
    "ravencalc": "SYM_RAVENCALC_TOKEN",
    "gateway":   None,          # the gateway reads a key FILE, named on the board
    "store":     "SYM_STORE_TOKEN",
    "symonscope": "SYM_SCOPE_TOKEN",
}


def _call(component: str, path: str, method: str = "GET", body: dict | None = None,
          timeout: float = 20.0) -> Any:
    base = ENDPOINTS.get(component)
    if not base:
        raise ToolError(f"no endpoint known for {component}")
    url = base.rstrip("/") + path
    headers = {"accept": "application/json"}
    env = TOKEN_ENV.get(component)
    if env:
        tok = os.environ.get(env, "").strip()
        if not tok:
            raise ToolError(
                f"{component} needs {env} and it is not set. The token is read here from the "
                f"environment and is never accepted as an argument.")
        headers["authorization"] = "Bearer " + tok
    data = json.dumps(body).encode() if body is not None else None
    if data is not None:
        headers["content-type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        detail = ""
        try:
            detail = json.loads(e.read()).get("detail", "")
        except Exception:
            pass
        raise ToolError(f"{component} answered {e.code}: {detail or e.reason}")
    except urllib.error.URLError as e:
        raise ToolError(f"{component} at {base} is not answering: {e.reason}")
    except Exception as e:
        raise ToolError(f"{component}: {type(e).__name__}: {e}")


# Each connector below is reached AS A TOOL, inside a run, not as a route of its own. That is
# the point of them: an agent is granted a subset, and a capability it was not granted is never
# declared. Routing them individually would create a second way in that no grant governs — a
# caller could then do through HTTP exactly what the grant exists to bound.
#
# They are still enumerable: GET /api/agents/connectors lists every one with its component,
# endpoint and token variable, and whether the far end is answering.
NOT_EXPOSED = {
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
]


def connectors() -> list[dict]:
    """Every wire between components, enumerated. This is what makes the estate's own
    connections visible rather than implicit."""
    by_tool = {
        "board_settings": "board", "board_status": "board", "board_check": "board",
        "model_kv_cache": "ravencalc", "model_budget": "ravencalc",
        "list_models": "gateway",
        "estate_survey": "symonscope", "estate_layers": "symonscope",
        "estate_live": "symonscope",
    }
    return [{"tool": t.name, "component": by_tool.get(t.name, "?"),
             "endpoint": ENDPOINTS.get(by_tool.get(t.name, ""), ""),
             "token_variable": TOKEN_ENV.get(by_tool.get(t.name, "")),
             "mutates": t.mutates, "description": t.description}
            for t in CONNECTORS]


def reachable() -> list[dict]:
    """Which components actually answer, right now. A connector to something that is not
    running is a wire to nowhere, and saying so is more useful than a timeout later."""
    out = []
    for name, base in ENDPOINTS.items():
        path = {"gateway": "/health", "board": "/api/board/health",
                "ravencalc": "/api/ravencalc/health", "store": "/api/store/health",
                "symonscope": "/api/symonscope/health"}.get(name, "/health")
        try:
            with urllib.request.urlopen(base.rstrip("/") + path, timeout=4) as r:
                out.append({"component": name, "endpoint": base, "up": r.status == 200,
                            "status": r.status})
        except Exception as e:
            out.append({"component": name, "endpoint": base, "up": False,
                        "status": type(e).__name__})
    return out
