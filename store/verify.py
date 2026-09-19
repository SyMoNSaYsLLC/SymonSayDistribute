#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
# SyMoNsAyLeaRn — SyMoNeuRaL, a subdivision of SymonSaysLLC. Terms: see LICENSE.
"""model-store verify — re-hash every tracked file and compare it to the manifest.

A THIN DOOR ONTO ONE IMPLEMENTATION
-----------------------------------
The checking lives in `inspect.verify`, which is what the HTTP surface calls. This is the same
function reached from a terminal, not a second implementation of it — two copies of "is this
checkpoint still what it was" would eventually disagree, and the day they disagree is the day
nobody knows which to believe.

WHY THIS FILE DID NOT EXIST
---------------------------
The CLI advertised `verify` in its usage and dispatched to `store/verify.py`, which was never
written. `model-store verify symon-imager` therefore died with a python file-not-found after a
successful 12 GiB placement — the command the placement itself told the operator to run next.
A command a tool recommends to itself is the one most likely to be trusted.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from store import inspect as S  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(prog="model-store verify")
    ap.add_argument("name", help="the model in the store to re-hash")
    ap.add_argument("--store", default=None, help="the store root (default: the configured one)")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    if a.store:
        os.environ["SYM_MODEL_STORE"] = a.store

    try:
        out = S.verify(a.name)
    except Exception as e:
        print(f"{type(e).__name__}: {e}", file=sys.stderr)
        return 4

    if a.json:
        print(json.dumps(out, indent=1))
    else:
        print(f"verify  {a.name}")
        for k in ("store", "files", "checked", "bytes"):
            if k in out:
                print(f"  {k:<12} {out[k]}")
        # The three are reported separately because they mean different things: a digest that
        # MOVED is corruption, a file that is GONE is a deletion, and an untracked file is
        # somebody having added something. Collapsing them loses which happened.
        for k, label in (("moved", "digest changed"), ("missing", "gone"),
                         ("untracked", "present but not in the manifest")):
            rows = out.get(k) or []
            if rows:
                print(f"  {label}:")
                for r in rows:
                    print(f"    {r}")
        ok = out.get("ok")
        print(f"  {'OK — every tracked file still hashes to what the manifest recorded' if ok else 'MISMATCH'}")
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
