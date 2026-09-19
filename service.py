#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
# SyMoNsAyLeaRn — SyMoNeuRaL, a subdivision of SymonSaysLLC. Terms: see LICENSE.
"""symonrag over HTTP — retrieval that can show its work.

Seven routes under /api/symonrag/. The index lives on disk and is loaded on demand, so this
process can be restarted without losing it and two processes cannot disagree about it.

WHAT THIS IS FOR, SAID PLAINLY
------------------------------
RAG supplies what the model should KNOW. A LoRA changes how it BEHAVES. Knowledge that changes
after training ends cannot be trained in, and this estate changes every day — which is why the
first corpus this indexes is the estate's own documents.
"""
from __future__ import annotations

import hmac
import ipaddress
import os
import time
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, status
from pydantic import BaseModel

from symonrag.chunk import ChunkError
from symonrag.index import Index, IndexError_

UNIT = "symonrag"
STARTED = time.time()
# Derived data, not weights, so it does not belong in the model store — and /models is
# root-owned here, which the symon-imager placement already ran into. It lives beside the
# other runtime state and can be moved with one variable.
INDEX_PATH = os.environ.get("SYM_RAG_INDEX",
                            os.path.expanduser("~/symoneural-run/rag/estate.index.json"))

# Where indexing is allowed to read. No default of "/" — an indexer that can read anything is a
# way to copy anything into a place the model will be shown.
ALLOWED_ROOTS = [r for r in (os.environ.get("SYM_RAG_ROOTS") or
                             "/mnt/SymonSayDistribute:/mnt/SymonSayOpen:/mnt/SymonSayOSS"
                             ).split(":") if r]

app = FastAPI(
    title="SyMoNeuRaL symonrag",
    version="1.0.0",
    description="Retrieval with citations and an explainable score.",
    docs_url="/api/symonrag/docs",
    openapi_url="/api/symonrag/openapi.json",
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
    host = (os.environ.get("SYM_RAG_HOST") or "127.0.0.1").strip()
    if host.lower() in ("localhost", ""):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False          # a name we cannot prove is loopback is treated as reachable

def require_token(authorization: Annotated[str | None, Header()] = None) -> None:
    if _open_on_loopback():
        return
    expected = (os.environ.get("SYM_RAG_TOKEN") or "").strip()
    if not expected:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="symonrag is unconfigured: SYM_RAG_TOKEN is not set")
    got = (authorization or "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(got, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="bad token")


Authed = Annotated[None, Depends(require_token)]

_LOADED: dict[str, Any] = {"index": None, "path": None}


def _guard(fn, *a, **kw) -> Any:
    try:
        return fn(*a, **kw)
    except (IndexError_, ChunkError) as e:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(e))


def _index() -> Index:
    if _LOADED["index"] is None or _LOADED["path"] != INDEX_PATH:
        _LOADED["index"] = _guard(Index.load, INDEX_PATH)
        _LOADED["path"] = INDEX_PATH
    return _LOADED["index"]


def _inside_allowed(p: Path) -> bool:
    rp = p.resolve()
    return any(str(rp).startswith(str(Path(r).resolve())) for r in ALLOWED_ROOTS)


class BuildIn(BaseModel):
    paths: list[str]
    glob: str = "*.md"
    target: int = 1200
    overlap: int = 150


class SearchIn(BaseModel):
    query: str
    k: int = 5


class ExplainIn(BaseModel):
    query: str
    passage_id: str


@app.get("/api/symonrag/health")
def health() -> dict[str, Any]:
    """Public; answers before the unit is configured and before an index exists."""
    return {"unit": UNIT, "status": "ok", "uptime_s": round(time.time() - STARTED, 1),
            "configured": bool((os.environ.get("SYM_RAG_TOKEN") or "").strip()),
            "index_present": Path(INDEX_PATH).is_file()}


@app.get("/api/symonrag/status")
def status_(_: Authed) -> dict[str, Any]:
    """What is indexed, and where indexing is permitted to read."""
    present = Path(INDEX_PATH).is_file()
    out: dict[str, Any] = {"index": INDEX_PATH, "present": present,
                           "allowed_roots": ALLOWED_ROOTS}
    if present:
        ix = _index()
        out.update({"passages": ix.n, "terms": len(ix.df),
                    "average_words": round(ix.avgdl, 1), "built_at": ix.built_at,
                    "sources": len({p.source for p in ix.passages.values()})})
    return out


@app.post("/api/symonrag/index")
def build(body: BuildIn, _: Authed) -> dict[str, Any]:
    """Build the index from files under the permitted roots. Refuses anything outside them."""
    ix = Index()
    files: list[Path] = []
    for raw in body.paths:
        p = Path(raw)
        if not _inside_allowed(p):
            raise HTTPException(status.HTTP_403_FORBIDDEN, detail={
                "refused": f"{p} is outside the permitted roots",
                "allowed_roots": ALLOWED_ROOTS,
                "why": "an indexer that can read anything is a way to put anything in front "
                       "of the model"})
        files.extend(sorted(p.rglob(body.glob)) if p.is_dir() else [p])
    if not files:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            detail="no files matched; an empty index is not built silently")
    skipped = []
    for f in files:
        try:
            ix.add_file(str(f), target=body.target, overlap=body.overlap)
        except ChunkError as e:
            skipped.append({"file": str(f), "why": str(e)})
    if ix.n == 0:
        raise HTTPException(status.HTTP_409_CONFLICT, detail={
            "refused": "every file was skipped, so the index would be empty", "skipped": skipped})
    saved = ix.save(INDEX_PATH)
    _LOADED["index"], _LOADED["path"] = ix, INDEX_PATH
    return {"indexed": ix.n, "files": len(files), "terms": len(ix.df),
            "skipped": skipped, **saved}


@app.post("/api/symonrag/search")
def search(body: SearchIn, _: Authed) -> dict[str, Any]:
    """Top passages, each with a citation that can be opened."""
    rows = _guard(_index().search, body.query, body.k)
    return {"query": body.query, "count": len(rows), "results": rows,
            "every_result_is_citable": all(r["cite"] for r in rows)}


@app.post("/api/symonrag/explain")
def explain(body: ExplainIn, _: Authed) -> dict[str, Any]:
    """Why a passage scored what it did, term by term."""
    return _guard(_index().explain, body.query, body.passage_id)


@app.post("/api/symonrag/context")
def context(body: SearchIn, _: Authed) -> dict[str, Any]:
    """Retrieved passages formatted for a prompt, with the citations attached.

    Separate from `search` because what goes in front of a model and what a person reads are
    different shapes, and building the prompt block here means every caller cites the same way
    rather than each inventing a format.
    """
    rows = _guard(_index().search, body.query, body.k)
    blocks = [f"[{i + 1}] {r['cite']}\n{r['text']}" for i, r in enumerate(rows)]
    return {"query": body.query, "passages": len(rows),
            "context": "\n\n".join(blocks),
            "citations": [{"n": i + 1, "cite": r["cite"], "score": r["score"]}
                          for i, r in enumerate(rows)],
            "note": "every passage carries its source and line range; an answer built from "
                    "this can be checked against the file"}


def main() -> None:
    import uvicorn
    uvicorn.run(app, host=os.environ.get("SYM_RAG_HOST", "127.0.0.1"),
                port=int(os.environ.get("SYM_RAG_PORT", "8819")))


if __name__ == "__main__":
    main()
