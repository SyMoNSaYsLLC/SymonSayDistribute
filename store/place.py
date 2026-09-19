#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
"""place — put an acquired checkpoint into the estate's model store, under our name.

WHAT A MIGRATION IS
-------------------
Our store, our name, our manifest, our provenance record. Section 3.11: our name goes on
what we made — the composition, the cards, the implementation.

WHAT IT IS NOT
--------------
Rewriting the checkpoint. config.json, the tokenizer and every tensor file are copied
byte-for-byte and verified. Two independent reasons that happen to agree:
  - they are technical identifiers required to load the software (3.11, permitted class 3);
    changing model_type or architectures breaks every loader that reads them
  - the licence obliges us to keep attribution and to state what we changed
A migration that edited them would be a misrepresentation, not a migration.

THE SOURCE IS NEVER TOUCHED
---------------------------
Copy, never move. The acquired tree stays exactly where it is, unmodified and complete,
so the placement is reversible and nothing of Garrett's is destroyed to perform it.
"""
from __future__ import annotations

import argparse, hashlib, json, os, shutil, subprocess, sys, time
from pathlib import Path

CARRY_VERBATIM = {".safetensors", ".json", ".jinja", ".txt", ".model"}


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 22), b""):
            h.update(chunk)
    return h.hexdigest()


def fs_facts(p: Path) -> dict:
    def run(cmd):
        r = subprocess.run(cmd, capture_output=True, text=True)
        return r.stdout.strip() if r.returncode == 0 else ""
    src = run(["findmnt", "-no", "SOURCE", "-T", str(p)])
    fst = run(["findmnt", "-no", "FSTYPE", "-T", str(p)])
    uuid = run(["lsblk", "-no", "UUID", src]).splitlines()[:1] if src.startswith("/dev/") else []
    st = os.statvfs(p)
    return {"device": src, "fstype": fst, "uuid": uuid[0] if uuid else "",
            "free_bytes": st.f_bavail * st.f_frsize}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("source"); ap.add_argument("name")
    ap.add_argument("--store", default=os.environ.get("SYM_MODELS_DIR") or str(Path.home() / "symoneural-models"))
    ap.add_argument("--upstream", default="", help="where the checkpoint was acquired from")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    src, store = Path(a.source).resolve(), Path(a.store)
    dest = store / a.name
    if not src.is_dir():
        print(f"no such source: {src}", file=sys.stderr); return 2
    if dest.exists() and not dest.is_symlink():
        print(f"{dest} already exists — this places a NEW entry, it does not overwrite", file=sys.stderr); return 3

    files = sorted(p for p in src.rglob("*") if p.is_file() and not p.is_symlink())
    total = sum(p.stat().st_size for p in files)
    facts = fs_facts(store if store.exists() else store.parent)

    # Refuse a destination that is not disk, or that cannot hold the copy with room to spare.
    if facts["fstype"] in ("tmpfs", "ramfs", "overlay") or facts["fstype"].startswith(("fuse", "nfs")):
        print(f"destination is {facts['fstype']} — not disk", file=sys.stderr); return 4
    if not facts["uuid"]:
        print("destination has no filesystem UUID — not disk (rules 3.1c)", file=sys.stderr); return 4
    need = int(total * 1.05)
    if facts["free_bytes"] < need:
        print(f"need {need/(1<<30):.1f} GiB, have {facts['free_bytes']/(1<<30):.1f} GiB", file=sys.stderr); return 4
    # A model store inside a git worktree would put weights on a path git can stage.
    if subprocess.run(["git", "-C", str(store.parent), "rev-parse", "--git-dir"],
                      capture_output=True).returncode == 0:
        print(f"{store.parent} is inside a git repository — weights never go there", file=sys.stderr); return 4

    print(f"place   {a.name}")
    print(f"  from    {src}")
    print(f"  into    {dest}")
    print(f"  files   {len(files)}   {total/(1<<30):.2f} GiB")
    print(f"  device  {facts['device']}  uuid {facts['uuid']}  free {facts['free_bytes']/(1<<30):.0f} GiB")
    if a.dry_run:
        print("  DRY RUN — nothing created"); return 0

    staging = store / f".{a.name}.incoming"
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True)

    manifest, t0 = {}, time.time()
    for i, p in enumerate(files, 1):
        rel = p.relative_to(src)
        out = staging / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(p, out)
        got, want = sha256(out), sha256(p)
        if got != want:
            print(f"  VERIFY FAILED {rel}", file=sys.stderr); return 5
        manifest[str(rel)] = {"sha256": got, "bytes": p.stat().st_size}
        print(f"  [{i}/{len(files)}] {rel}  {p.stat().st_size/(1<<20):.1f} MiB  ok", flush=True)

    lic = staging / "LICENSE"
    if not lic.exists():
        print("  no LICENSE in the source — refusing to place a checkpoint with no licence", file=sys.stderr)
        return 6

    (staging / "MANIFEST.sha256.json").write_text(json.dumps(
        {"schema": "symoneural-model-store/1", "name": a.name,
         "placed": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "files": manifest,
         "total_bytes": total}, indent=1, sort_keys=True) + "\n")

    (staging / "NOTICE").write_text(
        f"{a.name}\n\n"
        "This model is served by SyMoNeuRaL under SyMoNeuRaL's own name and model cards.\n"
        "The weights are acquired upstream material, carried unmodified and redistributed\n"
        "under the terms of the LICENSE file in this directory.\n\n"
        f"Upstream: {a.upstream or '(recorded in the estate source register)'}\n\n"
        "SyMoNeuRaL's contribution is the composition: the store layout, the model cards,\n"
        "the serving runtime and the dialect. It is not a claim of authorship over the\n"
        "weights, and no such claim is made anywhere in this distribution.\n")

    (staging / "PROVENANCE.md").write_text(
        f"# {a.name} — provenance\n\n"
        f"Placed {time.strftime('%Y-%m-%d %H:%M:%S%z')} by `model-store place`.\n\n"
        f"- source directory: `{src}`\n"
        f"- files carried: {len(files)}\n"
        f"- total bytes: {total}\n"
        f"- destination device: `{facts['device']}`, filesystem UUID `{facts['uuid']}`\n\n"
        "## What was changed\n\n"
        "Nothing in the checkpoint. Every file listed in `MANIFEST.sha256.json` was copied\n"
        "byte-for-byte and its digest verified after the copy. `config.json`, the tokenizer\n"
        "and every tensor file are identical to the source, because they are what a loader\n"
        "reads and because the licence requires modified files to say so — none are modified.\n\n"
        "## What was added\n\n"
        "`MANIFEST.sha256.json`, `NOTICE` and this file. Nothing was removed.\n\n"
        "## Verifying\n\n"
        "    model-store verify " + a.name + "\n\n"
        "recomputes every digest and reports any that moved.\n")

    os.replace(staging, dest.with_suffix(".placed") if dest.exists() else dest)
    print(f"  placed  {dest}  in {time.time()-t0:.0f}s")
    print(f"  next    model-store verify {a.name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
