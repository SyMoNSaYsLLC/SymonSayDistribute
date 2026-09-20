# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
# SyMoNsAyLeaRn — SyMoNeuRaL, a subdivision of SymonSaysLLC. Terms: see LICENSE.
"""What a serving runtime actually offers, asked of the runtime rather than of its docs.

WHY THIS IS NOT A DOCUMENTATION LOOKUP
--------------------------------------
Finding which tool-call parsers a vLLM offers took, on 2026-09-19: a failed import of
`vllm.entrypoints.openai.tool_parsers` (moved in this version), an empty registry (parsers
register lazily, so importing the package lists nothing), an rglob for files called
`*tool_parser*`, and finally reading the lazy-module dict out of `__init__.py` by line number.

The answer — `openai` and `openai_gptoss` — is three lines of a dict. Every step to reach it was
version-specific, and the documentation for a different version would have been confidently
wrong. So this reads the installed package, in its own interpreter, and reports what is there.

Nothing here imports the serving runtime into THIS process. A probe that needs the thing it is
probing already loaded is a probe that cannot describe a broken environment, which is the one
time it is most needed.
"""
from __future__ import annotations

import ast
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

from .device import ProbeError, _venv_python, build, devices

VENV_ROOTS = ["/home/google/.venvs", "/home/google", "/opt"]


def venvs() -> list[dict[str, Any]]:
    """Python environments on this host, with their interpreter version."""
    out = []
    seen: set[str] = set()
    for root in VENV_ROOTS:
        r = Path(root)
        if not r.is_dir():
            continue
        for cfg in list(r.glob("*/pyvenv.cfg")) + list(r.glob("*/*/pyvenv.cfg")):
            v = cfg.parent
            if str(v) in seen:
                continue
            seen.add(str(v))
            ver = ""
            for line in cfg.read_text(errors="replace").splitlines():
                if line.lower().startswith("version"):
                    ver = line.split("=", 1)[-1].strip()
            out.append({"venv": str(v), "python": ver,
                        "has_python": (v / "bin" / "python").exists()})
    return sorted(out, key=lambda d: d["venv"])


_PKGS = r'''
import json
from importlib.metadata import distributions
rows = []
for d in distributions():
    try:
        rows.append({"name": d.metadata["Name"], "version": d.version})
    except Exception:
        pass
print(json.dumps(sorted([r for r in rows if r["name"]], key=lambda r: (r["name"] or "").lower())))
'''


def packages(venv: str | Path, contains: str = "") -> list[dict[str, str]]:
    """Installed distributions and versions, read from the environment's own metadata."""
    py = _venv_python(venv)
    r = subprocess.run([str(py), "-c", _PKGS], capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise ProbeError(f"listing packages in {venv} failed rc={r.returncode}: "
                         f"{r.stderr.strip()[-200:]}")
    rows = json.loads(r.stdout.strip().splitlines()[-1])
    if contains:
        c = contains.lower()
        rows = [x for x in rows if c in (x["name"] or "").lower()]
    return rows


def _lazy_registry(pkg_init: Path) -> list[str]:
    """Read the names out of a lazy-registration dict without importing anything.

    vLLM registers parsers as {name: (module, class)} in a package __init__. Importing the
    package does NOT populate the manager — that is what made this hard to find by hand — so
    the names are parsed out of the source instead. Static reading also means a package that
    cannot import still reports what it would offer.
    """
    if not pkg_init.is_file():
        return []
    try:
        tree = ast.parse(pkg_init.read_text(errors="replace"))
    except SyntaxError:
        return []
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values):
                if (isinstance(k, ast.Constant) and isinstance(k.value, str)
                        and isinstance(v, ast.Tuple) and len(v.elts) == 2
                        and all(isinstance(e, ast.Constant) for e in v.elts)):
                    names.add(k.value)
    return sorted(names)


