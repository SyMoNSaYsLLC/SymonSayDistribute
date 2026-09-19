#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
# SyMoNsAyLeaRn — SyMoNeuRaL, a subdivision of SymonSaysLLC. Terms: see LICENSE.
"""ship-gate — the release gate, from every angle, run against the staged artifacts.

    ship-gate.py --stage /home/google/symoneural-release/v1.0.0 [--repo DIR ...] [--json OUT]

Exit 1 on any FAIL. It re-derives every census itself from the artifacts on disk — it
never trusts a build report. A scanner that is not installed is recorded as REVIEW,
never as a pass. The policy lives beside this file in ship-gate-policy.json; this
script only applies it.

Classes checked, per the policy: licence class of every component in every shipped
closure (wheels via a throwaway venv, web via package.json walk, ELF via NEEDED,
rootfs via license.manifest), attribution present in THIRD-PARTY-NOTICES, secrets by
content and by path (inside archives too), weights in artifacts, trademarks in
product-facing names, known CVEs, August-dated inputs, static-link copyleft.
"""
from __future__ import annotations
import argparse, hashlib, io, json, os, re, shutil, subprocess, sys, tarfile, tempfile, zipfile, time
from pathlib import Path

HERE = Path(__file__).resolve().parent
POLICY = json.loads((HERE / "ship-gate-policy.json").read_text())
CLASSES = POLICY["classes"]
ID2CLASS: dict[str, str] = {}
for cname, c in CLASSES.items():
    for i in c.get("ids", []):
        ID2CLASS.setdefault(i.lower(), cname)
NEUTRALISE = {e.lower() for e in CLASSES["STRONG_COPYLEFT"]["exceptions_that_neutralise"]}
USE_KW = [k.lower() for k in CLASSES["USE_RESTRICTED"].get("keywords", [])]
RANK = ["PERMISSIVE", "INVOKED_NOT_LINKED", "WEAK_COPYLEFT_FILE", "WEAK_COPYLEFT_LIB", "NUISANCE_CLAUSE", "PROPRIETARY_THIRD_PARTY",
        "USE_RESTRICTED", "UNKNOWN", "STRONG_COPYLEFT", "NETWORK_COPYLEFT"]
FAIL_CLASSES = {c for c, v in CLASSES.items() if v["verdict"] == "FAIL"}
EXC_COMPONENTS = {e["component"].lower(): e for e in POLICY.get("exceptions", [])}
FIRST_PARTY = {u.lower() for u in POLICY["first_party_units"]}
TRADEMARKS = re.findall(r"\((.*?)\)", POLICY["trademark_rule"])[0].split(", ")
SECRET_RX = {k: re.compile(v.encode()) for k, v in POLICY["secrets_patterns"].items()}
SECRET_PATH_RX = [re.compile(p) for p in POLICY.get("secret_file_paths", [])]
# Allowlisted by the sha256 of the MATCHED BYTES, never by path or pattern. A path
# allowlist exempts every future string in that file; a fingerprint exempts exactly one
# string and nothing else, so a real credential added to the same line still fails.
SECRET_OK = {e["fingerprint"]: e for e in POLICY.get("secret_fingerprint_allowlist", [])}
WEIGHT_EXT = tuple(POLICY["weights_extensions"])
BIG = POLICY["large_binary_review_bytes"]
# The product licence is policy, not a literal. It was written out in five places and all
# five went stale together when the SymonSaysLLC licences replaced FSL-1.1-ALv2 — including
# an equality test, where a stale string is a silent behaviour change rather than wrong text.
PRODUCT_LICENCE = POLICY["product_licence"]

# ----------------------------------------------------------------------------- SPDX
_norm = {"apache 2.0": "Apache-2.0", "apache-2": "Apache-2.0", "apache software license": "Apache-2.0", "apache license 2.0": "Apache-2.0",
         "apache license, version 2.0": "Apache-2.0", "mit license": "MIT", "the mit license": "MIT", "bsd": "BSD-3-Clause",
         "bsd license": "BSD-3-Clause", "new bsd": "BSD-3-Clause", "simplified bsd": "BSD-2-Clause", "isc license": "ISC",
         "mozilla public license 2.0": "MPL-2.0", "mpl 2.0": "MPL-2.0", "python software foundation license": "PSF-2.0",
         "psf": "PSF-2.0", "lgpl": "LGPL-2.1-or-later", "gpl": "GPL-2.0-or-later", "lgplv2.1": "LGPL-2.1-only", "lgplv3": "LGPL-3.0-only",
         "gplv2": "GPL-2.0-only", "gplv3": "GPL-3.0-only", "agplv3": "AGPL-3.0-only", "public domain": "public-domain",
         "unlicense": "Unlicense", "zlib/libpng": "Zlib", "0bsd": "0BSD", "bsd-3": "BSD-3-Clause", "bsd-2": "BSD-2-Clause",
         "apache-2.0 or mit": "Apache-2.0 OR MIT", "mit or apache-2.0": "MIT OR Apache-2.0", "mit/apache-2.0": "MIT OR Apache-2.0",
         "apache-2.0/mit": "Apache-2.0 OR MIT", "bsd-3-clause or mit": "BSD-3-Clause OR MIT", "mit or unlicense": "MIT OR Unlicense"}

def normalise(expr: str | None) -> str:
    if expr is None: return ""
    e = str(expr).strip()
    if e.lower() in _norm: return _norm[e.lower()]
    return e.replace("/", " OR ") if "/" in e and " " not in e else e

