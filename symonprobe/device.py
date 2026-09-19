# SPDX-License-Identifier: LicenseRef-SymonSaysLLC-Proprietary-1.0
# Copyright 2026 SymonSaysLLC
# SyMoNsAyLeaRn — SyMoNeuRaL, a subdivision of SymonSaysLLC. Terms: see LICENSE.
"""The card, and whether a build can actually run on it.

THE CONFUSION THIS EXISTS TO END
--------------------------------
On 2026-09-19 a venv named `vllm-0271-cu130` was read as saying the GPU was CUDA 13.0 when the
card was believed to be "120". Both numbers were right and they are different things:

    compute capability   12.0  (sm_120)   a property of the SILICON. Fixed. The RTX 5070 Ti.
    CUDA toolkit         13.0  (cu130)    a property of the BUILD. Chosen when torch was built.

Neither is the other, neither implies the other, and reading one as the other is how a build
gets blamed for a card's limit or a card for a build's. So this module always reports both,
always labelled, and answers the only question that actually matters:

    does the build's compiled arch list contain this device's compute capability?

If it does not, the build cannot run here no matter how new either number is. That is a
different failure from "out of memory" and it deserves a different answer.

Read-only: it queries the device and imports nothing from the model being served.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any


class ProbeError(Exception):
    """A probe that could not be completed, carrying why. Never a silent empty result."""


def _nvidia_smi(fields: str) -> list[list[str]]:
    exe = "/usr/bin/nvidia-smi"
    if not Path(exe).exists():
        raise ProbeError("no nvidia-smi on this host; there is no NVIDIA device to describe")
    r = subprocess.run([exe, f"--query-gpu={fields}", "--format=csv,noheader,nounits"],
                       capture_output=True, text=True, timeout=20)
    if r.returncode != 0:
        raise ProbeError(f"nvidia-smi rc={r.returncode}: {r.stderr.strip()[:200]}")
    return [[c.strip() for c in line.split(",")] for line in r.stdout.strip().splitlines() if line.strip()]


def devices() -> list[dict[str, Any]]:
    """Every NVIDIA device, with its compute capability labelled as such."""
    rows = _nvidia_smi("index,name,compute_cap,driver_version,memory.total,memory.free")
    out = []
    for idx, name, cap, drv, total, free in rows:
        out.append({
            "index": int(idx), "name": name,
            "compute_capability": cap,
            "compute_capability_arch": "sm_" + cap.replace(".", ""),
            "compute_capability_is": "a property of the silicon, fixed — NOT a CUDA version",
            "driver_version": drv,
            "memory_total_mib": int(total), "memory_free_mib": int(free),
            "memory_total_gib": round(int(total) / 1024, 2),
        })
    return out


def _venv_python(venv: str | Path) -> Path:
    p = Path(venv) / "bin" / "python"
    if not p.exists():
        raise ProbeError(f"{venv} has no bin/python; it is not a python environment")
    return p


_PROBE = r'''
import json
out = {}
try:
    import torch
    out["torch"] = torch.__version__
    out["cuda_built_against"] = torch.version.cuda
    out["arch_list"] = list(torch.cuda.get_arch_list())
    out["cuda_available"] = bool(torch.cuda.is_available())
    if out["cuda_available"]:
        maj, mnr = torch.cuda.get_device_capability(0)
        out["device_capability"] = f"{maj}.{mnr}"
        out["device_name"] = torch.cuda.get_device_name(0)
except Exception as e:
    out["error"] = f"{type(e).__name__}: {e}"
print(json.dumps(out))
'''


def build(venv: str | Path) -> dict[str, Any]:
    """What a python environment was BUILT against — versions, CUDA, compiled architectures."""
    py = _venv_python(venv)
    r = subprocess.run([str(py), "-c", _PROBE], capture_output=True, text=True, timeout=180)
    if r.returncode != 0:
        raise ProbeError(f"probing {venv} failed rc={r.returncode}: {r.stderr.strip()[-300:]}")
    try:
        d = json.loads(r.stdout.strip().splitlines()[-1])
    except Exception as e:
        raise ProbeError(f"probing {venv} produced unreadable output: {e}")
    d["venv"] = str(venv)
    d["cuda_built_against_is"] = "a property of the build, chosen — NOT the card's capability"
    return d


def fit(venv: str | Path, index: int = 0) -> dict[str, Any]:
    """Can this build run on this card? The one question worth asking, answered plainly.

    A name like `cu130` says nothing about whether the card is supported. The compiled arch
    list does, and it is the only thing that does.
    """
    b = build(venv)
    devs = devices()
    dev = next((d for d in devs if d["index"] == index), None)
    if dev is None:
        raise ProbeError(f"no device at index {index}; this host has {len(devs)}")
    arch = dev["compute_capability_arch"]
    archs = b.get("arch_list") or []
    supported = arch in archs
    return {
        "device": dev["name"],
        "device_compute_capability": dev["compute_capability"],
        "device_arch": arch,
        "build_cuda_toolkit": b.get("cuda_built_against"),
        "build_arch_list": archs,
        "runs_here": supported,
        "why": (f"the build carries {arch}, which is this card's compute capability, so it runs"
                if supported else
                f"the build carries {archs or 'no architectures'} and this card is {arch}; "
                f"it cannot run here regardless of the CUDA version in the name"),
        "these_are_not_the_same_number": {
            "compute_capability": dev["compute_capability"],
            "cuda_toolkit": b.get("cuda_built_against"),
            "note": "silicon versus build. Neither implies the other.",
        },
    }
