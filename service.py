#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
"""The control board over HTTP — every setting, switch and status, as endpoints.

The board is a file and stays a file: it is the thing an operator reads and edits, and a
control you cannot open in an editor is not the control this estate asked for. This serves the
same board, so a surface can render it and a tool can ask it questions without shelling out.

WHAT IT WILL NOT SERVE
----------------------
A credential value, ever. `/client` reports the FINGERPRINT of the key each surface is wired
to, and whether the helper emits that same key. Section 3.2 permits fingerprints and file
locations; this holds that line at the network edge as well as in the file.

WHAT IS MEASURED AND WHAT IS CONFIGURED
---------------------------------------
Every response separates the two. `configured` comes off the board; `live` is read from the
machine at the moment of the request. A surface that shows one while implying the other is how
a stale number gets believed, which is the failure the board exists to prevent.
"""
from __future__ import annotations

import ipaddress
import os
import time
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, status

import board as B

UNIT = "board"
STARTED = time.time()
BOARD_PATH = os.environ.get("SYM_BOARD", "/mnt/models/control.board")

app = FastAPI(
    title="SyMoNeuRaL control board",
    version="1.2.0",
    description="Every setting, switch and status in the estate, as endpoints.",
    docs_url="/api/board/docs",
    openapi_url="/api/board/openapi.json",
)


def _expected_token() -> str | None:
    v = os.environ.get("SYM_BOARD_TOKEN")
    return v.strip() or None if v else None


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
    host = (os.environ.get("SYM_BOARD_HOST") or "127.0.0.1").strip()
    if host.lower() in ("localhost", ""):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False          # a name we cannot prove is loopback is treated as reachable

def require_token(authorization: Annotated[str | None, Header()] = None) -> None:
    """Same posture as the gateway: unconfigured fails closed, never open.

    A control surface that answers freely because nobody provisioned a token is a control
    surface anyone can read. /health is the only route that answers unconfigured, because a
    readiness probe that needs a credential cannot report that the credential is missing.
    """
    if _open_on_loopback():
        return
    expected = _expected_token()
    if expected is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="board is unconfigured: SYM_BOARD_TOKEN is not set")
    presented = ""
    if authorization and authorization.lower().startswith("bearer "):
        presented = authorization[7:].strip()
    import hmac
    if not presented or not hmac.compare_digest(presented.encode(), expected.encode()):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="invalid or missing credential")


Authed = Annotated[None, Depends(require_token)]


def _load() -> B.Board:
    try:
        return B.Board.load(BOARD_PATH)
    except SystemExit as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(e))


# --------------------------------------------------------------------------- public
@app.get("/api/board/health")
def health() -> dict[str, Any]:
    """Public. Answers while the board is unconfigured and every unit is off."""
    return {"status": "ok", "unit": UNIT, "uptime_s": round(time.time() - STARTED, 1),
            "board": BOARD_PATH, "board_present": os.path.isfile(BOARD_PATH)}


# --------------------------------------------------------------------------- settings
@app.get("/api/board/sections")
def sections(_: Authed) -> dict[str, Any]:
    """Every section, its size, and which tree owns it — so a licence question has an answer."""
    b = _load()
    counts: dict[str, int] = {}
    for _i, s, _k, _v, _n in b.walk():
        counts[s] = counts.get(s, 0) + 1
    trees = b.trees()
    return {"count": len(b.sections()),
            "sections": [{"name": s, "settings": counts.get(s, 0), "tree": trees.get(s, "")}
                         for s in b.sections()]}


@app.get("/api/board/settings")
def settings(_: Authed, section: str | None = None) -> dict[str, Any]:
    """Every configured value with where it came from, and whether it was ever measured."""
    b = _load()
    rows = [{"section": s, "key": k, "name": f"{s}.{k}", "value": v,
             "why": note, "stale": "STALE" in note.upper(), "tree": b.trees().get(s, "")}
            for _i, s, k, v, note in b.walk() if s != B.LIVE]
    if section:
        rows = [r for r in rows if r["section"] == section]
    return {"count": len(rows), "stale": [r["name"] for r in rows if r["stale"]],
            "settings": rows}


