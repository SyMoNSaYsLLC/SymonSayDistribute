# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
"""Plugins — declared capability, never executed code.

A plugin is a manifest. It names a component, where that component answers, and the tools
that reach it. It does not carry code and nothing in it is imported or run.

WHY IT WORKS THAT WAY
---------------------
The obvious design is a directory of Python that the runtime imports. That makes dropping a
file into a directory equivalent to granting arbitrary execution inside the runtime that holds
the gateway credential — the capability a plugin adds would be bounded by nothing, and the
grant model the agents runtime is built on would be decorative.

A manifest can only ever describe an HTTP call. The worst a hostile plugin can do is point a
tool at an endpoint, which the operator can read in the manifest before enabling it, and which
`reachable()` will report as answering or not.

ENABLING IS DELIBERATE
----------------------
Discovery lists what is present. Nothing loads until it is enabled by name. A plugin that
appeared on disk has not been chosen, and "it was in the directory" is not consent.

THE LICENCE IS PART OF THE MANIFEST
-----------------------------------
Every plugin declares one, and a plugin whose licence would reach into this runtime is
reported rather than quietly loaded. That is the placement procedure applied at run time: this
runtime is proprietary, and what it links decides whether it can stay that way.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from .tools import Tool, ToolError

NOT_EXPOSED = {
    "plugin_root": "reported inside GET /api/agents/plugins",
    "PluginError": "an exception type",
    "discover": "its result is GET /api/agents/plugins, through load()",
    "enabled_names": "reported inside GET /api/agents/plugins",
    "tools_for": "turns one manifest into tools; reached through load() at start-up",
    "load": "runs once at start-up. Deliberately NOT routed: reloading plugins over HTTP "
            "would let a caller change what every subsequent run may do, which is the one "
            "decision the grant model exists to keep out of a request",
}

# Licence classes that can sit inside a proprietary runtime without changing what it is.
# Anything else is reported, never silently accepted — the decision belongs to a person.
PERMISSIVE = {
    "MIT", "MIT-0", "BSD-2-Clause", "BSD-3-Clause", "Apache-2.0", "ISC", "0BSD",
    "Zlib", "PSF-2.0", "Python-2.0", "Unlicense", "CC0-1.0", "BSL-1.0",
    "LicenseRef-SymonSaysLLC-Proprietary-1.0", "LicenseRef-SymonSaysLLC-OpenSource-1.0",
}

REQUIRED = ("name", "version", "licence", "component", "endpoint", "tools")


class PluginError(Exception):
    pass


def plugin_root() -> Path:
    return Path(os.environ.get("SYM_PLUGINS_DIR", "/models/plugins"))


def _read(manifest: Path) -> dict[str, Any]:
    try:
        m = json.loads(manifest.read_text())
    except Exception as e:
        raise PluginError(f"{manifest}: not readable JSON: {e}")
    missing = [k for k in REQUIRED if k not in m]
    if missing:
        raise PluginError(f"{manifest}: manifest lacks {missing}")
    if not isinstance(m["tools"], list) or not m["tools"]:
        raise PluginError(f"{manifest}: a plugin declaring no tools grants nothing")
    for t in m["tools"]:
        for k in ("name", "description", "path"):
            if k not in t:
                raise PluginError(f"{manifest}: a tool lacks {k}")
        if not str(t["path"]).startswith("/"):
            raise PluginError(f"{manifest}: tool {t['name']} path must begin with /")
    return m


def discover() -> list[dict[str, Any]]:
    """Every plugin present, whether or not it is enabled, with why it would be refused.

    A plugin that cannot be loaded is listed WITH ITS REASON rather than omitted. A directory
    silently skipping what it cannot parse is how a plugin comes to be "installed" and absent
    at the same time.
    """
    root = plugin_root()
    if not root.is_dir():
        return []
    out = []
    for d in sorted(p for p in root.iterdir() if p.is_dir()):
        manifest = d / "plugin.json"
        row: dict[str, Any] = {"directory": str(d), "name": d.name, "loadable": False}
        if not manifest.is_file():
            row["why"] = "no plugin.json"
            out.append(row)
            continue
        try:
            m = _read(manifest)
        except PluginError as e:
            row["why"] = str(e)
            out.append(row)
            continue
        lic = str(m["licence"])
        row |= {
            "name": m["name"], "version": m["version"], "licence": lic,
            "component": m["component"], "endpoint": m["endpoint"],
            "tools": [t["name"] for t in m["tools"]],
            "licence_permissive": lic in PERMISSIVE,
            "loadable": True,
        }
        if lic not in PERMISSIVE:
            row["why"] = (f"licence {lic} is not one this runtime can absorb without a "
                          "placement decision; it is listed, not loaded")
            row["loadable"] = False
        out.append(row)
    return out


def enabled_names() -> list[str]:
    """Only what was chosen. Presence on disk is not consent."""
    raw = os.environ.get("SYM_PLUGINS_ENABLED", "").strip()
    return [n for n in (x.strip() for x in raw.split(",")) if n]


def tools_for(manifest: dict[str, Any], call) -> list[Tool]:
    """Turn a manifest's declared tools into real ones.

    `call(component, path, method, body)` is injected — the plugin never gets a socket, only a
    description of the request it wants made, which the runtime performs with its own rules
    about credentials.
    """
    made = []
    for t in manifest["tools"]:
        name, path = t["name"], t["path"]
        method = str(t.get("method", "GET")).upper()
        mutates = bool(t.get("mutates", method not in ("GET", "HEAD")))
        component = manifest["component"]

        def run(args: dict, _p=path, _m=method, _c=component) -> Any:
            return call(_c, _p, _m, args or None)

        made.append(Tool(f"{manifest['name']}_{name}", t["description"],
                         t.get("input_schema") or {"type": "object", "properties": {}},
                         run, mutates=mutates))
    return made


def load(call) -> tuple[list[Tool], list[dict[str, Any]]]:
    """Return the tools from enabled, loadable plugins — and the record of every decision."""
    found = discover()
    want = set(enabled_names())
    tools: list[Tool] = []
    record = []
    for row in found:
        chosen = row["name"] in want
        state = ("loaded" if (chosen and row["loadable"]) else
                 "present, not enabled" if not chosen else
                 "enabled but refused")
        record.append(row | {"enabled": chosen, "state": state})
        if chosen and row["loadable"]:
            m = _read(Path(row["directory"]) / "plugin.json")
            tools.extend(tools_for(m, call))
    return tools, record