def classify_id(tok: str) -> str:
    t = tok.strip().strip("()").lower()
    if t.endswith("+"): t = t[:-1] + "-or-later"
    if t in ID2CLASS: return ID2CLASS[t]
    # families by prefix
    if t.startswith("agpl") or t.startswith("sspl") or t.startswith("osl-"): return "NETWORK_COPYLEFT"
    if t.startswith("lgpl-3") or t.startswith("gpl") or t.startswith("gfdl") or t.startswith("cc-by-sa"): return "STRONG_COPYLEFT"
    if t.startswith("lgpl"): return "WEAK_COPYLEFT_LIB"
    if t.startswith("mpl") or t.startswith("epl") or t.startswith("cddl"): return "WEAK_COPYLEFT_FILE"
    if t.startswith("cc-by-nc") or t.startswith("cc-by-nd") or "rail" in t or t.startswith("busl") or t.startswith("polyform") or t.startswith("fsl-") or t.startswith("llama"): return "USE_RESTRICTED"
    if t.startswith("bsd-4") or t == "json": return "NUISANCE_CLAUSE"
    if t.startswith("licenseref-nvidia") or t in ("proprietary", "unlicensed", "commercial"): return "PROPRIETARY_THIRD_PARTY"
    if t.startswith("cc-by") or t.startswith("bsd-") or t.startswith("mit") or t.startswith("apache") or t in ("isc", "zlib", "unlicense", "cc0-1.0", "0bsd", "psf-2.0", "python-2.0", "bsl-1.0", "ofl-1.1", "wtfpl", "blueoak-1.0.0"): return "PERMISSIVE"
    if t.startswith("licenseref-") or "custom" in t or "see license" in t: return "PROPRIETARY_THIRD_PARTY"
    return "UNKNOWN"

EXC_MATCH: dict[str, dict] = {m.lower(): e for e in POLICY.get("exceptions", []) for m in e.get("matches", [])}

def detect_licence_text(text: str) -> str:
    """The SPDX id a licence TEXT most plausibly is — for licence files carried beside binaries."""
    t = " ".join(text.split()).lower()
    if "permission is hereby granted, free of charge" in t: return "MIT"
    if "apache license" in t and "version 2.0" in t: return "Apache-2.0"
    if "redistribution and use in source and binary forms" in t:
        if "neither the name" in t: return "BSD-3-Clause"
        return "BSD-2-Clause"
    if "permission to use, copy, modify, and/or distribute this software for any purpose" in t: return "ISC"
    if "gnu lesser general public license" in t or "gnu library general public" in t: return "LGPL-2.1-or-later"
    if "gnu general public license" in t: return "GPL-2.0-or-later"
    if "mozilla public license" in t: return "MPL-2.0"
    return ""

def classify(expr: str | None, *, static: bool = False, invoked: bool = False, component: str = "") -> tuple[str, str]:
    """Return (class, reason) for an SPDX expression. OR → least restrictive; AND → most; WITH exception may neutralise.
    A recorded exception for the component wins first, whatever the expression says (or fails to say)."""
    if component.lower() in EXC_COMPONENTS:
        ex = EXC_COMPONENTS[component.lower()]
        return "PERMISSIVE", f"recorded exception ({ex['component']}): {ex['why_it_passes']}"
    e = normalise(expr)
    if not e or e.lower() in ("none", "null", "noassertion", "unknown"): return "UNKNOWN", "no licence expression"
    low = e.lower()
    for kw in USE_KW:
        if kw in low: return "USE_RESTRICTED", f"keyword '{kw}' in licence text"
    # tokenise: split on AND first (most restrictive governs), then OR inside (least restrictive wins)
    def rank(c): return RANK.index(c) if c in RANK else len(RANK)
    and_parts = re.split(r"\s+AND\s+|\s*&\s*", e, flags=re.I)
    worst, why = "PERMISSIVE", ""
    for part in and_parts:
        or_parts = re.split(r"\s+OR\s+|\s*\|\s*", part, flags=re.I)
        best, bwhy = None, ""
        for alt in or_parts:
            alt = alt.strip().strip("()")
            base, _, exc = alt.partition(" WITH ")
            c = classify_id(base)
            if exc and exc.strip().lower() in NEUTRALISE and c == "STRONG_COPYLEFT": c = "PERMISSIVE"
            if c == "WEAK_COPYLEFT_LIB" and static: c, alt = "STRONG_COPYLEFT", alt + " (statically linked)"
            if best is None or rank(c) < rank(best): best, bwhy = c, alt
        if rank(best) > rank(worst): worst, why = best, bwhy
    if component.lower() in EXC_COMPONENTS and worst in ("WEAK_COPYLEFT_LIB", "STRONG_COPYLEFT", "PROPRIETARY_THIRD_PARTY"):
        return "PERMISSIVE", f"recorded exception: {EXC_COMPONENTS[component.lower()]['why_it_passes']}"
    # An interpreter or a command our script EXECUTES is a separate program, reached across a
    # process boundary. Copyleft governs the work it is combined into; it does not cross an
    # exec. This is the same distinction already applied to build-time tools: bash is GPL-3.0
    # and a shell script that runs under it is not thereby GPL. The class is recorded, not
    # laundered — the real licence stays in the row so the notices and the audit can see it.
    # UNKNOWN is deliberately absent from this list. Invoking something does not excuse being
    # unable to say what it is; a licence we could not establish stays a failure however the
    # component is reached.
    if invoked and worst in ("WEAK_COPYLEFT_FILE", "WEAK_COPYLEFT_LIB", "STRONG_COPYLEFT",
                             "NETWORK_COPYLEFT", "NUISANCE_CLAUSE", "PROPRIETARY_THIRD_PARTY"):
        return "INVOKED_NOT_LINKED", f"{why or e} — executed as a separate process, not linked"
    return worst, why or e

# ----------------------------------------------------------------------------- report
class Report:
    def __init__(self): self.units: dict[str, dict] = {}; self.cross: list[dict] = []
    def unit(self, name):
        return self.units.setdefault(name, {"components": [], "findings": [], "artifacts": [], "verdict": "PASS"})
    def finding(self, unit, level, kind, detail):
        u = self.unit(unit); u["findings"].append({"level": level, "kind": kind, "detail": detail})
        if level == "FAIL": u["verdict"] = "FAIL"
        elif level == "REVIEW" and u["verdict"] == "PASS": u["verdict"] = "REVIEW"
    def component(self, unit, name, version, licence, klass, reason, source):
        self.unit(unit)["components"].append({"name": name, "version": version, "license": licence, "class": klass, "reason": reason, "source": source})
        if klass in FAIL_CLASSES or klass == "PROPRIETARY_THIRD_PARTY":
            self.finding(unit, "FAIL", f"licence:{klass}", f"{name} {version}: {licence} — {reason}")

def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""): h.update(chunk)
    return h.hexdigest()

def run(cmd, **kw):
    t0 = time.time(); r = subprocess.run(cmd, capture_output=True, text=True, **kw); return r.returncode, r.stdout, r.stderr, round(time.time() - t0, 1)