# --------------------------------------------------------------------------- live
@app.get("/api/board/live")
def live(_: Authed) -> dict[str, Any]:
    """What is actually running, measured now, with DIFFERS on anything that has drifted."""
    b = _load()
    rows = B.live(b)
    b.replace_section(B.LIVE, rows)
    B.Path(BOARD_PATH).write_text(b.text())
    out = []
    for line in rows:
        m = B._ENTRY.match(line)
        if m:
            note = (m.group(6) or "").strip()
            out.append({"key": m.group(2), "value": m.group(4).strip(), "note": note,
                        "differs": "DIFFERS" in note})
    return {"at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "count": len(out),
            "differs": [r["key"] for r in out if r["differs"]], "live": out}


@app.get("/api/board/diff")
def diff(_: Authed) -> dict[str, Any]:
    """Only where configured and live disagree. Empty means the machine matches the board."""
    d = live(None)  # type: ignore[arg-type]
    rows = [r for r in d["live"] if r["differs"]]
    return {"count": len(rows), "agrees": not rows, "differences": rows,
            "note": "nothing changes until the unit is restarted"}


@app.get("/api/board/check")
def check(_: Authed) -> dict[str, Any]:
    """Every path exists, every port is a port, nothing is stale."""
    b = _load()
    problems = []
    for _i, s, k, v, note in b.walk():
        if s == B.LIVE:
            continue
        if "STALE" in note.upper():
            problems.append({"kind": "stale", "name": f"{s}.{k}", "why": note})
        elif v.startswith("/") and "credential" not in k and not B.Path(v).exists():
            problems.append({"kind": "missing", "name": f"{s}.{k}", "why": f"{v} does not exist"})
        elif (k in ("chat", "gateway") or k.endswith("_port")) and not (
                v.isdigit() and 1 <= int(v) <= 65535):
            problems.append({"kind": "not-a-port", "name": f"{s}.{k}", "why": v})
    return {"ok": not problems, "count": len(problems), "problems": problems}


@app.get("/api/board/pinned")
def pinned(_: Authed) -> dict[str, Any]:
    """§3.1b-iii: every external program the board runs, against its recorded pin.

    Measured on every request by running each program, not read from a note. A row with
    `pin: null` is a program the estate has no version record for — reported rather than
    omitted, because an omitted program reads as one with nothing to check.
    """
    return B.pinned()


# --------------------------------------------------------------------------- switches
@app.get("/api/board/client")
def client(_: Authed) -> dict[str, Any]:
    """Which surface receives the credential, and whether it is actually wired.

    Reports the key's FINGERPRINT and whether the helper emits that same key. No value is
    returned by this route under any input, which is the whole point of it existing.
    """
    b = _load()
    rows = B.client_surfaces(b)
    return {"surfaces": B.SURFACES,
            "checks": [{"name": k, "state": v, "note": n} for k, v, n in rows],
            "wired": not any(v.isupper() and v not in ("ok",) for _k, v, _n in rows)}


@app.post("/api/board/client/{surface}")
def set_client(surface: str, _: Authed) -> dict[str, Any]:
    """Select which surface gets the credential: 3p, webui, both or off."""
    if surface not in B.SURFACES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail=f"{surface!r} is not one of {', '.join(B.SURFACES)}")
    b = _load()
    changed = False
    for i, s, k, _v, note in list(b.walk()):
        if s == "client" and k == "surface":
            e = B._ENTRY.match(b.lines[i])
            pad = " " * max(1, 28 - len(f"{k} = {surface}"))
            b.lines[i] = f"{e.group(1)}{k}{e.group(3)}{surface}{pad}# {note}"
            changed = True
    if not changed:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="no [client] surface line on the board")
    B.Path(BOARD_PATH).write_text(b.text())
    return client(None)  # type: ignore[arg-type]


def main() -> None:
    import uvicorn
    uvicorn.run(app, host=os.environ.get("SYM_BOARD_HOST", "127.0.0.1"),
                port=int(os.environ.get("SYM_BOARD_PORT", "8811")),
                log_level=os.environ.get("SYM_LOG_LEVEL", "info"))


if __name__ == "__main__":
    main()
