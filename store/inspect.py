# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
"""Reading the weight store — what is in it, and whether it still is what it was.

Placement is not here. Putting 13 GB somewhere is a deliberate act with a filesystem, free
space and a licence to check, and it stays a command somebody runs. This is the half that
answers questions, which is the half a surface and an agent need.

VERIFY IS THE POINT
-------------------
A manifest that nobody recomputes is a claim, not a check. `verify` re-hashes every file and
compares, so drift in a checkpoint — a partial copy, a truncated file, a disk that lied — is
found by asking rather than by a model producing nonsense three weeks later.
"""
from __future__ import annotations

# Reached through the routes named below rather than as routes of their own.
NOT_EXPOSED = {
    "sha256": "a helper; its result reaches a caller through verify()",
    "store_root": "reported inside /api/store/where and /api/store/models",
    "manifest": "routed as GET /api/store/models/{name}",
    "provenance": "returned inside GET /api/store/models/{name}",
    "StoreError": "an exception type",
}

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any

RECORDS = {"MANIFEST.sha256.json", "NOTICE", "PROVENANCE.md"}


class StoreError(Exception):
    pass


def store_root() -> Path:
    return Path(os.environ.get("SYM_MODELS_DIR", "/models"))


def _sh(*a: str) -> str:
    try:
        r = subprocess.run(a, capture_output=True, text=True, timeout=15)
        return r.stdout.strip() if r.returncode == 0 else ""
    except Exception:
        return ""


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for c in iter(lambda: f.read(1 << 22), b""):
            h.update(c)
    return h.hexdigest()


def where() -> dict[str, Any]:
    """The store's real location: device, filesystem, UUID, free space.

    A store on tmpfs, overlay or a network mount accepts every write and loses them. Section
    3.1c: if the filesystem UUID cannot be named, this is not disk in the sense that matters.
    """
    root = store_root()
    src = _sh("findmnt", "-no", "SOURCE", "-T", str(root))
    fst = _sh("findmnt", "-no", "FSTYPE", "-T", str(root))
    mnt = _sh("findmnt", "-no", "TARGET", "-T", str(root))
    uuid = ""
    if src.startswith("/dev/"):
        uuid = (_sh("lsblk", "-no", "UUID", src).splitlines() or [""])[0]
    free = None
    if root.exists():
        st = os.statvfs(root)
        free = st.f_bavail * st.f_frsize
    not_disk = fst in ("tmpfs", "ramfs", "overlay") or fst.startswith(("fuse", "nfs", "cifs"))
    return {
        "store": str(root), "exists": root.is_dir(), "mounted_at": mnt,
        "device": src or None, "filesystem": fst or None, "uuid": uuid or None,
        "free_bytes": free, "free_gib": round(free / (1 << 30), 1) if free else None,
        "is_disk": bool(uuid) and not not_disk,
        "why": None if (uuid and not not_disk) else
               (f"{fst} is not a block filesystem" if not_disk else "no filesystem UUID"),
    }


def models() -> list[dict[str, Any]]:
    """Every model in the store, with whether it carries the records that make it checkable."""
    root = store_root()
    if not root.is_dir():
        return []
    out = []
    for d in sorted(p for p in root.iterdir() if p.is_dir()):
        man = d / "MANIFEST.sha256.json"
        row: dict[str, Any] = {"name": d.name, "path": str(d),
                               "files": sum(1 for p in d.iterdir() if p.is_file())}
        if man.is_file():
            try:
                m = json.loads(man.read_text())
                row |= {"manifest": True, "declared_name": m.get("name"),
                        "version": m.get("version"), "bytes": m.get("total_bytes"),
                        "placed": m.get("placed"), "tracked_files": len(m.get("files", {}))}
            except Exception as e:
                row |= {"manifest": False, "why": f"manifest unreadable: {e}"}
        else:
            row |= {"manifest": False,
                    "why": "no MANIFEST.sha256.json — nothing can tell whether this has drifted"}
        row["licence"] = (d / "LICENSE").is_file()
        row["notice"] = (d / "NOTICE").is_file()
        row["provenance"] = (d / "PROVENANCE.md").is_file()
        out.append(row)
    return out


def manifest(name: str) -> dict[str, Any]:
    d = store_root() / name
    if not d.is_dir():
        raise StoreError(f"no model {name!r} in {store_root()}")
    man = d / "MANIFEST.sha256.json"
    if not man.is_file():
        raise StoreError(f"{name} has no manifest — it cannot be verified")
    return json.loads(man.read_text())


def provenance(name: str) -> str:
    d = store_root() / name
    p = d / "PROVENANCE.md"
    if not d.is_dir():
        raise StoreError(f"no model {name!r} in {store_root()}")
    if not p.is_file():
        raise StoreError(f"{name} carries no provenance record")
    return p.read_text()


def verify(name: str) -> dict[str, Any]:
    """Re-hash every file and compare with the manifest.

    Three things are reported separately, because they mean different things: a digest that
    MOVED (the bytes changed), a file that is GONE, and a file that is present but UNTRACKED.
    Collapsing them into one count loses the distinction between corruption and someone having
    added something.
    """
    m = manifest(name)
    d = store_root() / name
    moved, gone, untracked = [], [], []
    for rel, meta in m.get("files", {}).items():
        p = d / rel
        if not p.is_file():
            gone.append(rel)
            continue
        got = sha256(p)
        if got != meta.get("sha256"):
            moved.append({"file": rel, "was": meta.get("sha256", "")[:16], "now": got[:16]})
    tracked = set(m.get("files", {}))
    for p in d.iterdir():
        if p.is_file() and p.name not in tracked and p.name not in RECORDS:
            untracked.append(p.name)
    ok = not moved and not gone
    return {"name": name, "ok": ok, "checked": len(m.get("files", {})),
            "moved": moved, "gone": gone, "untracked": untracked,
            "verdict": "every tracked file matches its recorded digest" if ok else
                       "the store has drifted from its manifest"}
