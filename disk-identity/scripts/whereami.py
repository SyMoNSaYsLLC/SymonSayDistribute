#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
"""whereami — name the machine and the filesystem UUID for a path, read now, never recalled.

    scripts/whereami.py [path ...] [--json]

"On disk" in this estate means Garrett's machine. An agent that cannot name the filesystem
UUID it is writing to is not writing to disk in the sense that matters, and a UUID stated from
memory is worse than no answer: a mount moves, a disk gets replaced, and the remembered value
then names the wrong device with total confidence.
"""
from __future__ import annotations
import argparse, json, subprocess, sys
from pathlib import Path

# Derived, never written in. A skill whose job is to refuse remembered facts must not carry a
# remembered path: hardcoding one operator's home makes the answer wrong on any other machine
# and right only by luck on this one.
def _defaults() -> list[str]:
    import os
    seen, out = set(), []
    for p in ("/", str(Path.home()), os.getcwd(), "/mnt"):
        if p and p not in seen:
            seen.add(p); out.append(p)
    return out


def sh(*a) -> str:
    try:
        return subprocess.run(a, capture_output=True, text=True, timeout=15).stdout.strip()
    except Exception:
        return ""


def machine() -> dict:
    return {
        "hostname": sh("hostname"),
        "machine_id": Path("/etc/machine-id").read_text().strip() if Path("/etc/machine-id").exists() else "",
        "kernel": sh("uname", "-r"),
    }


def for_path(p: str) -> dict:
    path = Path(p)
    exists = path.exists()
    source = sh("bash", "-c", f"df --output=source {p!r} 2>/dev/null | tail -1") if exists else ""
    uuid = sh("lsblk", "-no", "UUID", source) .splitlines()[:1] if source.startswith("/dev/") else []
    fstype = sh("lsblk", "-no", "FSTYPE", source).splitlines()[:1] if source.startswith("/dev/") else []
    avail = sh("bash", "-c", f"df -h --output=avail {p!r} 2>/dev/null | tail -1") if exists else ""
    is_mount = path.is_mount() if exists else False
    holder = sh("bash", "-c", f"findmnt -no TARGET -T {p!r} 2>/dev/null") if exists else ""
    return {
        "path": p,
        "exists": exists,
        "is_mountpoint": is_mount,
        "filesystem_root": holder,
        "device": source or "(not a block device)",
        "uuid": (uuid[0] if uuid else ""),
        "fstype": (fstype[0] if fstype else ""),
        "available": avail,
        "writable": exists and __import__("os").access(p, __import__("os").W_OK),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="*", default=None)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    paths = a.paths or _defaults()

    m = machine()
    rows = [for_path(p) for p in paths]

    if a.json:
        print(json.dumps({"machine": m, "paths": rows}, indent=2))
        return 0

    print(f"machine     {m['hostname']}  machine-id {m['machine_id']}  kernel {m['kernel']}")
    print()
    for r in rows:
        if not r["exists"]:
            print(f"{r['path']}\n  does not exist on this machine")
            continue
        print(f"{r['path']}")
        if r["is_mountpoint"]:
            print(f"  mount      yes — this path is the root of its filesystem")
        else:
            print(f"  mount      no — a directory on the filesystem mounted at {r['filesystem_root'] or '?'}")
        print(f"  device     {r['device']}")
        print(f"  uuid       {r['uuid'] or '(none — not a block device)'}")
        print(f"  filesystem {r['fstype'] or '(unknown)'}")
        print(f"  available  {r['available']}")
        print(f"  writable   {'yes' if r['writable'] else 'no'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
