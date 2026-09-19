#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
"""source-pin — record or check what an acquired tree actually is.

    scripts/pin.py record <tree> [--component NAME] [--out FILE]
    scripts/pin.py check  <pin.json> [--tree PATH]

WHY A PIN AND NOT A TAG
-----------------------
A tag moves. A maintainer can delete one and push it again at a different commit, and every
build that trusted it silently changes. A commit identifier cannot move. So a pin records the
full commit, and the nearest tag beside it for humans only — never as the thing fetched.

WHAT A PIN HAS TO CONTAIN TO BE WORTH ANYTHING
----------------------------------------------
Enough to fetch the identical bytes again, and enough to defend the choice at a licence review
a year later, when the tree itself may be gone and nobody remembers the conversation:

  * the upstream URL and the full commit
  * the declared licence AND the checksum of the licence file, because "it was MIT" is a claim
    and the checksum is what makes it checkable after upstream relicenses
  * the copyright line the licence obliges us to carry
  * when it was acquired, so an August-dated acquisition can be caught

`check` re-reads all of that from the tree and reports every field that has drifted.
"""
from __future__ import annotations
import argparse, hashlib, json, re, subprocess, sys
from datetime import date
from pathlib import Path

LICENCE_NAMES = ("LICENSE", "LICENCE", "LICENSE.txt", "LICENSE.md", "COPYING", "COPYING.txt")
IDENTS = ("MIT", "Apache-2.0", "BSD-3-Clause", "BSD-2-Clause", "ISC", "0BSD", "Zlib",
          "MPL-2.0", "LGPL-2.1", "LGPL-3.0", "GPL-2.0", "GPL-3.0", "AGPL-3.0")


def git(tree: Path, *a) -> str:
    r = subprocess.run(["git", "-C", str(tree), *a], capture_output=True, text=True)
    return r.stdout.strip() if r.returncode == 0 else ""


def find_licence(tree: Path) -> tuple[str, str, str, str]:
    """(relative path, md5, declared identifier, copyright line)"""
    for name in LICENCE_NAMES:
        f = tree / name
        if not f.exists():
            continue
        data = f.read_bytes()
        text = data.decode("utf-8", errors="replace")
        ident = ""
        for i in IDENTS:
            probe = i.split("-")[0].lower()
            if probe in text.lower()[:2000]:
                ident = i
                break
        # The strictest signal beats the loosest: an explicit SPDX line wins over a word match.
        m = re.search(r"SPDX-License-Identifier:\s*([^\s]+)", text)
        if m:
            ident = m.group(1)
        c = ""
        for line in text.splitlines():
            if re.match(r"\s*(copyright|\(c\)|©)", line, re.I) and len(line.strip()) > 12:
                c = line.strip()
                break
        return name, hashlib.md5(data).hexdigest(), ident or "UNDETERMINED", c
    return "", "", "NO LICENCE FILE FOUND", ""


def record(tree: Path, component: str | None) -> dict:
    if not (tree / ".git").exists():
        print(f"{tree} is not a git checkout — a pin without a commit is not a pin", file=sys.stderr)
        raise SystemExit(2)
    lic_file, lic_md5, lic_id, copyright_line = find_licence(tree)
    commit = git(tree, "rev-parse", "HEAD")
    commit_date = git(tree, "show", "-s", "--format=%ci", "HEAD")
    pin = {
        "schema": "symoneural-acquisition/1",
        "component": component or tree.name,
        "upstream_url": git(tree, "config", "--get", "remote.origin.url"),
        "commit_sha": commit,
        "commit_date": commit_date,
        "nearest_tag": git(tree, "describe", "--tags", "--abbrev=0") or "",
        "declared_license": lic_id,
        "license_file": lic_file,
        "license_md5": lic_md5,
        "copyright": copyright_line,
        "acquired": date.today().isoformat(),
        "tree": str(tree),
        "size_on_disk": subprocess.run(["du", "-sh", str(tree)], capture_output=True, text=True).stdout.split()[0:1] or [""],
        "full_history": bool(git(tree, "rev-list", "--count", "HEAD")),
        "worktree_clean": git(tree, "status", "--porcelain") == "",
    }
    pin["size_on_disk"] = pin["size_on_disk"][0] if pin["size_on_disk"] else ""
    return pin


def check(pin_path: Path, tree_override: str | None) -> int:
    pin = json.loads(pin_path.read_text())
    tree = Path(tree_override or pin.get("tree", ""))
    print(f"{pin.get('component')}  pin {pin_path}")
    if not tree.exists():
        print(f"  the tree is gone: {tree}")
        print("  The pin is still the record. Re-fetch from upstream_url at commit_sha to check it.")
        return 1
    now = record(tree, pin.get("component"))
    drift = 0
    for field, why in (("commit_sha", "the tree is at a different commit than the pin says"),
                       ("declared_license", "upstream changed its licence, or the pin was wrong"),
                       ("license_md5", "the licence FILE changed even if its name did not"),
                       ("copyright", "the attribution we are obliged to carry has changed")):
        was, is_ = pin.get(field, ""), now.get(field, "")
        if was != is_:
            drift += 1
            print(f"  DRIFT  {field}")
            print(f"         pinned: {str(was)[:70]}")
            print(f"         now:    {str(is_)[:70]}")
            print(f"         {why}")
    if not now["worktree_clean"]:
        print("  the acquired tree has local modifications — it is supposed to be read-only")
        drift += 1
    if str(pin.get("acquired", "")).startswith("2026-08") or str(pin.get("commit_date", "")).startswith("2026-08"):
        print("  DATED AUGUST 2026 — barred from use until ruled on")
        drift += 1
    if drift == 0:
        print("  matches the pin in every recorded field")
    return 1 if drift else 0


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("record"); r.add_argument("tree", type=Path)
    r.add_argument("--component"); r.add_argument("--out", type=Path)
    c = sub.add_parser("check"); c.add_argument("pin", type=Path); c.add_argument("--tree")
    a = ap.parse_args()

    if a.cmd == "record":
        pin = record(a.tree, a.component)
        text = json.dumps(pin, indent=2, sort_keys=True) + "\n"
        if a.out:
            a.out.write_text(text); print(f"wrote {a.out}")
        else:
            print(text, end="")
        if pin["declared_license"] in ("UNDETERMINED", "NO LICENCE FILE FOUND"):
            print("\nThe licence could not be determined from the tree. That is not a pin you can"
                  "\nbuild from — establish it before this is used.", file=sys.stderr)
            return 2
        return 0
    return check(a.pin, a.tree)


if __name__ == "__main__":
    raise SystemExit(main())
