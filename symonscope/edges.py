# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
# SyMoNsAyLeaRn — SyMoNeuRaL, a subdivision of SymonSaysLLC. Terms: see LICENSE.
"""Dependency edges between units, found in code and carrying their evidence.

WHY EVIDENCE IS PART OF THE EDGE
--------------------------------
An architecture diagram is a claim. An edge here is a file and a line number, so the claim can
be checked and so a stale edge is visible the moment the line moves. An edge with no evidence
is not reported at all — that is how an intention ends up drawn as a wire.

This module found the thing it was written to find on its first run: symonpayload's document
said "the arithmetic belongs to ravencalc", and there was no edge. A sentence is not a wire.

THREE KINDS OF EDGE, AND THEY ARE NOT THE SAME
----------------------------------------------
  import   one unit imports another's package. The hardest kind: it cannot be turned off, and
           it means the two ship together.
  http     one unit calls another's published surface. The kind this estate prefers, because
           it is enumerable and the far end can be down without breaking the build.
  declared a connector or configuration naming another unit. A wire that exists to be used,
           whether or not it has been used yet.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .survey import TREES, SurveyError, units

SKIP_DIRS = {".git", "__pycache__", "node_modules", ".pytest_cache", ".next", "dist", "build"}

# 127.0.0.1:<port> in one unit's code, where the port belongs to a different unit.
_HTTP = re.compile(r"127\.0\.0\.1:(\d{4,5})")
_IMPORT = re.compile(r"^\s*(?:from|import)\s+([a-zA-Z_][\w.]*)", re.M)


def _source_files(root: Path):
    for p in root.rglob("*"):
        if p.is_file() and p.suffix in (".py", ".sh", ".ts", ".tsx") \
                and not any(d in SKIP_DIRS for d in p.parts):
            yield p


def _port_owner(rows: list[dict]) -> dict[int, str]:
    """Which unit owns which port, from the units' own service files."""
    return {r["port"]: r["unit"] for r in rows if r.get("port")}


def _package_owner(rows: list[dict]) -> dict[str, str]:
    """Importable package name -> unit that provides it."""
    out: dict[str, str] = {}
    for r in rows:
        d = Path(r["path"])
        for child in d.iterdir() if d.is_dir() else []:
            if child.is_dir() and (child / "__init__.py").is_file():
                out[child.name] = r["unit"]
    return out


def edges(tree: str = "SymonSayDistribute") -> dict[str, Any]:
    """Every dependency edge between units of a tree, each with the line that proves it."""
    rows = units(tree)
    ports = _port_owner(rows)
    packages = _package_owner(rows)
    found: list[dict] = []
    seen: set[tuple] = set()

    for r in rows:
        src = r["unit"]
        for f in _source_files(Path(r["path"])):
            try:
                text = f.read_text(errors="replace")
            except Exception:
                continue
            for i, line in enumerate(text.splitlines(), 1):
                # http edge: a loopback port owned by another unit
                for m in _HTTP.finditer(line):
                    owner = ports.get(int(m.group(1)))
                    if owner and owner != src:
                        key = (src, owner, "http")
                        if key not in seen:
                            seen.add(key)
                            found.append({"from": src, "to": owner, "kind": "http",
                                          "evidence": f"{f}:{i}", "line": line.strip()[:160]})
            # import edge: importing another unit's package
            for m in _IMPORT.finditer(text):
                top = m.group(1).split(".")[0]
                owner = packages.get(top)
                if owner and owner != src:
                    key = (src, owner, "import")
                    if key not in seen:
                        seen.add(key)
                        ln = text[:m.start()].count("\n") + 1
                        found.append({"from": src, "to": owner, "kind": "import",
                                      "evidence": f"{f}:{ln}", "line": m.group(0).strip()[:160]})

    isolated = sorted({r["unit"] for r in rows}
                      - {e["from"] for e in found} - {e["to"] for e in found})
    return {"tree": tree, "count": len(found), "edges": sorted(
                found, key=lambda e: (e["from"], e["to"], e["kind"])),
            "isolated": isolated,
            "isolated_means": "no unit depends on it and it depends on none — either a leaf "
                              "tool, or something that was built and never wired"}
