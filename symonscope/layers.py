# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
# SyMoNsAyLeaRn — SyMoNeuRaL, a subdivision of SymonSaysLLC. Terms: see LICENSE.
"""Layers, DERIVED from the dependency graph and never declared.

WHY DERIVED
-----------
A hand-written layer list is correct on the day it is written and drifts every day after. This
computes the layer from the edges: a unit's layer is one more than the deepest thing it depends
on. Nothing to keep in step, because there is nothing written down to fall out of step with.

Layer 0 is a PROVIDER: it depends on no other unit in the estate, so everything may rest on it.
ravencalc is the clearest case — Garrett, 2026-09-19: it is the estate's provider of
arithmetic.

A CYCLE IS A REFUSAL, NOT A DIAGRAM
-----------------------------------
If A depends on B and B on A, the estate is not layered and no honest number can be assigned.
This reports the cycle and refuses to give those units a layer, rather than picking one and
making the architecture look sound. The cycle is the finding.
"""
from __future__ import annotations

from typing import Any

from .edges import edges
from .survey import units


def layers(tree: str = "SymonSayDistribute") -> dict[str, Any]:
    """Each unit's derived layer, the cycles that prevent one, and what sits where."""
    rows = units(tree)
    e = edges(tree)
    names = [r["unit"] for r in rows]
    deps: dict[str, set[str]] = {n: set() for n in names}
    for edge in e["edges"]:
        if edge["from"] in deps and edge["to"] in deps:
            deps[edge["from"]].add(edge["to"])

    layer: dict[str, int] = {}
    cycles: list[list[str]] = []

    def depth(n: str, stack: tuple[str, ...] = ()) -> int | None:
        if n in layer:
            return layer[n]
        if n in stack:
            cyc = list(stack[stack.index(n):]) + [n]
            if cyc not in cycles:
                cycles.append(cyc)
            return None
        if not deps[n]:
            layer[n] = 0
            return 0
        got = [depth(d, stack + (n,)) for d in sorted(deps[n])]
        if any(g is None for g in got):
            return None
        layer[n] = 1 + max(got)  # type: ignore[arg-type]
        return layer[n]

    for n in names:
        depth(n)

    by_layer: dict[int, list[str]] = {}
    for n, lv in sorted(layer.items()):
        by_layer.setdefault(lv, []).append(n)

    unplaced = sorted(set(names) - set(layer))
    kinds = {r["unit"]: r["kind"] for r in rows}
    return {
        "tree": tree,
        "layers": [{"layer": lv,
                    "meaning": "provider — depends on nothing else in the estate" if lv == 0
                               else f"rests on layer {lv - 1}",
                    "units": [{"unit": u, "kind": kinds.get(u), "depends_on": sorted(deps[u])}
                              for u in us]}
                   for lv, us in sorted(by_layer.items())],
        "cycles": cycles,
        "unplaced": unplaced,
        "unplaced_means": "in a cycle; no honest layer can be assigned until it is broken",
        "edge_count": e["count"],
        "derived_from": "the dependency edges, recomputed on every call — nothing is declared",
    }