def parsers(venv: str | Path) -> dict[str, Any]:
    """Which tool-call and reasoning parsers a serving runtime offers, by registered NAME.

    The registered name is what a launcher flag takes. A file name is not it: the parser in
    `gptoss_tool_parser.py` is selected as `openai`, and guessing from the filename gives a
    flag the server rejects.
    """
    py = _venv_python(venv)
    r = subprocess.run([str(py), "-c",
                        "import vllm,pathlib;print(pathlib.Path(vllm.__file__).parent)"],
                       capture_output=True, text=True, timeout=120)
    if r.returncode != 0:
        raise ProbeError(f"{venv} has no importable vllm: {r.stderr.strip()[-200:]}")
    root = Path(r.stdout.strip().splitlines()[-1])
    ver = subprocess.run([str(py), "-c", "import vllm;print(vllm.__version__)"],
                         capture_output=True, text=True, timeout=120).stdout.strip()

    tool = _lazy_registry(root / "tool_parsers" / "__init__.py") or \
        _lazy_registry(root / "entrypoints" / "openai" / "tool_parsers" / "__init__.py")
    reason = _lazy_registry(root / "reasoning" / "__init__.py")
    return {
        "venv": str(venv), "runtime": "vllm", "version": ver, "package_root": str(root),
        "tool_call_parsers": tool, "reasoning_parsers": reason,
        "counts": {"tool_call": len(tool), "reasoning": len(reason)},
        "read_how": "parsed statically out of the lazy-registration dicts; importing the "
                    "package does not populate the manager, which is what makes these hard "
                    "to find by hand",
    }


def suggest(venv: str | Path, model_dir: str) -> dict[str, Any]:
    """Which parser names suit a checkpoint, and the evidence for the guess.

    It says `candidates`, never `answer`. Matching a checkpoint to a parser is a judgement, and
    a wrong flag is rejected loudly by the server, which is the right place to find out — better
    than this module asserting one and being believed.
    """
    p = parsers(venv)
    name = Path(model_dir).name.lower()
    cfg = Path(model_dir) / "config.json"
    arch = ""
    if cfg.is_file():
        try:
            arch = " ".join(json.loads(cfg.read_text()).get("architectures", [])).lower()
        except Exception:
            arch = ""
    hay = f"{name} {arch}"
    hints = {"gpt-oss": ("openai", "openai_gptoss"), "gptoss": ("openai", "openai_gptoss"),
             "mistral": ("mistral", None), "hermes": ("hermes", None),
             "deepseek": ("deepseek_v3", "deepseek_r1"), "qwen": ("hermes", "qwen3_engine")}
    hit = next((v for k, v in hints.items() if k in hay), None)
    return {
        "model_dir": model_dir, "matched_on": hay.strip() or "(nothing readable)",
        "candidates": {
            "tool_call_parser": hit[0] if hit and hit[0] in p["tool_call_parsers"] else None,
            "reasoning_parser": hit[1] if hit and hit[1] in p["reasoning_parsers"] else None,
        },
        "available": {"tool_call": p["tool_call_parsers"], "reasoning": p["reasoning_parsers"]},
        "caveat": "candidates, not an answer. A wrong parser name is rejected by the server at "
                  "start-up, which is a better place to learn it than here.",
    }


# ============================================================================================
# §3.1b-iii — what this probe invokes, against what the estate recorded it should be
# ============================================================================================
# Every other module here exists to stop somebody believing a stale number. `devices()` refuses
# to let a compute capability be read as a CUDA version; `fit()` refuses to let a `cu130` in a
# directory name stand for "runs on this card". Both of those answers come out of programs this
# estate did not write — nvidia-smi, a CPython, a torch, a vLLM — and until now the probe
# reported their output without ever asking what version produced it.
#
# That is the one failure this unit is least entitled to. A probe whose own inputs can move
# underneath it reports yesterday's machine with today's confidence.
#
# WHY THIS LIVES HERE AND NOT IN ITS OWN MODULE
# It was written as `pins.py` first. `no-divergent-copy` refused every commit in the estate for
# it — the gate compares by BASENAME across all four trees, and a second component carrying the
# same obvious filename is exactly the divergence it exists to catch. It sits in runtime.py
# rather than device.py because runtime.py already depends on device.py, so the census can read
# the card AND the build without a circular import.
#
# WHAT IS ASSERTED AND WHAT IS NAMED
# nvidia-smi, torch and vLLM have pins and are compared against them. The CUDA toolkit and the
# venv interpreter have no pin anywhere in SymonSaySource, so they are NAMED as gaps rather
# than omitted — an omitted program reads as one with nothing to check.
#
# DRIFT IS PRESERVED, NOT RESOLVED
# A pin records the INTENDED reproducible revision; a checkout records the OBSERVED one. Where
# they disagree, neither is edited to match the other — provenance settles that.

PIN_ROOT = os.environ.get("SYM_PIN_ROOT", "/mnt/SymonSaySource")

_VERSION_RE = re.compile(r"\d+(?:\.\d+)+")

