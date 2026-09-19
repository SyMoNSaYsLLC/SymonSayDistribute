# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
# SyMoNsAyLeaRn — SyMoNeuRaL, a subdivision of SymonSaysLLC. Terms: see LICENSE.
"""Making the call — the fabric holds the credentials so its callers do not.

WHY THE FABRIC CALLS, RATHER THAN JUST TELLING YOU WHERE TO CALL
---------------------------------------------------------------
A resolver hands back an address and the caller still needs that component's token, so every
caller ends up holding every credential it might ever need. Six components, six tokens, in
every process that wants any of them.

Routing through means a caller names a component and a path, and the fabric attaches the token
from ITS OWN environment. A caller holds nothing. That is the difference between wiring that is
merely enumerable and wiring where a compromised caller cannot take a credential with it,
because it never had one.

WHAT IT REFUSES
---------------
An unknown component; a path outside that component's published prefix; a component whose token
is not provisioned. The last is a 503 naming the variable rather than an anonymous 401 from
somewhere downstream, because "the estate is not finished being set up" and "you are not
allowed" are different answers and only one of them is the operator's to fix.
"""
from __future__ import annotations

import json
import ipaddress
import urllib.parse
import os
import time
import urllib.error
import urllib.request
from typing import Any

from .wiring import FabricError, components, resolve

SAFE_METHODS = {"GET", "HEAD"}
METHODS = SAFE_METHODS | {"POST", "PUT", "PATCH", "DELETE"}



def call(component: str, path: str, method: str = "GET", body: dict | None = None,
         timeout: float = 30.0) -> dict[str, Any]:
    """Route one call. Returns the far end's answer, and always says what it routed to."""
    method = method.upper()
    if method not in METHODS:
        raise FabricError(f"{method!r} is not a method the fabric forwards")
    target = resolve(component, path)

    headers = {"accept": "application/json"}
    # No key is attached unless one exists, and a missing one is never a refusal.
    #
    # Garrett, 2026-09-19: keys are for traffic that leaves this machine. Everything the fabric
    # routes to is on this machine BY CONSTRUCTION — `wiring.components()` builds every base as
    # http://127.0.0.1:<port>, so there is no off-loopback case here to guard. Writing one
    # anyway would be a branch that cannot execute, which gates nothing and reads as protection.
    #
    # If a component is ever given a non-loopback base, this is the line that must change with
    # it: attach the key, and refuse when it is missing.
    env = target.get("token_env")
    if env:
        tok = (os.environ.get(env) or "").strip()
        if tok:
            headers["authorization"] = "Bearer " + tok

    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["content-type"] = "application/json"

    req = urllib.request.Request(target["url"], data=data, method=method, headers=headers)
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            status = r.status
    except urllib.error.HTTPError as e:
        raw, status = e.read(), e.code
    except urllib.error.URLError as e:
        raise FabricError(f"{component} at {target['base']} is not answering: {e.reason}")
    except Exception as e:
        raise FabricError(f"{component}: {type(e).__name__}: {e}")

    try:
        payload = json.loads(raw or b"null")
    except Exception:
        payload = {"raw": raw.decode(errors="replace")[:2000]}

    return {"component": component, "path": target["path"], "method": method,
            "status": status, "ms": round((time.time() - t0) * 1000, 1),
            "routed_to": target["url"], "body": payload}


def reachable(timeout: float = 4.0) -> list[dict[str, Any]]:
    """Which components answer right now.

    Health is unauthenticated on every unit in this estate by design, so this needs no token
    and reports honestly even for components the fabric could not call.
    """
    out = []
    for name, c in sorted(components().items()):
        url = c["base"] + c["health"]
        t0 = time.time()
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r:
                body = json.loads(r.read() or b"null")
                out.append({"component": name, "url": url, "up": r.status == 200,
                            "status": r.status, "ms": round((time.time() - t0) * 1000, 1),
                            "configured": body.get("configured") if isinstance(body, dict) else None,
                            "token_set": c["token_set"]})
        except Exception as e:
            out.append({"component": name, "url": url, "up": False,
                        "status": type(e).__name__, "token_set": c["token_set"]})
    return out
