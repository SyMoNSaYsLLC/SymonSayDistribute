#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
# SyMoNsAyLeaRn — SyMoNeuRaL, a subdivision of SymonSaysLLC. Terms: see LICENSE.
"""symonlora over HTTP — everything before the card is taken.

Six routes under /api/symonlora/. What this automates is the part of a LoRA run that goes wrong
quietly: the training set that trains cleanly and makes the model worse, the plan that says it
fits and does not, the missing package discovered at hour two.

WHY THERE IS NO `train` ROUTE
-----------------------------
Not an omission. Training needs peft, datasets and accelerate, none of which are installed here,
and it needs the one GPU that is currently serving. A route that accepted a training request and
failed inside would be a promise this unit cannot keep — and starting a run from an HTTP call is
how a card gets taken while somebody is using it.

`prereq` names exactly what is missing and the command that fixes it. That is the honest surface
for a thing that is not ready, and it is a better one than a 501.
"""
from __future__ import annotations

import hmac
import ipaddress
import os
import time
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel

from symonlora import dataset as D
from symonlora import plan as P
from symonlora import prereq as Q

UNIT = "symonlora"
STARTED = time.time()

app = FastAPI(
    title="SyMoNeuRaL symonlora",
    version="1.0.0",
    description="Plan a LoRA, validate its training set, and know what is missing first.",
    docs_url="/api/symonlora/docs",
    openapi_url="/api/symonlora/openapi.json",
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
    host = (os.environ.get("SYM_LORA_HOST") or "127.0.0.1").strip()
    if host.lower() in ("localhost", ""):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False          # a name we cannot prove is loopback is treated as reachable

def require_token(authorization: Annotated[str | None, Header()] = None) -> None:
    if _open_on_loopback():
        return
    expected = (os.environ.get("SYM_LORA_TOKEN") or "").strip()
    if not expected:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="symonlora is unconfigured: SYM_LORA_TOKEN is not set")
    got = (authorization or "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(got, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="bad token")


Authed = Annotated[None, Depends(require_token)]


def _guard(fn, *a, **kw) -> Any:
    try:
        return fn(*a, **kw)
    except (P.PlanError, D.DatasetError, Q.PrereqError) as e:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(e))


class PlanIn(BaseModel):
    model_dir: str
    rank: int = 16
    alpha: int | None = None
    targets: list[str] | None = None
    dtype: str = "bf16"
    optimizer: str = "adamw"
    free_bytes: int | None = None


class DataIn(BaseModel):
    path: str
    minimum: int = D.SUGGESTED_MINIMUM
    max_chars: int | None = None


@app.get("/api/symonlora/health")
def health() -> dict[str, Any]:
    """Public; answers before the unit is configured."""
    return {"unit": UNIT, "status": "ok", "uptime_s": round(time.time() - STARTED, 1),
            "configured": bool((os.environ.get("SYM_LORA_TOKEN") or "").strip())}


@app.get("/api/symonlora/prereq")
def prereq(_: Authed, venv: str) -> dict[str, Any]:
    """What a run needs, what is present, and the command that fixes the difference."""
    return _guard(Q.check, venv)


@app.post("/api/symonlora/plan")
def do_plan(body: PlanIn, _: Authed) -> dict[str, Any]:
    """Adapter size and trainable memory, derived from the checkpoint's own config."""
    targets = tuple(body.targets) if body.targets else P.ATTENTION
    return _guard(P.plan, body.model_dir, rank=body.rank, alpha=body.alpha, targets=targets,
                  dtype=body.dtype, optimizer=body.optimizer, free_bytes=body.free_bytes)


@app.post("/api/symonlora/modules")
def modules(body: PlanIn, _: Authed) -> dict[str, Any]:
    """Which modules this architecture exposes to a LoRA, with their real shapes."""
    cfg = _guard(P.read_config, body.model_dir)
    shapes = _guard(P.module_shapes, cfg)
    return {"model_dir": body.model_dir,
            "architecture": (cfg.get("architectures") or ["unknown"])[0],
            "modules": [{"module": k, "in": v[0], "out": v[1]} for k, v in sorted(shapes.items())],
            "note": "shapes differ under grouped-query attention; sizing an adapter as though "
                    "they matched overstates it"}


@app.post("/api/symonlora/validate")
def validate(body: DataIn, _: Authed) -> dict[str, Any]:
    """Everything wrong with a training set, found before the card is taken."""
    rows = _guard(D.load, body.path)
    return {"path": body.path, **_guard(D.validate, rows, minimum=body.minimum,
                                        max_chars=body.max_chars)}


@app.post("/api/symonlora/deduplicate")
def deduplicate(body: DataIn, _: Authed) -> dict[str, Any]:
    """What deduplication WOULD remove. It is offered, never applied to the file."""
    rows = _guard(D.load, body.path)
    out = _guard(D.deduplicate, rows)
    out.pop("kept", None)          # the caller asked what would change, not for a new corpus
    return {"path": body.path, **out}


def main() -> None:
    import uvicorn
    uvicorn.run(app, host=os.environ.get("SYM_LORA_HOST", "127.0.0.1"),
                port=int(os.environ.get("SYM_LORA_PORT", "8820")))


if __name__ == "__main__":
    main()
