# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
# SyMoNsAyLeaRn — SyMoNeuRaL, a subdivision of SymonSaysLLC. Terms: see LICENSE.
"""The wiring table — one place that knows where every component answers.

READ FROM THE BOARD, NOT HARDCODED
----------------------------------
`/models/control.board` has been called the estate's port authority in five documents, and
until now exactly one service read it: the board itself. Every other unit read its own
SYM_*_PORT with a hardcoded default, so the authority was a claim in prose.

The fabric reads it. That makes the board authoritative in the only way that counts — something
depends on it — and it means changing a port is one edit in one file rather than an edit in
every caller.

WHAT A COMPONENT ENTRY IS
-------------------------
A name, where it answers, the path prefix it owns, and the NAME of the environment variable
holding its token. Never the token itself: the fabric reads that at call time, so a wiring
table can be printed, logged and served without printing a credential.
"""
from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

# Where each of these is reachable. The gate asks, and three of them ARE served — inside
# other routes, because they are parts of one answer rather than four answers. A caller does
# not want "the ports" and "what is not routable" as separate fetches; it wants the table, and
# the table is only honest when it says what was left out of it and why.
NOT_EXPOSED = {
    "board_text":       "reads the board file; its parsed result is served as GET "
                        "/api/fabric/board. Serving the raw text would publish a file whose "
                        "other sections are not the fabric's to hand out",
    "ports":            "served as GET /api/fabric/board",
    "not_routable":     "served inside GET /api/fabric/components, beside the routable ones, "
                        "because what the fabric refuses to route is part of the wiring table "
                        "and not a separate question",
    "unknown_on_board": "served inside GET /api/fabric/components as on_board_unaccounted",
    "components":       "routed as GET /api/fabric/components",
    "resolve":          "routed as GET /api/fabric/resolve",
}

BOARD = os.environ.get("SYM_BOARD_FILE", "/models/control.board")

_ENTRY = re.compile(r"^\s*([a-z_][a-z0-9_]*)\s*=\s*(\d{2,5})", re.M)

# What each named port means: the prefix it owns, its health path, and the variable holding its
# token. A component not in here is not routable — the fabric refuses rather than guessing a
# prefix, because guessing one means forwarding to a path the component never published.
KNOWN: dict[str, dict[str, Any]] = {
    "board":        {"prefix": "/api/board",        "token_env": "SYM_BOARD_TOKEN"},
    "store":        {"prefix": "/api/store",        "token_env": "SYM_STORE_TOKEN"},
    "agents":       {"prefix": "/api/agents",       "token_env": "SYM_AGENTS_TOKEN"},
    "ravencalc":    {"prefix": "/api/ravencalc",    "token_env": "SYM_RAVENCALC_TOKEN"},
    "symonpayload": {"prefix": "/api/symonpayload", "token_env": "SYM_PAYLOAD_TOKEN"},
    "symonscope":   {"prefix": "/api/symonscope",   "token_env": "SYM_SCOPE_TOKEN"},
    "symonprobe":   {"prefix": "/api/symonprobe",   "token_env": "SYM_PROBE_TOKEN"},
    "symonweb":     {"prefix": "/api/symonweb",     "token_env": "SYM_WEB_TOKEN"},
    "symonrag":     {"prefix": "/api/symonrag",     "token_env": "SYM_RAG_TOKEN"},
    "symonlora":    {"prefix": "/api/symonlora",    "token_env": "SYM_LORA_TOKEN"},
    # The gateway speaks the public Messages dialect, whose paths are fixed by its clients and
    # are not ours to prefix. Its credential is a FILE, named on the board, never an env var.
    "gateway":      {"prefix": "/v1",               "token_env": None, "health": "/health"},
}

# Named on the board and deliberately not routable through the fabric.
NOT_ROUTABLE = {
    "chat": "the engine. Reached through the gateway, which owns the dialect and the "
            "credential; a second path to the engine is a second thing to secure",
    "web":  "a browser interface, not a component API. Nothing calls it",
    "control_plane": "read-only and supervised elsewhere (rules R14). The fabric will not "
                     "forward to it, so it cannot be changed through here by accident",
    "fabric": "this service. Routing the fabric through the fabric is a loop, and a caller "
              "that wants the wiring table already has it — that is what /components is",
}


class FabricError(Exception):
    """A routing decision that could not be made, carrying why."""


def board_text() -> str:
    p = Path(BOARD)
    if not p.is_file():
        raise FabricError(f"no board at {BOARD}; the fabric has no wiring table without it")
    return p.read_text(errors="replace")


def ports() -> dict[str, int]:
    """The [ports] section of the board, as written."""
    text = board_text()
    start = text.find("[ports]")
    if start < 0:
        raise FabricError(f"{BOARD} has no [ports] section")
    block = text[start + len("[ports]"):]
    end = block.find("\n[")
    return {k: int(v) for k, v in _ENTRY.findall(block[:end if end > 0 else len(block)])}


def components() -> dict[str, dict[str, Any]]:
    """Every routable component: where it answers, what it owns, which variable holds its key.

    No credential is read here. The token VARIABLE NAME is part of the table; whether it is set
    is reported as a boolean, so an operator can see what is unprovisioned without the table
    ever holding a secret.
    """
    out: dict[str, dict[str, Any]] = {}
    for name, port in ports().items():
        if name in NOT_ROUTABLE:
            continue
        k = KNOWN.get(name)
        if not k:
            continue
        env = k.get("token_env")
        out[name] = {
            "component": name,
            "base": f"http://127.0.0.1:{port}",
            "port": port,
            "prefix": k["prefix"],
            "health": k.get("health", f"{k['prefix']}/health"),
            "token_env": env,
            "token_set": bool((os.environ.get(env) or "").strip()) if env else None,
        }
    return out


def not_routable() -> dict[str, str]:
    """What the board names that the fabric will not forward to, and why not for each."""
    p = ports()
    return {k: v for k, v in NOT_ROUTABLE.items() if k in p}


def unknown_on_board() -> list[str]:
    """Named on the board, not routable, and with no recorded reason — a gap, not a decision."""
    return sorted(set(ports()) - set(KNOWN) - set(NOT_ROUTABLE))


def resolve(component: str, path: str) -> dict[str, Any]:
    """Where a call goes, or a refusal saying why it does not go anywhere.

    Two refusals matter. An unknown component is refused rather than guessed at. And a path
    outside the component's own prefix is refused: the fabric forwards to published surfaces,
    and a caller that could name any path could reach anything this host serves.
    """
    table = components()
    c = table.get(component)
    if not c:
        raise FabricError(
            f"{component!r} is not a routable component. Routable: "
            f"{', '.join(sorted(table))}. Named on the board but not routed: "
            f"{', '.join(sorted(not_routable()))}")
    if not path.startswith("/"):
        path = "/" + path
    if not path.startswith(c["prefix"] + "/") and path != c["prefix"]:
        raise FabricError(
            f"{path!r} is outside {component}'s published surface ({c['prefix']}/…). The "
            f"fabric forwards to what a component publishes, never to an arbitrary path")
    return {**c, "path": path, "url": c["base"] + path}