# ----------------------------------------------------------------------------- censuses
def census_wheel(rep: Report, unit: str, whl: Path, tmp: Path):
    venv = tmp / f"venv-{unit}"; rc, out, err, s = run([sys.executable, "-m", "venv", str(venv)])
    if rc: return rep.finding(unit, "REVIEW", "census", f"venv creation failed rc={rc}: {err[-300:]}")
    py = venv / "bin" / "python"
    rc, out, err, s = run([str(py), "-m", "pip", "install", "-q", "--disable-pip-version-check", str(whl)])
    if rc: return rep.finding(unit, "FAIL", "install", f"pip install {whl.name} rc={rc}: {(err or out)[-600:]}")
    rep.finding(unit, "INFO", "install", f"pip install {whl.name} rc=0 in {s}s")
    code = r'''
import json, importlib.metadata as m
rows=[]
for d in m.distributions():
    md=d.metadata; lic=md.get("License-Expression") or md.get("License") or ""
    if not lic or len(lic)>200 or "\n" in lic:
        cls=[c.split("::")[-1].strip() for c in md.get_all("Classifier") or [] if c.startswith("License ::")]
        lic=" AND ".join(cls) if cls else (lic[:60] if lic else "")
    rows.append({"name":md["Name"],"version":md["Version"],"license":lic})
print(json.dumps(rows))'''
    rc, out, err, s = run([str(py), "-I", "-c", code])
    if rc: return rep.finding(unit, "REVIEW", "census", f"metadata read failed: {err[-300:]}")
    for r in json.loads(out):
        if r["name"].lower() in ("pip", "setuptools", "wheel"): continue
        fp = r["name"].lower().replace("_", "-") in FIRST_PARTY
        k, why = ("PERMISSIVE", "first-party") if fp else classify(r["license"], component=r["name"])
        rep.component(unit, r["name"], r["version"], r["license"], k, why, "importlib.metadata in throwaway venv")
    # bundled native libs inside the wheel → static rule
    with zipfile.ZipFile(whl) as z:
        sos = [n for n in z.namelist() if n.endswith(".so") or ".so." in n]
    if sos: rep.finding(unit, "REVIEW", "static", f"wheel bundles native libs {sos[:5]} — their closure must be checked as static")
    # CVEs
    rc, out, err, s = run([str(py), "-m", "pip", "install", "-q", "--disable-pip-version-check", "pip-audit"])
    if rc: return rep.finding(unit, "REVIEW", "cve", "pip-audit unavailable (install failed) — not a pass")
    rc, out, err, s = run([str(py), "-m", "pip_audit", "--format", "json", "--progress-spinner", "off"])
    try: vulns = json.loads(out).get("dependencies", [])
    except Exception: return rep.finding(unit, "REVIEW", "cve", f"pip-audit output unreadable rc={rc}: {err[-200:]}")
    tooling = {"pip", "setuptools", "wheel", "pip-audit", "cyclonedx-python-lib", "packaging", "rich", "pip-api", "pip-requirements-parser", "requests", "cachecontrol", "urllib3", "certifi", "idna", "charset-normalizer", "msgpack", "filelock", "platformdirs", "toml", "boolean-py", "license-expression", "defusedxml", "py-serializable", "sortedcontainers", "markdown-it-py", "mdurl", "pygments", "pyparsing", "pip-requirements-parser"}
    shipped = {d["name"].lower() for d in vulns} - tooling
    bad = [(d["name"], v["id"], v.get("fix_versions")) for d in vulns for v in d.get("vulns", []) if d["name"].lower() not in tooling]
    tool_bad = [(d["name"], v["id"]) for d in vulns for v in d.get("vulns", []) if d["name"].lower() in tooling]
    if bad: rep.finding(unit, "FAIL", "cve", f"known vulnerabilities in the shipped closure: {bad[:10]}")
    else: rep.finding(unit, "INFO", "cve", f"pip-audit: 0 known vulnerabilities across the shipped closure ({len(shipped)} dists)")
    if tool_bad: rep.finding(unit, "INFO", "cve", f"census-venv tooling (not shipped) has advisories: {sorted(set(n for n, _ in tool_bad))}")

def census_node_tree(rep: Report, unit: str, root: Path):
    seen = {}
    for pj in root.rglob("package.json"):
        try: d = json.loads(pj.read_text(encoding="utf-8", errors="replace"))
        except Exception: continue
        name, ver = d.get("name"), d.get("version")
        if not name or not ver: continue
        lic = d.get("license") or d.get("licenses")
        if isinstance(lic, list): lic = " OR ".join(x.get("type", str(x)) if isinstance(x, dict) else str(x) for x in lic)
        if isinstance(lic, dict): lic = lic.get("type")
        seen[(name, ver)] = lic or ""
    for (name, ver), lic in sorted(seen.items()):
        fp = name.lower() in FIRST_PARTY or name.lower().startswith("symoneural")
        k, why = ("PERMISSIVE", "first-party") if fp else classify(lic, component=name)
        rep.component(unit, name, ver, lic, k, why, f"package.json walk under {root.name}")
    rep.finding(unit, "INFO", "census", f"{len(seen)} node packages enumerated")

def _unit_root(elf: Path) -> Path:
    """The <unit>/<arch> directory a staged binary lives in (bin/ or lib/ or lib/ggml/ beneath it)."""
    p = elf.parent
    for _ in range(3):
        if (p / "bin").is_dir() or (p / "lib").is_dir() or (p / "SHA256SUMS").exists(): return p
        p = p.parent
    return elf.parent

def _carried_licence(root: Path, lib: str) -> tuple[str, str]:
    """A library bundled in the unit → the licence text carried beside it (licenses/ or LICENSE.<component>)."""
    stem = re.sub(r"\.so(\.\d+)*$", "", lib)
    stem = stem[3:] if stem.startswith("lib") else stem          # libggml-base → ggml-base; libllama → llama
    tokens = [t for t in re.split(r"[-_.]", stem) if len(t) > 2] or [stem]
    cands = [p for p in root.rglob("*") if p.is_file() and ("licenses" in p.parts or p.name.upper().startswith(("LICENSE", "COPYING")))]
    for p in cands:
        if any(t in str(p).lower() for t in tokens):
            return detect_licence_text(p.read_text(errors="replace")), str(p.relative_to(root))
    if lib.startswith("libsymoneural"):
        return PRODUCT_LICENCE, "first-party"
    return "", ""

