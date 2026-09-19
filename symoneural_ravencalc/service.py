"""RavenCalc HTTP surface — Phase 11's gate.

  /api/ravencalc answers from the estate interpreter.

Served by symoneural-uvicorn on symoneural-fastapi, computing through
symoneural-sympy / mpmath / numpy / scipy linked against symoneural-openblas.
Every layer is an estate package built from pinned source.

Route classes follow the DispatchOS classification:

  PUBLIC_BOOTSTRAP        /health, /backends  — must answer while the unit is
                          off or warming, and must expose no user data
  AUTHENTICATED_APPLICATION  every /compute route — requires a unit token
"""

from __future__ import annotations

import os
import time
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel, Field

from . import compute, model

UNIT = "ravencalc"
STARTED = time.time()

app = FastAPI(
    title="SyMoNeuRaL RavenCalc",
    version="1.0.0",
    description="Symbolic and numeric computation from the SyMoNeuRaL estate.",
    docs_url="/api/ravencalc/docs",
    openapi_url="/api/ravencalc/openapi.json",
)


# --------------------------------------------------------------------------
# Auth — SHARED_AUTH
# --------------------------------------------------------------------------

def _expected_token() -> str | None:
    """The unit token, supplied by symoneural-secrets via EnvironmentFile=.

    Never defaulted. An absent token means the unit is unconfigured, and an
    unconfigured unit refuses work rather than serving it openly.
    """
    return os.environ.get("SYM_RAVENCALC_TOKEN")


async def require_unit_token(
    authorization: Annotated[str | None, Header()] = None,
) -> None:
    expected = _expected_token()
    if not expected:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "SYM_RAVENCALC_TOKEN is not set; the unit is unconfigured",
        )
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "bearer token required")

    presented = authorization.removeprefix("Bearer ").strip()
    # Constant-time: a timing side channel on a token check is a real leak.
    import hmac

    if not hmac.compare_digest(presented, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid token")


Authed = Annotated[None, Depends(require_unit_token)]


# --------------------------------------------------------------------------
# Models
# --------------------------------------------------------------------------

class ExpressionIn(BaseModel):
    expression: str = Field(min_length=1, max_length=4096)


class SolveIn(ExpressionIn):
    symbol: str = Field(default="x", min_length=1, max_length=32)


class PreciseIn(ExpressionIn):
    digits: int = Field(default=50, ge=1, le=5000)


class MatrixIn(BaseModel):
    matrix: list[list[float]] = Field(min_length=1, max_length=512)
    rhs: list[float] = Field(min_length=1, max_length=512)


class IntegrateIn(ExpressionIn):
    lower: float
    upper: float


# --------------------------------------------------------------------------
# PUBLIC_BOOTSTRAP
# --------------------------------------------------------------------------

@app.get("/api/ravencalc/health")
def health() -> dict[str, Any]:
    """Answers even when unconfigured. Reports state; exposes no user data."""
    return {
        "unit": UNIT,
        "status": "ready",
        "uptime_s": round(time.time() - STARTED, 1),
        "configured": _expected_token() is not None,
    }


@app.get("/api/ravencalc/backends")
def backends() -> dict[str, Any]:
    """Which estate packages this process actually imported, and from where.

    This is the Phase 11 gate made checkable: it does not assert that the
    estate's numerics are in use, it imports them and reports the file path.
    """
    return {"unit": UNIT, "backends": compute.backends()}


# --------------------------------------------------------------------------
# AUTHENTICATED_APPLICATION
# --------------------------------------------------------------------------

def _run(fn, *args, **kwargs) -> dict[str, Any]:
    try:
        return fn(*args, **kwargs).to_dict()
    except compute.EvaluationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, exc.reason) from exc


@app.post("/api/ravencalc/simplify")
def do_simplify(body: ExpressionIn, _: Authed) -> dict[str, Any]:
    return _run(compute.simplify, body.expression)


@app.post("/api/ravencalc/solve")
def do_solve(body: SolveIn, _: Authed) -> dict[str, Any]:
    return _run(compute.solve, body.expression, body.symbol)


@app.post("/api/ravencalc/precise")
def do_precise(body: PreciseIn, _: Authed) -> dict[str, Any]:
    return _run(compute.precise, body.expression, body.digits)


@app.post("/api/ravencalc/matrix-solve")
def do_matrix_solve(body: MatrixIn, _: Authed) -> dict[str, Any]:
    return _run(compute.matrix_solve, body.matrix, body.rhs)


@app.post("/api/ravencalc/integrate")
def do_integrate(body: IntegrateIn, _: Authed) -> dict[str, Any]:
    return _run(compute.integrate, body.expression, body.lower, body.upper)


# --------------------------------------------------------------------------
# Model arithmetic — AUTHENTICATED_APPLICATION
#
# `model.py` existed with no route for a release. Every serving figure it produced was
# reachable only by importing it, which means the numbers behind a deployment decision could
# not be asked for — only recomputed by whoever remembered the module was there. A capability
# with no endpoint is a capability the estate cannot actually use.
# --------------------------------------------------------------------------

