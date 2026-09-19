#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
# SyMoNsAyLeaRn — SyMoNeuRaL, a subdivision of SymonSaysLLC. Terms: see LICENSE.
"""symonpayload over HTTP — admission and formation, in our namespace.

Thirteen routes under /api/symonpayload/. Not /v1/: that namespace is the Messages dialect the
gateway serves to third-party clients and its paths are fixed by them. Nothing outside this
host speaks to symonpayload, so it uses the convention every other unit here already uses.

NO ROUTE IS SERVED FOR A COMPONENT THAT IS NOT BUILT. Sixteen routes in the reference document
have no code behind them and therefore have no route — not a stub, not a 501, not a 200 with an
invented id. A surface that answers is a surface callers wire themselves to.
"""
from __future__ import annotations

import hmac
import ipaddress
import os
import time
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel, Field

from symonpayload.admit import (
    Coalescer, Gatekeeper, Ingress, Prioritizer, Queue, Refused, Request, TriageGate)
from symonpayload.form import (
    Bundler, CannotForm, Concatenator, DynamicBatcher, Packer, Padder, Reservoir, Stacker)

UNIT = "symonpayload"
STARTED = time.time()

app = FastAPI(
    title="SyMoNeuRaL symonpayload",
    version="1.1.0",
    description="Admission and batch formation for the inference path.",
    docs_url="/api/symonpayload/docs",
    openapi_url="/api/symonpayload/openapi.json",
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
    host = (os.environ.get("SYM_PAYLOAD_HOST") or "127.0.0.1").strip()
    if host.lower() in ("localhost", ""):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False          # a name we cannot prove is loopback is treated as reachable

def require_token(authorization: Annotated[str | None, Header()] = None) -> None:
    if _open_on_loopback():
        return
    expected = (os.environ.get("SYM_PAYLOAD_TOKEN") or "").strip()
    if not expected:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="symonpayload is unconfigured: SYM_PAYLOAD_TOKEN is not set")
    got = (authorization or "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(got, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="bad token")


Authed = Annotated[None, Depends(require_token)]


def _policy(name: str) -> int:
    """A policy number, from the environment, with no default.

    A default here is a number nobody chose silently deciding what the estate accepts. The
    unit answers 503 naming the variable instead, which is a thing an operator can fix.
    """
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail=f"{name} is not set; this unit does not default its policy")
    try:
        v = int(raw)
    except ValueError:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail=f"{name}={raw!r} is not an integer")
    if v <= 0:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail=f"{name}={v} must be positive")
    return v


# One admission point for the process, so "why was this refused" has a single answer.
_GATE: dict[str, Any] = {"keeper": None}


def _keeper() -> Gatekeeper:
    if _GATE["keeper"] is None:
        _GATE["keeper"] = Gatekeeper(
            gate=TriageGate(max_tokens=_policy("SYM_PAYLOAD_MAX_TOKENS")),
            ingress=Ingress(capacity=_policy("SYM_PAYLOAD_CAPACITY")),
            queue=Queue(Prioritizer()), coalescer=Coalescer())
    return _GATE["keeper"]


# --------------------------------------------------------------------------- shapes in
class SubmitIn(BaseModel):
    request_id: str
    tokens: int = Field(..., description="counted by the caller; the gateway serves count_tokens")
    tenant: str = "default"
    deadline_ms: int | None = None
    fingerprint: str = ""
    at_ms: int = 0


class BatchIn(BaseModel):
    requests: list[SubmitIn]


class FormIn(BaseModel):
    max_tokens: int
    max_requests: int
    window_ms: int
    now_ms: int = 0
    opened_at_ms: int | None = None


class ShapesIn(BaseModel):
    shapes: list[list[int]]


class LengthsIn(BaseModel):
    lengths: list[int]
    width: int | None = None


class ReservoirIn(BaseModel):
    per_window: int
    draw: int | None = None
    refill: bool = False


