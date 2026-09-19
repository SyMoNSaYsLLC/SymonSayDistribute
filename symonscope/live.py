# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
# SyMoNsAyLeaRn — SyMoNeuRaL, a subdivision of SymonSaysLLC. Terms: see LICENSE.
"""What is actually running, and whether the estate on disk matches it.

The survey reads what the estate SAYS it is. This reads what it IS. The gap between the two is
the only thing here worth reporting: a unit declaring a port nothing listens on, and a port
listening that no unit claims, are both findings and they are different findings.

Read-only in the strongest sense: it opens sockets to ask health and nothing else. It never
starts, stops or configures anything, and it never sends a credential — health is the one
route every unit in this estate answers unauthenticated, which is exactly what makes it usable
here.
"""
from __future__ import annotations

import json
import re
import subprocess
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .survey import units

# Why these three carry no route of their own. The gate asks, and the answer is not "later":
# they are the three halves of one question — what is running, what the board says, and whether
# those agree — and the only useful answer is the comparison. Routing the halves separately
# would invite a caller to fetch two of them and do the comparison itself, which is how two
# callers end up with two different ideas of whether the estate agrees with itself.
NOT_EXPOSED = {
    "listening":   "the raw socket list; returned inside GET /api/symonscope/live, which is "
                   "the same data already compared against what each unit declares",
    "board_ports": "what /models/control.board assigns; returned inside GET "
                   "/api/symonscope/live, where it is checked rather than merely reported",
    "state":       "routed as GET /api/symonscope/live",
}

BOARD = "/mnt/models/control.board"
_ENTRY = re.compile(r"^\s*([a-z_]+)\s*=\s*(\d{2,5})", re.M)


def listening() -> list[dict[str, Any]]:
    """Every loopback port with something on it, from ss, with the process behind it."""
    r = subprocess.run(["ss", "-ltnpH"], capture_output=True, text=True, timeout=15)
    if r.returncode != 0:
        return [{"error": f"ss failed rc={r.returncode}"}]
    out = []
    for line in r.stdout.splitlines():
        m = re.search(r"127\.0\.0\.1:(\d+)", line)
        if not m:
            continue
        pid = re.search(r"pid=(\d+)", line)
        row: dict[str, Any] = {"port": int(m.group(1)), "pid": int(pid.group(1)) if pid else None}
        if row["pid"]:
            try:
                row["cwd"] = str(Path(f"/proc/{row['pid']}/cwd").resolve())
            except Exception:
                row["cwd"] = None
        out.append(row)
    return sorted(out, key=lambda r: r["port"])


def board_ports() -> dict[str, int]:
    """What /models/control.board says the ports are. Absent is reported, not assumed."""
    p = Path(BOARD)
    if not p.is_file():
        return {}
    text = p.read_text(errors="replace")
    start = text.find("[ports]")
    if start < 0:
        return {}
    block = text[start:]
    end = block.find("\n[", 1)
    return {k: int(v) for k, v in _ENTRY.findall(block[:end if end > 0 else len(block)])}


def _health(port: int, prefix: str | None) -> dict[str, Any]:
    path = f"{prefix}/health" if prefix else "/health"
    url = f"http://127.0.0.1:{port}{path}"
    try:
        with urllib.request.urlopen(url, timeout=4) as r:
            body = json.loads(r.read() or b"null")
            return {"url": url, "up": r.status == 200, "status": r.status,
                    "configured": body.get("configured") if isinstance(body, dict) else None}
    except urllib.error.HTTPError as e:
        return {"url": url, "up": False, "status": e.code}
    except Exception as e:
        return {"url": url, "up": False, "status": type(e).__name__}


def state(tree: str = "SymonSayDistribute") -> dict[str, Any]:
    """Declared against actual, with every disagreement named."""
    rows = units(tree)
    live = {r["port"]: r for r in listening()}
    board = board_ports()
    declared, findings = [], []

    for u in rows:
        port = u.get("port")
        if not port:
            continue
        row = {"unit": u["unit"], "port": port, "route_prefix": u["route_prefix"],
               "listening": port in live}
        if port in live:
            row.update(_health(port, u["route_prefix"]))
            row["cwd"] = live[port].get("cwd")
            if row.get("cwd") and u["path"] not in row["cwd"]:
                findings.append({"kind": "wrong_tree", "unit": u["unit"], "port": port,
                                 "why": f"something is on {port} but it is running from "
                                        f"{row['cwd']}, not {u['path']}"})
        else:
            findings.append({"kind": "declared_not_running", "unit": u["unit"], "port": port,
                             "why": f"{u['unit']} declares {port} and nothing is listening"})
        declared.append(row)

    claimed = {u["port"] for u in rows if u.get("port")}
    for port, row in live.items():
        if port not in claimed:
            findings.append({"kind": "running_unclaimed", "port": port, "cwd": row.get("cwd"),
                             "why": f"{port} is listening and no unit in {tree} claims it"})

    for name, port in board.items():
        owner = next((u["unit"] for u in rows if u.get("port") == port), None)
        if owner is None and port not in live:
            findings.append({"kind": "board_only", "port": port, "board_name": name,
                             "why": f"the board assigns {port} to {name}; no unit claims it "
                                    f"and nothing is listening"})

    return {"tree": tree, "declared": declared, "board_ports": board,
            "listening": sorted(live), "findings": findings,
            "agrees": not findings}