# Every program or library this unit reads a version out of, and the component SymonSaySource
# pins it under. `pin: None` is a GAP, listed rather than dropped.
INVOKED: tuple[dict[str, Any], ...] = (
    {"program": "nvidia-smi", "reads": "driver_version",
     "where": "device._nvidia_smi() — every field devices() and fit() report about the card",
     "pin": "open-gpu-kernel-modules",
     "pin_note": "that pin's component is the open GPU KERNEL MODULE source; nvidia-smi is "
                 "driver userspace. They ship on one release train and the strings are "
                 "identical — `nvidia-smi --version` reports the same KMD version — which is "
                 "why this pin governs it. Said plainly rather than assumed, because the pin "
                 "does not nominally name the binary being asserted."},
    {"program": "torch", "reads": "torch.__version__",
     "where": "device.build() — the compiled arch_list that fit() decides `runs_here` from",
     "pin": "pytorch",
     "pin_note": "pinned at SymonSaySource/common/pins/pytorch.json. A second pin, "
                 "adaptive-fabric/pins/torch-2.11.x.json, records a 2.11.x line as "
                 "UNRESOLVED; it names no version, so it cannot be compared against."},
    {"program": "vllm", "reads": "vllm.__version__",
     "where": "runtime.parsers() — the registered parser names, which are version-specific "
              "and are exactly what a launcher flag takes",
     "pin": "vllm",
     "pin_note": "pinned at SymonSaySource/llm/pins/vllm.json."},
    {"program": "cuda", "reads": "torch.version.cuda",
     "where": "device.build() — reported as `cuda_built_against`, and named in fit()'s "
              "'these_are_not_the_same_number'",
     "pin": None,
     "pin_note": "GAP: SymonSaySource has no pin for the CUDA toolkit. This unit's whole "
                 "point is that the toolkit version and the card's compute capability are "
                 "different numbers, and one of the two has no record at all. Closed by a "
                 "cuda-toolkit pin under SymonSaySource."},
    {"program": "python", "reads": "interpreter",
     "where": "device._venv_python() — the interpreter every probe in this unit is run in",
     "pin": None,
     "pin_note": "GAP: SymonSaySource has no pin for CPython. Closed by a cpython pin under "
                 "SymonSaySource."},
)

# Drift measured on disk on 2026-09-20 and PRESERVED. Key is
# (program, normalised pin, normalised observed). Nothing here was resolved by editing a pin
# or by moving a checkout — see the §3.1b-iii banner above.
KNOWN_DRIFT: dict[tuple[str, str, str], str] = {
    ("torch", "2.14.0", "2.13.0"):
        "2026-09-20: the pin records v2.14.0; ~/.venvs/vllm-0271-cu130 carries 2.13.0+cu130. "
        "The +cu130 is a build tag, not a release, and is not what differs. Preserved rather "
        "than reconciled: provenance decides which of the two moves.",
    ("torch", "2.14.0", "2.11.0"):
        "2026-09-20: ~/.venvs/vllm carries 2.11.0+cu130 against the same v2.14.0 pin. This is "
        "the line adaptive-fabric/pins/torch-2.11.x.json was opened for and left UNRESOLVED.",
    ("vllm", "0.29.0", "0.27.1"):
        "2026-09-20: the pin records v0.29.0; ~/.venvs/vllm-0271-cu130 carries 0.27.1. The "
        "parser names this unit reports are properties of 0.27.1, which is why the version is "
        "carried in the same response as the names.",
    ("vllm", "0.29.0", "0.25.1"):
        "2026-09-20: ~/.venvs/vllm carries 0.25.1 against the same v0.29.0 pin — an older "
        "environment than the one probed by default, kept and therefore recorded.",
}


def _norm(v: str) -> str:
    """A version reduced to its dotted numeric core, so `v0.29.0` and `0.29.0+cu130` compare as
    one release. Empty when there is no number — reported as unreadable, not as disagreement."""
    m = _VERSION_RE.search(v or "")
    return m.group(0) if m else ""


def _pins() -> dict[str, dict[str, Any]]:
    """Every pin SymonSaySource records, by component name. Read off disk, never assumed."""
    out: dict[str, dict[str, Any]] = {}
    root = Path(PIN_ROOT)
    if not root.is_dir():
        return out
    for f in root.rglob("*.json"):
        s = str(f)
        if "/.git/" in s or "/pins/" not in s:
            continue
        try:
            d = json.loads(f.read_text())
        except Exception:
            continue
        c = d.get("component")
        if c:
            out[str(c).lower()] = {**d, "pin_file": s}
    return out


