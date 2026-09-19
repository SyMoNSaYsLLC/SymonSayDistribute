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