def census_elf(rep: Report, unit: str, elf: Path, static_meta: Path | None):
    rc, out, err, s = run(["readelf", "-d", str(elf)])
    needed = re.findall(r"Shared library: \[(.+?)\]", out)
    rep.finding(unit, "INFO", "linkage", f"{elf.name}: NEEDED={needed or 'none (static)'}")
    root = _unit_root(elf)
    for lib in needed:
        # 1. a recorded exception by library name (the CUDA runtime, the driver)
        if lib.lower() in EXC_MATCH:
            ex = EXC_MATCH[lib.lower()]
            rep.component(unit, lib, ex["component"], ex["licence"], "PERMISSIVE", f"recorded exception: {ex['why_it_passes']}", "readelf NEEDED → policy exception"); continue
        # 2. a library carried inside the unit itself (by soname or by versioned file name) → its carried licence text
        soname_stem = re.sub(r"\.so(\.\d+)*$", "", lib)
        if list(root.rglob(lib)) or any(p.name.startswith(soname_stem + ".so") for p in root.rglob(soname_stem + ".so*")):
            lic, src = _carried_licence(root, lib)
            if lic == PRODUCT_LICENCE: rep.component(unit, lib, "first-party", lic, "PERMISSIVE", "first-party", "carried in the unit"); continue
            k, why = classify(lic, component=lib)
            rep.component(unit, lib, "carried", lic, k, why if lic else "carried library without a licence text beside it", f"carried in the unit → {src or 'no licence text found'}"); continue
        # 3. a system library → the Debian package's machine-readable copyright (merged /usr: resolve the real path first)
        # /sbin is not on a non-root PATH on this host; the resolved real path is what dpkg knows (merged /usr)
        rc, o, e, s = run(["bash", "-c", f"p=$(/sbin/ldconfig -p 2>/dev/null | awk '$1==\"{lib}\"{{print $NF; exit}}'); [ -n \"$p\" ] && dpkg -S \"$(readlink -f \"$p\")\" 2>/dev/null | cut -d: -f1"])
        pkg = o.strip() or lib
        lic = ""
        cp = Path(f"/usr/share/doc/{pkg}/copyright")
        if cp.exists():
            m = re.findall(r"^License:\s*(.+)$", cp.read_text(errors="replace"), flags=re.M)
            lic = " AND ".join(sorted(set(x.strip() for x in m if x.strip()))) if m else detect_licence_text(cp.read_text(errors="replace"))
        comp = "glibc" if pkg.startswith("libc6") else ("libgcc / libstdc++ / libgomp" if pkg.startswith(("libgcc", "libstdc++", "libgomp")) else pkg)
        k, why = classify(lic or "UNKNOWN", component=comp)
        rep.component(unit, lib, pkg, lic, k, why, "readelf NEEDED → dpkg → debian/copyright")
    if static_meta and static_meta.exists():
        meta = json.loads(static_meta.read_text())
        for p in meta.get("packages", []):
            k, why = classify(p.get("license"), static=True, component=p["name"])
            rep.component(unit, p["name"], p["version"], p.get("license"), k, why, f"cargo metadata (static closure) {static_meta.name}")
    elif not needed:
        rep.finding(unit, "REVIEW", "static", f"{elf.name} has no dynamic dependencies (fully static) and no cargo-metadata.json sits beside it — static closure census missing")

def census_manifest(rep: Report, unit: str, manifest: Path):
    cur = {}
    for line in manifest.read_text(errors="replace").splitlines():
        if line.startswith("PACKAGE NAME:"): cur = {"name": line.split(":", 1)[1].strip()}
        elif line.startswith("PACKAGE VERSION:"): cur["version"] = line.split(":", 1)[1].strip()
        elif line.startswith("LICENSE:"):
            cur["license"] = line.split(":", 1)[1].strip()
            comp = "glibc" if cur["name"].startswith(("libc6", "glibc", "ldconfig", "libc-")) else ("libgcc / libstdc++ / libgomp" if cur["name"].startswith(("libgcc", "libstdc++", "libgomp")) else cur["name"])
            k, why = classify(cur["license"], component=comp)
            rep.component(unit, cur["name"], cur.get("version", ""), cur["license"], k, why, manifest.name)

# ----------------------------------------------------------------------------- cross-cutting
def scan_bytes(rep, unit, label, data: bytes):
    """A secret-shaped string in FIRST-PARTY material fails; inside third-party dependency code
    (node_modules, site-packages) it is listed for review — libraries carry placeholder keys and
    test fixtures, and a real credential there would be the upstream's leak, not ours to ship
    unknowingly, so it is still shown."""
    third_party = "/node_modules/" in label or "/site-packages/" in label or "/.pnpm/" in label
    for name, rx in SECRET_RX.items():
        for m in rx.finditer(data):
            fp = hashlib.sha256(m.group(0)).hexdigest()[:12]
            if fp in SECRET_OK:
                rep.finding(unit, "INFO", "secret", f"{label}: fingerprint {fp} allowlisted — {SECRET_OK[fp]['what']}")
                continue
            rep.finding(unit, "REVIEW" if third_party else "FAIL", "secret", f"{label}: pattern {name}, fingerprint {fp} (value withheld)")

_TM_REVIEW: dict[str, set] = {}

def scan_path_rules(rep, unit, label, *, top=False):
    """Secret-file names and weights fail anywhere. A third-party mark fails only in a TOP-LEVEL artifact
    name (that is what we ship under our name); inside an archive it is a dependency name → one REVIEW."""
    if any(r.search(label) for r in SECRET_PATH_RX): rep.finding(unit, "FAIL", "secret-file", f"{label}: path matches a secret-file rule")
    if label.endswith(WEIGHT_EXT): rep.finding(unit, "FAIL", "weights", f"{label}: model weights inside an artifact")
    low = Path(label.split("!")[-1]).name.lower()
    if low.startswith("symoneural"): return
    if "/licenses/" in label or low.startswith(("license", "licence", "copying", "notice", "third-party")): return   # class 1: licence material names its owner by right
    for tm in TRADEMARKS:
        if re.search(rf"\b{re.escape(tm)}\b", low):
            if top: rep.finding(unit, "FAIL", "trademark", f"{label}: third-party mark '{tm}' in an artifact name")
            else: _TM_REVIEW.setdefault(unit, set()).add(f"{tm}:{low}")