def _req(s: SubmitIn) -> Request:
    return Request(id=s.request_id, tokens=s.tokens, tenant=s.tenant,
                   deadline_ms=s.deadline_ms, fingerprint=s.fingerprint, at_ms=s.at_ms)


def _refused(r: Refused) -> HTTPException:
    # 429 and not 400: the request was well formed and the unit declined it. A caller that
    # reads 400 fixes its payload; a caller that reads 429 waits, which is the right response.
    return HTTPException(status.HTTP_429_TOO_MANY_REQUESTS,
                         detail={"refused": r.reason, "request_id": r.request_id})


# --------------------------------------------------------------------------- routes
@app.get("/api/symonpayload/health")
def health() -> dict[str, Any]:
    """Public; answers before the unit is configured, so liveness and readiness differ."""
    return {"unit": UNIT, "status": "ok", "uptime_s": round(time.time() - STARTED, 1),
            "configured": bool((os.environ.get("SYM_PAYLOAD_TOKEN") or "").strip())}


@app.post("/api/symonpayload/requests/submit")
def submit(body: SubmitIn, _: Authed) -> dict[str, Any]:
    """Admit one request. Amended from the reference: `tokens` is required and counted."""
    k = _keeper()
    try:
        leader = k.admit(_req(body))
    except Refused as r:
        raise _refused(r)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(e))
    return {"request_id": body.request_id, "queued": leader is None,
            "coalesced_into": leader, "queue_depth": len(k.queue)}


@app.post("/api/symonpayload/requests/batch")
def submit_many(body: BatchIn, _: Authed) -> dict[str, Any]:
    """Admit many. Partial success is reported, never rolled back silently."""
    k = _keeper()
    admitted, refused = [], []
    for s in body.requests:
        try:
            leader = k.admit(_req(s))
            admitted.append({"request_id": s.request_id, "coalesced_into": leader})
        except Refused as r:
            refused.append({"request_id": s.request_id, "why": r.reason})
        except ValueError as e:
            refused.append({"request_id": s.request_id, "why": str(e)})
    return {"admitted": admitted, "refused": refused,
            "counts": {"admitted": len(admitted), "refused": len(refused)},
            "queue_depth": len(k.queue)}


@app.post("/api/symonpayload/requests/triage")
def triage(body: SubmitIn, _: Authed) -> dict[str, Any]:
    """Which lane, and why. No estimated_wait_ms — that needs a measured service rate."""
    try:
        lane = _keeper().gate.route(_req(body))
    except Refused as r:
        raise _refused(r)
    return {"request_id": body.request_id, "lane": lane,
            "why": "carries a deadline" if body.deadline_ms is not None else "no deadline claimed",
            "estimated_wait_ms": None,
            "estimated_wait_omitted_because":
                "a wait is queue depth over a measured service rate, and this host has none"}


@app.post("/api/symonpayload/payloads/coalesce")
def coalesce(body: BatchIn, _: Authed) -> dict[str, Any]:
    """Group by the caller's declared fingerprint. Identity is never inferred here."""
    c = Coalescer()
    leaders: dict[str, list[str]] = {}
    standalone: list[str] = []
    for s in body.requests:
        lead = c.admit(_req(s))
        if lead is None:
            if s.fingerprint:
                leaders[s.request_id] = []
            else:
                standalone.append(s.request_id)
        else:
            leaders.setdefault(lead, []).append(s.request_id)
    return {"leaders": [{"request_id": k, "followers": v} for k, v in leaders.items()],
            "never_coalesced": standalone,
            "saved_calls": sum(len(v) for v in leaders.values())}


@app.get("/api/symonpayload/queue/status")
def queue_status(_: Authed) -> dict[str, Any]:
    """As declared in the reference."""
    k = _keeper()
    pending = k.queue.peek()
    return {"queues": [{"queue_name": "admitted", "pending_items": len(pending),
                        "tokens_pending": sum(r.tokens for r in pending),
                        "capacity": k.ingress.capacity}],
            "refused_since_start": len(k.refusals)}


