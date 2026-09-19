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

# A component named as a STRING in a call. This is what a fabric-routed wire looks like, and
# it is why this pattern exists: when the agents runtime stopped hardcoding 127.0.0.1:8801 and
# started naming "ravencalc", the http edge vanished and ravencalc was reported isolated. It
# was not isolated; it had stopped being reachable by the only method this module could see.
#
# A surveyor that only recognises the wiring style it was written against will report every
# improvement as a regression.
_NAMED = re.compile(r'_call\(\s*["\']([a-z][a-z0-9_-]*)["\']|'
                    r'"component"\s*:\s*["\']([a-z][a-z0-9_-]*)["\']')
_IMPORT = re.compile(r"^\s*(?:from|import)\s+([a-zA-Z_][\w.]*)", re.M)


PROSE_STARTS = ('#', '//', '*', '<!--', '- ', '"""', "'''")


def _is_prose(line: str) -> bool:
    """A comment or docstring line is prose, not a wire.

    This module reported `symonweb -> board` because symonweb's guard docstring names
    http://127.0.0.1:8811 as an EXAMPLE of an address it refuses. Reporting that as a
    dependency is the exact failure this module exists to prevent, committed by the thing
    that prevents it. It also manufactured cycles: a false edge is not one wrong row, it
    is every path that runs through it.
    """
    return line.lstrip().startswith(PROSE_STARTS)


def _is_test(path) -> bool:
    """A test naming an address exercises it; the shipped product does not depend on it."""
    return 'test' in path.name or 'tests' in path.parts


def _prose_lines(path: Path, text: str) -> set:
    """Line numbers that are prose: comments and docstrings. NOT every string.

    Two wrong answers preceded this one, and the second was worse than the first.

    First: a line was prose if it STARTED with a comment marker. Docstring body lines do
    not, so `symonweb -> board` survived — the address sits mid-paragraph in a docstring
    explaining what that unit refuses.

    Then: every COMMENT and STRING token from the tokenizer. That cut thirteen edges to
    five and silently deleted every fabric-routed wire, because a routed call names its
    component as a STRING — _call('ravencalc', ...) is the evidence, and the
    fix had classified the evidence as prose. The estate looked cleanly layered because
    most of its wiring had stopped being visible.

    A string that is an ARGUMENT is evidence. A string that is a STATEMENT is prose. That
    is the distinction, and ast knows it exactly: a docstring is an Expr whose value is a
    string constant. Comments still come from the tokenizer, which is the only thing that
    sees them at all.
    """
    lines = set()
    if path.suffix == '.py':
        import ast as _ast
        import io, tokenize
        try:
            for tok in tokenize.generate_tokens(io.StringIO(text).readline):
                if tok.type == tokenize.COMMENT:
                    lines.add(tok.start[0])
        except Exception:
            pass
        try:
            for node in _ast.walk(_ast.parse(text)):
                if isinstance(node, _ast.Expr) and isinstance(node.value, _ast.Constant) \
                        and isinstance(node.value.value, str):
                    for n in range(node.lineno, (node.end_lineno or node.lineno) + 1):
                        lines.add(n)
        except Exception:
            pass
    else:
        for i, line in enumerate(text.splitlines(), 1):
            if line.lstrip().startswith(PROSE_STARTS):
                lines.add(i)
    return lines


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
    unit_names = {r["unit"] for r in rows}
    found: list[dict] = []
    seen: set[tuple] = set()

    for r in rows:
        src = r["unit"]
        for f in _source_files(Path(r["path"])):
            try:
                text = f.read_text(errors="replace")
            except Exception:
                continue
            skip_file = _is_test(f)
            prose = set() if skip_file else _prose_lines(f, text)
            for i, line in enumerate(text.splitlines(), 1):
                if skip_file or i in prose:
                    continue
                # http edge: a loopback port owned by another unit
                for m in _HTTP.finditer(line):
                    owner = ports.get(int(m.group(1)))
                    if owner and owner != src:
                        key = (src, owner, "http")
                        if key not in seen:
                            seen.add(key)
                            found.append({"from": src, "to": owner, "kind": "http",
                                          "evidence": f"{f}:{i}", "line": line.strip()[:160]})
                # declared edge: a component named as a string, which is what routing
                # through the fabric looks like from the caller's side
                for m in _NAMED.finditer(line):
                    named = m.group(1) or m.group(2)
                    if named and named in unit_names and named != src:
                        key = (src, named, "declared")
                        if key not in seen:
                            seen.add(key)
                            found.append({"from": src, "to": named, "kind": "declared",
                                          "evidence": f"{f}:{i}",
                                          "line": line.strip()[:160]})

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