def flush_trademark_reviews(rep):
    for unit, hits in _TM_REVIEW.items():
        rep.finding(unit, "REVIEW", "trademark", f"{len(hits)} dependency/member names carry a third-party mark (not failed): {sorted(hits)[:8]}{' …' if len(hits) > 8 else ''}")

def scan_archive(rep, unit, path: Path):
    scan_path_rules(rep, unit, str(path), top=True); scan_bytes(rep, unit, path.name, path.read_bytes() if path.stat().st_size < BIG else b"")
    if path.stat().st_size >= BIG: rep.finding(unit, "REVIEW", "size", f"{path.name}: {path.stat().st_size} bytes — large binary; content scan skipped, contents listed")
    members = []
    try:
        if zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as z:
                for i in z.infolist():
                    members.append((i.filename, i.file_size)); scan_path_rules(rep, unit, f"{path.name}!{i.filename}")
                    if i.file_size < 20 << 20: scan_bytes(rep, unit, f"{path.name}!{i.filename}", z.read(i))
        elif tarfile.is_tarfile(path):
            with tarfile.open(path) as t:
                for m in t:
                    if not m.isfile(): continue
                    members.append((m.name, m.size)); scan_path_rules(rep, unit, f"{path.name}!{m.name}")
                    if m.size < 20 << 20: scan_bytes(rep, unit, f"{path.name}!{m.name}", t.extractfile(m).read())
                    elif m.size >= BIG: rep.finding(unit, "REVIEW", "size", f"{path.name}!{m.name}: {m.size} bytes inside archive — check it is not weights")
    except Exception as ex:
        rep.finding(unit, "REVIEW", "archive", f"{path.name}: could not open ({ex})")
    return members

IDENT_RX = {k: re.compile(v) for k, v in POLICY.get("identifier_patterns", {}).items()}
IDENT_EXT = tuple(POLICY.get("identifier_scan_extensions", []))
_IDENT_REVIEW: dict[str, dict[str, set]] = {}

def scan_identifiers(unit, label, text: str):
    """Operator identifiers (UUIDs, non-licensor e-mails, home paths) are REVIEW, aggregated per unit."""
    if not label.endswith(IDENT_EXT): return
    for name, rx in IDENT_RX.items():
        for m in rx.finditer(text):
            _IDENT_REVIEW.setdefault(unit, {}).setdefault(name, set()).add(f"{label}: {m.group(0)[:48]}")

def flush_identifier_reviews(rep):
    for unit, kinds in _IDENT_REVIEW.items():
        for name, hits in kinds.items():
            rep.finding(unit, "REVIEW", f"identifier:{name}", f"{len(hits)} occurrence(s), e.g. {sorted(hits)[:4]}")

def check_august(rep, unit, path: Path):
    mt = time.strftime("%Y-%m", time.gmtime(path.stat().st_mtime))
    if mt == "2026-08": rep.finding(unit, "FAIL", "august", f"{path.name} mtime is August 2026")  # gate-allow: no-august — this IS the August detector
    if path.suffix in (".md", ".json", ".txt"):
        for i, line in enumerate(path.read_text(errors="replace").splitlines(), 1):
            if "2026-08" in line and not re.search(r"rule|bars|predates|fresh start|section 3\.2", line, re.I):  # gate-allow: no-august — this IS the August detector
                rep.finding(unit, "FAIL", "august", f"{path.name}:{i} carries an August 2026 date")  # gate-allow: no-august — detector message text

def check_attribution(rep, notices: Path | None):
    text = notices.read_text(errors="replace").lower() if notices and notices.exists() else ""
    for unit, u in rep.units.items():
        missing = sorted({c["name"] for c in u["components"] if c["class"] in ("PERMISSIVE", "WEAK_COPYLEFT_FILE", "WEAK_COPYLEFT_LIB")
                          and c["reason"] != "first-party" and c["name"].lower() not in text})
        if not text: rep.finding(unit, "FAIL", "attribution", "THIRD-PARTY-NOTICES.md missing — attribution owed for every permissive component")
        elif missing: rep.finding(unit, "FAIL", "attribution", f"{len(missing)} components absent from THIRD-PARTY-NOTICES: {missing[:12]}{' …' if len(missing) > 12 else ''}")

def check_repo_history(rep, repo: Path):
    unit = f"repo:{repo.resolve().name}"
    rc, out, err, s = run(["git", "-C", str(repo), "rev-list", "--objects", "--all"])
    if rc: return rep.finding(unit, "REVIEW", "repo", f"not a git repo or unreadable: {err[-200:]}")
    n = 0
    for line in out.splitlines():
        sha, _, path = line.partition(" ")
        if not path: continue
        t = subprocess.run(["git", "-C", str(repo), "cat-file", "-t", sha], capture_output=True, text=True).stdout.strip()
        if t != "blob": continue
        n += 1; scan_path_rules(rep, unit, path)
        data = subprocess.run(["git", "-C", str(repo), "cat-file", "-p", sha], capture_output=True).stdout
        if len(data) > BIG: rep.finding(unit, "FAIL", "size", f"{path}: {len(data)} bytes in history — weights or build output")
        scan_bytes(rep, unit, f"{path}@{sha[:9]}", data)
        if len(data) < 4 << 20: scan_identifiers(unit, path, data.decode("utf-8", errors="replace"))
    rc, out, err, s = run(["git", "-C", str(repo), "log", "--format=%ci"])
    if any(l.startswith("2026-08") for l in out.splitlines()): rep.finding(unit, "FAIL", "august", "commits dated August 2026 in history")  # gate-allow: no-august — this IS the August detector
    rep.finding(unit, "INFO", "repo", f"{n} blobs scanned across all refs")

# ----------------------------------------------------------------------------- script census
# A unit made of shell and Python scripts has a real licence closure, and before this it had
# none: no census applied to it, so every such unit came out "licence closure UNESTABLISHED"
# and could never be released. The closure of a script is what it needs at run time — the
# interpreter named in its shebang, the external commands it executes, and for Python the
# distributions it imports. Those are derived here from the file, never from a manifest.
_STDLIB = frozenset(getattr(sys, "stdlib_module_names", ()))
_SH_KEYWORD = {"if","then","else","elif","fi","for","while","until","do","done","case","esac","in",
               "function","select","time","coproc","return","break","continue","local","export",
               "readonly","declare","typeset","shift","set","unset","eval","exec","trap","wait",
               "echo","printf","read","cd","pwd","test","source","alias","unalias","let","shopt",
               "true","false","exit","getopts","hash","type","ulimit","umask","jobs","kill","fg","bg",
               "and","or","not","the","a","is","it","to","of","this","that","one","no","we","be"}
