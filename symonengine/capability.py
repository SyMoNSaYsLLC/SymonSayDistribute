# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
# SyMoNsAyLeaRn — SyMoNeuRaL, a subdivision of SymonSaysLLC. Terms: see LICENSE.
"""What a serving build can actually do, asked of the build.

WHY THIS IS NOT A FEATURE LIST IN A DOCUMENT
--------------------------------------------
A capability written down is correct for the version it was written against. vLLM 0.27.1
supports 367 model architectures and 31 quantization methods; the next version supports a
different set, and a document saying otherwise is confidently wrong at exactly the moment
somebody relies on it.

So this asks the installed build. Every number here was read out of the package that would
serve the request, in its own interpreter, and it is re-read every time.

THE QUESTION WORTH ASKING
-------------------------
Not "what does it support" in the abstract, but `serves(checkpoint)`: can THIS build serve THAT
checkpoint. That has a real answer — the architecture in the checkpoint's config either is in
the registry or is not, and its quantization either is in the method list or is not — and it is
the question that actually precedes a serving decision.

NOT DUPLICATED HERE
-------------------
Tool-call and reasoning parser names are capabilities of the same build, and symonprobe already
reads them. Asking twice in two components is how two answers start disagreeing, so this defers
to it rather than reimplementing it.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any


class CapabilityError(Exception):
    """A capability that could not be established, carrying why."""


_PROBE = r'''
import importlib.util
import json
out = {}
try:
    import vllm
    out["runtime"] = "vllm"
    out["version"] = vllm.__version__
except Exception as e:
    print(json.dumps({"error": "no vllm: %s" % e})); raise SystemExit
try:
    from vllm.model_executor.models.registry import ModelRegistry
    out["architectures"] = sorted(ModelRegistry.get_supported_archs())
except Exception as e:
    out["architectures_error"] = "%s: %s" % (type(e).__name__, e)
try:
    from vllm.model_executor.layers.quantization import QUANTIZATION_METHODS
    out["quantization"] = sorted(QUANTIZATION_METHODS)
except Exception as e:
    out["quantization_error"] = "%s: %s" % (type(e).__name__, e)
try:
    import torch
    out["torch"] = torch.__version__
    out["cuda_built_against"] = torch.version.cuda
    out["arch_list"] = list(torch.cuda.get_arch_list())
except Exception as e:
    out["torch_error"] = "%s: %s" % (type(e).__name__, e)
# Feature flags, asked by import — with EVERY path tried recorded beside the answer.
#
# The first version of this named one module per feature and reported three features absent
# that vllm 0.27.1 plainly has: they moved to vllm.v1.*. It also used find_spec, which RAISES
# when a parent package is missing rather than returning None, so "vllm.core is gone" was
# caught by an except and became "prefix caching is not supported".
#
# A capability report that says False when it looked in the wrong place is worse than one that
# says nothing, so every candidate path is recorded and a False can be checked.
CANDIDATES = {
    "lora": ["vllm.lora"],
    "prefix_caching": ["vllm.v1.core", "vllm.core.block.prefix_caching_block"],
    "speculative_decoding": ["vllm.v1.spec_decode", "vllm.spec_decode"],
    "structured_outputs": ["vllm.v1.structured_output",
                           "vllm.model_executor.guided_decoding"],
    "multimodal": ["vllm.multimodal"],
    "pooling": ["vllm.pooling_params"],
    "reasoning": ["vllm.reasoning"],
    "tool_parsing": ["vllm.tool_parsers"],
}
feat = {}
for name, paths in CANDIDATES.items():
    found = None
    for m in paths:
        try:
            if importlib.util.find_spec(m) is not None:
                found = m
                break
        except Exception:
            continue
    feat[name] = {"present": found is not None, "found_at": found, "looked_in": paths}
out["features"] = feat
print(json.dumps(out))
'''


def _venv_python(venv: str | Path) -> Path:
    p = Path(venv) / "bin" / "python"
    if not p.exists():
        raise CapabilityError(f"{venv} has no bin/python; it is not a python environment")
    return p


def surface(venv: str | Path) -> dict[str, Any]:
    """The whole capability surface of one installed serving build."""
    py = _venv_python(venv)
    r = subprocess.run([str(py), "-c", _PROBE], capture_output=True, text=True, timeout=300)
    if r.returncode != 0:
        raise CapabilityError(f"probing {venv} failed rc={r.returncode}: "
                              f"{r.stderr.strip()[-300:]}")
    try:
        d = json.loads(r.stdout.strip().splitlines()[-1])
    except Exception as e:
        raise CapabilityError(f"probing {venv} produced unreadable output: {e}")
    if "error" in d:
        raise CapabilityError(f"{venv}: {d['error']}")
    d["venv"] = str(venv)
    d["counts"] = {"architectures": len(d.get("architectures") or []),
                   "quantization": len(d.get("quantization") or []),
                   "features_present": sum(1 for v in (d.get("features") or {}).values()
                                          if isinstance(v, dict) and v["present"])}
    d["read_how"] = ("asked of the installed package in its own interpreter, not read from a "
                     "document — a capability list is correct only for the version it was "
                     "written against")
    d["parsers"] = {"where": "symonprobe /api/symonprobe/parsers",
                    "why_not_here": "the same build's parser names, already read there; asking "
                                    "twice in two components is how two answers disagree"}
    return d


def serves(venv: str | Path, model_dir: str | Path) -> dict[str, Any]:
    """Can this build serve this checkpoint? The question that precedes a serving decision.

    Both halves are checkable: the architecture is in the registry or it is not, and the
    quantization method is in the list or it is not. Where a checkpoint declares neither, that
    is reported as unknown rather than as a pass — a checkpoint that says nothing about itself
    has not been approved by silence.
    """
    cap = surface(venv)
    cfg_path = Path(model_dir) / "config.json"
    if not cfg_path.is_file():
        raise CapabilityError(f"{model_dir} has no config.json; what it needs cannot be read")
    try:
        cfg = json.loads(cfg_path.read_text())
    except Exception as e:
        raise CapabilityError(f"{cfg_path} is not readable json: {e}")

    archs = cfg.get("architectures") or []
    supported = cap.get("architectures") or []
    arch_ok = [a for a in archs if a in supported]
    arch_missing = [a for a in archs if a not in supported]

    q = (cfg.get("quantization_config") or {}).get("quant_method")
    methods = cap.get("quantization") or []
    q_ok = None if q is None else (q in methods)

    reasons = []
    if not archs:
        reasons.append("the checkpoint declares no architecture, so this cannot be answered "
                       "from its config")
    if arch_missing:
        reasons.append(f"{', '.join(arch_missing)} is not in this build's registry of "
                       f"{len(supported)} architectures")
    if q_ok is False:
        reasons.append(f"quantization {q!r} is not among this build's {len(methods)} methods")

    verdict = None
    if archs and not arch_missing and q_ok is not False:
        verdict = True
    elif arch_missing or q_ok is False:
        verdict = False

    return {
        "venv": str(venv), "model_dir": str(model_dir),
        "runtime": cap.get("runtime"), "version": cap.get("version"),
        "architectures_declared": archs, "architectures_supported": arch_ok,
        "architectures_unsupported": arch_missing,
        "quantization_declared": q, "quantization_supported": q_ok,
        "serves": verdict,
        "why": ("; ".join(reasons) if reasons else
                f"every declared architecture is in this build's registry"
                + (f" and {q} is among its quantization methods" if q else
                   " and the checkpoint declares no quantization")),
        "not_checked": ["whether it FITS the card, which is memory and belongs to ravencalc "
                        "and symonprobe", "whether the weights are intact, which belongs to "
                        "model-store"],
    }


# ============================================================================================
# §3.1b-iii — what this unit invokes, against what the estate recorded it should be
# ============================================================================================
# Everything above runs a python interpreter this estate did not build, imports a vLLM and a
# torch this estate did not write, and reports what they can do. Invoking them is allowed and
# is what keeps their licences out of our artifacts. Invoking them BLIND is not: every number
# `surface()` returns is a property of a SPECIFIC vLLM, and the day that vLLM moves underneath
# us every one of those numbers changes with nothing in the estate to say so.
#
# So this asks the same build what version it carries and compares that to the pin in
# SymonSaySource. It re-uses `surface()` rather than starting a second interpreter: the version
# that governs is the one belonging to the build that answered the capability question, and
# asking a different process would assert against something other than what was measured.
#
# WHY THIS LIVES HERE AND NOT IN ITS OWN MODULE
# It was written as `pins.py` first. `no-divergent-copy` refused every commit in the estate for
# it — the gate compares by BASENAME across all four trees, and a second component carrying the
# same obvious filename is exactly the divergence it exists to catch. Every unit in this estate
# already keeps its pin comparison inside its own uniquely named domain module (board.py,
# toolchains.py, imager.py), and no component imports another. Following that is what this is.
#
# DRIFT IS PRESERVED, NOT RESOLVED
# A pin records the INTENDED reproducible revision; a checkout records the OBSERVED one. Where
# they disagree, neither is edited to match the other — provenance settles that. KNOWN_DRIFT
# carries the disagreement, dated, so a NEW movement fails a test while a recorded one does
# not. A permanently red suite is one nobody reads; a green one over unrecorded drift is the
# blind invocation this rule forbids.

PIN_ROOT = os.environ.get("SYM_PIN_ROOT", "/mnt/SymonSaySource")

_VERSION_RE = re.compile(r"\d+(?:\.\d+)+")

# What `surface()` reads a version of, and the component SymonSaySource pins it under.
# `pin: None` is a program with NO pin. It is listed rather than omitted: an omitted program
# reads as one with nothing to check, which is the exact impression §3.1b-iii forbids.
INVOKED: tuple[dict[str, Any], ...] = (
    {"program": "vllm", "reads": "version",
     "where": "capability._PROBE — vllm.__version__, and every architecture, quantization "
              "method and feature flag surface() reports",
     "pin": "vllm",
     "pin_note": "pinned at SymonSaySource/llm/pins/vllm.json. This is the version that "
                 "decides the whole answer: the 367 architectures and 31 quantization "
                 "methods are properties of one vLLM, not of vLLM."},
    {"program": "torch", "reads": "version",
     "where": "capability._PROBE — torch.__version__, torch.version.cuda and the compiled "
              "arch_list that serves() reasons about",
     "pin": "pytorch",
     "pin_note": "pinned at SymonSaySource/common/pins/pytorch.json. A second pin, "
                 "adaptive-fabric/pins/torch-2.11.x.json, records a 2.11.x line as "
                 "UNRESOLVED; it names no version, so it cannot be compared against and is "
                 "not used here."},
    {"program": "python", "reads": "interpreter",
     "where": "capability.surface() — the venv interpreter the probe is run in, invoked as an "
              "argument vector",
     "pin": None,
     "pin_note": "GAP: SymonSaySource has no pin for CPython. The estate builds against an "
                 "interpreter whose version nothing records, and the probe's own results "
                 "depend on it — importlib.util.find_spec semantics are interpreter "
                 "behaviour. Closed by a cpython pin under SymonSaySource."},
)

# Drift measured on disk on 2026-09-20 and PRESERVED. Each key is
# (program, normalised pin, normalised observed); the value says when and why it is carried.
# Nothing here was resolved by editing a pin or moving a checkout — see the §3.1b-iii banner above.
KNOWN_DRIFT: dict[tuple[str, str, str], str] = {
    ("vllm", "0.29.0", "0.27.1"):
        "2026-09-20: the pin records v0.29.0; ~/.venvs/vllm-0271-cu130, which is this unit's "
        "DEFAULT_VENV, carries 0.27.1. The pin is the intended reproducible revision and the "
        "venv is the observed one. Preserved, not reconciled: provenance decides which moves, "
        "and this unit's job is to make the disagreement visible rather than to pick a side.",
    ("vllm", "0.29.0", "0.25.1"):
        "2026-09-20: ~/.venvs/vllm carries 0.25.1 against the same v0.29.0 pin — an older "
        "environment than the default one, kept and therefore recorded.",
    ("torch", "2.14.0", "2.13.0"):
        "2026-09-20: the pin records v2.14.0; ~/.venvs/vllm-0271-cu130 carries 2.13.0+cu130. "
        "The local +cu130 suffix is a build tag, not a release, and is not what differs here.",
    ("torch", "2.14.0", "2.11.0"):
        "2026-09-20: ~/.venvs/vllm carries 2.11.0+cu130 against the same v2.14.0 pin. This is "
        "the line adaptive-fabric/pins/torch-2.11.x.json was opened for and left UNRESOLVED.",
}


def _norm(v: str) -> str:
    """A version reduced to its dotted numeric core, so `v0.29.0`, `0.29.0+cu130` and
    `0.29.0.dev1` compare as one release. Empty when there is no number, which is reported as
    unreadable rather than as disagreement — those are different facts."""
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
    except CapabilityError as e:
        return f"could not run: {e}"
    try:
        r = subprocess.run([str(py), "--version"], capture_output=True, text=True,
                           timeout=30, stdin=subprocess.DEVNULL, check=False)
    except Exception as e:
        return f"could not run: {e}"
    if r.returncode != 0:
        return f"exited {r.returncode}"
    return ((r.stdout or "") + (r.stderr or "")).strip().splitlines()[0] if (r.stdout or r.stderr) else ""


def _classify(program: str, want: str, observed: str, pin: dict[str, Any] | None,
              note: str) -> tuple[str, str]:
    wanted = _norm(want)
    if pin is None:
        return "NO-PIN", note
    if not wanted or want.upper().startswith("UNRESOLVED"):
        return "UNRESOLVED-PIN", f"the pin records {want!r}, which names no version to compare"
    if not observed:
        return "UNREADABLE", "the build did not report a version for this"
    if observed == wanted:
        return "MATCHES", f"reports {observed}, which is what {pin['pin_file']} records"
    if (program, wanted, observed) in KNOWN_DRIFT:
        return "DRIFT-RECORDED", KNOWN_DRIFT[(program, wanted, observed)]
    return "DRIFT-NEW", (f"the pin records {want!r} and this build carries {observed!r}. That "
                         f"movement is in no KNOWN_DRIFT entry, so it happened after the last "
                         f"time anyone looked at this.")


def pinned(venv: str | Path) -> dict[str, Any]:
    """Does what this build actually carries agree with what SymonSaySource recorded?

    Per-venv, deliberately. The two vLLM environments on this host disagree with each other, so
    a single module-level answer would be true of one of them and quietly wrong about the
    other — and `surface()` is per-venv for the same reason.
    """
    cap = surface(venv)
    pins = _pins()
    observed_of = {"vllm": cap.get("version") or "",
                   "torch": cap.get("torch") or "",
                   "python": _interpreter_version(venv)}

    rows, states = [], {}
    for spec in INVOKED:
        program = spec["program"]
        reported = observed_of.get(program, "")
        observed = _norm(reported)
        pin = pins.get((spec["pin"] or "").lower()) if spec["pin"] else None
        want = str(pin.get("intended_tag_version") or "") if pin else ""
        state, why = _classify(program, want, observed, pin, spec["pin_note"])
        rows.append({"program": program, "where": spec["where"], "reads": spec["reads"],
                     "reports": reported, "observed": observed,
                     "pin": spec["pin"], "pin_file": pin.get("pin_file") if pin else None,
                     "pinned": want or None, "state": state, "why": why,
                     "pin_note": spec["pin_note"]})
        states.setdefault(state, []).append(program)

    return {"venv": str(venv), "runtime": cap.get("runtime"), "pin_root": PIN_ROOT,
            "pins_available": len(pins), "count": len(rows), "programs": rows,
            "by_state": {k: sorted(v) for k, v in states.items()},
            "unpinned": sorted(states.get("NO-PIN", [])),
            "recorded_drift": sorted(states.get("DRIFT-RECORDED", [])),
            "new_drift": sorted(states.get("DRIFT-NEW", [])),
            "why": ("every version this build carries agrees with its pin"
                    if set(states) <= {"MATCHES"} else
                    "; ".join(f"{k}: {', '.join(sorted(v))}" for k, v in sorted(states.items()))),
            "drift_policy": ("a pin records the INTENDED reproducible revision and a checkout "
                             "the OBSERVED one. Where they disagree the disagreement is "
                             "preserved and dated in KNOWN_DRIFT, never resolved by editing "
                             "the pin or moving the checkout — provenance decides that. What "
                             "this asserts is that no version moved WITHOUT being recorded.")}