@app.post("/api/symonpayload/queue/prioritize")
def prioritize(_: Authed) -> dict[str, Any]:
    """Amended: ordering is by deadline, not by a level a caller can set for itself."""
    pending = _keeper().queue.peek()
    return {"order": [{"request_id": r.id, "deadline_ms": r.deadline_ms} for r in pending],
            "policy": "deadline first, then arrival; stable so nothing starves",
            "why_no_priority_level":
                "a level set per call lets one caller jump every queue by asking; a deadline "
                "is a claim that can be checked against the clock"}


@app.post("/api/symonpayload/batches/form")
def form_batch(body: FormIn, _: Authed) -> dict[str, Any]:
    """Not in the reference, and the most useful route here: it reports which bound tripped."""
    k = _keeper()
    pending = k.queue.peek()
    b = DynamicBatcher(max_tokens=body.max_tokens, max_requests=body.max_requests,
                       window_ms=body.window_ms, clock=lambda: body.now_ms)
    try:
        batch = b.form(pending, opened_at_ms=body.opened_at_ms)
    except CannotForm as e:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(e))
    k.queue.take(len(batch))
    return {"request_ids": batch.ids, "count": len(batch), "tokens": batch.tokens,
            "bound": batch.bound,
            "bound_means": {"tokens": "raise the ceiling or lower the served context",
                            "count": "raise the request limit",
                            "window": "shorten the window or add capacity",
                            "drained": "nothing — the unit is under-loaded, not saturated"}[batch.bound],
            "queue_depth": len(k.queue)}


@app.post("/api/symonpayload/shapes/stack")
def shapes_stack(body: ShapesIn, _: Authed) -> dict[str, Any]:
    """Amended: shapes in, shape out. This unit stores no tensors, so it mints no tensor ids."""
    try:
        out = Stacker().stack([tuple(s) for s in body.shapes])
    except CannotForm as e:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(e))
    return {"resulting_shape": list(out), "members": len(body.shapes)}


@app.post("/api/symonpayload/shapes/concatenate")
def shapes_concat(body: LengthsIn, _: Authed) -> dict[str, Any]:
    """Amended: lengths in, boundaries out, so the result can be split again correctly."""
    try:
        out = Concatenator().join(body.lengths)
    except (CannotForm, ValueError) as e:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(e))
    return out


@app.post("/api/symonpayload/shapes/pack")
def shapes_pack(body: LengthsIn, _: Authed) -> dict[str, Any]:
    """Not in the reference: the alternative to padding, with its cost, so a caller can choose."""
    if body.width is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="pack needs a width")
    try:
        return Packer().pack(body.lengths, body.width)
    except (CannotForm, ValueError) as e:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(e))


@app.post("/api/symonpayload/tokens/plan")
def tokens_plan(body: LengthsIn, _: Authed) -> dict[str, Any]:
    """Amended: the padding plan and what it wastes, rather than a tensor id for a tensor."""
    try:
        return Padder().pad(body.lengths, pad_to=body.width)
    except (CannotForm, ValueError) as e:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(e))


@app.post("/api/symonpayload/tokens/reservoir")
def tokens_reservoir(body: ReservoirIn, _: Authed) -> dict[str, Any]:
    """As declared: fill level and what is left."""
    try:
        res = Reservoir(per_window=body.per_window)
        if body.draw is not None:
            res.draw(body.draw)
        if body.refill:
            res.refill()
    except (CannotForm, ValueError) as e:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(e))
    # These are different quantities and returning `available` for both would have made the
    # route read correct while saying the same number twice.
    return {"current_fill_level": res.per_window - res.available,
            "capacity_remaining": res.available,
            "per_window": res.per_window, "windows": res.windows}


def main() -> None:
    import uvicorn
    uvicorn.run(app, host=os.environ.get("SYM_PAYLOAD_HOST", "127.0.0.1"),
                port=int(os.environ.get("SYM_PAYLOAD_PORT", "8814")))


if __name__ == "__main__":
    main()