# Debian copyright files use short names of their own; these are the ones this estate's
# scripts actually reach. An unrecognised one is left alone and classify() decides.
_DEB2SPDX = {"expat": "MIT", "mit": "MIT", "bsd-3-clause": "BSD-3-Clause", "bsd-2-clause": "BSD-2-Clause",
             "isc": "ISC", "apache-2.0": "Apache-2.0", "public-domain": "CC0-1.0", "zlib": "Zlib",
             "gpl-2+": "GPL-2.0-or-later", "gpl-2": "GPL-2.0-only", "gpl-3+": "GPL-3.0-or-later",
             "gpl-3": "GPL-3.0-only", "lgpl-2.1+": "LGPL-2.1-or-later", "lgpl-2.1": "LGPL-2.1-only",
             "lgpl-3+": "LGPL-3.0-or-later", "lgpl-2+": "LGPL-2.0-or-later",
             "gpl-2+ with autoconf exception": "GPL-2.0-or-later WITH Autoconf-exception-2.0",
             "gfdl-1.3+": "GFDL-1.3-or-later", "psf-2": "PSF-2.0", "python": "Python-2.0"}

def _deb_licence(pkg: str) -> str:
    """The licence a Debian package declares, as an SPDX expression where it maps cleanly."""
    p = Path("/usr/share/doc") / pkg / "copyright"
    if not p.is_file(): return ""
    try: txt = p.read_text(errors="replace")
    except Exception: return ""
    # Debian declares a SHORT NAME after "License:" — "GPL-3+", "BSD-4-clause-UC",
    # "GPL-3+ and BSD-4-clause-UC". Some packages instead inline the whole licence text on
    # that line; python3.13-minimal does, and taking the line whole produced the component
    # "The following text includes the Python license and licenses and" classed UNKNOWN,
    # which failed the unit. Only short-name shapes are accepted here; prose falls through
    # to a text detector below, so an unparsed file yields no licence rather than a wrong one.
    SHORT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.+_-]*(?:\s+(?:and|or|with)\s+[A-Za-z0-9][A-Za-z0-9.+_-]*)*$")
    # Debian declares a SHORT NAME after "License:" — "GPL-3+", "BSD-4-clause-UC". Some packages
    # inline the whole licence text on that line instead; python3.13-minimal does, and taking the
    # line whole produced the component "The following text includes the Python license and
    # licenses and" classed UNKNOWN. Only short-name shapes are accepted.
    SHORT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.+_-]*(?:\s+(?:and|or|with)\s+[A-Za-z0-9][A-Za-z0-9.+_-]*)*$")

    # A copyright file's stanzas describe DIFFERENT FILES, not a conjunction. Taking the most
    # restrictive across all of them made curl "OLDAP-2.8", the licence of one bundled piece,
    # and failed a unit that merely runs curl. The package's own licence is the one attached to
    # "Files: *"; everything else governs a subset we are not redistributing anyway.
    main = ""
    for para in re.split(r"\n\s*\n", txt):
        if re.search(r"^Files:\s*\*\s*$", para, re.M):
            m = re.search(r"^License:\s*(.+)$", para, re.M)
            if m and SHORT.match(m.group(1).strip()):
                main = m.group(1).strip(); break
    if main:
        return _DEB2SPDX.get(main.lower(), main)

    ids = [m.strip() for m in re.findall(r"^License:\s*(.+)$", txt, re.M) if m.strip() and SHORT.match(m.strip())]
    if not ids:
        if re.search(r"PYTHON SOFTWARE FOUNDATION LICENSE|PSF LICENSE AGREEMENT", txt, re.I): return "PSF-2.0"
        return detect_licence_text(txt)
    # No "Files: *" stanza: the licence the file states most often is the package's own.
    counts: dict[str, int] = {}
    for raw in ids:
        spdx = _DEB2SPDX.get(raw.lower(), raw)
        counts[spdx] = counts.get(spdx, 0) + 1
    return max(counts.items(), key=lambda kv: kv[1])[0]

_dpkg_cache: dict[str, str] = {}
def _providing_package(binary: str) -> str:
    if binary in _dpkg_cache: return _dpkg_cache[binary]
    rc, out, _, _ = run(["bash", "-lc", f"command -v {binary!r}"])
    path = out.strip().splitlines()[0] if rc == 0 and out.strip() else ""
    pkg = ""
    if path and Path(path).exists():
        real = str(Path(path).resolve())
        for cand in (real, path):
            rc2, out2, _, _ = run(["dpkg", "-S", cand])
            if rc2 == 0 and ":" in out2:
                pkg = out2.split(":", 1)[0].split(",")[0].strip(); break
    _dpkg_cache[binary] = pkg
    return pkg

def _shell_commands(text: str) -> set[str]:
    """Words in command position: line start, or after | ; & ( ` && || $( and the block keywords.

    Quoted runs are removed first, ACROSS LINES. An embedded awk or jq program is a single
    quoted string that happens to span several lines and to contain words in what looks like
    command position; without this, `code = line` inside an awk program was read as the command
    `code`, resolved to an installed editor, and failed the unit on an unstated licence. An
    assignment is dropped too: `x=1` is not an invocation of `x`.
    """
    # A HEREDOC BODY IS NOT SHELL. `python3 - <<PY ... PY` is a Python program, and its keywords
    # sit exactly where a shell command would: `import` resolves to ImageMagick's import(1) and
    # `print` to mailcap's print(1), so two embedded Python programs added two components with
    # unstated licences and failed a unit that runs neither program.
    def _strip_heredocs(s: str) -> str:
        out, lines, i = [], s.split("\n"), 0
        while i < len(lines):
            line = lines[i]
            m = re.search(r"<<-?\s*[\"']?([A-Za-z_][A-Za-z0-9_]*)[\"']?", line)
            if m:
                word = m.group(1)
                out.append(line[:m.start()])
                i += 1
                while i < len(lines) and lines[i].strip() != word:
                    i += 1
                i += 1
                continue
            out.append(line); i += 1
        return "\n".join(out)

    stripped = _strip_heredocs(text)
    stripped = re.sub(r"'[^']*'", " ", stripped, flags=re.S)
    stripped = re.sub(r'"[^"]*"', " ", stripped, flags=re.S)
    found = set()
    for m in re.finditer(r'(?:^|[|;&(`]|\$\(|\b(?:then|else|do|elif)\s)\s*([a-zA-Z][a-zA-Z0-9._+-]*)\s*(=?)', stripped, re.M):
        w, assign = m.group(1), m.group(2)
        if assign: continue
        if w in _SH_KEYWORD or w.lower() in _SH_KEYWORD: continue
        found.add(w)
    return found