def _interpreter_version(venv: str | Path) -> str:
    """What the venv's own interpreter says it is. An argument vector, never a shell."""
    try:
        py = _venv_python(venv)
    except ProbeError as e:
        return f"could not run: {e}"
    try:
        r = subprocess.run([str(py), "--version"], capture_output=True, text=True,
                           timeout=30, stdin=subprocess.DEVNULL, check=False)
    except Exception as e:
        return f"could not run: {e}"
    if r.returncode != 0:
        return f"exited {r.returncode}"
    text = (r.stdout or "") + (r.stderr or "")
    return next((ln.strip() for ln in text.splitlines() if ln.strip()), "")


def _observed(venv: str | Path) -> dict[str, str]:
    """The version string each invoked thing reports about ITSELF, read by running it.

    Each source is guarded on its own: a venv with no importable vLLM must still yield a torch
    and a driver answer. A failure that takes the whole census with it would turn one missing
    package into "nothing is checked", which is the silence this module exists to break.
    """
    out: dict[str, str] = {}
    try:
        devs = devices()
        out["nvidia-smi"] = devs[0]["driver_version"] if devs else "no device reported"
    except ProbeError as e:
        out["nvidia-smi"] = f"could not run: {e}"
    try:
        b = build(venv)
        out["torch"] = b.get("torch") or b.get("error") or ""
        out["cuda"] = b.get("cuda_built_against") or ""
    except ProbeError as e:
        out["torch"] = out["cuda"] = f"could not run: {e}"
    try:
        out["vllm"] = parsers(venv).get("version") or ""
    except ProbeError as e:
        out["vllm"] = f"could not run: {e}"
    out["python"] = _interpreter_version(venv)
    return out


def pinned(venv: str | Path) -> dict[str, Any]:
    """Does every version this probe's answers rest on agree with what the estate recorded?

    Per-venv, because the card is one thing and the build is another: the driver row is the
    same whichever venv is asked, and the torch and vLLM rows are not. Folding them into one
    module-level answer would make the build rows true of one environment and quietly wrong
    about every other.
    """
    obs = _observed(venv)
    pins = _pins()
    rows, states = [], {}
    for spec in INVOKED:
        program = spec["program"]
        reported = obs.get(program, "")
        observed = "" if reported.startswith(("could not run", "exited")) else _norm(reported)
        pin = pins.get((spec["pin"] or "").lower()) if spec["pin"] else None
        want = str(pin.get("intended_tag_version") or "") if pin else ""
        wanted = _norm(want)

        if pin is None:
            state, why = "NO-PIN", spec["pin_note"]
        elif not wanted or want.upper().startswith("UNRESOLVED"):
            state, why = "UNRESOLVED-PIN", f"the pin records {want!r}, which names no version"
        elif not observed:
            state, why = "UNREADABLE", f"no version could be read: {reported or 'nothing'}"
        elif observed == wanted:
            state, why = "MATCHES", f"reports {observed}, which is what {pin['pin_file']} records"
        elif (program, wanted, observed) in KNOWN_DRIFT:
            state, why = "DRIFT-RECORDED", KNOWN_DRIFT[(program, wanted, observed)]
        else:
            state, why = "DRIFT-NEW", (
                f"the pin records {want!r} and this host has {observed!r}. That movement is in "
                f"no KNOWN_DRIFT entry, so it happened after the last time anyone looked.")

        rows.append({"program": program, "reads": spec["reads"], "where": spec["where"],
                     "reports": reported, "observed": observed,
                     "pin": spec["pin"], "pin_file": pin.get("pin_file") if pin else None,
                     "pinned": want or None, "state": state, "why": why,
                     "pin_note": spec["pin_note"]})
        states.setdefault(state, []).append(program)

    return {"venv": str(venv), "pin_root": PIN_ROOT, "pins_available": len(pins),
            "count": len(rows), "programs": rows,
            "by_state": {k: sorted(v) for k, v in states.items()},
            "unpinned": sorted(states.get("NO-PIN", [])),
            "recorded_drift": sorted(states.get("DRIFT-RECORDED", [])),
            "new_drift": sorted(states.get("DRIFT-NEW", [])),
            "why": ("every version this probe rests on agrees with its pin"
                    if set(states) <= {"MATCHES"} else
                    "; ".join(f"{k}: {', '.join(sorted(v))}" for k, v in sorted(states.items()))),
            "drift_policy": ("a pin records the INTENDED reproducible revision and a checkout "
                             "the OBSERVED one. Where they disagree the disagreement is "
                             "preserved and dated in KNOWN_DRIFT, never resolved by editing "
                             "the pin or moving the checkout. What this asserts is that no "
                             "version moved WITHOUT being recorded.")}
