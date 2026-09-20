#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
# SyMoNsAyLeaRn — SyMoNeuRaL, a subdivision of SymonSaysLLC. Terms: see LICENSE.
"""symondevice over HTTP — the physical inventory, reachable.

Ten routes under /api/symondevice/. Nine of them are one capability each, named after the
function they call so that a reader — and the endpoints gate — can see the correspondence
without tracing an alias.

THE ROUTE THAT MATTERS IS `owned_by`
The other nine describe hardware. That one describes the ESTATE: which component covers each
class of hardware, and which classes are covered by nothing. It is the only route here whose
answer changes when a component is written rather than when a cable is moved.

EVERY ROUTE IS A GET AND EVERY ROUTE IS READ-ONLY
Nothing under here flashes, partitions, resets, rebinds, reconfigures or writes to any device.
The unit cannot be made to change the machine by any request it accepts, because there is no
code path in it that writes.
"""
from __future__ import annotations

import hmac
import ipaddress
import os
import time
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException, status

from symondevice import inventory as R

UNIT = "symondevice"
STARTED = time.time()

app = FastAPI(
    title="SyMoNeuRaL symondevice",
    version="1.0.0",
    description="What hardware exists, which driver owns it, and which component covers it.",
    docs_url="/api/symondevice/docs",
    openapi_url="/api/symondevice/openapi.json",
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
    host = (os.environ.get("SYM_DEVICE_HOST") or "127.0.0.1").strip()
    if host.lower() in ("localhost", ""):
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False          # a name we cannot prove is loopback is treated as reachable


def require_token(authorization: Annotated[str | None, Header()] = None) -> None:
    if _open_on_loopback():
        return
    expected = (os.environ.get("SYM_DEVICE_TOKEN") or "").strip()
    if not expected:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE,
                            detail="symondevice is unconfigured: SYM_DEVICE_TOKEN is not set")
    got = (authorization or "").removeprefix("Bearer ").strip()
    if not hmac.compare_digest(got, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="bad token")


Authed = Annotated[None, Depends(require_token)]


def _guard(fn, *a, **kw) -> Any:
    try:
        return fn(*a, **kw)
    except R.InventoryError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(e))


@app.get("/api/symondevice/health")
def health() -> dict[str, Any]:
    """Public; answers before the unit is configured and on a host with no hardware to report."""
    return {"unit": UNIT, "status": "ok", "uptime_s": round(time.time() - STARTED, 1),
            "loopback": _open_on_loopback(),
            "configured": bool((os.environ.get("SYM_DEVICE_TOKEN") or "").strip())}


@app.get("/api/symondevice/cpu")
def cpu(_: Authed) -> dict[str, Any]:
    """Counts, topology, frequency range and the flags that decide what can run here."""
    return _guard(R.cpu)


@app.get("/api/symondevice/memory")
def memory(_: Authed) -> dict[str, Any]:
    """Total, available, and how much of the rest is reclaimable cache rather than free."""
    return _guard(R.memory)


@app.get("/api/symondevice/storage")
def storage(_: Authed) -> dict[str, Any]:
    """Every block device, including the removable and zero-size ones. Nothing is filtered."""
    return _guard(R.storage)


@app.get("/api/symondevice/pci")
def pci(_: Authed) -> dict[str, Any]:
    """Every PCI function and the driver bound to it, or explicitly none."""
    return _guard(R.pci)


@app.get("/api/symondevice/usb")
def usb(_: Authed) -> dict[str, Any]:
    """The USB tree with each device's position, because a hub failure surfaces downstream."""
    return _guard(R.usb)


@app.get("/api/symondevice/network")
def network(_: Authed) -> dict[str, Any]:
    """Interfaces, state, driver and speed. The address is never returned."""
    return _guard(R.network)


@app.get("/api/symondevice/sensors")
def sensors(_: Authed) -> dict[str, Any]:
    """Temperatures, fans and voltages with the kernel's own labels. Nothing is written."""
    return _guard(R.sensors)


@app.get("/api/symondevice/power")
def power(_: Authed) -> dict[str, Any]:
    """Power supplies and their state, separated by whether they power the machine."""
    return _guard(R.power)


@app.get("/api/symondevice/owned_by")
def owned_by(_: Authed) -> dict[str, Any]:
    """Which component covers each hardware class, and which classes are covered by none."""
    return _guard(R.owned_by)


def main() -> None:
    import uvicorn
    uvicorn.run(app, host=os.environ.get("SYM_DEVICE_HOST", "127.0.0.1"),
                port=int(os.environ.get("SYM_DEVICE_PORT", "8832")))


if __name__ == "__main__":
    main()