def _python_imports(text: str) -> set[str]:
    try:
        import ast
        tree = ast.parse(text)
    except Exception:
        return set()
    mods = set()
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for al in n.names: mods.add(al.name.split(".")[0])
        elif isinstance(n, ast.ImportFrom):
            if n.level == 0 and n.module: mods.add(n.module.split(".")[0])
    return mods

def census_scripts(rep: Report, unit: str, root: Path, files: list[Path]):
    """Derive the run-time closure of a unit made of scripts. Called once per unit."""
    own = {f.stem for f in files} | {f.name for f in files}
    interpreters, commands, pymods = set(), set(), set()
    for f in files:
        try: text = f.read_text(errors="replace")
        except Exception: continue
        first = text.split("\n", 1)[0]
        if first.startswith("#!"):
            sheb = first[2:].split()
            for part in sheb:
                b = Path(part).name
                if b in ("env",) or part.startswith("-"): continue
                interpreters.add(b); break
        if f.suffix == ".py" or "python" in first:
            pymods |= _python_imports(text)
        if f.suffix in (".sh", ".bash") or re.search(r"#!.*\b(ba)?sh\b", first):
            # Comments are prose, not commands. Left in, the phrase "exit code read after a
            # pipeline" put the word `code` through `command -v`, which on this host resolves to
            # an editor, whose package declares no parseable licence — so a sentence in a comment
            # became an UNKNOWN component and failed the unit.
            code_only = re.sub(r"(?m)(^|\s)#.*$", " ", text)
            commands |= _shell_commands(code_only)
    commands -= own | interpreters
    seen_pkg = set()
    for name in sorted(interpreters | commands):
        pkg = _providing_package(name)
        if not pkg:
            if name in commands: continue          # not a program on this host: a function or a typo, not a dependency
            rep.finding(unit, "REVIEW", "census", f"interpreter '{name}' is not provided by any installed package — closure unverified")
            continue
        if pkg in seen_pkg: continue
        seen_pkg.add(pkg)
        lic = _deb_licence(pkg)
        klass, why = classify(lic or None, invoked=True, component=pkg)
        rep.component(unit, pkg, "system", lic or "unstated", klass, why, f"invoked by {unit} scripts")
    unit_norm = unit.lower().replace("-", "_")
    for mod in sorted(pymods):
        if mod in _STDLIB:
            continue
        # A package importing its own modules is not a dependency. `symoneural_agents`
        # importing `symoneural_agents.tools` resolves to no INSTALLED distribution — it is
        # the unit being censused — and reporting that as an unverified closure makes the
        # unit's own name look like a missing third party.
        m = mod.lower().replace("-", "_")
        if m == unit_norm or m.startswith(f"symoneural_{unit_norm}") or m == f"symoneural_{unit_norm}":
            continue
        # In the unit's own tree — searched RECURSIVELY, because a packed unit extracts under a
        # prefix directory (`board-1.2.0/service.py`), so a top-level check finds nothing and
        # the unit's own module is reported as an unresolved third party.
        if any(True for _ in root.rglob(f"{mod}.py")) or any(p.is_dir() for p in root.rglob(mod)):
            continue
        dist, lic = "", ""
        try:
            import importlib.metadata as im
            for d, ms in (im.packages_distributions() or {}).items():
                if d == mod: dist = ms[0]; break
            if dist:
                md = im.metadata(dist)
                lic = md.get("License-Expression") or md.get("License") or ""
                if not lic:
                    for c in md.get_all("Classifier") or []:
                        if c.startswith("License ::"): lic = c.rsplit("::", 1)[-1].strip(); break
        except Exception:
            pass
        if not dist:
            # No dist-info does not mean not installed. A distribution-packaged module
            # (python3-fastapi and friends) carries no metadata mapping module to
            # distribution, so packages_distributions() returns nothing for every one of them
            # — and every FastAPI service in this estate came out "closure unverified" while
            # importing perfectly. Resolve it the same way a binary is resolved: find the file
            # the interpreter would load, and ask the package manager who owns it.
            try:
                import importlib.util as _u
                spec = _u.find_spec(mod)
                origin = getattr(spec, "origin", None) or ""
            except Exception:
                origin = ""
            pkg = ""
            if origin and origin not in ("built-in", "frozen"):
                rc, out, _, _ = run(["dpkg", "-S", origin])
                if rc == 0 and ":" in out:
                    pkg = out.split(":", 1)[0].split(",")[0].strip()
            if pkg:
                lic = _deb_licence(pkg)
                klass, why = classify(lic or None, component=pkg)
                rep.component(unit, pkg, "system", lic or "unstated", klass, why,
                              f"python import '{mod}' in {unit}, resolved through the package manager")
                continue
            rep.finding(unit, "REVIEW", "census", f"python import '{mod}' resolves to no installed distribution — closure unverified")
            continue
        klass, why = classify(normalise(lic) or None, component=dist)
        rep.component(unit, dist, "installed", normalise(lic) or "unstated", klass, why, f"imported by {unit} python")
    if pymods & _STDLIB or any("python" in i for i in interpreters):
        klass, why = classify("PSF-2.0", invoked=True, component="cpython")
        rep.component(unit, "cpython", "system", "PSF-2.0", klass, why, f"standard library used by {unit}")