class ModelDirIn(BaseModel):
    model_dir: str = Field(..., description="a checkpoint directory in the weight store")


class KvIn(ModelDirIn):
    context: int = Field(..., ge=1, description="tokens of context to size for")
    sequences: int = Field(1, ge=1, description="concurrent sequences")
    bytes_per_element: int = Field(2, ge=1, le=8, description="2 for fp16/bf16")


class BudgetIn(KvIn):
    vram_bytes: int = Field(..., ge=1, description="the card's total, measured")


class FractionIn(BaseModel):
    total_bytes: int = Field(..., ge=1)
    free_bytes: int = Field(..., ge=0)
    required_bytes: int = Field(..., ge=0)
    reserve_bytes: int = Field(..., ge=0, description="no default: policy about this machine")
    ceiling: float = Field(..., gt=0, le=1.0, description="no default: policy about this machine")


def _config(model_dir: str) -> dict:
    """The checkpoint's own config, or a refusal naming what was missing."""
    import json
    from pathlib import Path
    p = Path(model_dir) / "config.json"
    if not p.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            detail=f"no config.json under {model_dir}")
    try:
        return json.loads(p.read_text())
    except Exception as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail=f"config.json is not readable JSON: {e}")


def _model_run(fn, *a, **kw) -> dict[str, Any]:
    """A refusal from the arithmetic is a 422 carrying its reason, never a 500.

    `model.py` raises rather than estimating when an input is missing. That is a statement
    about the request, not a fault in the service, and it reaches the caller as one."""
    t0 = time.time()
    try:
        out = fn(*a, **kw)
    except model.ModelReadError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))
    return {"result": out, "elapsed_ms": round((time.time() - t0) * 1000, 2)}


@app.post("/api/ravencalc/model/tensors")
def do_tensors(body: ModelDirIn, _: Authed) -> dict[str, Any]:
    """Every tensor's exact on-disk size, read from the safetensors header."""
    def go():
        ts = model.read_tensors(body.model_dir)
        return {"count": len(ts), "total_bytes": sum(t.bytes for t in ts),
                "tensors": [{"name": t.name, "dtype": t.dtype, "shape": t.shape,
                             "bytes": t.bytes} for t in ts]}
    return _model_run(go)


@app.post("/api/ravencalc/model/kv-cache")
def do_kv_cache(body: KvIn, _: Authed) -> dict[str, Any]:
    """Key/value cache bytes, accounting for grouped-query attention and sliding layers."""
    cfg = _config(body.model_dir)
    return _model_run(model.kv_cache, cfg, body.context, body.sequences, body.bytes_per_element)


@app.post("/api/ravencalc/model/experts")
def do_experts(body: ModelDirIn, _: Authed) -> dict[str, Any]:
    """What the mixture weights cost, and what one token actually touches."""
    cfg = _config(body.model_dir)
    return _model_run(model.expert_residency, body.model_dir, cfg)


@app.post("/api/ravencalc/model/budget")
def do_budget(body: BudgetIn, _: Authed) -> dict[str, Any]:
    """Does it fit: weights plus cache against a real card, with the shortfall named."""
    cfg = _config(body.model_dir)
    return _model_run(model.budget, cfg, body.model_dir, body.vram_bytes,
                      body.context, body.sequences, body.bytes_per_element)


@app.post("/api/ravencalc/model/gpu-fraction")
def do_gpu_fraction(body: FractionIn, _: Authed) -> dict[str, Any]:
    """The share of the card an engine may take, derived rather than chosen.

    `reserve_bytes` and `ceiling` are required with no defaults, here as in the module: they
    are policy about a machine, and a default would hand back a confident number nobody chose.
    """
    return _model_run(model.gpu_fraction, body.total_bytes, body.free_bytes,
                      body.required_bytes,
                      reserve_bytes=body.reserve_bytes, ceiling=body.ceiling)


class TransferIn(BaseModel):
    nbytes: int = Field(..., ge=0, description="bytes to move")
    bandwidth_bytes_per_s: float = Field(..., gt=0,
        description="MEASURED bandwidth; there is deliberately no default")


@app.post("/api/ravencalc/model/transfer")
def do_transfer(body: TransferIn, _: Authed) -> dict[str, Any]:
    """Milliseconds to move bytes at a measured bandwidth.

    The bandwidth is required. A plausible constant here manufactures a token-rate figure with
    nothing behind it, which is exactly how an unfounded number once reached a report.
    """
    return _model_run(model.transfer_ms, body.nbytes, body.bandwidth_bytes_per_s)


def main() -> None:
    """Entry point. Binds 127.0.0.1:8801 — the tunnel is the only way out."""
    import uvicorn

    uvicorn.run(
        app,
        host=os.environ.get("SYM_RAVENCALC_HOST", "127.0.0.1"),
        port=int(os.environ.get("SYM_RAVENCALC_PORT", "8801")),
        log_level=os.environ.get("SYM_LOG_LEVEL", "info"),
    )


if __name__ == "__main__":
    main()