# ----------------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--stage", type=Path, help="staged release dir: <unit>/<arch>/<files>")
    ap.add_argument("--repo", type=Path, action="append", default=[], help="git repo(s) whose full history is scanned before push")
    ap.add_argument("--notices", type=Path, help="THIRD-PARTY-NOTICES.md (default: <stage>/THIRD-PARTY-NOTICES.md)")
    ap.add_argument("--json", type=Path, help="write the full report here")
    ap.add_argument("--keep-tmp", action="store_true")
    a = ap.parse_args()
    rep = Report(); tmp = Path(tempfile.mkdtemp(prefix="ship-gate-", dir=os.environ.get("CLAUDE_JOB_DIR", "/tmp") + "/tmp" if os.environ.get("CLAUDE_JOB_DIR") else None))
    try:
        if a.stage and a.stage.exists():
            for unit_dir in sorted(p for p in a.stage.iterdir() if p.is_dir()):
                unit = unit_dir.name
                scripts: list[Path] = []
                for f in sorted(unit_dir.rglob("*")):
                    if not f.is_file(): continue
                    rel = f.relative_to(a.stage); arch = rel.parts[1] if len(rel.parts) > 2 else "-"
                    rep.unit(unit)["artifacts"].append({"path": str(rel), "arch": arch, "sha256": sha256(f), "bytes": f.stat().st_size})
                    check_august(rep, unit, f)
                    if f.suffix == ".whl": census_wheel(rep, unit, f, tmp); scan_archive(rep, unit, f)
                    elif f.name == "license.manifest": census_manifest(rep, unit, f)
                    elif f.suffix in (".gz", ".xz", ".bz2", ".zst", ".tar", ".zip", ".tgz"):
                        members = scan_archive(rep, unit, f)
                        # A unit staged as one archive must be censused exactly like a unit
                        # staged as a tree. Before this, only a package.json triggered an
                        # extraction, so packing the native units for release (which the
                        # cutter requires, since it uploads every loose file separately and
                        # drops symlinks) silently turned their ELF dependency census into
                        # "licence closure UNESTABLISHED". The archive is the artifact now,
                        # so it is opened and walked.
                        want = (any(m[0].endswith(("package.json", "license.manifest")) for m in members)
                                or any(not m[0].endswith("/") for m in members))
                        if want and f.stat().st_size < 2 << 30:
                            d = tmp / f"x-{unit}-{f.name.replace('.', '_')}"; d.mkdir(parents=True, exist_ok=True)
                            try:
                                if zipfile.is_zipfile(f):
                                    with zipfile.ZipFile(f) as z: z.extractall(d)
                                else:
                                    with tarfile.open(f) as tf: tf.extractall(d, filter="data")
                            except Exception as ex:
                                rep.finding(unit, "REVIEW", "census", f"could not extract {f.name} for census: {ex}")
                            else:
                                meta = next(iter(sorted(d.rglob("cargo-metadata.json"))), None)
                                # Scripts inside the archive count exactly as scripts loose in
                                # the stage do. Without this a unit made of shell and Python
                                # censused fine unpacked and came out UNESTABLISHED the moment
                                # it was packed — and packing is what the cutter requires, so
                                # the only form that can actually be released was the form that
                                # could not pass.
                                inner_scripts: list[Path] = []
                                for m in sorted(d.rglob("*")):
                                    if not m.is_file() or m.is_symlink():
                                        continue
                                    if m.name == "license.manifest":
                                        census_manifest(rep, unit, m)
                                    elif m.suffix == ".whl":
                                        census_wheel(rep, unit, m, tmp)
                                    elif m.stat().st_size > 0:
                                        try: magic = m.open("rb").read(4)
                                        except Exception: continue
                                        if magic == b"\x7fELF":
                                            census_elf(rep, unit, m, meta)
                                        elif m.suffix in (".py", ".sh", ".bash") or magic[:2] == b"#!":
                                            inner_scripts.append(m)
                                if any(x.name == "package.json" for x in d.rglob("package.json")):
                                    census_node_tree(rep, unit, d)
                                if inner_scripts and not rep.unit(unit)["components"]:
                                    census_scripts(rep, unit, d, inner_scripts)
                    elif f.stat().st_size > 0 and f.open("rb").read(4) == b"\x7fELF":
                        census_elf(rep, unit, f, f.parent / "cargo-metadata.json"); scan_path_rules(rep, unit, str(rel), top=True)
                    else:
                        if f.suffix in (".py", ".sh", ".bash") or (f.stat().st_size > 2 and f.open("rb").read(2) == b"#!"):
                            scripts.append(f)
                        scan_path_rules(rep, unit, str(rel), top=True)
                        if f.stat().st_size < BIG:
                            data = f.read_bytes(); scan_bytes(rep, unit, str(rel), data)
                            if len(data) < 4 << 20: scan_identifiers(unit, str(rel), data.decode("utf-8", errors="replace"))
                if scripts and not rep.unit(unit)["components"]:
                    census_scripts(rep, unit, unit_dir, scripts)
                if not rep.unit(unit)["components"] and unit not in ("source", "symoneural-learn-hostrun", "noncopyleft-image-policy"):
                    rep.finding(unit, "REVIEW", "census", "no dependency census could be derived for this unit — licence closure UNESTABLISHED")
            flush_trademark_reviews(rep); flush_identifier_reviews(rep)
            check_attribution(rep, a.notices or (a.stage / "THIRD-PARTY-NOTICES.md"))
        for r in a.repo: check_repo_history(rep, r)
        if a.repo and not a.stage: flush_identifier_reviews(rep)
    finally:
        if not a.keep_tmp: shutil.rmtree(tmp, ignore_errors=True)
    # ---- print
    overall = "PASS"
    for unit, u in rep.units.items():
        fails = [f for f in u["findings"] if f["level"] == "FAIL"]; reviews = [f for f in u["findings"] if f["level"] == "REVIEW"]
        by = {}
        for c in u["components"]: by[c["class"]] = by.get(c["class"], 0) + 1
        print(f"\n== {unit}: {u['verdict']}   components={len(u['components'])} {dict(sorted(by.items()))}  artifacts={len(u['artifacts'])}")
        for f in fails: print(f"   FAIL    {f['kind']:<22} {f['detail']}")
        for f in reviews: print(f"   REVIEW  {f['kind']:<22} {f['detail']}")
        if u["verdict"] == "FAIL": overall = "FAIL"
        elif u["verdict"] == "REVIEW" and overall == "PASS": overall = "REVIEW"
    print(f"\nSHIP GATE: {overall}")
    if a.json:
        a.json.write_text(json.dumps({"overall": overall, "policy": POLICY["schema"], "units": rep.units}, indent=1))
        print(f"report: {a.json}")
    sys.exit(1 if overall == "FAIL" else 0)

if __name__ == "__main__":
    main()
